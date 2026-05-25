"""
ÉTAPE 2 — Matcher un ticket utilisateur contre la base de données EAN

Ce fichier reçoit la sortie JSON de l'OCR (fourni par un membre du groupe)
et cherche chaque produit dans la table product_labels via fuzzy matching.

Entrée (JSON OCR) :
{
  "ticket": {
    "date": "20241028 17:39",
    "chaine_supermarche": "Carrefour Market",
    "adresse": "37 Rue de Lyon, 75012 Paris",
    "produits": [
      { "nom_produit": "*1/2 EPINARDS HACHE", "prix_unitaire_ou_kg": 1.29, "unites": 1 }
    ]
  }
}

Sortie :
{
  "enseigne": "Carrefour Market",
  "date": "20241028 17:39",
  "adresse": "37 Rue de Lyon, 75012 Paris",
  "produits": [
    {
      "nom_produit_ocr": "*1/2 EPINARDS HACHE",
      "prix_unitaire_ou_kg": 1.29,
      "unites": 1,
      "statut": "trouve",          # "trouve" | "candidats" | "inconnu"
      "confiance": 95,             # score fuzzy 0-100
      "ean": "3560070283484",
      "nom_canonique": "Épinards hachés 500g",
      "libelle_reference": "*x1/2 EPINARDS HACHE",   # libellé connu en base
      "enseigne_reference": "Carrefour Market"
    }
  ],
  "stats": {
    "total": 8,
    "trouves": 6,
    "candidats": 1,
    "inconnus": 1
  }
}
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from rapidfuzz import fuzz

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH           = Path("data/price_tracker.db")
SEUIL_CONFIANT    = 75   # score >= 75 → "trouve" (confiance haute)
SEUIL_CANDIDAT    = 50   # score >= 50 → "candidats" (à valider par l'utilisateur)
                         # score <  50 → "inconnu"
MAX_CANDIDATS     = 3    # nombre max de candidats retournés en cas d'ambiguïté


# ─────────────────────────────────────────────────────────────────────────────
# NORMALISATION (identique à l'étape 1)
# ─────────────────────────────────────────────────────────────────────────────

ENSEIGNES_A_EXCLURE = {
    "carrefour", "leclerc", "monoprix", "intermarche", "auchan",
    "lidl", "aldi", "casino", "franprix", "super u", "superu",
    "cora", "match", "netto", "picard", "biocoop", "naturalia",
}


def normaliser(texte: str) -> str:
    """
    Nettoie un libellé pour le fuzzy matching.
    "*1/2 EPINARDS HACHÉ !!"  →  "epinards hache"
    """
    if not texte:
        return ""
    texte = texte.lower()
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9 .]", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    # Supprimer les tokens parasites en début (chiffres isolés, x, *)
    match = re.search(r"[a-z]{3,}", texte)
    if match:
        texte = texte[match.start():]
    return texte


def score_fuzzy(libelle_ocr_norm: str, libelle_base_norm: str) -> float:
    """
    Score composite fuzzy (même formule qu'étape 1).
    Favorise les correspondances partielles (abréviations fréquentes sur tickets).
    """
    return (
        0.5 * fuzz.token_set_ratio(libelle_ocr_norm, libelle_base_norm)
        + 0.3 * fuzz.partial_ratio(libelle_ocr_norm, libelle_base_norm)
        + 0.2 * fuzz.token_sort_ratio(libelle_ocr_norm, libelle_base_norm)
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONNEXION BASE DE DONNÉES
# ─────────────────────────────────────────────────────────────────────────────

def ouvrir_base() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}. Lance d'abord l'étape 1.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def charger_labels(conn: sqlite3.Connection, enseigne: str | None) -> list[dict]:
    """
    Charge les libellés depuis product_labels.
    Si l'enseigne est connue, on charge d'abord les labels de cette enseigne
    puis les autres (fallback si produit absent chez cette enseigne).
    """
    if enseigne:
        enseigne_norm = enseigne.lower().strip()
        # Labels de l'enseigne en priorité
        rows_enseigne = conn.execute("""
            SELECT pl.ean, pl.libelle_original, pl.libelle_normalise,
                   pl.enseigne, p.nom AS nom_canonique
            FROM product_labels pl
            LEFT JOIN products p ON p.ean = pl.ean
            WHERE LOWER(pl.enseigne) LIKE ?
        """, (f"%{enseigne_norm}%",)).fetchall()

        # Tous les autres en fallback
        rows_autres = conn.execute("""
            SELECT pl.ean, pl.libelle_original, pl.libelle_normalise,
                   pl.enseigne, p.nom AS nom_canonique
            FROM product_labels pl
            LEFT JOIN products p ON p.ean = pl.ean
            WHERE LOWER(pl.enseigne) NOT LIKE ?
        """, (f"%{enseigne_norm}%",)).fetchall()

        return [dict(r) for r in rows_enseigne] + [dict(r) for r in rows_autres]
    else:
        rows = conn.execute("""
            SELECT pl.ean, pl.libelle_original, pl.libelle_normalise,
                   pl.enseigne, p.nom AS nom_canonique
            FROM product_labels pl
            LEFT JOIN products p ON p.ean = pl.ean
        """).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# MATCHING — cœur de l'étape 2
# ─────────────────────────────────────────────────────────────────────────────

def matcher_produit(nom_ocr: str, labels: list[dict]) -> dict:
    """
    Cherche le meilleur match pour un libellé OCR dans product_labels.

    Retourne un dict avec :
      - statut    : "trouve" | "candidats" | "inconnu"
      - confiance : score 0-100
      - ean, nom_canonique, libelle_reference, enseigne_reference (si trouvé)
      - candidats : liste de candidats (si statut = "candidats")
    """
    nom_norm = normaliser(nom_ocr)
    if not nom_norm:
        return {"statut": "inconnu", "confiance": 0, "raison": "libellé vide après normalisation"}

    mots_ocr = set(nom_norm.split())
    scores   = []

    for label in labels:
        lib_norm = label["libelle_normalise"]
        if not lib_norm:
            continue

        mots_lib = set(lib_norm.split())

        # Garde-fou : au moins 1 mot de 4+ lettres en commun
        mots_communs = {m for m in mots_ocr & mots_lib if len(m) >= 4}
        if not mots_communs and len(mots_ocr) > 1:
            continue

        score = score_fuzzy(nom_norm, lib_norm)
        if score >= SEUIL_CANDIDAT:
            scores.append((score, label))

    if not scores:
        return {"statut": "inconnu", "confiance": 0}

    # Trier par score décroissant
    scores.sort(key=lambda x: x[0], reverse=True)
    meilleur_score, meilleur_label = scores[0]

    # Statut "trouve" : confiance haute
    if meilleur_score >= SEUIL_CONFIANT:
        return {
            "statut":             "trouve",
            "confiance":          round(meilleur_score),
            "ean":                meilleur_label["ean"],
            "nom_canonique":      meilleur_label["nom_canonique"] or "",
            "libelle_reference":  meilleur_label["libelle_original"],
            "enseigne_reference": meilleur_label["enseigne"],
        }

    # Statut "candidats" : plusieurs possibilités, besoin de validation utilisateur
    candidats = []
    for score, label in scores[:MAX_CANDIDATS]:
        candidats.append({
            "confiance":          round(score),
            "ean":                label["ean"],
            "nom_canonique":      label["nom_canonique"] or "",
            "libelle_reference":  label["libelle_original"],
            "enseigne_reference": label["enseigne"],
        })

    return {
        "statut":    "candidats",
        "confiance": round(meilleur_score),
        "candidats": candidats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SAUVEGARDER LES INCONNUS — pour enrichir la base
# ─────────────────────────────────────────────────────────────────────────────

def sauvegarder_inconnus(conn: sqlite3.Connection, inconnus: list[dict]):
    """
    Insère les produits non reconnus dans product_aliases pour validation future.
    Permet d'enrichir progressivement la base avec les retours utilisateurs.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_aliases (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle_ocr     TEXT NOT NULL,
            libelle_normalise TEXT NOT NULL,
            enseigne        TEXT,
            prix            REAL,
            ean_valide      TEXT,          -- rempli après validation utilisateur
            valide          INTEGER DEFAULT 0,  -- 0=en attente, 1=validé, -1=rejeté
            vu_le           TEXT DEFAULT (datetime('now'))
        )
    """)
    for p in inconnus:
        conn.execute("""
            INSERT OR IGNORE INTO product_aliases
                (libelle_ocr, libelle_normalise, enseigne, prix)
            VALUES (?, ?, ?, ?)
        """, (
            p["nom_produit_ocr"],
            normaliser(p["nom_produit_ocr"]),
            p.get("enseigne"),
            p.get("prix_unitaire_ou_kg"),
        ))
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# FONCTION PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

def matcher_ticket(ocr_json: dict) -> dict:
    """
    Prend la sortie JSON de l'OCR et retourne les produits matchés.

    Paramètre :
        ocr_json : dict correspondant à la structure JSON de l'OCR
                   (avec la clé "ticket" en racine)

    Retourne :
        dict avec enseigne, date, adresse, produits matchés, et stats
    """
    ticket   = ocr_json.get("ticket", {})
    enseigne = ticket.get("chaine_supermarche") or ""
    date     = ticket.get("date") or ""
    adresse  = ticket.get("adresse") or ""
    produits = ticket.get("produits", [])

    conn   = ouvrir_base()
    labels = charger_labels(conn, enseigne)
    print(f"  📚 {len(labels)} libellés chargés depuis la base")

    resultats  = []
    n_trouves  = 0
    n_candidats = 0
    n_inconnus = 0
    inconnus   = []

    for p in produits:
        nom_ocr = p.get("nom_produit") or ""
        prix    = p.get("prix_unitaire_ou_kg")
        unites  = p.get("unites", 1)

        print(f"\n  🔍 '{nom_ocr}'")
        match = matcher_produit(nom_ocr, labels)

        ligne = {
            "nom_produit_ocr":    nom_ocr,
            "prix_unitaire_ou_kg": prix,
            "unites":             unites,
            **match,
        }

        if match["statut"] == "trouve":
            n_trouves += 1
            print(f"     ✅ {match['confiance']}/100 → {match['ean']} ({match['nom_canonique']})")

        elif match["statut"] == "candidats":
            n_candidats += 1
            print(f"     ⚠️  {match['confiance']}/100 → {len(match['candidats'])} candidats")
            for c in match["candidats"]:
                print(f"        - {c['confiance']}/100 {c['ean']} {c['nom_canonique']}")

        else:
            n_inconnus += 1
            print(f"     ❌ Inconnu — ajouté à product_aliases")
            inconnus.append({**ligne, "enseigne": enseigne})

        resultats.append(ligne)

    # Sauvegarder les inconnus pour enrichissement futur
    if inconnus:
        sauvegarder_inconnus(conn, inconnus)

    conn.close()

    return {
        "enseigne": enseigne,
        "date":     date,
        "adresse":  adresse,
        "produits": resultats,
        "stats": {
            "total":      len(produits),
            "trouves":    n_trouves,
            "candidats":  n_candidats,
            "inconnus":   n_inconnus,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXEMPLE D'UTILISATION
# ─────────────────────────────────────────────────────────────────────────────
"""
if __name__ == "__main__":
    # Exemple avec un ticket fictif au format de l'OCR du groupe
    exemple_ocr = {
        "ticket": {
            "date": "20241028 17:39",
            "chaine_supermarche": "Carrefour Market",
            "adresse": "37 Rue de Lyon, 75012 Paris",
            "produits": [
                {"nom_produit": "*1/2 EPINARDS HACHE",     "prix_unitaire_ou_kg": 1.29, "unites": 1},
                {"nom_produit": "LENTILLES CORAIL U BIO",  "prix_unitaire_ou_kg": 1.89, "unites": 1},
                {"nom_produit": "COCA COLA 1.5L",          "prix_unitaire_ou_kg": 2.49, "unites": 1},
                {"nom_produit": "PAIN DE MIE HARRYS",      "prix_unitaire_ou_kg": 1.89, "unites": 1},
            ]
        }
    }

    print("🧾 Matching du ticket...\n")
    resultat = matcher_ticket(exemple_ocr)

    print("\n" + "─" * 60)
    print("RÉSULTAT FINAL")
    print("─" * 60)
    print(json.dumps(resultat, ensure_ascii=False, indent=2))

    stats = resultat["stats"]
    print(f"\n📊 {stats['trouves']}/{stats['total']} produits identifiés "
          f"({stats['candidats']} à valider, {stats['inconnus']} inconnus)")
"""