"""How much does the same code score from one run to the next?

    python eval/noise_report.py    # complete ledger-test runs with the newest code hash

The free Gemini tier is not deterministic, so two runs of identical code answer some questions
differently. This reads the complete test runs saved under ``eval/results/`` (the plain
``ledger-test`` run and any ``ledger-test-repeatN`` repeats) that share one code hash, and reports,
per metric, the spread between runs and how many questions flipped between right and wrong.
Writes eval/results/noise.md.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
OUT = RESULTS / "noise.md"


def load_runs() -> list[tuple[Path, dict]]:
    runs = []
    for f in sorted(RESULTS.glob("*-ledger-test*.json")):
        if f.name.endswith("-ledger-test.json") or "-ledger-test-repeat" in f.name:
            d = json.loads(f.read_text())
            if not d.get("partial") and d["metrics"]["n"] == len(d["items"]):
                runs.append((f, d))
    if not runs:
        return []
    newest = max(runs, key=lambda r: r[1]["timestamp"])[1]["code_hash"]
    return [r for r in runs if r[1]["code_hash"] == newest]


def accuracy(items: list[dict], source: str | None) -> float:
    scored = [
        i
        for i in items
        if i["source"] != "handwritten"
        and i["correct"] is not None
        and (source is None or i["source"] == source)
    ]
    return sum(i["correct"] for i in scored) / len(scored)


def groundedness(items: list[dict]) -> float:
    claims = sum(i["claims"] for i in items)
    return sum(i["grounded_claims"] for i in items) / claims if claims else 0.0


def main() -> int:
    runs = load_runs()
    if len(runs) < 2:
        print(f"need at least two complete runs of the same code, found {len(runs)}")
        return 1
    metrics = {
        "Overall accuracy": lambda it: accuracy(it, None),
        "FinanceBench accuracy": lambda it: accuracy(it, "financebench"),
        "XBRL accuracy": lambda it: accuracy(it, "xbrl"),
        "Groundedness": groundedness,
    }
    lines = [
        "# Run-to-run noise (same code, same questions)",
        "",
        f"Runs compared: {len(runs)}, all with code hash `{runs[0][1]['code_hash']}`.",
        "",
        "| Run | file |",
        "|---|---|",
        *[f"| {n} | `{p.name}` |" for n, (p, _) in enumerate(runs, 1)],
        "",
        "| Metric | "
        + " | ".join(f"run {n}" for n in range(1, len(runs) + 1))
        + " | range | std dev |",
        "|---|" + "---|" * (len(runs) + 2),
    ]
    for name, fn in metrics.items():
        vals = [fn(d["items"]) * 100 for _, d in runs]
        lines.append(
            f"| {name} | "
            + " | ".join(f"{v:.1f}%" for v in vals)
            + f" | {max(vals) - min(vals):.1f} pts | {statistics.pstdev(vals):.2f} |"
        )
    by_id = [{i["id"]: i for i in d["items"]} for _, d in runs]
    flips = []
    for qid in by_id[0]:
        got = [r[qid]["correct"] for r in by_id if qid in r and r[qid]["correct"] is not None]
        if len(got) == len(runs) and len(set(got)) > 1:
            flips.append((qid, got, by_id[0][qid]["source"]))
    scored = sum(1 for qid in by_id[0] if all(r[qid]["correct"] is not None for r in by_id))
    lines += [
        "",
        f"Questions whose result changed between runs: **{len(flips)} of {scored}** "
        f"({100 * len(flips) / scored:.1f}%).",
        "",
        "| Question | results per run (1 = right) | source |",
        "|---|---|---|",
        *[f"| `{q}` | {' '.join(str(g) for g in got)} | {s} |" for q, got, s in flips],
        "",
        "A change between two systems smaller than the range above is inside the noise of the free "
        "tier and should not be read as an improvement or a regression.",
    ]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:14]))
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
