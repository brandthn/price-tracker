
from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download

from .logging import get_logger

logger = get_logger(__name__)


def download_snapshot(
    *,
    dataset: str,
    filename: str,
    revision: str = "main",
    token: str | None = None,
    cache_dir: str | Path = "/tmp/hf-cache",
) -> Path:

    logger.info(
        "hf_download_start",
        dataset=dataset,
        filename=filename,
        revision=revision,
    )
    local_path = hf_hub_download(
        repo_id=dataset,
        filename=filename,
        repo_type="dataset",
        revision=revision,
        token=token,
        cache_dir=str(cache_dir),
    )
    size_mb = Path(local_path).stat().st_size / (1024 * 1024)
    logger.info("hf_download_done", path=local_path, size_mb=round(size_mb, 2))
    return Path(local_path)
