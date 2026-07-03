"""Bulk enrichment LOCAL — étape 1/2 du ré-enrichissement OFF sur liste explicite d'EAN.

Contexte : pour (ré)enrichir plusieurs milliers d'EAN (init-scale), la politique
OFF (§11 du spec) demande d'utiliser le **dump bulk** plutôt que l'API 1-par-1
(15 req/min → ban). Ce script :

  1. lit la liste d'EAN d'un CSV (colonne `ean`) ;
  2. filtre le dump OFF local `food.parquet` sur ces EAN via DuckDB (SEMI JOIN,
     colonnes ciblées) → mappe vers `OFFProduct` (réutilise le contrat du worker) ;
  3. génère les embeddings Vertex `text-embedding-004` (dim 768) pour les trouvés ;
  4. écrit un artefact `enriched.jsonl.gz` (champs OFF + embedding) que l'étape
     Cloud (`pricetracker_off.load_artifact`) chargera dans BQ + Cloud SQL.

Cloud SQL `products` étant injoignable en local, ce script n'écrit AUCUNE base :
il produit uniquement l'artefact + (option) l'uploade sur GCS.

Ce module vit hors du wheel déployé (`pricetracker_off`) : il dépend de `duckdb`
qui n'a pas à être embarqué dans l'image Cloud Run.

Usage :
    cd workers/off
    uv run --with duckdb python bulk/enrich.py \
        --csv ../../data/catalog/catalog_feed/studio_results_20260624_1651.csv \
        --parquet ../../data/off_bulk/off_food_dump.parquet \
        --out ../../data/off_bulk/enriched.jsonl.gz
    # dry-run rapide (mapping only, sans coût Vertex) :
    uv run --with duckdb python bulk/enrich.py ... --limit 20 --no-embed
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Réutilise le contrat produit + le parsing catégories + la formule d'embedding
# du worker déployé. `build_embedding_text` est la SOURCE UNIQUE partagée avec
# le worker quotidien (parité API↔dump). `duckdb` est importé paresseusement
# dans `fetch_from_parquet` : ce module reste importable (mappers, parité) sans
# la dép lourde, notamment côté tests.
from pricetracker_off.config import get_settings
from pricetracker_off.embedding_text import build_embedding_text
from pricetracker_off.off_client import OFFProduct, _parse_categories

# --- Colonnes tirées du parquet OFF (schéma food.parquet, validé via DESCRIBE) ---
#   code                        VARCHAR
#   product_name                STRUCT(lang, text)[]
#   brands                      VARCHAR
#   categories_tags             VARCHAR[]
#   nutriscore_grade            VARCHAR
#   nova_group                  INTEGER
#   environmental_score_grade   VARCHAR   (= ecoscore)
#   images                      STRUCT(key, imgid, rev, sizes, ...)[]
_QUERY = """
SELECT
    p.code                      AS ean,
    p.product_name              AS product_name,       -- STRUCT(lang,text)[]
    p.generic_name              AS generic_name,        -- STRUCT(lang,text)[]
    p.brands                    AS brands,
    p.categories_tags           AS categories_tags,     -- VARCHAR[] (général -> spécifique)
    p.labels_tags               AS labels_tags,         -- VARCHAR[]
    p.quantity                  AS quantity,
    p.nutriscore_grade          AS nutriscore_grade,
    p.nova_group                AS nova_group,
    p.environmental_score_grade AS ecoscore_grade,
    list_transform(
        coalesce(p.images, []),
        x -> {'key': x.key, 'rev': x.rev}
    )                           AS images
FROM read_parquet(?) p
SEMI JOIN want w ON p.code = w.ean
"""


def read_eans(csv_path: Path) -> list[str]:
    eans: list[str] = []
    with csv_path.open() as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header or header[0].strip().strip('"').lower() != "ean":
            raise SystemExit(f"CSV attendu avec une colonne 'ean' en tête, trouvé: {header}")
        seen: set[str] = set()
        for row in reader:
            if row and row[0].strip():
                e = row[0].strip()
                if e not in seen:
                    seen.add(e)
                    eans.append(e)
    return eans


def _pick_name(product_name: list | None) -> str | None:
    """`product_name` = liste {lang, text}. Préférence fr → main → en → 1er non vide."""
    if not product_name:
        return None
    by_lang: dict[str, str] = {}
    first = None
    for item in product_name:
        lang = (item.get("lang") or "").lower()
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if first is None:
            first = text
        by_lang.setdefault(lang, text)
    return by_lang.get("fr") or by_lang.get("main") or by_lang.get("en") or first


def _as_text(v: object) -> str:
    """Champs OFF multilingues stockés en STRUCT(lang,text)[] (product_name,
    generic_name, ...). Renvoie le meilleur texte (fr>main>en>1er) ou ''."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return _pick_name(v) or ""
        return ", ".join(str(x) for x in v)
    return str(v)


def _barcode_path(code: str) -> str:
    """Découpage OFF du code-barres pour l'URL image (>8 chiffres → groupes de 3)."""
    if len(code) <= 8:
        return code
    return f"{code[0:3]}/{code[3:6]}/{code[6:9]}/{code[9:]}"


def _pick_image_url(ean: str, images: list | None) -> str | None:
    """Best-effort : construit l'URL de l'image `front` (front_fr prioritaire).
    Retourne None si aucune image front → limite connue du bulk (l'API donnait
    `image_front_url` directement). Cf. runbook."""
    if not images:
        return None
    front = None
    for img in images:
        key = img.get("key") or ""
        if key == "front_fr":
            front = img
            break
        if key.startswith("front") and front is None:
            front = img
    if not front:
        return None
    key, rev = front.get("key"), front.get("rev")
    if not key or rev is None:
        return None
    return (
        f"https://images.openfoodfacts.org/images/products/"
        f"{_barcode_path(ean)}/{key}.{rev}.400.jpg"
    )


def _row_to_product(row: dict) -> OFFProduct:
    """Mappe une ligne parquet → OFFProduct (même contrat que off_client)."""
    ean = row["ean"]
    l1, l2, l3 = _parse_categories(row.get("categories_tags"))
    brand = (row.get("brands") or "").split(",")[0].strip() or None
    nova = row.get("nova_group")
    return OFFProduct(
        ean=ean,
        name=_pick_name(row.get("product_name")),
        brand=brand,
        category_l1=l1,
        category_l2=l2,
        category_l3=l3,
        nutriscore=(row.get("nutriscore_grade") or "").upper() or None,
        nova=str(nova) if nova is not None else None,
        ecoscore=(row.get("ecoscore_grade") or "").upper() or None,
        image_url=_pick_image_url(ean, row.get("images")),
        found=True,
        # champs texte-embedding (non persistés) — normalisés à parité avec l'API
        generic_name=_as_text(row.get("generic_name")) or None,
        categories_tags=row.get("categories_tags") or None,
        labels_tags=row.get("labels_tags") or None,
        quantity=(row.get("quantity") or "").strip() or None,
    )


def _not_found(ean: str) -> OFFProduct:
    return OFFProduct(
        ean=ean, name=None, brand=None, category_l1=None, category_l2=None,
        category_l3=None, nutriscore=None, nova=None, ecoscore=None,
        image_url=None, found=False,
    )


def fetch_from_parquet(
    parquet_path: Path, eans: list[str]
) -> tuple[list[OFFProduct], list[str | None]]:
    """Filtre le dump OFF sur `eans`. Renvoie (produits, textes_embedding) alignés :
    - trouvés : OFFProduct mappé + texte d'embedding 'balanced' (catégories complètes) ;
    - non-trouvés : tombstone off_found=false + texte None (pas d'embedding)."""
    import duckdb  # lazy : dép lourde absente du wheel/tests, requise seulement ici

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE want(ean VARCHAR)")
    con.executemany("INSERT INTO want VALUES (?)", [(e,) for e in eans])
    cur = con.execute(_QUERY, [str(parquet_path)])
    cols = [d[0] for d in cur.description]
    found: dict[str, OFFProduct] = {}
    found_text: dict[str, str] = {}
    for tup in cur.fetchall():
        row = dict(zip(cols, tup, strict=True))
        p = _row_to_product(row)
        found[p.ean] = p
        # parité : le worker quotidien appelle la MÊME fonction sur un OFFProduct
        found_text[p.ean] = build_embedding_text(p)

    products: list[OFFProduct] = []
    texts: list[str | None] = []
    for e in eans:  # trouvés d'abord (ordre déterministe = ordre CSV)
        if e in found:
            products.append(found[e])
            texts.append(found_text[e])
    for e in eans:  # puis tombstones
        if e not in found:
            products.append(_not_found(e))
            texts.append(None)
    return products, texts


def embed_products(
    products: list[OFFProduct], texts: list[str | None]
) -> list[list[float] | None]:
    """Embeddings Vertex pour les textes non-None (produits trouvés) ; None aligné
    pour les tombstones."""
    import google.auth

    from pricetracker_off.vertex import VertexEmbedder

    s = get_settings()
    _, project = google.auth.default()
    if s.google_cloud_project:
        project = s.google_cloud_project
    if not project:
        raise SystemExit("Projet GCP introuvable (ADC). `gcloud auth application-default login`.")

    embedder = VertexEmbedder(
        project=project,
        location=s.prt_gcp_region,
        model_name=s.prt_vertex_model,
        batch_size=s.prt_vertex_batch,
        task_type=s.prt_vertex_task_type,
        output_dim=s.prt_vertex_output_dim,
    )
    idx = [i for i, t in enumerate(texts) if t]
    vecs = embedder.embed([texts[i] for i in idx])  # type: ignore[misc]
    out: list[list[float] | None] = [None] * len(products)
    for i, v in zip(idx, vecs, strict=True):
        out[i] = v
    return out


def write_artifact(
    out_path: Path,
    products: list[OFFProduct],
    texts: list[str | None],
    embeddings: list[list[float] | None],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        for p, txt, emb in zip(products, texts, embeddings, strict=True):
            rec = asdict(p)
            rec["embedding_text"] = txt  # str | None (traçabilité : ce qui est embeddé)
            rec["embedding"] = emb  # list[float] | None
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk OFF enrichment (local, produit un artefact).")
    ap.add_argument("--csv", required=True, type=Path, help="CSV avec colonne 'ean'.")
    ap.add_argument("--parquet", required=True, type=Path, help="Dump OFF food.parquet local.")
    ap.add_argument("--out", required=True, type=Path, help="Artefact de sortie .jsonl.gz.")
    ap.add_argument("--limit", type=int, default=0, help="Limite le nb d'EAN (dry-run).")
    ap.add_argument("--no-embed", action="store_true", help="Skip Vertex (mapping only).")
    ap.add_argument(
        "--found-only",
        action="store_true",
        help=(
            "N'émet PAS de tombstones : seuls les EAN trouvés dans le dump sont "
            "écrits dans l'artefact. Garde-fou vague 2 — un EAN présent en base "
            "mais absent du dump (ex: import Maty, produit hors OFF) ne doit pas "
            "être écrasé/vidé par un tombstone au chargement."
        ),
    )
    args = ap.parse_args()

    t0 = time.time()
    eans = read_eans(args.csv)
    if args.limit:
        eans = eans[: args.limit]
    print(f"[1/4] EAN à traiter : {len(eans)}")

    products, texts = fetch_from_parquet(args.parquet, eans)
    n_found = sum(p.found for p in products)
    print(f"[2/4] OFF match : {n_found}/{len(products)} trouvés "
          f"({100 * n_found / len(products):.1f}%), {len(products) - n_found} tombstones")
    if args.found_only:
        kept = [(p, t) for p, t in zip(products, texts, strict=True) if p.found]
        n_dropped = len(products) - len(kept)
        products = [p for p, _ in kept]
        texts = [t for _, t in kept]
        print(f"       --found-only : {n_dropped} tombstones exclus, "
              f"{len(products)} produits conservés")
    for p, t in zip(products, texts, strict=True):  # aperçu de 2 textes embeddés
        if t:
            print(f"       ex. embed_text[{p.ean}]: {t[:160]}")
            break

    if args.no_embed:
        embeddings: list[list[float] | None] = [None] * len(products)
        print("[3/4] Embeddings : SKIP (--no-embed)")
    else:
        embeddings = embed_products(products, texts)
        n_emb = sum(e is not None for e in embeddings)
        dim = len(next((e for e in embeddings if e), []))
        print(f"[3/4] Embeddings Vertex : {n_emb} vecteurs (dim {dim})")

    write_artifact(args.out, products, texts, embeddings)
    size_mb = args.out.stat().st_size / 1e6
    print(f"[4/4] Artefact écrit : {args.out} ({size_mb:.1f} MB) en {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
