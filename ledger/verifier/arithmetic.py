"""Safe arithmetic evaluation, ported from Financial-NRF ``framework/verifier.py``.

Model output is never passed to ``eval()``. Expressions are parsed into a
syntax tree and evaluated with an allow-list of numeric literals, the four
arithmetic operators, unary +/- and parentheses. Anything else raises.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable


class UnsafeExpressionError(Exception):
    """The expression contains something other than plain arithmetic."""


_ALLOWED_BINOPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_ALLOWED_UNARYOPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Guards against pathological inputs such as "9" * 10_000.
MAX_EXPRESSION_LENGTH = 500


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise UnsafeExpressionError(f"Non-numeric constant: {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand))
    raise UnsafeExpressionError(f"Disallowed expression node: {type(node).__name__}")


def clean_expression(expr: str) -> str:
    """Strip currency, thousands separators and percent signs."""
    return re.sub(r"[$£€,%]", "", expr).strip(" .\t\n")


def safe_eval_arithmetic(expr: str) -> float:
    """Evaluate ``expr`` with Python's own arithmetic.

    Raises ``UnsafeExpressionError``, ``SyntaxError`` or
    ``ZeroDivisionError``; callers must treat any of those as "could not
    verify", never as "verified".
    """
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise UnsafeExpressionError("Expression too long")
    return _eval_node(ast.parse(clean_expression(expr), mode="eval"))


# A span of digits, separators, currency, parentheses, operators and spaces.
_EXPR_SPAN_RE = re.compile(r"[\d.,$£€%()+\-*/\s]{3,}")
_HAS_OP = re.compile(r"[+\-*/]")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _looks_like_expression(span: str) -> bool:
    return bool(_HAS_OP.search(span)) and len(_NUM.findall(span)) >= 2


def find_last_expression(text: str) -> str | None:
    """The last arithmetic-looking span in ``text`` (Financial-NRF logic).

    A span needs an operator and at least two numbers. A period followed by
    whitespace is a sentence boundary, not a decimal point, so spans are
    split there and the last fragment that still qualifies is kept.
    """
    best = None
    for match in _EXPR_SPAN_RE.finditer(text):
        span = match.group(0)
        qualified = [f for f in re.split(r"\.\s+", span) if _looks_like_expression(f)]
        span = qualified[-1] if qualified else span
        if _looks_like_expression(span):
            best = span
    if best is None:
        return None
    cleaned = clean_expression(best)
    return cleaned if cleaned and _HAS_OP.search(cleaned) else None
