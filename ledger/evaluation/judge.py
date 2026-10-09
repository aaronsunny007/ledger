"""EVAL-1: an LLM judge for text answers.

Numeric answers are scored by ``numeric_match``; only answers that are not a
single number go to the judge. The judge is a free-tier model, so its
agreement with a human must be checked: ``eval/judge_spotcheck.py`` samples
50 judged answers for you to label and reports the agreement rate.
"""

from __future__ import annotations

import json
from typing import Any

from ledger.answer.llm import LLM

JUDGE_SYSTEM = """You grade answers to questions about company filings.
Given a question, a gold answer and a candidate answer, decide whether the candidate
states the same facts as the gold answer. Ignore citation markers like [1], wording,
and extra correct detail. Numbers must agree to within 1% (units may differ, e.g.
$1.2 billion = $1,200 million). A candidate that refuses or hedges is incorrect.
Reply with JSON only: {"correct": true|false, "reason": "<one sentence>"}"""


def judge(llm: LLM, question: str, gold: str, candidate: str) -> dict[str, Any]:
    res = llm.complete(
        JUDGE_SYSTEM,
        f"Question: {question}\n\nGold answer: {gold}\n\nCandidate answer: {candidate}",
    )
    try:
        start, end = res.text.find("{"), res.text.rfind("}")
        data = json.loads(res.text[start : end + 1])
        return {
            "correct": bool(data.get("correct")),
            "reason": str(data.get("reason", "")),
            "model": res.model,
            "cost_usd": res.cost_usd,
        }
    except (ValueError, json.JSONDecodeError):
        return {
            "correct": False,
            "reason": "unparseable judge output",
            "model": res.model,
            "cost_usd": res.cost_usd,
        }
