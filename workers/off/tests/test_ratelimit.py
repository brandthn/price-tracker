"""Vérifie le token-bucket : capacité initiale = rpm, refill linéaire."""

from __future__ import annotations

import asyncio
import time

import pytest

from pricetracker_off.ratelimit import TokenBucket


async def test_bucket_allows_initial_burst() -> None:
    """Au démarrage le bucket est plein (capacité = rpm) : N acquires
    consécutifs ne bloquent pas."""
    bucket = TokenBucket(rpm=15)
    start = time.monotonic()
    for _ in range(15):
        await bucket.acquire(1)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"15 acquires initiaux devraient être instantanés, pris {elapsed}s"


async def test_bucket_blocks_when_exhausted() -> None:
    """Une fois le bucket vidé, le prochain acquire attend ~4s (15 rpm = 1/4s)."""
    bucket = TokenBucket(rpm=15, capacity=2)
    await bucket.acquire(1)
    await bucket.acquire(1)
    # Le 3e acquire doit attendre. On vérifie qu'il attend au moins 3s
    # (refill = 0.25 tokens/s, donc 4s pour 1 token, on prend une marge).
    start = time.monotonic()
    await bucket.acquire(1)
    elapsed = time.monotonic() - start
    assert elapsed >= 3.5, f"Devrait attendre ~4s, attendu {elapsed}s"


def test_bucket_rejects_invalid_rpm() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rpm=0)


async def test_acquire_zero_is_noop() -> None:
    bucket = TokenBucket(rpm=15, capacity=1)
    await bucket.acquire(1)  # vide le bucket
    # acquire(0) ne doit pas bloquer.
    await asyncio.wait_for(bucket.acquire(0), timeout=0.1)
