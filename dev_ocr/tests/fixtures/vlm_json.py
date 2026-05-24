"""Sample VLM JSON outputs for parser unit tests."""

from __future__ import annotations

VALID_VLM_JSON = """\
{
  "ticket": {
    "date": "20240315 14:30",
    "chaine_supermarche": "CARREFOUR MARKET",
    "adresse": "12 rue de la République, 75001 Paris",
    "produits": [
      {
        "nom_produit": "BANANES BIO",
        "prix_unitaire_ou_kg": 2.15,
        "unites": 1
      },
      {
        "nom_produit": "PAIN COMPLET",
        "prix_unitaire_ou_kg": "1,20",
        "unites": 2
      }
    ]
  }
}
"""

FENCED_VLM_JSON = """\
```json
{
  "ticket": {
    "date": "",
    "chaine_supermarche": "SUPER U",
    "adresse": "",
    "produits": [
      {"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.09, "unites": 1}
    ]
  }
}
```
"""
