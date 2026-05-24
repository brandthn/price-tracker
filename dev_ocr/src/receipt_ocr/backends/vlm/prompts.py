"""Prompt templates for receipt extraction with VLMs."""

from __future__ import annotations

RECEIPT_EXTRACTION_PROMPT = """\
Tu analyses une photo de ticket de caisse de supermarché français.

Extrais les informations visibles et renvoie UNIQUEMENT un objet JSON valide \
(sans markdown, sans texte avant ou après), avec exactement cette structure :

{
  "ticket": {
    "date": "yyyyMMdd HH:mm",
    "chaine_supermarche": "nom du magasin",
    "adresse": "adresse complète sur le ticket",
    "produits": [
      {
        "nom_produit": "libellé du produit",
        "prix_unitaire_ou_kg": 0.00,
        "unites": 1
      }
    ]
  }
}

Règles strictes :
- Réponds UNIQUEMENT avec du JSON parseable. Aucune phrase explicative.
- Ignore l'arrière-plan (table, main, sol). Lis uniquement le papier du ticket.
- date au format yyyyMMdd HH:mm (ex. 20240315 14:30). Chaîne vide si absente.
- chaine_supermarche : enseigne en tête de ticket. Chaîne vide si absente.
- adresse : lignes d'adresse du magasin. Chaîne vide si absente.
- produits : une entrée par article (pas totaux, TVA, paiement).
- prix_unitaire_ou_kg : nombre décimal (point comme séparateur).
- unites : entier >= 1.
- N'invente pas : liste uniquement le texte lisible. Si doute, omets le produit.
"""

RECEIPT_EXTRACTION_STRICT_PROMPT = """\
Photo d'un ticket de caisse français. Renvoie SEULEMENT ce JSON (pas de markdown, pas de texte) :

{"ticket":{"date":"","chaine_supermarche":"","adresse":"","produits":[{"nom_produit":"","prix_unitaire_ou_kg":0.0,"unites":1}]}}

Remplis les champs visibles. Chaîne vide si absent. Pas de commentaire.
"""

RECEIPT_TRANSCRIPTION_PROMPT = """\
Tu vois une photo d'un ticket de caisse de supermarché français.

Transcris UNIQUEMENT le texte imprimé sur le ticket, ligne par ligne,
de haut en bas, en conservant l'ordre d'apparition.

Règles strictes :
- Aucun commentaire, aucune explication, pas de JSON.
- Ignore l'arrière-plan (table, main, sol, autres objets).
- Si un mot est illisible, écris [illisible].
- Conserve les prix tels qu'imprimés (ex. 1,20 €).
"""

RECEIPT_TRANSCRIPTION_STRICT_PROMPT = """\
Transcris ligne par ligne le texte du ticket de caisse visible sur cette photo.
UNIQUEMENT le texte du ticket. Pas de commentaire. Pas de JSON.
"""

MULTIPASS_HEADER_PROMPT = """\
Sur ce ticket de caisse français, extrais UNIQUEMENT l'enseigne et l'adresse du magasin.
Renvoie SEULEMENT ce JSON (pas de markdown) :
{"chaine_supermarche":"","adresse":""}
Chaîne vide si absent. Pas de commentaire.
"""

MULTIPASS_DATE_PROMPT = """\
Sur ce ticket de caisse français, extrais UNIQUEMENT la date et l'heure d'achat.
Renvoie SEULEMENT ce JSON (pas de markdown) :
{"date":"yyyyMMdd HH:mm"}
Format yyyyMMdd HH:mm ou chaîne vide. Pas de commentaire.
"""

MULTIPASS_PRODUCTS_PROMPT = """\
Sur ce ticket de caisse français, liste UNIQUEMENT les articles achetés (pas totaux/TVA/paiement).
Renvoie SEULEMENT ce JSON (pas de markdown) :
{"produits":[{"nom_produit":"","prix_unitaire_ou_kg":0.0,"unites":1}]}
Prix en nombre décimal. Pas de commentaire. N'invente pas.
"""
