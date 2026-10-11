"""Run Ledger (or the long-context baseline) over the golden set.

    python eval/run_eval.py --split dev                    # tune here
    python eval/run_eval.py --smoke --gate                 # what CI runs on a PR
    python eval/run_eval.py --split test --judge           # the reported number
    python eval/run_eval.py --system long-context --split test
    python eval/run_eval.py --config configs/experiments/fixed-512.yaml --tag fixed-512

Each run writes eval/results/<timestamp>-<tag>.json with the metrics, the
exact config, the git commit and every item, so numbers in the README can
be traced back. Free model tiers cap requests per minute: use --sleep.
When a daily free-tier quota runs out, the run stops and is saved as
partial; --resume continues the latest partial run with the same --tag the
next day, so the full test split fits the free tier over a few days.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.answer.llm import QuotaExhausted  # noqa: E402
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


def code_hash() -> str:
    """Hash of everything that decides an answer: code, prompts, configs, golden set.

    Results commits change the git sha daily, so resuming checks this instead.
    """
    h = hashlib.sha256()
    for pattern in ("ledger/**/*.py", "ledger/**/*.md", "configs/**/*.yaml", "eval/golden/*"):
        for f in sorted(ROOT.glob(pattern)):
            h.update(str(f.relative_to(ROOT)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def latest_partial(tag: str) -> Path | None:
    """The newest saved run with this tag, if it stopped before the end."""
    runs = sorted(RESULTS.glob(f"*-{tag}.json"))
    if not runs:
        return None
    last = runs[-1]
    return last if json.loads(last.read_text()).get("partial") else None


def rescore(path: Path) -> int:
    """Re-score a saved run with the current metrics, without asking the model again."""
    from ledger.evaluation.metrics import numeric_match

    run = json.loads(path.read_text())
    gold = {i.id: i for i in load_golden()}
    items = []
    for raw in run["items"]:
        r = ItemResult(**raw)
        g = gold.get(r.id)
        if g and r.error is None and g.answer_type == "numeric" and g.value is not None:
            r.correct = (
                0.0
                if r.refused
                else float(
                    numeric_match(r.answer, g.value, g.tolerance, percent=g.unit == "percent")
                )
            )
        items.append(r)
    run["metrics"] = aggregate(items)
    run["by_source"] = aggregate_by(items, "source")
    run["items"] = [asdict(r) for r in items]
    run["rescored_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    path.write_text(json.dumps(run, indent=2))
    print(json.dumps(run["metrics"], indent=2))
    return 0


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
    p.add_argument("--rescore", type=Path, help="re-score a saved result JSON and exit")
    p.add_argument(
        "--resume",
        action="store_true",
        help="continue the latest partial run with this --tag (no-op when there is none)",
    )
    args = p.parse_args()
    if args.rescore:
        return rescore(args.rescore)

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

    tag = args.tag or ("smoke" if args.smoke else f"{args.system}-{args.split}")
    done: dict[str, ItemResult] = {}
    path = RESULTS / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{tag}.json"
    if args.resume:
        prev = latest_partial(tag)
        if prev is not None and json.loads(prev.read_text()).get("code_hash") != code_hash():
            # Never mix answers from two versions of the system in one number.
            print(f"not resuming {prev.relative_to(ROOT)}: the code changed; starting over")
            prev = None
        if prev is not None:
            # Keep finished items; re-ask the ones that errored or were not reached.
            done = {
                r["id"]: ItemResult(**r)
                for r in json.loads(prev.read_text())["items"]
                if r.get("error") is None
            }
            path = prev
            print(f"resuming {prev.relative_to(ROOT)}: {len(done)} of {len(items)} done")

    judge_llm = build_llms(settings)[0] if args.judge else None
    fresh: dict[str, ItemResult] = {}

    def save(partial: bool) -> tuple[dict[str, object], int]:
        answered = {**done, **fresh}
        results = [answered[i.id] for i in items if i.id in answered]
        metrics = aggregate(results)
        remaining = len(items) - len(results)
        out = {
            "run": tag,
            "system": args.system,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_sha": _git_sha(),
            "code_hash": code_hash(),
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "config": config.model_dump(),
            "metrics": metrics,
            "by_source": aggregate_by(results, "source"),
            "partial": partial,
            "remaining": remaining,
            "items": [asdict(r) for r in results],
        }
        RESULTS.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2))
        return metrics, remaining

    partial = False
    todo = [i for i in items if i.id not in done]
    for n, item in enumerate(todo, 1):
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
        except QuotaExhausted as e:
            # Daily quota: every further call would fail the same way. Save
            # what we have; --resume picks up from here.
            print(f"[{n}/{len(todo)}] STOP {item.id}  {e}", flush=True)
            partial = True
            break
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
        fresh[item.id] = r
        mark = {1.0: "ok ", 0.0: "XX ", None: "?? "}[r.correct] if not r.error else "ERR"
        detail = r.error or (f"REFUSED ({r.refusal_reason})" if r.refused else repr(r.answer[:80]))
        print(f"[{n}/{len(todo)}] {mark} {item.id}  {r.latency_ms}ms  {detail}", flush=True)
        if n % 10 == 0:
            save(partial=True)  # a killed or timed-out run can still --resume
        if args.sleep:
            time.sleep(args.sleep)

    metrics, remaining = save(partial)
    print(json.dumps(metrics, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")
    if partial:
        print(f"PARTIAL: daily quota reached, {remaining} questions left; rerun with --resume")

    if args.write_baseline and (partial or metrics.get("errors")):
        print("not updating the baseline: the run was partial or had errors")
    elif args.write_baseline:
        BASELINE.write_text(json.dumps(metrics, indent=2))
        print(f"updated {BASELINE.relative_to(ROOT)}")

    failures: list[str] = []
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    if args.gate and baseline and partial:
        # A few questions before the quota ran out prove nothing either way.
        print(
            f"::warning::Regression gate not evaluated: the daily LLM quota ran out with "
            f"{remaining} of {len(items)} questions left."
        )
    elif args.gate and baseline:
        failures = check_regression(metrics, baseline)
    if args.summary:
        note = (
            f"\n\n**Partial run:** the daily free-tier quota ran out with {remaining} of "
            f"{len(items)} questions left; it continues with `--resume`.\n"
            if partial
            else ""
        )
        args.summary.write_text(markdown_summary(metrics, baseline, failures) + note)
    for f in failures:
        print(f"REGRESSION: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
