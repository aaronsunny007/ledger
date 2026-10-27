"""CACHE-1..3: a semantic cache that cannot return last year's number.

"Tesco revenue 2024" and "Tesco revenue 2023" embed almost identically, so
a plain similarity cache returns the wrong year. Here the key is the
extracted company + fiscal period *first*; similarity is only compared
between questions that share that key. Questions with no company or no year
are never cached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from ledger.retrieve.embed import Embedder, Vector
from ledger.retrieve.filters import Filters
from ledger.types import Answer

# Words that carry no meaning for "is this the same question?". Everything else must match:
# "Nike's revenue in 2023" and "Nike's net income in 2023" embed almost identically, but they
# are different questions, so the words that name the metric have to agree, not just the vector.
_FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "for",
        "to",
        "and",
        "or",
        "at",
        "by",
        "on",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "did",
        "does",
        "do",
        "has",
        "have",
        "had",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "much",
        "many",
        "s",
        "fiscal",
        "financial",
        "year",
        "years",
        "fy",
        "please",
        "tell",
        "me",
        "give",
        "show",
        "its",
        "it",
        "their",
        "company",
        "corporation",
        "inc",
        "during",
        "end",
        "ended",
    ]
)


def content_words(question: str) -> frozenset[str]:
    words = re.findall(r"[a-z]+|\d+", question.lower())
    return frozenset(w.rstrip("s") if len(w) > 3 else w for w in words if w not in _FILLER)


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
        words = content_words(question)
        for i in np.argsort(-sims):
            if sims[i] < self.threshold:
                break
            if content_words(bucket[i].question) == words:
                self.stats.hits += 1
                return bucket[i].answer, float(sims[i])
        self.stats.misses += 1
        return None, float(sims.max())

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
