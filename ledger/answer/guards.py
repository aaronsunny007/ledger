"""Questions Ledger declines before spending a model call on them."""

from __future__ import annotations

import re

# Personal investment advice: what to buy, sell or hold. Ledger reports what filings say;
# it does not recommend trades. Phrased narrowly so that questions about a company's own
# buybacks, dividends or "should" in a legal sense are not caught.
_ADVICE = [
    re.compile(
        r"\bshould\s+(i|we|you|one|someone|investors?)\s+"
        r"(buy|sell|invest|hold|purchase|short|own|trade|accumulate)\b",
        re.I,
    ),
    re.compile(
        r"\b(is|are)\b[^?.]{0,60}\b(good|great|bad|smart|safe|worthwhile)\s+"
        r"(buy|investment|stock|bet|purchase)\b",
        re.I,
    ),
    re.compile(r"\bworth\s+(buying|investing|owning|holding)\b", re.I),
    re.compile(r"\b(price|share\s+price)\s+target\b", re.I),
    re.compile(r"\b(buy|sell|hold)\s+(rating|recommendation)\b", re.I),
    re.compile(r"\bwhat\s+(stocks?|shares)\s+should\b", re.I),
]

ADVICE_REFUSAL = (
    "Ledger answers questions from company filings and does not give investment advice "
    "(whether to buy, sell or hold a stock)."
)


def is_investment_advice(question: str) -> bool:
    return any(p.search(question) for p in _ADVICE)
