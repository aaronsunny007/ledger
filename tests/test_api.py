from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from ledger.api import main as api
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
