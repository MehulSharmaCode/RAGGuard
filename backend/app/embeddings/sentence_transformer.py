"""Local embeddings with Sentence Transformers.

The model is loaded lazily on first use so the API can start (and report health)
before the model is downloaded or loaded. On first use, Hugging Face downloads
the model into its cache (~90 MB for all-MiniLM-L6-v2) if it is not present.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from app.core.errors import EmbeddingError

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Tokens reserved for the [CLS] and [SEP] special tokens added by BERT-style models.
_SPECIAL_TOKENS = 2


class SentenceTransformerEmbedder:
    def __init__(
        self, model_name: str, batch_size: int = 32, *, local_files_only: bool = False
    ) -> None:
        self.model_name = model_name
        self._batch_size = batch_size
        self._local_files_only = local_files_only
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info("Loading embedding model %s", self.model_name)
                    try:
                        from sentence_transformers import SentenceTransformer

                        self._model = SentenceTransformer(
                            self.model_name, local_files_only=self._local_files_only
                        )
                    except Exception as exc:
                        logger.exception("Failed to load embedding model %s", self.model_name)
                        raise EmbeddingError(
                            "The embedding model could not be loaded. Check EMBEDDING_MODEL "
                            "and network access for the first download."
                        ) from exc
        return self._model

    @property
    def dimension(self) -> int:
        dimension = self._get_model().get_embedding_dimension()
        if not dimension:
            raise EmbeddingError("The embedding model does not report a vector dimension.")
        return int(dimension)

    @property
    def max_input_tokens(self) -> int:
        max_length = self._get_model().max_seq_length
        if max_length is None:
            raise EmbeddingError("The embedding model does not report its input limit.")
        return int(max_length) - _SPECIAL_TOKENS

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        tokenizer = self._get_model().tokenizer
        encoded = tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            verbose=False,
        )
        return [(int(s), int(e)) for s, e in encoded["offset_mapping"]]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        try:
            with self._lock:
                vectors = model.encode(
                    texts,
                    batch_size=self._batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        except Exception as exc:
            logger.exception("Embedding generation failed")
            raise EmbeddingError("Embedding generation failed.") from exc
        return [[float(x) for x in row] for row in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]
