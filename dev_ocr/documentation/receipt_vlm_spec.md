





🧾

French Receipt VLM

Complete Technical Specification

A \~500M parameter Vision-Language Model for parsing French supermarket receipts into structured JSON



Stack: PyTorch · HuggingFace · CLIP · SmolLM · LoRA

For use with Cursor / any AI coding assistant







1\. Project Overview

This project implements a Vision-Language Model (VLM) that takes an image of a French supermarket receipt and outputs a structured JSON object containing all purchase information. The model is \~500M parameters, partially built from scratch (projector, LoRA adapters, JSON decoder, training loop) and partially initialized from pretrained weights (CLIP vision encoder, SmolLM language decoder).



Academic framing

This architecture mirrors LLaVA (Liu et al., 2023): frozen pretrained encoders connected by a learned multimodal projector. The projector, LoRA adapters, and JSON schema head are original contributions coded from scratch in PyTorch.



1.1 Target Output Schema

{

&#x20; "store": {

&#x20;   "name": "Carrefour Market",

&#x20;   "address": "12 rue de la Paix, 75001 Paris",

&#x20;   "siret": "123 456 789 00012"

&#x20; },

&#x20; "date": "2024-03-15",

&#x20; "time": "14:32",

&#x20; "items": \[

&#x20;   {

&#x20;     "name": "Lait demi-écrémé 1L",

&#x20;     "qty": 2,

&#x20;     "unit\_price": 1.09,

&#x20;     "total\_price": 2.18,

&#x20;     "category": "dairy",

&#x20;     "tva\_rate": 5.5

&#x20;   }

&#x20; ],

&#x20; "subtotal\_ht": 12.34,

&#x20; "tva\_breakdown": { "5.5": 0.68, "20.0": 1.12 },

&#x20; "total\_ttc": 14.14,

&#x20; "payment": { "method": "CB", "last4": "4242" },

&#x20; "loyalty\_points": 42

}



1.2 What is built from scratch vs pretrained



Component	Status	Params	Justification

CLIP ViT-B/16 encoder	Frozen pretrained	\~86M	Standard in all VLMs — not trainable

Multimodal projector	Built from scratch	\~15M	Cross-attention + MLP, original design

LoRA adapters (LM)	Built from scratch	\~8M	Hand-rolled, injected into frozen LM

SmolLM base decoder	Partially frozen	\~360M	Pretrained weights, adapted via LoRA

JSON schema decoder head	Built from scratch	\~5M	Receipt-domain specific output layer

Training loop	Built from scratch	—	Raw PyTorch, 3-phase curriculum

Data pipeline	Built from scratch	—	Augmentation, CORD/SROIE adapters, synthetic gen





2\. Architecture

2.1 High-level pipeline

Receipt Image (PNG/JPG)

&#x20;      │

┌──────▼────────────────────┐

│  CLIP ViT-B/16 Encoder    │  86M params — FROZEN

│  patch\_size=16, 197 tokens│  outputs: (B, 197, 768)

└──────┬────────────────────┘

&#x20;      │ vision embeddings

┌──────▼────────────────────┐

│  MultimodalProjector      │  \~15M params — TRAINED FROM SCRATCH

│  CrossAttention + MLP     │  maps 768-dim → 1024-dim (LM space)

└──────┬────────────────────┘

&#x20;      │ projected tokens

┌──────▼────────────────────┐

│  SmolLM Decoder           │  360M params — FROZEN + LoRA adapters

│  + LoRA in every Wq, Wv   │  generates JSON tokens autoregressively

└──────┬────────────────────┘

&#x20;      │ logits

┌──────▼────────────────────┐

│  JSON Schema Head         │  5M params — TRAINED FROM SCRATCH

│  Constrained decoding     │  enforces valid JSON structure

└───────────────────────────┘



2.2 MultimodalProjector — full implementation

This is the core original contribution. It uses cross-attention so language tokens can attend over visual patch embeddings, plus a residual MLP projection:



\# receipt\_vlm/models/projector.py



import torch

import torch.nn as nn

import math





class MultimodalProjector(nn.Module):

&#x20;   """

&#x20;   Maps CLIP patch embeddings into SmolLM token embedding space.

&#x20;   Built entirely from scratch — no pretrained weights.



&#x20;   Args:

&#x20;       vision\_dim: CLIP output dim (768 for ViT-B/16)

&#x20;       lang\_dim:   LM embedding dim (1024 for SmolLM-1.7B)

&#x20;       num\_patches: number of visual tokens (197 for ViT-B/16 + CLS)

&#x20;       num\_heads:  attention heads in cross-attn

&#x20;       dropout:    dropout rate

&#x20;   """

&#x20;   def \_\_init\_\_(self, vision\_dim=768, lang\_dim=1024,

&#x20;                num\_patches=197, num\_heads=8, dropout=0.1):

&#x20;       super().\_\_init\_\_()

&#x20;       self.vision\_dim = vision\_dim

&#x20;       self.lang\_dim = lang\_dim



&#x20;       # Learnable 2D positional encoding for visual patches

&#x20;       self.pos\_embedding = nn.Parameter(

&#x20;           torch.randn(1, num\_patches, vision\_dim) \* 0.02

&#x20;       )



&#x20;       # Cross-attention: language queries attend to visual keys/values

&#x20;       self.cross\_attn = nn.MultiheadAttention(

&#x20;           embed\_dim=lang\_dim,

&#x20;           num\_heads=num\_heads,

&#x20;           kdim=vision\_dim,

&#x20;           vdim=vision\_dim,

&#x20;           dropout=dropout,

&#x20;           batch\_first=True

&#x20;       )



&#x20;       # Query projection: learnable visual summary tokens

&#x20;       self.query\_tokens = nn.Parameter(

&#x20;           torch.randn(1, 32, lang\_dim) \* 0.02  # 32 summary tokens

&#x20;       )



&#x20;       # MLP projection with residual

&#x20;       self.mlp = nn.Sequential(

&#x20;           nn.Linear(vision\_dim, lang\_dim \* 2),

&#x20;           nn.GELU(),

&#x20;           nn.Dropout(dropout),

&#x20;           nn.Linear(lang\_dim \* 2, lang\_dim),

&#x20;       )

&#x20;       self.norm1 = nn.LayerNorm(lang\_dim)

&#x20;       self.norm2 = nn.LayerNorm(lang\_dim)



&#x20;       self.\_init\_weights()



&#x20;   def \_init\_weights(self):

&#x20;       for module in self.mlp.modules():

&#x20;           if isinstance(module, nn.Linear):

&#x20;               nn.init.xavier\_uniform\_(module.weight)

&#x20;               if module.bias is not None:

&#x20;                   nn.init.zeros\_(module.bias)



&#x20;   def forward(self, vision\_features: torch.Tensor) -> torch.Tensor:

&#x20;       """

&#x20;       Args:

&#x20;           vision\_features: (B, num\_patches, vision\_dim) from CLIP

&#x20;       Returns:

&#x20;           projected: (B, 32, lang\_dim) — visual tokens in LM space

&#x20;       """

&#x20;       B = vision\_features.shape\[0]



&#x20;       # Add positional encoding to patches

&#x20;       vision\_features = vision\_features + self.pos\_embedding



&#x20;       # Expand query tokens for batch

&#x20;       queries = self.query\_tokens.expand(B, -1, -1)  # (B, 32, lang\_dim)



&#x20;       # Cross-attention: queries attend to visual patches

&#x20;       attended, \_ = self.cross\_attn(

&#x20;           query=queries,

&#x20;           key=vision\_features,

&#x20;           value=vision\_features

&#x20;       )

&#x20;       attended = self.norm1(attended)  # (B, 32, lang\_dim)



&#x20;       # MLP on patch-level features, then mean-pool and add

&#x20;       patch\_proj = self.mlp(vision\_features)  # (B, num\_patches, lang\_dim)

&#x20;       patch\_summary = patch\_proj.mean(dim=1, keepdim=True)  # (B, 1, lang\_dim)



&#x20;       # Broadcast-add patch summary to all query tokens

&#x20;       output = self.norm2(attended + patch\_summary)



&#x20;       return output  # (B, 32, lang\_dim)



2.3 LoRA Adapters — hand-rolled implementation

Written from scratch in PyTorch. Injected into every query and value projection in the SmolLM transformer layers:



\# receipt\_vlm/models/lora.py



import torch

import torch.nn as nn

from typing import Optional





class LoRALinear(nn.Module):

&#x20;   """

&#x20;   Low-Rank Adaptation of a frozen Linear layer.

&#x20;   Replaces W\*x with W\*x + (B @ A)\*x \* (alpha/rank)



&#x20;   Built from scratch — no peft dependency.

&#x20;   """

&#x20;   def \_\_init\_\_(self, original: nn.Linear, rank: int = 16,

&#x20;                alpha: float = 32.0, dropout: float = 0.05):

&#x20;       super().\_\_init\_\_()

&#x20;       self.original = original

&#x20;       self.rank = rank

&#x20;       self.scale = alpha / rank



&#x20;       # Freeze the original weights

&#x20;       for param in self.original.parameters():

&#x20;           param.requires\_grad = False



&#x20;       d\_out, d\_in = original.weight.shape

&#x20;       self.lora\_A = nn.Linear(d\_in, rank, bias=False)

&#x20;       self.lora\_B = nn.Linear(rank, d\_out, bias=False)

&#x20;       self.dropout = nn.Dropout(dropout)



&#x20;       # Init: A \~ N(0, 0.02), B = 0 → delta = 0 at start

&#x20;       nn.init.normal\_(self.lora\_A.weight, std=0.02)

&#x20;       nn.init.zeros\_(self.lora\_B.weight)



&#x20;   def forward(self, x: torch.Tensor) -> torch.Tensor:

&#x20;       original\_out = self.original(x)

&#x20;       lora\_out = self.lora\_B(self.lora\_A(self.dropout(x)))

&#x20;       return original\_out + self.scale \* lora\_out



&#x20;   def merge\_weights(self) -> nn.Linear:

&#x20;       """Merge LoRA into base weights for inference (no overhead)."""

&#x20;       merged = nn.Linear(

&#x20;           self.original.in\_features,

&#x20;           self.original.out\_features,

&#x20;           bias=self.original.bias is not None

&#x20;       )

&#x20;       merged.weight.data = (

&#x20;           self.original.weight.data +

&#x20;           self.scale \* (self.lora\_B.weight @ self.lora\_A.weight)

&#x20;       )

&#x20;       if self.original.bias is not None:

&#x20;           merged.bias.data = self.original.bias.data.clone()

&#x20;       return merged





def inject\_lora(model: nn.Module, rank: int = 16, alpha: float = 32.0,

&#x20;               target\_modules: list = \['q\_proj', 'v\_proj']) -> nn.Module:

&#x20;   """Recursively replace target Linear layers with LoRALinear."""

&#x20;   for name, module in model.named\_children():

&#x20;       if isinstance(module, nn.Linear) and name in target\_modules:

&#x20;           setattr(model, name, LoRALinear(module, rank=rank, alpha=alpha))

&#x20;       else:

&#x20;           inject\_lora(module, rank, alpha, target\_modules)

&#x20;   return model





def count\_trainable\_params(model: nn.Module) -> dict:

&#x20;   total = sum(p.numel() for p in model.parameters())

&#x20;   trainable = sum(p.numel() for p in model.parameters() if p.requires\_grad)

&#x20;   return {

&#x20;       'total': total,

&#x20;       'trainable': trainable,

&#x20;       'frozen': total - trainable,

&#x20;       'trainable\_pct': 100 \* trainable / total

&#x20;   }





3\. Project Structure

receipt-vlm/

├── receipt\_vlm/

│   ├── \_\_init\_\_.py

│   ├── models/

│   │   ├── \_\_init\_\_.py

│   │   ├── vlm.py              # ReceiptVLM: full model assembly

│   │   ├── projector.py        # MultimodalProjector (FROM SCRATCH)

│   │   ├── lora.py             # LoRALinear + inject\_lora (FROM SCRATCH)

│   │   └── json\_head.py        # JSON schema decoder head (FROM SCRATCH)

│   ├── data/

│   │   ├── \_\_init\_\_.py

│   │   ├── dataset.py          # ReceiptDataset (torch Dataset)

│   │   ├── cord\_adapter.py     # CORD dataset loader \& normalizer

│   │   ├── sroie\_adapter.py    # SROIE dataset loader \& normalizer

│   │   ├── synthetic.py        # French receipt generator (FROM SCRATCH)

│   │   └── augmentation.py     # Receipt-specific augmentations

│   ├── training/

│   │   ├── \_\_init\_\_.py

│   │   ├── trainer.py          # 3-phase training loop (FROM SCRATCH)

│   │   ├── losses.py           # Custom losses

│   │   └── scheduler.py        # LR scheduler helpers

│   └── utils/

│       ├── \_\_init\_\_.py

│       ├── tokenizer.py        # JSON tokenizer helpers

│       └── metrics.py          # F1, exact match, ANLS

├── scripts/

│   ├── train.py                # Entry point: phase 1/2/3

│   ├── evaluate.py             # Eval on held-out receipts

│   ├── infer.py                # Single-image inference

│   └── generate\_synthetic.py   # Standalone synthetic data gen

├── configs/

│   ├── base.yaml               # Default hyperparams

│   ├── phase1.yaml             # Projector pretraining

│   ├── phase2.yaml             # LoRA fine-tuning

│   └── phase3.yaml             # JSON alignment

├── data/

│   ├── raw/                    # CORD, SROIE, your photos

│   ├── processed/              # Normalized JSON + images

│   └── synthetic/              # Generated receipts

├── checkpoints/                # Saved model weights

├── notebooks/

│   ├── 01\_data\_exploration.ipynb

│   ├── 02\_projector\_analysis.ipynb

│   └── 03\_results\_visualization.ipynb

├── requirements.txt

├── setup.py

└── README.md





4\. Data Pipeline

4.1 Data sources \& split strategy



Source	Size	Language	Labels	Split

CORD dataset	\~1,000 receipts	Korean/EN	Field-level bboxes + text	60% train

SROIE dataset	\~1,000 receipts	English	Entity spans	20% val

Your photos	50–100 receipts	French	Manual JSON annotation	10% test

Synthetic French	2,000+ generated	French	Perfect labels (auto)	10% train+



4.2 Synthetic French receipt generator

\# receipt\_vlm/data/synthetic.py

\# Generates photorealistic French receipt images with perfect labels



from PIL import Image, ImageDraw, ImageFont

import random, json, datetime

from dataclasses import dataclass, field

from typing import List



FRENCH\_STORES = \[

&#x20;   {"name": "Carrefour Market", "siret": "552 100 420 00241"},

&#x20;   {"name": "Monoprix", "siret": "552 028 425 00012"},

&#x20;   {"name": "Lidl France", "siret": "343 262 622 00015"},

&#x20;   {"name": "Franprix", "siret": "572 013 591 00032"},

&#x20;   {"name": "Super U", "siret": "334 532 462 00018"},

]



PRODUCTS\_BY\_CATEGORY = {

&#x20;   'produits\_laitiers': \[

&#x20;       ('Lait demi-écrémé 1L', 1.09, 5.5),

&#x20;       ('Yaourt nature x8', 2.45, 5.5),

&#x20;       ('Fromage râpé 200g', 2.89, 5.5),

&#x20;   ],

&#x20;   'épicerie': \[

&#x20;       ('Pâtes spaghetti 500g', 0.99, 5.5),

&#x20;       ('Riz basmati 1kg', 2.19, 5.5),

&#x20;       ('Huile tournesol 1L', 1.89, 5.5),

&#x20;   ],

&#x20;   'boissons': \[

&#x20;       ('Eau minérale 6x1.5L', 2.99, 5.5),

&#x20;       ('Jus d\\u2019orange 1L', 2.49, 5.5),

&#x20;   ],

&#x20;   'hygiène': \[

&#x20;       ('Savon liquide 300ml', 2.15, 20.0),

&#x20;       ('Dentifrice 75ml', 1.89, 20.0),

&#x20;   ],

}



def generate\_receipt(seed: int = None) -> dict:

&#x20;   """Generate a receipt dict with perfect labels."""

&#x20;   rng = random.Random(seed)

&#x20;   store = rng.choice(FRENCH\_STORES)

&#x20;   n\_items = rng.randint(3, 15)

&#x20;   items = \[]

&#x20;   for \_ in range(n\_items):

&#x20;       cat = rng.choice(list(PRODUCTS\_BY\_CATEGORY.keys()))

&#x20;       name, price, tva = rng.choice(PRODUCTS\_BY\_CATEGORY\[cat])

&#x20;       qty = rng.choice(\[1, 1, 1, 2, 3])

&#x20;       items.append({'name': name, 'qty': qty,

&#x20;           'unit\_price': price, 'total\_price': round(qty \* price, 2),

&#x20;           'category': cat, 'tva\_rate': tva})

&#x20;   subtotal = round(sum(i\['total\_price'] for i in items), 2)

&#x20;   tva\_5 = round(sum(i\['total\_price'] for i in items if i\['tva\_rate'] == 5.5) \* 0.055 / 1.055, 2)

&#x20;   tva\_20 = round(sum(i\['total\_price'] for i in items if i\['tva\_rate'] == 20.0) \* 0.2 / 1.2, 2)

&#x20;   d = datetime.datetime.now() - datetime.timedelta(days=rng.randint(0, 365))

&#x20;   return {

&#x20;       'store': store,

&#x20;       'date': d.strftime('%Y-%m-%d'),

&#x20;       'time': d.strftime('%H:%M'),

&#x20;       'items': items,

&#x20;       'subtotal\_ht': round(subtotal - tva\_5 - tva\_20, 2),

&#x20;       'tva\_breakdown': {'5.5': tva\_5, '20.0': tva\_20},

&#x20;       'total\_ttc': subtotal,

&#x20;       'payment': {'method': rng.choice(\['CB', 'ESPÈCES', 'SANS CONTACT'])},

&#x20;   }



def render\_receipt\_image(receipt: dict, width: int = 384) -> Image.Image:

&#x20;   """Render a receipt dict as a PIL image (thermal printer style)."""

&#x20;   lines = \[]

&#x20;   lines += \['=' \* 42, receipt\['store']\['name'].center(42),

&#x20;             f"SIRET: {receipt\['store']\['siret']}".center(42), '=' \* 42,

&#x20;             f"Date: {receipt\['date']}  Heure: {receipt\['time']}", '-' \* 42]

&#x20;   for item in receipt\['items']:

&#x20;       lines.append(f"{item\['name']\[:28]:<28}")

&#x20;       lines.append(f"  {item\['qty']} x {item\['unit\_price']:.2f}€".ljust(32) +

&#x20;                    f"{item\['total\_price']:.2f}€".rjust(10))

&#x20;   lines += \['-' \* 42,

&#x20;             f"{'TOTAL TTC':>32} {receipt\['total\_ttc']:.2f}€".rjust(42),

&#x20;             f"Règlement: {receipt\['payment']\['method']}",

&#x20;             '=' \* 42, 'Merci de votre visite !'.center(42)]

&#x20;   img = Image.new('RGB', (width, len(lines) \* 18 + 40), 'white')

&#x20;   draw = ImageDraw.Draw(img)

&#x20;   try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 12)

&#x20;   except: font = ImageFont.load\_default()

&#x20;   for i, line in enumerate(lines):

&#x20;       draw.text((8, 20 + i \* 18), line, fill='black', font=font)

&#x20;   return img



4.3 Augmentation pipeline

Receipt-specific augmentations to simulate real-world capture conditions:



\# receipt\_vlm/data/augmentation.py

import albumentations as A

import numpy as np

from PIL import Image



RECEIPT\_AUGMENTATIONS = A.Compose(\[

&#x20;   # Perspective distortion (phone held at angle)

&#x20;   A.Perspective(scale=(0.02, 0.08), p=0.6),



&#x20;   # Brightness/contrast (bad lighting, shadows)

&#x20;   A.RandomBrightnessContrast(brightness\_limit=0.3,

&#x20;                              contrast\_limit=0.3, p=0.7),



&#x20;   # Blur (out-of-focus capture)

&#x20;   A.OneOf(\[

&#x20;       A.MotionBlur(blur\_limit=5),

&#x20;       A.GaussianBlur(blur\_limit=5),

&#x20;   ], p=0.3),



&#x20;   # Paper crinkle simulation via elastic transform

&#x20;   A.ElasticTransform(alpha=20, sigma=5, p=0.3),



&#x20;   # Thermal paper fade (partial whitening)

&#x20;   A.RandomShadow(num\_shadows\_lower=1, num\_shadows\_upper=2, p=0.3),



&#x20;   # Slight rotation (not perfectly straight)

&#x20;   A.Rotate(limit=5, border\_mode=0, p=0.5),



&#x20;   # JPEG compression artifacts

&#x20;   A.ImageCompression(quality\_lower=60, quality\_upper=95, p=0.4),



&#x20;   # Final resize to model input

&#x20;   A.Resize(448, 448),

&#x20;   A.Normalize(mean=\[0.48145466, 0.4578275, 0.40821073],

&#x20;               std=\[0.26862954, 0.26130258, 0.27577711]),

])





5\. Training Strategy

5.1 Three-phase curriculum



Phase	What trains	Data	LR	Epochs	Goal

1 — Projector warmup	Projector only	CORD + SROIE	3e-4	5	Vision→language alignment

2 — LoRA fine-tuning	Projector + LoRA	All sources	1e-4	10	French receipt understanding

3 — JSON alignment	All (low LR)	Photo + synthetic	5e-5	5	Clean structured output



5.2 Training loop (from scratch)

\# receipt\_vlm/training/trainer.py

import torch

import torch.nn as nn

from torch.optim import AdamW

from torch.optim.lr\_scheduler import CosineAnnealingLR

from torch.cuda.amp import GradScaler, autocast

from pathlib import Path

import json, time

from receipt\_vlm.utils.metrics import compute\_field\_f1





class ReceiptTrainer:

&#x20;   """Hand-rolled training loop — no HuggingFace Trainer."""



&#x20;   def \_\_init\_\_(self, model, train\_loader, val\_loader, config):

&#x20;       self.model = model

&#x20;       self.train\_loader = train\_loader

&#x20;       self.val\_loader = val\_loader

&#x20;       self.config = config

&#x20;       self.device = torch.device('cuda' if torch.cuda.is\_available() else 'cpu')

&#x20;       self.scaler = GradScaler()  # Mixed precision

&#x20;       self.model.to(self.device)



&#x20;   def train\_phase(self, phase: int, epochs: int, lr: float,

&#x20;                   frozen\_components: list = \[]):

&#x20;       # Freeze specified components

&#x20;       for name, param in self.model.named\_parameters():

&#x20;           param.requires\_grad = not any(f in name for f in frozen\_components)



&#x20;       trainable = \[p for p in self.model.parameters() if p.requires\_grad]

&#x20;       optimizer = AdamW(trainable, lr=lr, weight\_decay=0.01)

&#x20;       scheduler = CosineAnnealingLR(optimizer, T\_max=epochs)



&#x20;       best\_val = float('inf')

&#x20;       for epoch in range(epochs):

&#x20;           train\_loss = self.\_train\_epoch(optimizer)

&#x20;           val\_loss, val\_f1 = self.\_val\_epoch()

&#x20;           scheduler.step()



&#x20;           print(f'Phase {phase} | Epoch {epoch+1}/{epochs} | '

&#x20;                 f'Train: {train\_loss:.4f} | Val: {val\_loss:.4f} | F1: {val\_f1:.3f}')



&#x20;           if val\_loss < best\_val:

&#x20;               best\_val = val\_loss

&#x20;               self.\_save\_checkpoint(f'phase{phase}\_best.pt')



&#x20;   def \_train\_epoch(self, optimizer):

&#x20;       self.model.train()

&#x20;       total\_loss = 0.0

&#x20;       for batch in self.train\_loader:

&#x20;           images = batch\['image'].to(self.device)

&#x20;           input\_ids = batch\['input\_ids'].to(self.device)

&#x20;           labels = batch\['labels'].to(self.device)



&#x20;           optimizer.zero\_grad()

&#x20;           with autocast():

&#x20;               logits = self.model(images, input\_ids)

&#x20;               loss = nn.functional.cross\_entropy(

&#x20;                   logits.view(-1, logits.size(-1)),

&#x20;                   labels.view(-1),

&#x20;                   ignore\_index=-100

&#x20;               )



&#x20;           self.scaler.scale(loss).backward()

&#x20;           self.scaler.unscale\_(optimizer)

&#x20;           nn.utils.clip\_grad\_norm\_(self.model.parameters(), 1.0)

&#x20;           self.scaler.step(optimizer)

&#x20;           self.scaler.update()

&#x20;           total\_loss += loss.item()



&#x20;       return total\_loss / len(self.train\_loader)



&#x20;   @torch.no\_grad()

&#x20;   def \_val\_epoch(self):

&#x20;       self.model.eval()

&#x20;       total\_loss, f1\_scores = 0.0, \[]

&#x20;       for batch in self.val\_loader:

&#x20;           images = batch\['image'].to(self.device)

&#x20;           input\_ids = batch\['input\_ids'].to(self.device)

&#x20;           labels = batch\['labels'].to(self.device)

&#x20;           with autocast():

&#x20;               logits = self.model(images, input\_ids)

&#x20;               loss = nn.functional.cross\_entropy(

&#x20;                   logits.view(-1, logits.size(-1)),

&#x20;                   labels.view(-1), ignore\_index=-100

&#x20;               )

&#x20;           total\_loss += loss.item()

&#x20;           preds = self.model.generate(images, max\_new\_tokens=512)

&#x20;           f1\_scores.append(compute\_field\_f1(preds, batch\['labels\_text']))

&#x20;       return total\_loss / len(self.val\_loader), sum(f1\_scores) / len(f1\_scores)



&#x20;   def \_save\_checkpoint(self, name: str):

&#x20;       path = Path(self.config.checkpoint\_dir) / name

&#x20;       torch.save({

&#x20;           'model\_state': self.model.state\_dict(),

&#x20;           'config': self.config,

&#x20;       }, path)

&#x20;       print(f'Checkpoint saved: {path}')





6\. Full Model Assembly

\# receipt\_vlm/models/vlm.py

import torch

import torch.nn as nn

from transformers import CLIPVisionModel, AutoModelForCausalLM, AutoTokenizer

from receipt\_vlm.models.projector import MultimodalProjector

from receipt\_vlm.models.lora import inject\_lora



CLIP\_MODEL = 'openai/clip-vit-base-patch16'

LM\_MODEL = 'HuggingFaceTB/SmolLM-1.7B'





class ReceiptVLM(nn.Module):

&#x20;   """

&#x20;   \~500M parameter Vision-Language Model for receipt parsing.



&#x20;   Architecture:

&#x20;     CLIP ViT-B/16 (frozen)  →  MultimodalProjector (scratch)

&#x20;                              →  SmolLM + LoRA (scratch adapters)

&#x20;                              →  JSON output tokens

&#x20;   """



&#x20;   def \_\_init\_\_(self, lora\_rank: int = 16, lora\_alpha: float = 32.0):

&#x20;       super().\_\_init\_\_()



&#x20;       # --- Vision Encoder: CLIP (FROZEN) ---

&#x20;       self.vision\_encoder = CLIPVisionModel.from\_pretrained(CLIP\_MODEL)

&#x20;       for param in self.vision\_encoder.parameters():

&#x20;           param.requires\_grad = False



&#x20;       # --- Multimodal Projector (FROM SCRATCH) ---

&#x20;       self.projector = MultimodalProjector(

&#x20;           vision\_dim=768,

&#x20;           lang\_dim=2048,  # SmolLM-1.7B hidden dim

&#x20;           num\_patches=197,

&#x20;       )



&#x20;       # --- Language Decoder: SmolLM + LoRA (FROM SCRATCH adapters) ---

&#x20;       self.tokenizer = AutoTokenizer.from\_pretrained(LM\_MODEL)

&#x20;       self.lm = AutoModelForCausalLM.from\_pretrained(LM\_MODEL)

&#x20;       inject\_lora(self.lm, rank=lora\_rank, alpha=lora\_alpha,

&#x20;                   target\_modules=\['q\_proj', 'v\_proj'])



&#x20;       # --- JSON prompt template ---

&#x20;       self.system\_prompt = (

&#x20;           'Tu es un assistant qui analyse des tickets de caisse français. '

&#x20;           'Extrait toutes les informations et réponds UNIQUEMENT en JSON valide.'

&#x20;       )



&#x20;   def forward(self, pixel\_values: torch.Tensor,

&#x20;               input\_ids: torch.Tensor) -> torch.Tensor:

&#x20;       # 1. Extract visual features

&#x20;       vision\_out = self.vision\_encoder(pixel\_values=pixel\_values)

&#x20;       patch\_embeddings = vision\_out.last\_hidden\_state  # (B, 197, 768)



&#x20;       # 2. Project to language space

&#x20;       visual\_tokens = self.projector(patch\_embeddings)  # (B, 32, 2048)



&#x20;       # 3. Prepend visual tokens to text embeddings

&#x20;       text\_embeds = self.lm.get\_input\_embeddings()(input\_ids)  # (B, T, 2048)

&#x20;       combined = torch.cat(\[visual\_tokens, text\_embeds], dim=1)  # (B, 32+T, 2048)



&#x20;       # 4. Forward through LM

&#x20;       outputs = self.lm(inputs\_embeds=combined)

&#x20;       return outputs.logits



&#x20;   @torch.no\_grad()

&#x20;   def generate(self, pixel\_values: torch.Tensor,

&#x20;                max\_new\_tokens: int = 512) -> list\[str]:

&#x20;       vision\_out = self.vision\_encoder(pixel\_values=pixel\_values)

&#x20;       visual\_tokens = self.projector(vision\_out.last\_hidden\_state)



&#x20;       prompt\_ids = self.tokenizer(

&#x20;           self.system\_prompt, return\_tensors='pt'

&#x20;       ).input\_ids.to(pixel\_values.device)

&#x20;       prompt\_embeds = self.lm.get\_input\_embeddings()(prompt\_ids)

&#x20;       prompt\_embeds = prompt\_embeds.expand(pixel\_values.shape\[0], -1, -1)



&#x20;       combined = torch.cat(\[visual\_tokens, prompt\_embeds], dim=1)



&#x20;       output\_ids = self.lm.generate(

&#x20;           inputs\_embeds=combined,

&#x20;           max\_new\_tokens=max\_new\_tokens,

&#x20;           do\_sample=False,

&#x20;           temperature=1.0,

&#x20;           eos\_token\_id=self.tokenizer.eos\_token\_id,

&#x20;       )

&#x20;       return \[self.tokenizer.decode(ids, skip\_special\_tokens=True)

&#x20;               for ids in output\_ids]





7\. Environment Setup

7.1 requirements.txt

\# Core

torch>=2.2.0

torchvision>=0.17.0

transformers>=4.40.0

tokenizers>=0.19.0



\# Vision

Pillow>=10.0.0

opencv-python>=4.9.0

albumentations>=1.3.0



\# Data

datasets>=2.18.0          # for CORD / SROIE

pandas>=2.0.0

numpy>=1.26.0



\# Training

accelerate>=0.28.0

tensorboard>=2.16.0



\# Utils

pyyaml>=6.0.1

tqdm>=4.66.0

jsonschema>=4.21.0        # output validation



\# Dev

pytest>=8.0.0

jupyter>=1.0.0



7.2 Hardware requirements



Setup	VRAM	Training time	Notes

Google Colab T4 (free)	16 GB	\~8h (all 3 phases)	Use 4-bit + gradient checkpointing

Colab A100 (Pro)	40 GB	\~2h	Recommended — comfortable fit

Local RTX 3090/4090	24 GB	\~4h	bfloat16 + batch\_size=4

CPU only	—	Not feasible	Inference only, not training



7.3 Quick start

\# 1. Install

git clone https://github.com/your-repo/receipt-vlm

cd receipt-vlm \&\& pip install -e .



\# 2. Download datasets

python scripts/download\_data.py --cord --sroie



\# 3. Generate synthetic French receipts

python scripts/generate\_synthetic.py --n 2000 --output data/synthetic/



\# 4. Train phase 1 (projector only, \~30min on A100)

python scripts/train.py --config configs/phase1.yaml



\# 5. Train phase 2 (LoRA, \~1h on A100)

python scripts/train.py --config configs/phase2.yaml \\

&#x20;   --resume checkpoints/phase1\_best.pt



\# 6. Train phase 3 (JSON alignment, \~30min on A100)

python scripts/train.py --config configs/phase3.yaml \\

&#x20;   --resume checkpoints/phase2\_best.pt



\# 7. Inference on a single receipt image

python scripts/infer.py --image path/to/receipt.jpg \\

&#x20;   --checkpoint checkpoints/phase3\_best.pt





8\. Instructions for Cursor / AI Coding Assistant



How to use this document with Cursor

Open this spec in Cursor, then use Cmd+K or the chat panel to ask it to implement specific files. Start with the models/ folder, then data/, then training/. Reference section numbers when prompting.



8.1 Recommended build order

1\.	receipt\_vlm/models/lora.py — implement LoRALinear and inject\_lora as in Section 2.3

2\.	receipt\_vlm/models/projector.py — implement MultimodalProjector as in Section 2.2

3\.	receipt\_vlm/models/vlm.py — assemble ReceiptVLM as in Section 6

4\.	receipt\_vlm/data/synthetic.py — implement generator as in Section 4.2

5\.	receipt\_vlm/data/augmentation.py — implement augmentations as in Section 4.3

6\.	receipt\_vlm/data/cord\_adapter.py — load CORD from HuggingFace datasets, normalize to schema in Section 1.2

7\.	receipt\_vlm/data/sroie\_adapter.py — load SROIE, normalize to schema

8\.	receipt\_vlm/data/dataset.py — ReceiptDataset wrapping all sources

9\.	receipt\_vlm/training/trainer.py — implement ReceiptTrainer as in Section 5.2

10\.	scripts/train.py — CLI entry point accepting --config and --resume



8.2 Key Cursor prompts to use



// Prompt 1: Start the model

"Implement receipt\_vlm/models/lora.py exactly as specified in Section 2.3

&#x20;of the spec. Include LoRALinear, inject\_lora, and count\_trainable\_params.

&#x20;Add full docstrings and type hints."



// Prompt 2: Data pipeline

"Implement receipt\_vlm/data/cord\_adapter.py that loads the CORD dataset

&#x20;from HuggingFace (naver-clova-ix/cord-v2) and converts each sample to

&#x20;the JSON schema defined in Section 1.2."



// Prompt 3: Synthetic data

"Expand the synthetic generator in Section 4.2 to add 20 more products

&#x20;per category and implement a save\_dataset(n, output\_dir) function that

&#x20;saves image + JSON pairs to disk."



// Prompt 4: Training config

"Create configs/phase1.yaml, phase2.yaml, phase3.yaml with the

&#x20;hyperparameters from Section 5.1. Use OmegaConf or plain PyYAML."



8.3 Testing strategy

•	Run pytest tests/ before each phase to validate shapes and forward passes

•	Use notebooks/01\_data\_exploration.ipynb to verify CORD/SROIE loading visually

•	After phase 1: check that projector output embeddings cluster by receipt region (notebook 02)

•	After phase 3: compute field-level F1 on held-out French photos as final metric



8.4 Common pitfalls to tell Cursor to avoid

•	Never pass raw pixel tensors to CLIP — always normalize with CLIP's own mean/std

•	Labels for cross-entropy must be shifted by +32 tokens (to account for visual prefix)

•	SmolLM tokenizer has no padding token by default — set tokenizer.pad\_token = tokenizer.eos\_token

•	CORD bbox coordinates are in \[0,1] normalized — rescale to pixel coords before rendering

•	JSON generation must strip <|endoftext|> and any preamble before json.loads()





9\. Evaluation Metrics



Metric	Measures	Target	How to compute

Field F1	Per-field extraction accuracy	> 0.85	Exact match on each JSON field

ANLS	Normalized edit distance on strings	> 0.80	1 - NED, averaged over fields

Total exact match	Whole JSON correct	> 0.40	json\_pred == json\_gt

Price error (€)	Mean absolute error on prices	< 0.05€	MAE on all numerical fields

Date accuracy	Correct date parsed	> 0.90	Exact match on date string



10\. References \& Acknowledgements

•	LLaVA: Liu et al. (2023) — Visual Instruction Tuning. This architecture directly follows LLaVA's frozen encoder + projector + LM decoder pattern.

•	LoRA: Hu et al. (2021) — LoRA: Low-Rank Adaptation of Large Language Models.

•	SmolLM / SmolVLM: HuggingFaceTB (2024) — Small but capable language models.

•	CORD dataset: Park et al. (2019) — CORD: A Consolidated Receipt Dataset for Post-OCR Parsing.

•	SROIE dataset: Huang et al. (2019) — ICDAR 2019 Competition on Scanned Receipt OCR and IE.

•	CLIP: Radford et al. (2021) — Learning Transferable Visual Models From Natural Language Supervision.



Generated as a technical specification for a school VLM project. All code is original and written for educational purposes.



