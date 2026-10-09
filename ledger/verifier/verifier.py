"""The NRF arithmetic verifier, as Ledger's guardrail.

Two verifiers live here:

``PostHocArithmeticVerifier``
    A faithful port of Financial-NRF's verifier. It reads a free-text
    response in the ``Reasoning: ... Final Answer: ...`` format, recomputes
    the last stated expression and checks its operands appear in the
    evidence. Kept so the dissertation's behaviour and tests carry over.

``ClaimVerifier``
    What Ledger's answer path uses (VER-2). The generator returns structured
    claims; each numeric claim may carry a calculation. For every claim this
    checks that the calculation recomputes to the stated result, that its
    operands appear in the *cited* passages, and that every number in the
    claim sentence is either in a cited passage or is the recomputed result.

Scope, carried over from Financial-NRF and worth repeating in the README:
``verified`` means "internally consistent and grounded in the cited text",
not "correct". It cannot tell whether the model picked the right line item
or the right year. Correctness is measured separately, by the eval.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ledger.verifier.arithmetic import (
    UnsafeExpressionError,
    find_last_expression,
    safe_eval_arithmetic,
)
from ledger.verifier.numbers import (
    ParsedNumber,
    extract_amounts,
    extract_final_answer,
    extract_numbers,
    is_probably_year,
)

# Constants a calculation may use without them being "facts" from the
# filing: percent conversion, scaling, months, quarters, day counts.
CONVERSION_CONSTANTS = frozenset({1.0, 100.0, 1000.0, 1_000_000.0, 1e9, 12.0, 4.0, 360.0, 365.0})

# A claim in billions may be grounded in a table reported in thousands or
# millions; evidence values are scaled up by these factors when matching.
_EVIDENCE_SCALES = (1.0, 1e3, 1e6, 1e9)


# ---------------------------------------------------------------------------
# Financial-NRF verifier (ported)
# ---------------------------------------------------------------------------

_REASONING_SECTION_RE = re.compile(
    r"reasoning\s*[:\-]\s*(.*?)(?:final\s*answer\s*[:\-]|\Z)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class VerificationResult:
    parseable: bool
    expression: str | None
    stated_result: float | None
    recomputed_result: float | None
    execution_consistent: bool | None
    operand_count: int
    grounded_operand_count: int
    ungrounded_operands: list[float] = field(default_factory=list)
    operands_grounded: bool | None = None
    verified: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class PostHocArithmeticVerifier:
    """Gold-free check of a response's own stated arithmetic (Financial-NRF)."""

    def __init__(self, relative_tolerance: float = 0.02, absolute_tolerance: float = 0.01):
        self.relative_tolerance = relative_tolerance
        self.absolute_tolerance = absolute_tolerance

    def _close(self, a: float, b: float) -> bool:
        return abs(a - b) <= max(self.absolute_tolerance, abs(b) * self.relative_tolerance)

    def verify(self, response: str, evidence_text: str) -> VerificationResult:
        response = response or ""
        m = _REASONING_SECTION_RE.search(response)
        reasoning = m.group(1) if m else response

        expr = find_last_expression(reasoning)
        if expr is None:
            return VerificationResult(
                False,
                None,
                None,
                None,
                None,
                0,
                0,
                reason="No arithmetic expression (operator and >=2 numbers) in Reasoning.",
            )
        try:
            recomputed = safe_eval_arithmetic(expr)
        except (UnsafeExpressionError, SyntaxError, ZeroDivisionError, TypeError, ValueError) as e:
            return VerificationResult(
                False,
                expr,
                None,
                None,
                None,
                0,
                0,
                reason=f"Extracted expression could not be safely evaluated: {e}",
            )

        final = extract_final_answer(response)
        if final is None:
            return VerificationResult(
                True,
                expr,
                None,
                recomputed,
                None,
                0,
                0,
                reason="Expression recomputed but no 'Final Answer:' value to compare against.",
            )

        consistent = self._close(recomputed, final.value)
        operands = extract_numbers(expr)
        evidence = extract_numbers(evidence_text or "")
        grounded = 0
        ungrounded: list[float] = []
        for op in operands:
            if (not op.is_percentage and op.value in CONVERSION_CONSTANTS) or any(
                op.is_percentage == e.is_percentage and self._close(op.value, e.value)
                for e in evidence
            ):
                grounded += 1
            else:
                ungrounded.append(op.value)

        operands_grounded = (not ungrounded) if operands else None
        verified = bool(consistent and operands_grounded is not False)
        if verified:
            reason = "Operands grounded in evidence and recomputation matches the stated answer."
        elif operands_grounded is False:
            reason = f"Operand(s) not found in evidence (possible hallucinated input): {ungrounded}"
        else:
            reason = (
                f"Python recomputation of '{expr}' = {recomputed:.4f}, which does not match "
                f"the stated result ({final.value})."
            )
        return VerificationResult(
            True,
            expr,
            final.value,
            recomputed,
            consistent,
            len(operands),
            grounded,
            ungrounded,
            operands_grounded,
            verified,
            reason,
        )


# ---------------------------------------------------------------------------
# Claim-level verifier used by Ledger (VER-2, VER-3, VER-4)
# ---------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    VERIFIED = "verified"  # numbers grounded, calculation (if any) recomputes
    NO_NUMBERS = "no_numbers"  # nothing numeric to check
    MISMATCH = "mismatch"  # calculation does not give the stated result
    UNGROUNDED = "ungrounded"  # a number is in neither the cited text nor the calculation
    UNPARSEABLE = "unparseable"  # calculation is not plain arithmetic


@dataclass
class ClaimCheck:
    status: ClaimStatus
    expression: str | None = None
    stated_result: float | None = None
    recomputed_result: float | None = None
    ungrounded_numbers: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.status in (ClaimStatus.VERIFIED, ClaimStatus.NO_NUMBERS)

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["status"] = self.status.value
        d["passed"] = self.passed
        return d


class ClaimVerifier:
    """Checks one structured claim against the passages it cites."""

    def __init__(self, result_rel_tolerance: float = 0.005, ground_rel_tolerance: float = 0.001):
        # The PRF scores numbers "within 1%"; the verifier is stricter on
        # the model's own arithmetic, and stricter still when matching a
        # number against evidence, where a loose tolerance would ground an
        # invented figure by coincidence (Financial-NRF measured this).
        self.result_rel_tolerance = result_rel_tolerance
        self.ground_rel_tolerance = ground_rel_tolerance

    def _grounded(self, n: ParsedNumber, evidence: Sequence[ParsedNumber]) -> bool:
        target = abs(n.magnitude)
        for e in evidence:
            if e.is_percentage != n.is_percentage:
                continue
            for scale in _EVIDENCE_SCALES if not n.is_percentage else (1.0,):
                candidate = abs(e.magnitude) * scale
                tol = max(n.precision, e.precision * scale, self.ground_rel_tolerance * candidate)
                if abs(target - candidate) <= tol:
                    return True
        return False

    def _matches_result(self, n: ParsedNumber, result: float) -> bool:
        scales = (1.0,) if n.is_percentage else _EVIDENCE_SCALES
        for scale in scales:
            candidate = abs(result) * scale
            tol = max(n.precision, self.result_rel_tolerance * candidate)
            if abs(abs(n.magnitude) - candidate) <= tol:
                return True
        return False

    def verify(
        self,
        claim_text: str,
        cited_texts: Iterable[str],
        expression: str | None = None,
        stated_result: float | None = None,
    ) -> ClaimCheck:
        evidence = [n for t in cited_texts for n in extract_amounts(t)]
        recomputed: float | None = None

        if expression:
            try:
                recomputed = safe_eval_arithmetic(expression)
            except (UnsafeExpressionError, SyntaxError, ZeroDivisionError, TypeError, ValueError):
                return ClaimCheck(
                    ClaimStatus.UNPARSEABLE,
                    expression,
                    stated_result,
                    message=f"The calculation '{expression}' is not plain arithmetic. "
                    "Write it using only numbers, + - * / and parentheses.",
                )
            if stated_result is not None:
                tol = max(0.01, self.result_rel_tolerance * abs(recomputed))
                if abs(recomputed - stated_result) > tol:
                    return ClaimCheck(
                        ClaimStatus.MISMATCH,
                        expression,
                        stated_result,
                        recomputed,
                        message=f"The calculation '{expression}' evaluates to {recomputed:.6g}, "
                        f"not {stated_result:g}. Restate the claim using {recomputed:.6g}.",
                    )
            bad_ops = [
                op.raw_text
                for op in extract_numbers(expression)
                if not (op.value in CONVERSION_CONSTANTS or self._grounded(op, evidence))
            ]
            if bad_ops:
                return ClaimCheck(
                    ClaimStatus.UNGROUNDED,
                    expression,
                    stated_result,
                    recomputed,
                    bad_ops,
                    message=f"The operand(s) {', '.join(bad_ops)} in '{expression}' do not appear "
                    "in the cited passages. Use figures from the cited text only.",
                )

        claim_numbers = [n for n in extract_amounts(claim_text) if not is_probably_year(n)]
        ungrounded = [
            n.raw_text
            for n in claim_numbers
            if not self._grounded(n, evidence)
            and not (recomputed is not None and self._matches_result(n, recomputed))
        ]
        if ungrounded:
            return ClaimCheck(
                ClaimStatus.UNGROUNDED,
                expression,
                stated_result,
                recomputed,
                ungrounded,
                message=f"The number(s) {', '.join(ungrounded)} are not in the cited passages "
                "and are not the result of a stated calculation. Cite the passage they come "
                "from, add the calculation, or remove them.",
            )
        if not claim_numbers and expression is None:
            return ClaimCheck(ClaimStatus.NO_NUMBERS)
        return ClaimCheck(ClaimStatus.VERIFIED, expression, stated_result, recomputed)
