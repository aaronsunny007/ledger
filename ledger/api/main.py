"""API-1, API-2: the FastAPI service.

POST /ask           -> Answer JSON
POST /ask/stream    -> server-sent events: stage progress, then the final answer.
                       The answer itself is sent only once verified, never token
                       by token, because no number may reach the user unchecked.
GET  /documents     -> what has been ingested
GET  /health
POST /feedback      -> thumbs up / down attached to a trace (OBS-4)

Run: ``uvicorn ledger.api.main:app --reload``  (OpenAPI docs at /docs)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ledger.answer.llm import LLMBusy, QuotaExhausted
from ledger.api.budget import BudgetExhausted, DailyBudget
from ledger.config import ROOT, Settings
from ledger.pipeline import CacheMiss, Ledger, QuestionTooLong
from ledger.retrieve.filters import Filters
from ledger.types import Answer

FEEDBACK_LOG = ROOT / "data" / "traces" / "feedback.jsonl"
FEEDBACK_LOG_MAX_BYTES = 5_000_000


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # Bounded so one request cannot ask the index to filter on thousands of values.
    tickers: list[Annotated[str, Field(max_length=10)]] = Field(default_factory=list, max_length=20)
    years: list[Annotated[int, Field(ge=1990, le=2100)]] = Field(
        default_factory=list, max_length=20
    )
    sections: list[Annotated[str, Field(max_length=60)]] = Field(
        default_factory=list, max_length=10
    )


class Feedback(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    thumbs_up: bool
    comment: str | None = Field(default=None, max_length=1000)


class RateLimiter:
    """Sliding window per client IP (COST-3)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        if len(self._hits) > 10_000:  # forget visitors who have gone quiet
            for k in [k for k, q in self._hits.items() if not q or now - q[-1] > 60]:
                del self._hits[k]
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


class SpendCap:
    """Hard daily cap on list-price model spend (COST-3)."""

    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self.day = date.today()
        self.spent = 0.0

    def _roll(self) -> None:
        if date.today() != self.day:
            self.day, self.spent = date.today(), 0.0

    def exhausted(self) -> bool:
        self._roll()
        return self.spent >= self.cap_usd

    def add(self, usd: float) -> None:
        self._roll()
        self.spent += usd


settings = Settings()
app = FastAPI(
    title="Ledger",
    version="0.1.0",
    description="Cited, arithmetic-verified answers over company annual reports.",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
)
limiter = RateLimiter(settings.rate_limit_per_minute)
spend = SpendCap(settings.daily_spend_cap_usd)
budget = DailyBudget(
    settings.ledger_daily_budget,
    settings.ledger_per_client_daily,
    Path(settings.ledger_budget_file) if settings.ledger_budget_file else None,
)
_ledger: Ledger | None = None


def get_ledger() -> Ledger:
    global _ledger
    if _ledger is None:
        from ledger.factory import build_ledger

        _ledger = build_ledger(settings)
    return _ledger


LedgerDep = Annotated[Ledger, Depends(get_ledger)]


def _client_ip(request: Request) -> str:
    """The address our own proxy saw. The left of X-Forwarded-For is caller-controlled."""
    fwd = request.headers.get("x-forwarded-for")
    hops = [h.strip() for h in fwd.split(",") if h.strip()] if fwd else []
    if hops and settings.trusted_proxy_hops > 0:
        return hops[max(0, len(hops) - settings.trusted_proxy_hops)]
    return request.client.host if request.client else "?"


def _quota_error(e: BudgetExhausted) -> HTTPException:
    return HTTPException(429, e.detail(), headers={"Retry-After": str(e.retry_after)})


def _guard(request: Request, ledger: Ledger, req: AskRequest) -> None:
    ip = _client_ip(request)
    if not limiter.allow(ip):
        raise HTTPException(429, "Rate limit reached; try again in a minute.")
    try:
        budget.check(ip)
    except BudgetExhausted as e:
        # A cached answer costs no model call, so it is still served after the quota is spent.
        if not ledger.has_cached_answer(req.question, _filters(req)):
            raise _quota_error(e) from e
    if spend.exhausted():
        raise HTTPException(503, "The demo's daily budget is used up; try again tomorrow.")


def _filters(req: AskRequest) -> Filters:
    return Filters(tickers=[t.upper() for t in req.tickers], years=req.years, sections=req.sections)


def _ask(ledger: Ledger, req: AskRequest, client: str) -> Answer:
    try:
        budget.reserve(client)  # counted up front so parallel requests cannot overshoot
    except BudgetExhausted as e:
        try:
            return ledger.ask(req.question, _filters(req), cache_only=True)
        except CacheMiss:
            raise _quota_error(e) from e
        except QuestionTooLong as too_long:
            raise HTTPException(422, str(too_long)) from too_long
    try:
        answer = ledger.ask(req.question, _filters(req))
    except QuestionTooLong as e:
        budget.refund(client)
        raise HTTPException(422, str(e)) from e
    except QuotaExhausted as e:  # the provider's own free quota ran out first
        raise _quota_error(budget.provider_exhausted()) from e
    except LLMBusy as e:  # a per-minute limit: nothing was answered, so the question is not counted
        budget.refund(client)
        wait = max(1, int(e.retry_after))
        raise HTTPException(
            503,
            {
                "error": "model_busy",
                "message": (
                    f"The free model is busy right now. Please try again in about {wait} seconds."
                ),
                "retry_after_seconds": wait,
            },
            headers={"Retry-After": str(wait)},
        ) from e
    if not answer.model or answer.cache_hit:  # no model call: advice refusal, cache, no passage
        budget.refund(client)
    spend.add(answer.cost_usd)
    return answer


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "llm_provider": settings.llm_provider,
        "store": settings.store,
        "daily_budget_remaining": budget.remaining(),
    }


@app.get("/documents")
def documents(ledger: LedgerDep) -> list[dict[str, object]]:
    return ledger.retriever.index.documents()


@app.post("/ask", response_model=Answer)
def ask(req: AskRequest, request: Request, ledger: LedgerDep) -> Answer:
    _guard(request, ledger, req)
    return _ask(ledger, req, _client_ip(request))


@app.post("/ask/stream")
async def ask_stream(req: AskRequest, request: Request, ledger: LedgerDep) -> StreamingResponse:
    _guard(request, ledger, req)
    ip = _client_ip(request)

    async def events() -> AsyncIterator[str]:
        yield _sse("status", {"stage": "retrieving"})
        task = asyncio.create_task(asyncio.to_thread(_ask, ledger, req, ip))
        stages = ["reranking", "drafting", "verifying"]
        i = 0
        while not task.done():
            await asyncio.sleep(0.8)
            if i < len(stages) and not task.done():
                yield _sse("status", {"stage": stages[i]})
                i += 1
        try:
            answer = task.result()
            yield _sse("answer", answer.model_dump())
        except HTTPException as e:
            yield _sse("error", {"status": e.status_code, "detail": e.detail})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/feedback")
def feedback(fb: Feedback, request: Request) -> dict[str, str]:
    if not limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Rate limit reached; try again in a minute.")
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    if FEEDBACK_LOG.exists() and FEEDBACK_LOG.stat().st_size > FEEDBACK_LOG_MAX_BYTES:
        return {"status": "recorded"}  # the log is full; do not let it fill the disk
    with FEEDBACK_LOG.open("a") as f:
        f.write(json.dumps({**fb.model_dump(), "ts": time.time()}) + "\n")
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            from ledger.obs.langfuse_sink import LangfuseSink

            LangfuseSink(
                settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host
            ).score(fb.request_id, float(fb.thumbs_up), fb.comment)
        except Exception:  # the local log above already has it; Langfuse is a bonus
            logging.getLogger(__name__).exception("Langfuse feedback score failed")
    return {"status": "recorded"}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
