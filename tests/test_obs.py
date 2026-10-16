from __future__ import annotations

import json
import logging
from pathlib import Path

from ledger.answer.llm import FakeLLM
from ledger.config import Settings
from ledger.factory import build_ledger
from ledger.obs.dashboard import daily_stats, load_requests
from ledger.obs.tracing import JsonFormatter, JsonlSink, Tracer
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.store import InMemoryIndex
from tests import conftest


def test_trace_spans_and_jsonl_sink(tmp_path: Path) -> None:
    path = tmp_path / "req.jsonl"
    tracer = Tracer([JsonlSink(path)])
    t = tracer.start("q?")
    with t.span("retrieve", n=3):
        pass
    t.fields.update(refused=False, verified=False, cost_usd=0.01, cache_hit=False)
    tracer.finish(t)
    rows = load_requests(path)
    assert rows[0]["request_id"] == t.request_id
    assert "retrieve" in rows[0]["stages_ms"]
    stats = daily_stats([*rows, {"ts": rows[0]["ts"], "cache_hit": True, "refused": True}])
    assert stats[0]["requests"] == 2
    assert stats[0]["verifier_flag_rate"] == 0.5 and stats[0]["cache_hit_rate"] == 0.5
    assert stats[0]["cost_per_request_usd"] == 0.01


def test_broken_sink_does_not_break_requests() -> None:
    class Broken:
        def emit(self, trace: object) -> None:
            raise RuntimeError("down")

    tracer = Tracer([Broken()])
    tracer.finish(tracer.start("q"))  # must not raise


def test_json_formatter_includes_request_id() -> None:
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "hello", None, None)
    rec.request_id = "abc"
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hello" and out["request_id"] == "abc"


def test_load_requests_missing_file(tmp_path: Path) -> None:
    assert load_requests(tmp_path / "nope.jsonl") == []


def test_without_langfuse_tracing_falls_back_to_the_local_file(
    tmp_path: Path, embedder: HashingEmbedder, index: InMemoryIndex
) -> None:
    # Keys set but the package missing or unreachable must not stop startup (offline demo).
    settings = Settings(langfuse_public_key="pk-placeholder", langfuse_secret_key="sk-placeholder")
    log = tmp_path / "requests.jsonl"
    ledger = build_ledger(
        settings,
        conftest.test_config(),
        llm=FakeLLM(lambda s, u: "{}"),
        index=index,
        embedder=embedder,
        trace_log=log,
    )
    assert any(isinstance(s, JsonlSink) for s in ledger.tracer.sinks)
    ledger.ask("Should I buy Acme Widgets stock?")
    assert load_requests(log)[0]["refused"] is True


def test_no_keys_means_only_the_local_sink(
    tmp_path: Path, embedder: HashingEmbedder, index: InMemoryIndex
) -> None:
    ledger = build_ledger(
        Settings(langfuse_public_key="", langfuse_secret_key=""),
        conftest.test_config(),
        llm=FakeLLM(lambda s, u: "{}"),
        index=index,
        embedder=embedder,
        trace_log=tmp_path / "r.jsonl",
    )
    assert [type(s) for s in ledger.tracer.sinks] == [JsonlSink]
