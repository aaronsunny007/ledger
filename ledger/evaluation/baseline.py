"""The plain baseline: the whole filing in a long-context model, no retrieval.

FinanceBench found this beat naive RAG (79% vs 50%). Ledger has to show
where it wins (cost, latency) and where it does not. The baseline uses the
same answer prompt and the same verifier-free scoring, so the only
difference is retrieval.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ledger.answer.generate import Generator
from ledger.answer.llm import LLM
from ledger.ingest.chunk import DocMeta, SectionChunker
from ledger.ingest.parse import parse_html
from ledger.pipeline import NOT_IN_FILINGS
from ledger.retrieve.filters import CompanyRegistry, Filters, filters_from_question
from ledger.types import Answer, ScoredChunk


class LongContextBaseline:
    def __init__(
        self, llm: LLM, raw_dir: Path, registry: CompanyRegistry | None, max_chars: int = 600_000
    ):
        # ~600k characters is ~150k tokens: a full 10-K fits Gemini's window.
        self.generator = Generator(llm, max_context_chars=max_chars)
        self.raw_dir = raw_dir
        self.registry = registry

    def _filing(self, ticker: str, year: int) -> list[ScoredChunk]:
        meta_path = self.raw_dir / ticker / str(year) / "meta.json"
        if not meta_path.exists():
            return []
        m = json.loads(meta_path.read_text())
        meta = DocMeta(m["doc_id"], m["company"], ticker, year, source_url=m["url"])
        doc = parse_html((meta_path.parent / "filing.htm").read_bytes())
        # Whole sections as passages, so citations still mean something.
        chunks = SectionChunker(size=20_000, overlap=0).chunk(doc, meta)
        return [ScoredChunk(chunk=c, score=0.0) for c in chunks]

    def ask(self, question: str, filters: Filters | None = None) -> Answer:
        t0 = time.monotonic()
        f = filters_from_question(question, self.registry, filters)
        passages = [p for t in f.tickers for y in f.years for p in self._filing(t, y)]
        if not passages:
            return Answer(
                question=question,
                answer=NOT_IN_FILINGS,
                refused=True,
                refusal_reason="Filing not found for baseline.",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        draft, res = self.generator.draft(question, passages)
        refused = not draft.answerable
        return Answer(
            question=question,
            answer=NOT_IN_FILINGS if refused else " ".join(c.text for c in draft.claims),
            refused=refused,
            model=res.model,
            cost_usd=res.cost_usd,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
