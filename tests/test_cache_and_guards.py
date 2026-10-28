from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ledger.cache.semantic_cache import SemanticCache, content_words, same_question
from ledger.pipeline import NO_COMPANY, Ledger
from ledger.retrieve.filters import Filters
from ledger.retrieve.needs import statements_needed
from ledger.types import Answer
from tests.conftest import claims_json, passage_number


class SameVector:
    """Every question embeds identically: the worst case for a similarity-only cache."""

    def embed_query(self, text: str) -> np.ndarray:
        return np.ones(4, dtype=np.float32) / 2.0


F = Filters(tickers=["NKE"], years=[2023])


def test_a_different_metric_is_not_served_from_the_cache() -> None:
    cache = SemanticCache(SameVector(), threshold=0.9)  # type: ignore[arg-type]
    cache.store(
        "What was Nike's revenue in fiscal year 2023?",
        F,
        Answer(question="q", answer="51,217"),
        set(),
    )
    hit, _ = cache.lookup("WHAT WAS NIKE'S NET INCOME IN FISCAL 2023???", F)
    assert hit is None  # identical vectors, different question


def test_the_same_question_worded_differently_still_hits() -> None:
    cache = SemanticCache(SameVector(), threshold=0.9)  # type: ignore[arg-type]
    cache.store(
        "What was Nike's revenue in fiscal year 2023?",
        F,
        Answer(question="q", answer="51,217"),
        set(),
    )
    for again in (
        "nike revenue FY2023?",
        "What were Nike's revenues in fiscal 2023",
        "Nike's REVENUE in 2023",
    ):
        hit, _ = cache.lookup(again, F)
        assert hit is not None and hit.answer == "51,217", again


def test_content_words_ignore_filler_but_not_the_metric() -> None:
    assert content_words("What was Nike's revenue in FY2023?") == content_words("nike revenue 2023")
    assert content_words("Nike net income 2023") != content_words("Nike revenue 2023")
    assert content_words("Nike revenue 2022") != content_words("Nike revenue 2023")


def test_typos_do_not_hide_the_statement_a_question_needs() -> None:
    assert statements_needed("whats teslas revnue in 2022") == statements_needed(
        "what is tesla's revenue in 2022"
    )
    assert statements_needed("Acme total asets in 2024") == statements_needed(
        "Acme total assets in 2024"
    )
    assert statements_needed("What risks does Tesla describe?") == []  # prose stays prose


def test_a_question_naming_no_known_company_is_asked_to_name_one(
    make_ledger: Callable[..., tuple[Ledger, object]],
) -> None:
    ledger, llm = make_ledger(lambda s, u: claims_json({"text": "x", "citations": [1]}))
    a = ledger.ask("What was the revenue last year?")
    assert a.refused and a.answer == NO_COMPANY and not a.model
    assert len(llm.calls) == 0  # type: ignore[attr-defined]
    assert ledger.ask("What was Acme Widgets operating income in 2024?").answer != NO_COMPANY


def test_unusable_claims_are_retried_once(
    make_ledger: Callable[..., tuple[Ledger, object]],
) -> None:
    replies = iter(['{"answerable": true, "claims": [], "confidence": "high"}', None])

    def respond(system: str, user: str) -> str:
        bad = next(replies)
        if bad is not None:
            return bad
        n = passage_number(user, "Operating income was $630 million")
        return claims_json(
            {"text": "Acme Widgets' operating income was $630 million.", "citations": [n]}
        )

    ledger, llm = make_ledger(respond)
    a = ledger.ask("What was Acme Widgets operating income in 2024?")
    assert not a.refused and len(llm.calls) == 2  # type: ignore[attr-defined]


def test_company_names_tolerate_a_plural_and_one_typo() -> None:
    from pathlib import Path

    from ledger.retrieve.filters import CompanyRegistry

    reg = CompanyRegistry.from_yaml(
        Path(__file__).resolve().parent.parent / "configs" / "corpus.yaml"
    )
    assert reg.find("whats teslas revnue in 2022") == ["TSLA"]
    assert reg.find("Tesla's revenue") == ["TSLA"]
    assert reg.find("What was Mircosoft revenue 2023") == ["MSFT"]
    # nothing close to a loaded company: stays unmatched, so Ledger asks which one is meant
    for q in (
        "What was the revenue last year?",
        "What was Zoom's revenue?",
        "population of France",
    ):
        assert reg.find(q) == [], q


def test_coverage_lines_group_years_by_company() -> None:
    from ledger.retrieve.coverage import coverage_lines

    docs = [
        {"ticker": "MSFT", "company": "Microsoft Corp", "fiscal_year": 2023},
        {"ticker": "AAPL", "company": "Apple Inc.", "fiscal_year": 2023},
        {"ticker": "AAPL", "company": "Apple Inc.", "fiscal_year": 2021},
        {"ticker": "", "company": "No ticker", "fiscal_year": 2020},
    ]
    assert coverage_lines(docs) == ["Apple Inc. (AAPL): 2021, 2023", "Microsoft Corp (MSFT): 2023"]
    assert coverage_lines([]) == []


def test_the_order_of_the_years_matters() -> None:
    a = "How much did Nike's revenue change from 2022 to 2023?"
    b = "How much did Nike's revenue change from 2023 to 2022?"
    assert not same_question(a, b)
    assert same_question(a, "nike revenue change from 2022 to 2023")
    cache = SemanticCache(SameVector(), threshold=0.9)  # type: ignore[arg-type]
    cache.store(
        a, Filters(tickers=["NKE"], years=[2022, 2023]), Answer(question="q", answer="up"), set()
    )
    assert cache.lookup(b, Filters(tickers=["NKE"], years=[2022, 2023]))[0] is None


# -- interactive latency: say "busy" instead of sleeping, and say what is loaded ---------------


def test_a_long_rate_limit_wait_raises_busy_instead_of_sleeping(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx
    import pytest

    from ledger.answer import llm as llm_mod
    from ledger.answer.llm import GeminiLLM, LLMBusy

    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: pytest.fail("must not sleep"))

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"error": {"message": "rate", "details": [{"retryDelay": "45s"}]}}
        return httpx.Response(429, json=body)

    patient = GeminiLLM("k", "m")  # batch default: no cap
    quick = GeminiLLM("k", "m", max_retry_wait=15)
    quick._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMBusy) as e:
        quick.complete("s", "u")
    assert e.value.retry_after == 45
    assert patient._max_retry_wait is None  # the eval keeps waiting


def test_a_short_rate_limit_wait_is_still_waited_out(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    from ledger.answer import llm as llm_mod
    from ledger.answer.llm import GeminiLLM

    slept: list[float] = []
    monkeypatch.setattr(llm_mod.time, "sleep", slept.append)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {"details": [{"retryDelay": "3s"}]}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    llm = GeminiLLM("k", "m", max_retry_wait=15)
    llm._http = httpx.Client(transport=httpx.MockTransport(handler))
    assert llm.complete("s", "u").text == "{}" and slept == [4.0]


def test_busy_model_gives_a_503_and_does_not_use_up_a_question(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from ledger.answer.llm import LLMBusy
    from ledger.api import main as api
    from ledger.api.budget import DailyBudget
    from ledger.pipeline import Ledger

    def busy(*_: object, **__: object) -> None:
        raise LLMBusy(429, "rate", retry_after=30)

    monkeypatch.setattr(Ledger, "ask", busy)
    api.budget = DailyBudget(300, 15)
    api.limiter.per_minute = 1000
    api.app.dependency_overrides[api.get_ledger] = lambda: Ledger.__new__(Ledger)
    try:
        r = TestClient(api.app).post("/ask", json={"question": "What was Nike revenue in 2023?"})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    assert (
        r.json()["detail"]["error"] == "model_busy"
        and "30 seconds" in r.json()["detail"]["message"]
    )
    assert api.budget.remaining() == 300  # refunded


def test_missing_year_note_says_what_is_loaded() -> None:
    from ledger.retrieve.coverage import missing_year_note

    docs = [
        {"ticker": "HD", "fiscal_year": 2023},
        {"ticker": "COST", "fiscal_year": 2021},
        {"ticker": "COST", "fiscal_year": 2022},
    ]
    note = missing_year_note(docs, "COST", [2009], "Costco")
    assert note == "I have Costco filings for 2021, 2022, but none for 2009."
    hd = missing_year_note(docs, "HD", [2024], "Home Depot", "start")
    assert hd and "none for 2024" in hd and "fiscal 2022" in hd and "labelled 2023" in hd
    assert missing_year_note(docs, "COST", [2022], "Costco") is None  # it is loaded
    assert missing_year_note(docs, "COST", [], "Costco") is None  # no year asked
    assert missing_year_note(docs, "ZZZ", [2023], "Nobody") is None  # nothing loaded for it


# -- one wider look before refusing -------------------------------------------------------------


def _answer_from(user: str) -> str:
    n = passage_number(user, "Operating income was $630 million")
    return claims_json(
        {"text": "Acme Widgets' operating income was $630 million.", "citations": [n]}
    )


def test_a_refusal_gets_one_wider_look_and_can_become_an_answer(
    make_ledger: Callable[..., tuple[Ledger, object]],
) -> None:
    prompts: list[str] = []

    def respond(system: str, user: str) -> str:
        prompts.append(user)
        if len(prompts) == 1:  # the first, narrow look: the model says it is not there
            return claims_json(answerable=False)
        return _answer_from(user)

    ledger, llm = make_ledger(respond)
    ledger.config.retrieval.top_k = 1  # narrow enough that the wide look finds more
    a = ledger.ask("What was Acme Widgets operating income in 2024?")
    assert not a.refused and "630" in a.answer and a.verified is True
    assert len(llm.calls) == 2  # type: ignore[attr-defined]
    assert prompts[1].count("<passage ") > prompts[0].count("<passage ")


def test_a_wider_look_that_still_finds_nothing_refuses_after_one_extra_call(
    make_ledger: Callable[..., tuple[Ledger, object]],
) -> None:
    ledger, llm = make_ledger(lambda s, u: claims_json(answerable=False))
    ledger.config.retrieval.top_k = 1
    a = ledger.ask("What was Acme Widgets operating income in 2024?")
    assert a.refused and len(llm.calls) == 2  # type: ignore[attr-defined]


def test_the_wider_look_can_be_switched_off_and_skips_when_nothing_new(
    make_ledger: Callable[..., tuple[Ledger, object]],
) -> None:
    ledger, llm = make_ledger(lambda s, u: claims_json(answerable=False))
    ledger.config.retrieval.top_k = 1
    ledger.config.answer.retry_wide_on_refusal = False
    assert ledger.ask("What was Acme Widgets operating income in 2024?").refused
    assert len(llm.calls) == 1  # type: ignore[attr-defined]
    ledger2, llm2 = make_ledger(lambda s, u: claims_json(answerable=False))
    ledger2.config.retrieval.top_k = 50  # the first look already saw everything there is
    assert ledger2.ask("What was Acme Widgets operating income in 2024?").refused
    assert len(llm2.calls) == 1  # type: ignore[attr-defined]
