"""ANS-1..ANS-4: draft a structured, cited answer from retrieved passages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from ledger.answer.llm import LLM, LLMResult
from ledger.types import ScoredChunk

PROMPTS = Path(__file__).parent / "prompts"


@cache
def system_prompt() -> str:
    # Fixed text, so free-tier prompt caching can reuse it (COST-2).
    return (PROMPTS / "answer_system.md").read_text()


@dataclass
class DraftClaim:
    text: str
    citations: list[int]
    calculation: str | None = None
    result: float | None = None


@dataclass
class Draft:
    answerable: bool
    claims: list[DraftClaim] = field(default_factory=list)
    confidence: str = "low"
    refusal_reason: str | None = None
    parse_error: str | None = None


def format_passages(passages: list[ScoredChunk], max_chars: int) -> str:
    """Number passages [1..n] and wrap each in tags that mark it as data."""
    budget = max_chars
    out = []
    for i, sc in enumerate(passages, start=1):
        c = sc.chunk
        text = c.text[: max(budget, 0)]
        budget -= len(text)
        out.append(
            f'<passage n="{i}" company="{c.company}" ticker="{c.ticker}" '
            f'fiscal_year="{c.fiscal_year}" section="{c.section}">\n{text}\n</passage>'
        )
        if budget <= 0:
            break
    return "\n\n".join(out)


def build_user_prompt(
    question: str, passages: list[ScoredChunk], max_chars: int, feedback: list[str] | None = None
) -> str:
    parts = [f"Passages:\n{format_passages(passages, max_chars)}", f"Question: {question}"]
    if feedback:
        parts.append(
            "Your previous answer failed these checks. Fix them and answer again:\n- "
            + "\n- ".join(feedback)
        )
    return "\n\n".join(parts)


def _extract_json(text: str) -> Any:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def _to_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("$", "").strip())
    except ValueError:
        return None


def parse_draft(text: str) -> Draft:
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        return Draft(
            answerable=False,
            parse_error=str(e),
            refusal_reason="The model returned output that could not be parsed.",
        )
    claims = []
    for c in data.get("claims") or []:
        if not isinstance(c, dict) or not str(c.get("text", "")).strip():
            continue
        raw_cites = c.get("citations") or []
        if not isinstance(raw_cites, list):
            raw_cites = [raw_cites]
        # Models write citations as 1, "1", "[1]" or "passage 1"; keep the numbers.
        cites = [int(m) for n in raw_cites for m in re.findall(r"\d+", str(n))]
        calc = c.get("calculation")
        claims.append(
            DraftClaim(
                text=str(c["text"]).strip(),
                citations=cites,
                calculation=str(calc).strip() if calc else None,
                result=_to_float(c.get("result")),
            )
        )
    conf = str(data.get("confidence", "low")).lower()
    answerable = bool(data.get("answerable", bool(claims)))
    reason = data.get("refusal_reason")
    if answerable and not claims:
        # Said it could answer but gave nothing usable: record what came back,
        # so a format mismatch is not mistaken for a genuine refusal.
        keys = ", ".join(sorted(data)) if isinstance(data, dict) else type(data).__name__
        reason = f"Model output had no usable claims (keys: {keys})."
    return Draft(
        answerable=answerable and bool(claims),
        claims=claims,
        confidence=conf if conf in ("high", "medium", "low") else "low",
        refusal_reason=str(reason) if reason else None,
    )


class Generator:
    def __init__(self, llm: LLM, max_context_chars: int = 12000):
        self.llm = llm
        self.max_context_chars = max_context_chars

    def draft(
        self,
        question: str,
        passages: list[ScoredChunk],
        feedback: list[str] | None = None,
        llm: LLM | None = None,
    ) -> tuple[Draft, LLMResult]:
        result = (llm or self.llm).complete(
            system_prompt(),
            build_user_prompt(question, passages, self.max_context_chars, feedback),
        )
        return parse_draft(result.text), result
