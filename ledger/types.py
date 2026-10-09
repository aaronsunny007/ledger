"""Data shapes shared across ingestion, retrieval, answering and the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """One retrievable passage plus the metadata needed to cite it (ING-3)."""

    id: str
    text: str
    company: str
    ticker: str
    fiscal_year: int | None = None
    form_type: str = "10-K"
    section: str = ""
    anchor: str = ""  # HTML anchor or "page-12" for PDFs; used by the citation viewer
    source_url: str = ""
    doc_id: str = ""
    is_table: bool = False


class ScoredChunk(BaseModel):
    chunk: Chunk
    score: float
    # Rank in each retrieval stage, so the trace shows what each stage contributed.
    ranks: dict[str, int] = Field(default_factory=dict)


class Citation(BaseModel):
    n: int  # the [n] marker shown to the user
    chunk_id: str
    company: str
    fiscal_year: int | None
    section: str
    source_url: str
    anchor: str
    quote: str  # short excerpt of the chunk, for hover text


class Claim(BaseModel):
    text: str
    citations: list[int]  # citation numbers
    calculation: str | None = None
    result: float | None = None
    verified: bool | None = None  # None: no numbers to verify
    verifier_status: str | None = None


Confidence = Literal["high", "medium", "low"]


class Answer(BaseModel):
    """What POST /ask returns (ANS-4)."""

    question: str
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
    closest_passages: list[Citation] = Field(default_factory=list)
    confidence: Confidence = "low"
    verified: bool | None = None
    regenerated: bool = False
    cache_hit: bool = False
    model: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    request_id: str = ""
    # Every passage the generator saw, for the eval's recall@k. Not sent by the API.
    retrieved: list[Chunk] = Field(default_factory=list, exclude=True)
