# 🧾 PriceTracker — Module Matching Produits

## C'est quoi ce projet ?

Quand un utilisateur prend en photo son ticket de caisse,
ce module lit le ticket et identifie chaque produit.

---

## Les 3 fichiers principaux

```
📁 price_tracker/
│
├── etape1_construire_dictionnaire.py   ← À lancer UNE SEULE FOIS
│                                          Construit le dictionnaire libellé → produit
│                                          à partir des données Open Food Facts
│
├── etape2_matching.py                  ← Le moteur de recherche
│                                          Prend un libellé, trouve le produit
│
├── etape3_analyser_ticket.py           ← Le point d'entrée principal
│                                          Prend une photo de ticket, retourne
│                                          tous les produits avec leurs prix
│
├── data/                               ← Créé automatiquement par l'étape 1
│   ├── dictionnaire_libelles.json         Le dictionnaire principal
│   └── produits_canoniques.json           Les infos détaillées des produits
│
└── requirements.txt                    ← Les bibliothèques à installer
```

---

## Comment utiliser

### 1. Installer les dépendances

```bash
pip install -r requirements.txt
```

⚠️ Installer aussi Tesseract OCR sur ton système :
- **Mac** : `brew install tesseract tesseract-lang`
- **Ubuntu/Debian** : `sudo apt install tesseract-ocr tesseract-ocr-fra`
- **Windows** : Télécharger sur https://github.com/UB-Mannheim/tesseract/wiki

### 2. Construire le dictionnaire (une seule fois)

```bash
python etape1_construire_dictionnaire.py
```

⏱️ Prend du temps (plusieurs heures pour 5000 tickets).
Lance ça une nuit ou sur un serveur.

### 3. Analyser un ticket

```python
from etape2_matching import MoteurMatching
from etape3_analyser_ticket import analyser_ticket, afficher_resultat

# Charger le moteur une seule fois au démarrage de l'app
moteur = MoteurMatching()

# Analyser un ticket
ticket = analyser_ticket("mon_ticket.jpg", moteur)

# Afficher le résultat
afficher_resultat(ticket)
```

---

## Comment ça marche en résumé

```
📸 Photo ticket
     ↓
🔤 OCR (Tesseract lit le texte)
     ↓
📋 Pour chaque ligne...
     ↓
  [Stratégie 1] Match exact dans le dictionnaire      → ✅ Confiance 100%
     ↓ non trouvé
  [Stratégie 2] Match fuzzy (approximatif)            → 🔶 Confiance 80-99%
     ↓ non trouvé
  [Stratégie 3] Match sémantique (IA)                 → 🧠 Confiance 75-90%
     ↓ non trouvé
  [Stratégie 4] Catégorie générique + "non identifié" → ❌ Confiance 0%
```

---

## Gérer les cas difficiles

### Produit non référencé
→ Il reçoit `methode = "inconnu"` et `ean = None`
→ On lui attribue quand même une catégorie si possible
→ Tu peux demander à l'utilisateur de confirmer et enrichir le dictionnaire

### Produit avec plusieurs EAN
→ Ils sont regroupés sous un "produit canonique" dans `produits_canoniques.json`
→ Le prix est normalisé à l'unité (€/L, €/kg) pour les comparaisons

### Améliorer les résultats avec le temps
→ Chaque correction utilisateur peut être ajoutée au dictionnaire
→ Relancer l'étape 1 périodiquement pour intégrer les nouveaux produits Open Food Facts
