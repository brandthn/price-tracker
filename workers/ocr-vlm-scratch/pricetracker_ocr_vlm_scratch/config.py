"""Settings worker OCR backend OCR-VLM from-scratch (checkpoint + tokenizer)."""

from __future__ import annotations

from functools import lru_cache

from pricetracker_receipt_pipeline.worker.config import BaseWorkerSettings
from pydantic import Field


class Settings(BaseWorkerSettings):
    prt_ocr_engine_label: str = Field(default="ocr-vlm-scratch")
    # Longueur max du décodage glouton (640 tokens caractères par défaut côté modèle).
    prt_scratch_max_len: int = Field(default=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
