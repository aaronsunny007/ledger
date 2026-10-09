"""Chunk stores. ``InMemoryIndex`` is numpy + BM25 saved to disk; the Postgres
store (pgvector + full-text search) is in ``pgstore.py``.

Both implement the same ``Index`` protocol, so retrieval code and the eval do
not care which one is behind them.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Protocol

import numpy as np

from ledger.retrieve.embed import Vector, tokenize
from ledger.retrieve.filters import Filters
from ledger.types import Chunk

Hit = tuple[Chunk, float]


class Index(Protocol):
    def add(self, chunks: list[Chunk], vectors: Vector) -> None: ...

    def delete_doc(self, doc_id: str) -> int: ...

    def vector_search(self, query: Vector, k: int, filters: Filters) -> list[Hit]: ...

    def keyword_search(self, query: str, k: int, filters: Filters) -> list[Hit]: ...

    def documents(self) -> list[dict[str, object]]: ...

    def count(self) -> int: ...


_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "did",
        "does",
        "do",
    ]
)


def _terms(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in _STOPWORDS]


class InMemoryIndex:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.chunks: list[Chunk] = []
        self.vectors: Vector | None = None
        self._k1, self._b = k1, b
        self._tf: list[Counter[str]] = []
        self._df: Counter[str] = Counter()
        self._lens: list[int] = []

    # -- writes ------------------------------------------------------------

    def add(self, chunks: list[Chunk], vectors: Vector) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self.chunks.extend(chunks)
        self.vectors = vectors if self.vectors is None else np.vstack([self.vectors, vectors])
        for c in chunks:
            tf = Counter(_terms(c.text))
            self._tf.append(tf)
            self._df.update(tf.keys())
            self._lens.append(sum(tf.values()))

    def delete_doc(self, doc_id: str) -> int:
        keep = [i for i, c in enumerate(self.chunks) if c.doc_id != doc_id]
        removed = len(self.chunks) - len(keep)
        if removed:
            chunks = [self.chunks[i] for i in keep]
            vectors = self.vectors[keep] if self.vectors is not None else None
            self.__init__(self._k1, self._b)  # type: ignore[misc]
            if chunks and vectors is not None:
                self.add(chunks, vectors)
        return removed

    # -- reads -------------------------------------------------------------

    def _allowed(self, filters: Filters) -> list[int]:
        if filters.is_empty():
            return list(range(len(self.chunks)))
        return [i for i, c in enumerate(self.chunks) if filters.matches(c)]

    def vector_search(self, query: Vector, k: int, filters: Filters) -> list[Hit]:
        idx = self._allowed(filters)
        if not idx or self.vectors is None:
            return []
        scores = self.vectors[idx] @ query
        order = np.argsort(-scores)[:k]
        return [(self.chunks[idx[i]], float(scores[i])) for i in order]

    def keyword_search(self, query: str, k: int, filters: Filters) -> list[Hit]:
        terms = set(_terms(query))
        if not terms or not self.chunks:
            return []
        n = len(self.chunks)
        avg = sum(self._lens) / n
        scores: dict[int, float] = defaultdict(float)
        for i in self._allowed(filters):
            tf = self._tf[i]
            for t in terms:
                f = tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                denom = f + self._k1 * (1 - self._b + self._b * self._lens[i] / avg)
                scores[i] += idf * f * (self._k1 + 1) / denom
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        return [(self.chunks[i], s) for i, s in top]

    def documents(self) -> list[dict[str, object]]:
        docs: dict[str, dict[str, object]] = {}
        for c in self.chunks:
            d = docs.setdefault(
                c.doc_id,
                {
                    "doc_id": c.doc_id,
                    "company": c.company,
                    "ticker": c.ticker,
                    "fiscal_year": c.fiscal_year,
                    "form_type": c.form_type,
                    "source_url": c.source_url,
                    "chunks": 0,
                },
            )
            d["chunks"] = int(str(d["chunks"])) + 1
        return sorted(docs.values(), key=lambda d: (str(d["ticker"]), str(d["fiscal_year"])))

    def count(self) -> int:
        return len(self.chunks)

    def get(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.id == chunk_id), None)

    # -- persistence -------------------------------------------------------

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with (path / "chunks.jsonl").open("w") as f:
            for c in self.chunks:
                f.write(c.model_dump_json() + "\n")
        np.save(
            path / "vectors.npy", self.vectors if self.vectors is not None else np.zeros((0, 0))
        )

    @classmethod
    def load(cls, path: Path) -> InMemoryIndex:
        idx = cls()
        if not (path / "chunks.jsonl").exists():
            return idx
        chunks = [
            Chunk.model_validate(json.loads(line))
            for line in (path / "chunks.jsonl").read_text().splitlines()
            if line
        ]
        if chunks:
            idx.add(chunks, np.load(path / "vectors.npy").astype(np.float32))
        return idx
