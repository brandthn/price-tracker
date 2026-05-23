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


def _chunks(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


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
        task_type: str = "RETRIEVAL_DOCUMENT",
        output_dim: int = 768,
    ) -> None:
        self._project = project
        self._location = location
        self._model_name = model_name
        self._batch_size = max(1, min(batch_size, 250))
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
        for batch in _chunks(list(texts), self._batch_size):
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
