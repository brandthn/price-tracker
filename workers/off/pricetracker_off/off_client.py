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
# - generic_name / labels_tags / quantity servent au texte d'embedding « balanced »
#   (cf. embedding_text.build_embedding_text) ; `quantity` est EN PLUS persisté
#   tel quel dans products.quantity_raw (affichage/audit).
# - product_quantity + product_quantity_unit : socle unité (§5.2) — persistés
#   normalisés (g→kg, ml→L) dans products.quantity_value / quantity_unit.
# Tous existent aussi dans le dump OFF, d'où la parité API↔dump.
_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "product_name_fr",
        "generic_name",
        "generic_name_fr",
        "brands",
        "categories_tags",
        "labels_tags",
        "quantity",
        "product_quantity",
        "product_quantity_unit",
        "nutriscore_grade",
        "nova_group",
        "ecoscore_grade",
        "image_front_url",
        "image_url",
    ]
)


@dataclass
class OFFProduct:
    """Vue normalisée des champs OFF utilisés par le worker.

    `generic_name` / `categories_tags` / `labels_tags` servent uniquement à
    construire le texte d'embedding (`embedding_text.build_embedding_text`) et ne
    sont pas persistés tels quels.

    Les champs quantité SONT persistés (socle unité, Étape 1 reco) :
    - `quantity` (texte libre OFF) → products.quantity_raw + texte d'embedding ;
    - `product_quantity` + `product_quantity_unit` (colonnes OFF normalisées) →
      products.quantity_value / quantity_unit via `quantity.normalize_quantity`.

    Tous ont un défaut pour que les « tombstone » et la reconstruction depuis
    l'artefact (load_artifact) restent inchangées.
    """

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
    # --- champs texte-embedding (non persistés tels quels) ---
    generic_name: str | None = None
    categories_tags: list[str] | None = None  # hiérarchie brute (en:/fr:), général->spécifique
    labels_tags: list[str] | None = None  # brut (en:/fr:)
    # --- socle unité (persisté) ---
    quantity: str | None = None  # texte libre OFF (« 500 g ») → quantity_raw + embedding
    product_quantity: str | None = None  # numérique OFF (g ou ml), VARCHAR côté OFF
    product_quantity_unit: str | None = None  # 'g' | 'ml' (rarement 'kg'/'l')


def _str_or_none(v: Any) -> str | None:
    """OFF renvoie `product_quantity` tantôt en nombre, tantôt en string. On le
    stocke en texte (parité avec le dump, VARCHAR) ; le cast float a lieu au
    calcul (`quantity.normalize_quantity`)."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


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
        # champs texte-embedding — normalisés à parité avec le dump
        generic_name=product.get("generic_name_fr") or product.get("generic_name") or None,
        categories_tags=product.get("categories_tags") or None,
        labels_tags=product.get("labels_tags") or None,
        # socle unité — bruts OFF, normalisés à l'écriture (pg.normalize_quantity)
        quantity=(product.get("quantity") or "").strip() or None,
        product_quantity=_str_or_none(product.get("product_quantity")),
        product_quantity_unit=(product.get("product_quantity_unit") or "").strip() or None,
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

    async def __aenter__(self) -> OFFClient:
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
