"""Receipt-specific augmentations simulating real capture conditions.

Final resize is 224×224 (CLIP ViT-B/16 @ patch 16 → 197 tokens). The draft
spec's 448×448 would yield 785 patches and break the frozen CLIP positional
embeddings — see adapted spec §1 item 5.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# CLIP's own normalization stats — mandatory for the frozen encoder.
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)

IMAGE_SIZE = 224


def build_train_augmentations():
    """Training pipeline: capture-noise simulation + resize + CLIP normalize."""
    import albumentations as A

    return A.Compose(
        [
            # Perspective distortion (phone held at an angle).
            A.Perspective(scale=(0.02, 0.08), p=0.6),
            # Bad lighting / shadows.
            A.RandomBrightnessContrast(
                brightness_limit=0.3, contrast_limit=0.3, p=0.7
            ),
            # Out-of-focus capture.
            A.OneOf(
                [A.MotionBlur(blur_limit=5), A.GaussianBlur(blur_limit=5)],
                p=0.3,
            ),
            # Paper crinkle.
            A.ElasticTransform(alpha=20, sigma=5, p=0.3),
            # Thermal paper fade / partial shadowing.
            A.RandomShadow(p=0.3),
            # Not perfectly straight.
            A.Rotate(limit=5, border_mode=0, p=0.5),
            # Phone JPEG artifacts.
            A.ImageCompression(quality_range=(60, 95), p=0.4),
            A.Resize(IMAGE_SIZE, IMAGE_SIZE),
            A.Normalize(mean=CLIP_MEAN, std=CLIP_STD),
        ]
    )


def build_eval_transform():
    """Deterministic eval pipeline: resize + CLIP normalize only."""
    import albumentations as A

    return A.Compose(
        [
            A.Resize(IMAGE_SIZE, IMAGE_SIZE),
            A.Normalize(mean=CLIP_MEAN, std=CLIP_STD),
        ]
    )


def prepare_pixels(image: Image.Image, transform) -> "np.ndarray":
    """PIL image → CHW float32 array via an albumentations transform."""
    array = np.asarray(image.convert("RGB"))
    transformed = transform(image=array)["image"]
    return np.transpose(transformed, (2, 0, 1)).astype(np.float32)


def clip_normalize_pil(image: Image.Image) -> "np.ndarray":
    """Albumentations-free eval path (used by the runtime provider).

    Resize to 224×224 + CLIP mean/std normalize, returns CHW float32.
    """
    resized = image.convert("RGB").resize(
        (IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR
    )
    array = np.asarray(resized).astype(np.float32) / 255.0
    mean = np.asarray(CLIP_MEAN, dtype=np.float32)
    std = np.asarray(CLIP_STD, dtype=np.float32)
    array = (array - mean) / std
    return np.transpose(array, (2, 0, 1))
