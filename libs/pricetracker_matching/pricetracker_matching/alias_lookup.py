"""Read-only EAN resolution against ``product_aliases``.

**Shared by BOTH OCR workers** (tier-1 ``workers/ocr``, tier-2
``workers/ocr-llm``) — the very same :func:`resolve_line_eans` is called at the
same hook in both, right after ``mapper.map_prix_extraits_rows`` and before the
line rows are persisted. See ``docs/ocr-alias-lookup-handoff.md``.

Design (and the non-negotiables it satisfies):

- **Engine/tier agnostic.** Operates only on ``(raw_text, enseigne)`` canonical
  fields. No branch on OCR engine or tier — it is a post-OCR stage by
  construction.
- **Exact-on-normalised.** :func:`pricetracker_matching.normalize.normalize_label`
  is applied symmetrically to the OCR label and to the stored alias ``raw_text``.
  No normalised form is ever written back.
- **Source arbitrage.** ``user-validation`` (``validated_by_user`` true,
  confidence 1.0) always beats ``catalogue`` (confidence 0.7). A user-validated
  hit clears ``needs_validation``; a catalogue hit fills the EAN but stays
  ``needs_validation=True`` — a suggestion, not an auto-accept.
- **Additive / non-regressive.** A line without a match is left untouched
  (``ean=None``, ``match_method='none'``, ``needs_validation=True``).
- **Best-effort.** A read failure on ``product_aliases`` never blocks ticket
  persistence: it is logged and the lines are left unresolved.
- **Read-only.** Never writes ``product_aliases``. The caller keeps its own
  write shape (tier-1 upsert / tier-2 atomic transaction) — this only fills
  fields on the row dicts in place.

Perf: one query per ticket (enseigne pre-filtered in SQL), matching done in
Python. A functional index on the normalised label / ``pg_trgm`` fuzzy fallback
would need a migration and is intentionally left for later — an exact-match
resolver needs none.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pricetracker_matching.normalize import (
    ENSEIGNE_ACCENT_DST,
    ENSEIGNE_ACCENT_SRC,
    enseigne_candidates,
    normalize_label,
)

logger = logging.getLogger(__name__)

# Vocabulary written to prix_extraits.match_method. The source is folded into
# the method because prix_extraits has no source column, and the source is what
# drives the needs_validation decision. Leaves room for future 'alias-*-fuzzy'
# / 'vector' methods.
MATCH_NONE = "none"
MATCH_ALIAS_USER = "alias-user"
MATCH_ALIAS_CATALOGUE = "alias-catalogue"

_CATALOGUE_FALLBACK_CONFIDENCE = 0.7

# Enseigne pre-filter only — it merely BOUNDS the candidate set; the
# authoritative label match happens in Python. The fold expression is kept in
# lock-step with normalize.enseigne_key, with the accent map passed as $3/$4 so
# there is a single source of truth for it.
#   $1 = exact enseigne forms (raw + '' wildcard)
#   $2 = folded enseigne forms (key + brand root)
#   $3/$4 = accent fold src/dst
# `ean IS NOT NULL`: an alias without an EAN cannot resolve anything.
_SELECT_ALIASES_SQL = """
WITH folded AS (
    SELECT raw_text, enseigne, source, ean, produit_nom, confidence, validated_by_user,
           btrim(regexp_replace(
               translate(lower(btrim(enseigne)), $3, $4),
               '[^a-z0-9]+', ' ', 'g')) AS ens_fold
    FROM product_aliases
    WHERE ean IS NOT NULL
)
SELECT raw_text, enseigne, source, ean, produit_nom, confidence, validated_by_user
FROM folded
WHERE enseigne = ANY($1::text[])
   OR ens_fold = ANY($2::text[])
   OR split_part(ens_fold, ' ', 1) = ANY($2::text[])
"""


@dataclass
class ResolveStats:
    """Per-ticket counters for the ``ocr_done`` structured log."""

    n_lines: int = 0
    n_resolved_user: int = 0
    n_resolved_catalogue: int = 0
    n_resolved_total: int = 0
    n_needs_validation: int = 0


def _alias_rank(record: Any) -> tuple[bool, bool, float, str]:
    """Ordering key, higher wins. Encodes the multi-source arbitrage:

    1. ``validated_by_user`` — user-validation always outranks catalogue.
    2. enseigne-specific over the ``''`` wildcard.
    3. higher ``confidence``.
    4. ``ean`` — deterministic tiebreak so the pick is stable across runs.
    """
    confidence = record["confidence"]
    return (
        bool(record["validated_by_user"]),
        bool((record["enseigne"] or "").strip()),
        float(confidence) if confidence is not None else -1.0,
        record["ean"] or "",
    )


def _build_index(records: list[Any]) -> dict[str, Any]:
    """``normalize_label(raw_text)`` → best alias, resolving collisions by rank."""
    index: dict[str, Any] = {}
    best_rank: dict[str, tuple[bool, bool, float, str]] = {}
    for record in records:
        key = normalize_label(record["raw_text"])
        if not key:
            continue
        rank = _alias_rank(record)
        if key not in index or rank > best_rank[key]:
            index[key] = record
            best_rank[key] = rank
    return index


def _tally(rows: list[dict[str, Any]], stats: ResolveStats) -> None:
    """Recompute counters from the ACTUAL row state, so they stay truthful whether
    the lookup fully resolved, or was skipped on a best-effort read failure."""
    stats.n_resolved_user = sum(1 for r in rows if r.get("match_method") == MATCH_ALIAS_USER)
    stats.n_resolved_catalogue = sum(
        1 for r in rows if r.get("match_method") == MATCH_ALIAS_CATALOGUE
    )
    stats.n_resolved_total = stats.n_resolved_user + stats.n_resolved_catalogue
    stats.n_needs_validation = sum(1 for r in rows if r["needs_validation"])


async def resolve_line_eans(
    pool: Any, enseigne: str | None, rows: list[dict[str, Any]]
) -> ResolveStats:
    """Fill ``ean``/``match_method``/``match_confidence``/``needs_validation`` on
    ``rows`` **in place**, from ``product_aliases``.

    ``pool`` is an ``asyncpg.Pool`` (duck-typed: only ``.fetch`` is used, so this
    lib keeps no DB-driver dependency). A line without a match is left exactly as
    the mapper produced it. Returns per-ticket counters.
    """
    stats = ResolveStats(n_lines=len(rows))
    if not rows:
        return stats

    try:
        exact_forms, folded_forms = enseigne_candidates(enseigne)
        records = await pool.fetch(
            _SELECT_ALIASES_SQL,
            exact_forms,
            folded_forms,
            ENSEIGNE_ACCENT_SRC,
            ENSEIGNE_ACCENT_DST,
        )
        index = _build_index(records) if records else {}

        for row in rows:
            alias = index.get(normalize_label(row.get("raw_text")))
            if alias is None:
                continue  # additive: leave ean=None / match_method='none' / needs_validation=True

            row["ean"] = alias["ean"]
            if alias["validated_by_user"]:
                row["match_method"] = MATCH_ALIAS_USER
                row["match_confidence"] = 1.0
                row["needs_validation"] = False
            else:
                confidence = alias["confidence"]
                row["match_method"] = MATCH_ALIAS_CATALOGUE
                row["match_confidence"] = (
                    float(confidence) if confidence is not None else _CATALOGUE_FALLBACK_CONFIDENCE
                )
                row["needs_validation"] = True
    except Exception:
        # Best-effort : une panne de lecture product_aliases ne doit JAMAIS
        # bloquer la persistance du ticket. On loggue et on laisse les lignes
        # non résolues (ean=NULL, needs_validation=True), comme si aucun alias ne
        # matchait. La résolution repassera au re-OCR tier-2 ou au PATCH user.
        logger.warning("alias_lookup_failed", exc_info=True)

    _tally(rows, stats)
    return stats
