# Ledger

**Ask a question about a company's annual report and get an answer you can check.** Every
sentence cites the filing passage it came from, and every number is recomputed by a calculator
before you see it. When the filings do not contain the answer, Ledger says so and shows the
closest passages instead of guessing.

> Live demo: _coming in week 8 (Hugging Face Spaces)_ · Results: [first full test run](#results), 70% on 217 questions

```text
Q: How much did Apple's net sales change from FY2023 to FY2024?

Apple's total net sales rose from $383,285 million in FY2023 to $391,035 million in
FY2024, an increase of 2.0% [1].            ✔ verifier: (391035 - 383285) / 383285 * 100 = 2.02

[1] Apple Inc. 10-K FY2024, Item 8. Financial Statements  → opens sec.gov at the highlighted row
```

Ledger is not a chatbot. It is the part around the chatbot that companies pay for:

| | What | Where |
|---|---|---|
| **Measuring it** | A 350-question golden set: the public FinanceBench open set, 150 questions with answers taken from the SEC's own XBRL data, and 50 hand-written traps | [`eval/`](eval/) |
| **Guarding it** | GitHub refuses to merge a change that drops accuracy by more than 2 points | [`ci.yml`](.github/workflows/ci.yml) |
| **Watching it** | Every request traced: latency per stage, tokens, cost, cache, verifier result | [`ledger/obs/`](ledger/obs/) |
| **Shipping it** | API, UI, Docker; a free public demo | [`ledger/api/`](ledger/api/), [`ui/`](ui/) |

## Results

Test split (217 questions: 85 FinanceBench 10-K, 122 XBRL, 10 hand-written refusals), Gemini
`gemini-3.5-flash-lite` on the free tier, run on 2026-10-10. Every number links to a committed JSON
in `eval/results/`.

| System | FinanceBench (10-K subset) | XBRL numeric | Refusals | Groundedness | p50 / p95 latency | Cost / question |
|---|---|---|---|---|---|---|
| [Ledger](eval/results/20261010T071950-ledger-test.json) (hybrid + rerank + pinning + verifier) | **57.6%** (49/85) | **78.7%** (96/122) | **100%** (10/10) | 96.2% | 16.0 s / 36.1 s | $0 (free tier) |
| [Long-context baseline](eval/results/20261010T084724-long-context-test.json) (whole filing, no retrieval) | 61.2% (52/85) | 78.9% (86/109)\* | 100% (10/10) | – (no citations) | 3.5 s / 102 s | $0 (free tier) |
| Target (PRF) | ≥ 70% | ≥ 90% | ≥ 85% | ≥ 90% | ≤ 4 s / ≤ 10 s | ≤ $0.02 |

\* The baseline stopped at the daily free-tier quota with 13 XBRL questions left; it resumes with
`--resume`. Groundedness is the share of claims whose cited passage contains their figures.

**Where this stands.** Overall, Ledger answers 70.0% of the 207 scored questions correctly against the baseline's
71.1%: no better on accuracy yet, and both miss the FinanceBench and XBRL targets. What Ledger adds is that
96% of its claims are grounded in a cited passage, 94% are arithmetic-verified, and it reads about 6k
characters per question instead of a whole filing (up to 600k), which is what the cost target is
about once a paid tier is used. Head to head, each system gets 21–23 questions the other misses.

**What failed** (from the per-question JSON):

- **False refusals on FinanceBench: 20 of 85.** Most are narrative questions (acquisitions, customers,
  litigation, segment growth) where retrieval brings statement tables, not the right prose. One is a
  filter bug: "JnJ" is not recognised as Johnson & Johnson, so no filing is searched.
- **Wrong numbers on XBRL: 17 of 122 (plus 9 refusals).** 9 are "net income change" questions; in the
  ones checked, the model uses consolidated net income while XBRL's `NetIncomeLoss` is the amount
  attributable to the parent (Amcor: a $136M fall vs the gold $134M; P&G: $55M vs $89M). 2 are bad gold labels: General Mills'
  operating margin comes out as 163% and 175%, so the XBRL golden builder mismatches a fact there.
- **Wrong answers on FinanceBench: 16 of 85.** Half are judged text answers (an assessment rather
  than the expected yes/no or list); the rest are multi-step ratios and per-share figures.
- **Latency.** Retrieval alone is about 12 s on a 2-core CPU runner, almost all of it the
  cross-encoder over long statement chunks; generation adds about 4 s. The target is 4 s.
- **The larger model's quota.** `gemini-3.8-flash` allows 20 requests a day on the free tier, so
  regenerations fall back to the default model once it is spent.

### Retrieval experiments

No LLM; [table](eval/results/experiments-retrieval.md), test split, filters read from the question.
Recall is the share of questions whose passages contain the gold evidence.

| Run | What changes | FinanceBench recall | XBRL recall | p50 retrieval |
|---|---|---|---|---|
| **default** | table chunks, hybrid + rerank, statements pinned | **71.8%** | 60.7% | 12.0 s |
| no-pin-statements | statement pinning off | 28.2% | 47.5% | 15.1 s |
| hybrid-no-rerank | reranker off | 68.2% | 51.6% | **0.06 s** |
| rerank-v2-m3 | bge-reranker-v2-m3 instead of -base | **76.5%** | **62.3%** | 52.1 s |
| vector-only | embeddings only | 71.8% | 62.3% | 16.1 s |
| keyword-only | BM25 only | 69.4% | 54.1% | 7.9 s |
| section | section-aware chunks | 27.1% | 54.1% | 11.1 s |
| fixed-1024 | fixed 1,024-character chunks | 25.9% | 56.6% | 12.7 s |
| fixed-512 | fixed 512-character chunks | 10.6% | 45.9% | 7.1 s |

- **Statement pinning is the biggest single factor**: FinanceBench recall falls from 71.8% to 28.2%
  without it. It depends on finding the statements, which ingest now does in
  [all 124 golden filings](eval/results/statements-coverage.md) (it was 107–114 of 124 before:
  statements split across tables, titles in their own table, PDF-style layouts).
- **Table-aware chunking beats section and fixed-size chunking** by 45 points on FinanceBench,
  because a statement stays in one chunk.
- **The reranker costs 12 s for 4 points of FinanceBench recall** (9 on XBRL). The larger v2-m3
  reranker adds 5 more points at four times the latency. Hybrid search does not beat vector-only
  here: BM25 adds nothing over embeddings once the statements are pinned.

### Baseline log

| Date | Run | Setup | Numeric accuracy | False refusals | Recall@6 | Groundedness | p50 latency |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | [week-3 baseline](eval/results/20261009T170958-baseline-week3.json) | 20 FinanceBench dev questions, Qwen2.5-7B on a GitHub CPU runner (Ollama), bge-small + bge-reranker-base | **0 / 16** | 79% | 16% | 75% | 128 s |
| 2026-10-09 | [+ statement pinning](eval/results/20261009T192503-baseline-week3.json) | same, after the retrieval fixes below | **2 / 15** | 35% | 85% | 85% | 121 s |

What failed: the model refused 15 of 19 answerable questions, and the passages it was given rarely
contained the evidence (recall@6 of 16%).

**Retrieval diagnosis** (`eval/diagnose_retrieval.py`, no LLM, same 20 questions):

| | [Before](eval/results/20261009T180700-diagnose.md) | [After](eval/results/20261009T183609-diagnose.md) |
|---|---|---|
| Company and year read correctly from the question | 19/20 | 19/20 |
| Filing in the index | 17/20 | 20/20 |
| Evidence findable anywhere in the filing | 16/20 | 20/20 |
| **Evidence in the passages given to the model** | **3/20** | **17/20** |

The evidence was in the index; ranking was the problem. Formula-style questions ("fixed asset
turnover = revenue / average PP&E") matched narrative text instead of the balance sheet. The
fixes were:

- tag the three primary statements at ingest and always include the ones a question needs;
- search the latest filing when several years are named, because it holds the comparatives;
- download EX-13 exhibits (CVS keeps its statements there);
- look up Activision and Square by CIK, because they are no longer listed under those tickers.

The 3 misses left are narrative questions (drivers, acquisitions, litigation).

With the right passages in hand, refusals fell from 79% to 35% and recall@k rose from 16% to 85%.
Accuracy only moved to 2 of 15, and the wrong answers show where the next work is:

- **Unit and scale errors that the verifier passes.** CVS's fixed asset turnover came out as
  1798.24 instead of 17.98, and Adobe's operating cash flow ratio as 825.77 instead of 0.83. In both,
  the arithmetic is internally consistent, so the verifier marks it verified. This is the
  Financial-NRF caveat in practice: verified does not mean correct.
- **A weak model on hard formulas.** DPO, cash conversion cycle and multi-year averages need several
  correct steps from a 7B model on CPU. A stronger free-tier model (Gemini) is the next variable to
  change.
- **Scoring bugs found on the way.** Gold answers stated in USD millions were not matched, and
  questions over 500 characters were rejected. Both are fixed, and saved runs can be re-scored with
  `python eval/run_eval.py --rescore <file>`.

Still to report: verifier on vs off, and cache hit vs false-hit rate.

## How it works

```text
                ┌──────────── offline ────────────┐
 SEC EDGAR ──▶  download (HTML) ─▶ parse Items & tables ─▶ chunk ─▶ embed (BGE) ─▶ pgvector + full-text
                └─────────────────────────────────┘
 question ─▶ company/year filters ─▶ cache (keyed on company+year) ─hit─▶ answer
                                         │ miss
                                         ▼
           hybrid search (vector + BM25, RRF) ─▶ cross-encoder rerank ─▶ top 6 passages
                                         ▼
           LLM drafts JSON claims with citations + calculations
                                         ▼
           NRF verifier: recompute every calculation, check every number is in the cited text
                 ├─ pass ─▶ answer with citations and ✔
                 └─ fail ─▶ regenerate once with the correction ─▶ still failing? flag ⚠ unverified
```

- **Retrieval** – hybrid vector + keyword search fused with Reciprocal Rank Fusion, filtered by
  company and fiscal year *before* ranking, then a cross-encoder reranker. Every stage is a
  switch in [`configs/retrieval.yaml`](configs/retrieval.yaml) so its contribution can be measured.
- **Verifier** – ported from my MSc project [Financial-NRF](https://github.com/aaronsunny007/Financial-NRF).
  It evaluates the model's arithmetic with a restricted syntax-tree evaluator (never `eval()`),
  and checks each operand appears in the cited passage. "Verified" means *internally consistent
  and grounded*, not *correct*; correctness is what the eval measures.
- **Cache** – a plain semantic cache would answer "revenue 2023" with the 2024 figure, because the
  questions embed almost identically. Ledger's cache key is company + fiscal year first, and the
  false-hit rate is reported.

## Run it (≈10 minutes, £0)

Requires Python 3.12. Everything runs on free tiers or on your laptop.

```bash
git clone https://github.com/aaronsunny007/ledger && cd ledger
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,models]"
cp .env.example .env          # add a free Gemini or Groq key and your SEC_USER_AGENT

ledger download --tickers AAPL MSFT --years 2023 2024   # 10-K HTML from SEC EDGAR
ledger ingest                                           # parse, chunk, embed (CPU is fine)
ledger ask "What was Apple's revenue in fiscal year 2024?"

uvicorn ledger.api.main:app --reload      # API + OpenAPI docs at http://localhost:8000/docs
streamlit run ui/streamlit_app.py         # UI at http://localhost:8501
```

With Docker (Postgres + pgvector, API and UI): `docker compose up`.

No API key? Install [Ollama](https://ollama.com), `ollama pull qwen2.5:7b-instruct`, and set
`LLM_PROVIDER=ollama`.

### API

| | |
|---|---|
| `POST /ask` | `{"question": "...", "tickers": ["AAPL"], "years": [2024]}` → `answer`, `claims[]` (text, citations, calculation, verified), `citations[]`, `refused`, `latency_ms`, `cost_usd` |
| `POST /ask/stream` | Server-sent events: progress stages, then the verified answer |
| `GET /documents` | Ingested filings |
| `POST /feedback` | Thumbs up/down on a `request_id` |
| `GET /health` | |

### Use it on your own documents

Point it at any folder of PDF, HTML or text files with one YAML file; see
[Ledger for your documents](docs/ledger-for-your-documents.md).

```bash
ledger ingest --folder configs/examples/my_docs.yaml
```

## Evaluate

```bash
python scripts/financebench.py              # FinanceBench open set -> eval/golden/
python scripts/make_xbrl_questions.py       # 150 questions answered by SEC XBRL data
python eval/run_eval.py --split dev         # tune here, never on test
python eval/run_eval.py --split test --judge
python eval/run_eval.py --system long-context --split test
```

Or run the **build-golden** workflow from the Actions tab. See [`eval/README.md`](eval/README.md).

## Repository

```text
ledger/
  ingest/      edgar.py (ING-1), parse.py (ING-2), chunk.py (ING-4), pipeline.py (ING-5), loader.py (ING-6)
  retrieve/    hybrid.py (RET-1/3/4), filters.py (RET-2), rerank.py, store.py, pgstore.py
  answer/      generate.py (ANS-1..4), citations.py, llm.py (Gemini / Groq / Ollama), prompts/
  verifier/    ported from Financial-NRF (VER-1..4)
  cache/       semantic_cache.py (CACHE-1..3)
  obs/         tracing.py, langfuse_sink.py, dashboard.py (OBS-1..5)
  api/         main.py (API-1/2, COST-3)
  evaluation/  golden.py, metrics.py, gate.py, judge.py, baseline.py
eval/          golden/*.jsonl, run_eval.py, results/
configs/       corpus.yaml, retrieval.yaml
docs/adr/      architecture decision records
```

Requirement IDs (ING-1, VER-2, ...) refer to the project requirements file and appear in code
comments so each one can be traced.

## Limits

Ledger answers only from filings it has ingested, gives no investment advice and has no market
data. FinanceBench is CC BY-NC 4.0: fine for this portfolio project, not for paid client work.
See [MODEL_CARD.md](MODEL_CARD.md) and [SECURITY.md](SECURITY.md).

## Licence

MIT. Copyright (c) 2026 Aaron Prakash Gandi.
