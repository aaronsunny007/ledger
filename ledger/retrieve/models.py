"""Open-source embedding and reranking models (free, run on a laptop CPU).

Needs the ``models`` extra: ``pip install -e '.[models]'``. The first call
downloads weights from Hugging Face (~130 MB for bge-small, ~1.1 GB for
bge-reranker-base); later runs use the local cache.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ledger.retrieve.embed import Vector

# BGE retrieval models expect this prefix on queries, not on passages.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", batch_size: int = 32):
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self._model: Any = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self._batch = batch_size
        self._prefix = _BGE_QUERY_PREFIX if "bge" in model_name.lower() else ""

    def embed_documents(self, texts: list[str]) -> Vector:
        out = self._model.encode(
            texts,
            batch_size=self._batch,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 500,
        )
        return np.asarray(out, dtype=np.float32)

    def embed_query(self, text: str) -> Vector:
        out = self._model.encode([self._prefix + text], normalize_embeddings=True)
        return np.asarray(out[0], dtype=np.float32)


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", max_length: int = 512):
        from sentence_transformers import CrossEncoder

        self.name = model_name
        self._model: Any = CrossEncoder(model_name, max_length=max_length)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        scores = self._model.predict([(query, p) for p in passages])
        return [float(s) for s in scores]
