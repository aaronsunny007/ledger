"""The three primary financial statements: find them in a filing, and tell
which ones a question needs.

Most FinanceBench questions (ratios, margins, turnover, capex) are answered
from the balance sheet, income statement or cash flow statement. The
retrieval diagnosis showed these tables were in the index but rarely ranked
in the top 6, because the questions read like formulas rather than like the
tables. So the statements are tagged at ingest, and a question that needs
one gets it directly (``RetrievalConfig.pin_statements``).
"""

from __future__ import annotations

import re

from ledger.ingest.parse import Block, ParsedDoc

BALANCE_SHEET = "balance_sheet"
INCOME = "income"
CASH_FLOW = "cash_flow"
STATEMENTS = (BALANCE_SHEET, INCOME, CASH_FLOW)

_TITLES = {
    BALANCE_SHEET: re.compile(
        r"balance\s*sheets?|statements?\s*of\s*financial\s*(position|condition)", re.I
    ),
    INCOME: re.compile(
        r"statements?\s*of\s*(consolidated\s*)?(operations|income|earnings)(?!\s*and\s*compre)"
        r"(?!.{0,20}comprehensive)",
        re.I,
    ),
    CASH_FLOW: re.compile(r"statements?\s*of\s*cash\s*flows?", re.I),
}

# Row labels a real statement must contain (titles alone also match notes
# and MD&A summaries).
_SIGNATURE = {
    BALANCE_SHEET: (re.compile(r"total\s+assets", re.I), re.compile(r"total\s+liabilities", re.I)),
    INCOME: (
        re.compile(r"revenue|net\s+sales|sales", re.I),
        re.compile(r"net\s+(income|earnings|loss)", re.I),
    ),
    CASH_FLOW: (
        re.compile(r"operating\s+activities", re.I),
        re.compile(r"investing\s+activities", re.I),
    ),
}


def _signature(text: str, kind: str) -> bool:
    return all(p.search(text) for p in _SIGNATURE[kind])


def classify_statements(doc: ParsedDoc, lookback: int = 3) -> None:
    """Set ``Block.statement`` on the primary statement tables of ``doc``.

    A table qualifies when its title (in the table or in the few text blocks
    before it) names the statement and its rows carry the statement's
    signature. Per statement only the largest qualifying table is kept: the
    primary statement is the full one, not a summary of it.
    """
    best: dict[str, Block] = {}
    recent: list[str] = []
    for b in doc.blocks:
        if not b.is_table:
            recent = [*recent, b.text][-lookback:]
            continue
        head = " ".join(recent) + " " + b.text[:300]
        for kind, title in _TITLES.items():
            if title.search(head) and _signature(b.text, kind):
                if kind not in best or len(b.text) > len(best[kind].text):
                    best[kind] = b
                break
    for kind, b in best.items():
        b.statement = kind


_NEEDS = {
    BALANCE_SHEET: re.compile(
        r"balance\s*sheet|statement\s+of\s+financial\s+position|total\s+assets|current\s+assets|"
        r"current\s+liabilit|working\s+capital|quick\s+ratio|current\s+ratio|inventor|"
        r"receivable|\bAR\b|payable|\bDPO\b|\bDSO\b|\bDIO\b|cash\s+conversion|PP&E|"
        r"property,?\s+(plant\s+)?and\s+equipment|fixed\s+asset|total\s+debt|"
        r"debt[-\s]to|equity|\bROA\b|return\s+on\s+assets|liquidity|solvency|leverage",
        re.I,
    ),
    INCOME: re.compile(
        r"income\s+statement|statement\s+of\s+(operations|income|earnings)|\bP&L\b|revenue|"
        r"net\s+sales|\bsales\b|\bCOGS\b|cost\s+of\s+(goods|sales|revenue)|gross\s+(margin|profit)|"
        r"operating\s+(income|margin|profit)|net\s+(income|earnings|profit|loss)|\bEBIT|"
        r"\bEPS\b|earnings\s+per\s+share|effective\s+tax|interest\s+expense|restructuring|"
        r"\bROA\b|return\s+on|turnover|payout\s+ratio|\bDPO\b|\bDSO\b|\bDIO\b|cash\s+conversion",
        re.I,
    ),
    CASH_FLOW: re.compile(
        r"cash\s+flow|capex|capital\s+expenditure|purchases?\s+of\s+property|"
        r"cash\s+(from|provided\s+by)\s+operat|operating\s+cash|free\s+cash|dividends?\s+paid|"
        r"total\s+cash\s+dividends|payout\s+ratio|depreciation|\bD&A\b|share\s+repurchase|buyback",
        re.I,
    ),
}


def statements_needed(question: str) -> list[str]:
    """Which primary statements a question's figures come from."""
    return [kind for kind in STATEMENTS if _NEEDS[kind].search(question)]
