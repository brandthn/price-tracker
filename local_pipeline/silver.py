"""
Couche SILVER — Nettoyage, validation et standardisation.

Objectif de la couche Silver :
    Transformer la donnée brute (Bronze) en une donnée de confiance :
    types corrects, valeurs normalisées, lignes invalides isolées avec
    la raison du rejet.

    C'est ici que réside la plus grande valeur métier du pipeline :
    une règle de validation floue en Bronze devient un rejet traçable
    en Silver. Les analystes peuvent ensuite FAIRE CONFIANCE aux données
    Silver sans se poser de questions sur la qualité.

Architecture de décision (par ligne) :
    Bronze row
        │
        ├─[hf_mapping]────────────→ Adapte les noms de colonnes HF → cleaner
        ├─[cleaner]───────────────→ Valide prix/devise/pays/date → rejet si invalide
        ├─[validate_ean]──────────→ Vérifie le checksum EAN-13/8 → rejet si invalide
        ├─[check_discount]────────→ Cohérence prix remisé/normal → rejet si incohérent
        ├─[normalize_store_brand]─→ "Auchan Supermarché, Rue..." → "Auchan"
        └─[standardize_city]──────→ "PARIS 17e Arrondissement" → "Paris"
               │
               ├─ OUI → clean_rows (buffer)
               └─ NON → openpricesrejections.parquet + raison

    Post-traitement (sur toutes les lignes acceptées) :
        └─[flag_suspicious_prices]─→ IQR × 3 par produit → écarte les aberrants

Quality Gates (bloquants) :
    - Taux d'acceptation ≥ 40% (QUALITY_GATE_ACCEPTANCE_RATE)
    - Couverture enseigne ≥ 70% (QUALITY_GATE_STORE_COVERAGE)
    Si un gate échoue, le pipeline s'arrête avec une exception explicite.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import decimal

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.cleaner import CleanerConfig, clean_price_record   # noqa: E402
from shared.hf_mapping import hf_open_prices_row_to_cleaner_record  # noqa: E402
from local_pipeline.silver_enrichments import (   # noqa: E402
    normalize_store_brand,
    standardize_city,
    validate_ean,
    check_discount_coherence,
    compute_price_bounds,
    flag_suspicious_prices,
)

# ──────────────────────────────────────────────────────────────────────────────
# Chemins locaux
# ──────────────────────────────────────────────────────────────────────────────

BRONZE_PARQUET = _REPO_ROOT / "data" / "bronze" / "open_prices.parquet"
SILVER_DIR     = _REPO_ROOT / "data" / "silver"
CLEAN_PARQUET  = SILVER_DIR / "openpricesclean.parquet"
REJECT_PARQUET = SILVER_DIR / "openpricesrejections.parquet"
METRICS_JSON   = SILVER_DIR / "_metrics.json"

# Quality gates locaux.
# Le dataset HuggingFace est mondial : beaucoup de lignes seront rejetées car hors
# périmètre France/DOM. Un taux de 40% est donc réaliste et acceptable en local.
# En production GCP, le seuil est 60% car on ingère un snapshot pré-filtré France.
GATE_ACCEPTANCE_RATE  = 0.40
GATE_STORE_COVERAGE   = 0.70


class QualityGateError(RuntimeError):
    """Levée quand un quality gate bloquant échoue."""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internes
# ──────────────────────────────────────────────────────────────────────────────

def _iter_bronze_rows(parquet_path: Path, batch_size: int = 50_000) -> Iterator[Dict[str, Any]]:
    """
    Lit le Parquet Bronze par batches pour limiter la consommation mémoire.

    En production avec 10M de lignes, charger tout en RAM en une fois
    ferait exploser la mémoire du pod Cloud Run. Le batch_size de 50k
    est un bon compromis performance / mémoire.
    """
    pf = pd.read_parquet(parquet_path, engine="pyarrow")
    for i in range(0, len(pf), batch_size):
        batch = pf.iloc[i : i + batch_size]
        for _, row in batch.iterrows():
            # Convertit la Series pandas en dict Python natif
            # (le cleaner attend des types Python standards, pas des numpy types)
            yield {k: (None if pd.isna(v) else v) for k, v in row.items()}


def _json_default(obj: Any) -> Any:
    """
    Sérialiseur JSON pour les types non standards présents dans raw_payload.

    Le cleaner recopie le dict brut tel quel dans raw_payload, ce qui peut
    contenir des Decimal (prix parsés), des date/datetime (dates parsées),
    ou des types numpy si la source est un DataFrame.
    """
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    # Fallback numpy scalars (int64, float32, etc.)
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"Type non sérialisable : {type(obj).__name__}")


def _sanitize_for_parquet(value: Any) -> Any:
    """
    Normalise les valeurs avant écriture Parquet.

    Pyarrow est strict sur les types. Un mélange float/None dans une colonne
    provoque une erreur si on ne force pas le type. On normalise ici plutôt
    qu'au niveau du cleaner pour garder celui-ci indépendant du format de sortie.
    """
    if value is None:
        return None
    if isinstance(value, float) and (value != value):   # NaN IEEE 754
        return None
    if isinstance(value, dict):
        # raw_payload contient parfois des Decimal (prix parsés par le cleaner).
        # json.dumps standard ne sait pas les sérialiser → _json_default les convertit.
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    return value


def _row_to_parquet_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    result = {k: _sanitize_for_parquet(v) for k, v in row.items()}
    # Force id en string pour éviter les conflits de types int/str entre les
    # rejets du cleaner (id numérique HF) et nos nouveaux rejets (id string).
    if "id" in result and result["id"] is not None:
        result["id"] = str(result["id"])
    return result


def _check_quality_gates(
    acceptance_rate: float,
    store_coverage: float,
    total: int,
) -> List[Dict[str, Any]]:
    """
    Évalue les quality gates et retourne leur statut.

    Principe :
        Un quality gate est un contrat de qualité qu'on passe avec les
        consommateurs de la couche Silver. S'il échoue, mieux vaut arrêter
        le pipeline que de publier de la data dégradée.
    """
    gates = [
        {
            "name":      "acceptance_rate",
            "value":     round(acceptance_rate, 4),
            "threshold": GATE_ACCEPTANCE_RATE,
            "passed":    acceptance_rate >= GATE_ACCEPTANCE_RATE,
        },
        {
            "name":      "store_brand_coverage",
            "value":     round(store_coverage, 4),
            "threshold": GATE_STORE_COVERAGE,
            "passed":    store_coverage >= GATE_STORE_COVERAGE,
        },
    ]

    failed = [g for g in gates if not g["passed"]]
    if failed:
        msgs = [
            f"{g['name']}={g['value']:.2%} < seuil={g['threshold']:.2%}"
            for g in failed
        ]
        raise QualityGateError(
            f"Quality gates échoués ({total} lignes traitées) : {'; '.join(msgs)}"
        )

    return gates


# ──────────────────────────────────────────────────────────────────────────────
# Fonction principale
# ──────────────────────────────────────────────────────────────────────────────

def run_silver(
    bronze_path: Optional[Path] = None,
    reference_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Exécute la couche Silver.

    Args:
        bronze_path:     Chemin vers le Parquet Bronze (défaut : BRONZE_PARQUET)
        reference_date:  Date de référence pour la validation des dates futures
                         (défaut : aujourd'hui UTC). Paramétrable pour les tests.

    Returns:
        Dictionnaire de métriques Silver.

    Raises:
        QualityGateError: Si un quality gate bloquant échoue.
    """
    bronze_path    = bronze_path or BRONZE_PARQUET
    reference_date = reference_date or date.today()
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    config     = CleanerConfig.default(reference_date=reference_date)

    print("\n" + "═" * 60)
    print("  SILVER — Nettoyage & validation")
    print("═" * 60)
    print(f"  [Silver] Source Bronze : {bronze_path}")

    # ── Lecture + transformation ligne à ligne ────────────────────────────────
    clean_rows:  List[Dict[str, Any]] = []
    reject_rows: List[Dict[str, Any]] = []
    total = 0
    with_brand = 0

    # Compteurs de rejets par raison (pour le rapport de qualité)
    rejection_counts: Dict[str, int] = {}

    # Compteurs pour les enrichissements (stats de la passe 1)
    ean_invalid_count      = 0
    discount_invalid_count = 0
    brand_normalized_count = 0
    city_normalized_count  = 0

    for raw_row in _iter_bronze_rows(bronze_path):
        total += 1

        # ── PASSE 1A : Mapping HF → format cleaner ────────────────────────────
        mapped = hf_open_prices_row_to_cleaner_record(raw_row)

        # ── PASSE 1B : Cleaner de base (devise/pays/prix/date) ────────────────
        clean_row, rejection = clean_price_record(mapped, config=config)

        if clean_row is None:
            if rejection is not None:
                reject_rows.append(_row_to_parquet_dict(rejection))
                reason = rejection.get("reason", "UNKNOWN")
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            if total % 2_000 == 0:
                print(f"  [Silver] {total:,} lignes traitées…", end="\r")
            continue

        # ── PASSE 1C : Validation EAN ─────────────────────────────────────────
        # On valide le code-barres APRÈS le cleaner car on a besoin que
        # product_code soit déjà normalisé (strip, None check) par le cleaner.
        ean_ok, ean_reason = validate_ean(clean_row.get("product_code"))
        if not ean_ok:
            ean_invalid_count += 1
            rej = {
                "id":           clean_row.get("id"),
                "product_code": clean_row.get("product_code"),
                "reason":       "INVALID_EAN",
                "details":      ean_reason,
                "currency":     clean_row.get("currency"),
                "raw_price":    str(clean_row.get("price_eur", "")),
                "price_date":   clean_row.get("price_date"),
                "country_code": clean_row.get("country_code"),
                "proof_type":   clean_row.get("proof_type"),
                "rejected_at":  datetime.now(timezone.utc).isoformat(),
                "raw_payload":  clean_row.get("raw_payload"),
            }
            reject_rows.append(rej)
            rejection_counts["INVALID_EAN"] = rejection_counts.get("INVALID_EAN", 0) + 1
            if total % 2_000 == 0:
                print(f"  [Silver] {total:,} lignes traitées…", end="\r")
            continue

        # ── PASSE 1D : Cohérence prix remisé ─────────────────────────────────
        discount_ok, discount_reason = check_discount_coherence(clean_row)
        if not discount_ok:
            discount_invalid_count += 1
            rej = {
                "id":           clean_row.get("id"),
                "product_code": clean_row.get("product_code"),
                "reason":       "INCOHERENT_DISCOUNT",
                "details":      discount_reason,
                "currency":     clean_row.get("currency"),
                "raw_price":    str(clean_row.get("price_eur", "")),
                "price_date":   clean_row.get("price_date"),
                "country_code": clean_row.get("country_code"),
                "proof_type":   clean_row.get("proof_type"),
                "rejected_at":  datetime.now(timezone.utc).isoformat(),
                "raw_payload":  clean_row.get("raw_payload"),
            }
            reject_rows.append(rej)
            rejection_counts["INCOHERENT_DISCOUNT"] = rejection_counts.get("INCOHERENT_DISCOUNT", 0) + 1
            if total % 2_000 == 0:
                print(f"  [Silver] {total:,} lignes traitées…", end="\r")
            continue

        # ── PASSE 1E : Enrichissements (ne rejettent pas, améliorent) ─────────

        # Normalisation du store_brand : adresse OSM → nom d'enseigne
        raw_brand = clean_row.get("store_brand")
        normalized_brand = normalize_store_brand(raw_brand)
        if normalized_brand != raw_brand:
            brand_normalized_count += 1
        clean_row = dict(clean_row)
        clean_row["store_brand"]            = raw_brand           # adresse complète conservée
        clean_row["store_brand_normalized"] = normalized_brand    # enseigne extraite (nouveau champ)

        # Standardisation de la ville : "PARIS 17e Arrondissement" → "Paris"
        raw_city = clean_row.get("city")
        std_city = standardize_city(raw_city)
        if std_city != raw_city:
            city_normalized_count += 1
        clean_row["city"] = std_city

        # ── Comptage pour quality gate ────────────────────────────────────────
        if clean_row.get("store_brand_normalized"):
            with_brand += 1

        clean_rows.append(_row_to_parquet_dict(clean_row))

        if total % 2_000 == 0:
            print(f"  [Silver] {total:,} lignes traitées…", end="\r")

    print(f"  [Silver] {total:,} lignes traitées — terminé.          ")

    # ── PASSE 2 : Détection des prix suspects par IQR ─────────────────────────
    # Cette passe nécessite d'avoir TOUTES les lignes acceptées pour calculer
    # les statistiques par produit. Elle ne peut donc pas se faire ligne par ligne.
    print("  [Silver] Détection des prix suspects (IQR)…")
    price_bounds = compute_price_bounds(clean_rows, iqr_factor=3.0, min_samples=5)
    clean_rows, suspicious_rows = flag_suspicious_prices(clean_rows, price_bounds)

    for s_row in suspicious_rows:
        rejection_counts["SUSPICIOUS_PRICE_IQR"] = rejection_counts.get("SUSPICIOUS_PRICE_IQR", 0) + 1
        reject_rows.append(_row_to_parquet_dict(s_row))

    n_suspicious = len(suspicious_rows)
    n_products_with_bounds = len(price_bounds)
    if n_suspicious:
        print(f"  [Silver] {n_suspicious} prix suspects écartés "
              f"(bornes calculées sur {n_products_with_bounds} produits)")

    # ── Calcul des taux finaux ─────────────────────────────────────────────────
    accepted = len(clean_rows)
    rejected = len(reject_rows)
    acceptance_rate = accepted / total if total else 0.0
    store_coverage  = with_brand / accepted if accepted else 0.0

    # ── Écriture des tables Silver ────────────────────────────────────────────
    if clean_rows:
        pd.DataFrame(clean_rows).to_parquet(CLEAN_PARQUET, index=False, engine="pyarrow")
        print(f"  [Silver] openpricesclean      → {CLEAN_PARQUET} ({accepted:,} lignes)")
    else:
        print("  [Silver] AVERTISSEMENT : aucune ligne propre !")

    if reject_rows:
        df_rej = pd.DataFrame(reject_rows)
        # La table de rejets est une table d'AUDIT, pas d'analyse.
        # On convertit toutes les colonnes en string pour éviter les conflits de
        # types entre les rejets du cleaner (types HF: int, date...) et nos
        # nouveaux rejets (types string). PyArrow est strict sur la cohérence.
        for col in df_rej.columns:
            df_rej[col] = df_rej[col].where(df_rej[col].notna(), other=None)
            df_rej[col] = df_rej[col].apply(
                lambda v: str(v) if v is not None else None
            )
        df_rej.to_parquet(REJECT_PARQUET, index=False, engine="pyarrow")
        print(f"  [Silver] openpricesrejections → {REJECT_PARQUET} ({rejected:,} lignes)")

    # ── Quality Gates ─────────────────────────────────────────────────────────
    print(f"\n  Taux d'acceptation : {acceptance_rate:.1%}  (seuil : {GATE_ACCEPTANCE_RATE:.0%})")
    print(f"  Couverture enseigne : {store_coverage:.1%}  (seuil : {GATE_STORE_COVERAGE:.0%})")

    quality_gates = _check_quality_gates(acceptance_rate, store_coverage, total)
    print("  Quality gates : ✓ TOUS PASSÉS")

    # ── Métriques ─────────────────────────────────────────────────────────────
    metrics: Dict[str, Any] = {
        "started_at":                  started_at,
        "finished_at":                 datetime.now(timezone.utc).isoformat(),
        "total_records":               total,
        "accepted_records":            accepted,
        "rejected_records":            rejected,
        "acceptance_rate":             round(acceptance_rate, 4),
        "store_brand_coverage":        round(store_coverage, 4),
        "rejections_by_reason":        dict(sorted(rejection_counts.items(), key=lambda x: -x[1])),
        "quality_gates":               quality_gates,
        # Statistiques des enrichissements
        "enrichments": {
            "brands_normalized":       brand_normalized_count,
            "cities_standardized":     city_normalized_count,
            "ean_rejected":            ean_invalid_count,
            "discount_rejected":       discount_invalid_count,
            "suspicious_price_rejected": n_suspicious,
            "products_with_iqr_bounds":  n_products_with_bounds,
        },
        "clean_parquet":               str(CLEAN_PARQUET),
        "reject_parquet":              str(REJECT_PARQUET),
    }
    METRICS_JSON.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"  [Silver] Métriques → {METRICS_JSON}")

    # ── Aperçu des rejets ─────────────────────────────────────────────────────
    if rejection_counts:
        print("\n  Répartition des rejets :")
        for reason, count in sorted(rejection_counts.items(), key=lambda x: -x[1]):
            pct = count / rejected * 100
            print(f"    {reason:<35} {count:>5} ({pct:.1f}%)")

    # ── Aperçu des enrichissements ────────────────────────────────────────────
    print("\n  Enrichissements appliqués :")
    print(f"    Enseignes normalisées   : {brand_normalized_count:,}")
    print(f"    Villes standardisées    : {city_normalized_count:,}")
    print(f"    EAN invalides rejetés   : {ean_invalid_count:,}")
    print(f"    Remises incohérentes    : {discount_invalid_count:,}")
    print(f"    Prix suspects (IQR)     : {n_suspicious:,}")

    return metrics
