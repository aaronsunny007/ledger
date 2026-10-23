"""COST-3 for a public demo: a daily cap on questions that call the free LLM tier.

Two counters, both reset when the provider's daily quota does (midnight
Pacific, 07:00 UTC while daylight saving is on): one for the whole service
and one per client. Only answers that really called the model are counted;
semantic-cache hits and investment-advice refusals are free. Counters live
in memory; an optional JSON file lets them survive a restart within the day.
Clients are stored as a short hash of their IP, never the address itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

RESET_HOUR_UTC = 7  # midnight Pacific; 08:00 UTC in winter, see docs/deploy-demo.md


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BudgetExhausted(Exception):
    def __init__(self, scope: str, resets_at: datetime, now: datetime):
        super().__init__(scope)
        self.scope = scope  # "global" or "client"
        self.resets_at = resets_at
        self.retry_after = max(1, int((resets_at - now).total_seconds()))

    @property
    def message(self) -> str:
        when = self.resets_at.strftime("%H:%M UTC")
        if self.scope == "client":
            who = "You have used your share of the free daily quota for this demo."
        else:
            who = "The free daily quota for this demo is used up."
        return f"{who} It resets at {when} (midnight Pacific). Please come back then."

    def detail(self) -> dict[str, object]:
        return {
            "error": "daily_quota_exhausted",
            "scope": self.scope,
            "message": self.message,
            "resets_at": self.resets_at.isoformat(timespec="seconds"),
            "retry_after_seconds": self.retry_after,
        }


class DailyBudget:
    def __init__(
        self,
        daily: int,
        per_client: int,
        path: Path | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.daily = daily
        self.per_client = per_client
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._day = ""
        self._total = 0
        self._clients: dict[str, int] = {}
        self._load()

    # -- time ----------------------------------------------------------------

    def _window(self, now: datetime) -> tuple[str, datetime]:
        """The quota day ``now`` falls in, and when the next one starts."""
        start = now.astimezone(UTC).replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
        if now < start:
            start -= timedelta(days=1)
        return start.date().isoformat(), start + timedelta(days=1)

    def _roll(self, now: datetime) -> datetime:
        day, resets_at = self._window(now)
        if day != self._day:
            self._day, self._total, self._clients = day, 0, {}
        return resets_at

    # -- counting ------------------------------------------------------------

    @staticmethod
    def _key(client: str) -> str:
        return hashlib.sha256(client.encode()).hexdigest()[:16]

    def _check(self, client: str, now: datetime) -> None:
        resets_at = self._roll(now)
        if self._total >= self.daily:
            raise BudgetExhausted("global", resets_at, now)
        if self._clients.get(self._key(client), 0) >= self.per_client:
            raise BudgetExhausted("client", resets_at, now)

    def check(self, client: str) -> None:
        """Raise ``BudgetExhausted`` if this client may not ask another question."""
        with self._lock:
            self._check(client, self._clock())

    def reserve(self, client: str) -> None:
        """Count one question before it runs, so concurrent requests cannot overshoot."""
        with self._lock:
            now = self._clock()
            self._check(client, now)
            key = self._key(client)
            self._total += 1
            self._clients[key] = self._clients.get(key, 0) + 1
            self._save()

    def refund(self, client: str) -> None:
        """Give a reservation back: the answer did not call the model."""
        with self._lock:
            self._roll(self._clock())
            key = self._key(client)
            if self._total > 0 and self._clients.get(key, 0) > 0:
                self._total -= 1
                self._clients[key] -= 1
                self._save()

    def provider_exhausted(self) -> BudgetExhausted:
        """The provider itself refused (its quota ran out before ours): same message."""
        now = self._clock()
        return BudgetExhausted("global", self._window(now)[1], now)

    def remaining(self) -> int:
        with self._lock:
            self._roll(self._clock())
            return max(0, self.daily - self._total)

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            if data["day"] == self._window(self._clock())[0]:
                self._day = data["day"]
                self._total = int(data["total"])
                self._clients = {str(k): int(v) for k, v in data["clients"].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass  # a missing or corrupt file just means starting the day from zero

    def _save(self) -> None:
        if self.path is None:
            return
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps({"day": self._day, "total": self._total, "clients": self._clients})
            )
            os.replace(tmp, self.path)
        except OSError:
            pass  # persistence is best effort; the in-memory counters still hold
