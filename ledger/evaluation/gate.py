"""CI-2: fail a pull request when accuracy or groundedness drops.

The baseline is the metrics JSON of the last smoke run on main, committed at
``eval/results/baseline-smoke.json``. A gated metric fails when it drops by
more than ``max_drop`` (2 points by default) *and* the drop is larger than
sampling noise at the sizes actually measured: with 50 questions a metric has
a standard error of several points, so a bare 2-point rule fails on noise
about as often as on real regressions. The noise bar is ``z`` standard errors
of the difference of two proportions (1.645 = one-sided 95%), so a regression
that clears both bars is real with 95% confidence. Large samples (the full
test split) are therefore held to the 2-point rule, small ones to the noise bar.

Sample sizes come from the metrics files (``accuracy_n``, ``groundedness_n``,
``refusal_n``). A baseline written before those counts existed is assumed to
have the size of the current run (the smoke set is fixed). When the current
run has no counts at all, the plain 2-point rule applies.
"""

from __future__ import annotations

import math
from typing import Any

GATED = ("accuracy", "groundedness", "refusal_accuracy")
# Metric -> the metric-file field holding its sample size.
SAMPLE_SIZE = {
    "accuracy": "accuracy_n",
    "groundedness": "groundedness_n",
    "refusal_accuracy": "refusal_n",
}
Z_ONE_SIDED_95 = 1.645


def noise_bar(
    p_old: float, p_new: float, n_old: float, n_new: float, z: float = Z_ONE_SIDED_95
) -> float:
    """The drop in a proportion that two runs of these sizes could show by chance."""

    def var(p: float, n: float) -> float:
        smoothed = (p * n + 0.5) / (n + 1)  # keeps the variance above zero at p = 0 or 1
        return smoothed * (1 - smoothed) / n

    return z * math.sqrt(var(p_old, n_old) + var(p_new, n_new))


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
            continue
        drop = old - new
        if drop <= max_drop:
            continue
        n_new = current.get(SAMPLE_SIZE[metric])
        if not n_new:
            bar = 0.0  # no counts: the plain rule
        else:
            n_old = baseline.get(SAMPLE_SIZE[metric]) or n_new
            bar = noise_bar(old, new, n_old, n_new)
        if drop > bar:
            noise = f", beyond the noise bar of {bar:.3f}" if bar else ""
            failures.append(
                f"{metric}: {new:.3f} vs baseline {old:.3f} "
                f"(drop {drop:.3f} > {max_drop:.2f}{noise})"
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
