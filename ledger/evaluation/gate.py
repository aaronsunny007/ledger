"""CI-2: fail a pull request when accuracy or groundedness drops.

The baseline is the metrics JSON of the last smoke run on main, committed at
``eval/results/baseline-smoke.json``. A drop of more than ``max_drop``
(2 points by default) on any gated metric fails the check.
"""

from __future__ import annotations

from typing import Any

GATED = ("accuracy", "groundedness", "refusal_accuracy")


def check_regression(
    current: dict[str, Any], baseline: dict[str, Any], max_drop: float = 0.02
) -> list[str]:
    failures = []
    for metric in GATED:
        new, old = current.get(metric), baseline.get(metric)
        if old is None:
            continue
        if new is None:
            failures.append(f"{metric}: missing in this run (baseline {old:.3f})")
        elif new < old - max_drop:
            failures.append(
                f"{metric}: {new:.3f} vs baseline {old:.3f} (drop {old - new:.3f} > {max_drop:.2f})"
            )
    return failures


def markdown_summary(
    current: dict[str, Any], baseline: dict[str, Any] | None, failures: list[str]
) -> str:
    rows = ["| metric | this PR | main |", "|---|---|---|"]
    for k, v in current.items():
        if isinstance(v, (int, float)) or v is None:
            b = (baseline or {}).get(k)
            rows.append(f"| {k} | {_fmt(v)} | {_fmt(b)} |")
    status = (
        "**Eval gate: FAILED**\n\n- " + "\n- ".join(failures)
        if failures
        else ("**Eval gate: passed**")
    )
    return status + "\n\n" + "\n".join(rows)


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}" if v < 10 else f"{v:,.0f}"
    return str(v)
