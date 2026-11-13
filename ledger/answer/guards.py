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


# A question about which way a figure moved, or by how much. Answering one takes a calculation
# (a difference, a total for each year then the difference); a list of the inputs is not an answer.
_DIRECTION = re.compile(
    r"\b(increas\w*|decreas\w*|grow\w*|grew|declin\w*|rose|fell|rise|drop\w*|higher|lower|"
    r"changed?|differen\w*|up or down|more or less)\b",
    re.I,
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def lists_inputs_without_finishing(
    question: str, claim_texts: list[str], has_calculation: bool
) -> bool:
    """True for a direction or change question answered with figures but no calculation.

    Example: "Has Verizon increased its debt between 2021 and 2022?" answered with each year's
    long-term debt and current debt, and never a total or a difference. Narrow on purpose: the
    question must ask about a change, no claim may carry a calculation, and the claims must hold
    at least four different figures (two periods, two or more items), so a one-line answer that
    quotes the filing's own "revenue grew 8%" is left alone.
    """
    if has_calculation or not _DIRECTION.search(question):
        return False
    figures = {m.group().replace(",", "") for t in claim_texts for m in _NUMBER.finditer(t)}
    return len(figures) >= 4
