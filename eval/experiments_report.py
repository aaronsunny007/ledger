"""Collect eval/results/retrieval/*.json into one markdown table.

python eval/experiments_report.py   # writes eval/results/experiments-retrieval.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results" / "retrieval"
OUT = ROOT / "eval" / "results" / "experiments-retrieval.md"

# Display order and what each run changes from the default.
ORDER = {
    "default": "Default: table chunks, hybrid + rerank, statements pinned",
    "no-pin-statements": "Statement pinning off",
    "hybrid-no-rerank": "Reranker off",
    "rerank-v2-m3": "Reranker bge-reranker-v2-m3 instead of -base",
    "vector-only": "Vector search only",
    "keyword-only": "Keyword (BM25) search only",
    "section": "Section-aware chunks",
    "fixed-1024": "Fixed 1,024-character chunks",
    "fixed-512": "Fixed 512-character chunks",
}


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.1f}%"


def _get(run: dict, group: str, key: str) -> float | None:  # type: ignore[type-arg]
    return run["groups"].get(group, {}).get(key)


def main() -> int:
    runs = {p.stem: json.loads(p.read_text()) for p in sorted(RESULTS.glob("*.json"))}
    if not runs:
        print("no results in", RESULTS)
        return 1
    names = [n for n in ORDER if n in runs] + sorted(set(runs) - set(ORDER))
    lines = [
        "# Retrieval experiments",
        "",
        "Recall = share of questions where the passages given to the model contain the gold "
        "evidence. MRR = mean reciprocal rank of the first such passage. Test split, filters "
        "extracted from the question as in production. No LLM involved.",
        "",
        "| Run | What changes | FinanceBench recall | FinanceBench MRR | XBRL recall | "
        "XBRL MRR | Passages | Context chars | p50 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for n in names:
        r = runs[n]
        lines.append(
            f"| `{n}` | {ORDER.get(n, r.get('config_file', ''))} "
            f"| {_pct(_get(r, 'financebench/test', 'recall'))} "
            f"| {_get(r, 'financebench/test', 'mrr') or 0:.3f} "
            f"| {_pct(_get(r, 'xbrl/test', 'recall'))} "
            f"| {_get(r, 'xbrl/test', 'mrr') or 0:.3f} "
            f"| {_get(r, 'test', 'passages_avg')} | {_get(r, 'test', 'context_chars_avg')} "
            f"| {_get(r, 'test', 'latency_p50_ms')} |"
        )
    n_fb = _get(runs[names[0]], "financebench/test", "n")
    n_x = _get(runs[names[0]], "xbrl/test", "n")
    lines += [
        "",
        f"Questions: {n_fb} FinanceBench (10-K, test split), {n_x} XBRL (test split).",
        f"Commit: `{runs[names[0]]['git_sha']}`.",
    ]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
