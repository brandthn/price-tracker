"""Publisher Pub/Sub pour déclencher le re-OCR tier-2 (boucle de feedback).

Quand un utilisateur met un 👎 sur l'output OCR, le backend publie le
`ticket_id` sur le topic `ocr-retry`. Une push subscription relaie le message
vers le worker OCR (`POST /retry`), qui ré-analyse l'image avec un second LLM.

Auth : ADC via la SA Cloud Run `prt-prod-backend-sa` (pas de clé JSON). La SA
doit avoir `roles/pubsub.publisher` sur le topic (cf. infra/envs/prod).
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import get_settings
from ..logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _publisher() -> Any:
    # Import paresseux : évite de charger le client gRPC Pub/Sub au démarrage
    # (et de l'exiger dans les tests qui monkeypatchent `publish_ocr_retry`).
    from google.cloud import pubsub_v1

    return pubsub_v1.PublisherClient()


def reset_for_tests() -> None:
    _publisher.cache_clear()


def publish_ocr_retry(ticket_id: str) -> str:
    """Publie `{"ticket_id": ...}` sur le topic de re-OCR. Retourne le message id.

    Le payload est encodé en JSON UTF-8 dans `data` (le worker le décode via
    `parse_retry_envelope`). Bloquant le temps du `result()` pour propager une
    éventuelle erreur de publication à l'appelant.
    """
    settings = get_settings()
    topic_path = settings.ocr_retry_topic_path
    data = json.dumps({"ticket_id": ticket_id}).encode("utf-8")

    future = _publisher().publish(topic_path, data=data)
    message_id = future.result()
    logger.info(
        "ocr_retry_published",
        ticket_id=ticket_id,
        topic=topic_path,
        message_id=message_id,
    )
    return message_id
