# ADR-003: Run everything for £0

**Status:** accepted · **Date:** 2026-10-09

## Decision

| Need | Choice | Limit we plan around |
|---|---|---|
| Generator | Gemini free tier (`gemini-3.5-flash-lite`, retries on `gemini-3.8-flash`; the 2.5 models are closed to new keys); Groq free tier or local Ollama as drop-in alternatives | Requests per minute/day: the full eval runs nightly, PRs run 50 questions with a 4 s gap |
| Judge | Same free tier | Spot-checked by hand on 50 answers; agreement reported |
| Embeddings / reranker | Open BGE models on CPU | First full index is slow; it is built once and cached in CI |
| Database | In-memory index on the demo; Postgres + pgvector in Docker; Neon/Supabase free tier online | Storage caps: 40 companies fits |
| Tracing | JSONL request log + Langfuse free cloud tier | Monthly event cap |
| CI | GitHub Actions (free for public repos) | Smoke eval only on PRs |
| Hosting | Hugging Face Spaces free CPU | Sleeps when idle; first request is slow |

LLMs are called over plain HTTP, not vendor SDKs, so switching provider is one environment
variable (`LLM_PROVIDER`). Cost is always recorded at **list price** even on a free tier, so the
README can state what Ledger would cost to run for real.

## Consequences

- Free tiers may use prompts for training. Ledger only sends public SEC filings; client
  documents (the freelance use) must use Ollama or a paid tier.
- AWS (DEP-2) stays the week-9 goal on new-account credits, with a £1 budget alarm from day one.
