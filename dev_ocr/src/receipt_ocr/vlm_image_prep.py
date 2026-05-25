"""Image preparation pipeline for VLM backends (crop + resize)."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from receipt_ocr.constants import (
    DEFAULT_VLM_CROP_MARGIN,
    DEFAULT_VLM_JPEG_QUALITY,
    DEFAULT_VLM_MAX_IMAGE_SIDE,
    ENV_VLM_CROP,
    ENV_VLM_CROP_MARGIN,
    ENV_VLM_JPEG_QUALITY,
    ENV_VLM_MAX_IMAGE_SIDE,
    VlmCropMode,
)


@dataclass(frozen=True)
class VlmImageConfig:
    """Parameters for :func:`prepare_vlm_image`."""

    max_image_side: int = DEFAULT_VLM_MAX_IMAGE_SIDE
    crop_mode: str = VlmCropMode.AUTO.value
    crop_margin: float = DEFAULT_VLM_CROP_MARGIN
    jpeg_quality: int = DEFAULT_VLM_JPEG_QUALITY


def load_vlm_image_config_from_env() -> VlmImageConfig:
    """Build config from ``RECEIPT_VLM_*`` environment variables."""
    return VlmImageConfig(
        max_image_side=_env_int(ENV_VLM_MAX_IMAGE_SIDE, DEFAULT_VLM_MAX_IMAGE_SIDE),
        crop_mode=_env_str(ENV_VLM_CROP, VlmCropMode.AUTO.value).lower(),
        crop_margin=_env_float(ENV_VLM_CROP_MARGIN, DEFAULT_VLM_CROP_MARGIN),
        jpeg_quality=_env_int(ENV_VLM_JPEG_QUALITY, DEFAULT_VLM_JPEG_QUALITY),
    )


def prepare_vlm_image(
    path: Path,
    config: VlmImageConfig | None = None,
    *,
    crop_mode_override: str | None = None,
) -> tuple[str, list[Path]]:
    """Crop and resize ``path`` for VLM inference.

    Returns ``(path_for_inference, temp_files_to_delete)``.
    """
    cfg = config or load_vlm_image_config_from_env()
    crop_mode = (crop_mode_override or cfg.crop_mode).lower()
    temp_files: list[Path] = []

    try:
        from PIL import Image
    except ImportError:
        return str(path), temp_files

    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            cropped = _apply_crop(rgb, crop_mode, cfg.crop_margin)
            if cropped is not rgb:
                cropped_path = _save_temp_image(cropped, cfg.jpeg_quality)
                temp_files.append(cropped_path)
                work_path = cropped_path
            else:
                work_path = path

            with Image.open(work_path) as work_img:
                rgb_work = work_img.convert("RGB")
                resized = _resize_if_needed(rgb_work, cfg.max_image_side)
                if resized is rgb_work and work_path == path:
                    return str(path), temp_files
                resized_path = _save_temp_image(resized, cfg.jpeg_quality)
                temp_files.append(resized_path)
                return str(resized_path), temp_files
    except Exception:
        return str(path), temp_files


def _apply_crop(img: object, crop_mode: str, margin: float) -> object:
    if crop_mode in (VlmCropMode.OFF.value, "none", "false", "0"):
        return img
    if crop_mode == VlmCropMode.CENTER.value:
        return _center_crop(img, fraction=0.7)
    return _auto_crop_receipt(img, margin=margin)


def _auto_crop_receipt(img: object, margin: float) -> object:
    """Estimate receipt bounding box from background contrast (Pillow-only)."""
    gray = img.convert("L")
    width, height = gray.size
    if width < 32 or height < 32:
        return img

    pixels = gray.load()
    corners = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    background = sum(corners) / len(corners)
    threshold = 18

    min_x, min_y = width, height
    max_x, max_y = 0, 0
    found = False
    step = max(1, min(width, height) // 400)

    for y in range(0, height, step):
        for x in range(0, width, step):
            if abs(pixels[x, y] - background) > threshold:
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if not found or max_x <= min_x or max_y <= min_y:
        return _center_crop(img, fraction=0.75)

    pad_x = int((max_x - min_x) * margin)
    pad_y = int((max_y - min_y) * margin)
    left = max(0, min_x - pad_x)
    top = max(0, min_y - pad_y)
    right = min(width, max_x + pad_x)
    bottom = min(height, max_y + pad_y)

    if (right - left) < width * 0.25 or (bottom - top) < height * 0.25:
        return _center_crop(img, fraction=0.75)

    return img.crop((left, top, right, bottom))


def _center_crop(img: object, fraction: float) -> object:
    width, height = img.size
    crop_w = int(width * fraction)
    crop_h = int(height * fraction)
    left = (width - crop_w) // 2
    top = (height - crop_h) // 2
    return img.crop((left, top, left + crop_w, top + crop_h))


def _resize_if_needed(img: object, max_side: int) -> object:
    if max_side <= 0:
        return img
    from PIL import Image

    width, height = img.size
    longest = max(width, height)
    if longest <= max_side:
        return img
    scale = max_side / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def _save_temp_image(img: object, quality: int) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        suffix=".jpg",
        prefix="receipt_vlm_",
        delete=False,
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    img.save(tmp_path, format="JPEG", quality=max(1, min(100, quality)), optimize=True)
    return tmp_path


def cleanup_temp_files(paths: list[Path]) -> None:
    for temp_path in paths:
        temp_path.unlink(missing_ok=True)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()
