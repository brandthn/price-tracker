
from __future__ import annotations

import io
import json

import pandas as pd
from google.cloud import storage

from .config import Settings
from .logging import get_logger

logger = get_logger(__name__)




def _get_latest_blob(client: storage.Client, bucket_name: str) -> str:
    blobs = list(client.list_blobs(bucket_name, prefix="open-prices/dt="))
    parquets = [b.name for b in blobs if b.name.endswith("snapshot.parquet")]
    if not parquets:
        raise FileNotFoundError("Aucun snapshot parquet trouvé dans open-prices/")
    latest = sorted(parquets)[-1]  # tri lexicographique = tri chronologique YYYY-MM-DD
    logger.info("gcs_latest_snapshot", blob=latest)
    return latest




def _extract_raw(raw_payload: str) -> dict:
    try:
        d = json.loads(raw_payload)
        return {
            "proof_id":        d.get("proof_id"),
            "proof_file_path": d.get("proof_file_path"),
            "product_name":    d.get("product_name"),
            "proof_date":      d.get("proof_date"),
        }
    except (json.JSONDecodeError, TypeError):
        return {
            "proof_id": None, "proof_file_path": None,
            "product_name": None, "proof_date": None,
        }




def download_parquet(settings: Settings) -> pd.DataFrame:
    client = storage.Client(project=settings.google_cloud_project or None)
    bucket_name = settings.prt_bronze_bucket
    blob_name = _get_latest_blob(client, bucket_name)

    logger.info("gcs_download_start", bucket=bucket_name, blob=blob_name)

    buffer = io.BytesIO()
    client.bucket(bucket_name).blob(blob_name).download_to_file(buffer)
    buffer.seek(0)

    df = pd.read_parquet(buffer)
    logger.info("gcs_download_done", total_rows=len(df))


    raw_expanded = df["raw_payload"].apply(_extract_raw).apply(pd.Series)
    df = pd.concat([df, raw_expanded], axis=1)


    mask = (
        (df["proof_type"] == settings.prt_filter_proof_type)
        & (df["country_code"].isin(settings.allowed_countries))
        & df["product_code"].notna()
        & df["proof_file_path"].notna()
        & df["proof_id"].notna()
    )
    df_filtered = df[mask].copy()


    df_filtered["proof_id"] = df_filtered["proof_id"].astype(int)
    df_filtered["price_eur"] = pd.to_numeric(df_filtered["price_eur"], errors="coerce")

    logger.info(
        "gcs_filter_done",
        filtered_rows=len(df_filtered),
        unique_tickets=df_filtered["proof_id"].nunique(),
    )
    return df_filtered




def group_by_ticket(df: pd.DataFrame) -> dict[int, dict]:
    tickets: dict[int, dict] = {}

    for proof_id, groupe in df.groupby("proof_id"):
        first = groupe.iloc[0]
        produits = [
            {
                "ean":         str(row["product_code"]),
                "prix":        float(row["price_eur"]) if pd.notna(row["price_eur"]) else None,
                "nom_dataset": row["product_name"] if pd.notna(row.get("product_name")) else None,
            }
            for _, row in groupe.iterrows()
        ]
        tickets[int(proof_id)] = {
            "proof_file_path": first["proof_file_path"],
            "enseigne":        first.get("store_brand_normalized", "") or "",
            "date":            first.get("proof_date"),
            "pays":            first.get("country_code", "FR"),
            "produits":        produits,
        }

    logger.info("group_by_ticket_done", unique_tickets=len(tickets))
    return tickets