"""seed_aliases_catalogue: backfill product_aliases depuis catalogue_labels.

Revision ID: 0004_seed_aliases_catalogue
Revises: 0003_ocr_feedback_loop
Create Date: 2026-07-04

NB id COURT : `alembic_version.version_num` est VARCHAR(32). Un revision id plus long
est tronqué → le bump de version échoue et rollback TOUTE la migration (le seed inclus).

But : alimenter `product_aliases` (vide) avec le corpus (libellé-ticket, enseigne) → EAN
produit par le worker `catalogue` (Gemini vision sur les images Open Prices), stocké
dans `catalogue_labels`. C'est le premier corpus d'alias exploitable par un futur
matcher OCR — aujourd'hui l'OCR ne résout aucun EAN.

Décisions (et leur raison) :

  raw_text = libelle_original          → on garde le libellé BRUT tel qu'écrit sur le
                                          ticket. La normalisation n'est PAS stockée ici :
                                          c'est une responsabilité du matcher (une seule
                                          fonction, appliquée symétriquement au match).
                                          On IGNORE volontairement catalogue_labels.
                                          libelle_normalise (normaliseur étranger, lossy).

  source   = 'catalogue'               → source dédiée. La PK (raw_text, enseigne, source)
                                          fait cohabiter ces alias avec ceux de la
                                          validation utilisateur ('user-validation') sans
                                          jamais les écraser. L'arbitrage se fait au lookup.

  confidence = 0.7                     → PLANCHER du filtre worker (il ne garde que les
                                          matchs >= 0.7). La vraie confiance par ligne
                                          n'est pas persistée par le worker. Ce ne sont
                                          PAS des vérités terrain → validated_by_user=false.

  Clés AMBIGUËS écartées               → ~174 paires (libellé, enseigne) pointent vers
                                          plusieurs EAN (libellés génériques abrégés par
                                          la caisse, ex. "LINDT EXCELLENCE NOI"). La PK
                                          n'autorise qu'un EAN par paire ; en choisir un
                                          fabriquerait une fausse certitude. On n'importe
                                          QUE les paires non-ambiguës (1 seul EAN).
                                          Le job catalogue reste intact (rien n'est supprimé
                                          côté catalogue_labels).

Effet attendu : ~7924 INSERT (= 8098 paires distinctes − 174 ambiguës). Confirmer avec
la pré-vérif du runbook AVANT d'appliquer. Purement additif, réversible par downgrade.

NB : lit catalogue_labels / catalogue_products, tables créées hors Alembic par le worker
catalogue (CREATE TABLE IF NOT EXISTS). Elles doivent exister au moment du upgrade.
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
    # Cloud SQL est injoignable en local : on logge le décompte pour vérifier
    # directement dans les logs du Cloud Run Job (pas de requête locale possible).
    n = bind.execute(
        sa.text("SELECT count(*) FROM product_aliases WHERE source = 'catalogue'")
    ).scalar()
    print(f"[0004] product_aliases seeded: {n} lignes source='catalogue'", flush=True)


def downgrade() -> None:
    # Réversible exactement : on retire uniquement ce que cette migration a inséré.
    op.execute(_DELETE_SQL)
