"""ING-4: three chunking strategies behind one interface.

* ``fixed``   - fixed-size character windows with overlap, ignoring structure.
* ``section`` - packs consecutive blocks of the same 10-K Item together.
* ``table``   - like ``section``, but every table is its own chunk, headed by
  its section, the sentence that introduces it and its units; long tables
  are split by rows with the header row repeated.

The eval compares them; the default is ``table``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from ledger.ingest.parse import Block, ParsedDoc
from ledger.types import Chunk


@dataclass
class DocMeta:
    doc_id: str
    company: str
    ticker: str
    fiscal_year: int | None
    form_type: str = "10-K"
    source_url: str = ""


class Chunker(Protocol):
    name: str

    def chunk(self, doc: ParsedDoc, meta: DocMeta) -> list[Chunk]: ...


def _split_text(text: str, size: int, overlap: int) -> Iterator[str]:
    """Windows of at most ``size`` chars, cut at whitespace where possible."""
    if size <= overlap:
        raise ValueError("chunk size must exceed overlap")
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(" ", start + size // 2, end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            yield piece
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)


def _make(meta: DocMeta, i: int, text: str, block: Block, is_table: bool = False) -> Chunk:
    return Chunk(
        id=f"{meta.doc_id}:{i:05d}",
        text=text,
        company=meta.company,
        ticker=meta.ticker,
        fiscal_year=meta.fiscal_year,
        form_type=meta.form_type,
        section=block.section,
        anchor=block.anchor,
        source_url=meta.source_url,
        doc_id=meta.doc_id,
        is_table=is_table,
    )


class FixedChunker:
    def __init__(self, size: int = 1024, overlap: int = 128):
        self.size, self.overlap = size, overlap
        self.name = f"fixed-{size}"

    def chunk(self, doc: ParsedDoc, meta: DocMeta) -> list[Chunk]:
        # Concatenate everything, remembering which block each offset came from.
        parts, starts, pos = [], [], 0
        for b in doc.blocks:
            starts.append(pos)
            parts.append(b.text)
            pos += len(b.text) + 1
        full = "\n".join(parts)
        out: list[Chunk] = []
        search_from = 0
        for piece in _split_text(full, self.size, self.overlap):
            offset = full.find(piece, search_from)
            search_from = max(offset, 0)
            idx = max(i for i, s in enumerate(starts) if s <= max(offset, 0))
            out.append(_make(meta, len(out), piece, doc.blocks[idx]))
        return out


class SectionChunker:
    name = "section"

    def __init__(self, size: int = 1024, overlap: int = 128):
        self.size, self.overlap = size, overlap

    def chunk(self, doc: ParsedDoc, meta: DocMeta) -> list[Chunk]:
        out: list[Chunk] = []
        group: list[Block] = []

        def flush() -> None:
            if not group:
                return
            text = "\n".join(b.text for b in group)
            for piece in _split_text(text, self.size, self.overlap):
                out.append(_make(meta, len(out), piece, group[0]))
            group.clear()

        for b in doc.blocks:
            size_now = sum(len(g.text) + 1 for g in group)
            if group and (b.section != group[0].section or size_now + len(b.text) > self.size):
                flush()
            group.append(b)
        flush()
        return out


class TableAwareChunker(SectionChunker):
    name = "table"

    def _table_chunks(self, table: Block, intro: str) -> list[str]:
        header = f"[{table.section}]"
        if intro:
            header += f" {intro[:300]}"
        if table.units:
            header += f" (amounts in {table.units})"
        rows = table.text.split("\n")
        # The first row or two usually hold the column years; repeat them.
        head_rows = rows[:2] if len(rows) > 2 else rows[:1]
        budget = max(self.size - len(header) - sum(len(r) + 1 for r in head_rows), 200)
        pieces: list[list[str]] = []
        current: list[str] = []
        used = 0
        for row in rows[len(head_rows) :]:
            if current and used + len(row) + 1 > budget:
                pieces.append(current)
                current, used = [], 0
            current.append(row)
            used += len(row) + 1
        if current or not pieces:
            pieces.append(current)
        return ["\n".join([header, *head_rows, *p]) for p in pieces]

    def chunk(self, doc: ParsedDoc, meta: DocMeta) -> list[Chunk]:
        out: list[Chunk] = []
        prose: list[Block] = []

        def flush_prose() -> None:
            if not prose:
                return
            sub = SectionChunker(self.size, self.overlap)
            for c in sub.chunk(ParsedDoc(doc.title, list(prose)), meta):
                out.append(c.model_copy(update={"id": f"{meta.doc_id}:{len(out):05d}"}))
            prose.clear()

        last_text = ""
        for b in doc.blocks:
            if b.is_table:
                flush_prose()
                for text in self._table_chunks(b, last_text):
                    out.append(_make(meta, len(out), text, b, is_table=True))
            else:
                prose.append(b)
                last_text = b.text
        flush_prose()
        return out


def get_chunker(strategy: str, size: int = 1024, overlap: int = 128) -> Chunker:
    if strategy == "fixed":
        return FixedChunker(size, overlap)
    if strategy == "section":
        return SectionChunker(size, overlap)
    if strategy == "table":
        return TableAwareChunker(size, overlap)
    raise ValueError(f"unknown chunking strategy {strategy!r}")
