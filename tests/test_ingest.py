from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ledger.ingest.chunk import FixedChunker, get_chunker
from ledger.ingest.edgar import EdgarClient, download_filings
from ledger.ingest.loader import folder_docs
from ledger.ingest.parse import parse_html
from ledger.ingest.pipeline import Manifest, SourceDoc, ingest, sec_raw_docs
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.store import InMemoryIndex
from tests.conftest import ACME, SAMPLE


def test_parse_finds_items_tables_and_units() -> None:
    doc = parse_html(SAMPLE.read_text())
    assert "Item 7. MD&A" in doc.sections()
    assert "Item 8. Financial Statements" in doc.sections()
    tables = [b for b in doc.blocks if b.is_table and b.section.startswith("Item 8")]
    assert len(tables) == 1
    t = tables[0]
    assert t.units == "millions"
    assert "Total revenue | $4,500 | $4,000" in t.text
    assert "Cost of sales | (2,700) | (2,480)" in t.text
    assert t.anchor == "item8"


def test_parse_drops_hidden_xbrl_header() -> None:
    doc = parse_html(SAMPLE.read_text())
    assert not any("999999" in b.text for b in doc.blocks)


@pytest.mark.parametrize("strategy", ["fixed", "section", "table"])
def test_every_chunker_keeps_metadata(strategy: str) -> None:
    chunks = get_chunker(strategy, 300, 50).chunk(parse_html(SAMPLE.read_text()), ACME)
    assert chunks
    assert all(c.ticker == "ACME" and c.fiscal_year == 2024 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)
    assert any("4,500" in c.text for c in chunks)


def test_table_chunker_isolates_tables_with_context() -> None:
    chunks = get_chunker("table", 1024, 50).chunk(parse_html(SAMPLE.read_text()), ACME)
    tables = [c for c in chunks if c.is_table and c.section.startswith("Item 8")]
    assert tables[0].text.startswith("[Item 8. Financial Statements]")
    assert "amounts in millions" in tables[0].text


def test_table_chunker_splits_long_tables_repeating_header() -> None:
    rows = "".join(f"<tr><td>Line {i}</td><td>{i},000</td></tr>" for i in range(80))
    html = (
        f"<p>Item 8. Financial Statements</p><table><tr><td></td><td>2024</td></tr>{rows}</table>"
    )
    chunks = [c for c in get_chunker("table", 300, 20).chunk(parse_html(html), ACME) if c.is_table]
    assert len(chunks) > 3
    assert all(c.text.splitlines()[1].endswith("2024") for c in chunks)


def test_fixed_chunker_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError):
        FixedChunker(100, 100).chunk(parse_html(SAMPLE.read_text()), ACME)


def test_ingest_is_idempotent_and_reindexes_on_change(tmp_path: Path) -> None:
    raw = tmp_path / "doc.htm"
    raw.write_text(SAMPLE.read_text())
    idx, emb = InMemoryIndex(), HashingEmbedder()
    manifest = Manifest(tmp_path / "manifest.json")
    chunker = get_chunker("table", 500, 50)
    invalidated: list[str] = []

    r1 = ingest([SourceDoc(raw, ACME)], idx, emb, chunker, manifest, invalidated.append)
    n = idx.count()
    assert r1.indexed == ["ACME_2024_10K"] and n > 0

    r2 = ingest([SourceDoc(raw, ACME)], idx, emb, chunker, Manifest(manifest.path))
    assert r2.skipped == ["ACME_2024_10K"] and idx.count() == n

    raw.write_text(SAMPLE.read_text().replace("12,400", "13,000"))
    r3 = ingest(
        [SourceDoc(raw, ACME)], idx, emb, chunker, Manifest(manifest.path), invalidated.append
    )
    assert r3.indexed == ["ACME_2024_10K"] and idx.count() == n
    assert invalidated == ["ACME_2024_10K"]


def test_index_save_and_load_roundtrip(tmp_path: Path) -> None:
    idx, emb = InMemoryIndex(), HashingEmbedder()
    chunks = get_chunker("table", 500, 50).chunk(parse_html(SAMPLE.read_text()), ACME)
    idx.add(chunks, emb.embed_documents([c.text for c in chunks]))
    idx.save(tmp_path)
    loaded = InMemoryIndex.load(tmp_path)
    assert loaded.count() == idx.count()
    assert loaded.documents()[0]["doc_id"] == "ACME_2024_10K"


def _edgar_transport(calls: list[str]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        assert "@" in req.headers["user-agent"]
        if req.url.path == "/files/company_tickers.json":
            return httpx.Response(
                200, json={"0": {"cik_str": 1, "ticker": "ACME", "title": "Acme Widgets"}}
            )
        if req.url.path == "/submissions/CIK0000000001.json":
            return httpx.Response(
                200,
                json={
                    "name": "ACME WIDGETS INC",
                    "filings": {
                        "recent": {
                            "form": ["10-K", "10-Q", "10-K", "10-K/A"],
                            "accessionNumber": [
                                "0001-24-000001",
                                "0001-24-000002",
                                "0001-23-000001",
                                "x",
                            ],
                            "reportDate": ["2024-12-31", "2024-09-30", "2023-12-31", "2023-12-31"],
                            "filingDate": ["2025-02-01", "2024-11-01", "2024-02-01", "2024-03-01"],
                            "primaryDocument": ["acme-2024.htm", "q.htm", "acme-2023.htm", "a.htm"],
                        },
                        "files": [],
                    },
                },
            )
        if req.url.path.endswith(".htm"):
            return httpx.Response(200, text="<p>filing</p>")
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_edgar_download_is_polite_and_idempotent(tmp_path: Path) -> None:
    calls: list[str] = []
    client = EdgarClient(
        "Test test@example.com", min_interval_s=0, transport=_edgar_transport(calls)
    )
    saved = download_filings(client, "ACME", [2023, 2024], tmp_path)
    assert len(saved) == 2
    meta = json.loads((tmp_path / "ACME" / "2024" / "meta.json").read_text())
    assert meta["url"] == ("https://www.sec.gov/Archives/edgar/data/1/000124000001/acme-2024.htm")
    assert meta["doc_id"] == "ACME_2024_10K"
    fetched = len([c for c in calls if c.endswith(".htm")])
    download_filings(client, "ACME", [2023, 2024], tmp_path)
    assert len([c for c in calls if c.endswith(".htm")]) == fetched

    docs = list(sec_raw_docs(tmp_path))
    assert {d.meta.fiscal_year for d in docs} == {2023, 2024}


def test_edgar_requires_contact_email() -> None:
    with pytest.raises(ValueError):
        EdgarClient("no contact")


def test_folder_loader_reads_yaml_config(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "policy_2024.txt").write_text("Refunds within 30 days.\n\nSecond para.")
    (tmp_path / "docs" / "notes.md").write_text("# Notes")
    (tmp_path / "docs" / "ignore.bin").write_text("x")
    cfg = tmp_path / "client.yaml"
    cfg.write_text("company: Client Ltd\nticker: CLNT\nroot: docs\nyear_pattern: '(20\\d{2})'\n")
    docs = list(folder_docs(cfg))
    assert sorted(d.meta.doc_id for d in docs) == ["CLNT:notes.md", "CLNT:policy_2024.txt"]
    policy = next(d for d in docs if "policy" in d.meta.doc_id)
    assert policy.meta.fiscal_year == 2024
    assert len(policy.parser(policy.path.read_bytes()).blocks) == 2
