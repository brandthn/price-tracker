

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


MATCH_NONE = "none"
MATCH_ALIAS_USER = "alias-user"
MATCH_ALIAS_CATALOGUE = "alias-catalogue"

_CATALOGUE_FALLBACK_CONFIDENCE = 0.7


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


    n_lines: int = 0
    n_resolved_user: int = 0
    n_resolved_catalogue: int = 0
    n_resolved_total: int = 0
    n_needs_validation: int = 0


def _alias_rank(record: Any) -> tuple[bool, bool, float, str]:

    confidence = record["confidence"]
    return (
        bool(record["validated_by_user"]),
        bool((record["enseigne"] or "").strip()),
        float(confidence) if confidence is not None else -1.0,
        record["ean"] or "",
    )


def _build_index(records: list[Any]) -> dict[str, Any]:

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

    stats.n_resolved_user = sum(1 for r in rows if r.get("match_method") == MATCH_ALIAS_USER)
    stats.n_resolved_catalogue = sum(
        1 for r in rows if r.get("match_method") == MATCH_ALIAS_CATALOGUE
    )
    stats.n_resolved_total = stats.n_resolved_user + stats.n_resolved_catalogue
    stats.n_needs_validation = sum(1 for r in rows if r["needs_validation"])


async def resolve_line_eans(
    pool: Any, enseigne: str | None, rows: list[dict[str, Any]]
) -> ResolveStats:

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

        logger.warning("alias_lookup_failed", exc_info=True)

    _tally(rows, stats)
    return stats
