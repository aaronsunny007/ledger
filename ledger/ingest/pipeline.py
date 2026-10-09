"""ING-5: idempotent ingestion with a manifest.

The manifest records, per document, the hash of the raw file and the
settings it was indexed with (chunker, size, embedder). Re-running skips a
document whose hash and settings are unchanged, and re-indexes (deleting the
old chunks and invalidating cached answers) when either changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ledger.ingest.chunk import Chunker, DocMeta
from ledger.ingest.parse import ParsedDoc, parse_html
from ledger.retrieve.embed import Embedder
from ledger.retrieve.store import Index

log = logging.getLogger(__name__)


@dataclass
class SourceDoc:
    path: Path
    meta: DocMeta
    parser: Callable[[bytes], ParsedDoc] = parse_html


def sec_raw_docs(raw_dir: Path) -> Iterable[SourceDoc]:
    """Filings saved by ``ledger.ingest.edgar.download_filings``."""
    for meta_path in sorted(raw_dir.glob("*/*/meta.json")):
        m = json.loads(meta_path.read_text())
        yield SourceDoc(
            path=meta_path.parent / "filing.htm",
            meta=DocMeta(
                doc_id=m["doc_id"],
                company=m["company"],
                ticker=m["ticker"],
                fiscal_year=int(m["report_date"][:4]),
                form_type=m["form"],
                source_url=m["url"],
            ),
        )


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict[str, Any]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )

    def is_current(self, doc_id: str, digest: str, settings: dict[str, Any]) -> bool:
        e = self.entries.get(doc_id)
        return bool(e and e["sha256"] == digest and e["settings"] == settings)

    def record(self, doc_id: str, digest: str, settings: dict[str, Any], chunks: int) -> None:
        self.entries[doc_id] = {
            "sha256": digest,
            "settings": settings,
            "chunks": chunks,
            "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2, sort_keys=True))


@dataclass
class IngestReport:
    indexed: list[str]
    skipped: list[str]
    chunks: int


def ingest(
    docs: Iterable[SourceDoc],
    index: Index,
    embedder: Embedder,
    chunker: Chunker,
    manifest: Manifest,
    on_reindex: Callable[[str], object] | None = None,
) -> IngestReport:
    settings = {
        "chunker": chunker.name,
        "embedder": embedder.name,
        "size": getattr(chunker, "size", None),
        "overlap": getattr(chunker, "overlap", None),
    }
    indexed, skipped, total = [], [], 0
    for doc in docs:
        raw = doc.path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if manifest.is_current(doc.meta.doc_id, digest, settings):
            skipped.append(doc.meta.doc_id)
            continue
        if index.delete_doc(doc.meta.doc_id) and on_reindex:
            on_reindex(doc.meta.doc_id)  # CACHE-3
        chunks = chunker.chunk(doc.parser(raw), doc.meta)
        if chunks:
            index.add(chunks, embedder.embed_documents([c.text for c in chunks]))
        manifest.record(doc.meta.doc_id, digest, settings, len(chunks))
        manifest.save()
        indexed.append(doc.meta.doc_id)
        total += len(chunks)
        log.info("indexed %s: %d chunks", doc.meta.doc_id, len(chunks))
    return IngestReport(indexed=indexed, skipped=skipped, chunks=total)
