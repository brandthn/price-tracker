"""
ÉTAPE 1 — Construire le dictionnaire EAN ↔ Libellés

Ce fichier fait une seule chose :
  - Il télécharge les données Open Food Facts + Open Prices
  - Il lit les photos de tickets (proof_file_path) et en extrait les libellés via OCR
  - Il sauvegarde un dictionnaire  libellé → produit  dans un fichier JSON

Tu n'as besoin de lancer ce fichier QU'UNE SEULE FOIS (ou quand tu veux mettre à jour la base).
"""

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from datasets import load_dataset
from PIL import Image
import pytesseract          # OCR : lit le texte dans une image
import io


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Où on va sauvegarder notre dictionnaire final
CHEMIN_DICTIONNAIRE = Path("data/dictionnaire_libelles.json")
CHEMIN_PRODUITS     = Path("data/produits_canoniques.json")

# Nombre de tickets à traiter (mets None pour tout traiter, mais c'est long !)
LIMITE_TICKETS = 7    #5000


# ─────────────────────────────────────────────────────────────────────────────
# FONCTIONS UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────────

def normaliser_libelle(texte: str) -> str:
    """
    Nettoie un libellé pour faciliter la comparaison.

    Exemple :
        "  Évian 1.5L  6X !!"  →  "evian 1.5l 6x"

    On fait ça parce que les tickets ont souvent des accents manquants,
    des espaces en trop, des majuscules, etc.
    """
    if not texte:
        return ""

    # 1. Tout en minuscules
    texte = texte.lower()

    # 2. Supprimer les accents  (é → e, à → a, etc.)
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")

    # 3. Supprimer les caractères spéciaux sauf chiffres, lettres, espaces, points
    texte = re.sub(r"[^a-z0-9 .]", " ", texte)

    # 4. Supprimer les espaces multiples
    texte = re.sub(r"\s+", " ", texte).strip()

    return texte


BASE_URL_IMAGES = "https://prices.openfoodfacts.org/img/"

def extraire_libelles_depuis_image(url_image: str) -> list[str]:
    """
    Prend l'URL d'une photo de ticket de caisse,
    et retourne la liste des lignes de texte lues par l'OCR.

    Exemple de retour :
        ["EVIAN 1.5L 6X", "YAOURT DANONE X4", "TOTAL  12.34€"]
    """
    try:
        # Construire l'URL complète si nécessaire
        if not url_image.startswith("http"):
            url_image = BASE_URL_IMAGES + url_image

        # Télécharger l'image
        reponse = requests.get(url_image, timeout=10)
        image = Image.open(io.BytesIO(reponse.content))

        # Lancer l'OCR (tesseract lit l'image et retourne du texte)
        # lang="fra" = français, mais les tickets mélangent souvent fr/en
        texte_brut = pytesseract.image_to_string(image, lang="fra+eng")

        # Découper en lignes et nettoyer les lignes vides
        lignes = [ligne.strip() for ligne in texte_brut.split("\n") if ligne.strip()]

        return lignes

    except Exception as e:
        # Si l'image est inaccessible ou corrompue, on passe
        print(f"  ⚠️  Image inaccessible : {e}")
        return []


ENSEIGNES_CONNUES = [
    "carrefour", "leclerc", "monoprix", "intermarche", "intermarché",
    "auchan", "lidl", "aldi", "casino", "franprix", "super u", "superu",
    "cora", "match", "netto", "picard", "biocoop", "naturalia",
]

def detecter_enseigne(row) -> str:
    """
    Essaie de trouver le nom de l'enseigne à partir des métadonnées Open Prices.
    On cherche dans PLUSIEURS champs car le dataset n'est pas toujours cohérent.
    """
    # Tous les champs qui peuvent contenir le nom de l'enseigne
    champs_a_tester = [
        row.get("location_name"),           # ex: "Carrefour Market Paris"
        row.get("location_display_name"),   # ex: "Carrefour, Rue de Rivoli, Paris"
        row.get("location_osm_name"),       # ex: "Carrefour Market"
    ]

    for valeur in champs_a_tester:
        if not valeur or (isinstance(valeur, float)):  # ignore None et NaN
            continue
        nom = str(valeur).lower()
        for enseigne in ENSEIGNES_CONNUES:
            if enseigne in nom:
                # Normaliser : "intermarché" → "Intermarché", "super u" → "Super U"
                return enseigne.title()

    return "Inconnue"


# Cache pour éviter de requêter OFF plusieurs fois pour le même EAN
_cache_off: dict = {}

def recuperer_nom_produit_off(ean: str) -> tuple[str, str]:
    """
    Interroge l'API Open Food Facts pour obtenir le nom et la marque d'un produit
    à partir de son EAN, quand open-prices ne les fournit pas.

    Retourne (nom_produit, marque).
    """
    if ean in _cache_off:
        return _cache_off[ean]

    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{ean}?fields=product_name,brands"
        r = requests.get(url, timeout=8, headers={"User-Agent": "PriceTracker/1.0"})
        data = r.json()
        if data.get("status") == 1:
            produit = data.get("product", {})
            nom    = produit.get("product_name") or ""
            marque = produit.get("brands") or ""
            _cache_off[ean] = (nom, marque)
            return nom, marque
    except Exception:
        pass

    _cache_off[ean] = ("", "")
    return "", ""



def detecter_enseigne_depuis_ocr(lignes: list[str]) -> str | None:
    """
    Si les métadonnées ne donnent pas l'enseigne, on la cherche
    dans les premières lignes du ticket OCR.
    Les tickets affichent toujours le nom du magasin en haut.
    """
    for ligne in lignes[:6]:  # on ne regarde que les 6 premières lignes
        ligne_lower = ligne.lower()
        for enseigne in ENSEIGNES_CONNUES:
            if enseigne in ligne_lower:
                return enseigne.title()
    return None


def trouver_ligne_produit(lignes: list[str], nom_produit: str, marque: str) -> str | None:
    """
    Cherche dans les lignes OCR du ticket CELLE qui correspond au produit connu.

    Stratégie : on prend les mots significatifs du nom produit (ex: "Épinards hachés")
    → mots-clés = ["epinar", "hache"]  (on tronque à 6 lettres pour tolérer les variations)
    → on cherche la ligne qui contient le plus de ces mots-clés

    Retourne la ligne brute si trouvée, None sinon.
    """
    if not nom_produit and not marque:
        return None

    # Construire les mots-clés à partir du nom produit + marque
    # On normalise et on ne garde que les mots de 4+ lettres (les courts sont du bruit)
    reference = normaliser_libelle(f"{nom_produit} {marque}")
    mots_cles = [mot[:6] for mot in reference.split() if len(mot) >= 4]
    # ([:6] = on tronque à 6 lettres pour matcher "epinard" et "epinards" pareil)

    if not mots_cles:
        return None

    meilleure_ligne = None
    meilleur_score  = 0

    for ligne in lignes:
        ligne_norm = normaliser_libelle(ligne)
        # Compter combien de mots-clés sont présents dans cette ligne
        score = sum(1 for mc in mots_cles if mc in ligne_norm)
        # On exige au moins la moitié des mots-clés pour valider
        seuil = max(1, len(mots_cles) // 2)
        if score >= seuil and score > meilleur_score:
            meilleur_score  = score
            meilleure_ligne = ligne

    return meilleure_ligne


def construire_dictionnaire():
    """
    Fonction principale : construit et sauvegarde le dictionnaire.
    """
    print("📥 Chargement du dataset Open Prices depuis Hugging Face...")

    # Charger uniquement les colonnes dont on a besoin (plus rapide)
    dataset = load_dataset(
        "openfoodfacts/open-prices",
        split="prices",
        streaming=True   # streaming = on ne télécharge pas tout d'un coup
    )

    # ── Dictionnaire final ────────────────────────────────────────────────────
    # Structure :
    # {
    #   "evian 1.5l 6x": {
    #       "ean": "3068320113530",
    #       "libelle_original": "EVIAN 1.5L 6X",
    #       "enseigne": "Carrefour",
    #       "produit_nom": "Evian eau minérale naturelle"
    #   },
    #   ...
    # }
    dictionnaire = {}

    # ── Table des produits canoniques (regroupement multi-EAN) ────────────────
    # Structure :
    # {
    #   "3068320113530": {
    #       "nom": "Evian Eau Minérale 1.5L",
    #       "marque": "Evian",
    #       "categorie": "Eaux minérales",
    #       "unite": "l",
    #       "quantite": 1.5,
    #       "eans_lies": ["3068320113530", "3068320008773"]
    #   }
    # }
    produits = {}

    print(f"🔄 Traitement des {LIMITE_TICKETS} premiers tickets...")
    compteur = 0

    for ligne in dataset:
        if LIMITE_TICKETS and compteur >= LIMITE_TICKETS:
            break

        ean           = ligne.get("product_code")
        url_image     = ligne.get("proof_file_path")
        nom_produit   = ligne.get("product_name") or ""
        marque        = ligne.get("product_brands") or ""

        # On saute les lignes sans EAN ni image
        if not ean or not url_image:
            continue

        enseigne = detecter_enseigne(ligne)

        # ── Récupérer le nom produit (depuis open-prices ou l'API OFF) ─────────
        if not nom_produit and not marque:
            nom_produit, marque = recuperer_nom_produit_off(ean)

        # ── Enregistrer le produit canonique ──────────────────────────────────
        if ean not in produits:
            produits[ean] = {
                "nom":       nom_produit,
                "marque":    marque,
                "categorie": ligne.get("product_categories_tags", [""])[0] if ligne.get("product_categories_tags") else "",
                "unite":     ligne.get("product_quantity_unit") or "",
                "quantite":  ligne.get("product_quantity") or 0,
                "eans_lies": [ean]
            }
        else:
            # Le produit existe déjà → on l'enrichit si on a plus d'infos
            if not produits[ean]["nom"] and nom_produit:
                produits[ean]["nom"] = nom_produit

        # ── Extraire les libellés depuis la photo du ticket ───────────────────
        print(f"  [{compteur+1}/{LIMITE_TICKETS}] OCR sur ticket {enseigne} — {nom_produit or ean}...")
        lignes_ticket = extraire_libelles_depuis_image(url_image)

        # Détecter l'enseigne depuis le texte OCR si pas trouvée dans les métadonnées
        if enseigne == "Inconnue":
            enseigne = detecter_enseigne_depuis_ocr(lignes_ticket) or "Inconnue"

        # On cherche UNIQUEMENT la ligne du ticket qui correspond au produit connu
        libelle_trouve = trouver_ligne_produit(lignes_ticket, nom_produit, marque)

        if libelle_trouve:
            libelle_normalise = normaliser_libelle(libelle_trouve)
            if libelle_normalise and libelle_normalise not in dictionnaire:
                dictionnaire[libelle_normalise] = {
                    "ean":              ean,
                    "libelle_original": libelle_trouve,
                    "enseigne":         enseigne,
                    "produit_nom":      nom_produit or marque,
                }
                print(f"     ✅ '{libelle_trouve}'  →  {nom_produit}")
        else:
            print(f"     ⚠️  Aucune ligne trouvée pour '{nom_produit}'")

        compteur += 1

    # ── Sauvegarder ───────────────────────────────────────────────────────────
    Path("data").mkdir(exist_ok=True)

    with open(CHEMIN_DICTIONNAIRE, "w", encoding="utf-8") as f:
        json.dump(dictionnaire, f, ensure_ascii=False, indent=2)

    with open(CHEMIN_PRODUITS, "w", encoding="utf-8") as f:
        json.dump(produits, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Dictionnaire sauvegardé : {len(dictionnaire)} libellés connus")
    print(f"✅ Produits canoniques    : {len(produits)} produits uniques")


if __name__ == "__main__":
    construire_dictionnaire()
