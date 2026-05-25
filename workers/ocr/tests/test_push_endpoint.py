"""Contract tests for POST /push."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from pricetracker_ocr.main import app
from pricetracker_ocr.ocr import OcrProcessingError

FIXTURE = Path(__file__).parent / "fixtures" / "pubsub_envelope.json"


@pytest.fixture
async def client():
    mock_pool = MagicMock()
    mock_pool.execute = AsyncMock(return_value="UPDATE 1")
    mock_pool.executemany = AsyncMock()
    mock_pool.close = AsyncMock()
    app.state.pool = mock_pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_pool


@pytest.mark.asyncio
async def test_push_happy_path(client, sample_ocr_result):
    ac, mock_pool = client
    with (
        patch("pricetracker_ocr.main.download_image", AsyncMock(return_value=b"\xff\xd8\xff")),
        patch(
            "pricetracker_ocr.main.asyncio.to_thread",
            AsyncMock(return_value=sample_ocr_result),
        ),
        patch("pricetracker_ocr.main.pg.set_ticket_processing", AsyncMock(return_value=True)),
        patch("pricetracker_ocr.main.pg.set_ticket_done", AsyncMock()) as done,
        patch("pricetracker_ocr.main.pg.upsert_prix_extraits", AsyncMock()) as upsert,
    ):
        response = await ac.post("/push", content=FIXTURE.read_bytes())
    assert response.status_code == 204
    done.assert_awaited_once()
    upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_idempotent_skip(client):
    ac, _mock_pool = client
    with patch(
        "pricetracker_ocr.main.pg.set_ticket_processing",
        AsyncMock(return_value=False),
    ):
        with patch("pricetracker_ocr.main.ocr.run_ocr") as run_ocr:
            response = await ac.post("/push", content=FIXTURE.read_bytes())
    assert response.status_code == 204
    run_ocr.assert_not_called()


@pytest.mark.asyncio
async def test_push_corrupt_image_marks_failed(client):
    ac, _mock_pool = client
    with (
        patch("pricetracker_ocr.main.download_image", AsyncMock(return_value=b"bad")),
        patch("pricetracker_ocr.main.pg.set_ticket_processing", AsyncMock(return_value=True)),
        patch(
            "pricetracker_ocr.main.asyncio.to_thread",
            AsyncMock(side_effect=OcrProcessingError("parse failed")),
        ),
        patch("pricetracker_ocr.main.pg.set_ticket_failed", AsyncMock()) as failed,
    ):
        response = await ac.post("/push", content=FIXTURE.read_bytes())
    assert response.status_code == 204
    failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_bad_envelope_returns_400(client):
    ac, _mock_pool = client
    response = await ac.post("/push", content=b"not-json")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_healthz(client):
    ac, _mock_pool = client
    response = await ac.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
