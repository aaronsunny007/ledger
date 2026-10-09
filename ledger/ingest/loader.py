"""ING-6: point Ledger at any folder of PDF / HTML / text files via YAML.

Example ``configs/my_docs.yaml``::

    company: Acme Ltd
    ticker: ACME
    root: ~/Documents/acme
    include: ["**/*.pdf", "**/*.html", "**/*.htm", "**/*.txt", "**/*.md"]
    # Optional: take the fiscal year from the file name, e.g. "report_2024.pdf"
    year_pattern: "(20\\d{2})"
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from ledger.ingest.chunk import DocMeta
from ledger.ingest.parse import Block, ParsedDoc, parse_html
from ledger.ingest.pipeline import SourceDoc


def parse_text(raw: bytes) -> ParsedDoc:
    text = raw.decode("utf-8", errors="replace")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return ParsedDoc(title="", blocks=[Block(text=p, section="") for p in paras])


def parse_pdf(raw: bytes) -> ParsedDoc:
    """One block per paragraph, anchored by page ("page-12") for citations."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    blocks = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for para in re.split(r"\n\s*\n", text):
            para = " ".join(para.split())
            if para:
                blocks.append(Block(text=para, section="", anchor=f"page-{i}"))
    return ParsedDoc(title="", blocks=blocks)


_PARSERS = {
    ".pdf": parse_pdf,
    ".html": parse_html,
    ".htm": parse_html,
    ".txt": parse_text,
    ".md": parse_text,
}


def folder_docs(config_path: Path) -> Iterable[SourceDoc]:
    cfg = yaml.safe_load(config_path.read_text())
    root = Path(cfg["root"]).expanduser()
    if not root.is_absolute():
        root = (config_path.parent / root).resolve()
    patterns = cfg.get("include", ["**/*.pdf", "**/*.htm", "**/*.html", "**/*.txt", "**/*.md"])
    year_re = re.compile(cfg["year_pattern"]) if cfg.get("year_pattern") else None
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path in seen or path.suffix.lower() not in _PARSERS:
                continue
            seen.add(path)
            year = None
            if year_re and (m := year_re.search(path.name)):
                year = int(m.group(1))
            rel = path.relative_to(root).as_posix()
            yield SourceDoc(
                path=path,
                meta=DocMeta(
                    doc_id=f"{cfg['ticker']}:{rel}",
                    company=cfg["company"],
                    ticker=cfg["ticker"],
                    fiscal_year=year,
                    form_type=cfg.get("form_type", "document"),
                    source_url=cfg.get("base_url", "").rstrip("/") + "/" + rel
                    if cfg.get("base_url")
                    else "",
                ),
                parser=_PARSERS[path.suffix.lower()],
            )
