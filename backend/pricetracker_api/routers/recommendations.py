"""Router /recommendations — endpoints de recommandation produit et utilisateur.

Deux endpoints publics (pas de Bearer requis, aligné sur /products/* et
/observatoire/* qui sont publics dans main.py) :

  GET /recommendations/product/{ean}
    → Top 3 alternatives moins chères au produit demandé.
    → Source : table `product_substitutions` + vues `product_metrics` /
      `products`.

  GET /recommendations/user/{user_id}
    → Économies potentielles estimées sur 1 mois, basées sur
      `user_basket_history` (agrégation 6 mois, une ligne par EAN par user).
    → Retourne le meilleur substitut par produit distinct du panier.

Toutes les requêtes passent par du SQL brut (`text()`) — les vues
matérialisées `product_prices` et `product_metrics` ne sont pas mappées
en ORM. Même approche que `routers/products.py` pour les requêtes pgvector.

Dépendance DB : `get_session` (AsyncSession scoped à la requête).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..logging import get_logger
from ..schemas.recommendations import (
    ProductAlternative,
    ProductRecommendationsResponse,
    UserProductRecommendation,
    UserRecommendationsResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


# ---------------------------------------------------------------------------
# GET /recommendations/product/{ean}
# ---------------------------------------------------------------------------

_PRODUCT_SUBSTITUTES_SQL = text("""
    SELECT
        ps.target_ean,
        p.name,
        p.brand,
        p.nutriscore,
        p.image_url,
        pm.avg_price,
        ps.saving_avg,
        ps.saving_pct,
        ps.score,
        ps.similarity
    FROM product_substitutions ps
    JOIN products p
        ON p.ean = ps.target_ean
    LEFT JOIN product_metrics pm
        ON pm.ean = ps.target_ean
    WHERE ps.source_ean = :ean
    ORDER BY ps.score DESC
    LIMIT 3
""")

_PRODUCT_SOURCE_SQL = text("""
    SELECT
        p.name,
        pm.avg_price
    FROM products p
    LEFT JOIN product_metrics pm ON pm.ean = p.ean
    WHERE p.ean = :ean
""")


@router.get(
    "/product/{ean}",
    response_model=ProductRecommendationsResponse,
    summary="Top 3 alternatives moins chères à un produit",
)
async def get_product_recommendations(
    ean: str,
    session: AsyncSession = Depends(get_session),
) -> ProductRecommendationsResponse:
    src_row = (await session.execute(_PRODUCT_SOURCE_SQL, {"ean": ean})).mappings().first()
    if src_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Produit {ean} introuvable.",
        )

    rows = (await session.execute(_PRODUCT_SUBSTITUTES_SQL, {"ean": ean})).mappings().all()

    alternatives = [
        ProductAlternative(
            ean=row["target_ean"],
            name=row["name"],
            brand=row["brand"],
            nutriscore=row["nutriscore"],
            image_url=row["image_url"],
            avg_price=float(row["avg_price"]) if row["avg_price"] is not None else None,
            saving_avg=float(row["saving_avg"]) if row["saving_avg"] is not None else None,
            saving_pct=float(row["saving_pct"]) if row["saving_pct"] is not None else None,
            score=float(row["score"]),
            similarity=float(row["similarity"]) if row["similarity"] is not None else None,
        )
        for row in rows
    ]

    logger.info(
        "recommendations_product",
        ean=ean,
        alternatives_count=len(alternatives),
    )

    return ProductRecommendationsResponse(
        source_ean=ean,
        source_name=src_row["name"],
        source_avg_price=float(src_row["avg_price"]) if src_row["avg_price"] is not None else None,
        alternatives=alternatives,
    )


# ---------------------------------------------------------------------------
# GET /recommendations/user/{user_id}
# ---------------------------------------------------------------------------

# user_basket_history est une table agrégée (une ligne par user × ean),
# sans created_at — la fenêtre temporelle est gérée par le worker indices
# qui alimente la table sur 6 mois glissants.
# On récupère toutes les lignes du panier habituel de l'user,
# avec le meilleur substitut par EAN (ORDER BY score DESC, dédoublonné en Python).
_USER_BASKET_SQL = text("""
    SELECT
        ubh.ean                         AS purchased_ean,
        ubh.purchase_count_6m           AS purchase_count_6m,
        p_src.name                      AS purchased_name,
        pm_src.avg_price                AS purchased_avg_price,
        ps.target_ean                   AS alternative_ean,
        p_tgt.name                      AS alternative_name,
        pm_tgt.avg_price                AS alternative_avg_price,
        p_tgt.nutriscore                AS alternative_nutriscore,
        p_tgt.image_url                 AS alternative_image_url,
        ps.saving_avg,
        ps.saving_pct,
        ps.score
    FROM user_basket_history ubh
    JOIN product_substitutions ps
        ON ps.source_ean = ubh.ean
    LEFT JOIN products p_src
        ON p_src.ean = ubh.ean
    LEFT JOIN product_metrics pm_src
        ON pm_src.ean = ubh.ean
    LEFT JOIN products p_tgt
        ON p_tgt.ean = ps.target_ean
    LEFT JOIN product_metrics pm_tgt
        ON pm_tgt.ean = ps.target_ean
    WHERE ubh.user_id = :user_id
    ORDER BY ubh.ean, ps.score DESC
""")


@router.get(
    "/user/{user_id}",
    response_model=UserRecommendationsResponse,
    summary="Économies potentielles estimées sur les produits habituels d'un utilisateur",
)
async def get_user_recommendations(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> UserRecommendationsResponse:
    rows = (
        await session.execute(_USER_BASKET_SQL, {"user_id": str(user_id)})
    ).mappings().all()

    # purchase_count_6m par EAN — utilisé pour estimer l'économie mensuelle
    purchase_counts: dict[str, int] = {}
    for row in rows:
        ean = row["purchased_ean"]
        if ean not in purchase_counts:
            purchase_counts[ean] = row["purchase_count_6m"] or 1

    # Dédoublonner : garder uniquement le meilleur substitut par EAN acheté
    # (ORDER BY ps.score DESC côté SQL garantit que la 1ère occurrence est la meilleure)
    seen: set[str] = set()
    recommendations: list[UserProductRecommendation] = []
    for row in rows:
        ean = row["purchased_ean"]
        if ean in seen:
            continue
        seen.add(ean)
        recommendations.append(
            UserProductRecommendation(
                purchased_ean=ean,
                purchased_name=row["purchased_name"],
                purchased_avg_price=(
                    float(row["purchased_avg_price"])
                    if row["purchased_avg_price"] is not None
                    else None
                ),
                alternative_ean=row["alternative_ean"],
                alternative_name=row["alternative_name"],
                alternative_avg_price=(
                    float(row["alternative_avg_price"])
                    if row["alternative_avg_price"] is not None
                    else None
                ),
                alternative_nutriscore=row["alternative_nutriscore"],
                alternative_image_url=row["alternative_image_url"],
                saving_avg=float(row["saving_avg"]) if row["saving_avg"] is not None else None,
                saving_pct=float(row["saving_pct"]) if row["saving_pct"] is not None else None,
                score=float(row["score"]),
            )
        )

    # Économie mensuelle estimée :
    # saving_avg × (purchase_count_6m / 6) pour ramener à 1 mois
    potential_savings = sum(
        (r.saving_avg or 0.0) * (purchase_counts.get(r.purchased_ean, 1) / 6)
        for r in recommendations
        if r.saving_avg is not None
    )

    logger.info(
        "recommendations_user",
        user_id=str(user_id),
        recommendations_count=len(recommendations),
        potential_monthly_savings=round(potential_savings, 2),
    )

    return UserRecommendationsResponse(
        user_id=str(user_id),
        potential_monthly_savings=round(potential_savings, 2) if potential_savings else None,
        recommendations=sorted(
            recommendations,
            key=lambda r: r.saving_avg or 0.0,
            reverse=True,
        ),
    )