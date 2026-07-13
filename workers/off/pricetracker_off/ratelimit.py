#Simple async token bucket

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    rpm: int
    capacity: int | None = None

    def __post_init__(self) -> None:
        if self.rpm <= 0:
            raise ValueError("rpm must be > 0")
        self.capacity = self.capacity or self.rpm
        self._tokens: float = float(self.capacity)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def refill_rate(self) -> float:
        return self.rpm / 60.0

    async def acquire(self, n: int = 1) -> None:
        #Bloque jusqu'à ce que `n` tokens soient disponibles
        if n <= 0:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    float(self.capacity or self.rpm),
                    self._tokens + elapsed * self.refill_rate,
                )
                self._last_refill = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                missing = n - self._tokens
                wait = missing / self.refill_rate
                await asyncio.sleep(wait)
