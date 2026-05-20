"""Chargements batch vers BigQuery (lignes Python → JSON)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Sequence

from google.cloud import bigquery


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convertit les types non supportés par insert_rows_json (ex. date, dict)."""
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict):
            out[key] = json.dumps(value, ensure_ascii=False, default=_json_default)
        elif isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def insert_rows_in_batches(
    client: bigquery.Client,
    table_id: str,
    rows: Sequence[Dict[str, Any]],
    batch_size: int = 8000,
) -> None:
    """Insère des lignes par paquets pour limiter la taille des requêtes."""
    table = client.get_table(table_id)
    buffer: List[Dict[str, Any]] = []
    for row in rows:
        buffer.append(_serialize_row(row))
        if len(buffer) >= batch_size:
            errors = client.insert_rows_json(table, buffer)
            if errors:
                raise RuntimeError(f"BigQuery insert errors (first): {errors[:3]}")
            buffer.clear()
    if buffer:
        errors = client.insert_rows_json(table, buffer)
        if errors:
            raise RuntimeError(f"BigQuery insert errors (first): {errors[:3]}")


def stream_iterable_in_batches(
    client: bigquery.Client,
    table_id: str,
    rows: Iterable[Dict[str, Any]],
    batch_size: int = 5000,
) -> int:
    """Parcourt un itérable sans tout matérialiser ; retourne le nombre de lignes insérées."""
    table = client.get_table(table_id)
    buffer: List[Dict[str, Any]] = []
    total = 0
    for row in rows:
        buffer.append(_serialize_row(row))
        if len(buffer) >= batch_size:
            errors = client.insert_rows_json(table, buffer)
            if errors:
                raise RuntimeError(f"BigQuery insert errors (first): {errors[:3]}")
            total += len(buffer)
            buffer.clear()
    if buffer:
        errors = client.insert_rows_json(table, buffer)
        if errors:
            raise RuntimeError(f"BigQuery insert errors (first): {errors[:3]}")
        total += len(buffer)
    return total
