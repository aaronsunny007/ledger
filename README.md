# Ledger

**Ask a question about a company's annual report and get an answer you can check.** Every
sentence cites the filing passage it came from, and every number is recomputed by a calculator
before you see it. When the filings do not contain the answer, Ledger says so and shows the
closest passages instead of guessing.

> Results: [80.7% on the 207 scored test questions](#results) on the latest run (24 Oct; three earlier runs of older code scored 77.3–78.7%), the long-context baseline gets 75.4%; live demo: not deployed yet, see [Running the demo](#running-the-demo)

```text
Q: How much did Apple's net sales change from FY2022 to FY2023?

Apple's total net sales fell from $394,328 million in FY2022 to $383,285 million in
FY2023, a decrease of 2.80% [1].            ✔ verifier: (383285 - 394328) / 394328 * 100 = -2.80

[1] Apple Inc. 10-K FY2023, Item 8. Financial Statements  → opens sec.gov at the highlighted row
```

Ledger is not a chatbot. It is the part around the chatbot that companies pay for:

| | What | Where |
|---|---|---|
| **Measuring it** | A 313-question golden set: 150 questions from the public FinanceBench open set, 150 with answers taken from the SEC's own XBRL data, and 13 hand-written traps | [`eval/`](eval/) |
| **Guarding it** | GitHub refuses to merge a change that clearly drops accuracy, groundedness or refusals (more than 2 points and beyond sampling noise) | [`ci.yml`](.github/workflows/ci.yml) |
| **Watching it** | Every request traced: latency per stage, tokens, cost, cache, verifier result | [`ledger/obs/`](ledger/obs/) |
| **Shipping it** | API, UI, Docker; a free public demo | [`ledger/api/`](ledger/api/), [`ui/`](ui/) |

## Results

Test split (217 questions: 85 FinanceBench 10-K, 122 XBRL, 10 hand-written refusals), Gemini
`gemini-3.5-flash-lite` on the free tier, run on 2026-10-23/24 (Ledger) and 2026-10-14 (baseline). The baseline ran on an
earlier version of the prompt (the Ledger prompt has changed since, see "24 Oct" below). Every number links to a committed JSON
in `eval/results/`.

| System | FinanceBench (10-K subset) | XBRL numeric | Refusals | Groundedness | p50 / p95 latency | Cost / question |
|---|---|---|---|---|---|---|
| [Ledger](eval/results/20261023T232507-ledger-test-v2.json) (vector search + pinning + verifier) | 63.5% (54/85) | **92.6%** (113/122) | **100%** (10/10) | 94.6% | **1.8 s** / **6.3 s** | $0 (free tier) |
| [Long-context baseline](eval/results/20261014T080946-long-context-test.json) (whole filing, no retrieval) | **65.9%** (56/85) | 82.0% (100/122) | 100% (10/10) | – (no citations) | 4.1 s / 157.5 s\* | $0 (free tier) |
| Target (PRF) | ≥ 70% | ≥ 90% | ≥ 85% | ≥ 90% | ≤ 4 s / ≤ 10 s | ≤ $0.02 |

\* The baseline's tail latency includes the free tier's rate-limit waits (each question sends a whole filing, and the last third of the run was throttled to about two minutes a question), so its p95 overstates the cost of the approach; its p50 is the fairer figure. The earlier baseline run (11 Oct, [file](eval/results/20261011T160510-long-context-test.json)) used the previous prompt and scored 74.8% overall.
Groundedness is the share of claims whose cited passage contains their figures.

**Where this stands.** On the 24 Oct run Ledger answers 80.7% of the 207 scored questions (167) against the
baseline's 75.4% (156). It meets five of the six targets: XBRL (113 of 122), refusals (10 of 10), groundedness (94.6%),
and both latency targets (1.8 s median, 6.3 s slowest-5%), with cost at zero. It still misses FinanceBench (63.5%
against 70%). The long-context baseline is now ahead of Ledger on FinanceBench by 2 points (65.9% against 63.5%), where on
13 Oct it was ahead by 9; Ledger is ahead on XBRL by 11, and it cites its sources, checks its arithmetic and answers in
under two seconds. The three earlier runs (13, 16 and 17 Oct) scored 77.3–78.7% overall and 52.9–56.5% on FinanceBench.

**Run-to-run noise.** The free tier does not answer the same way twice. A repeat of the same code on 16 Oct
([file](eval/results/20261016T134041-ledger-test-repeat1.json), [report](eval/results/noise.md)) scored 77.3% overall
against 78.7%, FinanceBench 52.9% against 56.5%, XBRL 94.3% both times, groundedness 96.8% against 96.3%. Nine of the
217 questions changed between right and wrong (all FinanceBench), including four I had counted as fixed on 13 Oct and
three I had counted as regressions. So differences of about 3 points on FinanceBench or 1.5 points overall between two
runs are inside the noise; only the XBRL and refusal results were stable.

**17 Oct: narrative retrieval, end to end** ([file](eval/results/20261017T071149-ledger-test.json), the same 217 questions
with the narrative settings from `configs/retrieval.yaml`). Overall 77.8% (161 of 207), FinanceBench 55.3% (47 of 85),
XBRL 93.4% (114 of 122), refusals 10/10, groundedness 98.2%, p50 1.0 s, p95 2.6 s, no errors. All three are
inside the noise range of the two earlier runs (overall 77.3–78.7%, FinanceBench 52.9–56.5%): **this run does not show an accuracy
gain on the whole set.** What it does show is on the 19 narrative questions I had traced: all 19 were wrong in both
earlier runs, and 4 are right now (ids 00499, 01028, 01981, 02024), none of them wrong again. The other flips are
questions the narrative settings do not touch, and they go both ways (8 against the 13 Oct run, 5 against the 16 Oct
run), which is what the noise looks like. So the change helps the questions it was built for, a little (4 of 19), and
the evidence of a net gain is not strong enough to claim it. Retrieval recall rose as measured (FinanceBench 80.0%),
latency did not move. The code differs from the other two runs, so this run is not pooled into the noise report.

**24 Oct: answer form, arithmetic repair, stated fallbacks** ([file](eval/results/20261023T232507-ledger-test-v2.json)).
Overall 80.7% (167 of 207), FinanceBench 63.5% (54 of 85), XBRL 92.6% (113 of 122), refusals 10/10, groundedness 94.6%,
p50 1.8 s, p95 6.3 s, no errors. Four changes, all found by reading failures on the **dev** split (58 questions) rather
than the test split, then run once on the test split:

1. The prompt follows the question's rounding ("round to one decimal place") and states a ratio the question defines as
   A / B as a plain number (0.83) instead of a percentage (82.58%). Three dev answers were right in substance and scored wrong
   only because of this.
2. When a claim's own calculation recomputes to a different value than the one written beside it (CVS fixed-asset
   turnover: written 18.23, the calculation gives 17.98), the sentence now carries the recomputed value. The
   operands are still checked against the cited passages afterwards.
3. When the question offers a fallback ("if restructuring costs are not outlined, state 0", "if operating margin is not
   a useful metric for a company like this, say so") and the passages show it applies, the fallback is the answer and
   not a refusal.
4. A reply that is not valid JSON gets one retry instead of becoming a refusal.

On dev, accuracy went from 74.5% (41 of 55) to 81.8% (45 of 55). On the test split FinanceBench rose from 52.9–56.5% to
63.5%, a gain of at least 7 points against a noise range of about 3.5, and overall from 77.3–78.7% to 80.7%
(+2.0 against about 1.5). So this one is outside the noise I measured, unlike the 17 Oct change, though it is one run and
the noise estimate comes from two. Against the 17 Oct run 9 questions turned right and 3 turned wrong. The gains are
mostly ratio, margin and "is this metric meaningful" questions of the kinds the changes target (for example American
Express's gross margin, now answered with the fallback); I did not trace each one. The losses are two American Express
narrative questions that fluctuate between runs (ids 01028 and 01981; they were right on 17 Oct and wrong on 13 and 16 Oct)
and one XBRL net-income change (MGM), which I did not investigate.

Costs and caveats:

- **Groundedness fell** (94.6% against 96.3–98.2%) and the share of answers the verifier fully confirms fell (91.8% against
  94.4–97.8%). Eleven answers are newly flagged, and 8 of those 11 are correct: the checker is strict about how a
  figure is written in a table, and more questions are now answered rather than refused, so more claims are exposed to
  it. "Verified" still means internally consistent and grounded in the cited text, not correct.
- **The fallback rule can overreach.** On dev, PepsiCo's restructuring costs (a note, not an income-statement line, gold
  $411 million) were answered "not outlined, so 0" and got worse; the AES question it fixed has the opposite answer.
- **Latency rose**: p50 1.8 s against 1.0 s, p95 6.3 s against 2.6 s, with 13.8% of answers regenerated (10.6% before).
  I did not look into how much of that is the model's speed on the day.
- **The test split was not untouched.** I had read test-split failures earlier in the project (the "What failed" section
  below comes from them), and the dev split is small (31 FinanceBench questions). The specific fixes above came from
  dev failures, but the test number is a little optimistic for that reason. A fresh repeat on another day would say how much.

**How Ledger got here** (same 217 questions; the first run predates a corrected General Mills answer
key, which moves three questions):

| Run | Change | Overall | FinanceBench | XBRL | p50 latency |
|---|---|---|---|---|---|
| [10 Oct](eval/results/20261010T071950-ledger-test.json) | first full run: hybrid search + reranker | 70.0% | 57.6% | 78.7% | 16.0 s |
| [11 Oct](eval/results/20261011T154339-ledger-test.json) | + net-income prompt, answer-key fix, JnJ alias, year fallback; vector search, no reranker | 68.1% | 52.9% | 78.7% | 0.9 s |
| [12 Oct](eval/results/20261012T071411-ledger-test.json) | + statement pinning for named line items (cash, R&D, debt...) | 76.3% | 56.5% | 90.2% | 0.9 s |
| [13 Oct](eval/results/20261013T073749-ledger-test.json) | + J&J fiscal-year label, investment-advice refusal, citation parsing, net-income line | 78.7% | 56.5% | 94.3% | 0.9 s |
| [24 Oct](eval/results/20261023T232507-ledger-test-v2.json) | + narrative retrieval (17 Oct, no net change), answer form, arithmetic repair, stated fallbacks, JSON retry | 80.7% | 63.5% | 92.6% | 1.8 s |

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
the code of 13 Oct; the first three rows were re-run on 16 Oct after "capital-intensive" and "dividends
paid" questions started pinning the statements they need, and the three chunking rows (no statement tags, so
unaffected by pinning) ran earlier. Compare the first three rows with each other, and the rest with the
`vector, all questions` row of 13 Oct (74.1%).

| Run | What changes | FinanceBench recall | XBRL recall | p50 retrieval |
|---|---|---|---|---|
| **default** | table chunks, vector search; questions needing no statement (acquisitions, customers, legal) use keyword fusion and 10 passages | **80.0%** | 64.8% | **0.06 s** |
| narrative-rerank | the same, but those questions are reranked (8 passages) | 78.8% | 64.8% | 0.06 s median (the reranker runs only for those questions, so its tail is slower) |
| vector, all questions | the same without the narrative settings | 76.5% | 64.8% | 0.07 s |
| vector, 13 Oct | the earlier default, before the new pinning wording | 74.1% | 64.8% | 0.06 s |
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
  FinanceBench recall than embeddings alone once the statements are pinned. It does help the questions
  that need no statement: for those, [19 failed narrative questions](eval/results/20261016T134937-diagnose.md)
  went from 0 to 2 findable with keyword fusion and 10 passages (3 with a reranker), and over the whole test
  split that setting adds 3.5 points of FinanceBench recall (76.5% to 80.0%) without touching XBRL. Most
  narrative evidence is still missed: the passages are in the index, but the small embedding model ranks
  generic text above them.

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

## Running the demo

A public demo that costs nothing: a free Hugging Face Docker Space (CPU) serving the
Streamlit UI, with the free Gemini tier answering. Step by step, with every click, in
[docs/deploy-demo.md](docs/deploy-demo.md); in short:

1. Run the **build-demo-index** workflow (Actions tab). It indexes the filings and attaches
   `demo-index.tar.gz` to a release named `demo-index`.
2. Create a free Docker Space and push the three files in [`deploy/hf-space/`](deploy/hf-space).
3. In the Space's *Variables and secrets*: secret `GEMINI_API_KEY`, variable
   `LEDGER_INDEX_URL` (the release asset URL). Optional: `LANGFUSE_PUBLIC_KEY` and
   `LANGFUSE_SECRET_KEY` from the free Langfuse Cloud Hobby tier.

Keep billing disabled everywhere, and keys only in those secret settings. To protect the free
quota the API answers at most `LEDGER_DAILY_BUDGET` questions a day (default 300) and
`LEDGER_PER_CLIENT_DAILY` per visitor (default 15); after that it returns HTTP 429 and the UI
says the free daily quota is used up and when it resets (midnight Pacific, 07:00 UTC). Cache
hits and investment-advice refusals are not counted. Tracing always goes to a local file
(`data/traces/requests.jsonl`, shown on the UI's Dashboard tab); Langfuse is added on top when
its keys are set, and is skipped without them.

Expect a free-CPU cold start of a few minutes after the Space has slept, a hard daily cap, and
answers that are not investment advice.

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
  api/         main.py (API-1/2, COST-3), budget.py (daily free-tier quota)
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
