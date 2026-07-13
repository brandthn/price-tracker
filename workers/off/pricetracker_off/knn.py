#In-memory kNN helpers for batch substitution scoring

from __future__ import annotations

import numpy as np

from .logging import get_logger

logger = get_logger(__name__)

# Sources traitées par bloc : borne la mémoire du produit matriciel (b x m).
_BLOCK = 1024


def compute_knn_pairs(
    eans: list[str],
    embeddings: np.ndarray,
    units: list[str],
    *,
    source_eans: set[str],
    k: int,
) -> list[tuple[str, str, float]]:
    # Return the top-k cosine neighbors for each source EAN
    n = len(eans)
    if n == 0 or embeddings.shape[0] != n:
        return []

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    normed = (embeddings / norms).astype(np.float32)

    units_arr = np.asarray(units)
    pairs: list[tuple[str, str, float]] = []

    for unit in np.unique(units_arr):
        idx = np.nonzero(units_arr == unit)[0]
        if idx.size < 2:
            continue
        group = normed[idx]  # (m, D)
        group_eans = [eans[i] for i in idx]
        src_local = np.asarray(
            [gi for gi, e in enumerate(group_eans) if e in source_eans], dtype=np.int64
        )
        if src_local.size == 0:
            continue
        kk = min(k, idx.size - 1)

        for start in range(0, src_local.size, _BLOCK):
            block = src_local[start : start + _BLOCK]
            sims = group[block] @ group.T  # (b, m)
            sims[np.arange(block.size), block] = -np.inf  # exclut soi-même
            top = np.argpartition(sims, -kk, axis=1)[:, -kk:]  # kk voisins (non triés)
            for bi, gi in enumerate(block):
                s_ean = group_eans[gi]
                for j in top[bi]:
                    c = float(sims[bi, j])
                    if c != float("-inf"):
                        pairs.append((s_ean, group_eans[int(j)], c))

    logger.info("knn_computed", pairs=len(pairs), products=n, k=k)
    return pairs
