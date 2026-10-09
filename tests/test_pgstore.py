"""Postgres + pgvector store. Runs only when LEDGER_TEST_DATABASE_URL is set
(CI starts a pgvector service container for it)."""

from __future__ import annotations

import os

import pytest

from ledger.ingest.chunk import get_chunker
from ledger.ingest.parse import parse_html
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.filters import Filters
from tests.conftest import ACME, SAMPLE

DSN = os.environ.get("LEDGER_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="LEDGER_TEST_DATABASE_URL not set")


def test_pgvector_index_roundtrip() -> None:
    from ledger.retrieve.pgstore import PgVectorIndex

    emb = HashingEmbedder()
    idx = PgVectorIndex(str(DSN), emb.dim)
    idx.delete_doc(ACME.doc_id)
    chunks = get_chunker("table", 400, 50).chunk(parse_html(SAMPLE.read_text()), ACME)
    idx.add(chunks, emb.embed_documents([c.text for c in chunks]))
    assert idx.count() >= len(chunks)

    q = "Acme total revenue 2024"
    vec = idx.vector_search(emb.embed_query(q), 3, Filters(tickers=["ACME"], years=[2024]))
    kw = idx.keyword_search(q, 3, Filters(tickers=["ACME"]))
    assert vec and kw and any("4,500" in c.text for c, _ in kw)
    assert idx.vector_search(emb.embed_query(q), 3, Filters(years=[1999])) == []
    assert any(d["doc_id"] == ACME.doc_id for d in idx.documents())
    assert idx.delete_doc(ACME.doc_id) == len(chunks)
