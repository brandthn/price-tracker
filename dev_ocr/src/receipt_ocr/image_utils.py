"""Shared image helpers for OCR and VLM backends."""

from __future__ import annotations

import tempfile
from pathlib import Path


def resize_image_to_max_side(
    path: Path,
    max_side: int,
) -> tuple[str, Path | None]:
    """Downscale ``path`` when its longest side exceeds ``max_side``.

    Returns ``(path_for_inference, temp_path_or_none)``. When no resize
    is needed, returns the original path and ``None``.
    """
    if max_side <= 0:
        return str(path), None

    try:
        from PIL import Image
    except ImportError:
        return str(path), None

    try:
        with Image.open(path) as img:
            width, height = img.size
            longest = max(width, height)
            if longest <= max_side:
                return str(path), None

            scale = max_side / longest
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            converted = img.convert("RGB") if img.mode not in ("RGB", "L") else img
            resized = converted.resize(new_size, Image.Resampling.LANCZOS)

            tmp = tempfile.NamedTemporaryFile(
                suffix=".jpg",
                prefix="receipt_ocr_",
                delete=False,
            )
            tmp_path = Path(tmp.name)
            tmp.close()
            resized.save(tmp_path, format="JPEG", quality=85, optimize=True)
            return str(tmp_path), tmp_path
    except Exception:
        return str(path), None
