"""
Couche BRONZE — Acquisition et stockage brut de la donnée.

Principe fondamental de la couche Bronze :
    On écrit la donnée telle quelle, hormis un pré-filtre géographique
    appliqué dès l'ingestion. Le dataset HuggingFace est mondial : sans
    filtre, 62 % des lignes seraient rejetées en Silver pour hors-périmètre
    (devise non EUR, pays non FR). Filtrer ici évite de stocker et de
    traiter des données qui ne nous concernent pas.

    Périmètre retenu : France métropolitaine + DOM/TOM
    (codes ISO : FR, GP, GF, MQ, RE, YT, PM, MF, BL, WF, NC, PF)

    En production GCP, ce Parquet serait uploadé dans un bucket GCS
    partitionné par date (gs://bronze-bucket/open-prices/date=…/snapshot.parquet).
    En local, on écrit dans data/bronze/.

Métadonnées Bronze :
    _metadata.json trace : date d'ingestion, nb lignes mondial vs FR,
    colonnes présentes, taille fichier.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

BRONZE_DIR      = _REPO_ROOT / "data" / "bronze"
BRONZE_PARQUET  = BRONZE_DIR / "open_prices.parquet"
BRONZE_METADATA = BRONZE_DIR / "_metadata.json"

# Noms de pays reconnus comme territoire français (comparaison lowercase-strip)
_FRENCH_COUNTRY_NAMES = {
    "france",
    "guadeloupe",
    "martinique",
    "guyane",
    "réunion",
    "reunion",
    "mayotte",
    "saint-martin",
    "saint barthélemy",
    "saint-barthélemy",
    "saint pierre and miquelon",
    "wallis and futuna",
    "new caledonia",
    "nouvelle-calédonie",
    "french polynesia",
    "polynésie française",
}

COLUMNS = [
    "id", "product_code", "price", "price_is_discounted",
    "price_without_discount", "currency", "date", "proof_type",
    "location_id", "location_osm_display_name",
    "location_osm_address_city", "location_osm_address_postcode",
    "location_osm_address_country", "location_osm_lat", "location_osm_lon",
    "source",
]


def run_bronze() -> Dict[str, Any]:
    """
    Télécharge le snapshot Open Prices depuis HuggingFace,
    pré-filtre les données France + DOM/TOM, et persiste en Parquet.

    Returns:
        Dictionnaire de métadonnées Bronze (utilisé par l'orchestrateur).
    """
    try:
        from datasets import load_dataset
        import duckdb
    except ImportError as exc:
        raise ImportError(
            "Installez 'datasets' et 'duckdb' : pip install datasets duckdb"
        ) from exc

    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()

    print("\n" + "═" * 60)
    print("  BRONZE — Acquisition brute")
    print("═" * 60)
    print("  [Bronze] Connexion à HuggingFace (openfoodfacts/open-prices)…")

    dataset = load_dataset(
        "openfoodfacts/open-prices",
        split="prices",
        columns=COLUMNS,
    )
    n_total = len(dataset)
    print(f"  [Bronze] {n_total:,} lignes reçues (monde entier)")
    print("  [Bronze] Pré-filtre : France + DOM/TOM…")

    def _is_french(row: Dict[str, Any]) -> bool:
        country = row.get("location_osm_address_country") or ""
        return country.strip().lower() in _FRENCH_COUNTRY_NAMES

    dataset_fr = dataset.filter(_is_french, desc="Filtre France")
    n_fr = len(dataset_fr)
    pct_kept = n_fr / n_total * 100 if n_total else 0
    print(f"  [Bronze] {n_fr:,} lignes conservées ({pct_kept:.1f}% — France + DOM/TOM)")
    print(f"  [Bronze] {n_total - n_fr:,} lignes hors périmètre écartées à la source")
    print("  [Bronze] Écriture Parquet…")

    dataset_fr.to_parquet(str(BRONZE_PARQUET))

    # Vérification de cohérence via DuckDB (lecture indépendante du fichier)
    con = duckdb.connect()
    result = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{BRONZE_PARQUET}')"
    ).fetchone()
    con.close()
    print(f"  [Bronze] Vérification DuckDB : {result[0]:,} lignes dans le Parquet")

    df_check = pd.read_parquet(BRONZE_PARQUET)
    columns = list(df_check.columns)

    metadata: Dict[str, Any] = {
        "source":              "huggingface_open_prices",
        "ingested_at":         started_at,
        "n_rows_total_world":  n_total,
        "n_rows":              result[0],
        "filter_applied":      "France + DOM/TOM (location_osm_address_country)",
        "pct_kept":            round(pct_kept, 2),
        "n_columns":           len(columns),
        "columns":             columns,
        "parquet_path":        str(BRONZE_PARQUET),
        "size_bytes":          BRONZE_PARQUET.stat().st_size,
    }
    BRONZE_METADATA.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    print(f"  [Bronze] Parquet écrit   → {BRONZE_PARQUET}")
    print(f"  [Bronze] Métadonnées     → {BRONZE_METADATA}")
    print(f"  [Bronze] {result[0]:,} lignes, {metadata['size_bytes'] / 1024:.1f} Ko")

    return metadata
