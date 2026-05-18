# PriceTracker — Suivi de l'Inflation consommateur

**Projet annuel — Mastère Intelligence Artificielle & Big Data**
ESGI 5 IABD 2 — Année académique 2025-2026

---

## Table des matières

1. [Vision : Mesurer l'Inflation Réelle](#1-vision--mesurer-linflation-réelle)
2. [Personas Clés](#2-personas-clés)
3. [Flux Utilisateur Principal](#3-flux-utilisateur-principal)
4. [Fonctionnalités Utilisateur & Composantes IA](#4-fonctionnalités-utilisateur--composantes-ia)
5. [Calcul des Indices d'Inflation](#5-calcul-des-indices-dinflation)
6. [Sources de Données](#6-sources-de-données)
7. [Catalogue Produits — Brique Centrale](#7-catalogue-produits--brique-centrale)
8. [Architecture Technique — Synthèse](#8-architecture-technique--synthèse)
9. [Frontend & Orchestration Data](#9-frontend--orchestration-data)
10. [Stockage des Données](#10-stockage-des-données)
11. [Catégorisation et Embeddings : Le Processus](#11-catégorisation-et-embeddings--le-processus)

---

## 1. Vision : Mesurer l'Inflation Réelle

PriceTracker est une plateforme crowdsourcée qui mesure l'inflation **réelle et vécue** par les consommateurs français. Son originalité repose sur la combinaison de deux sources de données :

- **Dataset Public Open Prices** — Prix au niveau EAN, géolocalisés, datés, mis à jour quotidiennement (HuggingFace).
- **Tickets de Caisse Utilisateurs** — Tickets uploadés par les utilisateurs, traités par un pipeline OCR/NLP.

Ces données sont croisées avec un **catalogue produit normalisé** (Open Food Facts) pour calculer des indices d'inflation personnalisés, régionaux et nationaux, comparés aux chiffres officiels de l'INSEE.

---

## 2. Personas Clés

Nous avons identifié deux personas principales pour PriceTracker, chacune avec des besoins spécifiques liés au suivi de l'inflation.

### Mère de famille (35-45 ans)

Budget serré, achète chez Leclerc/Lidl. Cherche à réduire sa facture de 10-15% et reçoit des alertes sur les hausses de prix.

> Marie, 38 ans, employée administrative avec 2 enfants, gagne environ 2 000 €/mois. Elle photographie ses tickets pour suivre l'évolution de ses produits habituels (lait, pain, hygiène) et cherche des substituts moins chers ainsi que des alertes de hausse.

### Jeune actif (25-35 ans)

Étudiant ou salarié. Souhaite un suivi hebdomadaire et trouver les prix les moins chers dans sa ville.

---

## 3. Flux Utilisateur Principal

Parcours d'un utilisateur, de l'upload d'un ticket de caisse à la réception d'alertes personnalisées et la consultation de l'observatoire public.

1. **Upload** — L'utilisateur photographie son ticket, qui est directement uploadé vers GCS et déclenche le Worker OCR.
2. **Extraction & Résolution** — Preprocessing image, inférence OCR, parsing structuré et résolution EAN via NLP matching.
3. **Validation Utilisateur** — Résultat présenté à l'utilisateur pour feedback et correction, alimentant les alias produits.
4. **Calcul périodique (2× hebdo ou Nightly)** — Job BigQuery pour calculer les indices d'inflation (personnel, régional, national) et détecter les anomalies de prix.
5. **Alerte** — Détection des hausses sur les produits habituels et envoi de notifications push.
6. **Observatoire** — Suivi de la consommation personnelle et analyse de l'inflation en France.

---

## 4. Fonctionnalités Utilisateur & Composantes IA

### WebApp (Next.js)

- Upload de tickets de caisse avec extraction automatique.
- Validation/correction des articles mal reconnus.
- Dashboard personnel : inflation, évolution dans le temps.
- Carte choroplèthe France : inflation par département.
- Classement enseignes, "Hall of Shame" des produits en hausse.
- Recommandations d'économies personnalisées.

### Composantes IA & Data

#### Pipeline OCR — (Modèle OCR)

Traitement des photos de tickets (preprocessing, extraction texte via modèle custom, parsing structuré, score de confiance).

#### Résolution EAN

Mapper texte OCR bruité vers EAN canonique (NLP matching, similarité vectorielle, feedback loop utilisateur).

#### Recommandations Économies

Comparaison inter-enseignes, substituts par catégorie et sémantiques.

#### Détection Anomalies Prix

Filtrage des prix aberrants via Z-score SQL pour garantir la qualité des indices.

---

## 5. Calcul des Indices d'Inflation

Les indices sont calculés nuitamment dans BigQuery à partir des données Silver validées. Nous utilisons une formule d'**indice de Laspeyres pondérée par la fréquence d'achat**, standard et académiquement défendable.

- **Indice Personnel** — Panier réel de l'utilisateur (produits achetés ≥ 2 fois sur 6 mois), variation N vs N-1.
- **Indice Régional** — Agrégation par département.
- **Indice National** — Agrégation France entière.

---

## 6. Sources de Données

### Open Prices (HuggingFace)

- Format : Parquet, mis à jour quotidiennement (~1 MB/jour incrémental).
- Contient des données `PRODUCT` (EAN) et `CATEGORY` (produits bruts/vrac).

### Tickets de Caisse Utilisateurs

- Photos uploadées via l'application web/mobile.
- Données extraites : enseigne, date, articles (texte brut → EAN), prix, quantités.
- Source primaire pour les contributions communautaires récentes.

### Open Food Facts (OFF) API

- Enrichissement du catalogue à partir de l'EAN.
- Données récupérées : nom canonique, marque, catégorie normalisée, Nutriscore, Ecoscore.

---

## 7. Catalogue Produits — Brique Centrale

Le catalogue est le référentiel dont dépendent toutes les autres composantes. Sans lui, les EAN sont opaques et incomparables.

### Structure Logique

- `products` (ean, name_canonical, brand, category_1/2/3, unit_reference, nutriscore, last_synced_at)
- `product_aliases` (raw_text, ean, confidence, validated_by_user)

### Catalogage Produits Bruts

Les produits de type `CATEGORY` (bruts/vrac) sont comparables via `category_tag`, `labels_tags` et `origins_tags` sans passer par l'EAN.

### Comparabilité & Substituts

Deux produits sont comparables s'ils partagent la même `category_l3` et la même unité de référence. La recherche de substituts sémantiques utilise des embeddings produits (pgvector).

---

## 8. Architecture Technique — Synthèse

Infrastructure intégralement sur **Google Cloud Platform (GCP)**, provisionnée en **Terraform** pour la portabilité.

| Service | Rôle |
|---|---|
| Cloud Run | Backend API (scale-to-zero), Workers data et OCR |
| Cloud SQL (PG 15) | Données opérationnelles : users, tickets, aliases, embeddings produits (pgvector) |
| BigQuery | Data warehouse : Open Prices (bronze→silver→gold), catalogue, indices, agrégats observatoire |
| Cloud Storage (GCS) | Images tickets, fichiers Parquet archivés, modèles ML |
| Pub/Sub + Eventarc | Déclenchement asynchrone du Worker OCR à l'upload |
| Firebase Auth | Authentication managée (JWT, email/password, reset) |
| Firebase Cloud Msg | Push notifications alertes |
| Artifact Registry | Images Docker des services Cloud Run |
| Secret Manager | Credentials (Cloud SQL, Firebase Admin SDK…) |

---

## 9. Frontend & Orchestration Data

### Frontend

- Next.js déployé sur Vercel (free tier).
- Observatoire public et dashboard utilisateur.

### Orchestration Data (Bronze → Silver → Gold)

L'orchestration est gérée par Cloud Scheduler, appelant des Cloud Run Services.

- **03h00 — Worker Ingestion** : HuggingFace Parquet → GCS → BQ Silver
- **04h00 — Worker OFF** : EAN → OFF API → catalogue + embeddings
- **05h00 — Worker Indices** : Silver → calcul indices → BQ Gold + INSEE
- **07h00 — Worker Alertes** : Gold → détection hausses → push FCM

---

## 10. Stockage des Données

Les données sont réparties entre **Cloud SQL** pour les transactions opérationnelles, **BigQuery** pour l'analytique et l'historisation, et **Cloud Storage** pour les fichiers bruts.

### Cloud SQL (PostgreSQL)

| Table | Cas d'usage concret |
|---|---|
| `users` | Profil utilisateur, préférences, département. Complète Firebase Auth. |
| `tickets` | Métadonnées des tickets uploadés : statut, lien GCS, enseigne, date. |
| `prix_extraits` | Lignes articles brutes des tickets, avec prix, confiance OCR, et validation utilisateur. |
| `product_aliases` | Mapping "texte brut" → EAN canonique, enrichi par le feedback utilisateur. |
| `products` (pgvector) | Embeddings des fiches produit pour les recommandations sémantiques. |
| `user_basket_history` | Historique des EAN achetés régulièrement par l'utilisateur pour l'indice personnel. |
| `notification_prefs` | Seuils d'alerte, fréquence et enseignes favorites par utilisateur. |

### BigQuery

Plateforme d'entrepôt de données pour les flux Bronze, Silver et Gold.

#### Dataset Silver

| Table | Contenu | Alimenté par |
|---|---|---|
| `open_prices_clean` | Entrées Open Prices filtrées France, dédupliquées et partitionnées par date. | Worker Ingestion (03h00) |
| `catalogue_produits` | Fiches EAN (nom, marque, catégorie L1/L2/L3, nutriscore, unité de référence). | Worker OFF (04h00) |

#### Dataset Gold

| Table | Contenu | Alimenté par |
|---|---|---|
| `indices_inflation` | Indices de Laspeyres (national, régional). | Worker Indices (05h00) |
| `aggregats_enseignes` | Prix moyen par produit × enseigne × semaine. | Worker Indices (05h00) |
| `rankings_produits` | Top hausses du mois, Hall of Shame. | Worker Indices (05h00) |
| `anomalies_detected` | Prix aberrants exclus des calculs d'indices. | Worker Indices (05h00) |

### Cloud Storage

#### GCS Bronze

- `/open-prices/date=YYYY-MM-DD/snapshot.parquet` : Archives brutes des données HuggingFace.
- `/tickets/raw/user_id/uuid.jpg` : Images brutes des tickets uploadés par les utilisateurs.

## 11. Catégorisation et Embeddings : Le Processus

1. **Détection EAN** — Un nouveau code EAN est identifié dans la table `open_prices_clean` (BigQuery Silver).
2. **Activation Worker OFF** — Le processus est déclenché par le Worker OFF (chaque jour à 04h00).
3. **Appel OFF API** — L'API Open Food Facts est interrogée avec le nouvel EAN.
4. **Récupération des Données** — Les informations du produit (nom, marque, Nutriscore, PNNS) sont extraites.
5. **Normalisation de l'Unité** — L'unité de référence du produit (ex : 1L, 1kg) est normalisée.
6. **Mise à Jour Catalogue BQ** — Les données enrichies sont insérées ou mises à jour dans la table `catalogue_produits` (BigQuery Silver).
7. **Génération d'Embeddings** — Un embedding vectoriel est créé à partir des attributs du produit (nom, marque, catégorie).
8. **Stockage Embeddings SQL** — L'embedding est enregistré dans Cloud SQL `products` (via pgvector) pour la recherche de similarité.