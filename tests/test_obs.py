from __future__ import annotations

import json
import logging
from pathlib import Path

from ledger.obs.dashboard import daily_stats, load_requests
from ledger.obs.tracing import JsonFormatter, JsonlSink, Tracer


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
