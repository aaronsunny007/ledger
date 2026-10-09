"""Generate numeric questions whose answers come from SEC XBRL company facts.

    python scripts/make_xbrl_questions.py --n 150

The gold value is what the company itself tagged in its 10-K, so it is not
our judgement. Templates cover single values (revenue, net income), growth
rates and margins, the arithmetic FinanceBench says most questions need.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.config import Settings  # noqa: E402
from ledger.evaluation.golden import GoldenItem, assign_split, write_golden  # noqa: E402
from ledger.ingest.edgar import EdgarClient  # noqa: E402

# Concept fallbacks: companies tag revenue under different names.
CONCEPTS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "net income": ["NetIncomeLoss", "ProfitLoss"],
    "operating income": ["OperatingIncomeLoss"],
    "gross profit": ["GrossProfit"],
    "research and development expense": ["ResearchAndDevelopmentExpense"],
    "total assets": ["Assets"],
    "cash and cash equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
}
INSTANT = {"total assets", "cash and cash equivalents"}  # balance-sheet values


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def annual_values(facts: dict[str, Any], metric: str) -> dict[int, float]:
    """fiscal year (year the period ends) -> value, from 10-K filings only."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in CONCEPTS[metric]:
        units = gaap.get(concept, {}).get("units", {}).get("USD")
        if not units:
            continue
        out: dict[int, float] = {}
        for f in units:
            if f.get("form") != "10-K" or f.get("fp") != "FY":
                continue
            if metric not in INSTANT and (
                "start" not in f or not 350 <= _days(f["start"], f["end"]) <= 380
            ):
                continue
            year = int(f["end"][:4])
            # The first filing to report a year is the original, not a restatement.
            out.setdefault(year, float(f["val"]))
        if out:
            return out
    return {}


def make_items(
    ticker: str, company: str, facts: dict[str, Any], years: list[int]
) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    vals = {m: annual_values(facts, m) for m in CONCEPTS}

    def add(kind: str, year: int, q: str, value: float, unit: str, tags: list[str]) -> None:
        iid = f"xbrl-{ticker}-{year}-{kind}"
        items.append(
            GoldenItem(
                id=iid,
                source="xbrl",
                question=q,
                answer=f"{value:,.2f}" + ("%" if unit == "percent" else ""),
                answer_type="numeric",
                value=value,
                unit=unit,
                tolerance=0.005,
                ticker=ticker,
                fiscal_year=year,
                tags=tags,
                split=assign_split(iid),
            )
        )

    for y in years:
        for metric in (
            "revenue",
            "net income",
            "operating income",
            "research and development expense",
            "total assets",
            "cash and cash equivalents",
        ):
            v = vals[metric].get(y)
            if v is not None:
                when = (
                    f"at the end of fiscal year {y}" if metric in INSTANT else f"in fiscal year {y}"
                )
                add(
                    metric.replace(" ", "_"),
                    y,
                    f"What was {company}'s {metric} {when}?",
                    v,
                    "usd",
                    ["lookup"],
                )
        rev, prev = vals["revenue"].get(y), vals["revenue"].get(y - 1)
        if rev and prev:
            add(
                "revenue_growth",
                y,
                f"By what percentage did {company}'s revenue change from fiscal year {y - 1} "
                f"to fiscal year {y}?",
                (rev - prev) / prev * 100,
                "percent",
                ["needs-arithmetic"],
            )
        for metric, kind in (
            ("operating income", "operating_margin"),
            ("gross profit", "gross_margin"),
        ):
            v = vals[metric].get(y)
            if v is not None and rev:
                name = kind.replace("_", " ")
                add(
                    kind,
                    y,
                    f"What was {company}'s {name} in fiscal year {y}, as a percentage of revenue?",
                    v / rev * 100,
                    "percent",
                    ["needs-arithmetic"],
                )
        ni, ni_prev = vals["net income"].get(y), vals["net income"].get(y - 1)
        if ni is not None and ni_prev:
            add(
                "net_income_change",
                y,
                f"How much did {company}'s net income change in dollars from fiscal year {y - 1} "
                f"to fiscal year {y}?",
                ni - ni_prev,
                "usd",
                ["needs-arithmetic"],
            )
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "golden" / "xbrl.jsonl")
    args = ap.parse_args()

    corpus = yaml.safe_load((ROOT / "configs" / "corpus.yaml").read_text())
    client = EdgarClient(Settings().sec_user_agent)
    pool: list[GoldenItem] = []
    for c in corpus["companies"]:
        years = c.get("years") or corpus["years"]
        try:
            facts = client.company_facts(c["ticker"])
        except Exception as e:
            print(f"skip {c['ticker']}: {e}", file=sys.stderr)
            continue
        pool += make_items(c["ticker"], c["name"], facts, years)

    # Half lookups, half arithmetic, spread across companies.
    rng = random.Random(args.seed)
    rng.shuffle(pool)
    arith = [i for i in pool if "needs-arithmetic" in i.tags]
    look = [i for i in pool if "needs-arithmetic" not in i.tags]
    chosen = arith[: args.n // 2] + look[: args.n - min(len(arith), args.n // 2)]
    chosen.sort(key=lambda i: i.id)
    n = write_golden(args.out, chosen)
    print(f"wrote {n} XBRL questions to {args.out.relative_to(ROOT)} (pool {len(pool)})")


if __name__ == "__main__":
    main()
