"""Run Ledger (or the long-context baseline) over the golden set.

    python eval/run_eval.py --split dev                    # tune here
    python eval/run_eval.py --smoke --gate                 # what CI runs on a PR
    python eval/run_eval.py --split test --judge           # the reported number
    python eval/run_eval.py --system long-context --split test
    python eval/run_eval.py --config configs/experiments/fixed-512.yaml --tag fixed-512

Each run writes eval/results/<timestamp>-<tag>.json with the metrics, the
exact config, the git commit and every item, so numbers in the README can
be traced back. Free model tiers cap requests per minute: use --sleep.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.config import LedgerConfig, Settings  # noqa: E402
from ledger.evaluation.gate import check_regression, markdown_summary  # noqa: E402
from ledger.evaluation.golden import GoldenItem, load_golden, smoke_set  # noqa: E402
from ledger.evaluation.metrics import ItemResult, aggregate, aggregate_by, score_item  # noqa: E402
from ledger.retrieve.filters import Filters  # noqa: E402

RESULTS = ROOT / "eval" / "results"
BASELINE = RESULTS / "baseline-smoke.json"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def select(items: list[GoldenItem], args: argparse.Namespace) -> list[GoldenItem]:
    if args.smoke:
        return smoke_set(items, args.smoke_n)
    if args.split != "all":
        items = [i for i in items if i.split == args.split]
    if args.sources:
        items = [i for i in items if i.source in args.sources]
    if not args.include_out_of_corpus:
        items = [i for i in items if "out-of-corpus" not in i.tags]
    return items[: args.limit] if args.limit else items


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--system", choices=["ledger", "long-context"], default="ledger")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--smoke", action="store_true", help="the fixed 50-question CI set")
    p.add_argument("--smoke-n", type=int, default=50)
    p.add_argument("--sources", nargs="*")
    p.add_argument("--limit", type=int)
    p.add_argument("--include-out-of-corpus", action="store_true")
    p.add_argument("--config", type=Path, help="retrieval.yaml override (experiments)")
    p.add_argument("--tag", default="")
    p.add_argument(
        "--oracle-filters",
        action="store_true",
        help="pass the gold company/year as filters instead of extracting them",
    )
    p.add_argument("--judge", action="store_true", help="LLM-judge non-numeric answers")
    p.add_argument("--sleep", type=float, default=0.0, help="seconds between questions")
    p.add_argument("--gate", action="store_true", help="fail on regression vs baseline")
    p.add_argument("--write-baseline", action="store_true")
    p.add_argument(
        "--print-needs",
        action="store_true",
        help="print the TICKER YEAR filings the selected items need, then exit",
    )
    p.add_argument("--summary", type=Path, help="write a markdown summary here (CI)")
    args = p.parse_args()

    settings = Settings()
    config = LedgerConfig.load(args.config) if args.config else LedgerConfig.load()
    config.cache.enabled = False  # each question must be answered from scratch

    items = select(load_golden(), args)
    if not items:
        print("No golden items selected. Build them first (see eval/README.md).")
        return 1
    if args.print_needs:
        for ticker, year in sorted(
            {(i.ticker, i.fiscal_year) for i in items if i.ticker and i.fiscal_year}
        ):
            print(ticker, year)
        return 0

    from ledger.factory import build_ledger, build_llms

    if args.system == "ledger":
        system = build_ledger(settings, config, trace_log=None)
        registry = system.registry
    else:
        from ledger.evaluation.baseline import LongContextBaseline
        from ledger.retrieve.filters import CompanyRegistry

        llm, _ = build_llms(settings)
        corpus = ROOT / "configs" / "corpus.yaml"
        registry = CompanyRegistry.from_yaml(corpus)
        system = LongContextBaseline(llm, ROOT / "data" / "raw", registry)  # type: ignore[assignment]

    judge_llm = build_llms(settings)[0] if args.judge else None
    results: list[ItemResult] = []
    for n, item in enumerate(items, 1):
        # By default Ledger must find company and year in the question itself (RET-2);
        # --oracle-filters measures retrieval with them handed over, as a UI filter would.
        filters = None
        if args.oracle_filters and item.answer_type != "refusal":
            filters = Filters(
                tickers=[item.ticker] if item.ticker else [],
                years=[item.fiscal_year] if item.fiscal_year else [],
            )
        try:
            answer = system.ask(item.question, filters)
            r = score_item(item, answer, config.retrieval.top_k)
            if r.correct is None and judge_llm is not None and not answer.refused:
                from ledger.evaluation.judge import judge

                r.judge = judge(judge_llm, item.question, item.answer, answer.answer)
                r.correct = 1.0 if r.judge["correct"] else 0.0
        except Exception as e:  # keep going; errors are counted, not hidden
            r = ItemResult(
                item.id,
                item.source,
                item.answer_type,
                item.question,
                item.answer,
                "",
                False,
                None,
                None,
                None,
                None,
                0,
                0,
                0,
                0.0,
                False,
                False,
                item.tags,
                error=f"{type(e).__name__}: {e}",
            )
        results.append(r)
        mark = {1.0: "ok ", 0.0: "XX ", None: "?? "}[r.correct] if not r.error else "ERR"
        print(f"[{n}/{len(items)}] {mark} {item.id}  {r.latency_ms}ms  {r.answer[:80]!r}")
        if args.sleep:
            time.sleep(args.sleep)

    metrics = aggregate(results)
    tag = args.tag or ("smoke" if args.smoke else f"{args.system}-{args.split}")
    out = {
        "run": tag,
        "system": args.system,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "config": config.model_dump(),
        "metrics": metrics,
        "by_source": aggregate_by(results, "source"),
        "items": [asdict(r) for r in results],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{tag}.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(metrics, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")

    if args.write_baseline:
        BASELINE.write_text(json.dumps(metrics, indent=2))
        print(f"updated {BASELINE.relative_to(ROOT)}")

    failures: list[str] = []
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    if args.gate and baseline:
        failures = check_regression(metrics, baseline)
    if args.summary:
        args.summary.write_text(markdown_summary(metrics, baseline, failures))
    for f in failures:
        print(f"REGRESSION: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
