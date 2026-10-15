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


def test_smoke_set_excludes_out_of_corpus() -> None:
    items = [
        _item(id=f"x{i}", split="dev", tags=["out-of-corpus"] if i % 2 else []) for i in range(10)
    ]
    assert all("out-of-corpus" not in i.tags for i in smoke_set(items, 10))


def test_quota_error_carries_the_providers_wait() -> None:
    import httpx

    from ledger.answer.llm import GeminiLLM, QuotaExhausted

    body = {"error": {"message": "q", "details": [{"retryDelay": "1215s"}]}}
    llm = GeminiLLM("key", "m")
    llm._http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, json=body))
    )
    try:
        llm.complete("s", "u")
    except QuotaExhausted as e:
        assert e.retry_after == 1215.0
    else:
        raise AssertionError("expected QuotaExhausted")


def _run_eval_module():  # type: ignore[no-untyped-def]
    import importlib.util
    import sys

    path = Path(__file__).resolve().parent.parent / "eval" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_resume_picks_the_finished_run_or_the_fullest_partial(tmp_path: Path) -> None:
    import json

    mod = _run_eval_module()
    mod.RESULTS = tmp_path

    def save(name: str, code: str, partial: bool, n: int) -> None:
        (tmp_path / name).write_text(
            json.dumps({"code_hash": code, "partial": partial, "items": [{}] * n})
        )

    save("1-t.json", "A", False, 217)
    save("2-t.json", "A", True, 0)  # an empty partial left by a rate-limited start
    save("3-t.json", "B", True, 50)
    found = mod.best_saved_run("t", {"A"})
    assert found and found[0].name == "1-t.json" and not found[1]["partial"]
    found = mod.best_saved_run("t", {"B"})
    assert found and found[0].name == "3-t.json"
    assert mod.best_saved_run("t", {"C"}) is None


def test_gate_ignores_a_drop_that_is_sampling_noise() -> None:
    # PR #4: groundedness 69/74 -> 73/83 on the 50-question smoke set.
    base = {"accuracy": 0.79, "groundedness": 0.9324, "refusal_accuracy": 1.0}
    cur = {
        "accuracy": 0.82,
        "accuracy_n": 38,
        "groundedness": 0.8795,
        "groundedness_n": 83,
        "refusal_accuracy": 1.0,
        "refusal_n": 2,
    }
    assert check_regression(cur, base) == []


def test_gate_still_catches_a_large_drop_on_a_small_sample() -> None:
    base = {"groundedness": 0.95, "groundedness_n": 80}
    cur = {"groundedness": 0.70, "groundedness_n": 80}
    (failure,) = check_regression(cur, base)
    assert "groundedness" in failure and "noise bar" in failure


def test_gate_holds_large_samples_to_the_two_point_rule() -> None:
    # 400 claims each: sampling noise is about 2 points, so 2.5 points is a regression.
    base = {"groundedness": 0.97, "groundedness_n": 400}
    assert check_regression({"groundedness": 0.945, "groundedness_n": 400}, base)
    assert not check_regression({"groundedness": 0.955, "groundedness_n": 400}, base)


def test_noise_bar_shrinks_with_sample_size_and_survives_perfect_scores() -> None:
    from ledger.evaluation.gate import noise_bar

    assert noise_bar(0.9, 0.9, 400, 400) < noise_bar(0.9, 0.9, 50, 50)
    assert noise_bar(1.0, 1.0, 10, 10) > 0


@pytest.mark.parametrize(
    ("report_date", "year"),
    [
        ("2023-01-01", 2022),  # Johnson & Johnson's fiscal 2022
        ("2022-01-02", 2021),
        ("2021-01-03", 2020),
        ("2023-12-31", 2023),  # and its fiscal 2023, which used to share the label 2023
        ("2024-01-31", 2024),  # Walmart's FY2024 stays with the year it ends in
        ("2023-01-29", 2023),  # Home Depot, Ulta and other late-January years
        ("2022-09-24", 2022),
    ],
)
def test_fiscal_year_of_a_52_53_week_year(report_date: str, year: int) -> None:
    from ledger.ingest.fiscal import fiscal_year_of

    assert fiscal_year_of(report_date) == year


def test_two_johnson_and_johnson_filings_no_longer_share_a_year() -> None:
    from ledger.ingest.edgar import Filing

    def filing(report_date: str) -> Filing:
        return Filing("JNJ", "Johnson & Johnson", 200406, "10-K", "a", report_date, "x", "d.htm")

    assert filing("2023-01-01").fiscal_year != filing("2023-12-31").fiscal_year
    assert filing("2023-01-01").doc_id == "JNJ_2022_10K"
