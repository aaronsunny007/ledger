# ADR-004: Embedding and reranking models

**Status:** proposed — to be confirmed by the week-4 retrieval experiments · **Date:** 2026-10-09

## Decision (starting point)

- **Embedder:** `BAAI/bge-small-en-v1.5` (384 dimensions, ~130 MB). Fast enough on a laptop CPU
  to index 120 filings once; `bge-base` is the measured step up.
- **Reranker:** `BAAI/bge-reranker-base` cross-encoder over the top 30 fused candidates, keeping 6.
  `BAAI/bge-reranker-v2-m3` (the PRF default) is the measured alternative.

## Why not v2-m3 by default

It is about twice the size of `bge-reranker-base`. On a free CPU, reranking 30 passages of up to
512 tokens with it is likely to exceed the PRF's p50 latency target of 4 s on its own. The
experiment table will report both: if v2-m3's accuracy gain is worth the latency, it becomes
the default and this ADR is updated.

## Evidence to collect

- recall@6 and MRR with rerank off / base / v2-m3 on the dev split;
- p50 / p95 rerank latency on the Hugging Face Space CPU;
- answer accuracy end to end.

A 2026 study found a cross-encoder reranker lifted "basically correct" 10-K answers from 33.5%
to 49.0% (arXiv 2603.16877); the experiment checks whether that holds here.
