"""Turning passage numbers into user-facing citations, with deep links.

A citation link opens the filing on sec.gov and, in browsers that support
URL text fragments (Chrome, Edge, Safari), scrolls to and highlights the
quoted words. That is the zero-infrastructure version of UI-1.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from ledger.types import Chunk, Citation

_HEADER = re.compile(r"^\[[^\]]*\][^\n]*\n")


def quote_for(chunk: Chunk, words: int = 30) -> str:
    text = _HEADER.sub("", chunk.text)
    return " ".join(text.split()[:words])


def deep_link(chunk: Chunk) -> str:
    if not chunk.source_url:
        return ""
    text = _HEADER.sub("", chunk.text)
    if chunk.is_table:
        # Highlight the first row label of the table slice.
        first = next((ln for ln in text.splitlines() if "|" in ln), "")
        snippet = first.split("|")[0].strip()
    else:
        snippet = " ".join(text.split()[:8])
    snippet = re.sub(r"[^\w\s$%.,'-]", " ", snippet).strip()
    if len(snippet) < 4:
        return f"{chunk.source_url}#{chunk.anchor}" if chunk.anchor else chunk.source_url
    return f"{chunk.source_url}#:~:text={quote(snippet, safe='')}"


def to_citation(n: int, chunk: Chunk) -> Citation:
    return Citation(
        n=n,
        chunk_id=chunk.id,
        company=chunk.company,
        fiscal_year=chunk.fiscal_year,
        section=chunk.section,
        source_url=deep_link(chunk),
        anchor=chunk.anchor,
        quote=quote_for(chunk),
    )
