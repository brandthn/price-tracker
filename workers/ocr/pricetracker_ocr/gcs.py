"""Téléchargement des images tickets depuis GCS bronze."""

from __future__ import annotations

import asyncio

from google.cloud import storage

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageTooLargeError(Exception):
    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size
        super().__init__(f"Image {path!r} exceeds 10 MB limit ({size} bytes).")


def _download_sync(bucket_name: str, object_path: str) -> bytes:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    blob.reload()
    size = blob.size or 0
    if size > MAX_IMAGE_BYTES:
        raise ImageTooLargeError(object_path, size)
    return blob.download_as_bytes()


async def download_image(bucket: str, object_path: str) -> bytes:
    """Download object bytes from GCS (ADC). Raises :class:`ImageTooLargeError`."""
    return await asyncio.to_thread(_download_sync, bucket, object_path)
