"""seed_aliases_catalogue: backfill product_aliases depuis catalogue_labels.

Revision ID: 0004_seed_aliases_catalogue
Revises: 0003_ocr_feedback_loop
Create Date: 2026-07-04

id court : alembic_version.version_num = VARCHAR(32) ; id plus long -> tronque ->
bump echoue et rollback toute la migration.

Alimente product_aliases (vide) depuis catalogue_labels (worker catalogue, Gemini
vision sur images Open Prices). Choix :
- raw_text = libelle_original brut ; la normalisation est au matcher, pas stockee ici.
- source='catalogue' : PK (raw_text, enseigne, source) cohabite avec user-validation
  sans ecraser ; arbitrage au lookup.
- confidence=0.7 = plancher du filtre worker, pas verite terrain -> validated_by_user=false.
- paires ambigues ecartees (~174 libelles -> plusieurs EAN) : on n'importe que les
  1-EAN pour ne pas fabriquer de fausse certitude.

Effet : ~7924 INSERT. Additif, reversible. Lit catalogue_labels/catalogue_products
(crees hors Alembic par le worker catalogue) : doivent exister au upgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_seed_aliases_catalogue"
down_revision: str | Sequence[str] | None = "0003_ocr_feedback_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INSERT_SQL = """
INSERT INTO product_aliases
    (raw_text, enseigne, source, ean, produit_nom, confidence, validated_by_user)
SELECT DISTINCT
    left(l.libelle_original, 300)        AS raw_text,          -- brut, no-op (max observé = 71)
    coalesce(l.enseigne, '')             AS enseigne,
    'catalogue'                          AS source,
    l.ean                                AS ean,
    left(coalesce(cp.nom, ''), 300)      AS produit_nom,
    0.7                                  AS confidence,
    false                                AS validated_by_user
FROM catalogue_labels l
JOIN (
    -- Paires (libellé, enseigne) qui mappent vers UN SEUL ean (non-ambiguës).
    SELECT libelle_original, coalesce(enseigne, '') AS ens
    FROM catalogue_labels
    WHERE ean ~ '^[0-9]{8,13}$'
      AND btrim(libelle_original) <> ''
    GROUP BY libelle_original, coalesce(enseigne, '')
    HAVING count(DISTINCT ean) = 1
) keep
    ON keep.libelle_original = l.libelle_original
   AND keep.ens = coalesce(l.enseigne, '')
LEFT JOIN catalogue_products cp ON cp.ean = l.ean
WHERE l.ean ~ '^[0-9]{8,13}$'
  AND btrim(l.libelle_original) <> ''
ON CONFLICT ON CONSTRAINT product_aliases_pk DO NOTHING;
"""

_DELETE_SQL = "DELETE FROM product_aliases WHERE source = 'catalogue';"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_INSERT_SQL))
    # Cloud SQL injoignable en local : on logge le decompte, lisible dans les logs du Job
    n = bind.execute(
        sa.text("SELECT count(*) FROM product_aliases WHERE source = 'catalogue'")
    ).scalar()
    print(f"[0004] product_aliases seeded: {n} lignes source='catalogue'", flush=True)


def downgrade() -> None:
    op.execute(_DELETE_SQL)
