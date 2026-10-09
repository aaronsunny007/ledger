"""OBS-3: dashboard numbers computed from the request log.

Reads ``data/traces/requests.jsonl`` (one line per request, written by
``JsonlSink``) and returns daily p50/p95 latency, cost per request, request
count, error, refusal and verifier-flag rates. The Streamlit app charts
these; Langfuse shows the same data per trace when it is configured.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ledger.evaluation.metrics import percentile


def load_requests(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def daily_stats(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in requests:
        day = datetime.fromtimestamp(float(r.get("ts", 0)), tz=UTC).date().isoformat()
        by_day[day].append(r)
    rows = []
    for day, rs in sorted(by_day.items()):
        misses = [r for r in rs if not r.get("cache_hit")]
        lat = [float(r.get("latency_ms", 0)) for r in misses]
        n = len(rs)
        rows.append(
            {
                "day": day,
                "requests": n,
                "latency_p50_ms": percentile(lat, 0.5),
                "latency_p95_ms": percentile(lat, 0.95),
                "cost_per_request_usd": round(
                    sum(float(r.get("cost_usd") or 0) for r in misses) / len(misses), 6
                )
                if misses
                else 0.0,
                "error_rate": round(sum(1 for r in rs if r.get("error")) / n, 4),
                "refusal_rate": round(sum(1 for r in rs if r.get("refused")) / n, 4),
                "verifier_flag_rate": round(
                    sum(1 for r in rs if r.get("verified") is False) / n, 4
                ),
                "regenerated_rate": round(sum(1 for r in rs if r.get("regenerated")) / n, 4),
                "cache_hit_rate": round(sum(1 for r in rs if r.get("cache_hit")) / n, 4),
            }
        )
    return rows
