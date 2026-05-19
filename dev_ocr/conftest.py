"""Root :mod:`pytest` configuration.

Adds the ``integration`` marker and the ``--no-integration`` flag, and
auto-skips integration tests when the real receipt data is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DATA_DIR = ROOT / "data" / "raw"

# Make `from receipt_ocr import ...` work without installation.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-integration",
        action="store_true",
        default=False,
        help="Skip tests marked as integration even if data is available.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require real receipt images on disk.",
    )


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

    if skip_reason is None:
        return

    marker = pytest.mark.skip(reason=skip_reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(marker)
