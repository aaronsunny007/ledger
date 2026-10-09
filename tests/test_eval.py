from __future__ import annotations

from pathlib import Path

import pytest

from ledger.evaluation.gate import check_regression, markdown_summary
from ledger.evaluation.golden import (
    Evidence,
    GoldenItem,
    assign_split,
    load_golden,
    smoke_set,
    write_golden,
)
from ledger.evaluation.metrics import (
    aggregate,
    aggregate_by,
    evidence_hit,
    numeric_match,
    percentile,
    score_item,
)
from ledger.types import Answer, Chunk, Claim
from scripts.financebench import doc_type_and_year, parse_numeric


@pytest.mark.parametrize(
    ("text", "gold", "ok"),
    [
        ("Revenue was $4.5 billion in FY2024 [1].", 4_500_000_000, True),
        ("Revenue was $4,500 million.", 4_500_000_000, True),
        ("Revenue was 4,500 (in millions).", 4_500_000_000, True),
        ("Revenue was $4.6 billion.", 4_500_000_000, False),
        ("It grew 12.5% in 2024.", 12.5, True),
        ("It grew 12.6%.", 12.5, True),  # within 1%
        ("It grew 13%.", 12.5, False),
        ("A net loss of $(2.0) million.", -2_000_000, True),
        ("In fiscal 2024.", 2_000_000, False),
        ("Inventories were $5,409 million.", 5409, True),  # gold in USD millions
        ("Net AR was $1,615.9 million.", 1616, True),
        ("Revenue was $5.4 billion.", 5409, True),
        ("The ratio is 825.77.", 0.83, False),
    ],
)
def test_numeric_match(text: str, gold: float, ok: bool) -> None:
    assert numeric_match(text, gold, 0.01) is ok


def test_ratio_matches_percent_gold() -> None:
    assert numeric_match("The margin was 0.25.", 25.0, 0.01, percent=True)


def _item(**kw: object) -> GoldenItem:
    base: dict[str, object] = {
        "id": "x",
        "source": "xbrl",
        "question": "q",
        "value": 4.5e9,
        "ticker": "ACME",
        "fiscal_year": 2024,
    }
    base.update(kw)
    return GoldenItem.model_validate(base)


def test_evidence_hit_by_text_overlap() -> None:
    item = _item(
        source="financebench",
        evidence=[Evidence(text="Total revenue 4,500 4,000 operating income 630")],
    )
    good = Chunk(
        id="1",
        text="Total revenue | $4,500 | $4,000\nOperating income | 630",
        company="A",
        ticker="ACME",
    )
    bad = Chunk(id="2", text="Employees 12,400", company="A", ticker="ACME")
    assert evidence_hit(good, item) and not evidence_hit(bad, item)


def test_evidence_hit_for_xbrl_needs_right_filing_and_value() -> None:
    item = _item()
    c = Chunk(id="1", text="Total revenue | 4,500", company="A", ticker="ACME", fiscal_year=2024)
    assert evidence_hit(c, item)
    assert not evidence_hit(c.model_copy(update={"fiscal_year": 2023}), item)


def test_score_and_aggregate() -> None:
    chunk = Chunk(
        id="1", text="Total revenue | 4,500", company="A", ticker="ACME", fiscal_year=2024
    )
    right = Answer(
        question="q",
        answer="Revenue was $4.5 billion.",
        latency_ms=1000,
        cost_usd=0.001,
        claims=[Claim(text="t", citations=[1], verified=True)],
        verified=True,
        retrieved=[chunk],
    )
    wrong = Answer(
        question="q",
        answer="Revenue was $9 billion.",
        latency_ms=3000,
        cost_usd=0.003,
        claims=[Claim(text="t", citations=[1], verified=False)],
        verified=False,
    )
    refused = Answer(question="q", answer="no", refused=True, latency_ms=500)
    results = [
        score_item(_item(id="a"), right),
        score_item(_item(id="b"), wrong),
        score_item(_item(id="c", answer_type="refusal", value=None), refused),
        score_item(_item(id="d", source="handwritten", answer_type="refusal", value=None), right),
    ]
    m = aggregate(results)
    assert m["accuracy"] == 0.5
    assert m["refusal_accuracy"] == 0.5
    assert m["groundedness"] == pytest.approx(2 / 3, abs=1e-3)
    assert m["recall_at_k"] == 0.5 and m["mrr"] == 0.5
    assert m["latency_p50_ms"] == 1000
    assert set(aggregate_by(results, "source")) == {"handwritten", "xbrl"}


def test_text_answers_await_the_judge() -> None:
    r = score_item(_item(answer_type="text", value=None), Answer(question="q", answer="ok"))
    assert r.correct is None


def test_percentile() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2.5 and percentile([], 0.5) is None


def test_gate_flags_drops_over_two_points() -> None:
    base = {"accuracy": 0.70, "groundedness": 0.95, "refusal_accuracy": 0.9}
    assert (
        check_regression({"accuracy": 0.69, "groundedness": 0.95, "refusal_accuracy": 0.9}, base)
        == []
    )
    fails = check_regression(
        {"accuracy": 0.65, "groundedness": None, "refusal_accuracy": 0.9}, base
    )
    assert len(fails) == 2
    assert "FAILED" in markdown_summary({"accuracy": 0.65}, base, fails)


def test_split_is_stable_and_roughly_20_percent() -> None:
    splits = [assign_split(f"id-{i}") for i in range(2000)]
    assert assign_split("id-7") == assign_split("id-7")
    assert 0.15 < splits.count("dev") / len(splits) < 0.25


def test_golden_roundtrip_and_smoke_set(tmp_path: Path) -> None:
    items = [_item(id=f"x{i}", split="dev") for i in range(30)] + [
        _item(id=f"h{i}", source="handwritten", answer_type="refusal", split="dev")
        for i in range(30)
    ]
    write_golden(tmp_path / "g.jsonl", items)
    loaded = load_golden([tmp_path / "g.jsonl"])
    assert len(loaded) == 60
    smoke = smoke_set(loaded, 50)
    assert len(smoke) == 50 and {i.source for i in smoke} == {"xbrl", "handwritten"}
    with pytest.raises(ValueError):
        write_golden(tmp_path / "dup.jsonl", [items[0], items[0]])
        load_golden([tmp_path / "dup.jsonl"])


def test_committed_golden_files_are_valid() -> None:
    items = load_golden()
    assert any(i.source == "handwritten" for i in items)


@pytest.mark.parametrize(
    ("answer", "value", "unit"),
    [
        ("$1577.00", 1577.0, "usd"),
        ("8.5%", 8.5, "percent"),
        ("$1.2 billion", 1.2e9, "usd"),
        ("-0.02", -0.02, ""),
        ("Yes, because the company has strong liquidity", None, ""),
        (", 1.2", None, ""),
        ("No. 3M is not capital-intensive", None, ""),
    ],
)
def test_financebench_answer_parsing(answer: str, value: float | None, unit: str) -> None:
    v, u = parse_numeric(answer)
    assert (v == pytest.approx(value) if value is not None else v is None) and u == unit


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"doc_type": "10k", "doc_period": 2018}, ("10k", 2018)),
        ({"doc_name": "3M_2018_10K"}, ("10k", 2018)),
        ({"doc_name": "AMCOR_2023Q2_10Q"}, ("10q", 2023)),
        ({"doc_name": "PEPSICO_2023_8K_dated-2023-05-30"}, ("8k", 2023)),
        ({"doc_name": "nothing"}, ("", None)),
    ],
)
def test_financebench_doc_type_and_year(
    row: dict[str, object], expected: tuple[str, int | None]
) -> None:
    assert doc_type_and_year(row) == expected
