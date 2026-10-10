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

# Titles and row labels are matched on lower-cased text with all whitespace
# removed: filings split words across HTML spans ("Statement of Incom e",
# "S TATEMENTS"), and the squashed form reads the same either way.
_TITLES = {
    BALANCE_SHEET: re.compile(r"balancesheets?|statements?offinancial(position|condition)"),
    INCOME: re.compile(
        r"(statements?of(consolidated)?(operations|income|earnings)|(?<!comprehensive)incomestatements?)"
        r"(?!andcompre)(?!.{0,20}comprehensive)"
    ),
    CASH_FLOW: re.compile(r"statements?ofcashflows?|cashflows?statements?"),
}

# Row labels a real statement must contain (titles alone also match notes
# and MD&A summaries).
_SIGNATURE = {
    # MGM prints total assets as an unlabelled line; current assets are labelled.
    BALANCE_SHEET: (re.compile(r"total(current)?assets"), re.compile(r"totalliabilities|equity")),
    INCOME: (re.compile(r"revenue|sales"), re.compile(r"net(income|earnings|loss)")),
    CASH_FLOW: (re.compile(r"operatingactivities|operations"), re.compile(r"investing")),
}

# Standard line items of each statement. Among the tables that pass the
# signature, the one carrying the most of these is the statement: segment
# notes and reclassification tables share a few labels, not most of them.
_LINE_ITEMS = {
    BALANCE_SHEET: (
        r"cashandcashequivalents|^cash",
        r"receivable",
        r"inventor",
        r"totalcurrentassets",
        r"property|equipment",
        r"goodwill",
        r"totalassets",
        r"accountspayable|payable",
        r"totalcurrentliabilities",
        r"long-?termdebt|borrowings",
        r"retainedearnings|deficit",
        r"totalliabilitiesand",
        r"commonstock|sharecapital|paid-?in",
    ),
    INCOME: (
        r"revenue|netsales",
        r"costof",
        r"grossprofit|grossmargin",
        r"operating(income|profit)",
        r"interestexpense|interest,net|interestincome",
        r"before(income)?tax",
        r"(provision|benefit)forincometax|incometax(expense|es)",
        r"net(income|earnings)",
        r"pershare|pershare",
        r"diluted",
        r"weighted|averageshares|sharesoutstanding",
        r"selling|general|administrative|research",
    ),
    CASH_FLOW: (
        r"net(income|earnings)",
        r"depreciation",
        r"operatingactivities|operations",
        r"capitalexpenditure|purchases?ofproperty|additionstoproperty|propertyandequipment",
        r"investingactivities|investing",
        r"financingactivities|financing",
        r"dividends",
        r"repurchase|treasury",
        r"endof(the)?(year|period)|endingbalance",
        r"deferredincometax",
        r"stock-?basedcompensation|share-?basedcompensation",
        r"acquisition",
    ),
}
_LINE_ITEM_RES = {k: [re.compile(p) for p in v] for k, v in _LINE_ITEMS.items()}


def _line_items(text: str, kind: str) -> int:
    return sum(bool(p.search(text)) for p in _LINE_ITEM_RES[kind])


# A table with fewer figures than this is a title or a footnote.
_MIN_FIGURES = 3
_FIGURE = re.compile(r"\d[\d,.]*\d")
# Text between two tables of one statement: page numbers, "Table of Contents".
# A short line naming any statement is a new title, not furniture.
_FURNITURE = 40
_ANY_TITLE = re.compile(r"statement|balancesheet|comprehensive")
_BOILERPLATE = re.compile(r"accompanyingnotes|integralpart|tableofcontents|continued")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _titles_by_position(text: str) -> list[str]:
    """Statements named in squashed ``text``, the last-named first."""
    last = {k: max((m.end() for m in t.finditer(text)), default=-1) for k, t in _TITLES.items()}
    return sorted((k for k in last if last[k] >= 0), key=lambda k: -last[k])


def _signature(text: str, kind: str) -> bool:
    return all(p.search(text) for p in _SIGNATURE[kind])


def classify_statements(doc: ParsedDoc, lookback: int = 8) -> None:
    """Set ``Block.statement`` on the primary statement tables of ``doc``.

    Tables are grouped into runs: a statement printed across pages, or split
    into an assets table and a liabilities table, is one run when only page
    furniture or a repeat of its own header lines sits between the tables. A
    run qualifies when its title (in the few lines before it, including
    title-only tables) names the statement and its rows carry the
    statement's signature. Per statement the qualifying run carrying the
    most of its standard line items is kept (then the largest): the primary
    statement, not a segment note or a summary of it.
    """
    best: dict[str, tuple[tuple[int, int], list[Block]]] = {}
    recent: list[str] = []
    run: list[Block] = []
    head = ""
    gap_ok = True

    def close() -> None:
        if not run:
            return
        text = _squash(" ".join(b.text for b in run))
        # The title nearest the table names it; earlier lines may still
        # hold the previous statement's title.
        for kind in _titles_by_position(head):
            if _signature(text, kind):
                score = (_line_items(text, kind), len(text))
                if kind not in best or score > best[kind][0]:
                    best[kind] = (score, list(run))
                break

    for b in doc.blocks:
        squashed = _squash(b.text)
        # An index of the statements lists several titles with page numbers.
        index = len(b.text) < 1500 and len(_titles_by_position(squashed)) >= 2
        if b.is_table and not index and len(_FIGURE.findall(b.text)) >= _MIN_FIGURES:
            # A table that opens with its own title starts a new statement.
            opening = _squash(b.text[:60])
            titled = any(t.search(opening) for t in _TITLES.values())
            if run and gap_ok and not titled:
                run.append(b)
            else:
                close()
                run = [b]
                head = _squash(" ".join(recent) + " " + b.text[:60])
            recent, gap_ok = [], True
            continue
        # Text, or a table too short to be a statement (often the title).
        recent = [*recent, b.text][-lookback:]
        if not run:
            continue
        # A title is a short line, not a sentence that mentions a statement.
        title_line = len(b.text) <= 80 and not b.text.rstrip().endswith(".")
        named = _titles_by_position(squashed) if title_line else []
        if named:
            # A title line continues the run only if it repeats the run's own.
            gap_ok = gap_ok and named[:1] == _titles_by_position(head)[:1]
            continue
        furniture = (len(b.text) <= _FURNITURE and not _ANY_TITLE.search(squashed)) or bool(
            _BOILERPLATE.search(squashed) and len(b.text) <= 200
        )
        # "Adjustments to reconcile net income ...:" introduces the next rows.
        subheading = b.text.rstrip().endswith(":") and len(b.text) <= 200
        if not (furniture or subheading or squashed in head):
            gap_ok = False
    close()
    for kind, (_, blocks) in best.items():
        for blk in blocks:
            blk.statement = kind


_NEEDS = {
    BALANCE_SHEET: re.compile(
        r"balance\s*sheet|statement\s+of\s+financial\s+position|total\s+assets|current\s+assets|"
        r"current\s+liabilit|working\s+capital|quick\s+ratio|current\s+ratio|inventor|"
        r"receivable|\bAR\b|payable|\bDPO\b|\bDSO\b|\bDIO\b|cash\s+conversion|PP&E|\bPPNE\b|"
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
