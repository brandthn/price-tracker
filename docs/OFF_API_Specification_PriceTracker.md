# Spécification API Open Food Facts — PriceTracker

**Document de référence à destination du Worker OFF (04h00)**  
**Projet : PriceTracker — Suivi de l'Inflation Consommateur**  
**ESGI 5 IABD 2 — Année académique 2025-2026**

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Environnements & Base URLs](#2-environnements--base-urls)
3. [Authentification](#3-authentification)
4. [Rate Limits & Stratégies d'Atténuation](#4-rate-limits--stratégies-datténuation)
5. [Endpoint Principal : GET Produit par EAN](#5-endpoint-principal--get-produit-par-ean)
6. [Champs Utiles au Catalogue PriceTracker](#6-champs-utiles-au-catalogue-pricetracker)
7. [Gestion des Cas Limites et Données Manquantes](#7-gestion-des-cas-limites-et-données-manquantes)
8. [Normalisation des Données](#8-normalisation-des-données)
9. [Bulk Fetching : Récupération par Lots](#9-bulk-fetching--récupération-par-lots)
10. [Endpoint de Recherche (usage limité)](#10-endpoint-de-recherche-usage-limité)
11. [Téléchargement Bulk vs Appels API](#11-téléchargement-bulk-vs-appels-api)
12. [Implémentation du Worker OFF dans le Contexte PriceTracker](#12-implémentation-du-worker-off-dans-le-contexte-pricetracker)
13. [SDK Python Officiel](#13-sdk-python-officiel)
14. [Licences & Obligations Légales](#14-licences--obligations-légales)
15. [Environnement de Staging & Tests](#15-environnement-de-staging--tests)
16. [Référence Rapide des URLs](#16-référence-rapide-des-urls)

---

## 1. Vue d'ensemble

L'API Open Food Facts (OFF) est une API publique et open data permettant d'accéder à la base de données de produits alimentaires mondiale. Dans le contexte du projet **PriceTracker**, cette API est utilisée exclusivement par le **Worker OFF** (déclenché chaque jour à 04h00) pour enrichir le catalogue produit (`catalogue_produits` dans BigQuery Silver) à partir des EAN identifiés dans la table `open_prices_clean`.

### Données récupérées pour PriceTracker

| Champ OFF | Usage dans le Catalogue | Table cible |
|---|---|---|
| `product_name` | `name_canonical` | `catalogue_produits` (BQ Silver) |
| `brands` | `brand` | `catalogue_produits` (BQ Silver) |
| `pnns_groups_1` / `pnns_groups_2` | `category_l1` / `category_l2` | `catalogue_produits` (BQ Silver) |
| `categories_tags` | `category_l3` (normalisée) | `catalogue_produits` (BQ Silver) |
| `nutrition_grades` | `nutriscore` | `catalogue_produits` (BQ Silver) |
| `ecoscore_grade` | `ecoscore` | `catalogue_produits` (BQ Silver) |
| `serving_size` / `product_quantity` | `unit_reference` (normalisation) | `catalogue_produits` (BQ Silver) |
| `product_name` + `brands` + `categories_tags` | Vecteur d'embedding pgvector | `products` (Cloud SQL) |

> **Point clé :** L'API OFF est **gratuite et sans clé API** pour les opérations de lecture. Seules les opérations d'écriture nécessitent une authentification. Le Worker OFF n'effectue que des opérations de **lecture (GET)**.

---

## 2. Environnements & Base URLs

### Production (à utiliser en production uniquement)

```
https://world.openfoodfacts.org
```

### Staging (à utiliser pendant le développement et les tests)

```
https://world.openfoodfacts.net
```

> ⚠️ **Important :** L'environnement de staging nécessite une authentification HTTP Basic pour éviter l'indexation par les moteurs de recherche. Les credentials sont :
> - **Username :** `off`
> - **Password :** `off`

Exemple en Python :

```python
import requests

# Staging — avec auth HTTP Basic
response = requests.get(
    "https://world.openfoodfacts.net/api/v2/product/3017624010701.json",
    auth=("off", "off"),
    headers={"User-Agent": "PriceTracker/1.0 (contact@pricetracker.fr)"}
)
```

> ⚠️ **Les bases de données de production et de staging sont séparées.** Un EAN valide en production n'est pas forcément présent en staging. En développement, il est normal de rencontrer des produits introuvables sur le staging.

---

## 3. Authentification

### Opérations de Lecture (GET) — Worker OFF PriceTracker

Les opérations READ **ne requièrent aucune authentification**, à l'exception du staging (voir ci-dessus).

**Obligation : User-Agent personnalisé**

Toutes les requêtes, y compris les GET, doivent inclure un header `User-Agent` personnalisé. Sans ce header, les requêtes peuvent être identifiées comme du scraping bot et bannie par IP.

Format requis : `AppName/Version (ContactEmail)`

```python
HEADERS = {
    "User-Agent": "PriceTracker-WorkerOFF/1.0 (contact@pricetracker.fr)"
}
```

> 💡 **Bonne pratique :** Remplir également le [formulaire d'usage API](https://docs.google.com/forms/d/e/1FAIpQLSdIE3D8qvjC_zRJw1W8OmuHhsWJ_NSckiiniAHlfaVwUZCziQ/viewform) pour déclarer l'usage. Cela permet d'éviter les bans et d'obtenir du support en cas de problème.

### Opérations d'Écriture (POST/PUT) — Non concerné par le Worker OFF

Le Worker OFF de PriceTracker ne fait **que des lectures**. Les opérations d'écriture (non utilisées ici) nécessitent :
- Un `user_id` (username, **pas** l'email) + `password`
- Ou un cookie de session obtenu via l'API de login

---

## 4. Rate Limits & Stratégies d'Atténuation

### Limites imposées par l'API OFF

| Type de requête | Limite |
|---|---|
| **Requêtes GET produit** (`/api/v*/product/*`) | **15 req/min/IP** |
| **Requêtes de recherche** (`/api/v*/search` ou `/cgi/search.pl`) | **10 req/min/IP** |
| **Écriture** (POST/PUT) | Pas de limite déclarée |

> ⚠️ Si ces limites sont dépassées, l'IP peut être **bannie**. En cas de ban, contacter : reuse@openfoodfacts.org.

En plus des limites par IP, des **limites globales** (HTTP 503) peuvent s'appliquer sur l'ensemble des endpoints, indépendamment de l'IP.

### Stratégie d'atténuation recommandée pour le Worker OFF

Le Worker OFF est déclenché chaque nuit à 04h00 et doit traiter les nouveaux EAN identifiés dans `open_prices_clean`. Voici la stratégie à implémenter :

#### 1. Rate Limiting côté client — `time.sleep()` avec backoff exponentiel

```python
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RATE_LIMIT_DELAY = 4.5  # secondes entre chaque requête (≈ 13 req/min, sous la limite de 15)

def get_product_with_backoff(ean: str, max_retries: int = 3) -> dict | None:
    """
    Appel OFF API avec backoff exponentiel en cas d'erreur 429/503.
    Retourne le dict produit ou None si introuvable.
    """
    base_url = "https://world.openfoodfacts.org"
    url = f"{base_url}/api/v2/product/{ean}.json"
    fields = "product_name,brands,categories_tags,pnns_groups_1,pnns_groups_2,nutrition_grades,ecoscore_grade,serving_size,product_quantity,quantity,labels_tags,origins_tags"
    
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                params={"fields": fields},
                headers={"User-Agent": "PriceTracker-WorkerOFF/1.0 (contact@pricetracker.fr)"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == 1:
                    return data.get("product")
                else:
                    return None  # Produit inexistant dans OFF
            
            elif response.status_code in (429, 503):
                wait_time = (2 ** attempt) * 60  # Backoff : 60s, 120s, 240s
                print(f"Rate limit atteint pour EAN {ean}. Attente {wait_time}s...")
                time.sleep(wait_time)
            
            else:
                response.raise_for_status()
        
        except requests.RequestException as e:
            print(f"Erreur pour EAN {ean}, tentative {attempt + 1}: {e}")
            time.sleep(30)
    
    return None  # Échec après max_retries tentatives


def process_ean_batch(ean_list: list[str]) -> list[dict]:
    results = []
    for ean in ean_list:
        product = get_product_with_backoff(ean)
        if product:
            results.append({"ean": ean, **product})
        time.sleep(RATE_LIMIT_DELAY)  # Respect du rate limit
    return results
```

#### 2. Cache local — Éviter les re-fetch inutiles

Ne jamais re-fetcher un EAN déjà présent dans `catalogue_produits` sauf si `last_synced_at` est ancien (ex : > 30 jours). Filtrer en amont depuis BigQuery :

```sql
-- BigQuery : EAN à fetcher = présents dans open_prices_clean mais absents/obsolètes dans catalogue
SELECT DISTINCT op.product_code AS ean
FROM `pricetracker.silver.open_prices_clean` op
LEFT JOIN `pricetracker.silver.catalogue_produits` cat
  ON op.product_code = cat.ean
WHERE op.product_type = 'PRODUCT'
  AND (cat.ean IS NULL OR cat.last_synced_at < DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY))
ORDER BY op.product_code
```

#### 3. Découpage en micro-batches

Si le nombre d'EAN à fetcher est supérieur à 500, découper en batches de 200 EAN avec une pause de 5 minutes entre les batches pour éviter les bans.

#### 4. Alternative pour volume élevé : Bulk Download

Au-delà de quelques centaines de produits, préférer le **téléchargement bulk** (voir section 11).

---

## 5. Endpoint Principal : GET Produit par EAN

C'est l'endpoint **exclusivement utilisé** par le Worker OFF de PriceTracker.

### Requête

```
GET https://world.openfoodfacts.org/api/v2/product/{barcode}.json
```

| Paramètre | Type | Description |
|---|---|---|
| `{barcode}` | string (path) | Code EAN-13 du produit (ex : `3017624010701`) |
| `fields` | string (query) | Champs à retourner, séparés par virgule. **Toujours spécifier** pour alléger la réponse. |

### Exemple de requête optimisée pour PriceTracker

```
GET https://world.openfoodfacts.org/api/v2/product/3017624010701.json?fields=product_name,brands,categories_tags,pnns_groups_1,pnns_groups_2,nutrition_grades,ecoscore_grade,serving_size,product_quantity,quantity,labels_tags,origins_tags
```

### Structure de la réponse

```json
{
  "code": "3017624010701",
  "status": 1,
  "status_verbose": "product found",
  "product": {
    "product_name": "Nutella",
    "brands": "Ferrero",
    "categories_tags": [
      "en:sugary-snacks",
      "en:spreads",
      "en:chocolate-spreads",
      "fr:pates-a-tartiner"
    ],
    "pnns_groups_1": "Sugary snacks",
    "pnns_groups_2": "Chocolate products",
    "nutrition_grades": "e",
    "ecoscore_grade": "d",
    "serving_size": "15 g",
    "product_quantity": "750 g",
    "quantity": "750 g",
    "labels_tags": ["en:no-gluten"],
    "origins_tags": []
  }
}
```

### Codes de statut

| `status` | `status_verbose` | Signification | Action Worker |
|---|---|---|---|
| `1` | `product found` | Produit trouvé | Extraire les champs |
| `0` | `product not found` | EAN introuvable | Marquer `off_not_found = true` dans catalogue |
| — | HTTP 429 | Rate limit dépassé | Backoff exponentiel |
| — | HTTP 503 | Limite globale atteinte | Pause 5-10 min |
| — | HTTP 5xx | Erreur serveur temporaire | Retry avec backoff |

### Normalisation des codes-barres (EAN)

L'API OFF normalise automatiquement les codes-barres (padding avec des zéros, suppression des espaces). Toutefois, il est recommandé de normaliser côté client avant l'appel :

```python
def normalize_ean(raw_ean: str) -> str:
    """Normalise un EAN : supprime les caractères non-numériques, pad à 13 chiffres."""
    ean = ''.join(filter(str.isdigit, str(raw_ean)))
    # EAN-8 → pas de padding (codes courtes valides)
    if len(ean) <= 8:
        return ean.zfill(8)
    return ean.zfill(13)  # Standard EAN-13
```

> ⚠️ Ne jamais utiliser l'email comme `user_id`. Dans l'API OFF, `user_id` désigne le **username** du compte, pas l'adresse email.

---

## 6. Champs Utiles au Catalogue PriceTracker

### Champs recommandés pour le `fields` parameter

```
product_name,brands,categories_tags,pnns_groups_1,pnns_groups_2,
nutrition_grades,ecoscore_grade,serving_size,product_quantity,
quantity,labels_tags,origins_tags
```

### Détail des champs

#### Identité du produit

| Champ OFF | Type | Description | Mapping PriceTracker |
|---|---|---|---|
| `product_name` | string | Nom canonique du produit | `name_canonical` |
| `brands` | string | Marques (séparées par virgule si multiples) | `brand` (prendre la 1ère) |
| `quantity` | string | Quantité brute avec unité, ex : `"750 g"` | Base pour `unit_reference` |
| `product_quantity` | float | Valeur numérique de la quantité | `unit_reference` (valeur) |
| `serving_size` | string | Taille d'une portion | Secondaire |

#### Catégorisation (critique pour la comparabilité)

| Champ OFF | Type | Description | Mapping PriceTracker |
|---|---|---|---|
| `pnns_groups_1` | string | Groupe PNNS niveau 1 (ex : `"Sugary snacks"`) | `category_l1` |
| `pnns_groups_2` | string | Groupe PNNS niveau 2 (ex : `"Chocolate products"`) | `category_l2` |
| `categories_tags` | array[string] | Tags de catégories normalisés (taxonomie OFF), du général au spécifique | `category_l3` = dernier tag |

> 💡 **Pour `category_l3` :** Prendre le **dernier élément** du tableau `categories_tags` car il correspond à la catégorie la plus spécifique. Ex : pour `["en:spreads", "en:chocolate-spreads", "fr:pates-a-tartiner"]`, `category_l3 = "fr:pates-a-tartiner"` (ou le dernier tag `en:` si préférence langue).

#### Scores nutritionnels et environnementaux

| Champ OFF | Type | Valeurs possibles | Mapping PriceTracker |
|---|---|---|---|
| `nutrition_grades` | string | `"a"`, `"b"`, `"c"`, `"d"`, `"e"` (ou absent) | `nutriscore` |
| `ecoscore_grade` | string | `"a"`, `"b"`, `"c"`, `"d"`, `"e"` (ou absent) | `ecoscore` |
| `nova_group` | integer | `1`, `2`, `3`, `4` (ou absent) | Optionnel |

#### Étiquettes et origines (pour produits vrac/CATEGORY)

| Champ OFF | Type | Description |
|---|---|---|
| `labels_tags` | array[string] | Labels normalisés (ex : `"en:organic"`, `"fr:ab-agriculture-biologique"`) |
| `origins_tags` | array[string] | Origines géographiques (ex : `"en:france"`) |

---

## 7. Gestion des Cas Limites et Données Manquantes

### Produit absent (`status = 0`)

Environ **10-20% des EAN** d'Open Prices ne seront pas trouvés dans la base OFF (produits locaux, enseignes discount, produits récents non contributés). Stratégie :

```python
def build_catalogue_entry(ean: str, off_product: dict | None) -> dict:
    """
    Construit une entrée catalogue même si OFF ne retourne rien.
    Les champs absents sont mis à None pour être traités ultérieurement.
    """
    if off_product is None:
        return {
            "ean": ean,
            "name_canonical": None,
            "brand": None,
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "nutriscore": None,
            "ecoscore": None,
            "unit_reference": None,
            "off_not_found": True,
            "last_synced_at": datetime.utcnow().isoformat()
        }
    
    # Extraction des catégories
    categories_tags = off_product.get("categories_tags", [])
    category_l3 = next(
        (tag for tag in reversed(categories_tags) if tag.startswith("en:")),
        categories_tags[-1] if categories_tags else None
    )
    
    # Parsing de l'unité de référence
    quantity_raw = off_product.get("quantity", "")
    unit_reference = parse_unit_reference(quantity_raw)  # Voir section 8
    
    return {
        "ean": ean,
        "name_canonical": off_product.get("product_name"),
        "brand": off_product.get("brands", "").split(",")[0].strip() or None,
        "category_l1": off_product.get("pnns_groups_1"),
        "category_l2": off_product.get("pnns_groups_2"),
        "category_l3": category_l3,
        "nutriscore": off_product.get("nutrition_grades"),
        "ecoscore": off_product.get("ecoscore_grade"),
        "unit_reference": unit_reference,
        "labels_tags": off_product.get("labels_tags", []),
        "origins_tags": off_product.get("origins_tags", []),
        "off_not_found": False,
        "last_synced_at": datetime.utcnow().isoformat()
    }
```

### Champs partiellement renseignés

La base OFF est contributive et les données **ne sont pas garanties complètes**. Il est normal de recevoir des `null` sur des champs comme `nutrition_grades`, `ecoscore_grade`, ou `pnns_groups_1`. Ne pas rejeter ces entrées — les insérer avec les données disponibles et marquer les champs manquants pour une mise à jour future.

| Situation | Comportement recommandé |
|---|---|
| `product_name` absent | Insérer avec `name_canonical = null`, flag pour revue manuelle |
| `pnns_groups_1` absent | Tenter d'inférer depuis `categories_tags` (voir heuristiques section 8) |
| `nutrition_grades` absent | Insérer `null`, ne pas bloquer le pipeline |
| `categories_tags` vide | Produit non catégorisé, `off_not_categorized = true` |

### Produits Vrac/CATEGORY (non-EAN)

Pour les produits `CATEGORY` dans Open Prices (fruits, légumes, vrac), l'API OFF par EAN n'est pas applicable. Ces produits sont à comparer via `category_tag`, `labels_tags` et `origins_tags` directement depuis les données Open Prices. **Le Worker OFF ne doit pas tenter de fetcher ces entrées par EAN.**

```python
def should_fetch_from_off(product_type: str, ean: str | None) -> bool:
    """Seuls les produits PRODUCT avec un EAN valide sont fetchés via l'API OFF."""
    if product_type != "PRODUCT":
        return False
    if not ean or len(str(ean).strip()) < 8:
        return False
    return True
```

---

## 8. Normalisation des Données

### Normalisation de l'unité de référence

Le champ `quantity` retourné par OFF est une chaîne libre (`"750 g"`, `"1 L"`, `"6x125g"`, etc.). La normalisation est critique pour la **comparabilité des prix** (prix/kg ou prix/L).

```python
import re

UNIT_MAPPINGS = {
    "g": "g", "gr": "g", "grams": "g", "grammes": "g",
    "kg": "kg", "kilogrammes": "kg",
    "ml": "ml", "mL": "ml", "millilitres": "ml",
    "l": "L", "L": "L", "litres": "L", "liters": "L", "cl": "cl"
}

def parse_unit_reference(quantity_str: str | None) -> dict | None:
    """
    Parse la quantité brute OFF en unité normalisée.
    Retourne {"value": float, "unit": str} ou None si non parseable.
    
    Exemples :
      "750 g"     → {"value": 750.0, "unit": "g"}
      "1 L"       → {"value": 1.0, "unit": "L"}
      "6x125g"    → {"value": 750.0, "unit": "g"}  (produit multi-unités)
      "33 cl"     → {"value": 330.0, "unit": "ml"}
    """
    if not quantity_str:
        return None
    
    quantity_str = quantity_str.strip()
    
    # Cas multi-unités : "6x125g" ou "6 x 125 g"
    multi_match = re.match(r"(\d+)\s*[xX×]\s*(\d+\.?\d*)\s*([a-zA-Z]+)", quantity_str)
    if multi_match:
        count = float(multi_match.group(1))
        value = float(multi_match.group(2))
        unit_raw = multi_match.group(3).lower()
        unit = UNIT_MAPPINGS.get(unit_raw, unit_raw)
        # Convertir cl → ml
        if unit == "cl":
            return {"value": count * value * 10, "unit": "ml"}
        return {"value": count * value, "unit": unit}
    
    # Cas standard : "750 g" ou "750g"
    match = re.match(r"(\d+\.?\d*)\s*([a-zA-Z]+)", quantity_str)
    if match:
        value = float(match.group(1))
        unit_raw = match.group(2).lower()
        unit = UNIT_MAPPINGS.get(unit_raw, unit_raw)
        if unit == "cl":
            return {"value": value * 10, "unit": "ml"}
        return {"value": value, "unit": unit}
    
    return None
```

### Normalisation des catégories PNNS

Si `pnns_groups_1` est absent, tenter d'inférer depuis `categories_tags` :

```python
PNNS_INFERENCE_MAP = {
    "en:beverages": "Beverages",
    "en:dairy": "Milk and dairy products",
    "en:cereals-and-potatoes": "Cereals and potatoes",
    "en:fruits-and-vegetables": "Fruits and vegetables",
    "en:meat": "Fish Meat Eggs",
    "en:fish": "Fish Meat Eggs",
    "en:legumes": "Legumes",
    "en:fats": "Fat and sauces",
    "en:sugary-snacks": "Sugary snacks",
    "en:salty-snacks": "Salty snacks",
    "en:composite-foods": "Composite foods",
}

def infer_pnns_from_tags(categories_tags: list[str]) -> str | None:
    for tag in categories_tags:
        if tag in PNNS_INFERENCE_MAP:
            return PNNS_INFERENCE_MAP[tag]
    return None
```

---

## 9. Bulk Fetching : Récupération par Lots

L'API OFF v2 permet de récupérer **plusieurs produits par EAN** en une seule requête via le paramètre `code` avec des valeurs séparées par des virgules.

### Endpoint multi-EAN

```
GET https://world.openfoodfacts.org/api/v2/search?code={ean1},{ean2},{ean3}&fields=product_name,brands,...
```

> ⚠️ **Attention :** Cet endpoint utilise le chemin `/api/v2/search` qui est soumis à la **limite de 10 req/min** (plus restrictive). À utiliser avec parcimonie.

### Exemple Python pour batch de 5 EAN max

```python
def fetch_products_batch(ean_list: list[str], fields: str) -> dict[str, dict]:
    """
    Fetch plusieurs produits en une requête.
    Retourne un dict {ean: product_data}.
    Limiter à 5-10 EAN par batch pour éviter les timeouts.
    """
    code_param = ",".join(ean_list[:10])  # Max 10 EAN par batch
    url = "https://world.openfoodfacts.org/api/v2/search"
    
    response = requests.get(
        url,
        params={"code": code_param, "fields": fields},
        headers={"User-Agent": "PriceTracker-WorkerOFF/1.0 (contact@pricetracker.fr)"},
        timeout=15
    )
    response.raise_for_status()
    data = response.json()
    
    results = {}
    for product in data.get("products", []):
        ean = product.get("code")
        if ean:
            results[ean] = product
    
    return results
```

> 💡 **Recommandation :** Pour des volumes importants (> 500 EAN nouveaux par jour), préférer l'approche individuelle `/api/v2/product/{ean}` avec rate limiting plutôt que le batch search, pour avoir un meilleur contrôle des erreurs par EAN.

---

## 10. Endpoint de Recherche (usage limité)

> ⚠️ **Le Worker OFF ne doit PAS utiliser le search endpoint pour des recherches textuelles.** La limite de 10 req/min est facilement atteinte, et l'usage principal du Worker est la résolution EAN → données produit, pas la recherche textuelle.

Si un besoin de recherche par catégorie ou marque émerge (ex : pour enrichir des produits sans EAN), voici les paramètres disponibles :

```
GET https://world.openfoodfacts.org/api/v2/search
```

| Paramètre | Description | Exemple |
|---|---|---|
| `code` | EAN(s), séparés par virgule | `3017624010701,3017620422003` |
| `categories_tags_en` | Filtre par catégorie (EN) | `Orange Juice` |
| `nutrition_grades_tags` | Filtre par Nutriscore | `a`, `b`, `c`, `d`, `e` |
| `sort_by` | Tri des résultats | `last_modified_t`, `unique_scans_n` |
| `fields` | Champs à retourner | Voir section 6 |
| `page` | Numéro de page (défaut: 1) | `2` |
| `page_size` | Résultats par page (défaut: 24, max: 1000) | `100` |

> **Recherche full-text :** La recherche full-text n'est supportée que par l'**API v1** (`/cgi/search.pl`), pas par la v2. L'API v2 `search` ne supporte que des **filtres sur les tags** (categories, nutrition_grades, etc.).

---

## 11. Téléchargement Bulk vs Appels API

### Règle fondamentale d'OFF

> *"Si vous avez besoin de fetcher plus de quelques centaines de produits, nous vous demandons de télécharger les données directement sous forme de fichier CSV ou JSONL."*

### Comparaison des approches

| Critère | API `/api/v2/product/{ean}` | Bulk Download (JSONL/CSV) |
|---|---|---|
| Volume recommandé | < 500 EAN/jour (nouveaux) | > 500 EAN, initialisation complète |
| Rate limit | 15 req/min | Aucun (download direct) |
| Fraîcheur des données | Temps réel | Export quotidien (une fois par jour) |
| Latence | ~200-500ms/requête | Download unique ~2-5 GB compressé |
| Usage dans PriceTracker | Worker OFF (delta quotidien) | Initialisation du catalogue (`init`) |

### URLs de téléchargement bulk

```bash
# Export complet JSONL (tous produits, ~2 GB gzippé)
https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz

# Export CSV (format simplifié)
https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz

# Export delta (mise à jour quotidienne incrémentale recommandée)
https://static.openfoodfacts.org/data/delta/{YYYY-MM-DD}.jsonl.gz
```

### Stratégie recommandée pour PriceTracker

```
INITIALISATION (une seule fois) :
  → Télécharger openfoodfacts-products.jsonl.gz
  → Charger dans BigQuery (table de référence OFF complète)
  → Joindre avec open_prices_clean pour pré-remplir catalogue_produits

OPÉRATION QUOTIDIENNE (Worker OFF 04h00) :
  → Identifier les EAN delta (nouveaux dans open_prices_clean)
  → Si volume delta < 500 : appels API individuels avec rate limiting
  → Si volume delta > 500 : télécharger delta/{date}.jsonl.gz + joindre
```

---

## 12. Implémentation du Worker OFF dans le Contexte PriceTracker

### Flux complet du Worker OFF (04h00)

```
BigQuery Silver
  open_prices_clean
       │
       │ SELECT nouveaux EAN (delta depuis last_synced_at)
       ▼
  Liste EAN à enrichir
       │
       │ Pour chaque EAN : GET /api/v2/product/{ean}
       │ Rate limit : 4.5s entre requêtes
       │ Backoff sur 429/503
       ▼
  Données OFF brutes
       │
       │ Normalisation :
       │  - unit_reference (parse_unit_reference)
       │  - category_l3 (dernier tag en:*)
       │  - brand (premier de la liste)
       │  - pnns inference si absent
       ▼
  Entrées catalogue normalisées
       │
       ├──▶ BigQuery Silver : catalogue_produits (UPSERT sur ean)
       │
       └──▶ Cloud SQL (pgvector) : generate + store embedding
              Input embedding = f"{name_canonical} {brand} {category_l3}"
```

### Template complet du Worker OFF

```python
import time
import requests
from datetime import datetime
from google.cloud import bigquery

HEADERS = {"User-Agent": "PriceTracker-WorkerOFF/1.0 (contact@pricetracker.fr)"}
OFF_BASE_URL = "https://world.openfoodfacts.org"
FIELDS = "product_name,brands,categories_tags,pnns_groups_1,pnns_groups_2,nutrition_grades,ecoscore_grade,serving_size,product_quantity,quantity,labels_tags,origins_tags"
RATE_LIMIT_DELAY = 4.5  # secondes

def get_new_eans_from_bigquery(bq_client: bigquery.Client) -> list[str]:
    query = """
        SELECT DISTINCT op.product_code AS ean
        FROM `pricetracker.silver.open_prices_clean` op
        LEFT JOIN `pricetracker.silver.catalogue_produits` cat ON op.product_code = cat.ean
        WHERE op.product_type = 'PRODUCT'
          AND op.product_code IS NOT NULL
          AND (
            cat.ean IS NULL
            OR cat.last_synced_at < DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
          )
        LIMIT 500
    """
    return [row.ean for row in bq_client.query(query).result()]


def fetch_off_product(ean: str) -> dict | None:
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{OFF_BASE_URL}/api/v2/product/{ean}.json",
                params={"fields": FIELDS},
                headers=HEADERS,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("product") if data.get("status") == 1 else None
            elif resp.status_code in (429, 503):
                time.sleep((2 ** attempt) * 60)
            else:
                return None
        except Exception as e:
            time.sleep(30)
    return None


def run_worker_off():
    bq_client = bigquery.Client()
    ean_list = get_new_eans_from_bigquery(bq_client)
    print(f"Worker OFF : {len(ean_list)} EAN à traiter")
    
    catalogue_rows = []
    for ean in ean_list:
        product = fetch_off_product(ean)
        entry = build_catalogue_entry(ean, product)  # voir section 7
        catalogue_rows.append(entry)
        time.sleep(RATE_LIMIT_DELAY)
    
    # UPSERT dans BigQuery Silver catalogue_produits
    # ... (utiliser bq_client.insert_rows_json ou un job MERGE)
    print(f"Worker OFF terminé : {len(catalogue_rows)} entrées insérées/mises à jour.")


if __name__ == "__main__":
    run_worker_off()
```

---

## 13. SDK Python Officiel

Un SDK Python officiel est disponible et maintenu par la communauté OFF :

```bash
pip install openfoodfacts
```

- **GitHub :** https://github.com/openfoodfacts/openfoodfacts-python
- **PyPI :** https://pypi.org/project/openfoodfacts/

> ⚠️ **Attention avant utilisation :** Vérifier que le SDK gère correctement :
> - Le rate limiting (il ne gère pas toujours le backoff automatique)
> - Le paramètre `fields` pour limiter les réponses
> - La version de l'API (v2 vs v3)
>
> Pour le Worker OFF de PriceTracker, l'implémentation directe avec `requests` (voir sections 5 et 12) est préférable car elle offre un meilleur contrôle sur le rate limiting et la gestion des erreurs.

---

## 14. Licences & Obligations Légales

### Licences des données OFF

| Type de données | Licence |
|---|---|
| Base de données OFF (structure) | [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1.0/) |
| Contenu individuel de la base | [Database Contents License (DbCL)](https://opendatacommons.org/licenses/dbcl/1.0/) |
| Images produits | [Creative Commons Attribution ShareAlike (CC BY-SA 3.0)](https://creativecommons.org/licenses/by-sa/3.0/deed.en) |

### Obligations pour PriceTracker

1. **Attribution :** Mentionner Open Food Facts comme source de données dans la documentation et l'interface de PriceTracker.
2. **Share-alike :** Si PriceTracker publie des données dérivées des données OFF, elles doivent être publiées sous la même licence ODbL.
3. **Déclaration d'usage :** [Remplir le formulaire de déclaration d'usage API](https://docs.google.com/forms/d/e/1FAIpQLSdIE3D8qvjC_zRJw1W8OmuHhsWJ_NSckiiniAHlfaVwUZCziQ/viewform) avant la mise en production.
4. **Compte dédié :** Créer un compte OFF au nom de l'application (ex : `pricetracker-app`) pour les éventuelles contributions. Utiliser les paramètres `app_name`, `app_version`, `app_uuid` dans les requêtes d'écriture.

> ℹ️ Les données enrichissent un catalogue **interne**. Les prix collectés par PriceTracker depuis les tickets utilisateurs **ne sont pas des données OFF** et ne sont pas soumis à l'ODbL.

---

## 15. Environnement de Staging & Tests

### Staging OFF

- **URL :** `https://world.openfoodfacts.net`
- **Auth HTTP Basic :** `off` / `off`
- **Base de données séparée** de la production
- Utiliser pour tous les tests du Worker OFF

### Tests recommandés

Créer une suite de tests d'intégration couvrant :

```python
# Cas à tester obligatoirement
TEST_EANS = {
    "3017624010701": "Produit très connu (Nutella) — doit être trouvé avec toutes les données",
    "3175680011534": "Produit standard français — données partielles possibles",
    "0000000000000": "EAN invalide — doit retourner status=0 sans exception",
    "9999999999999": "EAN inconnu — doit retourner status=0 proprement",
}

# Tester le rate limiting
# Tester le backoff sur 429 (simulé avec un mock)
# Tester la normalisation d'unité sur des cas ambigus
# Tester l'upsert BigQuery sur un EAN déjà existant
```

---

## 16. Référence Rapide des URLs

| Action | URL | Notes |
|---|---|---|
| GET produit par EAN | `https://world.openfoodfacts.org/api/v2/product/{ean}.json` | Endpoint principal Worker OFF |
| GET multiple EAN | `https://world.openfoodfacts.org/api/v2/search?code={ean1},{ean2}&fields=...` | Limite 10 req/min |
| Staging GET produit | `https://world.openfoodfacts.net/api/v2/product/{ean}.json` | Auth Basic `off`/`off` requis |
| Download bulk JSONL | `https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz` | Initialisation catalogue |
| Download delta quotidien | `https://static.openfoodfacts.org/data/delta/{YYYY-MM-DD}.jsonl.gz` | Alternative haute volumétrie |
| Documentation OpenAPI v2 | `https://openfoodfacts.github.io/openfoodfacts-server/api/ref-v2/` | Référence complète |
| Documentation OpenAPI v3 | `https://openfoodfacts.github.io/openfoodfacts-server/api/ref-v3/` | En développement actif |
| Cheatsheet API | `https://openfoodfacts.github.io/openfoodfacts-server/api/ref-cheatsheet/` | Référence rapide |
| FAQ API | `https://support.openfoodfacts.org/help/en-gb/12-api` | Support |
| Formulaire déclaration usage | [Google Form](https://docs.google.com/forms/d/e/1FAIpQLSdIE3D8qvjC_zRJw1W8OmuHhsWJ_NSckiiniAHlfaVwUZCziQ/viewform) | Obligatoire avant prod |

---

*Document généré pour le projet PriceTracker — ESGI 5 IABD 2 — Mai 2026*  
*Sources : [OFF API Documentation](https://openfoodfacts.github.io/openfoodfacts-server/api/), [OFF API Tutorial](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorial-off-api/), [OFF API CheatSheet](https://openfoodfacts.github.io/openfoodfacts-server/api/ref-cheatsheet/)*
