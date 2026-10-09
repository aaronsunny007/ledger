"""The golden set: one JSONL file per source, one question per line.

Fields
    id            stable id, e.g. "fb-0042", "xbrl-AAPL-2023-revenue"
    source        financebench | xbrl | handwritten
    question      what the user types
    answer        the gold answer as text
    answer_type   numeric | text | refusal
    value         gold number for numeric answers (dollars, not millions;
                  percentages as 12.5 for 12.5%)
    unit          usd | percent | ratio | count | ""
    tolerance     relative tolerance for numeric match (PRF: 0.01, XBRL 0.005)
    ticker, fiscal_year   what the question is about
    evidence      [{"doc_id": ..., "text": ...}] passages that support the answer
    tags          e.g. ["needs-arithmetic"], ["out-of-corpus"], ["injection"]
    split         dev | test   (20 / 80, fixed by hashing the id; never tune on test)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "eval" / "golden"
Split = Literal["dev", "test"]


class Evidence(BaseModel):
    doc_id: str = ""
    text: str = ""
    page: int | None = None


class GoldenItem(BaseModel):
    id: str
    source: Literal["financebench", "xbrl", "handwritten"]
    question: str
    answer: str = ""
    answer_type: Literal["numeric", "text", "refusal"] = "numeric"
    value: float | None = None
    unit: str = ""
    tolerance: float = 0.01
    ticker: str = ""
    fiscal_year: int | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    split: Split = "test"


def assign_split(item_id: str, dev_fraction: float = 0.2) -> Split:
    h = int(hashlib.sha256(item_id.encode()).hexdigest()[:8], 16)
    return "dev" if (h % 1000) / 1000 < dev_fraction else "test"


def load_golden(paths: Iterable[Path] | None = None) -> list[GoldenItem]:
    paths = list(paths) if paths is not None else sorted(GOLDEN_DIR.glob("*.jsonl"))
    items = []
    for p in paths:
        for line in p.read_text().splitlines():
            if line.strip():
                items.append(GoldenItem.model_validate(json.loads(line)))
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ids in golden set")
    return items


def write_golden(path: Path, items: Iterable[GoldenItem]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w") as f:
        for item in items:
            f.write(item.model_dump_json(exclude_defaults=False) + "\n")
            n += 1
    return n


def smoke_set(items: list[GoldenItem], n: int = 50) -> list[GoldenItem]:
    """CI-1: a fixed, cheap subset drawn from the dev split, balanced by source."""
    dev = sorted((i for i in items if i.split == "dev"), key=lambda i: i.id)
    by_source: dict[str, list[GoldenItem]] = {}
    for i in dev:
        by_source.setdefault(i.source, []).append(i)
    out: list[GoldenItem] = []
    while len(out) < n and any(by_source.values()):
        for src in sorted(by_source):
            if by_source[src] and len(out) < n:
                out.append(by_source[src].pop(0))
    return out
