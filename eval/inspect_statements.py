"""Which filings have their primary statements tagged? No LLM, no index.

    python eval/inspect_statements.py                 # every downloaded filing
    python eval/inspect_statements.py KHC:2022 PEP:2021

Statement pinning only helps when ingest found the balance sheet, income
statement and cash flow statement. For each filing this reports which were
found and, for each one missing, the near misses: tables whose title matched
but whose rows did not (or the reverse), with the text just before them.
Writes eval/results/statements-coverage.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.ingest.parse import parse_html  # noqa: E402
from ledger.ingest.statements import (  # noqa: E402
    _SIGNATURE,
    _TITLES,
    STATEMENTS,
    classify_statements,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "eval" / "results" / "statements-coverage.md"


def _one_line(text: str, n: int) -> str:
    return " ".join(text.split())[:n].replace("|", "/")


def inspect(path: Path) -> tuple[dict[str, int], list[str]]:
    doc = parse_html(path.read_bytes())
    classify_statements(doc)
    found = {b.statement: len(b.text) for b in doc.blocks if b.statement}
    notes: list[str] = []
    missing = [k for k in STATEMENTS if k not in found]
    if not missing:
        return found, notes
    recent: list[str] = []
    for b in doc.blocks:
        if not b.is_table:
            recent = [*recent, b.text][-3:]
            continue
        head = " ".join(recent) + " " + b.text[:300]
        for kind in missing:
            title = bool(_TITLES[kind].search(head))
            rows = [bool(p.search(b.text)) for p in _SIGNATURE[kind]]
            # A near miss: the title matched, or every signature row matched.
            if title or all(rows):
                notes.append(
                    f"- `{kind}` title={'Y' if title else 'n'} rows={rows} "
                    f"len={len(b.text)} section={b.section!r}\n"
                    f"  - before: {_one_line(' / '.join(recent), 220)}\n"
                    f"  - table: {_one_line(b.text, 220)}"
                )
    return found, notes


def main() -> int:
    wanted = {tuple(a.split(":")) for a in sys.argv[1:]}
    files = sorted(RAW.glob("*/*/filing.htm"))
    if wanted:
        files = [f for f in files if (f.parent.parent.name, f.parent.name) in wanted]
    if not files:
        print("no filings found under", RAW)
        return 1
    rows, details = [], []
    counts = dict.fromkeys(STATEMENTS, 0)
    for f in files:
        ticker, year = f.parent.parent.name, f.parent.name
        try:
            found, notes = inspect(f)
        except Exception as e:  # report and keep going
            rows.append(f"| {ticker} | {year} | error: {type(e).__name__}: {e} | | |")
            continue
        for k in found:
            counts[k] += 1
        cells = " | ".join(f"{found[k]:,}" if k in found else "**missing**" for k in STATEMENTS)
        rows.append(f"| {ticker} | {year} | {cells} |")
        if notes:
            details.append(f"### {ticker} {year}\n\n" + "\n".join(notes[:12]))
        print(ticker, year, {k: found.get(k) for k in STATEMENTS}, flush=True)
    n = len(files)
    summary = ", ".join(f"{k} {counts[k]}/{n}" for k in STATEMENTS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Primary statement coverage\n\n"
        f"Filings: {n}. Found: {summary}.\n\n"
        "Cells give the tagged table's size in characters.\n\n"
        "| Ticker | Year | Balance sheet | Income | Cash flow |\n|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n## Near misses for missing statements\n\n"
        + ("\n\n".join(details) or "None.")
        + "\n"
    )
    print(summary)
    print("wrote", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
