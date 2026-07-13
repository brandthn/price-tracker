# receipt_vlm — le VLM maison (côté entraînement)

Le code du modèle vision-langage entraîné from scratch pour lire les tickets, et
sortir directement le schéma canonique du projet
(`{"ticket": {"date", "chaine_supermarche", "adresse", "produits": [...]}}`) — donc
sans rien changer au parsing/validation de `receipt_ocr` à l'inférence.

L'architecture, environ 457M de paramètres mais seulement une vingtaine de
millions réellement entraînés :

- encodeur vision **CLIP ViT-B/16**, pré-entraîné, gelé ;
- **projecteur multimodal** écrit à la main (cross-attention + 32 query tokens
  appris) : c'est la pièce qu'on entraîne vraiment ;
- décodeur **SmolLM2-360M-Instruct**, pré-entraîné, gelé ;
- **LoRA fait main** sur chaque `q_proj` / `v_proj`, sans `peft` ;
- **décodage contraint JSON** : machine à états qui masque les tokens, 0 paramètre.

## Ce qu'il y a dans le package

```
receipt_vlm/
├── models/      vlm.py (l'assemblage), projector.py, lora.py,
│                constrained.py (le masque JSON),
│                ocr_vlm.py + ocr_encoder.py / ocr_decoder.py (la variante OCR pure)
├── data/        synthetic.py (génération de faux tickets), samples.py, dataset.py,
│                ocr_dataset.py, tokenizer.py, schema.py, lin_schema.py,
│                augmentation.py, ocr_transform.py, locales.py, real_photos.py,
│                et les adaptateurs de datasets publics : cord_adapter,
│                sroie_adapter, wildreceipt_adapter, trainingdatapro_adapter
├── training/    trainer.py, le curriculum en 3 temps
└── utils/       metrics.py
```

Le curriculum (`training/trainer.py`) : d'abord on chauffe le projecteur seul
(le reste est gelé), puis on ouvre les LoRA, et enfin on aligne sur le JSON. Dans
cet ordre, parce qu'un projecteur non entraîné qui pousse du bruit dans le
décodeur ne fait qu'abîmer les LoRA.

Les données d'entraînement sont majoritairement synthétiques (`data/synthetic.py`
fabrique des tickets français plausibles avec leurs labels) — on n'a pas de jeu
labellisé assez gros, et labelliser à la main des centaines de tickets n'était pas
tenable dans le temps du projet.

## Entraînement et éval

Deux modèles, donc deux boucles d'entraînement séparées. C'est la chose à savoir
avant de lire quoi que ce soit d'autre ici :

| | modèle | script | boucle |
|---|---|---|---|
| hybride | CLIP + SmolLM2 + LoRA | `scripts/train.py` (+ `configs/phase*.yaml`) | `receipt_vlm/training/trainer.py` |
| from scratch | `OcrVLM`, tout maison | `scripts/train_ocr_vlm.py` | dans le script lui-même |

Le second n'utilise **pas** `trainer.py`. Chercher son entraînement dans le paquet
est une perte de temps : tout est dans le script.

Les données d'entraînement ne sont pas sur le disque. `scripts/train_ocr_vlm.py`
construit des échantillons dont l'image est un *callable* : le ticket est dessiné au
moment où le DataLoader le demande. À chaque epoch le modèle voit donc des tickets
fraîchement rendus, avec une mise en page, une police et des distorsions différentes,
et un label parfait par construction. C'est ce qui permet d'entraîner un modèle de
lecture sans posséder un seul ticket annoté à la main.

**En pratique tout tourne sur Kaggle** (`notebooks/*_kaggle.ipynb`). Un `generate` en
local a déjà figé la machine, et il n'y a aucune raison de retenter. Les notebooks
Colab / Vertex et les configs `*_local.yaml` sont des pistes qu'on a explorées puis
abandonnées ; elles sont gardées ici pour mémoire, pas pour être relancées.

Le tokenizer caractère est figé au premier run et sauvé à côté du checkpoint. C'est
pour ça que le worker a besoin de **deux** fichiers : un checkpoint sans le vocabulaire
avec lequel il a été entraîné ne vaut rien.

## Ce qu'il y a autour du package

- `scripts/` : entraînement, éval, export, génération synthétique, pseudo-labelling.
- `configs/` : les YAML du curriculum en 3 phases (hybride uniquement).
- `notebooks/` : les runs Kaggle, plus les variantes Colab/Vertex abandonnées.
- `tests/` : `pytest tests -m "not slow"`. Les tests `slow` téléchargent CLIP et
  SmolLM2, donc on les saute par défaut.

## Inférence

Le checkpoint entraîné est consommé par le worker `workers/ocr-vlm-scratch`
(`scratch_backend.py`), qui charge le `.pt` et le tokenizer posés par le bootstrap
des poids depuis GCS. Ce package peut importer `receipt_ocr` ; l'inverse est
interdit.
