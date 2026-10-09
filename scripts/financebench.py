"""Download the FinanceBench open set (150 questions) and convert it to the golden format.

    python scripts/financebench.py            # writes eval/golden/financebench.jsonl
    python scripts/financebench.py --list     # companies + fiscal years the questions need

Licence: CC BY-NC 4.0. Fine for a portfolio; do not use in paid client work.

FinanceBench also asks about 10-Qs, 8-Ks and earnings releases. Ledger's
corpus is 10-Ks, so those items are tagged ``out-of-corpus`` and reported
separately rather than silently dropped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.evaluation.golden import Evidence, GoldenItem, assign_split, write_golden  # noqa: E402
from ledger.retrieve.filters import CompanyRegistry  # noqa: E402

ROWS_API = "https://datasets-server.huggingface.co/rows"
GITHUB_JSONL = (
    "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/"
    "financebench_open_source.jsonl"
)

_NUM = re.compile(
    r"^[^\d\-($]*(\(?-?\$?[\d,]+(?:\.\d+)?\)?)\s*(%|percent)?\s*"
    r"(?:(thousand|million|billion|trillion)\b)?",
    re.IGNORECASE,
)
_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def fetch_rows() -> list[dict[str, object]]:
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        try:
            rows: list[dict[str, object]] = []
            offset = 0
            while True:
                r = http.get(
                    ROWS_API,
                    params={
                        "dataset": "PatronusAI/financebench",
                        "config": "default",
                        "split": "train",
                        "offset": offset,
                        "length": 100,
                    },
                )
                r.raise_for_status()
                batch = [x["row"] for x in r.json()["rows"]]
                rows += batch
                if len(batch) < 100:
                    return rows
                offset += 100
        except (httpx.HTTPError, KeyError) as e:
            print(f"datasets-server failed ({e}); trying GitHub", file=sys.stderr)
            r = http.get(GITHUB_JSONL)
            r.raise_for_status()
            return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def parse_numeric(answer: str) -> tuple[float | None, str]:
    """Gold value in base units from answers like "$1577.00", "8.5%", "$1.2 billion".

    Only short answers are treated as numeric; anything wordier goes to the judge.
    """
    text = answer.strip()
    if len(text) > 40:
        return None, ""
    m = _NUM.match(text)
    if not m:
        return None, ""
    raw = m.group(1)
    neg = raw.startswith("(") or raw.startswith("-")
    value = float(re.sub(r"[^\d.]", "", raw))
    if m.group(2):
        return (-value if neg else value), "percent"
    value *= _SCALE.get((m.group(3) or "").lower(), 1.0)
    unit = "usd" if "$" in raw else ""
    return (-value if neg else value), unit


def convert(
    rows: list[dict[str, object]], registry: CompanyRegistry
) -> tuple[list[GoldenItem], list[str]]:
    items, unmapped = [], []
    for i, row in enumerate(rows):
        company = str(row.get("company", ""))
        tickers = registry.find(company)
        if not tickers:
            unmapped.append(company)
        doc_type = str(row.get("doc_type", "")).lower()
        try:
            year = int(str(row.get("doc_period", "")))
        except ValueError:
            year = None
        answer = str(row.get("answer", ""))
        value, unit = parse_numeric(answer)
        tags = [str(row.get("question_type", "")).lower().replace(" ", "-")]
        if doc_type and doc_type != "10k":
            tags.append("out-of-corpus")
        if row.get("question_reasoning"):
            tags.append(str(row["question_reasoning"]).lower().replace(" ", "-"))
        evidence = [
            Evidence(
                doc_id=str(e.get("doc_name", "")),
                text=str(e.get("evidence_text", "")),
                page=e.get("evidence_page_num"),
            )  # type: ignore[arg-type]
            for e in row.get("evidence", []) or []  # type: ignore[attr-defined]
            if isinstance(e, dict)
        ]
        fid = str(row.get("financebench_id", f"fb-{i:04d}"))
        items.append(
            GoldenItem(
                id=fid if fid.startswith("financebench") else f"fb-{fid}",
                source="financebench",
                question=str(row["question"]),
                answer=answer,
                answer_type="numeric" if value is not None else "text",
                value=value,
                unit=unit,
                tolerance=0.01,
                ticker=tickers[0] if tickers else "",
                fiscal_year=year,
                evidence=evidence,
                tags=[t for t in tags if t],
                split=assign_split(fid),
            )
        )
    return items, sorted(set(unmapped))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "golden" / "financebench.jsonl")
    args = ap.parse_args()

    registry = CompanyRegistry.from_yaml(ROOT / "configs" / "corpus.yaml")
    rows = fetch_rows()
    items, unmapped = convert(rows, registry)

    need: dict[str, set[int]] = defaultdict(set)
    for it in items:
        if it.ticker and it.fiscal_year and "out-of-corpus" not in it.tags:
            need[it.ticker].add(it.fiscal_year)

    if args.list:
        print(f"{len(rows)} questions, {len(need)} companies with 10-K questions\n")
        for t in sorted(need):
            print(f"  - {t}: years {sorted(need[t])}")
        print(
            "\nOut of corpus (10-Q / 8-K / earnings):",
            sum("out-of-corpus" in i.tags for i in items),
        )
        if unmapped:
            print("\nAdd these to configs/corpus.yaml (no ticker match):", ", ".join(unmapped))
        return

    n = write_golden(args.out, items)
    print(
        f"wrote {n} items to {args.out.relative_to(ROOT)} "
        f"({sum(i.answer_type == 'numeric' for i in items)} numeric, "
        f"{sum('out-of-corpus' in i.tags for i in items)} out of corpus)"
    )
    if unmapped:
        print("Unmapped companies:", ", ".join(unmapped))


if __name__ == "__main__":
    main()
