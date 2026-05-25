"""Root :mod:`pytest` configuration.

Adds the ``integration`` marker and the ``--no-integration`` flag, and
auto-skips integration tests when the real receipt data is missing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DATA_DIR = ROOT / "data" / "raw"

# Make `from receipt_ocr import ...` work without installation.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from receipt_ocr.env import load_project_env

load_project_env()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-integration",
        action="store_true",
        default=False,
        help="Skip tests marked as integration even if data is available.",
    )
    parser.addoption(
        "--integration-max-images",
        type=int,
        default=int(os.environ.get("INTEGRATION_MAX_IMAGES", "3")),
        help=(
            "Max number of receipt images to OCR in integration tests "
            "(default 3). Set 0 for no limit."
        ),
    )
    parser.addoption(
        "--integration-all-data",
        action="store_true",
        default=False,
        help=(
            "Also include Kaggle-cached images in integration tests "
            "(can be hundreds of files and very slow)."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require real receipt images on disk.",
    )
    config.addinivalue_line(
        "markers",
        "groq: marks tests that call the live Groq vision API (requires API key).",
    )


def _groq_api_key_available() -> bool:
    for name in ("GROQ_API_KEY", "groq_key"):
        value = os.environ.get(name)
        if value and value.strip():
            return True
    return False


def _data_available() -> bool:
    """Return True when at least one real receipt image is on disk."""
    if not DATA_DIR.exists():
        return False
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    for path in DATA_DIR.rglob("*"):
        if path.suffix.lower() in image_exts:
            return True
    return False


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    skip_reason: str | None = None
    if config.getoption("--no-integration"):
        skip_reason = "--no-integration was passed."
    elif not _data_available():
        skip_reason = (
            f"No receipt images found under {DATA_DIR}. "
            "Run `python scripts/download_datasets.py` to populate it."
        )

    if skip_reason is not None:
        marker = pytest.mark.skip(reason=skip_reason)
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(marker)
        return

    if not _groq_api_key_available():
        groq_skip = pytest.mark.skip(
            reason="Groq API key not set (GROQ_API_KEY or groq_key in .env)."
        )
        for item in items:
            if "groq" in item.keywords:
                item.add_marker(groq_skip)
