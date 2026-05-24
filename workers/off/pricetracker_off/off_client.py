"""Client OpenFoodFacts — un seul endpoint utilisé : GET /api/v2/product/<ean>.

Rate-limit (15 req/min) tenu côté caller via `TokenBucket`. Le client se
contente du retry sur 429/5xx (backoff exp via tenacity) et du parsing.

Doc API : https://openfoodfacts.github.io/openfoodfacts-server/api/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .logging import get_logger
from .ratelimit import TokenBucket

logger = get_logger(__name__)

# Champs explicitement demandés à OFF — limite la taille de la réponse et
# rend le contrat de schéma explicite côté worker.
_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "product_name_fr",
        "brands",
        "categories_tags",
        "nutriscore_grade",
        "nova_group",
        "ecoscore_grade",
        "image_front_url",
        "image_url",
    ]
)


@dataclass
class OFFProduct:
    """Vue normalisée des champs OFF utilisés par le worker."""

    ean: str
    name: str | None
    brand: str | None
    category_l1: str | None
    category_l2: str | None
    category_l3: str | None
    nutriscore: str | None
    nova: str | None
    ecoscore: str | None
    image_url: str | None
    found: bool

    @property
    def embedding_text(self) -> str:
        """Texte qu'on enverra à Vertex AI text-embedding-004."""
        parts = [self.name or "", self.brand or "", self.category_l3 or ""]
        return " | ".join(p for p in parts if p).strip() or self.ean


def _parse_categories(tags: list[str] | None) -> tuple[str | None, str | None, str | None]:
    """`categories_tags` OFF = liste ordonnée du général au spécifique
    (`en:foods`, `en:beverages`, `en:drinks-with-sugar`...). On prend le
    premier / un milieu / le dernier comme L1/L2/L3.
    """
    if not tags:
        return None, None, None
    l1 = tags[0]
    l3 = tags[-1]
    l2 = tags[len(tags) // 2] if len(tags) >= 3 else None
    return l1, l2, l3


def _to_off_product(ean: str, payload: dict[str, Any]) -> OFFProduct:
    status = payload.get("status")
    if status != 1:
        # OFF retourne {"status": 0, "status_verbose": "product not found"} sur 404 logique.
        return OFFProduct(
            ean=ean,
            name=None,
            brand=None,
            category_l1=None,
            category_l2=None,
            category_l3=None,
            nutriscore=None,
            nova=None,
            ecoscore=None,
            image_url=None,
            found=False,
        )
    product = payload.get("product", {})
    brand = (product.get("brands") or "").split(",")[0].strip() or None
    l1, l2, l3 = _parse_categories(product.get("categories_tags"))
    return OFFProduct(
        ean=ean,
        name=product.get("product_name_fr") or product.get("product_name") or None,
        brand=brand,
        category_l1=l1,
        category_l2=l2,
        category_l3=l3,
        nutriscore=(product.get("nutriscore_grade") or "").upper() or None,
        nova=str(product.get("nova_group")) if product.get("nova_group") else None,
        ecoscore=(product.get("ecoscore_grade") or "").upper() or None,
        image_url=product.get("image_front_url") or product.get("image_url") or None,
        found=True,
    )


class OFFClient:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        rate_limit_rpm: int,
        timeout_s: float = 20.0,
        max_retries: int = 4,
        burst_capacity: int = 1,
        retry_wait_min_s: float = 30.0,
        retry_wait_max_s: float = 300.0,
        retry_wait_multiplier: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # capacity=1 par défaut : OFF rate-limit est anti-burst, pas seulement
        # anti-débit-moyen. Un bucket plein (15 tokens) déclenche 429 dès la
        # 7-8e requête en rafale. Forcer capacity=1 = strict 1 req tous les
        # 60/rpm secondes, pas de burst possible.
        self._bucket = TokenBucket(rpm=rate_limit_rpm, capacity=burst_capacity)
        self._max_retries = max_retries
        # Backoff aligné sur la reco officielle OFF (60s/120s/240s sur 429/503).
        # Cf. docs/OFF_API_Specification_PriceTracker.md §4 : "Si ces limites
        # sont dépassées, l'IP peut être bannie". Tests : override à 0 pour
        # ne pas patienter.
        self._retry_wait_min_s = retry_wait_min_s
        self._retry_wait_max_s = retry_wait_max_s
        self._retry_wait_multiplier = retry_wait_multiplier
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_s),
            http2=False,
        )

    async def __aenter__(self) -> "OFFClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def fetch_product(self, ean: str) -> OFFProduct:
        path = f"/api/v2/product/{ean}.json"
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(
                multiplier=self._retry_wait_multiplier,
                min=self._retry_wait_min_s,
                max=self._retry_wait_max_s,
            ),
            retry=retry_if_exception_type((httpx.TransportError, _RetryableStatus)),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                # Acquire DANS la boucle retry : sinon un retry sur 429 repart
                # immédiatement sans consommer de token, ce qui aggrave le
                # rate-limit côté OFF (vu en prod : 4 tentatives en rafale).
                await self._bucket.acquire(1)
                resp = await self._client.get(path, params={"fields": _FIELDS})
                if resp.status_code == 404:
                    # OFF retourne parfois 404 HTTP au lieu de status:0 — on
                    # marque comme not_found, c'est un état final.
                    return OFFProduct(
                        ean=ean,
                        name=None,
                        brand=None,
                        category_l1=None,
                        category_l2=None,
                        category_l3=None,
                        nutriscore=None,
                        nova=None,
                        ecoscore=None,
                        image_url=None,
                        found=False,
                    )
                if resp.status_code == 429 or resp.status_code >= 500:
                    logger.warning(
                        "off_retryable_status",
                        ean=ean,
                        status=resp.status_code,
                    )
                    raise _RetryableStatus(resp.status_code)
                resp.raise_for_status()
                return _to_off_product(ean, resp.json())
        # Boucle terminée sans return (impossible — `reraise=True` propage), pour mypy.
        raise RuntimeError("unreachable")


class _RetryableStatus(Exception):
    """Marqueur interne pour les statuts HTTP qui doivent déclencher un retry."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"retryable status {status_code}")
        self.status_code = status_code
