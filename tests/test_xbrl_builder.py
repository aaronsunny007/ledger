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
