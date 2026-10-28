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
