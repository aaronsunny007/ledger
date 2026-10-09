"""RET-3: reranking. The cross-encoder itself is in ``models.py``."""

from __future__ import annotations

from typing import Protocol

from ledger.retrieve.embed import tokenize


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class OverlapReranker:
    """Query-term overlap. A dependency-free stand-in for tests and CI only."""

    name = "overlap"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = set(tokenize(query))
        if not q:
            return [0.0] * len(passages)
        return [len(q & set(tokenize(p))) / len(q) for p in passages]


def get_reranker(name: str) -> Reranker:
    if name == "overlap":
        return OverlapReranker()
    from ledger.retrieve.models import CrossEncoderReranker

    return CrossEncoderReranker(name)
