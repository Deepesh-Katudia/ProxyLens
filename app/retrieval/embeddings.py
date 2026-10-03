"""Text embedders. BGE needs an instruction prefix on queries but not on passages."""

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from app.config import Settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
EMBED_BATCH_SIZE = 32


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """sentence-transformers model, loaded on first use (it pulls in torch)."""

    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> "SentenceTransformer":
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model %s", self.model_name)
            self._model = SentenceTransformer(self.model_name, device="cpu")
            actual = self._model.get_embedding_dimension()
            if actual != self.dim:
                raise ValueError(
                    f"{self.model_name} produces {actual}-d vectors but EMBEDDING_DIM={self.dim}"
                )
        return self._model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.model.encode(
            list(texts),
            batch_size=EMBED_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > EMBED_BATCH_SIZE,
        )
        return [[float(x) for x in row] for row in vectors]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        prefix = BGE_QUERY_INSTRUCTION if "bge" in self.model_name.lower() else ""
        return self._encode([prefix + text])[0]


def create_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "vertex":
        # Wired with the Vertex teacher in Phase 3; local BGE is the default.
        raise NotImplementedError("EMBEDDING_PROVIDER=vertex is not implemented yet")
    return LocalEmbedder(settings.embedding_model, settings.embedding_dim)
