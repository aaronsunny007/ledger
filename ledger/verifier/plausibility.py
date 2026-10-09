"""Is a result the right size for what the question asks?

The week-3 run showed the arithmetic verifier passing answers that were
internally consistent but 100x or 1,000x off: CVS's fixed asset turnover
as 1798.24 instead of 17.98 (multiplied by 100), Adobe's operating cash flow
ratio as 825.77 instead of 0.83 (thousands mixed with millions). Recomputing
the model's own expression cannot catch that. Knowing what kind of number
the question wants can: a turnover ratio of 1,798 is not a turnover ratio.

The ranges are deliberately wide. They exist to catch unit and scale
mistakes, not to judge whether a company's figure is unusual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ledger.verifier.numbers import ParsedNumber, extract_amounts, is_probably_year


@dataclass(frozen=True)
class Kind:
    name: str
    pattern: re.Pattern[str]
    low: float
    high: float
    hint: str
    # Upper bound used instead when the answer is written as a percentage.
    percent_high: float | None = None


# Checked in order; the first kind whose pattern matches the question wins.
KINDS = (
    Kind(
        "days",
        re.compile(r"\bdays?\b|\bDPO\b|\bDSO\b|\bDIO\b|cash\s+conversion\s+cycle", re.I),
        -400,
        1000,
        "a number of days",
    ),
    Kind(
        "per-share amount",
        re.compile(r"per\s+share|\bEPS\b", re.I),
        -1000,
        1000,
        "dollars per share",
    ),
    Kind(
        "ratio",
        re.compile(
            r"ratio|turnover|\btimes\b|coverage|\bROA\b|\bROE\b|return\s+on\s+(assets|equity)",
            re.I,
        ),
        -100,
        100,
        "a ratio (for example 1.5, or 150% if stated as a percentage)",
        percent_high=10_000,
    ),
    Kind(
        "percentage",
        re.compile(r"percent|%|\bmargin\b|growth|\brate\b|\bshare\s+of\b", re.I),
        -1000,
        1000,
        "a percentage",
    ),
)


def expected_kind(question: str) -> Kind | None:
    return next((k for k in KINDS if k.pattern.search(question)), None)


def _stated_value(claim_text: str, result: float | None) -> ParsedNumber | None:
    """The claim's answer: the calculation result, else its last non-year number."""
    nums = [n for n in extract_amounts(claim_text) if not is_probably_year(n)]
    if result is not None:
        pct = any(
            n.is_percentage and abs(n.value - result) <= 0.01 * abs(result) + 1e-9 for n in nums
        )
        return ParsedNumber(raw_text=str(result), value=result, is_percentage=pct)
    return nums[-1] if nums else None


def check_plausible(question: str, claim_text: str, result: float | None) -> str | None:
    """None if fine, else a correction message for the model."""
    kind = expected_kind(question)
    if kind is None:
        return None
    n = _stated_value(claim_text, result)
    if n is None or n.scaled_value not in (None, n.value):
        return None  # "$1.2 billion" is an amount, not the kind of figure checked here
    high = kind.percent_high if (n.is_percentage and kind.percent_high) else kind.high
    low = -high if (n.is_percentage and kind.percent_high) else kind.low
    if low <= n.value <= high:
        return None
    return (
        f"The question asks for {kind.hint}, but the answer is {n.value:g}, which is outside "
        f"the plausible range for a {kind.name} ({low:g} to {high:g}). Check that all figures "
        "use the same units (thousands vs millions) and that you did not multiply by 100 "
        "unless a percentage was asked for."
    )
