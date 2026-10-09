from __future__ import annotations

import pytest

from ledger.config import RetrievalConfig
from ledger.ingest.chunk import get_chunker
from ledger.ingest.parse import parse_html
from ledger.ingest.statements import statements_needed
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.filters import Filters
from ledger.retrieve.hybrid import Retriever
from ledger.retrieve.store import InMemoryIndex
from tests.conftest import ACME, SAMPLE

BS = (
    "<p>Item 8. Financial Statements</p><p>CONSOLIDATED BALANCE SHEETS</p><p>(in millions)</p>"
    "<table><tr><td></td><td>2024</td><td>2023</td></tr>"
    "<tr><td>Inventories</td><td>900</td><td>850</td></tr>"
    "<tr><td>Total assets</td><td>9,000</td><td>8,000</td></tr>"
    "<tr><td>Total liabilities</td><td>5,000</td><td>4,500</td></tr></table>"
    # A note table that mentions the balance sheet but is not the statement.
    "<p>The following balance sheet reconciliation shows leases.</p>"
    "<table><tr><td>Lease assets</td><td>10</td></tr>"
    "<tr><td>Lease liabilities</td><td>9</td></tr></table>"
)


def test_primary_statements_are_tagged_and_kept_whole() -> None:
    chunks = get_chunker("table", 300, 50).chunk(parse_html(SAMPLE.read_text() + BS), ACME)
    tagged = {c.statement: c for c in chunks if c.statement}
    assert set(tagged) == {"income", "balance_sheet"}
    assert "Total liabilities" in tagged["balance_sheet"].text  # not split at 300 chars
    assert not any("Lease assets" in c.text for c in tagged.values())


@pytest.mark.parametrize(
    ("q", "needs"),
    [
        (
            "What is the FY2019 fixed asset turnover ratio for Activision?",
            ["balance_sheet", "income"],
        ),
        ("What is the FY2018 capital expenditure amount for 3M?", ["cash_flow"]),
        ("Does AMD have a healthy quick ratio for FY22?", ["balance_sheet"]),
        ("What industry does Amcor operate in?", []),
    ],
)
def test_statements_needed(q: str, needs: list[str]) -> None:
    assert statements_needed(q) == needs


def _retriever(pin: bool) -> Retriever:
    emb = HashingEmbedder()
    idx = InMemoryIndex()
    chunks = get_chunker("table", 300, 50).chunk(parse_html(SAMPLE.read_text() + BS), ACME)
    idx.add(chunks, emb.embed_documents([c.text for c in chunks]))
    cfg = RetrievalConfig(embedder="hashing", rerank=False, top_k=1, pin_statements=pin)
    return Retriever(idx, emb, cfg)


def test_needed_statement_is_pinned_first() -> None:
    q = "What were Acme's inventories at the end of 2024?"
    pinned = _retriever(True).retrieve(q, Filters(tickers=["ACME"]))
    assert pinned[0].chunk.statement == "balance_sheet" and pinned[0].ranks == {"pinned": 1}
    assert not any(p.chunk.statement for p in _retriever(False).retrieve(q, Filters(["ACME"]))[:0])


def test_pinning_needs_a_company_filter() -> None:
    hits = _retriever(True).retrieve("What were inventories?", Filters())
    assert all("pinned" not in h.ranks for h in hits)


def test_latest_year_only_falls_back_when_latest_missing() -> None:
    r = _retriever(False)
    assert r.retrieve("revenue", Filters(["ACME"], [2023, 2024]))  # latest (2024) exists
    assert r.retrieve("revenue", Filters(["ACME"], [2024, 2025]))  # 2025 missing -> all years
