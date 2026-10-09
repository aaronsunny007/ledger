"""Number parsing shared by the verifier and the eval.

Ported from Financial-NRF ``framework/nrf.py`` (``ParsedNumber``,
``extract_numbers``, ``extract_final_answer``) with two additions that
annual reports need and FinQA did not:

* accounting negatives written in parentheses, ``(1,234)``;
* scale words after a number (``$1.2 billion``, ``£450m``), so a claim
  in billions can be grounded against a table reported in millions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Kept in sync with Financial-NRF: no whitespace between a sign and its
# digits, so the "-" in "5829 - 5735" stays an operator.
_NUMBER_TOKEN_RE = re.compile(r"[-+]?[$£€]?\d+(?:,\d{3})*(?:\.\d+)?%?")

# A number with optional accounting parentheses and an optional scale word.
_AMOUNT_RE = re.compile(
    r"(?P<open>\()?(?P<sign>[-+])?(?P<cur>[$£€])?\s?"
    r"(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?P<close>\))?"
    r"(?P<pct>\s?%)?"
    r"(?:\s?(?P<scale>trillion|billion|million|thousand|bn|tn|m|k)\b)?",
    re.IGNORECASE,
)

_SCALES = {
    "thousand": 1e3,
    "k": 1e3,
    "million": 1e6,
    "m": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "trillion": 1e12,
    "tn": 1e12,
}

_FINAL_ANSWER_LINE_RE = re.compile(
    r"final\s*answer\s*[:\-]\s*(.*?)(?:\n|$|confidence\s*[:\-]|reasoning\s*[:\-])",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ParsedNumber:
    raw_text: str
    value: float
    is_percentage: bool = False
    # Value after applying a scale word ("1.2 billion" -> 1.2e9). Equal to
    # ``value`` when no scale word was present.
    scaled_value: float | None = None
    # Half a unit of the last stated digit: "383 billion" -> 0.5e9. Used so
    # display rounding is not mistaken for a wrong number.
    precision: float = 0.0

    @property
    def magnitude(self) -> float:
        return self.scaled_value if self.scaled_value is not None else self.value


def _half_unit(num_text: str) -> float:
    if "." in num_text:
        decimals = len(num_text.split(".", 1)[1])
        return 0.5 * 10.0 ** (-decimals)
    return 0.5


def parse_number_token(token: str) -> ParsedNumber | None:
    """Parse one token such as ``$94``, ``32.5%`` or ``1,234.5``."""
    raw = token.strip()
    if not raw:
        return None
    is_percentage = raw.endswith("%")
    cleaned = re.sub(r"[$£€,%]", "", raw).strip()
    if cleaned in ("", "-", "+", "."):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return ParsedNumber(
        raw_text=raw,
        value=value,
        is_percentage=is_percentage,
        precision=_half_unit(cleaned.lstrip("+-")),
    )


def extract_numbers(text: str) -> list[ParsedNumber]:
    """All plain numeric tokens in ``text`` (Financial-NRF behaviour)."""
    if not text:
        return []
    out = []
    for match in _NUMBER_TOKEN_RE.finditer(str(text)):
        parsed = parse_number_token(match.group(0))
        if parsed is not None:
            out.append(parsed)
    return out


def extract_amounts(text: str) -> list[ParsedNumber]:
    """Numbers with accounting negatives and scale words understood."""
    if not text:
        return []
    out = []
    for m in _AMOUNT_RE.finditer(text):
        num = m.group("num")
        value = float(num.replace(",", ""))
        negative = m.group("sign") == "-" or bool(m.group("open") and m.group("close"))
        if negative:
            value = -value
        scale_word = (m.group("scale") or "").lower()
        scale = _SCALES.get(scale_word, 1.0)
        # A bare "m" or "k" right after a number is only a scale when a
        # currency marks the number as money; "10 m" could be metres.
        if scale_word in ("m", "k") and not m.group("cur"):
            scale = 1.0
        is_pct = bool(m.group("pct"))
        precision = _half_unit(num) * scale
        out.append(
            ParsedNumber(
                raw_text=m.group(0).strip(),
                value=value,
                is_percentage=is_pct,
                scaled_value=value * scale,
                precision=precision,
            )
        )
    return out


def extract_final_answer(response: str) -> ParsedNumber | None:
    """The last number on the ``Final Answer:`` line, never the confidence.

    Ported unchanged from Financial-NRF: no fallback to scanning the whole
    response, because that is what once mistook "Confidence: 1" for the
    answer.
    """
    if not response:
        return None
    match = _FINAL_ANSWER_LINE_RE.search(response)
    if not match:
        return None
    numbers = extract_numbers(match.group(1))
    return numbers[-1] if numbers else None


def is_probably_year(n: ParsedNumber) -> bool:
    """Fiscal years in claim text ("FY2024") are labels, not quantities."""
    return (
        not n.is_percentage
        and n.scaled_value == n.value
        and n.value.is_integer()
        and 1900 <= n.value <= 2100
        and "," not in n.raw_text
        and not any(c in n.raw_text for c in "$£€")
    )
