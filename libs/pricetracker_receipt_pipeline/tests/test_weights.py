"""Bootstrap des poids : download atomique, idempotence, propagation d'erreur."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pricetracker_receipt_pipeline.worker import weights


def _mock_storage(monkeypatch: pytest.MonkeyPatch, size: int, payload: bytes = b"x") -> MagicMock:
    blob = MagicMock()
    blob.size = size

    def _download(filename: str) -> None:
        Path(filename).write_bytes(payload)

    blob.download_to_filename.side_effect = _download
    client = MagicMock()
    client.bucket.return_value.blob.return_value = blob
    monkeypatch.setattr(weights.storage, "Client", lambda: client)
    return blob


def test_downloads_weights_to_dest_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    blob = _mock_storage(monkeypatch, size=1, payload=b"w")

    dest = weights.ensure_weights("gs://models/vlm/v1/model.pt", str(tmp_path / "models"))

    assert dest == tmp_path / "models" / "model.pt"
    assert dest.read_bytes() == b"w"
    blob.download_to_filename.assert_called_once()
    # Téléchargement via .part puis rename → jamais de fichier tronqué visible.
    assert blob.download_to_filename.call_args[0][0].endswith(".part")
    assert not (tmp_path / "models" / "model.pt.part").exists()


def test_skips_download_when_file_already_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "model.pt").write_bytes(b"abc")
    blob = _mock_storage(monkeypatch, size=3)

    dest = weights.ensure_weights("gs://models/model.pt", str(tmp_path))

    assert dest == tmp_path / "model.pt"
    blob.download_to_filename.assert_not_called()


def test_redownloads_when_local_size_differs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "model.pt").write_bytes(b"truncated")
    blob = _mock_storage(monkeypatch, size=99, payload=b"full-content")

    dest = weights.ensure_weights("gs://models/model.pt", str(tmp_path))

    blob.download_to_filename.assert_called_once()
    assert dest.read_bytes() == b"full-content"


def test_propagates_download_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    blob = _mock_storage(monkeypatch, size=1)
    blob.download_to_filename.side_effect = RuntimeError("404 not found")

    with pytest.raises(RuntimeError, match="404"):
        weights.ensure_weights("gs://models/model.pt", str(tmp_path))
