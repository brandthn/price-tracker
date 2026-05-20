"""
Enrichissements et validations supplémentaires de la couche Silver.

Ce module ajoute 5 transformations qui complètent le cleaner de base :

  1. Normalisation du store_brand
     L'adresse OSM complète ("Auchan Supermarché, 14, Rue Lobau, Nancy...")
     est réduite au nom d'enseigne canonique ("Auchan") pour que les agrégats
     Gold regroupent correctement tous les magasins d'une même chaîne.

  2. Standardisation de la ville
     "PARIS", "Paris 17e Arrondissement", "paris" → "Paris"
     Normalise la casse et supprime les suffixes d'arrondissement.

  3. Validation EAN-13
     Vérifie que product_code est un code-barres valide :
     - 13 chiffres numériques
     - Checksum modulo 10 correct
     Un EAN invalide ne vient pas d'un scanner de caisse → donnée douteuse.

  4. Cohérence prix remisé / prix normal
     Si price_is_discounted=True et price_without_discount est renseigné,
     alors price_without_discount DOIT être strictement supérieur à price_eur.
     Sinon la remise n'a aucun sens (on ne peut pas vendre plus cher qu'avant).

  5. Détection de prix suspects (IQR)
     Pour chaque produit, on calcule sur l'ensemble des lignes acceptées :
       - Q1 (1er quartile), Q3 (3ème quartile)
       - IQR = Q3 - Q1 (intervalle interquartile)
       - Borne basse  = Q1 - 3 × IQR
       - Borne haute  = Q3 + 3 × IQR
     Tout prix hors de cet intervalle est statistiquement aberrant.
     Le facteur 3 (vs le classique 1.5) est volontairement large pour ne pas
     rejeter des promotions légitimes ni des produits premium.
     Cette étape est une passe post-traitement (nécessite toutes les lignes).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# 1. NORMALISATION DU STORE_BRAND
# ──────────────────────────────────────────────────────────────────────────────

# Liste des enseignes connues, ordonnée du plus spécifique au plus général.
# L'ordre est important : "Carrefour Market" doit être testé avant "Carrefour"
# pour éviter de capturer "Carrefour Market" → "Carrefour".
# Chaque entrée : (pattern regex, nom canonique)
_BRAND_PATTERNS: List[Tuple[str, str]] = [
    # Leclerc (toutes variantes)
    (r"e\.?\s*leclerc|centre\s+commercial\s+e\.?\s*leclerc", "E.Leclerc"),
    # Carrefour
    (r"carrefour\s+city",           "Carrefour City"),
    (r"carrefour\s+market",         "Carrefour Market"),
    (r"carrefour\s+express",        "Carrefour Express"),
    (r"carrefour",                  "Carrefour"),
    # Auchan
    (r"auchan\s+supermarché|auchan\s+supermarche", "Auchan Supermarché"),
    (r"auchan\s+hypermarché|auchan\s+hypermarche", "Auchan Hypermarché"),
    (r"auchan",                     "Auchan"),
    # Intermarché
    (r"intermarché|intermarche",    "Intermarché"),
    # Super U / U Express / Hyper U
    (r"hyper\s+u\b",                "Hyper U"),
    (r"u\s+express",                "U Express"),
    (r"super\s+u\b",                "Super U"),
    (r"\bu\s+marché|\bu\s+marche",  "U Marché"),
    # Lidl / Aldi
    (r"\blidl\b",                   "Lidl"),
    (r"\baldi\b",                   "Aldi"),
    # Monoprix / Monop'
    (r"monop['']?",                 "Monoprix"),
    (r"monoprix",                   "Monoprix"),
    # Franprix
    (r"franprix",                   "Franprix"),
    # Casino / Géant Casino
    (r"géant\s+casino|geant\s+casino", "Géant Casino"),
    (r"\bcasino\b",                 "Casino"),
    # Netto
    (r"\bnetto\b",                  "Netto"),
    # Biocoop
    (r"biocoop",                    "Biocoop"),
    # La Vie Claire
    (r"la\s+vie\s+claire",          "La Vie Claire"),
    # Picard
    (r"\bpicard\b",                 "Picard"),
    # Action
    (r"\baction\b",                 "Action"),
    # Diagonal (hard-discount régional)
    (r"\bdiagonal\b",               "Diagonal"),
    # Grand Frais
    (r"grand\s+frais",              "Grand Frais"),
    # Cora
    (r"\bcora\b",                   "Cora"),
    # Match
    (r"\bmatch\b",                  "Match"),
]

# Pré-compilation des patterns pour la performance (évite de recompiler à chaque appel)
_COMPILED_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), canonical)
    for pattern, canonical in _BRAND_PATTERNS
]


def normalize_store_brand(raw_store_brand: Optional[str]) -> Optional[str]:
    """
    Extrait le nom canonique de l'enseigne depuis l'adresse OSM complète.

    L'adresse OSM suit en général le format :
        "Nom du magasin, Numéro, Rue, Quartier, Ville, Département, Région..."

    On cherche d'abord un pattern d'enseigne connue dans toute la chaîne.
    Si aucune enseigne n'est reconnue, on retourne le premier segment avant
    la première virgule (le nom du POI OSM), nettoyé.

    Args:
        raw_store_brand: Valeur brute du champ store_brand (adresse OSM)

    Returns:
        Nom canonique de l'enseigne, ou le premier segment si inconnu, ou None
    """
    if not raw_store_brand:
        return None

    # Recherche d'une enseigne connue dans toute la chaîne
    for compiled_pattern, canonical in _COMPILED_PATTERNS:
        if compiled_pattern.search(raw_store_brand):
            return canonical

    # Fallback : premier segment avant la virgule, limité à 80 caractères
    first_segment = raw_store_brand.split(",")[0].strip()
    if first_segment:
        return first_segment[:80]

    return None


# ──────────────────────────────────────────────────────────────────────────────
# 2. STANDARDISATION DE LA VILLE
# ──────────────────────────────────────────────────────────────────────────────

# Patterns de suffixes à supprimer après le nom de ville principal
# Exemples : "Paris 17e Arrondissement", "Lyon 7e Arrondissement", "Marseille 13e"
_ARRONDISSEMENT_PATTERN = re.compile(
    r'\s+\d+\s*(e|er|ème|eme|ième|ieme)?\s*(arrondissement)?$',
    re.IGNORECASE
)


def standardize_city(raw_city: Optional[str]) -> Optional[str]:
    """
    Normalise le nom de ville pour unifier les variantes d'une même commune.

    Transformations appliquées dans l'ordre :
      1. Strip des espaces
      2. Suppression des diacritiques pour la comparaison (stockage conserve les accents)
      3. Title case (Première lettre de chaque mot en majuscule)
      4. Suppression des suffixes d'arrondissement ("17e Arrondissement")

    Exemples :
      "PARIS"                    → "Paris"
      "paris 17e Arrondissement" → "Paris"
      "LYON 7e"                  → "Lyon"
      "marseille"                → "Marseille"
      "Échirolles"               → "Échirolles"  (accents préservés)

    Args:
        raw_city: Valeur brute du champ city

    Returns:
        Nom de ville normalisé, ou None si vide
    """
    if not raw_city:
        return None

    city = raw_city.strip()
    if not city:
        return None

    # Title case : "PARIS 17E ARRONDISSEMENT" → "Paris 17E Arrondissement"
    city = city.title()

    # Suppression du suffixe d'arrondissement
    city = _ARRONDISSEMENT_PATTERN.sub("", city).strip()

    return city if city else None


# ──────────────────────────────────────────────────────────────────────────────
# 3. VALIDATION EAN-13
# ──────────────────────────────────────────────────────────────────────────────

def validate_ean(product_code: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Valide qu'un code produit est un EAN-13 (ou EAN-8) valide.

    Algorithme de checksum EAN-13 :
      - Prendre les 12 premiers chiffres
      - Alterner les poids 1 et 3 (positions paires × 1, impaires × 3)
      - Somme modulo 10 → si résultat ≠ 0, chiffre de contrôle = 10 - résultat
      - Le 13e chiffre doit correspondre au chiffre de contrôle calculé

    Exemple : 3560070283484
      Digits: 3 5 6 0 0 7 0 2 8 3 4 8 [4]
      Poids:  1 3 1 3 1 3 1 3 1 3 1 3
      Produits: 3+15+6+0+0+21+0+6+8+9+4+24 = 96
      96 % 10 = 6 → check = 10 - 6 = 4 ✓

    Args:
        product_code: Code produit à valider

    Returns:
        (True, None) si valide
        (False, "raison") si invalide
    """
    if not product_code:
        return False, "product_code vide"

    code = str(product_code).strip()

    # On accepte EAN-8 (petit emballage) et EAN-13 (standard)
    if not code.isdigit():
        return False, f"contient des caractères non numériques: '{code}'"

    if len(code) == 8:
        # EAN-8 checksum : alternance 3,1 (inverse de EAN-13)
        digits = [int(d) for d in code]
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        expected = (10 - (total % 10)) % 10
        if digits[-1] != expected:
            return False, f"checksum EAN-8 invalide (attendu {expected}, reçu {digits[-1]})"
        return True, None

    if len(code) == 13:
        # EAN-13 checksum : alternance 1,3
        digits = [int(d) for d in code]
        total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[:-1]))
        expected = (10 - (total % 10)) % 10
        if digits[-1] != expected:
            return False, f"checksum EAN-13 invalide (attendu {expected}, reçu {digits[-1]})"
        return True, None

    return False, f"longueur invalide: {len(code)} chiffres (attendu 8 ou 13)"


# ──────────────────────────────────────────────────────────────────────────────
# 4. COHÉRENCE PRIX REMISÉ / PRIX NORMAL
# ──────────────────────────────────────────────────────────────────────────────

def check_discount_coherence(row: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Vérifie la cohérence entre le prix remisé et le prix d'origine.

    Règles métier vérifiées :
      - Si price_is_discounted=True ET price_without_discount est renseigné :
          price_without_discount DOIT être > price_eur
          (on ne peut pas vendre plus cher que le prix "sans remise")
      - Si price_is_discounted=True MAIS price_without_discount est nul :
          C'est un avertissement, pas un rejet (l'enseigne n'a pas renseigné
          le prix d'origine — courant en grande distribution)

    Args:
        row: Dictionnaire de la ligne nettoyée (post-cleaner)

    Returns:
        (True, None)           → cohérent
        (False, "explication") → incohérent → rejet
    """
    is_discounted = row.get("price_is_discounted", False)
    price_eur = row.get("price_eur")
    price_without_discount = row.get("price_without_discount_eur")

    if not is_discounted:
        return True, None

    # Cas : remisé=True mais prix d'origine absent → acceptable
    if price_without_discount is None:
        return True, None

    # Cas : prix d'origine doit être strictement supérieur au prix remisé
    if price_without_discount <= price_eur:
        return False, (
            f"prix remisé ({price_eur}€) ≥ prix sans remise ({price_without_discount}€)"
        )

    # Sanity check : remise > 95% est suspect (probablement une erreur de saisie)
    discount_pct = (price_without_discount - price_eur) / price_without_discount
    if discount_pct > 0.95:
        return False, (
            f"remise de {discount_pct:.0%} trop importante "
            f"({price_eur}€ vs {price_without_discount}€ sans remise)"
        )

    return True, None


# ──────────────────────────────────────────────────────────────────────────────
# 5. DÉTECTION DE PRIX SUSPECTS (IQR — passe post-traitement)
# ──────────────────────────────────────────────────────────────────────────────

def compute_price_bounds(
    clean_rows: List[Dict[str, Any]],
    iqr_factor: float = 3.0,
    min_samples: int = 5,
) -> Dict[str, Tuple[float, float]]:
    """
    Calcule les bornes de prix acceptables par produit via la méthode IQR.

    Pourquoi l'IQR plutôt que moyenne ± n*σ ?
        La moyenne est sensible aux outliers. Si un produit coûte normalement
        1.50€ mais qu'une saisie aberrante à 150€ est dans les données, la
        moyenne serait tirée vers le haut et le seuil serait biaisé.
        L'IQR (Q3-Q1) ne dépend que de la moitié centrale des données :
        il est robuste aux valeurs extrêmes existantes.

    Formule :
        borne_basse = Q1 - iqr_factor × IQR   (plancher à 0.01€ minimum)
        borne_haute = Q3 + iqr_factor × IQR

    Avec iqr_factor=3 (vs le classique 1.5 de Tukey) on est très permissif
    pour ne pas rejeter des promotions légitimes ou des achats en gros.

    Args:
        clean_rows:  Liste des lignes Silver acceptées (post-cleaner)
        iqr_factor:  Multiplicateur de l'IQR (3.0 par défaut = très permissif)
        min_samples: Nombre minimum d'observations pour calculer des bornes.
                     En dessous, on ne calcule pas (trop peu de données = biais).

    Returns:
        Dict {product_code → (borne_basse, borne_haute)}
    """
    if not clean_rows:
        return {}

    df = pd.DataFrame([
        {"product_code": r.get("product_code"), "price_eur": r.get("price_eur")}
        for r in clean_rows
        if r.get("product_code") and r.get("price_eur") is not None
    ])

    if df.empty:
        return {}

    bounds: Dict[str, Tuple[float, float]] = {}

    for product_code, group in df.groupby("product_code"):
        if len(group) < min_samples:
            # Pas assez de données pour établir des bornes fiables
            continue

        prices = group["price_eur"]
        q1 = float(prices.quantile(0.25))
        q3 = float(prices.quantile(0.75))
        iqr = q3 - q1

        lower = max(0.01, q1 - iqr_factor * iqr)
        upper = q3 + iqr_factor * iqr

        bounds[str(product_code)] = (lower, upper)

    return bounds


def flag_suspicious_prices(
    clean_rows: List[Dict[str, Any]],
    price_bounds: Dict[str, Tuple[float, float]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Sépare les lignes en deux groupes selon les bornes IQR calculées.

    Une ligne est "suspecte" si son prix est hors de la plage calculée
    pour ce produit. Les lignes de produits sans bornes (trop peu d'observations)
    sont gardées telles quelles — on ne peut pas les évaluer.

    Args:
        clean_rows:   Lignes Silver acceptées par le cleaner
        price_bounds: Dict {product_code → (borne_basse, borne_haute)}

    Returns:
        (lignes_ok, lignes_suspectes)
    """
    ok: List[Dict[str, Any]] = []
    suspicious: List[Dict[str, Any]] = []

    for row in clean_rows:
        product_code = str(row.get("product_code", ""))
        price = row.get("price_eur")

        if product_code not in price_bounds or price is None:
            # Pas de bornes pour ce produit → on garde sans juger
            ok.append(row)
            continue

        lower, upper = price_bounds[product_code]
        if lower <= price <= upper:
            ok.append(row)
        else:
            # On ajoute des métadonnées pour comprendre le rejet
            suspicious_row = dict(row)
            suspicious_row["reason"] = "SUSPICIOUS_PRICE_IQR"
            suspicious_row["details"] = (
                f"Prix {price}€ hors plage [{lower:.2f}€ ; {upper:.2f}€] "
                f"pour produit {product_code}"
            )
            suspicious_row["rejected_at"] = pd.Timestamp.utcnow().isoformat()
            suspicious.append(suspicious_row)

    return ok, suspicious
