"""Token bucket asynchrone simple.

Le worker OFF est limité à **15 req/min/IP** sur l'endpoint `GET /product`
(politique officielle OFF). Le timing exact = 1 token toutes les 4 secondes,
sans rafale au-delà de la capacité du bucket.

On garde un bucket à `rpm` tokens (= 1 minute de marge), refill linéaire.
Pourquoi pas `tenacity` natif : `tenacity` retry sur erreur, ici on rate-limit
en aval **avant** que la requête parte. Les deux sont complémentaires.
"""

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
        """Tokens/seconde."""
        return self.rpm / 60.0

    async def acquire(self, n: int = 1) -> None:
        """Bloque jusqu'à ce que `n` tokens soient disponibles."""
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
                # Libère le lock pendant la sieste : le rate-limit s'applique
                # globalement mais d'autres tâches asyncio peuvent progresser
                # (logs, etc.). Ici on garde le lock pour simplicité — le
                # worker n'a qu'un consommateur (la boucle principale).
                await asyncio.sleep(wait)
