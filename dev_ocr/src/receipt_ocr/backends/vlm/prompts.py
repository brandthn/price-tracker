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

Règles :
- date au format yyyyMMdd HH:mm (ex. 20240315 14:30). Chaîne vide si absente.
- chaine_supermarche : enseigne visible en tête de ticket. Chaîne vide si absente.
- adresse : lignes d'adresse du magasin. Chaîne vide si absente.
- produits : une entrée par ligne article achetée (pas les totaux, TVA, paiement).
- prix_unitaire_ou_kg : nombre décimal (point comme séparateur).
- unites : entier >= 1 (quantité achetée).
- N'invente pas de produits : liste uniquement ce qui est lisible sur le ticket.
- Si une information est illisible, utilise "" ou omets le produit concerné.
"""
