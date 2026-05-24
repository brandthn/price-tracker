"""Tests for :mod:`receipt_ocr.vlm_image_prep`."""

from __future__ import annotations

from receipt_ocr.vlm_image_prep import VlmImageConfig, prepare_vlm_image


def _make_receipt_image(path, size=(400, 600)):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color=(40, 40, 40))
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, 40, 320, 560), fill=(245, 245, 245))
    draw.text((100, 60), "SUPER U", fill=(0, 0, 0))
    img.save(path)


def test_prepare_vlm_image_center_crop(tmp_path):
    image = tmp_path / "photo.jpg"
    _make_receipt_image(image)
    cfg = VlmImageConfig(max_image_side=256, crop_mode="center", jpeg_quality=90)
    out_path, temps = prepare_vlm_image(image, cfg, crop_mode_override="center")
    assert out_path
    assert temps


def test_prepare_vlm_image_off_crop(tmp_path):
    image = tmp_path / "photo.jpg"
    _make_receipt_image(image)
    cfg = VlmImageConfig(max_image_side=0, crop_mode="off", jpeg_quality=90)
    out_path, temps = prepare_vlm_image(image, cfg)
    assert out_path == str(image)
