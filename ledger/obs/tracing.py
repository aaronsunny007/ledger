"""OBS-1, OBS-2, OBS-5: per-request traces and structured JSON logs.

A ``Trace`` collects timed spans (parse, cache, retrieve, generate, verify)
and request-level fields (tokens, cost, cache hit, verifier result,
refusal). When it finishes it is written as one JSON log line carrying the
request ID, and handed to any configured sinks (Langfuse, the local
metrics file the dashboard reads).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("ledger.trace")


@dataclass
class Span:
    name: str
    start: float
    ms: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    question: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    started: float = field(default_factory=time.time)
    spans: list[Span] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)
    _t0: float = field(default_factory=time.monotonic)

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Span]:
        s = Span(name=name, start=time.monotonic() - self._t0, attrs=dict(attrs))
        t = time.monotonic()
        try:
            yield s
        finally:
            s.ms = round((time.monotonic() - t) * 1000, 1)
            self.spans.append(s)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ts": self.started,
            "question": self.question,
            "latency_ms": self.elapsed_ms(),
            "stages_ms": {s.name: s.ms for s in self.spans},
            "spans": [s.__dict__ for s in self.spans],
            **self.fields,
        }


class TraceSink(Protocol):
    def emit(self, trace: Trace) -> None: ...


class JsonlSink:
    """Appends one line per request; ``ledger.obs.dashboard`` reads it."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, trace: Trace) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(trace.to_dict(), default=str) + "\n")


class Tracer:
    def __init__(self, sinks: list[TraceSink] | None = None):
        self.sinks = sinks or []

    def start(self, question: str) -> Trace:
        return Trace(question=question)

    def finish(self, trace: Trace) -> None:
        log.info("request", extra={"trace": trace.to_dict()})
        for sink in self.sinks:
            try:
                sink.emit(trace)
            except Exception:  # tracing must never break answering
                log.exception("trace sink %s failed", type(sink).__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        trace = getattr(record, "trace", None)
        if trace:
            payload.update(trace)
        rid = getattr(record, "request_id", None)
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
