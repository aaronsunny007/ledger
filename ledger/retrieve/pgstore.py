"""Postgres 16 + pgvector + full-text search, behind the same ``Index`` protocol.

Works with the docker compose database, Neon free tier or Supabase free tier:
point ``DATABASE_URL`` at it and set ``STORE=postgres``. Needs the
``postgres`` extra.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from ledger.retrieve.embed import Vector
from ledger.retrieve.filters import Filters
from ledger.retrieve.store import Hit, _terms
from ledger.types import Chunk

_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
    id          text PRIMARY KEY,
    doc_id      text NOT NULL,
    ticker      text NOT NULL,
    fiscal_year int,
    section     text,
    data        jsonb NOT NULL,
    embedding   vector({dim}) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', data->>'text')) STORED
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_meta_idx ON chunks (ticker, fiscal_year);
CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (doc_id);
"""


class PgVectorIndex:
    def __init__(self, dsn: str, dim: int):
        import psycopg
        from pgvector.psycopg import register_vector

        self._conn: Any = psycopg.connect(dsn, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._conn)
        self._conn.execute(_SCHEMA.format(dim=dim))

    @staticmethod
    def _where(filters: Filters) -> tuple[str, list[Any]]:
        clauses: list[str] = ["TRUE"]
        params: list[Any] = []
        if filters.tickers:
            clauses.append("ticker = ANY(%s)")
            params.append(filters.tickers)
        if filters.years:
            clauses.append("fiscal_year = ANY(%s)")
            params.append(filters.years)
        for s in filters.sections:
            clauses.append("section ILIKE %s")
            params.append(f"%{s}%")
        return " AND ".join(clauses), params

    def add(self, chunks: list[Chunk], vectors: Vector) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (id, doc_id, ticker, fiscal_year, section, data, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
                "data = EXCLUDED.data, embedding = EXCLUDED.embedding, section = EXCLUDED.section",
                [
                    (
                        c.id,
                        c.doc_id,
                        c.ticker,
                        c.fiscal_year,
                        c.section,
                        c.model_dump_json(),
                        np.asarray(v, dtype=np.float32),
                    )
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )

    def delete_doc(self, doc_id: str) -> int:
        cur = self._conn.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
        return int(cur.rowcount)

    def vector_search(self, query: Vector, k: int, filters: Filters) -> list[Hit]:
        where, params = self._where(filters)
        q = np.asarray(query, dtype=np.float32)
        rows = self._conn.execute(
            f"SELECT data, 1 - (embedding <=> %s) FROM chunks WHERE {where} "
            "ORDER BY embedding <=> %s LIMIT %s",
            [q, *params, q, k],
        ).fetchall()
        return [(Chunk.model_validate(_json(r[0])), float(r[1])) for r in rows]

    def keyword_search(self, query: str, k: int, filters: Filters) -> list[Hit]:
        terms = sorted(set(_terms(query)))
        if not terms:
            return []
        # OR the terms so one missing word does not empty the result.
        tsquery = " | ".join(t.replace("'", "") for t in terms)
        where, params = self._where(filters)
        rows = self._conn.execute(
            f"SELECT data, ts_rank_cd(tsv, to_tsquery('english', %s)) AS r FROM chunks "
            f"WHERE {where} AND tsv @@ to_tsquery('english', %s) ORDER BY r DESC LIMIT %s",
            [tsquery, *params, tsquery, k],
        ).fetchall()
        return [(Chunk.model_validate(_json(r[0])), float(r[1])) for r in rows]

    def documents(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT doc_id, min(data->>'company'), ticker, fiscal_year, min(data->>'source_url'), "
            "count(*) FROM chunks GROUP BY doc_id, ticker, fiscal_year ORDER BY ticker, fiscal_year"
        ).fetchall()
        return [
            {
                "doc_id": r[0],
                "company": r[1],
                "ticker": r[2],
                "fiscal_year": r[3],
                "form_type": "10-K",
                "source_url": r[4],
                "chunks": r[5],
            }
            for r in rows
        ]

    def statement_chunks(self, filters: Filters, statements: list[str]) -> list[Chunk]:
        where, params = self._where(filters)
        rows = self._conn.execute(
            f"SELECT data FROM chunks WHERE {where} AND data->>'statement' = ANY(%s) ORDER BY id",
            [*params, statements],
        ).fetchall()
        return [Chunk.model_validate(_json(r[0])) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT count(*) FROM chunks").fetchone()[0])


def _json(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v
