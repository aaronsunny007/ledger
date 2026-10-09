# ADR-002: Store — Postgres 16 with pgvector and full-text search

**Status:** accepted · **Date:** 2026-10-09

## Decision

One Postgres 16 database holds chunk text, metadata, a `vector` column (pgvector, HNSW index,
cosine distance) and a generated `tsvector` column (GIN index) for keyword search. Metadata
filters (`ticker`, `fiscal_year`, `section`) are plain `WHERE` clauses applied before ranking.

A dependency-free `InMemoryIndex` (numpy + BM25, saved to `data/processed/index/`) implements
the same `Index` protocol. It is the default for laptops and for the free Hugging Face Space;
Postgres is used with `docker compose` and in production.

## Why

- **Hybrid search in one place.** Vector and keyword search over the same rows, with the same
  filters, in one query language. No second system to keep in sync.
- **Filters before ranking** are a `WHERE` clause, not a post-filter that can empty the top-k.
- **Free everywhere:** Docker locally, Neon or Supabase free tier online, RDS on AWS credits.
- **Boring and hireable:** Postgres is in every job description; a vector-only database is not.

## Alternatives

- **Qdrant** (measured alternative in the PRF): excellent filtered vector search, but keyword
  search would need a second engine, and it is one more service to run on a free tier.
- **FAISS** (used in Financial-NRF): fast, but no metadata filtering or persistence story.

## Consequences

- Postgres full-text ranking (`ts_rank_cd`) is not BM25; the in-memory index uses true BM25.
  Retrieval experiments must name which store produced them.
- The embedding dimension is fixed per table; changing embedder means re-creating the table
  (the ingest manifest records the embedder, so re-indexing is detected).
