"""Retrieval-only experiment: no LLM, so it is free and runs on any question.

    python eval/retrieval_eval.py --config configs/experiments/vector-only.yaml --tag vector-only

For every answerable golden question it runs the production retrieval path
(filters extracted from the question, the config's search mode, reranker and
statement pinning) and checks whether the passages handed to the model hold
the gold evidence: FinanceBench evidence text, or for XBRL questions the
right filing stating the gold value. Writes eval/results/retrieval/<tag>.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.config import LedgerConfig, Settings  # noqa: E402
from ledger.evaluation.golden import GoldenItem, load_golden  # noqa: E402
from ledger.evaluation.metrics import evidence_hit, percentile  # noqa: E402
from ledger.retrieve.filters import filters_from_question  # noqa: E402

OUT = ROOT / "eval" / "results" / "retrieval"


def eligible(item: GoldenItem, sources: list[str], split: str) -> bool:
    return (
        item.source in sources
        and (split == "all" or item.split == split)
        and item.answer_type != "refusal"
        and "out-of-corpus" not in item.tags
        and bool(item.ticker and item.fiscal_year)
        and (any(e.text for e in item.evidence) or item.value is not None)
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "recall": round(sum(r["hit"] for r in rows) / n, 4),
        "mrr": round(sum(r["rr"] for r in rows) / n, 4),
        "filters_ok": round(sum(r["filters_ok"] for r in rows) / n, 4),
        "passages_avg": round(sum(r["passages"] for r in rows) / n, 2),
        "context_chars_avg": round(sum(r["chars"] for r in rows) / n),
        "latency_p50_ms": percentile([r["ms"] for r in rows], 0.5),
        "latency_p95_ms": percentile([r["ms"] for r in rows], 0.95),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=ROOT / "configs" / "retrieval.yaml")
    p.add_argument("--tag", required=True)
    p.add_argument("--split", default="all", choices=["dev", "test", "all"])
    p.add_argument("--sources", nargs="*", default=["financebench", "xbrl"])
    p.add_argument("--limit", type=int)
    args = p.parse_args()

    from ledger.answer.llm import FakeLLM
    from ledger.factory import build_ledger

    config = LedgerConfig.load(args.config)
    ledger = build_ledger(Settings(), config, llm=FakeLLM(lambda s, u: "{}"), trace_log=None)
    if ledger.retriever.index.count() == 0:
        print(
            f"Index for {config.index_name()} is empty: run `ledger ingest --config {args.config}`"
        )
        return 1

    items = [i for i in load_golden() if eligible(i, args.sources, args.split)][: args.limit]
    rows = []
    for n, item in enumerate(items, 1):
        f = filters_from_question(item.question, ledger.registry)
        t0 = time.monotonic()
        passages = ledger.retriever.retrieve(item.question, f)
        ms = (time.monotonic() - t0) * 1000
        rank = next((r for r, p in enumerate(passages, 1) if evidence_hit(p.chunk, item)), None)
        rows.append(
            {
                "id": item.id,
                "source": item.source,
                "split": item.split,
                "filters_ok": item.ticker in f.tickers
                and (not f.years or item.fiscal_year in f.years),
                "hit": rank is not None,
                "rr": 1 / rank if rank else 0.0,
                "rank": rank,
                "passages": len(passages),
                "chars": sum(len(p.chunk.text) for p in passages),
                "pinned": sum(1 for p in passages if "pinned" in p.ranks),
                "ms": round(ms, 1),
            }
        )
        if n % 25 == 0:
            print(f"[{n}/{len(items)}] recall so far {sum(r['hit'] for r in rows) / n:.3f}")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[f"{r['source']}/{r['split']}"].append(r)
        groups[r["source"]].append(r)
        groups[r["split"]].append(r)
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    out = {
        "tag": args.tag,
        "config_file": str(args.config),
        "config": config.model_dump(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": sha,
        "overall": summarize(rows),
        "groups": {k: summarize(v) for k, v in sorted(groups.items())},
        "items": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.tag}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out["overall"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
