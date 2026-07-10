"""Embeddings via Vertex AI `text-embedding-004` (dim 768).

Batches de `prt_vertex_batch` instances pour amortir le coût de réseau.
L'auth se fait via ADC — la SA Cloud Run `prt-prod-worker-sa` a déjà
`roles/aiplatform.user` (cf. infra/README.md §Service Accounts).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)


def _batches_by_budget(
    texts: Sequence[str], max_count: int, max_chars: int
) -> Iterable[list[str]]:
    """Regroupe les textes en batches respectant DEUX bornes de l'API Vertex :
    - `max_count` instances par requête (250) ;
    - `max_chars` caractères cumulés par requête (proxy du plafond de 20000
      tokens/requête — le français accentué ~2.9 char/token).
    Packing glouton ; un texte seul dépassant le budget forme son propre batch."""
    batch: list[str] = []
    chars = 0
    for t in texts:
        tlen = len(t)
        if batch and (len(batch) >= max_count or chars + tlen > max_chars):
            yield batch
            batch, chars = [], 0
        batch.append(t)
        chars += tlen
    if batch:
        yield batch


class VertexEmbedder:
    """Wrap `vertexai.language_models.TextEmbeddingModel` mais lazy-loaded :
    on n'importe le SDK que lors du premier `embed()` pour ne pas payer le
    coût d'import (et de check ADC) au boot du worker.
    """

    def __init__(
        self,
        *,
        project: str,
        location: str,
        model_name: str,
        batch_size: int,
        task_type: str = "SEMANTIC_SIMILARITY",
        output_dim: int = 768,
        max_request_chars: int = 45000,
    ) -> None:
        self._project = project
        self._location = location
        self._model_name = model_name
        self._batch_size = max(1, min(batch_size, 250))
        # Plafond de caractères par requête : ~20000 tokens/requête côté API.
        # 45000 chars laisse une marge pour le français accentué (~2.9 char/token).
        self._max_request_chars = max_request_chars
        self._task_type = task_type
        self._output_dim = output_dim
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        vertexai.init(project=self._project, location=self._location)
        self._model = TextEmbeddingModel.from_pretrained(self._model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Renvoie 1 vecteur par texte, dans le même ordre."""
        if not texts:
            return []
        model = self._load()
        from vertexai.language_models import TextEmbeddingInput

        out: list[list[float]] = []
        for batch in _batches_by_budget(
            list(texts), max_count=self._batch_size, max_chars=self._max_request_chars
        ):
            inputs = [TextEmbeddingInput(text=t, task_type=self._task_type) for t in batch]
            kwargs: dict[str, Any] = {}
            # `text-embedding-004` supporte `output_dimensionality` ; on le
            # passe explicitement pour figer la dim côté contrat (pgvector
            # déclare `vector(768)`).
            kwargs["output_dimensionality"] = self._output_dim
            embeddings = model.get_embeddings(inputs, **kwargs)
            out.extend(emb.values for emb in embeddings)
            logger.info("vertex_batch_done", batch=len(batch))
        return out
