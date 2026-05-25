"""
ÉTAPE 1 — Construire la base de données EAN ↔ Libellés (version SQLite)

Ce fichier :
  - Parcourt le dataset Open Prices (Hugging Face)
  - Filtre sur les tickets de caisse français (RECEIPT + FR)
  - Fait un OCR local (Tesseract) sur chaque photo
  - Sauvegarde le texte OCR brut dans la table `receipts`
  - Envoie le texte OCR à un LLM (Groq) qui retourne un JSON structuré
  - Stocke les résultats dans une base SQLite (data/price_tracker.db)
  - Gère proactivement les rate limits Groq (12K tokens/min, 30 req/min)

Tables créées :
  - products       : un produit par EAN (nom, marque, catégorie...)
  - product_labels : libellés par enseigne (un EAN peut avoir plusieurs lignes)
  - receipts       : tickets traités — texte OCR brut + JSON LLM sauvegardés ici
  - progression    : pour reprendre si interruption (une seule ligne)
"""

import json
import re
import sqlite3
import time
import unicodedata
from io import BytesIO
from pathlib import Path

import openai
import pytesseract
import requests
import yaml
from datasets import load_dataset
from PIL import Image
from rapidfuzz import fuzz


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH            = Path("data/price_tracker.db")
LIMITE_TICKETS     = None     # None = tout traiter
PAUSE_ENTRE_APPELS = 0.3      # secondes entre appels API
SEUIL_FUZZY_MATCH  = 60       # score minimum pour valider un match
BASE_URL_IMAGES    = "https://prices.openfoodfacts.org/img/"

# Limites Groq (plan gratuit llama-3.3-70b-versatile)
GROQ_TPM_LIMITE    = 12_000   # tokens par minute
GROQ_RPM_LIMITE    = 30       # requêtes par minute
GROQ_TPM_SEUIL     = 0.90     # on lève le pied à 90% de la limite

CONF   = yaml.safe_load(open("conf.yml"))
client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=CONF["groq_key"],
)


# ─────────────────────────────────────────────────────────────────────────────
# GESTION DU RATE LIMIT GROQ — basée sur les headers de réponse HTTP
# ─────────────────────────────────────────────────────────────────────────────
# Groq retourne après chaque appel :
#   x-ratelimit-remaining-tokens:   tokens restants dans la minute courante
#   x-ratelimit-remaining-requests: requêtes restantes dans la minute courante
# On lit ces valeurs réelles plutôt que de recalculer localement,
# ce qui évite les erreurs au redémarrage du script.

_remaining_tokens   = GROQ_TPM_LIMITE   # mis à jour après chaque appel
_remaining_requests = GROQ_RPM_LIMITE   # mis à jour après chaque appel


def mettre_a_jour_quotas(headers: dict):
    """
    Lit les headers Groq après chaque appel réussi.
    Met à jour les compteurs globaux avec les valeurs réelles du serveur.
    """
    global _remaining_tokens, _remaining_requests
    try:
        rt = headers.get("x-ratelimit-remaining-tokens")
        rr = headers.get("x-ratelimit-remaining-requests")
        if rt is not None:
            _remaining_tokens   = int(rt)
        if rr is not None:
            _remaining_requests = int(rr)
    except (ValueError, TypeError):
        pass


def attendre_si_necessaire(tokens_estimes: int = 1200, modele: str = "llama-3.1-8b-instant"):
    """
    Vérifie AVANT chaque appel LLM si les quotas restants sont suffisants.
    Dort 61s (reset garanti) si tokens ou requêtes insuffisants.
    Basé sur les vraies valeurs Groq — fiable même après redémarrage du script.
    """
    # Limites différentes selon le modèle
    tpm_limite = 6_000 if "8b" in modele else GROQ_TPM_LIMITE   # 8b = 6K TPM, 70b = 12K TPM
    marge = 1.2   # 10% de marge de sécurité
    if _remaining_tokens < tokens_estimes * marge:
        print(f"    ⏳ Tokens restants insuffisants ({_remaining_tokens} < {int(tokens_estimes * marge)}) — pause 61s")
        time.sleep(61)
    elif _remaining_requests < 3:
        print(f"    ⏳ Requêtes restantes insuffisantes ({_remaining_requests}) — pause 61s")
        time.sleep(61)


def choisir_modele(texte_ocr: str) -> str:
    """
    Utilise llama-3.1-8b-instant par défaut (14 400 req/jour, 6K TPM).
    Réserve le 70b uniquement pour les tickets très longs (> 1500 chars).
    """
    if len(texte_ocr) > 1500:
        return "llama-3.3-70b-versatile"
    return "llama-3.1-8b-instant"


# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRE — conversion types numpy/pyarrow → Python natif
# ─────────────────────────────────────────────────────────────────────────────

def _natif(val):
    """
    Convertit les scalaires numpy/pyarrow/Decimal en types Python natifs
    acceptés par le driver SQLite.
    """
    if val is None:
        return None
    if hasattr(val, "as_py"):      # pyarrow scalar
        return val.as_py()
    if hasattr(val, "item"):       # numpy scalar (int64, float32, bool_...)
        return val.item()
    import decimal
    if isinstance(val, decimal.Decimal):
        return float(val)
    return val


# ─────────────────────────────────────────────────────────────────────────────
# BASE DE DONNÉES SQLITE
# ─────────────────────────────────────────────────────────────────────────────

def initialiser_base() -> sqlite3.Connection:
    """
    Crée le fichier SQLite et les tables si elles n'existent pas.

    Structure :
      products       → un produit par EAN
      product_labels → libellés tels qu'imprimés sur les tickets, par enseigne
      receipts       → tickets traités : OCR brut + JSON LLM + toutes colonnes HF
      progression    → compteur de reprise (une seule ligne, id=1)
    """
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # accès aux colonnes par nom

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            ean       TEXT PRIMARY KEY,
            nom       TEXT,
            marque    TEXT,
            categorie TEXT,
            unite     TEXT,
            quantite  REAL
        );

        CREATE TABLE IF NOT EXISTS product_labels (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            ean               TEXT NOT NULL,
            libelle_original  TEXT NOT NULL,   -- libellé EXACT du ticket (ex: "*1/2 EPINARDS HACHE")
            libelle_normalise TEXT NOT NULL,   -- version normalisée pour le fuzzy matching
            enseigne          TEXT,
            produit_nom       TEXT,
            receipt_id        INTEGER,         -- lien vers le ticket source (receipts.id)
            UNIQUE(ean, enseigne)
        );

        CREATE TABLE IF NOT EXISTS receipts (
            -- ── Colonnes ajoutées par notre pipeline ────────────────────────
            id                            INTEGER PRIMARY KEY AUTOINCREMENT,
            texte_ocr                     TEXT,    -- texte brut Tesseract
            llm_json                      TEXT,    -- réponse JSON brute du LLM
            enseigne                      TEXT,    -- enseigne détectée par le LLM
            date_ticket                   TEXT,    -- date lue sur le ticket
            total_ticket                  REAL,    -- total lu sur le ticket
            traite_le                     TEXT DEFAULT (datetime('now')),

            -- ── Colonnes Open Prices (dataset HuggingFace) ──────────────────
            hf_id                         INTEGER,
            type                          TEXT,
            product_code                  TEXT,
            product_name                  TEXT,
            category_tag                  TEXT,
            labels_tags                   TEXT,    -- liste sérialisée en JSON
            origins_tags                  TEXT,    -- liste sérialisée en JSON
            price                         REAL,
            price_is_discounted           INTEGER, -- booléen (0/1)
            price_without_discount        REAL,
            discount_type                 TEXT,
            price_per                     TEXT,
            currency                      TEXT,
            location_osm_id               INTEGER,
            location_osm_type             TEXT,
            location_id                   INTEGER,
            date                          TEXT,
            proof_id                      INTEGER,
            receipt_quantity              REAL,
            owner                         TEXT,
            source                        TEXT,
            created                       TEXT,
            updated                       TEXT,
            proof_file_path               TEXT NOT NULL UNIQUE,  -- clé de déduplication
            proof_mimetype                TEXT,
            proof_type                    TEXT,
            proof_date                    TEXT,
            proof_currency                TEXT,
            proof_receipt_price_count     INTEGER,
            proof_receipt_price_total     REAL,
            proof_owner                   TEXT,
            proof_source                  TEXT,
            proof_created                 TEXT,
            proof_updated                 TEXT,
            location_type                 TEXT,
            location_osm_display_name     TEXT,
            location_osm_tag_key          TEXT,
            location_osm_tag_value        TEXT,
            location_osm_address_postcode TEXT,
            location_osm_address_city     TEXT,
            location_osm_address_country  TEXT,
            location_osm_address_country_code TEXT,
            location_osm_lat              REAL,
            location_osm_lon              REAL,
            location_website_url          TEXT,
            location_source               TEXT,
            location_created              TEXT,
            location_updated              TEXT
        );

        CREATE TABLE IF NOT EXISTS progression (
            id       INTEGER PRIMARY KEY,
            compteur INTEGER DEFAULT 0
        );

        INSERT OR IGNORE INTO progression (id, compteur) VALUES (1, 0);
    """)
    conn.commit()
    return conn


def lire_progression(conn: sqlite3.Connection) -> int:
    """Retourne le numéro de la dernière entrée traitée."""
    row = conn.execute("SELECT compteur FROM progression WHERE id = 1").fetchone()
    return row["compteur"] if row else 0


def sauvegarder_progression(conn: sqlite3.Connection, compteur: int):
    """Met à jour le compteur de progression."""
    conn.execute("UPDATE progression SET compteur = ? WHERE id = 1", (compteur,))
    conn.commit()


def upsert_product(conn: sqlite3.Connection, ean: str, nom: str, marque: str,
                   categorie: str, unite: str, quantite: float):
    """
    INSERT OR IGNORE : on n'écrase jamais un produit déjà enregistré.
    Si l'EAN existe mais que le nom est vide, on le complète.
    """
    conn.execute("""
        INSERT OR IGNORE INTO products (ean, nom, marque, categorie, unite, quantite)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ean, nom, marque, categorie, unite, quantite))

    if nom:
        conn.execute("""
            UPDATE products SET nom = ? WHERE ean = ? AND (nom IS NULL OR nom = '')
        """, (nom, ean))

    conn.commit()


def sauvegarder_ocr_seul(conn: sqlite3.Connection, texte_ocr: str, ligne: dict) -> int:
    """
    Sauvegarde le résultat OCR + toutes les colonnes HF de la ligne courante.
    Appelé immédiatement après l'OCR, AVANT l'appel LLM.
    ON CONFLICT sur proof_file_path : si le ticket existe déjà, on met à jour l'OCR.
    Retourne l'id SQLite du ticket inséré ou mis à jour.
    """
    cursor = conn.execute("""
        INSERT INTO receipts (
            texte_ocr,
            hf_id, type, product_code, product_name, category_tag,
            labels_tags, origins_tags,
            price, price_is_discounted, price_without_discount, discount_type,
            price_per, currency,
            location_osm_id, location_osm_type, location_id,
            date, proof_id, receipt_quantity, owner, source, created, updated,
            proof_file_path, proof_mimetype, proof_type, proof_date, proof_currency,
            proof_receipt_price_count, proof_receipt_price_total,
            proof_owner, proof_source, proof_created, proof_updated,
            location_type, location_osm_display_name,
            location_osm_tag_key, location_osm_tag_value,
            location_osm_address_postcode, location_osm_address_city,
            location_osm_address_country, location_osm_address_country_code,
            location_osm_lat, location_osm_lon,
            location_website_url, location_source, location_created, location_updated
        ) VALUES (
            ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?, ?
        )
        ON CONFLICT(proof_file_path) DO UPDATE SET
            texte_ocr = excluded.texte_ocr
    """, (
        texte_ocr,
        _natif(ligne.get("id")),
        _natif(ligne.get("type")),
        _natif(ligne.get("product_code")),
        _natif(ligne.get("product_name")),
        _natif(ligne.get("category_tag")),
        json.dumps(_natif(ligne.get("labels_tags")) or []),
        json.dumps(_natif(ligne.get("origins_tags")) or []),
        _natif(ligne.get("price")),
        _natif(ligne.get("price_is_discounted")),
        _natif(ligne.get("price_without_discount")),
        _natif(ligne.get("discount_type")),
        _natif(ligne.get("price_per")),
        _natif(ligne.get("currency")),
        _natif(ligne.get("location_osm_id")),
        _natif(ligne.get("location_osm_type")),
        _natif(ligne.get("location_id")),
        _natif(ligne.get("date")),
        _natif(ligne.get("proof_id")),
        _natif(ligne.get("receipt_quantity")),
        _natif(ligne.get("owner")),
        _natif(ligne.get("source")),
        _natif(ligne.get("created")),
        _natif(ligne.get("updated")),
        _natif(ligne.get("proof_file_path")),
        _natif(ligne.get("proof_mimetype")),
        _natif(ligne.get("proof_type")),
        _natif(ligne.get("proof_date")),
        _natif(ligne.get("proof_currency")),
        _natif(ligne.get("proof_receipt_price_count")),
        _natif(ligne.get("proof_receipt_price_total")),
        _natif(ligne.get("proof_owner")),
        _natif(ligne.get("proof_source")),
        _natif(ligne.get("proof_created")),
        _natif(ligne.get("proof_updated")),
        _natif(ligne.get("location_type")),
        _natif(ligne.get("location_osm_display_name")),
        _natif(ligne.get("location_osm_tag_key")),
        _natif(ligne.get("location_osm_tag_value")),
        _natif(ligne.get("location_osm_address_postcode")),
        _natif(ligne.get("location_osm_address_city")),
        _natif(ligne.get("location_osm_address_country")),
        _natif(ligne.get("location_osm_address_country_code")),
        _natif(ligne.get("location_osm_lat")),
        _natif(ligne.get("location_osm_lon")),
        _natif(ligne.get("location_website_url")),
        _natif(ligne.get("location_source")),
        _natif(ligne.get("location_created")),
        _natif(ligne.get("location_updated")),
    ))
    conn.commit()
    return cursor.lastrowid


def mettre_a_jour_receipt_llm(conn: sqlite3.Connection, receipt_id: int,
                               llm_json: str, enseigne: str,
                               date_ticket: str, total_ticket: float):
    """
    Complète un ticket déjà en base (OCR + colonnes HF) avec la réponse LLM.
    Appelé après sauvegarder_ocr_seul, une fois que le LLM a répondu.
    """
    conn.execute("""
        UPDATE receipts
        SET llm_json = ?, enseigne = ?, date_ticket = ?, total_ticket = ?
        WHERE id = ?
    """, (llm_json, enseigne, date_ticket, total_ticket, receipt_id))
    conn.commit()


def upsert_label(conn: sqlite3.Connection, ean: str,
                 libelle_original: str, libelle_normalise: str,
                 enseigne: str, produit_nom: str,
                 receipt_id: int | None = None):
    """
    INSERT OR REPLACE : si le couple (ean, enseigne) existe déjà,
    on met à jour le libellé (un ticket plus récent peut être plus lisible).
    receipt_id permet de retrouver le ticket source depuis product_labels.
    """
    conn.execute("""
        INSERT OR REPLACE INTO product_labels
            (ean, libelle_original, libelle_normalise, enseigne, produit_nom, receipt_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ean, libelle_original, libelle_normalise, enseigne, produit_nom, receipt_id))
    conn.commit()


def compter_labels(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM product_labels").fetchone()[0]


def ticket_deja_traite(conn: sqlite3.Connection, proof_file_path: str) -> bool:
    """
    Vérifie si ce ticket a déjà un OCR ET une réponse LLM sauvegardés.
    Permet de sauter les proof_file_path déjà entièrement traités lors d'une reprise.
    """
    row = conn.execute(
        "SELECT 1 FROM receipts WHERE proof_file_path = ? AND llm_json IS NOT NULL",
        (proof_file_path,)
    ).fetchone()
    return row is not None


# ─────────────────────────────────────────────────────────────────────────────
# NORMALISATION
# ─────────────────────────────────────────────────────────────────────────────

ENSEIGNES_A_EXCLURE = {
    "carrefour", "leclerc", "monoprix", "intermarche", "auchan",
    "lidl", "aldi", "casino", "franprix", "super u", "superu",
    "cora", "match", "netto", "picard", "biocoop", "naturalia",
}


def normaliser_libelle(texte: str) -> str:
    """
    Nettoie un libellé pour en faire une clé stable pour le fuzzy matching.
    "*x*x1/2 ÉPINARDS HACHÉ !!"  →  "epinards hache"
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9 .]", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    match = re.search(r"[a-z]{3,}", texte)
    if match:
        texte = texte[match.start():]
    return texte


def normaliser_reference(nom_produit: str, marque: str) -> str:
    """
    Référence pour le fuzzy matching, sans les noms d'enseignes.
    (Les MDD ont souvent l'enseigne dans le champ 'marque')
    """
    tokens = normaliser_libelle(f"{nom_produit} {marque}").split()
    return " ".join(t for t in tokens if t not in ENSEIGNES_A_EXCLURE)


# ─────────────────────────────────────────────────────────────────────────────
# OPEN FOOD FACTS — compléter les infos produit manquantes
# ─────────────────────────────────────────────────────────────────────────────

_cache_off: dict = {}


def recuperer_nom_produit_off(ean: str) -> tuple[str, str]:
    """Interroge l'API OFF pour obtenir nom + marque quand open-prices ne les a pas."""
    if ean in _cache_off:
        return _cache_off[ean]
    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{ean}?fields=product_name,brands"
        r = requests.get(url, timeout=8, headers={"User-Agent": "PriceTracker/1.0"})
        data = r.json()
        if data.get("status") == 1:
            p = data.get("product", {})
            nom    = p.get("product_name") or ""
            marque = p.get("brands") or ""
            _cache_off[ean] = (nom, marque)
            return nom, marque
    except Exception:
        pass
    _cache_off[ean] = ("", "")
    return "", ""


# ─────────────────────────────────────────────────────────────────────────────
# LLM — OCR + structuration JSON
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_ANALYSE_TICKET = """Tu analyses le texte OCR brut d'un ticket de caisse français.
Ce texte peut contenir des erreurs OCR (lettres mal reconnues, caractères parasites).

Les tickets français ont des formats variés selon l'enseigne. Exemples réels :
- Carrefour Market : "6  *1/2 EPINARDS HACHE    1,25€"  (le "6" est le code TVA, à ignorer)
- Auchan           : "*BANANE ANTILLES    1,46"          (libellé direct avec prix)
- Super U          : "EAU MIN.NATURELLE EVIAN 6X1,5L    7,30  11"  (code TVA à la fin)

Dans tous les cas, le libellé produit est la partie textuelle centrale de la ligne.
Les chiffres seuls en début ou fin de ligne sont des codes TVA — ne pas les inclure.

Retourne UNIQUEMENT un objet JSON (sans markdown, sans explication) avec cette structure :
{
  "enseigne": "Carrefour Market",
  "date": "28/10/2024",
  "produits": [
    {
      "libelle": "*1/2 EPINARDS HACHE",
      "quantite": 1,
      "prix_unitaire": 1.25,
      "prix_total": 1.25
    }
  ],
  "total": 12.61
}

Règles :
- "enseigne" : nom exact de la chaîne (ex: "Carrefour Market", "Auchan", "Super U"), null si inconnu
- "libelle" : COPIE EXACTE du texte produit tel qu'il apparaît sur le ticket —
  conserve les astérisques, slashs, abréviations, points, tout.
  Exclus uniquement les chiffres isolés de code TVA en début/fin de ligne.
- Ne pas inclure : TVA, totaux, paiement, horaires, adresse, nom du magasin, numéros de caisse
- Si un champ est illisible, mettre null
- Ne retourne RIEN d'autre que le JSON
"""


def analyser_ticket_avec_llm(url_image: str, ligne: dict,
                              conn: sqlite3.Connection) -> tuple[dict | None, str | None, int | None]:
    """
    1. Télécharge l'image et fait l'OCR avec Tesseract (local, gratuit)
    2. Sauvegarde immédiatement l'OCR + toutes les colonnes HF en base
    3. Choisit le modèle selon la longueur du texte OCR
    4. Vérifie les quotas Groq AVANT l'appel (évite les 429)
    5. Envoie le texte OCR à Groq pour structuration en JSON
    6. Complète le ticket en base avec la réponse LLM

    Retourne : (resultat_dict, texte_ocr, receipt_id)
    """
    # ── OCR ───────────────────────────────────────────────────────────────────
    try:
        if not url_image.startswith("http"):
            url_image = BASE_URL_IMAGES + url_image
        response = requests.get(url_image, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        try:
            texte_ocr = pytesseract.image_to_string(image, lang="fra")
        except Exception:
            texte_ocr = pytesseract.image_to_string(image, lang="eng")
        texte_ocr = texte_ocr.strip()
        if not texte_ocr:
            print("    ⚠️  OCR vide")
            return None, None, None
    except Exception as e:
        print(f"    ⚠️  OCR impossible : {e}")
        return None, None, None

    # ── Sauvegarde OCR immédiate ───────────────────────────────────────────────
    receipt_id = sauvegarder_ocr_seul(conn, texte_ocr, ligne)
    print(f"    💾 OCR sauvegardé (receipt #{receipt_id}, {len(texte_ocr)} chars)")

    # ── Choix du modèle ────────────────────────────────────────────────────────
    modele          = choisir_modele(texte_ocr)
    # Estimation : prompt système (~400) + OCR (~len/3) + réponse JSON (~600)
    tokens_estimes = 400 + len(texte_ocr) // 3 + 600

    # ── LLM avec retry sur rate limit ─────────────────────────────────────────
    for tentative in range(3):
        try:
            # Vérification proactive AVANT l'appel
            attendre_si_necessaire(tokens_estimes, modele)

            # Appel via with_raw_response pour accéder aux headers HTTP Groq
            raw = client.with_raw_response.chat.completions.create(
                model=modele,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": PROMPT_ANALYSE_TICKET},
                    {"role": "user",   "content": f"Voici le texte OCR brut du ticket :\n\n{texte_ocr}"},
                ],
            )
            # Mettre à jour les quotas depuis les headers AVANT de parser
            mettre_a_jour_quotas(dict(raw.headers))

            completion = raw.parse()
            resultat   = json.loads(completion.choices[0].message.content)

            # Sauvegarde de la réponse LLM
            mettre_a_jour_receipt_llm(
                conn, receipt_id,
                llm_json     = completion.choices[0].message.content,
                enseigne     = resultat.get("enseigne"),
                date_ticket  = resultat.get("date"),
                total_ticket = resultat.get("total"),
            )
            return resultat, texte_ocr, receipt_id

        except Exception as e:
            msg        = str(e)
            match_time = re.search(r"try again in (\d+)m([\d.]+)s", msg)
            match_sec  = re.search(r"try again in ([\d.]+)s", msg)
            match_ms   = re.search(r"try again in (\d+)ms", msg)

            if match_time and tentative < 2:
                attente = int(match_time.group(1)) * 60 + float(match_time.group(2)) + 2
                print(f"    ⏳ Rate limit — attente {match_time.group(1)}m avant retry ({tentative+1}/3)...")
                time.sleep(attente)
                continue
            elif match_ms and not match_time and tentative < 2:
                attente = int(match_ms.group(1)) / 1000 + 1
                print(f"    ⏳ Rate limit — attente {attente:.1f}s avant retry ({tentative+1}/3)...")
                time.sleep(attente)
                continue
            elif match_sec and not match_time and tentative < 2:
                attente = float(match_sec.group(1)) + 1
                print(f"    ⏳ Rate limit — attente {attente:.1f}s avant retry ({tentative+1}/3)...")
                time.sleep(attente)
                continue
            else:
                print(f"    ⚠️  Erreur LLM : {e}")
                return None, texte_ocr, receipt_id

    return None, texte_ocr, receipt_id

def initialiser_quotas_groq():
    """
    Fait un micro-appel Groq au démarrage pour lire les headers
    et initialiser _remaining_tokens / _remaining_requests
    avec les vraies valeurs courantes côté serveur.
    Evite le rate limit sur le premier vrai appel après un redémarrage.
    """
    global _remaining_tokens, _remaining_requests
    try:
        raw = client.with_raw_response.chat.completions.create(
            model="llama-3.1-8b-instant",   # petit modèle, consomme ~10 tokens
            max_tokens=1,
            messages=[{"role": "user", "content": "1"}],
        )
        mettre_a_jour_quotas(dict(raw.headers))
        print(f"  📊 Quotas Groq initialisés — tokens restants : {_remaining_tokens}, requêtes : {_remaining_requests}")
    except Exception as e:
        print(f"  ⚠️  Impossible d'initialiser les quotas Groq : {e}")

# ─────────────────────────────────────────────────────────────────────────────
# MATCHING — trouver le bon libellé dans la réponse du LLM
# ─────────────────────────────────────────────────────────────────────────────

def trouver_libelle_dans_resultat(produits_llm: list[dict],
                                  nom_produit: str, marque: str) -> str | None:
    """
    Parmi les produits détectés sur le ticket, trouve celui qui correspond à l'EAN.
    Utilise un score fuzzy avec garde-fou (au moins 1 mot commun obligatoire).
    """
    if not produits_llm:
        return None
    if len(produits_llm) == 1:
        return produits_llm[0].get("libelle")

    reference = normaliser_reference(nom_produit, marque)
    mots_ref  = set(reference.split())

    if not reference.strip():
        return None

    meilleur_libelle = None
    meilleur_score   = 0

    print(f"    🔍 Référence : '{reference}'")
    for p in produits_llm:
        libelle = p.get("libelle") or ""
        if not libelle:
            continue
        libelle_norm = normaliser_libelle(libelle)
        mots_lib     = set(libelle_norm.split())

        # Garde-fou : au moins 1 mot de 4+ lettres en commun
        mots_communs = {m for m in mots_ref & mots_lib if len(m) >= 4}
        if not mots_communs and len(mots_ref) > 1:
            continue

        score = (
            0.5 * fuzz.token_set_ratio(reference, libelle_norm)
            + 0.3 * fuzz.partial_ratio(reference, libelle_norm)
            + 0.2 * fuzz.token_sort_ratio(reference, libelle_norm)
        )
        print(f"    🔍 '{libelle}'  →  {score:.0f}/100  {mots_communs}")

        if score > meilleur_score:
            meilleur_score   = score
            meilleur_libelle = libelle

    if meilleur_score < SEUIL_FUZZY_MATCH:
        print(f"    ⚠️  Score trop bas ({meilleur_score:.0f}/100) — ignoré")
        return None

    return meilleur_libelle


# ─────────────────────────────────────────────────────────────────────────────
# PROGRAMME PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def construire_dictionnaire():
    print("📥 Chargement du dataset Open Prices depuis Hugging Face...")
    dataset = load_dataset("openfoodfacts/open-prices", split="prices", streaming=True)

    conn         = initialiser_base()
    initialiser_quotas_groq()
    index_depart = lire_progression(conn)
    n_labels     = compter_labels(conn)

    if index_depart > 0:
        print(f"↩️  Reprise depuis l'entrée #{index_depart} ({n_labels} libellés déjà en base)")

    print(f"🔄 Traitement (limite : {LIMITE_TICKETS or '∞'})...")
    compteur = 0

    for ligne in dataset:
        if compteur < index_depart:
            compteur += 1
            continue

        if LIMITE_TICKETS and compteur >= LIMITE_TICKETS:
            break

        ean        = _natif(ligne.get("product_code"))
        url_image  = _natif(ligne.get("proof_file_path"))
        proof_type = _natif(ligne.get("proof_type"))
        pays       = (_natif(ligne.get("location_osm_address_country_code")) or "").upper()

        # Filtre 1 : tickets de caisse uniquement
        if proof_type != "RECEIPT":
            compteur += 1
            continue

        # Filtre 2 : France uniquement
        if pays != "FR":
            compteur += 1
            continue

        # Filtre 3 : EAN et image obligatoires
        if not ean or not url_image:
            compteur += 1
            continue

        # Déduplication : ticket déjà entièrement traité
        if ticket_deja_traite(conn, url_image):
            print(f"  [{compteur+1}] ⏭️  Ticket déjà traité — {url_image[:60]}")
            compteur += 1
            continue

        nom_produit = _natif(ligne.get("product_name")) or ""
        marque      = _natif(ligne.get("product_brands")) or ""

        # Compléter nom/marque via API OFF si manquant
        if not nom_produit and not marque:
            nom_produit, marque = recuperer_nom_produit_off(ean)

        # Sauvegarder le produit canonique
        upsert_product(
            conn, ean, nom_produit, marque,
            categorie=_natif(ligne.get("category_tag")) or "",
            unite=_natif(ligne.get("product_quantity_unit")) or "",
            quantite=_natif(ligne.get("product_quantity")) or 0,
        )

        # OCR + sauvegarde + LLM
        print(f"  [{compteur+1}] 🤖 {nom_produit or ean}...")
        resultat, texte_ocr, receipt_id = analyser_ticket_avec_llm(url_image, ligne, conn)

        if resultat:
            enseigne       = resultat.get("enseigne") or "Inconnue"
            libelle_trouve = trouver_libelle_dans_resultat(
                resultat.get("produits", []), nom_produit, marque
            )
            if libelle_trouve:
                libelle_normalise = normaliser_libelle(libelle_trouve)
                if libelle_normalise:
                    upsert_label(conn, ean, libelle_trouve, libelle_normalise,
                                 enseigne, nom_produit or marque,
                                 receipt_id=receipt_id)
                    print(f"     ✅ '{libelle_trouve}'  →  {nom_produit}  ({enseigne})")
            else:
                print(f"     ⚠️  Produit non trouvé pour '{nom_produit}'")
        elif texte_ocr:
            print(f"     ❌ LLM en échec — OCR conservé en base (receipt #{receipt_id})")
        else:
            print(f"     ❌ Ticket illisible ou erreur OCR")

        compteur += 1

        if compteur % 50 == 0:
            sauvegarder_progression(conn, compteur)
            print(f"  💾 Progression : {compteur} entrées traitées, {compter_labels(conn)} libellés en base")

        time.sleep(PAUSE_ENTRE_APPELS)

    sauvegarder_progression(conn, compteur)
    conn.close()

    conn_final = sqlite3.connect(DB_PATH)
    n_final    = conn_final.execute("SELECT COUNT(*) FROM product_labels").fetchone()[0]
    n_receipts = conn_final.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    conn_final.close()

    print(f"\n✅ Terminé — {n_final} libellés et {n_receipts} tickets en base")


if __name__ == "__main__":
    construire_dictionnaire()