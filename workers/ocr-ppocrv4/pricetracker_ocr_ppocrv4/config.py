"""Settings worker OCR backend PP-OCRv4 mobile (français)."""

from __future__ import annotations

from functools import lru_cache

from pricetracker_receipt_pipeline.worker.config import BaseWorkerSettings
from pydantic import Field


class Settings(BaseWorkerSettings):
    prt_ocr_engine_label: str = Field(default="ppocrv4")


@lru_cache
def get_settings() -> Settings:
    return Settings()
