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


def missing_year_note(
    docs: list[dict[str, object]],
    ticker: str,
    years: list[int],
    name: str,
    year_naming: str = "end",
) -> str | None:
    """Say what is loaded for ``ticker`` when none of the asked-for ``years`` is, or ``None``.

    Names the years that are loaded and, for a company that names its fiscal year by the year it
    begins in (Home Depot: the year ending January 2023 is its "fiscal 2022"), how that appears.
    """
    have = sorted(
        {
            fy
            for d in docs
            if d.get("ticker") == ticker and isinstance(fy := d.get("fiscal_year"), int)
        }
    )
    if not have or not years or any(y in have for y in years):
        return None
    asked = ", ".join(str(y) for y in years)
    note = f"I have {name} filings for {', '.join(str(y) for y in have)}, but none for {asked}."
    if year_naming == "start":
        note += (
            f" Ledger labels a filing by the calendar year its period ends in, and {name} names its"
            " fiscal year by the year it begins in, so the year ending in January "
            f"{have[-1]} (the company's fiscal {have[-1] - 1}) is labelled {have[-1]}."
        )
    return note
