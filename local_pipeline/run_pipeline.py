"""
Orchestrateur du pipeline local Bronze → Silver → Gold.

Ce script est le point d'entrée unique. Il enchaîne les trois couches
dans l'ordre et s'arrête proprement si une étape échoue.

La couche Bronze télécharge le dataset HuggingFace Open Prices et le
pré-filtre sur la France + DOM/TOM avant écriture. Silver nettoie,
valide et enrichit. Gold calcule les agrégats et indices.

Usage :
    # Pipeline complet (Bronze + Silver + Gold) :
    python local_pipeline/run_pipeline.py

    # Réutiliser un Bronze déjà téléchargé (saute le téléchargement HF) :
    python local_pipeline/run_pipeline.py --skip-bronze

    # Recalculer seulement Gold (Silver et Bronze déjà présents) :
    python local_pipeline/run_pipeline.py --only-gold

    # Depuis la racine du projet :
    python -m local_pipeline.run_pipeline

Sortie :
    data/
    ├── bronze/
    │   ├── open_prices.parquet     ← snapshot France filtré (Bronze)
    │   └── _metadata.json          ← traçabilité Bronze
    ├── silver/
    │   ├── openpricesclean.parquet     ← données validées (Silver)
    │   ├── openpricesrejections.parquet← lignes rejetées avec raison
    │   └── _metrics.json               ← métriques de qualité
    └── gold/
        ├── aggregatsenseignes.parquet  ← agrégats semaine/enseigne
        ├── indicesinflation.parquet    ← indice base 100
        ├── rankingsproduits.parquet    ← top hausses de prix
        └── anomaliesdetected.parquet   ← outliers z-score ≥ 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_pipeline.bronze import run_bronze                    # noqa: E402
from local_pipeline.silver import run_silver, QualityGateError  # noqa: E402
from local_pipeline.gold import run_gold                        # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline Bronze/Silver/Gold local — Open Prices France",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--skip-bronze",
        action="store_true",
        help="Saute la couche Bronze (utilise le Parquet existant dans data/bronze/)",
    )
    parser.add_argument(
        "--skip-silver",
        action="store_true",
        help="Saute la couche Silver (utilise le Parquet existant dans data/silver/)",
    )
    parser.add_argument(
        "--only-gold",
        action="store_true",
        help="Raccourci pour --skip-bronze --skip-silver",
    )
    return parser.parse_args()


def _section(title: str) -> None:
    print(f"\n{'━' * 60}")
    print(f"  {title}")
    print(f"{'━' * 60}")


def _print_final_summary(
    bronze_metrics: dict | None,
    silver_metrics: dict | None,
    gold_metrics: dict | None,
    elapsed: float,
) -> None:
    _section("RÉCAPITULATIF DU PIPELINE")

    if bronze_metrics:
        n_world = bronze_metrics.get("n_rows_total_world")
        n_fr    = bronze_metrics["n_rows"]
        pct     = bronze_metrics.get("pct_kept")
        if n_world:
            print(f"  Bronze  : {n_fr:>8,} lignes France  "
                  f"({n_world:,} monde → {pct}% conservés)")
        else:
            print(f"  Bronze  : {n_fr:>8,} lignes")

    if silver_metrics:
        accepted = silver_metrics["accepted_records"]
        rejected = silver_metrics["rejected_records"]
        rate     = silver_metrics["acceptance_rate"]
        print(f"  Silver  : {accepted:>8,} acceptées  "
              f"{rejected:>6,} rejetées  "
              f"(taux : {rate:.1%})")

    if gold_metrics:
        for tname, tinfo in gold_metrics["tables"].items():
            print(f"  Gold/{tname:<22} : {tinfo['n_rows']:>6,} lignes")

    print(f"\n  Durée totale : {elapsed:.1f}s")
    print(f"  Résultats dans : {_REPO_ROOT / 'data'}")


def main() -> None:
    args = _parse_args()

    if args.only_gold:
        args.skip_bronze = True
        args.skip_silver = True

    pipeline_start = time.time()
    bronze_metrics = silver_metrics = gold_metrics = None

    print("\n" + "█" * 60)
    print("  PIPELINE LOCAL : Bronze → Silver → Gold")
    print("  Open Prices France — Architecture Médaillon")
    print("█" * 60)
    print(f"  Démarré : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # ── COUCHE BRONZE ─────────────────────────────────────────────────────────
    if not args.skip_bronze:
        try:
            bronze_metrics = run_bronze()
        except Exception:
            print("\n  [ERREUR BRONZE] Arrêt du pipeline.")
            traceback.print_exc()
            sys.exit(1)
    else:
        print("\n  [Bronze] Étape sautée (--skip-bronze)")
        bronze_path = _REPO_ROOT / "data" / "bronze" / "open_prices.parquet"
        if not bronze_path.exists():
            print(f"  ERREUR : Aucun Parquet Bronze trouvé dans {bronze_path}")
            print("  Relancez sans --skip-bronze pour télécharger les données.")
            sys.exit(1)
        meta = _REPO_ROOT / "data" / "bronze" / "_metadata.json"
        if meta.exists():
            bronze_metrics = json.loads(meta.read_text())

    # ── COUCHE SILVER ─────────────────────────────────────────────────────────
    if not args.skip_silver:
        try:
            silver_metrics = run_silver()
        except QualityGateError as exc:
            print(f"\n  [QUALITY GATE ÉCHEC] {exc}")
            print("  Le pipeline s'arrête : publier la couche Gold avec des")
            print("  données Silver dégradées produirait des indicateurs faux.")
            sys.exit(1)
        except Exception:
            print("\n  [ERREUR SILVER] Arrêt du pipeline.")
            traceback.print_exc()
            sys.exit(1)
    else:
        print("\n  [Silver] Étape sautée (--skip-silver)")
        clean_path = _REPO_ROOT / "data" / "silver" / "openpricesclean.parquet"
        if not clean_path.exists():
            print(f"  ERREUR : Aucun Parquet Silver trouvé dans {clean_path}")
            print("  Relancez sans --skip-silver pour générer les données propres.")
            sys.exit(1)
        metrics_path = _REPO_ROOT / "data" / "silver" / "_metrics.json"
        if metrics_path.exists():
            silver_metrics = json.loads(metrics_path.read_text())

    # ── COUCHE GOLD ───────────────────────────────────────────────────────────
    try:
        gold_metrics = run_gold()
    except Exception:
        print("\n  [ERREUR GOLD] Arrêt du pipeline.")
        traceback.print_exc()
        sys.exit(1)

    # ── RÉSUMÉ ────────────────────────────────────────────────────────────────
    elapsed = time.time() - pipeline_start
    _print_final_summary(bronze_metrics, silver_metrics, gold_metrics, elapsed)

    print("\n  Pipeline terminé avec succès.\n")


if __name__ == "__main__":
    main()
