"""Image preprocessing for the from-scratch OCR-VLM.

Own normalization (NOT CLIP's) and a receipt-shaped canvas: receipts are tall/narrow, so the
default is portrait (H > W). Aspect ratio is preserved by letterbox-padding onto a white canvas
before resizing, so text isn't squashed. Height/width are multiples of 16 (the CNN stem's total
stride) so the feature grid is exact.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Default input canvas (H, W). Portrait for tall receipts; both divisible by 16.
IMG_H = 384
IMG_W = 256

# Simple symmetric normalization -> roughly [-1, 1]; the encoder learns the rest.
OCR_MEAN = 0.5
OCR_STD = 0.5


def prepare_ocr_pixels(
    image: Image.Image, height: int = IMG_H, width: int = IMG_W
) -> "np.ndarray":
    """PIL image -> CHW float32, aspect-preserving letterbox onto (height, width)."""
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
