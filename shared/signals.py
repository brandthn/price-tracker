"""Persistance des signaux JSON sur disque (mode local sans GCS)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def write_local_signal(
    base_dir: Path,
    execution_date: str,
    worker_name: str,
    payload: Dict[str, Any],
) -> Path:
    path = base_dir / "pipeline-signals" / f"date={execution_date}" / f"{worker_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_local_signal(
    base_dir: Path,
    execution_date: str,
    worker_name: str,
) -> Dict[str, Any] | None:
    path = base_dir / "pipeline-signals" / f"date={execution_date}" / f"{worker_name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
