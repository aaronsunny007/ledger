from __future__ import annotations

import pytest

from ledger.cache.semantic_cache import SemanticCache
from ledger.config import RetrievalConfig
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.filters import CompanyRegistry, Filters, extract_years, filters_from_question
from ledger.retrieve.hybrid import Retriever, reciprocal_rank_fusion
from ledger.retrieve.rerank import OverlapReranker
from ledger.retrieve.store import InMemoryIndex
from ledger.types import Answer, Chunk


def _c(i: str) -> Chunk:
    return Chunk(id=i, text=i, company="X", ticker="X")


def test_rrf_rewards_agreement() -> None:
    fused = reciprocal_rank_fusion(
        {
            "vector": [(_c("a"), 0.9), (_c("b"), 0.8)],
            "keyword": [(_c("b"), 5.0), (_c("c"), 4.0)],
        }
    )
    assert fused[0].chunk.id == "b"
    assert fused[0].ranks == {"vector": 2, "keyword": 1}


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_each_mode_finds_the_revenue_table(
    index: InMemoryIndex, embedder: HashingEmbedder, mode: str
) -> None:
    cfg = RetrievalConfig(embedder="hashing", mode=mode, rerank=False, top_k=3)  # type: ignore[arg-type]
    hits = Retriever(index, embedder, cfg).retrieve(
        "Acme total revenue operating income 2024", Filters(tickers=["ACME"])
    )
    assert hits and all(h.chunk.ticker == "ACME" for h in hits)
    assert any("4,500" in h.chunk.text for h in hits)
    if mode == "hybrid":
        assert any(len(h.ranks) == 2 for h in hits)


def test_reranker_reorders_and_records_rank(
    index: InMemoryIndex, embedder: HashingEmbedder
) -> None:
    cfg = RetrievalConfig(embedder="hashing", rerank=True, top_k=2)
    hits = Retriever(index, embedder, cfg, OverlapReranker()).retrieve(
        "employed people", Filters(tickers=["ACME"])
    )
    assert "employed" in hits[0].chunk.text
    assert hits[0].ranks["rerank"] == 1


def test_rerank_off_by_config_ignores_reranker(
    index: InMemoryIndex, embedder: HashingEmbedder
) -> None:
    cfg = RetrievalConfig(embedder="hashing", rerank=False)
    assert Retriever(index, embedder, cfg, OverlapReranker()).reranker is None


def test_filters_by_year(index: InMemoryIndex, embedder: HashingEmbedder) -> None:
    cfg = RetrievalConfig(embedder="hashing", rerank=False)
    assert Retriever(index, embedder, cfg).retrieve("revenue", Filters(years=[2019])) == []


def test_delete_doc(index: InMemoryIndex) -> None:
    n = index.count()
    removed = index.delete_doc("BETA_2024_10K")
    assert removed > 0 and index.count() == n - removed
    assert all(c.ticker == "ACME" for c in index.chunks)


@pytest.mark.parametrize(
    ("q", "years"),
    [
        ("FY2024 revenue", [2024]),
        ("revenue in FY23", [2023]),
        ("fiscal 2022 vs 2021", [2021, 2022]),
        ("revenue growth", []),
        ("revenue of 12,000", []),
    ],
)
def test_extract_years(q: str, years: list[int]) -> None:
    assert extract_years(q) == years


def test_company_extraction(registry: CompanyRegistry) -> None:
    assert registry.find("How did acme widgets do?") == ["ACME"]
    assert registry.find("BETA vs Acme") == ["ACME", "BETA"]
    assert registry.find("beta testing is fun") == ["BETA"]  # alias match is case-insensitive
    f = filters_from_question("Acme FY2024", registry, Filters(tickers=["BETA"]))
    assert f.tickers == ["BETA"] and f.years == [2024]


def test_cache_never_crosses_years_or_companies() -> None:
    emb = HashingEmbedder()
    cache = SemanticCache(emb, threshold=0.8)
    a = Answer(question="q", answer="Revenue was $4,500 million.")
    cache.store("Acme revenue FY2024", Filters(["ACME"], [2024]), a, {"ACME_2024_10K"})
    hit, _ = cache.lookup("Acme revenue FY2024?", Filters(["ACME"], [2024]))
    assert hit is not None
    miss, _ = cache.lookup("Acme revenue FY2023", Filters(["ACME"], [2023]))
    assert miss is None
    miss2, _ = cache.lookup("Acme revenue FY2024", Filters(["BETA"], [2024]))
    assert miss2 is None
    assert cache.lookup("revenue", Filters())[0] is None and cache.stats.skipped == 1
    assert cache.invalidate_doc("ACME_2024_10K") == 1
    assert cache.lookup("Acme revenue FY2024", Filters(["ACME"], [2024]))[0] is None
    assert 0 < cache.stats.hit_rate < 1


def test_registry_from_yaml(tmp_path: object) -> None:
    from pathlib import Path

    p = Path(str(tmp_path)) / "c.yaml"
    p.write_text("companies:\n  - {ticker: KO, name: Coca-Cola, aliases: [Coke]}\n")
    reg = CompanyRegistry.from_yaml(p)
    assert reg.find("Coke revenue") == ["KO"] and reg.get("ko") is not None
