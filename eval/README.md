# Evaluation

Evaluation is the centre of Ledger: every design choice is an experiment against a fixed golden
set and a plain baseline.

## Golden set (`golden/`)

| File | Size | Source | Build |
|---|---|---|---|
| `financebench.jsonl` | 150 | FinanceBench open set (CC BY-NC 4.0) | `python scripts/financebench.py` |
| `xbrl.jsonl` | 150 | SEC XBRL company facts, templated | `python scripts/make_xbrl_questions.py` |
| `handwritten.jsonl` | 50 (13 so far) | Written by hand: unanswerable, traps, injection | edit by hand |

The two scripts need internet access to Hugging Face and SEC EDGAR. Run them locally or with the
**build-golden** workflow (Actions tab), which commits the result.

Each item has a fixed `split` (20% `dev`, 80% `test`), decided by hashing its id.
**Tune on `dev`. Never look at `test` results while changing prompts or settings.**

### Still to write by hand (37 more)

Aim for a mix; each needs `answer_type`, and numeric ones a `value` checked against the filing:

- multi-year comparisons ("How did Nike's gross margin change from FY2021 to FY2023?");
- wrong-company traps ("What was Pepsi's revenue in Coca-Cola's FY2022 10-K?" → refuse);
- unit and sign errors (net loss years, figures in thousands);
- more prompt-injection cases (SEC-2).

Answers pulled from user feedback (thumbs down, OBS-4) belong here too.

## Running

```bash
python eval/run_eval.py --split dev                 # tune
python eval/run_eval.py --smoke --gate              # what CI runs on a PR
python eval/run_eval.py --split test --judge        # the reported number
python eval/run_eval.py --system long-context --split test
python eval/run_eval.py --config configs/experiments/fixed-512.yaml --tag chunk-fixed-512
python eval/run_eval.py --oracle-filters            # retrieval with gold company/year given
```

Free tiers limit requests per minute: `--sleep 4` keeps Gemini's free tier happy.

## Metrics

| Metric | Definition |
|---|---|
| `accuracy` | Numeric: any number in the answer within tolerance of gold (scale words and units allowed to differ). Text: LLM judge (`--judge`). Refusing an answerable question scores 0. |
| `refusal_accuracy` | Share of unanswerable questions Ledger refused |
| `false_refusal_rate` | Share of answerable questions Ledger refused |
| `groundedness` | Share of claims the verifier did not flag |
| `recall_at_k`, `mrr` | Whether a retrieved passage contains the gold evidence (token overlap ≥ 50% for FinanceBench; right filing + gold value for XBRL) |
| `latency_p50_ms`, `latency_p95_ms`, `cost_per_question_usd` | Cache misses only; cost at list price |

Results land in `results/<timestamp>-<tag>.json` with the exact config and git commit.
`results/baseline-smoke.json` is the main-branch smoke baseline the PR gate compares against
(refreshed nightly).

## The CI gate

A PR fails when `accuracy`, `groundedness` or `refusal_accuracy` on the smoke set drops more than
2 points below the baseline (CI-2). Leave one deliberately bad PR in history to show the gate
catching it (CI-4): for example, set `rerank: false` and `top_k: 2` and open a PR.

## Judge spot-check

`--judge` grades non-numeric answers with the same free-tier model. Before reporting a judged
number, hand-label 50 judged answers and report the agreement rate (EVAL-1).
