"""
ÉTAPE 1 — Construire le dictionnaire EAN ↔ Libellés (version LLM)

Ce fichier fait une seule chose :
  - Il parcourt le dataset Open Prices (Hugging Face)
  - Pour chaque entrée, il envoie la photo du ticket à Claude
  - Claude lit l'image et retourne directement un JSON propre :
      enseigne + liste de produits avec libellé/prix/quantité
  - On ne garde que la ligne qui correspond à l'EAN connu
  - On sauvegarde le dictionnaire  libellé_normalisé → produit

On n'a besoin de lancer ce fichier QU'UNE SEULE FOIS (ou périodiquement pour mise à jour).
"""

import base64
import json
import re
import time
import unicodedata
from pathlib import Path

#import anthropic
import requests
import yaml
import openai
from datasets import load_dataset


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

CHEMIN_DICTIONNAIRE  = Path("data/dictionnaire_libelles.json")
CHEMIN_PRODUITS      = Path("data/produits_canoniques.json")
CHEMIN_PROGRESSION   = Path("data/progression.json")   # pour reprendre si interruption

LIMITE_TICKETS       = 1   #5000   # None = tout traiter
PAUSE_ENTRE_APPELS   = 0.3    # secondes entre chaque appel API (évite le rate limiting)

BASE_URL_IMAGES      = "https://prices.openfoodfacts.org/img/"

# Initialiser le client Anthropic
# La clé API est lue depuis la variable d'environnement ANTHROPIC_API_KEY
#client = anthropic.Anthropic()
CONF = yaml.safe_load(open("conf.yml"))
client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=CONF["groq_key"],
)


# ─────────────────────────────────────────────────────────────────────────────
# NORMALISATION (gardée — on en a besoin pour les clés du dictionnaire)
# ─────────────────────────────────────────────────────────────────────────────

def normaliser_libelle(texte: str) -> str:
    """
    Nettoie un libellé pour en faire une clé de dictionnaire stable.
    "  ÉVIAN 1.5L 6X !!"  →  "evian 1.5l 6x"
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9 .]", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte


# ─────────────────────────────────────────────────────────────────────────────
# RÉCUPÉRER LE NOM PRODUIT DEPUIS L'API OPEN FOOD FACTS
# ─────────────────────────────────────────────────────────────────────────────

_cache_off: dict = {}

def recuperer_nom_produit_off(ean: str) -> tuple[str, str]:
    """
    Interroge l'API Open Food Facts pour obtenir le nom et la marque
    quand open-prices ne les fournit pas.
    Retourne (nom_produit, marque).
    """
    if ean in _cache_off:
        return _cache_off[ean]
    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{ean}?fields=product_name,brands"
        r = requests.get(url, timeout=8, headers={"User-Agent": "PriceTracker/1.0"})
        data = r.json()
        if data.get("status") == 1:
            p = data.get("product", {})
            nom, marque = p.get("product_name") or "", p.get("brands") or ""
            _cache_off[ean] = (nom, marque)
            return nom, marque
    except Exception:
        pass
    _cache_off[ean] = ("", "")
    return "", ""


# ─────────────────────────────────────────────────────────────────────────────
# APPEL LLM — LE CŒUR DU NOUVEAU CODE
# ─────────────────────────────────────────────────────────────────────────────

# Le prompt qu'on envoie à Claude avec chaque image
# On lui dit exactement ce qu'on veut : du JSON, rien d'autre
PROMPT_ANALYSE_TICKET = """Tu analyses une photo de ticket de caisse français.

Retourne UNIQUEMENT un objet JSON (sans markdown, sans explication) avec cette structure :
{
  "enseigne": "Carrefour",
  "date": "23/05/2026",
  "produits": [
    {
      "libelle": "EPINARDS HACHES SURGELES",
      "quantite": 1,
      "prix_unitaire": 1.39,
      "prix_total": 1.39
    }
  ],
  "total": 12.61
}

Règles :
- "enseigne" : nom de la chaîne de magasin uniquement (ex: "Carrefour", "Leclerc"), null si inconnu
- "libelle" : exactement le texte imprimé sur le ticket pour ce produit, en majuscules
- Ne pas inclure les lignes TVA, totaux, paiement, horaires, adresse
- Si un champ est illisible, mettre null
- Ne retourne RIEN d'autre que le JSON
"""


def analyser_ticket_avec_llm(url_image: str) -> dict | None:
    """
    Analyse un ticket avec un modèle vision compatible OpenAI/Groq.
    """

    try:
        # Construire URL absolue
        if not url_image.startswith("http"):
            url_image = BASE_URL_IMAGES + url_image

        # Télécharger image
        response = requests.get(
            url_image,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        response.raise_for_status()

        # Détecter le mime type
        content_type = response.headers.get("content-type", "image/jpeg")

        if "png" in content_type:
            mime = "image/png"
        elif "webp" in content_type:
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        # Base64
        image_b64 = base64.b64encode(response.content).decode("utf-8")

    except Exception as e:
        print(f"    ⚠️ Image inaccessible : {e}")
        return None

    try:

        completion = client.chat.completions.create(
            model="llama-3.2-90b-vision-preview",
            temperature=0,
            max_tokens=1200,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un système OCR spécialisé dans "
                        "les tickets de caisse français."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": PROMPT_ANALYSE_TICKET,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_b64}"
                            },
                        },
                    ],
                },
            ],
        )

        texte_reponse = completion.choices[0].message.content.strip()

        return json.loads(texte_reponse)

    except json.JSONDecodeError as e:
        print(f"    ⚠️ JSON invalide : {e}")
        print(texte_reponse[:500])
        return None

    except Exception as e:
        print(f"    ⚠️ Erreur API Groq : {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# TROUVER LE BON PRODUIT DANS LA RÉPONSE DU LLM
# ─────────────────────────────────────────────────────────────────────────────

def trouver_libelle_dans_resultat(
    produits_llm: list[dict],
    nom_produit: str,
    marque: str,
) -> str | None:
    """
    Parmi tous les produits détectés par le LLM sur le ticket,
    trouve celui qui correspond à l'EAN qu'on cherche.

    Même logique qu'avant (mots-clés) mais maintenant on travaille sur
    des libellés déjà propres fournis par le LLM — beaucoup plus fiable.
    """
    if not produits_llm:
        return None

    # Si le LLM n'a trouvé qu'un seul produit sur le ticket → c'est forcément lui
    if len(produits_llm) == 1:
        return produits_llm[0].get("libelle")

    # Sinon, on cherche par mots-clés dans les libellés retournés
    reference = normaliser_libelle(f"{nom_produit} {marque}")
    mots_cles = [mot[:6] for mot in reference.split() if len(mot) >= 4]

    if not mots_cles:
        # Pas de mots-clés → on prend le premier produit par défaut
        return produits_llm[0].get("libelle")

    meilleur_libelle = None
    meilleur_score   = 0

    for produit in produits_llm:
        libelle = produit.get("libelle", "")
        libelle_norm = normaliser_libelle(libelle)
        score = sum(1 for mc in mots_cles if mc in libelle_norm)
        if score > meilleur_score:
            meilleur_score   = score
            meilleur_libelle = libelle

    return meilleur_libelle if meilleur_score > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# GESTION DE LA PROGRESSION (pour reprendre si interruption)
# ─────────────────────────────────────────────────────────────────────────────

def charger_progression() -> tuple[dict, dict, int]:
    """Charge les données déjà traitées si le script a été interrompu."""
    dictionnaire, produits, index_depart = {}, {}, 0
    if CHEMIN_PROGRESSION.exists():
        with open(CHEMIN_PROGRESSION, encoding="utf-8") as f:
            prog = json.load(f)
            dictionnaire  = prog.get("dictionnaire", {})
            produits      = prog.get("produits", {})
            index_depart  = prog.get("compteur", 0)
        print(f"↩️  Reprise depuis le ticket #{index_depart} ({len(dictionnaire)} libellés déjà indexés)")
    return dictionnaire, produits, index_depart


def sauvegarder_progression(dictionnaire: dict, produits: dict, compteur: int):
    """Sauvegarde régulièrement pour ne pas tout perdre en cas d'interruption."""
    Path("data").mkdir(exist_ok=True)
    with open(CHEMIN_PROGRESSION, "w", encoding="utf-8") as f:
        json.dump({"dictionnaire": dictionnaire, "produits": produits, "compteur": compteur},
                  f, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# PROGRAMME PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def construire_dictionnaire():
    print("📥 Chargement du dataset Open Prices depuis Hugging Face...")
    dataset = load_dataset("openfoodfacts/open-prices", split="prices", streaming=True)

    # Reprendre là où on s'était arrêté si interruption
    dictionnaire, produits, index_depart = charger_progression()

    print(f"🔄 Traitement des tickets (limite : {LIMITE_TICKETS or '∞'})...")
    compteur = 0

    for ligne in dataset:
        # Sauter les entrées déjà traitées si reprise
        if compteur < index_depart:
            compteur += 1
            continue

        if LIMITE_TICKETS and compteur >= LIMITE_TICKETS:
            break

        ean         = ligne.get("product_code")
        url_image   = ligne.get("proof_file_path")
        nom_produit = ligne.get("product_name") or ""
        marque      = ligne.get("product_brands") or ""

        if not ean or not url_image:
            compteur += 1
            continue

        # Compléter le nom produit via API OFF si manquant
        if not nom_produit and not marque:
            nom_produit, marque = recuperer_nom_produit_off(ean)

        # ── Enregistrer le produit canonique ──────────────────────────────────
        if ean not in produits:
            produits[ean] = {
                "nom":      nom_produit,
                "marque":   marque,
                "categorie": (ligne.get("product_categories_tags") or [""])[0],
                "unite":    ligne.get("product_quantity_unit") or "",
                "quantite": ligne.get("product_quantity") or 0,
                "eans_lies": [ean],
            }
        elif not produits[ean]["nom"] and nom_produit:
            produits[ean]["nom"] = nom_produit

        # ── Appel LLM ─────────────────────────────────────────────────────────
        print(f"  [{compteur+1}] 🤖 Analyse LLM — {nom_produit or ean}...")
        resultat = analyser_ticket_avec_llm(url_image)

        if resultat:
            # Récupérer l'enseigne détectée par le LLM
            enseigne = resultat.get("enseigne") or "Inconnue"

            # Trouver le libellé qui correspond à notre EAN
            libelle_trouve = trouver_libelle_dans_resultat(
                resultat.get("produits", []),
                nom_produit,
                marque,
            )

            if libelle_trouve:
                libelle_normalise = normaliser_libelle(libelle_trouve)
                if libelle_normalise and libelle_normalise not in dictionnaire:
                    dictionnaire[libelle_normalise] = {
                        "ean":              ean,
                        "libelle_original": libelle_trouve,
                        "enseigne":         enseigne,
                        "produit_nom":      nom_produit or marque,
                    }
                    print(f"     ✅ '{libelle_trouve}'  →  {nom_produit}  ({enseigne})")
            else:
                print(f"     ⚠️  Produit non trouvé dans le ticket pour '{nom_produit}'")
        else:
            print(f"     ❌ Ticket illisible ou erreur LLM")

        compteur += 1

        # Sauvegarder la progression toutes les 50 entrées
        if compteur % 50 == 0:
            sauvegarder_progression(dictionnaire, produits, compteur)
            print(f"  💾 Progression sauvegardée ({len(dictionnaire)} libellés)")

        # Pause pour ne pas dépasser les limites de l'API
        time.sleep(PAUSE_ENTRE_APPELS)

    # ── Sauvegarde finale ─────────────────────────────────────────────────────
    Path("data").mkdir(exist_ok=True)
    with open(CHEMIN_DICTIONNAIRE, "w", encoding="utf-8") as f:
        json.dump(dictionnaire, f, ensure_ascii=False, indent=2)
    with open(CHEMIN_PRODUITS, "w", encoding="utf-8") as f:
        json.dump(produits, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Dictionnaire sauvegardé : {len(dictionnaire)} libellés connus")
    print(f"✅ Produits canoniques    : {len(produits)} produits uniques")


if __name__ == "__main__":
    construire_dictionnaire()
