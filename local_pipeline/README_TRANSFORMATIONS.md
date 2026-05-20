# Documentation des transformations Silver — Open Prices Pipeline

## Vue d'ensemble

La couche Silver prend les données brutes (Bronze) et produit deux tables :

- **`openpricesclean.parquet`** — données validées, normalisées, enrichies
- **`openpricesrejections.parquet`** — lignes rejetées avec raison explicite

Sur les 257 607 lignes du dataset HuggingFace réel :
- **140 425 acceptées** (54.5%)
- **117 182 rejetées** (45.5%)

---

## Architecture de traitement — ordre des étapes

Chaque ligne passe par une chaîne de 7 étapes dans cet ordre :

```
Ligne Bronze (brute HuggingFace)
    │
    ▼
[1] Mapping HF → format cleaner
    │
    ▼
[2] Validations de base (cleaner)
    ├── ✗ Champ requis manquant   → rejet MISSING_REQUIRED_FIELD
    ├── ✗ Devise non EUR          → rejet INVALID_CURRENCY
    ├── ✗ Pays hors périmètre     → rejet INVALID_COUNTRY
    ├── ✗ Type de preuve invalide → rejet INVALID_PROOF_TYPE
    ├── ✗ Prix non parsable       → rejet INVALID_PRICE
    ├── ✗ Prix hors plage globale → rejet OUT_OF_RANGE_PRICE
    └── ✗ Date future             → rejet FUTURE_DATE
    │
    ▼
[3] Validation EAN
    └── ✗ Code-barres invalide    → rejet INVALID_EAN
    │
    ▼
[4] Cohérence remise
    └── ✗ prix_remisé ≥ prix_normal → rejet INCOHERENT_DISCOUNT
    │
    ▼
[5] Normalisation enseigne         → enrichissement (ne rejette pas)
    │
    ▼
[6] Standardisation ville          → enrichissement (ne rejette pas)
    │
    ▼
    Buffer (toutes lignes acceptées de 1 à 6)
    │
    ▼
[7] Détection prix suspects IQR    (passe sur toutes les lignes)
    └── ✗ Prix hors Q1-3×IQR / Q3+3×IQR → rejet SUSPICIOUS_PRICE_IQR
    │
    ▼
openpricesclean.parquet
```

---

## Détail de chaque transformation

---

### [1] Mapping HuggingFace → format cleaner

**Fichier :** `shared/hf_mapping.py`

**Problème résolu :**
Le dataset HuggingFace utilise des noms de colonnes différents de ceux attendus
par le cleaner. Il faut adapter avant de valider.

**Transformations :**

| Champ HF | Action | Résultat |
|---|---|---|
| `date` | Copié vers | `price_date` |
| `location_osm_address_country` = "France" | Converti nom → ISO alpha-2 | `location_osm_address_country_code` = "FR" |
| `location_osm_display_name` | Copié si `location_name` absent | `location_name` |

**Exemple :**
```
Avant : { "date": "2026-03-15", "location_osm_address_country": "France" }
Après : { "price_date": "2026-03-15", "location_osm_address_country_code": "FR" }
```

---

### [2] Validations de base

**Fichier :** `shared/cleaner.py`

#### 2a. Champs obligatoires
Les champs `id`, `product_code`, `price`, `currency`, `price_date` doivent
tous être présents et non vides.

**Résultat sur les vraies données :** 8 257 rejets (7.0% des rejets)

#### 2b. Devise
Seul `EUR` est accepté. Le dataset est mondial — USD, GBP, CHF, etc. sont rejetés.

**Résultat :** 51 529 rejets (44.0% des rejets) — première cause de rejet

```python
# Logique
if currency not in {"EUR"}:
    → rejet INVALID_CURRENCY
```

#### 2c. Pays
Seuls la France métropolitaine et les DOM/TOM sont acceptés :
`FR, GP, GF, MQ, RE, YT, PM, MF, BL, WF, NC, PF`

**Résultat :** 21 707 rejets (18.5%)

#### 2d. Type de preuve
Trois types sont acceptés :

| Type | Description |
|---|---|
| `PRICE_TAG` | Photo d'une étiquette en rayon (OCR) — le plus courant |
| `RECEIPT` | Photo ou scan d'un ticket de caisse |
| `SHOP_IMPORT` | Prix importés directement par une enseigne — acceptés car 100% France/EUR et fiables |

Rejeté : `GDPR_REQUEST` — ce sont des archives personnelles exportées suite à une demande
GDPR, pas des observations fraîches de prix en magasin.

**Résultat (avec SHOP_IMPORT accepté) :** ~21 751 rejets GDPR_REQUEST (au lieu de 32 885)

#### 2e. Plage de prix globale
- Minimum : 0.01€ (prix nul ou négatif = erreur)
- Maximum : 500€ (au-delà = probablement une saisie en centimes ou erreur)

**Résultat :** 41 rejets (très peu — la plupart des aberrants sont détectés par l'IQR ensuite)

#### 2f. Date non future
Une date de prix dans le futur est impossible — c'est une erreur de saisie.

#### 2g. Normalisation sur les lignes acceptées
Sur les lignes qui passent toutes les validations, le cleaner produit un dictionnaire
enrichi avec des champs calculés :

| Champ ajouté | Calcul |
|---|---|
| `price_eur` | Prix converti en float propre |
| `price_eur_decimal` | Prix en string Decimal (précision comptable) |
| `week_start_date` | Lundi de la semaine ISO contenant `price_date` |
| `store_brand` | Extrait depuis `store_name` → `location_osm_display_name` |
| `ingested_at` | Horodatage UTC d'ingestion |
| `raw_payload` | Dict brut original sérialisé en JSON (traçabilité) |

---

### [3] Validation EAN-13

**Fichier :** `local_pipeline/silver_enrichments.py` — fonction `validate_ean()`

**Problème résolu :**
N'importe quelle chaîne non vide passait le cleaner de base. Un code comme
"12345" ou "abc" était accepté. Or un vrai code-barres alimentaire suit le
standard EAN-13 (ou EAN-8 pour les petits emballages) avec un checksum intégré.

**Algorithme de validation EAN-13 :**

```
Code : 3 5 6 0 0 7 0 2 8 3 4 8 4
Poids: 1 3 1 3 1 3 1 3 1 3 1 3

Produits = 3×1 + 5×3 + 6×1 + 0×3 + 0×1 + 7×3 + 0×1 + 2×3 + 8×1 + 3×3 + 4×1 + 8×3
         = 3 + 15 + 6 + 0 + 0 + 21 + 0 + 6 + 8 + 9 + 4 + 24 = 96

Chiffre de contrôle attendu = (10 - (96 % 10)) % 10 = (10 - 6) % 10 = 4 ✓
Le 13e chiffre est bien 4 → EAN valide
```

**Ce qui est rejeté :**
- Code non entièrement numérique
- Code de longueur différente de 8 ou 13
- Code avec checksum incorrect (saisie avec faute de frappe)

**Résultat :** 118 codes invalides rejetés sur les vraies données

---

### [4] Cohérence prix remisé / prix normal

**Fichier :** `local_pipeline/silver_enrichments.py` — fonction `check_discount_coherence()`

**Problème résolu :**
Si un produit est marqué `price_is_discounted=True` avec un `price_without_discount`
renseigné, le prix normal DOIT être supérieur au prix remisé. L'inverse n'a
aucun sens commercial.

**Règles appliquées :**

```
Si price_is_discounted = True ET price_without_discount est présent :

  ✗ price_without_discount ≤ price_eur
    → rejet : "prix remisé (1.20€) ≥ prix sans remise (0.99€)"

  ✗ remise > 95%
    → rejet : "remise de 97% trop importante"

  ✓ Tout le reste → ligne acceptée
```

**Cas non rejeté :** `price_is_discounted=True` sans `price_without_discount`
(l'enseigne n'a pas renseigné le prix d'origine — courant, pas une erreur)

**Résultat :** 2 lignes incohérentes sur les vraies données

---

### [5] Normalisation du store_brand

**Fichier :** `local_pipeline/silver_enrichments.py` — fonction `normalize_store_brand()`

**Problème résolu :**
Le champ `store_brand` contient l'adresse OSM complète du magasin.
Résultat : chaque magasin physique est traité comme une enseigne différente
dans Gold, ce qui rend les agrégats inutilisables.

**Avant (adresse OSM brute) :**
```
"Centre Commercial E.Leclerc, Rue Yitzhak Rabin, Clichy, Nanterre,
 Hauts-de-Seine, Île-de-France, France métropolitaine, 92110, France"

"E. Leclerc, Rue du Pré Ruffier, Zone d'activités Pré Ruffier,
 Saint-Martin-d'Hères, Grenoble, Isère, ..."
```

**Après (enseigne normalisée) :**
```
"E.Leclerc"
"E.Leclerc"
```

**Méthode :**
Une liste de 25 patterns regex triés du plus spécifique au plus général.
L'ordre est crucial : "Carrefour Market" doit être testé avant "Carrefour"
pour ne pas être capturé en "Carrefour".

**Enseignes reconnues :** E.Leclerc, Carrefour (City/Market/Express), Auchan,
Intermarché, Super U, U Express, Hyper U, Lidl, Aldi, Monoprix, Franprix,
Casino, Géant Casino, Netto, Biocoop, La Vie Claire, Picard, Action, Grand Frais, Cora, Match, Diagonal

**Nouveau champ produit :** `store_brand_normalized`
(l'adresse OSM complète est conservée dans `store_brand` pour la traçabilité)

**Résultat :** 143 068 lignes enrichies (99.7% des lignes acceptées)

---

### [6] Standardisation de la ville

**Fichier :** `local_pipeline/silver_enrichments.py` — fonction `standardize_city()`

**Problème résolu :**
La même ville peut apparaître sous plusieurs formes selon la source OSM :
"PARIS", "Paris 17e Arrondissement", "paris", "LYON 7e".

**Transformations appliquées dans l'ordre :**

1. Strip des espaces
2. Title Case : `"PARIS 17E ARRONDISSEMENT"` → `"Paris 17E Arrondissement"`
3. Suppression du suffixe d'arrondissement via regex :
   `r'\s+\d+\s*(e|er|ème|eme)?\s*(arrondissement)?$'`
4. Résultat : `"Paris"`

**Exemples :**

| Entrée | Sortie |
|---|---|
| `"PARIS"` | `"Paris"` |
| `"Paris 17e Arrondissement"` | `"Paris"` |
| `"LYON 7e"` | `"Lyon"` |
| `"marseille"` | `"Marseille"` |
| `"Échirolles"` | `"Échirolles"` (accents préservés) |

**Résultat :** 11 423 villes standardisées

---

### [7] Détection de prix suspects par IQR

**Fichier :** `local_pipeline/silver_enrichments.py` — fonctions
`compute_price_bounds()` et `flag_suspicious_prices()`

**Problème résolu :**
Un prix de 0.05€ pour un Nutella passe la validation globale (≥ 0.01€).
Mais rapporté à l'historique de ce produit spécifique, c'est clairement aberrant.

**Pourquoi l'IQR plutôt que moyenne ± n×σ ?**

La moyenne est sensible aux outliers existants. Si on a déjà quelques prix
aberrants dans les données, la moyenne monte et les seuils deviennent trop larges.
L'IQR (Q3 - Q1) ne dépend que de la moitié centrale des données : il est robuste.

**Algorithme (passe post-traitement) :**

```
Pour chaque produit ayant ≥ 5 observations :

    Q1  = 1er quartile des prix de ce produit
    Q3  = 3ème quartile des prix de ce produit
    IQR = Q3 - Q1

    Borne basse  = max(0.01€,  Q1 - 3 × IQR)
    Borne haute  =             Q3 + 3 × IQR

    Si prix < borne_basse OU prix > borne_haute :
        → rejet SUSPICIOUS_PRICE_IQR
```

**Pourquoi le facteur 3 (et non 1.5 de Tukey) ?**
Le facteur classique 1.5 est conçu pour des distributions normales en
statistiques académiques. Ici on traite des prix alimentaires avec des
promotions légitimes à -50%, des achats en gros, des produits premium.
Un facteur 3 est très permissif et ne rejette que les vrais aberrants
(erreur de saisie en centimes au lieu d'euros, doublon décimal, etc.)

**Exemple réel détecté :**
Un produit habituellement entre 1.50€ et 3.50€ signalé à 0.03€
→ probablement saisi en centimes d'euro par erreur.

**Résultat :** 2 643 prix suspects détectés sur 6 524 produits évalués

---

## Résultats finaux sur les vraies données HuggingFace

### Volume

| Étape | Lignes | % du total |
|---|---|---|
| Bronze (brut) | 257 607 | 100% |
| Silver acceptées | 140 425 | 54.5% |
| Silver rejetées | 117 182 | 45.5% |

### Répartition des rejets

| Raison | Nb | % des rejets | Couche |
|---|---|---|---|
| `INVALID_CURRENCY` | 51 529 | 44.0% | Cleaner |
| `INVALID_PROOF_TYPE` | 32 885 | 28.1% | Cleaner |
| `INVALID_COUNTRY` | 21 707 | 18.5% | Cleaner |
| `MISSING_REQUIRED_FIELD` | 8 257 | 7.0% | Cleaner |
| `SUSPICIOUS_PRICE_IQR` | 2 643 | 2.3% | Enrichissement |
| `INVALID_EAN` | 118 | 0.1% | Enrichissement |
| `OUT_OF_RANGE_PRICE` | 41 | 0.0% | Cleaner |
| `INCOHERENT_DISCOUNT` | 2 | 0.0% | Enrichissement |

### Enrichissements appliqués sur les 140 425 lignes acceptées

| Enrichissement | Nb lignes impactées |
|---|---|
| Enseignes normalisées (`store_brand_normalized`) | 143 068 |
| Villes standardisées (`city`) | 11 423 |
| EAN invalides rejetés | 118 |
| Remises incohérentes rejetées | 2 |
| Prix suspects rejetés (IQR) | 2 643 |

---

## Pourquoi 45.5% de rejets sur les données réelles ?

Le dataset HuggingFace Open Prices est **mondial**. Il contient des prix de
toute l'Europe et au-delà. Notre pipeline est configuré pour la France uniquement :

- **44% des rejets sont des devises non EUR** : prix en USD, GBP, PLN, etc.
- **18.5% sont des pays hors périmètre** : Allemagne, Espagne, Pologne, etc.

En production GCP, le snapshot est pré-filtré France avant ingestion,
ce qui explique pourquoi le seuil de quality gate est 60% en prod vs 40% en local.

---

## Fichiers produits

```
data/
├── bronze/
│   ├── open_prices.parquet       # 257 607 lignes brutes HuggingFace
│   └── _metadata.json            # source, date, taille, colonnes
├── silver/
│   ├── openpricesclean.parquet   # 140 425 lignes validées + enrichies
│   ├── openpricesrejections.parquet # 117 182 rejets avec raison
│   └── _metrics.json             # métriques complètes du run Silver
└── gold/
    ├── aggregatsenseignes.parquet  # 326 agrégats semaine/enseigne/pays
    ├── indicesinflation.parquet    # 326 indices base 100
    ├── rankingsproduits.parquet    # top hausses de prix
    └── anomaliesdetected.parquet   # outliers z-score ≥ 3
```

## Colonnes de openpricesclean.parquet

| Colonne | Type | Description |
|---|---|---|
| `id` | string | Identifiant unique HuggingFace |
| `product_code` | string | EAN-13 validé |
| `price_eur` | float | Prix en euros (float) |
| `price_eur_decimal` | string | Prix en euros (précision Decimal) |
| `price_without_discount_eur` | float | Prix avant remise (si applicable) |
| `price_is_discounted` | bool | Produit en promotion ? |
| `currency` | string | Toujours "EUR" |
| `price_date` | string | Date du relevé (ISO 8601) |
| `week_start_date` | string | Lundi de la semaine ISO |
| `proof_type` | string | RECEIPT ou PRICE_TAG |
| `country_code` | string | Code ISO pays (FR, GP, etc.) |
| `store_brand` | string | Adresse OSM complète |
| `store_brand_normalized` | string | **NOUVEAU** — Enseigne extraite (ex: "E.Leclerc") |
| `city` | string | Ville standardisée (ex: "Paris") |
| `postcode` | string | Code postal |
| `latitude` | float | Latitude GPS |
| `longitude` | float | Longitude GPS |
| `source` | string | Origine de la donnée |
| `ingested_at` | string | Horodatage UTC d'ingestion |
| `raw_payload` | string | JSON brut original (traçabilité) |
