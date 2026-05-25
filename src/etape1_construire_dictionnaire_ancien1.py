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
LIMITE_TICKETS = 1    #5000
 
 
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
        print(f"  [{compteur+1}/{LIMITE_TICKETS}] OCR sur ticket {enseigne}...")
        lignes_ticket = extraire_libelles_depuis_image(url_image)
 
        for libelle_brut in lignes_ticket:
            # ── Filtres de longueur ────────────────────────────────────────────
            if len(libelle_brut) < 4 or len(libelle_brut) > 45:
                continue
 
            # ── Ignorer les lignes qui ne contiennent que des chiffres/symboles ─
            sans_espaces = libelle_brut.replace(" ", "").replace(",", "").replace(".", "")
            if sans_espaces.isdigit():
                continue
 
            libelle_lower = libelle_brut.lower()
 
            # ── Ignorer les lignes parasites (en-têtes, totaux, infos magasin) ──
            MOTS_PARASITES = [
                # Totaux et paiement
                "total", "tva", "ttc", "ht ", "sous-total", "remise",
                "cb ", "carte", "visa", "mastercard", "espece", "rendu", "monnaie",
                "avoir", "fidelite", "points", "cagnotte",
                # En-têtes de colonne
                "description", "qte", "p.u.", "montant", "designation",
                # Infos magasin / ticket
                "ouvert", "lundi", "mardi", "mercredi", "jeudi", "vendredi",
                "samedi", "dimanche", "8h", "9h", "10h", "22h", "20h",
                "merci", "bienvenue", "ticket", "caisse", "siret", "siren",
                "tel ", "tél", "www.", "http", "@",
                "paris", "lyon", "marseille", "bordeaux", "rue ", "avenue",
                "article(s)", "articles",
            ]
            if any(mot in libelle_lower for mot in MOTS_PARASITES):
                continue
 
            # ── Ignorer les lignes qui sont juste des prix ou codes ────────────
            # Ex: "12,61€"  ou  "0,65 11,96"  ou  "h> 5,50 0,47"
            if re.match(r"^[a-z>*]{0,2}\s*[\d,. €%]+$", libelle_lower):
                continue
 
            libelle_normalise = normaliser_libelle(libelle_brut)
 
            if libelle_normalise not in dictionnaire:
                dictionnaire[libelle_normalise] = {
                    "ean":              ean,
                    "libelle_original": libelle_brut,
                    "enseigne":         enseigne,
                    "produit_nom":      nom_produit or marque,
                }
 
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
 