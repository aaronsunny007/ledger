from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ledger.api.budget import BudgetExhausted, DailyBudget


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


def test_per_client_cap(clock: Clock) -> None:
    b = DailyBudget(daily=10, per_client=2, clock=clock)
    b.reserve("1.1.1.1")
    b.reserve("1.1.1.1")
    with pytest.raises(BudgetExhausted) as e:
        b.reserve("1.1.1.1")
    assert e.value.scope == "client"
    b.reserve("2.2.2.2")  # another client is unaffected


def test_global_cap(clock: Clock) -> None:
    b = DailyBudget(daily=2, per_client=10, clock=clock)
    b.reserve("a")
    b.reserve("b")
    with pytest.raises(BudgetExhausted) as e:
        b.check("c")
    assert e.value.scope == "global"
    assert b.remaining() == 0


def test_refund_frees_the_slot(clock: Clock) -> None:
    b = DailyBudget(daily=1, per_client=1, clock=clock)
    b.reserve("a")
    b.refund("a")
    b.reserve("a")  # the cached / refused answer did not use quota
    b.refund("a")
    b.refund("a")  # nothing left to refund; never goes negative
    assert b.remaining() == 1


def test_resets_at_seven_utc(clock: Clock) -> None:
    clock.now = datetime(2026, 10, 16, 6, 59, tzinfo=UTC)
    b = DailyBudget(daily=1, per_client=1, clock=clock)
    b.reserve("a")
    with pytest.raises(BudgetExhausted) as e:
        b.check("a")
    assert e.value.resets_at == datetime(2026, 10, 16, 7, 0, tzinfo=UTC)
    assert e.value.retry_after == 60
    clock.now = datetime(2026, 10, 16, 7, 0, tzinfo=UTC)
    b.check("a")  # new quota day
    assert b.remaining() == 1
    clock.now += timedelta(hours=23, minutes=59)  # still the same quota day
    b.reserve("a")
    with pytest.raises(BudgetExhausted) as e2:
        b.check("a")
    assert e2.value.resets_at == datetime(2026, 10, 17, 7, 0, tzinfo=UTC)


def test_message_says_quota_and_reset_time(clock: Clock) -> None:
    b = DailyBudget(daily=0, per_client=1, clock=clock)
    with pytest.raises(BudgetExhausted) as e:
        b.check("a")
    d = e.value.detail()
    assert d["error"] == "daily_quota_exhausted" and d["retry_after_seconds"] == 19 * 3600
    assert "free daily quota" in str(d["message"]) and "07:00 UTC" in str(d["message"])
    assert "midnight Pacific" in str(d["message"])
    assert b.provider_exhausted().scope == "global"


def test_persistence_survives_restart_and_stores_no_ip(clock: Clock, tmp_path: Path) -> None:
    path = tmp_path / "sub" / "budget.json"
    b = DailyBudget(daily=5, per_client=1, path=path, clock=clock)
    b.reserve("203.0.113.9")
    assert "203.0.113.9" not in path.read_text()
    again = DailyBudget(daily=5, per_client=1, path=path, clock=clock)
    assert again.remaining() == 4
    with pytest.raises(BudgetExhausted):
        again.check("203.0.113.9")
    clock.now += timedelta(days=1)  # a stale file from yesterday is ignored
    assert DailyBudget(daily=5, per_client=1, path=path, clock=clock).remaining() == 5


@pytest.mark.parametrize("content", ["not json", '{"day": "x"}', "[]"])
def test_corrupt_file_starts_from_zero(clock: Clock, tmp_path: Path, content: str) -> None:
    path = tmp_path / "budget.json"
    path.write_text(content)
    assert DailyBudget(daily=5, per_client=1, path=path, clock=clock).remaining() == 5


def test_unwritable_path_does_not_break_counting(clock: Clock, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    b = DailyBudget(daily=5, per_client=5, path=blocker / "budget.json", clock=clock)
    b.reserve("a")
    assert b.remaining() == 4
