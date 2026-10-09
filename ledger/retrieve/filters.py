"""RET-2: metadata filters, and pulling company and year out of the question.

Filters are applied *before* ranking, so a question about Apple can never be
answered from a Microsoft passage that happened to score well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ledger.types import Chunk


@dataclass
class Filters:
    tickers: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)

    def matches(self, c: Chunk) -> bool:
        if self.tickers and c.ticker not in self.tickers:
            return False
        if self.years and c.fiscal_year not in self.years:
            return False
        return not (self.sections and not any(s in c.section for s in self.sections))

    def is_empty(self) -> bool:
        return not (self.tickers or self.years or self.sections)

    def key(self) -> str:
        return f"{','.join(sorted(self.tickers))}|{','.join(map(str, sorted(self.years)))}"


@dataclass
class Company:
    ticker: str
    name: str
    aliases: list[str] = field(default_factory=list)


class CompanyRegistry:
    def __init__(self, companies: list[Company]):
        self.companies = companies
        self._by_ticker = {c.ticker.upper(): c for c in companies}
        patterns = []
        for c in companies:
            for alias in {c.name, *c.aliases}:
                patterns.append((re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), c.ticker))
            # Tickers only match in capitals, so "MO" and "ALL" don't fire on prose.
            patterns.append((re.compile(rf"\b{re.escape(c.ticker)}\b"), c.ticker))
        self._patterns = patterns

    @classmethod
    def from_yaml(cls, path: Path) -> CompanyRegistry:
        data = yaml.safe_load(path.read_text()) or {}
        return cls(
            [
                Company(ticker=row["ticker"], name=row["name"], aliases=row.get("aliases", []))
                for row in data.get("companies", [])
            ]
        )

    def get(self, ticker: str) -> Company | None:
        return self._by_ticker.get(ticker.upper())

    def find(self, text: str) -> list[str]:
        found: dict[str, None] = {}
        for pattern, ticker in self._patterns:
            if pattern.search(text):
                found.setdefault(ticker, None)
        return list(found)


_YEAR_RES = [
    re.compile(r"\bFY\s?'?(\d{4})\b", re.IGNORECASE),
    re.compile(r"\bFY\s?'?(\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?:fiscal|financial)\s+(?:year\s+)?(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b((?:19|20)\d{2})\b"),
]


def extract_years(text: str) -> list[int]:
    years: dict[int, None] = {}
    for pattern in _YEAR_RES:
        for m in pattern.finditer(text):
            y = int(m.group(1))
            if y < 100:
                y += 2000
            if 1990 <= y <= 2100:
                years.setdefault(y, None)
    return sorted(years)


def filters_from_question(
    question: str, registry: CompanyRegistry | None, given: Filters | None = None
) -> Filters:
    """User-supplied filters win; otherwise extract them from the question."""
    given = given or Filters()
    tickers = given.tickers or (registry.find(question) if registry else [])
    years = given.years or extract_years(question)
    return Filters(tickers=list(tickers), years=list(years), sections=list(given.sections))
