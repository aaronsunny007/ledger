"""Print "TICKER YEAR" for the filings the given golden question ids need.

    python eval/needs_for_ids.py financebench_id_01079 financebench_id_00757

Used by workflows that run on a handful of questions, so they download only
those filings (``ledger download --tickers T --years Y``).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.evaluation.golden import load_golden  # noqa: E402


def main(ids: list[str]) -> int:
    wanted = set(ids)
    needs: dict[tuple[str, int], None] = {}
    for item in load_golden():
        if item.id in wanted and item.ticker and item.fiscal_year:
            needs.setdefault((item.ticker, item.fiscal_year), None)
    for ticker, year in needs:
        print(ticker, year)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
