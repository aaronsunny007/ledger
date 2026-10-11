"""RET-1, RET-3, RET-4: hybrid search, fusion and reranking, each switchable.

``mode`` picks vector, keyword or hybrid (both fused with Reciprocal Rank
Fusion); ``rerank`` turns the cross-encoder on or off. Every returned chunk
carries its rank from each stage so a trace can show what each one did.
"""

from __future__ import annotations

from collections.abc import Sequence

from ledger.config import RetrievalConfig
from ledger.ingest.statements import statements_needed
from ledger.retrieve.embed import Embedder
from ledger.retrieve.filters import Filters
from ledger.retrieve.rerank import Reranker
from ledger.retrieve.store import Hit, Index
from ledger.types import ScoredChunk


def reciprocal_rank_fusion(rankings: dict[str, Sequence[Hit]], k: int = 60) -> list[ScoredChunk]:
    """score(d) = sum over rankings of 1 / (k + rank(d)), ranks starting at 1."""
    fused: dict[str, ScoredChunk] = {}
    for stage, hits in rankings.items():
        for rank, (chunk, _score) in enumerate(hits, start=1):
            sc = fused.get(chunk.id)
            if sc is None:
                sc = fused[chunk.id] = ScoredChunk(chunk=chunk, score=0.0)
            sc.score += 1.0 / (k + rank)
            sc.ranks[stage] = rank
    return sorted(fused.values(), key=lambda s: -s.score)


class Retriever:
    def __init__(
        self,
        index: Index,
        embedder: Embedder,
        config: RetrievalConfig,
        reranker: Reranker | None = None,
    ):
        self.index = index
        self.embedder = embedder
        self.config = config
        self.reranker = reranker if config.rerank else None

    def candidates(self, question: str, filters: Filters) -> list[ScoredChunk]:
        cfg = self.config
        rankings: dict[str, Sequence[Hit]] = {}
        if cfg.mode in ("vector", "hybrid"):
            q = self.embedder.embed_query(question)
            rankings["vector"] = self.index.vector_search(q, cfg.candidates, filters)
        if cfg.mode in ("keyword", "hybrid"):
            rankings["keyword"] = self.index.keyword_search(question, cfg.candidates, filters)
        return reciprocal_rank_fusion(rankings, cfg.rrf_k)[: cfg.candidates]

    def retrieve(self, question: str, filters: Filters) -> list[ScoredChunk]:
        if self.config.latest_year_only and len(filters.years) > 1:
            latest = Filters(filters.tickers, [max(filters.years)], filters.sections)
            found = self._retrieve(question, latest)
            if found:
                return found
        found = self._retrieve(question, filters)
        if found or not (filters.tickers and filters.years):
            return found
        # A 10-K reports two or three years, so a year whose own filing is not
        # indexed is often a comparative in the next one or two.
        for later in (1, 2):
            year = max(filters.years) + later
            found = self._retrieve(question, Filters(filters.tickers, [year], filters.sections))
            if found:
                return found
        return found

    def _retrieve(self, question: str, filters: Filters) -> list[ScoredChunk]:
        cands = self.candidates(question, filters)
        if self.reranker is not None and cands:
            scores = self.reranker.score(question, [c.chunk.text for c in cands])
            for c, s in zip(cands, scores, strict=True):
                c.score = s
            cands.sort(key=lambda c: -c.score)
            for i, c in enumerate(cands, start=1):
                c.ranks["rerank"] = i
        ranked = cands[: self.config.top_k]
        if not (self.config.pin_statements and filters.tickers):
            return ranked
        needed = statements_needed(question)
        pinned = self.index.statement_chunks(filters, needed) if needed else []
        if not pinned:
            return ranked
        top = ranked[0].score if ranked else 0.0
        pinned_ids = {c.id for c in pinned}
        out = [
            ScoredChunk(chunk=c, score=top, ranks={"pinned": i})
            for i, c in enumerate(pinned, start=1)
        ]
        return out + [c for c in ranked if c.chunk.id not in pinned_ids]
