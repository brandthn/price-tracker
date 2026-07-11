"""Bootstrap des poids modèle depuis GCS au démarrage (cold start Cloud Run).

Utilisé par les workers à poids locaux (moondream, receipt-vlm, ocr-vlm-scratch)
dans leur ``lifespan``, AVANT la construction du backend. Un échec doit faire
échouer le démarrage : Cloud Run relance le conteneur, Pub/Sub NACK/retry — un
worker sans poids ne doit jamais ACKer de messages.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.cloud import storage

from .gcs import split_gs_uri
from .logging import get_logger

logger = get_logger(__name__)


def ensure_weights(gs_uri: str, dest_dir: str = "/tmp/models") -> Path:
    """Télécharge ``gs://bucket/path/file`` vers ``dest_dir/file``. Idempotent.

    - Retourne immédiatement si le fichier local existe déjà avec la taille
      attendue du blob (redémarrage à chaud du conteneur).
    - Télécharge vers ``<file>.part`` puis ``os.replace`` → jamais de fichier
      tronqué visible, même si le process meurt en plein download.
    - Appelable plusieurs fois pour les modèles multi-fichiers (checkpoint +
      tokenizer).
    """
    bucket_name, object_path = split_gs_uri(gs_uri)
    dest = Path(dest_dir) / Path(object_path).name
    dest.parent.mkdir(parents=True, exist_ok=True)

    client = storage.Client()
    blob = client.bucket(bucket_name).blob(object_path)
    blob.reload()
    expected_size = blob.size or 0

    if dest.is_file() and dest.stat().st_size == expected_size:
        logger.info("weights_cached", path=str(dest), size=expected_size)
        return dest

    part = dest.with_suffix(dest.suffix + ".part")
    logger.info("weights_download_start", uri=gs_uri, size=expected_size)
    blob.download_to_filename(str(part))
    os.replace(part, dest)
    logger.info("weights_download_done", path=str(dest), size=dest.stat().st_size)
    return dest
