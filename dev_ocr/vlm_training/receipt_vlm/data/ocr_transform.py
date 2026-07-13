"""Preparation d'image pour l'OCR-VLM.

Normalisation maison, et une toile au format d'un ticket : c'est haut et etroit, donc
le defaut est en portrait. On preserve le ratio en padant sur une toile blanche avant
de redimensionner, sinon le texte est ecrase et devient illisible.

Hauteur et largeur sont des multiples de 16, le stride total du CNN, pour que la
grille de features tombe juste.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# La toile par defaut. En portrait, parce qu'un ticket est haut et etroit, et
# divisible par 16 (le stride du CNN).
IMG_H = 384
IMG_W = 256

# Normalisation symetrique, en gros [-1, 1]. L'encodeur apprend le reste.
OCR_MEAN = 0.5
OCR_STD = 0.5


def prepare_ocr_pixels(
    image: Image.Image, height: int = IMG_H, width: int = IMG_W
) -> "np.ndarray":
    """Image PIL vers CHW float32, en letterbox pour ne pas ecraser le texte."""
    img = image.convert("RGB")
    w, h = img.size
    scale = min(width / w, height / h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(resized, ((width - new_w) // 2, (height - new_h) // 2))

    array = np.asarray(canvas).astype(np.float32) / 255.0
    array = (array - OCR_MEAN) / OCR_STD
    return np.transpose(array, (2, 0, 1))  # CHW
