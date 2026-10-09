"""CACHE-1..3: a semantic cache that cannot return last year's number.

"Tesco revenue 2024" and "Tesco revenue 2023" embed almost identically, so
a plain similarity cache returns the wrong year. Here the key is the
extracted company + fiscal period *first*; similarity is only compared
between questions that share that key. Questions with no company or no year
are never cached.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ledger.retrieve.embed import Embedder, Vector
from ledger.retrieve.filters import Filters
from ledger.types import Answer


@dataclass
class _Entry:
    question: str
    vector: Vector
    answer: Answer
    doc_ids: set[str]


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    skipped: int = 0  # not cacheable (no company or year)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


@dataclass
class SemanticCache:
    embedder: Embedder
    threshold: float = 0.92
    max_entries_per_key: int = 200
    _buckets: dict[str, list[_Entry]] = field(default_factory=dict)
    stats: CacheStats = field(default_factory=CacheStats)

    @staticmethod
    def cacheable(filters: Filters) -> bool:
        return bool(filters.tickers) and bool(filters.years)

    def lookup(self, question: str, filters: Filters) -> tuple[Answer | None, float]:
        if not self.cacheable(filters):
            self.stats.skipped += 1
            return None, 0.0
        bucket = self._buckets.get(filters.key(), [])
        if not bucket:
            self.stats.misses += 1
            return None, 0.0
        q = self.embedder.embed_query(question)
        sims = np.array([float(e.vector @ q) for e in bucket])
        best = int(np.argmax(sims))
        if sims[best] >= self.threshold:
            self.stats.hits += 1
            return bucket[best].answer, float(sims[best])
        self.stats.misses += 1
        return None, float(sims[best])

    def store(self, question: str, filters: Filters, answer: Answer, doc_ids: set[str]) -> None:
        if not self.cacheable(filters) or answer.refused:
            return
        bucket = self._buckets.setdefault(filters.key(), [])
        bucket.append(_Entry(question, self.embedder.embed_query(question), answer, doc_ids))
        del bucket[: -self.max_entries_per_key]

    def invalidate_doc(self, doc_id: str) -> int:
        """CACHE-3: drop every answer that cited a re-ingested filing."""
        removed = 0
        for key, bucket in list(self._buckets.items()):
            keep = [e for e in bucket if doc_id not in e.doc_ids]
            removed += len(bucket) - len(keep)
            self._buckets[key] = keep
        return removed

    def clear(self) -> None:
        self._buckets.clear()
