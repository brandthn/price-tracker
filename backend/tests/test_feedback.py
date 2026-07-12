"""Tests endpoint POST /tickets/{id}/feedback (boucle de feedback 👍/👎).

Stratégie (cf. conftest) : pas de testcontainers en CI → on override la
dependency `get_session` par une fausse session et on monkeypatch le
provisioning user + le publisher Pub/Sub.
"""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _make_ticket(
    user_id: uuid.UUID, *, attempts: int = 1, last_feedback=None, ocr_engine: str = "ocr-vlm-scratch"
):
    now = datetime.datetime.now(datetime.UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        status="ocr_done",
        enseigne="Carrefour Market",
        date_ticket=None,
        total_eur=None,
        ocr_confidence=1.0,
        ocr_engine=ocr_engine,  # tier-1 par défaut → escalade vers ocr-llm
        ocr_model=None,
        ocr_duration_ms=1200,
        ocr_error=None,
        ocr_attempts=attempts,
        last_feedback=last_feedback,
        created_at=now,
        updated_at=now,
    )


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self, ticket):
        self._ticket = ticket
        self.added: list = []
        self.committed = False

    async def get(self, _model, _pk):
        return self._ticket

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        return None

    async def execute(self, _stmt):
        return _FakeResult()


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    """Construit un TestClient avec une session fake + spies injectés."""

    def _build(ticket):
        import importlib

        from pricetracker_api import main as main_mod
        from pricetracker_api.db import get_session
        from pricetracker_api.routers import tickets as tickets_router
        from pricetracker_api.services import pubsub

        importlib.reload(main_mod)

        db_user = SimpleNamespace(id=ticket.user_id)

        async def _fake_get_or_create_user(_session, _user):
            return db_user

        published: list[str] = []

        def _fake_publish(topic_path: str, ticket_id: str) -> str:
            published.append(ticket_id)
            return "msg-id-123"

        monkeypatch.setattr(
            tickets_router, "get_or_create_user", _fake_get_or_create_user
        )
        monkeypatch.setattr(pubsub, "publish_to_topic", _fake_publish)

        session = _FakeSession(ticket)
        main_mod.app.dependency_overrides[get_session] = lambda: session

        return TestClient(main_mod.app), session, published

    return _build


def test_feedback_up_does_not_retry(make_client) -> None:
    user_id = uuid.uuid4()
    ticket = _make_ticket(user_id)
    client, session, published = make_client(ticket)

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "up"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retry_triggered"] is False
    assert body["ticket"]["last_feedback"] == "up"
    assert published == []
    # Une ligne ocr_feedback a bien été ajoutée.
    assert any(getattr(o, "rating", None) == "up" for o in session.added)


def test_feedback_down_triggers_retry(make_client) -> None:
    user_id = uuid.uuid4()
    ticket = _make_ticket(user_id, attempts=1)
    client, session, published = make_client(ticket)

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "down"})

    assert r.status_code == 200, r.text
    assert r.json()["retry_triggered"] is True
    assert published == [str(ticket.id)]
    fb = next(o for o in session.added if getattr(o, "rating", None) == "down")
    assert fb.ocr_attempt == 1


def test_feedback_down_at_cap_does_not_retry(make_client) -> None:
    user_id = uuid.uuid4()
    ticket = _make_ticket(user_id, attempts=4)  # plafond = 4 (scratch + 2 passes ocr-llm)
    client, _session, published = make_client(ticket)

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "down"})

    assert r.status_code == 200, r.text
    assert r.json()["retry_triggered"] is False
    assert published == []


def test_feedback_down_gemini_mid_chain_retries(make_client) -> None:
    # Chaîne scratch → ocr-llm → ocr-llm : le 1er `gemini` (attempts=3) n'est PAS
    # terminal, il re-boucle vers ocr-llm pour la 2e passe corrective.
    user_id = uuid.uuid4()
    ticket = _make_ticket(user_id, attempts=3, ocr_engine="gemini")
    client, _session, published = make_client(ticket)

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "down"})

    assert r.status_code == 200, r.text
    assert r.json()["retry_triggered"] is True
    assert published == [str(ticket.id)]


def test_feedback_down_gemini_at_cap_does_not_retry(make_client) -> None:
    # Après la 2e passe ocr-llm (attempts=4), le plafond stoppe la chaîne.
    user_id = uuid.uuid4()
    ticket = _make_ticket(user_id, attempts=4, ocr_engine="gemini")
    client, _session, published = make_client(ticket)

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "down"})

    assert r.status_code == 200, r.text
    assert r.json()["retry_triggered"] is False
    assert published == []


def test_feedback_other_user_404(make_client) -> None:
    ticket = _make_ticket(uuid.uuid4())
    client, _session, published = make_client(ticket)
    # Le ticket appartient à un autre user que celui résolu par le provisioning.
    ticket.user_id = uuid.uuid4()

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "up"})

    assert r.status_code == 404
    assert published == []


def test_feedback_invalid_rating_422(make_client) -> None:
    ticket = _make_ticket(uuid.uuid4())
    client, _session, _published = make_client(ticket)

    r = client.post(f"/tickets/{ticket.id}/feedback", json={"rating": "meh"})

    assert r.status_code == 422
