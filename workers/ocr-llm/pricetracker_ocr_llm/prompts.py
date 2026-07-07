"""Prompt d'extraction du worker OCR tier-2 (Gemini).

Local au worker (non partagé avec ``receipt_ocr``) : il désambiguïse les
colonnes d'un ticket français (Carrefour et la plupart des enseignes) —
notamment le code TVA de gauche, souvent confondu avec une quantité.
"""

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
        "quantite": 1,
        "prix_unitaire": 0.00,
        "montant_ttc": 0.00
      }
    ]
  }
}

Lecture des colonnes (tickets type Carrefour et la plupart des enseignes) :
Les lignes d'articles ont généralement trois colonnes de chiffres. De gauche à droite :
  1) TVA : un CODE de catégorie de TVA — un chiffre seul (1, 2, 3, 4, 5, 6…),
     parfois précédé d'un « * ». ⚠️ Ce N'EST PAS une quantité : ne le mets
     JAMAIS dans "quantite". Ignore-le complètement.
  2) QTE x P.U. : la quantité achetée et le prix unitaire (ex. « 2 x 1,50 »).
     → "quantite" et "prix_unitaire" viennent d'ICI. Cette colonne est souvent
     VIDE (article vendu à l'unité) : dans ce cas "quantite" = 1.
  3) MONTANT TTC : le montant payé pour la ligne, à l'extrême droite (ex. « 1,25€ »).
     → C'est "montant_ttc" : le total effectivement payé pour cette ligne.

Règles strictes :
- Réponds UNIQUEMENT avec du JSON parseable. Aucune phrase explicative.
- Ignore l'arrière-plan (table, main, sol). Lis uniquement le papier du ticket.
- date au format yyyyMMdd HH:mm (ex. 20241028 17:39). Chaîne vide si absente.
- chaine_supermarche : enseigne en tête de ticket. Chaîne vide si absente.
- adresse : lignes d'adresse du magasin. Chaîne vide si absente.
- produits : une entrée par LIGNE d'article imprimée (jamais les totaux, la TVA,
  ni le paiement). Ne fusionne PAS deux lignes identiques : si le même article
  apparaît deux fois, garde deux entrées distinctes.
- quantite : nombre (entier, ou poids en kg si l'article est vendu au poids).
  Défaut 1 quand la colonne QTE x P.U. est vide.
- prix_unitaire : prix d'une seule unité (colonne P.U.). Mets 0 si non imprimé.
- montant_ttc : nombre décimal (point comme séparateur) — le montant payé de la
  ligne. TOUJOURS renseigné.
- N'invente pas : liste uniquement le texte lisible. En cas de doute, omets la ligne.
- Un seul objet JSON {"ticket": ...} dans la réponse (pas de répétition).
"""

CORRECTIVE_TEMPLATE = """\

ATTENTION — SECONDE ANALYSE.
Une première analyse automatique a produit l'extraction JSON ci-dessous, que \
l'utilisateur a signalée comme ERRONÉE :

{previous_json}

Ré-analyse l'image du ticket avec le plus grand soin. Corrige les erreurs \
(libellés mal lus, quantités, prix unitaires, montants payés, enseigne, date). \
Vérifie en particulier que le CODE TVA de gauche n'a pas été pris pour une \
quantité, et que "montant_ttc" correspond bien au montant payé de la ligne \
(colonne de droite). Ne recopie pas aveuglément l'extraction précédente : \
contrôle chaque ligne sur l'image. Renvoie UNIQUEMENT le JSON corrigé, au même \
schéma que ci-dessus.
"""
