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
| **Guarding it** | GitHub refuses to merge a change that clearly drops accuracy, groundedness or refusals (more than 2 points and beyond sampling noise) | [`ci.yml`](.github/workflows/ci.yml) |
| **Watching it** | Every request traced: latency per stage, tokens, cost, cache, verifier result | [`ledger/obs/`](ledger/obs/) |
| **Shipping it** | API, UI, Docker; a free public demo | [`ledger/api/`](ledger/api/), [`ui/`](ui/) |

## Results

Test split (217 questions: 85 FinanceBench 10-K, 122 XBRL, 10 hand-written refusals), Gemini
`gemini-3.5-flash-lite` on the free tier, run on 2026-10-13 (Ledger) and 2026-10-14 (baseline), both on the same prompt. Every number links to a committed JSON
in `eval/results/`.

| System | FinanceBench (10-K subset) | XBRL numeric | Refusals | Groundedness | p50 / p95 latency | Cost / question |
|---|---|---|---|---|---|---|
| [Ledger](eval/results/20261013T073749-ledger-test.json) (vector search + pinning + verifier) | 56.5% (48/85) | **94.3%** (115/122) | **100%** (10/10) | 96.3% | **0.9 s** / **4.9 s** | $0 (free tier) |
| [Long-context baseline](eval/results/20261014T080946-long-context-test.json) (whole filing, no retrieval) | **65.9%** (56/85) | 82.0% (100/122) | 100% (10/10) | – (no citations) | 4.1 s / 157.5 s\* | $0 (free tier) |
| Target (PRF) | ≥ 70% | ≥ 90% | ≥ 85% | ≥ 90% | ≤ 4 s / ≤ 10 s | ≤ $0.02 |

\* The baseline's tail latency includes the free tier's rate-limit waits (each question sends a whole filing, and the last third of the run was throttled to about two minutes a question), so its p95 overstates the cost of the approach; its p50 is the fairer figure. The earlier baseline run (11 Oct, [file](eval/results/20261011T160510-long-context-test.json)) used the previous prompt and scored 74.8% overall.
Groundedness is the share of claims whose cited passage contains their figures.

**Where this stands.** Overall Ledger answers 78.7% of the 207 scored questions (163) against the
baseline's 75.4% (156). It meets five of the six targets: XBRL (115 of 122), refusals (10 of 10), groundedness,
and both latency targets (0.9 s median, 4.9 s slowest-5%), with cost at zero. It misses FinanceBench (56.5% against 70%). The
long-context baseline is better than Ledger on FinanceBench by 9 points; Ledger is better on XBRL by 12, and it cites
its sources, checks its arithmetic and answers in about a second. Where the two disagree, Ledger is right on 26 questions
the baseline gets wrong (15 XBRL, 11 FinanceBench) and the baseline is right on 19 that Ledger gets wrong (all FinanceBench).
Ledger's p95 of 4.9 s is partly luck of the run (fewer regenerations and no rate-limit waits; 14.6 s on 12 Oct). I have not
measured run-to-run noise on the free tier beyond the five questions that flipped for the worse on 13 Oct, so treat gaps under
about 3 points as inconclusive.

**How Ledger got here** (same 217 questions; the first run predates a corrected General Mills answer
key, which moves three questions):

| Run | Change | Overall | FinanceBench | XBRL | p50 latency |
|---|---|---|---|---|---|
| [10 Oct](eval/results/20261010T071950-ledger-test.json) | first full run: hybrid search + reranker | 70.0% | 57.6% | 78.7% | 16.0 s |
| [11 Oct](eval/results/20261011T154339-ledger-test.json) | + net-income prompt, answer-key fix, JnJ alias, year fallback; vector search, no reranker | 68.1% | 52.9% | 78.7% | 0.9 s |
| [12 Oct](eval/results/20261012T071411-ledger-test.json) | + statement pinning for named line items (cash, R&D, debt...) | 76.3% | 56.5% | 90.2% | 0.9 s |
| [13 Oct](eval/results/20261013T073749-ledger-test.json) | + J&J fiscal-year label, investment-advice refusal, citation parsing, net-income line | 78.7% | 56.5% | 94.3% | 0.9 s |

**13 Oct follow-up** (the four fixes for the failures below, same 217 questions). Overall 78.7% (163 of 207), XBRL 94.3% (115/122), refusals 10/10, groundedness 96.3%, p50 0.9 s,
p95 4.9 s. Fixed: five of the six net-income-change questions, the investment-advice refusal, J&J inventory turnover
and Walmart's EBITDA margin (one of the two citation-parsing failures), plus three FinanceBench questions that
flipped without a targeted change. Not fixed: two of the three J&J questions (retrieval still misses the evidence
for 00956 and 00669), 03718 (still refuses although the evidence is retrieved), CVS net income change. Five
questions got worse (Adobe, Best Buy and Corning now answer for the wrong years or with another line item; American
Express is refused instead of explained), which looks like the free model's run-to-run variation: FinanceBench overall is
unchanged at 56.5%, so the FinanceBench gains and losses cancel. The p95 drop (14.6 s to 4.9 s) is mostly
fewer regenerations (11.5% against 16.1%) and no rate-limit waits on this run, not a latency fix.
FinanceBench accuracy is the one target still missing.

Dropping the reranker made retrieval 250 times faster but lost ten questions that never say "balance
sheet" or "income statement", because nothing told Ledger which statement to include. Pinning by line
item recovered them and more, and XBRL recall rose from 53% to 65%.

**What failed** (from the per-question JSON of the 12 Oct run; the 13 Oct paragraph above says what the follow-up fixed):

- **False refusals on FinanceBench: 22 of 85.** Thirteen are narrative questions (acquisitions, customers,
  litigation, segments, registered securities) where retrieval brings statement tables, not the right
  prose. Four are ratio or assessment questions where the needed figures did not reach the model (3M and
  CVS capital intensity, Adobe free cash flow conversion, Corning's tax rate). Three are Johnson & Johnson,
  and are a bug: Ledger labels a filing by the calendar year its period ends in, J&J's fiscal 2022 ended on
  1 January 2023, so "FY2022" lands on the previous year's filing ("they only cover years up to 2021").
  Two are "no claim could be supported with a citation": the model answered, but its citations did not parse.
- **Wrong answers on FinanceBench: 15 of 85.** Multi-step ratios, per-share figures and assessments that
  the judge marked wrong.
- **Wrong numbers on XBRL: 10 of 122, plus 2 refusals.** Six are "net income change" questions: the prompt now says
  plain "net income" means the amount attributable to the company, but several still use another line (Boeing,
  Tesla, CVS, Verizon, MGM, Amcor). The two refusals are Home Depot and Ulta, whose years end in January: the question says fiscal 2023, the filing
  calls the same year fiscal 2022, and the model declines.
- **One refusal case failed.** "Should I buy NVIDIA stock?" was answered with risk-factor text instead of
  declined; the prompt has no rule against investment advice yet.
- **Latency tail.** All 15 questions slower than 10 s were regenerated after the first answer failed
  verification (35 of 217 regenerate). The slowest took 146 s, which looks like waiting out free-tier
  rate limits, not computation.
- **Free-tier quota.** Gemini's free tier allows 500 requests a day, resetting at midnight Pacific
  (07:00 GMT), and the larger `gemini-3.8-flash` only 20. A full Ledger run plus the baseline needs about
  370, and a rate-limited eval waits or stops and resumes (`eval/run_eval.py --resume`).

### Retrieval experiments

No LLM; [table](eval/results/experiments-retrieval.md), test split, filters read from the question.
Recall is the share of questions whose passages contain the gold evidence. The table-index rows ran on
the final code; the three chunking rows (no statement tags, so unaffected by pinning) ran earlier.

| Run | What changes | FinanceBench recall | XBRL recall | p50 retrieval |
|---|---|---|---|---|
| **default** | table chunks, vector search, no reranker, statements pinned | 74.1% | 64.8% | **0.06 s** |
| hybrid-rerank | hybrid search + bge-reranker-base (the earlier default) | 74.1% | 65.6% | 9.1 s |
| rerank-top10 | rerank only the top 10 candidates | 72.9% | 64.8% | 3.9 s |
| rerank-v2-m3 | bge-reranker-v2-m3 instead of -base | **78.8%** | **67.2%** | 42.9 s |
| hybrid-no-rerank | hybrid search, reranker off | 70.6% | 63.9% | 0.08 s |
| vector-only | embeddings only, with the reranker | 74.1% | 64.8% | 10.1 s |
| keyword-only | BM25 only, with the reranker | 71.8% | 63.1% | 14.4 s |
| no-pin-statements | statement pinning off | 29.4% | 47.5% | 14.9 s |
| section | section-aware chunks | 27.1% | 54.1% | 11.1 s |
| fixed-1024 | fixed 1,024-character chunks | 25.9% | 56.6% | 12.7 s |
| fixed-512 | fixed 512-character chunks | 10.6% | 45.9% | 7.1 s |

- **Statement pinning is the biggest single factor**: FinanceBench recall falls from 74.1% to 29.4%
  without it. It depends on finding the statements, which ingest now does in
  [all 124 golden filings](eval/results/statements-coverage.md) (it was 107-114 of 124 before:
  statements split across tables, titles in their own table, PDF-style layouts), and on knowing which
  statement a question needs, which now includes named line items such as cash or R&D.
- **Table-aware chunking beats section and fixed-size chunking** by about 47 points on FinanceBench,
  because a statement stays in one chunk.
- **Once the right statements are pinned, the base reranker adds under one point** (74.1% / 65.6% against
  74.1% / 64.8%) for 9 seconds, so Ledger dropped it. Only the larger v2-m3 reranker improves recall
  (+4.7 and +2.4 points), at 43 seconds a question: too slow on a free CPU runner, a reasonable
  choice with a GPU or a paid reranking API.
- **Hybrid search does not beat vector search**: BM25 on top of embeddings is 3.5 points worse on
  FinanceBench recall than embeddings alone once the statements are pinned.

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
