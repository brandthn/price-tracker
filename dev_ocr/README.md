# receipt_ocr

Extraction de données structurées à partir de photos de tickets de caisse
français.

```python
from receipt_ocr import extract_receipt

data = extract_receipt("data/raw/images_tickets_caisse/image_2.jpg")
```

Ce qui sort :

```json
{
  "ticket": {
    "date": "yyyyMMdd HH:mm",
    "chaine_supermarche": "nom",
    "adresse": "adresse complète",
    "produits": [
      { "nom_produit": "nom", "prix_unitaire_ou_kg": 0.00, "unites": 1 }
    ]
  }
}
```

Un backend OCR rend du texte brut, `ReceiptParser` en fait le dict ci-dessus. Les
deux sont indépendants : on change de moteur sans toucher au parsing. Les backends
dispo : `paddle` (défaut), `ppocrv4` (plus rapide), `vlm` (Moondream en local ou
Groq en cloud). `tesseract` et `easyocr` sont des stubs qui lèvent
`NotImplementedError`.

L'historique et les notes de perf sont dans [`documentation.md`](documentation.md).

## Installation

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # PowerShell
# source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt
```

`paddleocr` + `paddlepaddle` pour le backend par défaut, `Pillow` pour le resize
avant OCR, `pytest` pour les tests, et `huggingface_hub` / `kagglehub` seulement si
on télécharge les datasets.

Pour ne lancer que les tests unitaires, `pip install pytest` suffit — le package
s'importe sans aucune lib OCR installée (les imports tiers sont faits à
l'instanciation du backend, exprès).

## Utilisation

Sur une image, en partant de la racine `dev_ocr/` :

```bash
$env:PYTHONPATH = "src"     # PowerShell ; export PYTHONPATH=src en bash
python scripts/smoke_test_ocr.py data/raw/images_tickets_caisse/image_2.jpg
```

Compter ~30-40 s de chargement des modèles au premier appel, puis 1 à 2 minutes
par grosse photo sur CPU. C'est normal, et avec les réglages par défaut la machine
reste utilisable pendant ce temps (ça n'a pas toujours été le cas, cf.
`documentation.md`).

`scripts/test_extract_receipt.py` fait la même chose mais en passant par l'API
publique, et vérifie le schéma de sortie.

En batch, construire le backend une seule fois — sinon on recharge les poids à
chaque image :

```python
from receipt_ocr import extract_receipt
from receipt_ocr.backends import PaddleOcrBackend

backend = PaddleOcrBackend()
for path in image_paths:
    data = extract_receipt(path, backend=backend)
```

Sinon le backend se choisit par variable d'env :

```bash
RECEIPT_OCR_BACKEND=ppocrv4 python scripts/smoke_test_ocr.py
```

## Le backend Paddle et ses réglages

Les défauts sont calés pour un laptop Windows, quitte à perdre en vitesse :
moteur `paddle_dynamic` (parce que `paddle_static` + oneDNN plante souvent sur
Windows), poids mobile désactivés (ils exigent `paddle_static`), image ramenée à
1280 px, 2 threads CPU max, MKL-DNN coupé, et tout le pré-traitement PaddleX
(orientation, dewarping) désactivé.

| Variable | Défaut | Rôle |
|---|---|---|
| `RECEIPT_OCR_CPU_THREADS` | `2` | Threads max. Monter ça, c'est prendre le risque de figer la machine. |
| `RECEIPT_OCR_MAX_IMAGE_SIDE` | `1280` | Côté le plus long avant OCR (`0` = pas de resize). |

Sur Linux, où `paddle_static` tient la route, `PaddleOcrBackend(use_mobile_models=True)`
utilise les poids `PP-OCRv4_mobile_det`, plus légers.

## Le backend VLM

`RECEIPT_OCR_BACKEND=vlm`, puis on choisit le provider avec `RECEIPT_VLM_MODEL`.

**Groq (cloud, JSON).** Impose `RECEIPT_VLM_MODE=json` — les autres modes lèvent
une erreur, un modèle cloud qui transcrit ligne à ligne n'aurait pas d'intérêt.

```bash
pip install -r requirements-groq.txt
# .env : GROQ_API_KEY=...  (ou l'ancien groq_key)

$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODEL = "groq-llama4-scout"
$env:RECEIPT_VLM_MODE = "json"
python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/ticket.jpg
```

**Moondream 0.5B (local).** Trois modes. Le défaut est `transcribe` : on demande au
VLM du texte ligne à ligne, puis `ReceiptParser` fait le reste. Un 0.5B s'en sort
bien mieux sur une tâche étroite que sur « rends-moi tout le JSON ».

```bash
pip install -r requirements-vlm.txt
python scripts/download_moondream_weights.py     # -> data/models/, gitignoré

$env:RECEIPT_OCR_BACKEND = "vlm"
$env:RECEIPT_VLM_MODE = "transcribe"             # transcribe | json | multipass
python scripts/run_vlm_test.py data/raw/images_tickets_caisse/image_12.jpg
python scripts/benchmark_vlm.py                  # compare les modes
```

| Variable | Défaut | Rôle |
|---|---|---|
| `RECEIPT_VLM_MODE` | `transcribe` | `transcribe` / `json` / `multipass` |
| `RECEIPT_VLM_MODEL` | `moondream-0.5b` | `moondream-0.5b` ou `groq-llama4-scout` |
| `RECEIPT_VLM_MODEL_PATH` | `data/models/…` | poids `.mf` locaux |
| `RECEIPT_VLM_MAX_IMAGE_SIDE` | `1536` | resize avant inférence (`0` = off) |
| `RECEIPT_VLM_CROP` | `auto` | `auto` / `center` / `off` |
| `RECEIPT_VLM_MAX_RETRIES` | `2` | retries si la sortie est bavarde ou invalide |
| `RECEIPT_VLM_TEMPERATURE` | `0.1` | température |
| `RECEIPT_VLM_MAX_TOKENS` | `1024` | tokens max par requête |
| `RECEIPT_GROQ_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | modèle côté Groq |

Quand la validation échoue jusqu'au bout des retries, on lève un
`ReceiptParseError` plutôt que de rendre du JSON inventé.

## Ce que le parser sait encaisser

L'en-tête (enseigne + adresse, sans liste de marques en dur), les dates au format
français y compris **coupées sur deux lignes** (`15/10/24` puis `12:40`), les
produits sur une ligne (`PAIN 1,20 €`) comme **étalés sur plusieurs**
(nom → prix unitaire → total → `2 x`), le poids (`0,452 kg x 5,98 €/kg`, y compris
en bloc multi-lignes), et il ignore le pied de ticket (totaux, TVA, paiement).

## Tests

```bash
pytest --no-integration          # unitaires : pas de réseau, pas d'OCR, ~1 s
pytest -m integration            # OCR sur 3 images de images_tickets_caisse/
pytest -m groq                   # vraie API Groq
```

Les tests d'intégration partagent un `PaddleOcrBackend` sur toute la session (un
seul chargement de modèle). Ne pas lancer
`pytest -m integration --integration-all-data` sur un laptop : ça part sur des
centaines d'images.

## Ajouter un backend

Créer `src/receipt_ocr/backends/<nom>_backend.py`, hériter de `OcrBackend` et
implémenter `extract_text(path) -> str`. Deux règles : importer la lib tierce
**dans** `__init__` (sinon `import receipt_ocr` casse pour tout le monde), et
emballer les erreurs dans `OcrBackendError`. Puis l'enregistrer dans
`_BACKEND_REGISTRY` (`extract_receipt.py`) et ajouter un test mocké — voir
`tests/test_paddle_backend.py`.

Ni le parser ni l'API publique n'ont à bouger.

## Datasets de test

```bash
python scripts/download_datasets.py
```

Lit `data/raw/ocr_testing/datasets_to_use_for_testing.txt` (HuggingFace
`shirastromer/supermarket-receipts`, Kaggle `sushmithanarayan/expenses-receipt-ocr`)
et télécharge dans `data/raw/`. Idempotent : ce qui est déjà là n'est pas
retéléchargé, sauf avec `--force`.
