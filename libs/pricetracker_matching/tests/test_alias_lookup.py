"""Unit tests for resolve_line_eans (pure Python path, no DB).

A FakePool re-implements the SQL WHERE clause of _SELECT_ALIASES_SQL
INDEPENDENTLY over an in-memory alias table, so the whole matcher path is
exercised without Docker: enseigne pre-filter → index build → source arbitrage →
symmetric normalisation → in-place mutation → stats. The literal SQL string is
validated separately by the workers' testcontainers integration tests.
"""

from __future__ import annotations

import re

import pytest

from pricetracker_matching import alias_lookup
from pricetracker_matching.normalize import ENSEIGNE_ACCENT_DST, ENSEIGNE_ACCENT_SRC

_TABLE = str.maketrans(ENSEIGNE_ACCENT_SRC, ENSEIGNE_ACCENT_DST)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _sql_ens_fold(enseigne: str) -> str:
    """Mirror of btrim(regexp_replace(translate(lower(btrim(e)),src,dst),'[^a-z0-9]+',' ','g'))."""
    return _NON_ALNUM.sub(" ", enseigne.strip().lower().translate(_TABLE)).strip()


# (raw_text, enseigne, source, ean, confidence, validated_by_user)
_ALIASES = [
    ("Pain Complet", "Carrefour", "catalogue", "3270190123456", 0.7, False),
    ("LAIT UHT", "Carrefour Market", "user-validation", "3560070111111", 1.0, True),
    ("YAOURT NATURE", "Carrefour", "catalogue", "3000000000001", 0.7, False),
    ("YAOURT NATURE", "Carrefour", "user-validation", "3000000000002", 1.0, True),
    ("Beurre Doux", "Leclerc", "catalogue", "3111111111111", 0.7, False),
    ("VRAC LEGUMES", "Carrefour", "catalogue", None, 0.7, False),
    ("cafe ethiopie 250g", "Carrefour", "catalogue", "3222222222222", 0.7, False),
]


class _FakePool:
    def __init__(self, aliases=_ALIASES):
        self._aliases = aliases

    async def fetch(self, _sql, exact_forms, folded_forms, _src, _dst):
        out = []
        for raw_text, enseigne, source, ean, conf, validated in self._aliases:
            if ean is None:  # WHERE ean IS NOT NULL
                continue
            ens_fold = _sql_ens_fold(enseigne)
            if (
                enseigne in exact_forms
                or ens_fold in folded_forms
                or ens_fold.split(" ")[0] in folded_forms
            ):
                out.append({
                    "raw_text": raw_text, "enseigne": enseigne, "source": source,
                    "ean": ean, "produit_nom": None, "confidence": conf,
                    "validated_by_user": validated,
                })
        return out


class _RaisingPool:
    async def fetch(self, *_args, **_kwargs):
        raise RuntimeError("product_aliases read failed")


def _line(i, raw_text):
    return {"line_index": i, "raw_text": raw_text, "ean": None,
            "match_method": "none", "match_confidence": None,
            "needs_validation": True, "validated_by_user": False}


async def _resolve(pool, enseigne, raw_texts):
    rows = [_line(i, t) for i, t in enumerate(raw_texts)]
    stats = await alias_lookup.resolve_line_eans(pool, enseigne, rows)
    return rows, stats


async def test_exact_hit_catalogue_is_suggestion():
    rows, _ = await _resolve(_FakePool(), "CARREFOUR MARKET", ["PAIN COMPLET"])
    assert rows[0]["ean"] == "3270190123456"
    assert rows[0]["match_method"] == "alias-catalogue"
    assert rows[0]["match_confidence"] == pytest.approx(0.7)
    assert rows[0]["needs_validation"] is True


async def test_exact_hit_user_clears_needs_validation():
    rows, _ = await _resolve(_FakePool(), "CARREFOUR MARKET", ["lait uht"])
    assert rows[0]["ean"] == "3560070111111"
    assert rows[0]["match_method"] == "alias-user"
    assert rows[0]["needs_validation"] is False


async def test_source_priority_user_beats_catalogue():
    rows, _ = await _resolve(_FakePool(), "Carrefour", ["YAOURT NATURE"])
    assert rows[0]["ean"] == "3000000000002"
    assert rows[0]["match_method"] == "alias-user"


async def test_enseigne_discordante_no_match():
    rows, _ = await _resolve(_FakePool(), "CARREFOUR MARKET", ["BEURRE DOUX"])
    assert rows[0]["ean"] is None
    assert rows[0]["match_method"] == "none"


async def test_null_ean_and_miss_untouched():
    rows, _ = await _resolve(_FakePool(), "CARREFOUR MARKET", ["VRAC LEGUMES", "INCONNU"])
    assert all(r["ean"] is None and r["match_method"] == "none" for r in rows)


async def test_normaliser_symmetry_accents():
    rows, _ = await _resolve(_FakePool(), "CARREFOUR MARKET", ["CAFÉ ÉTHIOPIE 250G"])
    assert rows[0]["ean"] == "3222222222222"


async def test_stats_counters():
    _rows, stats = await _resolve(
        _FakePool(), "CARREFOUR MARKET",
        ["PAIN COMPLET", "lait uht", "YAOURT NATURE", "BEURRE DOUX",
         "INCONNU", "VRAC LEGUMES", "CAFÉ ÉTHIOPIE 250G"],
    )
    assert (stats.n_lines, stats.n_resolved_user, stats.n_resolved_catalogue,
            stats.n_resolved_total, stats.n_needs_validation) == (7, 2, 2, 4, 5)


async def test_read_failure_is_best_effort_no_raise():
    rows, stats = await _resolve(_RaisingPool(), "CARREFOUR MARKET", ["PAIN COMPLET", "lait uht"])
    for row in rows:
        assert row["ean"] is None
        assert row["match_method"] == "none"
        assert row["needs_validation"] is True
    assert stats.n_resolved_total == 0
    assert stats.n_needs_validation == 2


async def test_empty_rows_no_query():
    stats = await alias_lookup.resolve_line_eans(_FakePool(), "CARREFOUR", [])
    assert stats.n_lines == 0 and stats.n_resolved_total == 0
