"""What is loaded, in words a visitor can read: one line per company with its years."""

from __future__ import annotations

from collections import defaultdict


def coverage_lines(docs: list[dict[str, object]]) -> list[str]:
    """``["Apple Inc. (AAPL): 2021, 2022, 2023", ...]`` sorted by company name."""
    names: dict[str, str] = {}
    years: dict[str, set[int]] = defaultdict(set)
    for d in docs:
        ticker = str(d.get("ticker") or "")
        if not ticker:
            continue
        names.setdefault(ticker, str(d.get("company") or ticker))
        year = d.get("fiscal_year")
        if isinstance(year, int):
            years[ticker].add(year)
    return [
        f"{names[t]} ({t}): " + (", ".join(str(y) for y in sorted(years[t])) or "no year")
        for t in sorted(names, key=lambda t: names[t].lower())
    ]
