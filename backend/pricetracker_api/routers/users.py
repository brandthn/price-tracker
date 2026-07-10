"""Router users — /me + /me/preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, verify_bearer
from ..db import get_session
from ..models.notification_prefs import NotificationPrefs
from ..schemas.recommendations import (
    RecommendationItem,
    RecommendationsOut,
    RecoProductRef,
)
from ..schemas.users import (
    BasketMonth,
    BasketProduct,
    BasketSummaryOut,
    NotificationPrefsOut,
    NotificationPrefsPatch,
    UserOut,
    UserPatch,
)
from ..services.user_provisioning import get_or_create_user

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    db_user = await get_or_create_user(session, user)
    return UserOut.model_validate(db_user)


@router.patch("/me", response_model=UserOut)
async def patch_me(
    body: UserPatch,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    db_user = await get_or_create_user(session, user)
    if body.display_name is not None:
        db_user.display_name = body.display_name
    if body.departement is not None:
        # Validation minimale : 2 ou 3 chars (FR métropole + DOM).
        dept = body.departement.upper()
        if len(dept) not in (2, 3):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Invalid département code.",
            )
        db_user.departement = dept
    await session.commit()
    await session.refresh(db_user)
    return UserOut.model_validate(db_user)


@router.get("/me/basket", response_model=BasketSummaryOut)
async def get_my_basket(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> BasketSummaryOut:
    """Panier réel de l'utilisateur, agrégé depuis ses tickets (Cloud SQL).

    C'est la source de vérité de la vue « Mon budget » : dépenses mensuelles,
    panier moyen, produits récurrents. La date de référence d'un ticket est
    `date_ticket` (lue sur le ticket) avec repli sur `created_at` quand
    l'extraction n'a pas trouvé de date.
    """
    db_user = await get_or_create_user(session, user)
    uid = {"uid": db_user.id}

    summary = (
        await session.execute(
            text(
                """
                SELECT
                  COUNT(*) AS tickets_count,
                  SUM(total_eur) AS total_spent_eur,
                  AVG(total_eur) AS avg_ticket_eur,
                  MIN(COALESCE(date_ticket, created_at::date)) AS first_ticket_date
                FROM tickets
                WHERE user_id = :uid
                """
            ),
            uid,
        )
    ).mappings().one()

    monthly_rows = (
        await session.execute(
            text(
                """
                SELECT
                  date_trunc('month', COALESCE(date_ticket, created_at::date))::date AS month,
                  SUM(total_eur) AS total_eur,
                  COUNT(*) AS tickets
                FROM tickets
                WHERE user_id = :uid AND total_eur IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """
            ),
            uid,
        )
    ).mappings().all()

    # Produits récurrents : groupés par EAN quand il est résolu, sinon par
    # libellé normalisé — un même produit mal OCRisé ne compte qu'une fois.
    top_rows = (
        await session.execute(
            text(
                """
                SELECT
                  MIN(p.ean) AS ean,
                  MIN(COALESCE(p.produit_nom, p.raw_text)) AS label,
                  COUNT(*) AS purchases,
                  AVG(p.price_eur) AS avg_price_eur,
                  MAX(COALESCE(t.date_ticket, t.created_at::date)) AS last_purchased
                FROM prix_extraits p
                JOIN tickets t ON t.id = p.ticket_id
                WHERE t.user_id = :uid
                GROUP BY COALESCE(p.ean, lower(COALESCE(p.produit_nom, p.raw_text)))
                ORDER BY COUNT(*) DESC,
                         MAX(COALESCE(t.date_ticket, t.created_at::date)) DESC
                LIMIT 8
                """
            ),
            uid,
        )
    ).mappings().all()

    return BasketSummaryOut(
        tickets_count=int(summary["tickets_count"] or 0),
        total_spent_eur=(
            float(summary["total_spent_eur"]) if summary["total_spent_eur"] is not None else None
        ),
        avg_ticket_eur=(
            float(summary["avg_ticket_eur"]) if summary["avg_ticket_eur"] is not None else None
        ),
        first_ticket_date=summary["first_ticket_date"],
        monthly=[
            BasketMonth(
                month=r["month"],
                total_eur=float(r["total_eur"]),
                tickets=int(r["tickets"]),
            )
            for r in monthly_rows
        ],
        top_products=[
            BasketProduct(
                ean=r["ean"],
                label=r["label"],
                purchases=int(r["purchases"]),
                avg_price_eur=(
                    float(r["avg_price_eur"]) if r["avg_price_eur"] is not None else None
                ),
                last_purchased=r["last_purchased"],
            )
            for r in top_rows
        ],
    )


# Reco « substitut moins cher » (Étape 3). Join local Cloud SQL :
#   panier live (prix_extraits x tickets, EAN résolu, fenêtre 6 mois)
#     x product_substitutions (cache précalculé, tier ≤ max_tier)
#     x products (x2 : noms/marques/images + quantity_value du source).
# On garde LE meilleur substitut par produit du panier (tier asc, score desc),
# et on calcule l'économie mensuelle en euros réels :
#   monthly_saving = saving_per_unit [€/unité] x source.quantity_value [unité/pack]
#                    x (packs_6m / 6) [packs/mois].
# Tri final par économie mensuelle desc. Tout est en €/unité — jamais le prix paquet.
_RECOMMENDATIONS_SQL = text(
    """
    WITH basket AS (
        SELECT
            pe.ean AS ean,
            SUM(COALESCE(pe.quantity, 1)) AS packs_6m
        FROM prix_extraits pe
        JOIN tickets t ON t.id = pe.ticket_id
        WHERE t.user_id = :uid
          AND pe.ean IS NOT NULL
          AND COALESCE(t.date_ticket, t.created_at::date)
              >= CURRENT_DATE - INTERVAL '6 months'
        GROUP BY pe.ean
        HAVING SUM(COALESCE(pe.quantity, 1)) >= :min_purchases
    ),
    ranked AS (
        SELECT
            s.source_ean, s.target_ean, s.tier, s.score, s.quantity_unit,
            s.source_price_per_unit, s.target_price_per_unit,
            s.saving_per_unit, s.saving_pct, b.packs_6m,
            ROW_NUMBER() OVER (
                PARTITION BY s.source_ean
                ORDER BY s.tier ASC, s.score DESC, s.saving_pct DESC
            ) AS rn
        FROM product_substitutions s
        JOIN basket b ON b.ean = s.source_ean
        WHERE s.tier <= :max_tier
    )
    SELECT
        r.source_ean, r.target_ean, r.tier,
        r.score::float8                 AS score,
        r.quantity_unit,
        r.source_price_per_unit::float8 AS source_ppu,
        r.target_price_per_unit::float8 AS target_ppu,
        r.saving_per_unit::float8       AS saving_per_unit,
        r.saving_pct::float8            AS saving_pct,
        r.packs_6m::float8              AS packs_6m,
        src.name AS source_name, src.brand AS source_brand, src.image_url AS source_image_url,
        tgt.name AS target_name, tgt.brand AS target_brand, tgt.image_url AS target_image_url,
        (r.saving_per_unit * src.quantity_value * (r.packs_6m / 6.0))::float8
            AS monthly_saving_eur
    FROM ranked r
    JOIN products src ON src.ean = r.source_ean
    JOIN products tgt ON tgt.ean = r.target_ean
    WHERE r.rn = 1
      AND src.quantity_value IS NOT NULL
    ORDER BY monthly_saving_eur DESC NULLS LAST
    LIMIT :limit
    """
)


def _row_to_reco(r: dict) -> RecommendationItem:
    """Map une row SQL → RecommendationItem. `saving_pct` est stocké en fraction
    (0-1) → exposé en pourcentage (x100), cohérent avec `pct_change_window`."""
    return RecommendationItem(
        source=RecoProductRef(
            ean=r["source_ean"],
            name=r["source_name"],
            brand=r["source_brand"],
            image_url=r["source_image_url"],
            price_per_unit=round(r["source_ppu"], 4),
        ),
        target=RecoProductRef(
            ean=r["target_ean"],
            name=r["target_name"],
            brand=r["target_brand"],
            image_url=r["target_image_url"],
            price_per_unit=round(r["target_ppu"], 4),
        ),
        unit=r["quantity_unit"],
        tier=int(r["tier"]),
        score=round(r["score"], 4),
        saving_per_unit=round(r["saving_per_unit"], 4),
        saving_pct=round(r["saving_pct"] * 100.0, 1),
        monthly_packs=round(r["packs_6m"] / 6.0, 2),
        monthly_saving_eur=round(r["monthly_saving_eur"], 2),
    )


@router.get("/me/recommendations", response_model=RecommendationsOut)
async def get_my_recommendations(
    limit: int = Query(default=20, ge=1, le=100),
    max_tier: int = Query(
        default=2, ge=1, le=3, description="Tier max exposé (2 = exclut l'élargi, cf. DoD)."
    ),
    min_purchases: int = Query(
        default=1, ge=1, le=50, description="Paquets cumulés min sur 6 mois pour retenir un produit."
    ),
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> RecommendationsOut:
    """Recommandations d'économies : pour chaque produit récurrent du panier,
    le meilleur substitut moins cher au €/unité, avec l'économie mensuelle.

    Panier = agrégation live des tickets de l'utilisateur (mêmes données que
    `/me/basket`). `user_basket_history` (pré-agrégé par le worker indices)
    reste un cache futur, non requis ici.

    Panier vide ou aucun substitut moins cher → `200` avec `items=[]` : c'est
    l'état d'onboarding « ajoutez un ticket », pas une erreur.
    """
    db_user = await get_or_create_user(session, user)
    rows = (
        await session.execute(
            _RECOMMENDATIONS_SQL,
            {
                "uid": db_user.id,
                "max_tier": max_tier,
                "min_purchases": min_purchases,
                "limit": limit,
            },
        )
    ).mappings().all()

    items = [_row_to_reco(dict(r)) for r in rows]
    total = round(sum(i.monthly_saving_eur for i in items), 2)
    return RecommendationsOut(items=items, total_monthly_saving_eur=total, count=len(items))


@router.get("/me/preferences", response_model=NotificationPrefsOut)
async def get_prefs(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> NotificationPrefsOut:
    db_user = await get_or_create_user(session, user)
    prefs = await session.get(NotificationPrefs, db_user.id)
    if prefs is None:
        # Renvoie un payload de défauts plutôt que 404 : la ligne sera créée
        # au premier PATCH. C'est plus utile pour le frontend qui peut
        # afficher les défauts sans avoir à gérer le 404.
        return NotificationPrefsOut(
            threshold_pct=5.0,
            frequency="weekly",
            favorite_enseignes=None,
            fcm_token=None,
        )
    return NotificationPrefsOut.model_validate(prefs)


@router.patch("/me/preferences", response_model=NotificationPrefsOut)
async def patch_prefs(
    body: NotificationPrefsPatch,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> NotificationPrefsOut:
    db_user = await get_or_create_user(session, user)
    patch_values: dict[str, object] = {}
    if body.threshold_pct is not None:
        patch_values["threshold_pct"] = body.threshold_pct
    if body.frequency is not None:
        patch_values["frequency"] = body.frequency
    if body.favorite_enseignes is not None:
        patch_values["favorite_enseignes"] = body.favorite_enseignes
    if body.fcm_token is not None:
        patch_values["fcm_token"] = body.fcm_token

    insert_values = {"user_id": db_user.id, **patch_values}
    stmt = pg_insert(NotificationPrefs).values(**insert_values)
    if patch_values:
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"], set_=patch_values
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id"])
    await session.execute(stmt)
    await session.commit()

    prefs = await session.get(NotificationPrefs, db_user.id)
    assert prefs is not None
    return NotificationPrefsOut.model_validate(prefs)
