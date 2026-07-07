"""kNN en mémoire (BLAS) : top-k intra-unité, auto-exclusion, filtre sources."""

from __future__ import annotations

import numpy as np

from pricetracker_off.knn import compute_knn_pairs

_EANS = ["a", "b", "c", "d"]
_EMB = np.array(
    [
        [1.0, 0.0, 0.0],   # a
        [0.99, 0.02, 0.0],  # b — très proche de a
        [0.0, 1.0, 0.0],   # c — loin de a/b
        [1.0, 0.0, 0.0],   # d — même vecteur que a MAIS unité différente (L)
    ],
    dtype=np.float32,
)
_UNITS = ["kg", "kg", "kg", "L"]


def test_knn_same_unit_self_excluded() -> None:
    pairs = compute_knn_pairs(_EANS, _EMB, _UNITS, source_eans=set(_EANS), k=1)
    d = {(s, t) for s, t, _ in pairs}
    assert ("a", "b") in d  # top-1 de a = b (même unité, pas soi-même, pas d)
    assert all(s != t for s, t in d)  # jamais soi-même
    assert all(s != "d" and t != "d" for s, t in d)  # d seul en L → aucune paire


def test_knn_respects_source_filter() -> None:
    pairs = compute_knn_pairs(_EANS, _EMB, _UNITS, source_eans={"a"}, k=2)
    assert pairs  # a a des voisins
    assert {s for s, _t, _c in pairs} == {"a"}  # seules les sources demandées


def test_knn_cosine_values_sane() -> None:
    pairs = compute_knn_pairs(_EANS, _EMB, _UNITS, source_eans={"a"}, k=2)
    by_t = {t: c for s, t, c in pairs}
    assert by_t["b"] > by_t["c"]  # b plus proche de a que c
    assert 0.9 < by_t["b"] <= 1.0
