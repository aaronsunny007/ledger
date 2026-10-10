"""EVAL-1..EVAL-5: scoring one answer, and aggregating a run."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ledger.evaluation.golden import GoldenItem
from ledger.types import Answer, Chunk
from ledger.verifier.numbers import extract_amounts, is_probably_year

_SCALES = (1.0, 1e3, 1e6, 1e9)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def numeric_match(
    answer_text: str, gold: float, rel_tol: float = 0.01, percent: bool = False
) -> bool:
    """True if any number in the answer equals ``gold`` within ``rel_tol``.

    Scale words and units may differ on either side: "$4.5 billion" matches
    4_500_000_000, "4,500" in a millions table matches it too, and "$5,409
    million" matches a gold answer of 5409 given in USD millions (FinanceBench
    states many answers in millions). Sign is ignored, because "a loss of $2m"
    and "-2,000,000" state the same fact.
    """
    target = abs(gold)
    for n in extract_amounts(answer_text):
        if is_probably_year(n) and not (1900 <= target <= 2100):
            continue
        if n.is_percentage:
            if abs(abs(n.value) - target) <= max(rel_tol * target, 1e-9):
                return True
        else:
            value, magnitude = abs(n.value), abs(n.magnitude)
            tol = max(rel_tol * target, 1e-9)
            # The answer's number as written, or scaled up as a table in thousands/millions.
            if any(abs(value * s - target) <= tol for s in _SCALES):
                return True
            # A scale word on the answer ("$5.4 billion") against gold in millions.
            if magnitude != value and any(
                abs(magnitude - target * s) <= rel_tol * target * s for s in _SCALES
            ):
                return True
        # A ratio stated where a percent was expected, or vice versa.
        if percent and not n.is_percentage and abs(abs(n.value) * 100 - target) <= rel_tol * target:
            return True
    return False


def _content_tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if len(t) > 2 or t.isdigit()}


def evidence_overlap(text: str, item: GoldenItem) -> float:
    """Largest share of any gold evidence passage's content tokens found in ``text``."""
    tokens = _content_tokens(text)
    best = 0.0
    for e in item.evidence:
        ev = _content_tokens(e.text)
        if ev:
            best = max(best, len(ev & tokens) / len(ev))
    return best


def evidence_hit(chunk: Chunk, item: GoldenItem, threshold: float = 0.5) -> bool:
    """Does this retrieved chunk contain the gold evidence?

    Filings are indexed from HTML while FinanceBench evidence comes from PDF
    pages, so exact matching is impossible; a chunk counts as a hit when it
    holds at least ``threshold`` of the evidence's distinct content tokens
    (numbers included). XBRL items, which have no evidence text, count a hit
    when the chunk is from the right filing and states the gold value.
    """
    if item.evidence and any(e.text for e in item.evidence):
        return evidence_overlap(chunk.text, item) >= threshold
    if item.value is not None and item.ticker:
        if chunk.ticker != item.ticker or chunk.fiscal_year != item.fiscal_year:
            return False
        return numeric_match(chunk.text, item.value, 0.005)
    return False


def recall_and_rr(retrieved: Sequence[Chunk], item: GoldenItem, k: int) -> tuple[float, float]:
    """(recall@k as 0/1 for "any evidence found", reciprocal rank of first hit)."""
    for rank, c in enumerate(retrieved, start=1):
        if evidence_hit(c, item):
            return (1.0 if rank <= k else 0.0), 1.0 / rank
    return 0.0, 0.0


@dataclass
class ItemResult:
    id: str
    source: str
    answer_type: str
    question: str
    gold: str
    answer: str
    refused: bool
    correct: float | None  # None: needs an LLM judge and none was run
    verified: bool | None
    recall: float | None
    rr: float | None
    claims: int
    grounded_claims: int
    latency_ms: int
    cost_usd: float
    cache_hit: bool
    regenerated: bool
    tags: list[str] = field(default_factory=list)
    error: str | None = None
    judge: dict[str, Any] | None = None
    refusal_reason: str | None = None


def score_item(item: GoldenItem, answer: Answer, k: int = 6) -> ItemResult:
    if item.answer_type == "refusal":
        correct: float | None = 1.0 if answer.refused else 0.0
    elif answer.refused:
        correct = 0.0
    elif item.answer_type == "numeric" and item.value is not None:
        correct = (
            1.0
            if numeric_match(
                answer.answer, item.value, item.tolerance, percent=item.unit == "percent"
            )
            else 0.0
        )
    else:
        correct = None

    has_evidence = item.answer_type != "refusal" and (
        any(e.text for e in item.evidence) or item.value is not None
    )
    recall, rr = recall_and_rr(answer.retrieved, item, k) if has_evidence else (None, None)
    grounded = sum(1 for c in answer.claims if c.verified is not False)
    return ItemResult(
        id=item.id,
        source=item.source,
        answer_type=item.answer_type,
        question=item.question,
        gold=item.answer,
        answer=answer.answer,
        refused=answer.refused,
        correct=correct,
        verified=answer.verified,
        recall=recall,
        rr=rr,
        claims=len(answer.claims),
        grounded_claims=grounded,
        latency_ms=answer.latency_ms,
        cost_usd=answer.cost_usd,
        cache_hit=answer.cache_hit,
        regenerated=answer.regenerated,
        tags=list(item.tags),
        refusal_reason=answer.refusal_reason if answer.refused else None,
    )


def _mean(xs: Sequence[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def percentile(xs: Sequence[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = (len(s) - 1) * p
    lo, hi = math.floor(i), math.ceil(i)
    return round(s[lo] + (s[hi] - s[lo]) * (i - lo), 1)


def aggregate(results: Sequence[ItemResult]) -> dict[str, Any]:
    ok = [r for r in results if r.error is None]
    answerable = [r for r in ok if r.answer_type != "refusal"]
    unanswerable = [r for r in ok if r.answer_type == "refusal"]
    scored = [r.correct for r in answerable if r.correct is not None]
    total_claims = sum(r.claims for r in ok)
    latencies = [r.latency_ms for r in ok if not r.cache_hit]
    costs = [r.cost_usd for r in ok if not r.cache_hit]
    return {
        "n": len(results),
        "errors": len(results) - len(ok),
        "accuracy": _mean(scored),
        "accuracy_n": len(scored),
        "refusal_accuracy": _mean([r.correct or 0.0 for r in unanswerable]),
        "false_refusal_rate": _mean([1.0 if r.refused else 0.0 for r in answerable]),
        "groundedness": round(sum(r.grounded_claims for r in ok) / total_claims, 4)
        if total_claims
        else None,
        "verified_rate": _mean([1.0 if r.verified else 0.0 for r in ok if r.verified is not None]),
        "regenerated_rate": _mean([1.0 if r.regenerated else 0.0 for r in ok]),
        "recall_at_k": _mean([r.recall for r in ok if r.recall is not None]),
        "mrr": _mean([r.rr for r in ok if r.rr is not None]),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "cost_per_question_usd": round(sum(costs) / len(costs), 6) if costs else None,
    }


def aggregate_by(results: Sequence[ItemResult], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[ItemResult]] = {}
    for r in results:
        groups.setdefault(str(getattr(r, key)), []).append(r)
    return {k: aggregate(v) for k, v in sorted(groups.items())}
