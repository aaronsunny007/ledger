from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from ledger.api import main as api
from ledger.api.budget import DailyBudget
from ledger.pipeline import Ledger
from tests.conftest import claims_json, passage_number


@pytest.fixture
def client(make_ledger: Callable[..., tuple[Ledger, object]]) -> Iterator[TestClient]:
    def respond(system: str, user: str) -> str:
        n = passage_number(user, "Operating income was $630 million")
        return claims_json(
            {"text": "Acme Widgets' operating income was $630 million in FY2024.", "citations": [n]}
        )

    ledger, _ = make_ledger(respond)
    api.app.dependency_overrides[api.get_ledger] = lambda: ledger
    api.limiter.per_minute = 1000
    api.spend.spent = 0.0
    api.budget = DailyBudget(300, 15)
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_ask_returns_cited_verified_answer(client: TestClient) -> None:
    r = client.post("/ask", json={"question": "What was Acme Widgets operating income in 2024?"})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False and body["verified"] is True
    assert body["claims"][0]["citations"] == [1]
    assert {"answer", "claims", "refused", "latency_ms", "cost_usd"} <= body.keys()


def test_documents(client: TestClient) -> None:
    tickers = {d["ticker"] for d in client.get("/documents").json()}
    assert tickers == {"ACME", "BETA"}


def test_stream_ends_with_answer(client: TestClient) -> None:
    with client.stream(
        "POST", "/ask/stream", json={"question": "What was Acme Widgets operating income in 2024?"}
    ) as r:
        text = "".join(r.iter_text())
    assert "event: status" in text and "event: answer" in text


def test_rate_limit(client: TestClient) -> None:
    api.limiter.per_minute = 1
    api.limiter._hits.clear()
    q = {"question": "What was Acme Widgets operating income in 2024?"}
    assert client.post("/ask", json=q).status_code == 200
    assert client.post("/ask", json=q).status_code == 429


def test_spend_cap(client: TestClient) -> None:
    api.spend.spent = api.spend.cap_usd
    r = client.post("/ask", json={"question": "What was Acme Widgets operating income in 2024?"})
    assert r.status_code == 503


def test_too_long_question_rejected(client: TestClient) -> None:
    assert client.post("/ask", json={"question": "x" * 3000}).status_code == 422


def test_feedback(client: TestClient, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    monkeypatch.setattr(api, "FEEDBACK_LOG", Path(str(tmp_path)) / "fb.jsonl")
    r = client.post("/feedback", json={"request_id": "abc", "thumbs_up": False})
    assert r.json() == {"status": "recorded"}


ASK = {"question": "What was Acme Widgets operating income in 2024?"}


def test_client_quota_returns_429_with_reset_message(client: TestClient) -> None:
    api.budget = DailyBudget(300, 1)
    assert client.post("/ask", json=ASK).status_code == 200
    r = client.post("/ask", json=ASK)
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["error"] == "daily_quota_exhausted" and detail["scope"] == "client"
    assert "free daily quota" in detail["message"] and "UTC" in detail["message"]
    assert int(r.headers["retry-after"]) == detail["retry_after_seconds"] > 0
    # another client is still served (the first hop of X-Forwarded-For names the client)
    other = client.post("/ask", json=ASK, headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.1"})
    assert other.status_code == 200


def test_global_quota_blocks_everyone_and_stream_too(client: TestClient) -> None:
    api.budget = DailyBudget(1, 15)
    assert client.post("/ask", json=ASK, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    r = client.post("/ask", json=ASK, headers={"X-Forwarded-For": "2.2.2.2"})
    assert r.status_code == 429 and r.json()["detail"]["scope"] == "global"
    s = client.post("/ask/stream", json=ASK, headers={"X-Forwarded-For": "2.2.2.2"})
    assert s.status_code == 429
    assert client.get("/health").json()["daily_budget_remaining"] == 0


def test_advice_refusal_and_too_long_do_not_count(client: TestClient) -> None:
    advice = {"question": "Should I buy Acme Widgets stock?"}
    assert client.post("/ask", json=advice).json()["refused"] is True
    assert client.post("/ask", json={"question": "x" * 1500}).status_code == 422
    assert api.budget.remaining() == 300
    assert client.post("/ask", json=ASK).status_code == 200
    assert api.budget.remaining() == 299


def test_cache_hit_does_not_count(make_ledger: Callable[..., tuple[Ledger, object]]) -> None:
    def respond(system: str, user: str) -> str:
        n = passage_number(user, "Operating income was $630 million")
        return claims_json({"text": "Operating income was $630 million.", "citations": [n]})

    ledger, _ = make_ledger(respond, cache=True)
    api.app.dependency_overrides[api.get_ledger] = lambda: ledger
    api.limiter.per_minute = 1000
    api.budget = DailyBudget(300, 15)
    try:
        c = TestClient(api.app)
        assert c.post("/ask", json=ASK).json()["cache_hit"] is False
        assert api.budget.remaining() == 299
        assert c.post("/ask", json=ASK).json()["cache_hit"] is True
        assert api.budget.remaining() == 299
    finally:
        api.app.dependency_overrides.clear()


def test_provider_quota_exhausted_maps_to_same_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ledger.answer.llm import QuotaExhausted

    def boom(*_: object, **__: object) -> None:
        raise QuotaExhausted(429, "daily limit")

    monkeypatch.setattr(Ledger, "ask", boom)
    r = client.post("/ask", json=ASK)
    assert r.status_code == 429 and r.json()["detail"]["error"] == "daily_quota_exhausted"
