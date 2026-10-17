"""Which primary statements a question's figures come from.

Most FinanceBench and XBRL questions are answered from the balance sheet, the
income statement or the cash flow statement. Ingest tags those tables
(``ledger.ingest.statements``); this decides, from the wording of a question,
which of them to hand to the model directly (``RetrievalConfig.pin_statements``)
instead of hoping that similarity search ranks them. A question that names a
line item ("cash and cash equivalents", "research and development") needs the
statement that carries it even though it never says "balance sheet".

Kept apart from ingest on purpose: this runs at question time, so changing it
must not invalidate indexes built from the filings. ``ledger.ingest.statements``
still holds an older copy of these patterns; it is unused and is deleted the
next time ingest changes anyway (removing it now would force a reindex).
"""

from __future__ import annotations

import re

from ledger.ingest.statements import BALANCE_SHEET, CASH_FLOW, INCOME, STATEMENTS

_NEEDS = {
    BALANCE_SHEET: re.compile(
        r"balance\s*sheet|statement\s+of\s+financial\s+position|total\s+assets|current\s+assets|"
        r"current\s+liabilit|total\s+liabilit|working\s+capital|quick\s+ratio|current\s+ratio|"
        r"inventor|receivable|\bAR\b|payable|\bDPO\b|\bDSO\b|\bDIO\b|cash\s+conversion|"
        r"PP&E|\bPPNE\b|property,?\s+(plant\s+)?and\s+equipment|fixed\s+asset|total\s+debt|"
        r"long-?term\s+debt|short-?term\s+(debt|borrowings)|debt[-\s]to|equity|retained\s+earnings|"
        r"cash\s+and\s+cash\s+equivalents|cash\s+equivalents|marketable\s+securities|goodwill|"
        r"book\s+value|\bROA\b|return\s+on\s+assets|liquidity|solvency|leverage|"
        r"capital[-\s]+intensi",
        re.I,
    ),
    INCOME: re.compile(
        r"income\s+statement|statement\s+of\s+(operations|income|earnings)|\bP&L\b|revenue|"
        r"net\s+sales|\bsales\b|\bCOGS\b|cost\s+of\s+(goods|sales|revenue)|gross\s+(margin|profit)|"
        r"operating\s+(income|margin|profit|expenses?)|net\s+(income|earnings|profit|loss)|\bEBIT|"
        r"research\s+and\s+development|\bR&D\b|selling,?\s+general|\bSG&A\b|"
        r"income\s+before|pre-?tax|income\s+tax|\bEPS\b|earnings\s+per\s+share|diluted|"
        r"effective\s+tax|interest\s+expense|restructuring|"
        r"\bROA\b|return\s+on|turnover|payout\s+ratio|\bDPO\b|\bDSO\b|\bDIO\b|cash\s+conversion|"
        r"capital[-\s]+intensi",
        re.I,
    ),
    CASH_FLOW: re.compile(
        r"cash\s+flow|capex|capital\s+expenditure|purchases?\s+of\s+property|"
        r"cash\s+(from|provided\s+by)\s+operat|operating\s+cash|free\s+cash|dividends?\s+paid|"
        r"total\s+cash\s+dividends|dividends?\s+(to|paid)|paid\s+dividends|payout\s+ratio|"
        r"depreciation|\bD&A\b|share\s+repurchase|buyback|capital[-\s]+intensi",
        re.I,
    ),
}


def statements_needed(question: str) -> list[str]:
    """Which primary statements a question's figures come from."""
    return [kind for kind in STATEMENTS if _NEEDS[kind].search(question)]


def is_narrative(question: str) -> bool:
    """A question no primary statement answers: its evidence is prose."""
    return not statements_needed(question)
