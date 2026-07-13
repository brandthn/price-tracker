"""Publisher Pub/Sub pour l'escalade OCR (boucle de feedback).

Sur retour negatif, le backend publie le ticket_id sur le topic du tier suivant ;
une push subscription relaie vers le worker cible. Auth ADC (backend-sa), la SA a
roles/pubsub.publisher sur chaque topic.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _publisher() -> Any:
    # import lazy : pas de client gRPC au boot ni dans les tests qui monkeypatchent
    from google.cloud import pubsub_v1

    return pubsub_v1.PublisherClient()


def reset_for_tests() -> None:
    _publisher.cache_clear()


def publish_to_topic(topic_path: str, ticket_id: str) -> str:
    # {"ticket_id": ...} en JSON UTF-8 ; result() bloque pour propager l'erreur
    data = json.dumps({"ticket_id": ticket_id}).encode("utf-8")

    future = _publisher().publish(topic_path, data=data)
    message_id = future.result()
    logger.info(
        "ocr_escalation_published",
        ticket_id=ticket_id,
        topic=topic_path,
        message_id=message_id,
    )
    return message_id
