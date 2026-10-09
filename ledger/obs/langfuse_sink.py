"""Send traces to Langfuse (free cloud tier). Needs the ``tracing`` extra."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ledger.obs.tracing import Trace


class LangfuseSink:
    def __init__(self, public_key: str, secret_key: str, host: str):
        from langfuse import Langfuse

        self._lf: Any = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    def emit(self, trace: Trace) -> None:
        f = trace.fields
        t = self._lf.trace(
            id=trace.request_id,
            name="ask",
            input={"question": trace.question},
            output={"answer": f.get("answer"), "refused": f.get("refused")},
            metadata={k: v for k, v in f.items() if k != "answer"},
        )
        for s in trace.spans:
            start = datetime.fromtimestamp(trace.started + s.start, tz=UTC)
            end = datetime.fromtimestamp(trace.started + s.start + s.ms / 1000, tz=UTC)
            if s.name.startswith("generate"):
                t.generation(
                    name=s.name,
                    start_time=start,
                    end_time=end,
                    model=s.attrs.get("model"),
                    usage={
                        "input": s.attrs.get("input_tokens", 0),
                        "output": s.attrs.get("output_tokens", 0),
                    },
                    metadata=s.attrs,
                )
            else:
                t.span(name=s.name, start_time=start, end_time=end, metadata=s.attrs)

    def score(self, request_id: str, value: float, comment: str | None = None) -> None:
        """OBS-4: thumbs up (1) / down (0) attached to the trace."""
        self._lf.score(trace_id=request_id, name="user_feedback", value=value, comment=comment)
