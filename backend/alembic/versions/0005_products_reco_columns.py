"""products: socle reco substituts — quantité normalisée + chemin de catégories OFF.

Revision ID: 0005_products_reco_columns
Revises: 0004_seed_aliases_catalogue
Create Date: 2026-07-06

⚠️ id volontairement COURT : `alembic_version.version_num` = VARCHAR(32).

Ajoute à `products` (table PARTAGÉE avec le worker OFF) les colonnes OFF
aujourd'hui JETÉES mais nécessaires à la reco de substituts :

  Socle UNITÉ (Étape 1) — comparer au €/kg / €/L :
  - quantity_raw   : texte OFF `quantity` brut (« 500 g ») — affichage/audit,
                     JAMAIS utilisé pour le calcul (pas de regex, §5.2 handoff) ;
  - quantity_value : valeur numérique en unité canonique (NUMERIC) ;
  - quantity_unit  : 'kg' | 'L' (dérivé de product_quantity_unit : g→kg, ml→L).

  Socle CATÉGORIE (Étape 2) — tiers de confiance par préfixe commun :
  - categories_tags : chemin OFF COMPLET ordonné (général → spécifique), ex.
                      {en:foods, en:spreads, en:sweet-spreads, en:hazelnut-spreads}.
                      Aujourd'hui seuls les 3 slices positionnels category_l1/l2/l3
                      sont gardés — insuffisant : le tier « catégorie » (§4) se
                      calcule sur la PROFONDEUR du préfixe commun entre deux
                      chemins, ce qui exige le chemin entier.

quantity_value/quantity_unit NULL = pas d'unité propre = exclu du €/unité
(couverture ≈ 86,5 %, vérifiée). categories_tags NULL possible (couverture ≈ 92,8 %).

`ADD COLUMN IF NOT EXISTS` (idempotent) : `products` peut être bootstrappée par le
worker OFF ; on ne casse pas si une colonne existe déjà. Aligné avec le DDL
embarqué côté worker (workers/off/pricetracker_off/pg.py).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_products_reco_columns"
down_revision: str | Sequence[str] | None = "0004_seed_aliases_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity_raw varchar(100)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity_value numeric(12, 6)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity_unit varchar(8)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS categories_tags text[]")


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS categories_tags")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quantity_unit")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quantity_value")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quantity_raw")
