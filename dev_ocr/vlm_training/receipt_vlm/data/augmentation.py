"""Augmentations qui simulent les conditions reelles de prise de vue.

Le resize final est en 224x224 : c'est ce qu'attend CLIP ViT-B/16. Monter a 448
donnerait 785 patchs et casserait les embeddings positionnels du CLIP gele.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Les stats de normalisation de CLIP. Obligatoires, l'encodeur est gele.
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)

IMAGE_SIZE = 224


def build_train_augmentations():
    """Pipeline d'entrainement : bruit de prise de vue, resize, normalisation CLIP."""
    import albumentations as A

    return A.Compose(
        [
            # Le telephone tenu de travers.
            A.Perspective(scale=(0.02, 0.08), p=0.6),
            # Mauvaise lumiere, ombres.
            A.RandomBrightnessContrast(
                brightness_limit=0.3, contrast_limit=0.3, p=0.7
            ),
            # Photo floue.
            A.OneOf(
                [A.MotionBlur(blur_limit=5), A.GaussianBlur(blur_limit=5)],
                p=0.3,
            ),
            # Papier froisse.
            A.ElasticTransform(alpha=20, sigma=5, p=0.3),
            # Papier thermique delave, ombre partielle.
            A.RandomShadow(p=0.3),
            # Jamais parfaitement droit.
            A.Rotate(limit=5, border_mode=0, p=0.5),
            # Les artefacts JPEG du telephone.
            A.ImageCompression(quality_range=(60, 95), p=0.4),
            A.Resize(IMAGE_SIZE, IMAGE_SIZE),
            A.Normalize(mean=CLIP_MEAN, std=CLIP_STD),
        ]
    )


def build_eval_transform():
    """Pipeline d'eval, deterministe : resize et normalisation CLIP, rien d'autre."""
    import albumentations as A

    return A.Compose(
        [
            A.Resize(IMAGE_SIZE, IMAGE_SIZE),
            A.Normalize(mean=CLIP_MEAN, std=CLIP_STD),
        ]
    )


def prepare_pixels(image: Image.Image, transform) -> "np.ndarray":
    """Image PIL vers un tableau CHW float32, via albumentations."""
    array = np.asarray(image.convert("RGB"))
    transformed = transform(image=array)["image"]
    return np.transpose(transformed, (2, 0, 1)).astype(np.float32)


def clip_normalize_pil(image: Image.Image) -> "np.ndarray":
    """Chemin d'eval sans albumentations, celui qu'utilise le provider a l'inference.

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
