"""Command line: ``ledger download | ingest | ask | documents``."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import yaml

from ledger.config import ROOT, LedgerConfig, Settings


def _corpus() -> dict[str, list[dict[str, object]]]:
    data = yaml.safe_load((ROOT / "configs" / "corpus.yaml").read_text())
    assert isinstance(data, dict)
    return data


def cmd_download(args: argparse.Namespace) -> None:
    from ledger.ingest.edgar import EdgarClient, download_filings

    s = Settings()
    corpus = _corpus()
    years = args.years or corpus.get("years", [])
    client = EdgarClient(s.sec_user_agent)
    wanted = {t.upper() for t in args.tickers or []}
    for c in corpus["companies"]:
        t = str(c["ticker"])
        if wanted and t not in wanted:
            continue
        company_years = args.years or c.get("years") or years
        try:
            download_filings(
                client,
                t,
                [int(y) for y in company_years],  # type: ignore[union-attr]
                Path(args.raw_dir),
                str(corpus.get("form", "10-K")),
            )
        except Exception as e:
            logging.error("%s: %s", t, e)


def cmd_ingest(args: argparse.Namespace) -> None:
    from ledger.ingest.chunk import get_chunker
    from ledger.ingest.loader import folder_docs
    from ledger.ingest.pipeline import Manifest, ingest, sec_raw_docs
    from ledger.retrieve.embed import get_embedder
    from ledger.retrieve.store import InMemoryIndex

    s = Settings()
    cfg = LedgerConfig.load(Path(args.config) if args.config else None)
    embedder = get_embedder(cfg.retrieval.embedder)
    chunker = get_chunker(cfg.chunking.strategy, cfg.chunking.size, cfg.chunking.overlap)
    docs = folder_docs(Path(args.folder)) if args.folder else sec_raw_docs(Path(args.raw_dir))
    if s.store == "postgres":
        from ledger.retrieve.pgstore import PgVectorIndex

        index: object = PgVectorIndex(s.database_url, embedder.dim)
        manifest = Manifest(ROOT / "data" / "processed" / "manifest-postgres.json")
    else:
        index_dir = s.index_path / cfg.index_name()
        index = InMemoryIndex.load(index_dir)
        manifest = Manifest(index_dir / "manifest.json")
    report = ingest(docs, index, embedder, chunker, manifest)  # type: ignore[arg-type]
    if isinstance(index, InMemoryIndex):
        index.save(index_dir)
    print(json.dumps(report.__dict__, indent=2))


def cmd_ask(args: argparse.Namespace) -> None:
    from ledger.factory import build_ledger

    ledger = build_ledger()
    print(ledger.ask(" ".join(args.question)).model_dump_json(indent=2))


def cmd_documents(_: argparse.Namespace) -> None:
    from ledger.factory import build_ledger

    for d in build_ledger().retriever.index.documents():
        print(f"{d['ticker']:<6} {d['fiscal_year']}  {d['chunks']:>5} chunks  {d['doc_id']}")


def main(argv: list[str] | None = None) -> None:
    from ledger.obs.tracing import configure_logging

    configure_logging()
    p = argparse.ArgumentParser(prog="ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="fetch 10-K HTML from SEC EDGAR (ING-1)")
    d.add_argument("--tickers", nargs="*")
    d.add_argument("--years", nargs="*", type=int)
    d.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    d.set_defaults(fn=cmd_download)

    i = sub.add_parser("ingest", help="parse, chunk, embed and index")
    i.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    i.add_argument("--folder", help="YAML config for a generic folder of documents (ING-6)")
    i.add_argument("--config", help="retrieval.yaml to use")
    i.set_defaults(fn=cmd_ingest)

    a = sub.add_parser("ask", help="ask one question")
    a.add_argument("question", nargs="+")
    a.set_defaults(fn=cmd_ask)

    sub.add_parser("documents", help="list ingested filings").set_defaults(fn=cmd_documents)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
