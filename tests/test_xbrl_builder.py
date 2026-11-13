from __future__ import annotations

from typing import Any

from scripts.make_xbrl_questions import annual_values, make_items


def _fact(val: float, end: str, fy: int, start: str | None = None) -> dict[str, Any]:
    f: dict[str, Any] = {"val": val, "end": end, "fy": fy, "form": "10-K", "fp": "FY"}
    if start:
        f["start"] = start
    return f


def _facts(**concepts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {k: {"units": {"USD": v}} for k, v in concepts.items()}}}


def test_revenue_takes_the_total_not_a_part() -> None:
    # General Mills: a smaller "Revenues" fact beside the net sales total.
    facts = _facts(
        Revenues=[_fact(2_134e6, "2022-05-29", 2022, "2021-05-31")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            _fact(18_992.8e6, "2022-05-29", 2022, "2021-05-31")
        ],
    )
    assert annual_values(facts, "revenue") == {2022: 18_992.8e6}


def test_original_figure_beats_a_later_restatement() -> None:
    facts = _facts(
        NetIncomeLoss=[
            _fact(900e6, "2021-12-31", 2022, "2021-01-01"),  # restated in the FY2022 10-K
            _fact(939e6, "2021-12-31", 2021, "2021-01-01"),  # as first reported
        ]
    )
    assert annual_values(facts, "net income") == {2021: 939e6}


def test_implausible_margin_is_not_a_question() -> None:
    facts = _facts(
        Revenues=[_fact(2_134e6, "2022-05-29", 2022, "2021-05-31")],
        OperatingIncomeLoss=[_fact(3_475.8e6, "2022-05-29", 2022, "2021-05-31")],
    )
    kinds = {i.id.rsplit("-", 1)[-1] for i in make_items("GIS", "General Mills", facts, [2022])}
    assert "operating_margin" not in kinds and "revenue" in kinds


def test_extra_questions_are_signed_tuning_items_outside_dev_and_test() -> None:
    from scripts.make_xbrl_questions import make_extra_items, pick_balanced

    def two_years(concept: str, a: float, b: float, instant: bool = False) -> dict[str, Any]:
        def f(val: float, y: int) -> dict[str, Any]:
            return _fact(val, f"{y}-12-31", y, None if instant else f"{y}-01-01")

        return {concept: [f(a, 2022), f(b, 2023)]}

    facts = _facts(
        **two_years("Revenues", 4000e6, 4500e6),
        **two_years("OperatingIncomeLoss", 500e6, 630e6),
        **two_years("LongTermDebtNoncurrent", 143e9, 140e9, True),
        **two_years("LongTermDebtCurrent", 7e9, 8e9, True),
    )
    items = {i.id.rsplit("-", 1)[-1]: i for i in make_extra_items("ACME", "Acme", facts, [2023])}
    assert {"revenue_direction", "total_debt_direction", "operating_margin_change"} <= set(items)
    debt = items["total_debt_direction"]
    assert debt.split == "extra" and "signed" in debt.tags and "multi-step" in debt.tags
    assert debt.value == (140e9 + 8e9) - (143e9 + 7e9)  # -2 billion: it fell
    assert pick_balanced(list(items.values()), 2, seed=1)
