"""Téléchargement des images tickets depuis GCS (URI gs:// complète en base)."""

from __future__ import annotations

import asyncio

from google.cloud import storage

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageTooLargeError(Exception):
    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size
        super().__init__(f"Image {path!r} exceeds 10 MB limit ({size} bytes).")


def split_gs_uri(gs_uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/path/to/object`` → ``(bucket, object_path)``.

    La colonne ``tickets.gcs_path`` stocke l'URI gs:// complète.
    """
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {gs_uri!r}")
    without_scheme = gs_uri[len("gs://"):]
    bucket, _, object_path = without_scheme.partition("/")
    if not bucket or not object_path:
        raise ValueError(f"Malformed gs:// URI (missing bucket or object): {gs_uri!r}")
    return bucket, object_path


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
