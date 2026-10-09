from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ledger.answer.generate import Generator
from ledger.answer.llm import FakeLLM
from ledger.cache.semantic_cache import SemanticCache
from ledger.config import LedgerConfig, RetrievalConfig
from ledger.ingest.chunk import DocMeta, get_chunker
from ledger.ingest.parse import parse_html
from ledger.pipeline import Ledger
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.filters import Company, CompanyRegistry
from ledger.retrieve.hybrid import Retriever
from ledger.retrieve.rerank import OverlapReranker
from ledger.retrieve.store import InMemoryIndex

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_10k.htm"
ACME = DocMeta(
    "ACME_2024_10K",
    "Acme Widgets",
    "ACME",
    2024,
    source_url="https://www.sec.gov/Archives/edgar/data/1/acme-20241231.htm",
)


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture
def index(embedder: HashingEmbedder) -> InMemoryIndex:
    idx = InMemoryIndex()
    doc = parse_html(SAMPLE.read_text())
    chunks = get_chunker("table", 400, 50).chunk(doc, ACME)
    # A second company, so filters have something to exclude.
    other = DocMeta("BETA_2024_10K", "Beta Corp", "BETA", 2024)
    beta = get_chunker("table", 400, 50).chunk(
        parse_html("<p>Item 7. MD&A</p><p>Total revenue was $9,999 million in 2024.</p>"), other
    )
    all_chunks = chunks + beta
    idx.add(all_chunks, embedder.embed_documents([c.text for c in all_chunks]))
    return idx


@pytest.fixture
def registry() -> CompanyRegistry:
    return CompanyRegistry(
        [Company("ACME", "Acme Widgets", ["Acme"]), Company("BETA", "Beta Corp", ["Beta"])]
    )


def test_config() -> LedgerConfig:
    return LedgerConfig(
        retrieval=RetrievalConfig(embedder="hashing", reranker="overlap", top_k=4, candidates=10)
    )


def passage_number(user_prompt: str, needle: str) -> int:
    """Which [n] passage in the prompt contains ``needle``."""
    for block in user_prompt.split("<passage ")[1:]:
        n = int(block.split('n="')[1].split('"')[0])
        if needle in block:
            return n
    raise AssertionError(f"{needle!r} not in any passage")


Responder = Callable[[str, str], str]


@pytest.fixture
def make_ledger(
    index: InMemoryIndex, embedder: HashingEmbedder, registry: CompanyRegistry
) -> Callable[..., tuple[Ledger, FakeLLM]]:
    def _make(respond: Responder, cache: bool = False) -> tuple[Ledger, FakeLLM]:
        cfg = test_config()
        llm = FakeLLM(respond)
        ledger = Ledger(
            retriever=Retriever(index, embedder, cfg.retrieval, OverlapReranker()),
            generator=Generator(llm),
            config=cfg,
            registry=registry,
            cache=SemanticCache(embedder, threshold=0.9) if cache else None,
        )
        return ledger, llm

    return _make


def claims_json(*claims: dict[str, object], answerable: bool = True) -> str:
    return json.dumps(
        {
            "answerable": answerable,
            "claims": list(claims),
            "confidence": "high",
            "refusal_reason": None if answerable else "not in passages",
        }
    )
