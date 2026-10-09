"""Why does retrieval miss the evidence? No LLM needed.

    python eval/diagnose_retrieval.py --split dev --sources financebench --limit 20

For each question it reports:
  - the company/year filters extracted from the question vs the gold ones;
  - the rank of the first retrieved passage that contains the evidence;
  - the best evidence overlap among the retrieved passages; and
  - the best overlap among *all* indexed passages of the right filing.

If the last number is low, the evidence never made it into the index in a
findable form (parsing / chunking). If it is high but retrieval missed it,
ranking is the problem. Writes eval/results/<timestamp>-diagnose.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.config import LedgerConfig, Settings  # noqa: E402
from ledger.evaluation.golden import load_golden  # noqa: E402
from ledger.evaluation.metrics import evidence_overlap  # noqa: E402
from ledger.retrieve.filters import Filters, filters_from_question  # noqa: E402
from ledger.retrieve.store import InMemoryIndex  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--split", default="dev")
    p.add_argument("--sources", nargs="*", default=["financebench"])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--threshold", type=float, default=0.5)
    args = p.parse_args()

    from ledger.answer.llm import FakeLLM
    from ledger.factory import build_ledger

    settings = Settings()
    config = LedgerConfig.load()
    ledger = build_ledger(settings, config, llm=FakeLLM(lambda s, u: "{}"), trace_log=None)
    index = ledger.retriever.index
    assert isinstance(index, InMemoryIndex), "diagnosis reads the in-memory index"

    items = [
        i
        for i in load_golden()
        if i.split == args.split
        and i.source in args.sources
        and "out-of-corpus" not in i.tags
        and i.answer_type != "refusal"
        and any(e.text for e in i.evidence)
    ][: args.limit]

    rows = []
    for item in items:
        extracted = filters_from_question(item.question, ledger.registry)
        gold = Filters(tickers=[item.ticker], years=[item.fiscal_year] if item.fiscal_year else [])
        hits = {}
        for name, f in (("extracted", extracted), ("gold", gold)):
            got = ledger.retriever.retrieve(item.question, f)  # all passages the model sees
            overlaps = [evidence_overlap(c.chunk.text, item) for c in got]
            first = next((r for r, o in enumerate(overlaps, 1) if o >= args.threshold), None)
            hits[name] = {
                "first_hit_rank": first,
                "best_overlap": round(max(overlaps, default=0), 2),
                "top": [f"{c.chunk.section[:24]} | {c.chunk.text[:90]!r}" for c in got[:3]],
            }
        doc_chunks = [
            c for c in index.chunks if c.ticker == item.ticker and c.fiscal_year == item.fiscal_year
        ]
        scored = sorted(
            ((evidence_overlap(c.text, item), c) for c in doc_chunks), key=lambda t: -t[0]
        )
        best_any, best_chunk = scored[0] if scored else (0.0, None)
        rows.append(
            {
                "id": item.id,
                "question": item.question[:160],
                "gold_filters": f"{item.ticker} {item.fiscal_year}",
                "extracted_filters": f"{','.join(extracted.tickers)} {extracted.years}",
                "chunks_in_filing": len(doc_chunks),
                "best_overlap_in_filing": round(best_any, 2),
                "best_chunk": (best_chunk.text[:160] if best_chunk else ""),
                "evidence": item.evidence[0].text[:160] if item.evidence else "",
                **{
                    f"{k}_{m}": v[m]
                    for k, v in hits.items()
                    for m in ("first_hit_rank", "best_overlap")
                },
                "top_extracted": hits["extracted"]["top"],
            }
        )

    n = len(rows)

    def share(pred):
        return f"{sum(1 for r in rows if pred(r))}/{n}"

    summary = {
        "questions": n,
        "filters extracted correctly": share(
            lambda r: (
                r["extracted_filters"].split(" ")[0] == r["gold_filters"].split(" ")[0]
                and r["gold_filters"].split(" ")[1] in r["extracted_filters"]
            )
        ),
        "filing indexed at all": share(lambda r: r["chunks_in_filing"] > 0),
        f"evidence findable in filing (overlap >= {args.threshold})": share(
            lambda r: r["best_overlap_in_filing"] >= args.threshold
        ),
        "hit in passages given to model, extracted filters": share(
            lambda r: r["extracted_first_hit_rank"]
        ),
        "hit in passages given to model, gold filters": share(lambda r: r["gold_first_hit_rank"]),
    }

    out = ROOT / "eval" / "results" / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-diagnose.md"
    lines = [
        "# Retrieval diagnosis",
        "",
        f"Config: `{json.dumps(config.retrieval.model_dump())}`",
        "",
        "| check | result |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in summary.items()]
    lines += ["", "## Per question", ""]
    for r in rows:
        lines += [
            f"### {r['id']}",
            "",
            f"- **Q:** {r['question']}",
            f"- filters gold `{r['gold_filters']}` vs extracted `{r['extracted_filters']}`",
            f"- chunks in filing: {r['chunks_in_filing']}, best evidence overlap in filing: "
            f"{r['best_overlap_in_filing']}",
            f"- first hit rank: extracted filters {r['extracted_first_hit_rank']}, "
            f"gold filters {r['gold_first_hit_rank']} "
            f"(best overlap {r['extracted_best_overlap']} / {r['gold_best_overlap']})",
            f"- evidence starts: `{r['evidence']!r}`",
            f"- best indexed chunk: `{r['best_chunk']!r}`",
            "- top retrieved:",
            *[f"  - `{t}`" for t in r["top_extracted"]],
            "",
        ]
    out.write_text("\n".join(lines))
    print("\n".join(lines[:12]))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
