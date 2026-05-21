"""Normalisation du parquet Open Prices brut → schéma Silver `open_prices_clean`.

Le dataset HF a un schéma qui évolue (ajout/suppression de colonnes par OFF
au fil des versions). On ne suppose donc PAS un schéma figé : on lit ce
qui est présent, on mappe les colonnes vers le schéma BQ, et on remplit
NULL pour ce qui manque. La table BQ accepte NULL sur tout sauf `id`,
`date`, `kind`, `source`, `ingested_at`.

Pipeline :
1. Coalesce chaque colonne cible parmi ses alias possibles.
2. Cast vers le type pyarrow attendu (NULL × N si la colonne est absente).
3. Ajoute `source` + `ingested_at` constants.
4. Filtre `country_code` (optionnel).
5. Dédup sur `id` via `Table.combine_chunks` + `drop_duplicates` côté
   pandas — pyarrow seul force un `group_by` qui renomme les colonnes en
   `<col>_first` et complique inutilement la sortie.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .logging import get_logger

logger = get_logger(__name__)

SILVER_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("date", pa.date32()),
        ("product_code", pa.string()),
        ("product_name", pa.string()),
        ("price", pa.float64()),
        ("currency", pa.string()),
        ("location_id", pa.int64()),
        ("location_osm_name", pa.string()),
        ("country_code", pa.string()),
        ("category_tag", pa.string()),
        ("kind", pa.string()),
        ("source", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
    ]
)


_COLUMN_ALIASES: dict[str, list[str]] = {
    "id": ["id"],
    "date": ["date"],
    "product_code": ["product_code", "code"],
    "product_name": ["product_name", "name"],
    "price": ["price"],
    "currency": ["currency"],
    "location_id": ["location_id"],
    "location_osm_name": ["location_osm_name", "location_osm_display_name"],
    "country_code": ["country_code", "location_osm_address_country_code"],
    "category_tag": ["category_tag", "category", "labels_tags"],
    "kind": ["kind", "type"],
}


def _maybe_col(
    table: pa.Table,
    candidates: list[str],
    *,
    n: int,
    target_type: pa.DataType,
) -> pa.Array:
    """Trouve la première colonne candidate présente dans `table`, la cast
    vers `target_type`. Si aucune n'est présente, retourne un Array de N
    NULLs typés. Toujours longueur N.
    """
    for name in candidates:
        if name in table.column_names:
            arr = table.column(name).combine_chunks()
            if arr.type == target_type:
                return arr
            return arr.cast(target_type, safe=False)
    return pa.nulls(n, type=target_type)


def _date_col(table: pa.Table, candidates: list[str], *, n: int) -> pa.Array:
    """`date` est REQUIRED en BQ → on lève si absent côté source.
    Supporte source en date32, timestamp ou string YYYY-MM-DD.
    """
    for name in candidates:
        if name in table.column_names:
            arr = table.column(name).combine_chunks()
            if pa.types.is_date(arr.type):
                return arr.cast(pa.date32(), safe=False)
            if pa.types.is_timestamp(arr.type):
                return arr.cast(pa.date32(), safe=False)
            if pa.types.is_string(arr.type):
                return pc.cast(
                    pc.strptime(arr, format="%Y-%m-%d", unit="us"), pa.date32()
                )
            return arr.cast(pa.date32(), safe=False)
    raise ValueError(f"Missing required column 'date' (tried {candidates}) in source parquet.")


def normalize(
    raw: pa.Table,
    *,
    country_code_filter: str | None = "FR",
    source_label: str = "hf-open-prices",
    ingested_at: datetime | None = None,
) -> pa.Table:
    """Mappe colonnes brutes → SILVER_SCHEMA, filtre pays, dédup sur `id`."""
    n_input = raw.num_rows
    if n_input == 0:
        logger.info("transform_empty_input")
        return pa.table({name: pa.array([], type=t) for name, t in zip(
            SILVER_SCHEMA.names, SILVER_SCHEMA.types, strict=True
        )}, schema=SILVER_SCHEMA)

    n = n_input

    # `kind` reçoit un traitement spécifique (uppercase, fallback PRODUCT).
    kind_raw = _maybe_col(raw, _COLUMN_ALIASES["kind"], n=n, target_type=pa.string())
    kind = pc.utf8_upper(pc.fill_null(kind_raw, "PRODUCT")).cast(pa.string())

    cols: dict[str, pa.Array] = {
        "id": _maybe_col(raw, _COLUMN_ALIASES["id"], n=n, target_type=pa.string()),
        "date": _date_col(raw, _COLUMN_ALIASES["date"], n=n),
        "product_code": _maybe_col(raw, _COLUMN_ALIASES["product_code"], n=n, target_type=pa.string()),
        "product_name": _maybe_col(raw, _COLUMN_ALIASES["product_name"], n=n, target_type=pa.string()),
        "price": _maybe_col(raw, _COLUMN_ALIASES["price"], n=n, target_type=pa.float64()),
        "currency": _maybe_col(raw, _COLUMN_ALIASES["currency"], n=n, target_type=pa.string()),
        "location_id": _maybe_col(raw, _COLUMN_ALIASES["location_id"], n=n, target_type=pa.int64()),
        "location_osm_name": _maybe_col(raw, _COLUMN_ALIASES["location_osm_name"], n=n, target_type=pa.string()),
        "country_code": _maybe_col(raw, _COLUMN_ALIASES["country_code"], n=n, target_type=pa.string()),
        "category_tag": _maybe_col(raw, _COLUMN_ALIASES["category_tag"], n=n, target_type=pa.string()),
        "kind": kind,
    }

    ts = ingested_at or datetime.now(UTC)
    cols["source"] = pa.array([source_label] * n, type=pa.string())
    cols["ingested_at"] = pa.array([ts] * n, type=pa.timestamp("us", tz="UTC"))

    table = pa.table(cols, schema=SILVER_SCHEMA)

    if country_code_filter:
        mask = pc.equal(table.column("country_code"), country_code_filter)
        table = table.filter(mask)
    n_after_filter = table.num_rows

    # Dédup sur `id` — `id` est NOT NULL côté schéma, mais on garde un mask
    # défensif (un cast safe=False peut produire un NULL silencieux).
    if table.num_rows:
        df = table.to_pandas(types_mapper=None)
        df = df.dropna(subset=["id"]).drop_duplicates(subset=["id"], keep="first")
        table = pa.Table.from_pandas(df, schema=SILVER_SCHEMA, preserve_index=False)

    logger.info(
        "transform_done",
        rows_input=n_input,
        rows_after_country_filter=n_after_filter,
        rows_after_dedup=table.num_rows,
    )
    return table


def read_parquet(path: str) -> pa.Table:
    return pq.read_table(path)


def write_parquet(table: pa.Table, dest: str) -> None:
    pq.write_table(table, dest, compression="snappy")
