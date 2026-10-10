from __future__ import annotations

import pytest

from ledger.config import RetrievalConfig
from ledger.ingest.chunk import get_chunker
from ledger.ingest.parse import parse_html
from ledger.ingest.statements import statements_needed
from ledger.retrieve.embed import HashingEmbedder
from ledger.retrieve.filters import Filters
from ledger.retrieve.hybrid import Retriever
from ledger.retrieve.store import InMemoryIndex
from tests.conftest import ACME, SAMPLE

BS = (
    "<p>Item 8. Financial Statements</p><p>CONSOLIDATED BALANCE SHEETS</p><p>(in millions)</p>"
    "<table><tr><td></td><td>2024</td><td>2023</td></tr>"
    "<tr><td>Inventories</td><td>900</td><td>850</td></tr>"
    "<tr><td>Total assets</td><td>9,000</td><td>8,000</td></tr>"
    "<tr><td>Total liabilities</td><td>5,000</td><td>4,500</td></tr></table>"
    # A note table that mentions the balance sheet but is not the statement.
    "<p>The following balance sheet reconciliation shows leases.</p>"
    "<table><tr><td>Lease assets</td><td>10</td></tr>"
    "<tr><td>Lease liabilities</td><td>9</td></tr></table>"
)


def test_primary_statements_are_tagged_and_kept_whole() -> None:
    chunks = get_chunker("table", 300, 50).chunk(parse_html(SAMPLE.read_text() + BS), ACME)
    tagged = {c.statement: c for c in chunks if c.statement}
    assert set(tagged) == {"income", "balance_sheet"}
    assert "Total liabilities" in tagged["balance_sheet"].text  # not split at 300 chars
    assert not any("Lease assets" in c.text for c in tagged.values())


@pytest.mark.parametrize(
    ("q", "needs"),
    [
        (
            "What is the FY2019 fixed asset turnover ratio for Activision?",
            ["balance_sheet", "income"],
        ),
        ("What is the FY2018 capital expenditure amount for 3M?", ["cash_flow"]),
        ("Does AMD have a healthy quick ratio for FY22?", ["balance_sheet"]),
        ("What industry does Amcor operate in?", []),
    ],
)
def test_statements_needed(q: str, needs: list[str]) -> None:
    assert statements_needed(q) == needs


def _retriever(pin: bool) -> Retriever:
    emb = HashingEmbedder()
    idx = InMemoryIndex()
    chunks = get_chunker("table", 300, 50).chunk(parse_html(SAMPLE.read_text() + BS), ACME)
    idx.add(chunks, emb.embed_documents([c.text for c in chunks]))
    cfg = RetrievalConfig(embedder="hashing", rerank=False, top_k=1, pin_statements=pin)
    return Retriever(idx, emb, cfg)


def test_needed_statement_is_pinned_first() -> None:
    q = "What were Acme's inventories at the end of 2024?"
    pinned = _retriever(True).retrieve(q, Filters(tickers=["ACME"]))
    assert pinned[0].chunk.statement == "balance_sheet" and pinned[0].ranks == {"pinned": 1}
    assert not any(p.chunk.statement for p in _retriever(False).retrieve(q, Filters(["ACME"]))[:0])


def test_pinning_needs_a_company_filter() -> None:
    hits = _retriever(True).retrieve("What were inventories?", Filters())
    assert all("pinned" not in h.ranks for h in hits)


def test_latest_year_only_falls_back_when_latest_missing() -> None:
    r = _retriever(False)
    assert r.retrieve("revenue", Filters(["ACME"], [2023, 2024]))  # latest (2024) exists
    assert r.retrieve("revenue", Filters(["ACME"], [2024, 2025]))  # 2025 missing -> all years


def _tagged(html: str) -> dict[str, list[str]]:
    from ledger.ingest.statements import classify_statements

    doc = parse_html(html)
    classify_statements(doc)
    out: dict[str, list[str]] = {}
    for b in doc.blocks:
        if b.statement:
            out.setdefault(b.statement, []).append(b.text)
    return out


def _table(*rows: tuple[str, ...]) -> str:
    return (
        "<table>"
        + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        + "</table>"
    )


def test_title_in_its_own_table_and_split_words() -> None:
    # Corning: the title is a one-row table; 3M: "Statement of Incom e".
    html = (
        _table(("Consolidated Balance Sheets",), ("Corning Incorporated",))
        + _table(("Total assets", "9,000", "8,000"), ("Total equity", "4,000", "3,500"))
        + "<p>3M Company</p><p>Consolidated Statement of Incom e</p><p>Years ended</p>"
        + _table(("Net sales", "32,765", "31,657"), ("Net income", "5,349", "4,858"))
    )
    assert set(_tagged(html)) == {"balance_sheet", "income"}


def test_statement_split_across_tables_is_tagged_whole_but_notes_are_not() -> None:
    # American Water: assets and liabilities in two tables, header repeated.
    header = "<p>American Water Works</p><p>Consolidated Balance Sheets</p><p>(In millions)</p>"
    html = (
        header
        + _table(("Cash", "547", "60"), ("Total assets", "26,075", "24,766"))
        + "<p>80</p><p>Table of Contents</p>"
        + header
        + _table(("Long-term debt", "9,656", "8,644"), ("Total liabilities", "19,000", "18,500"))
        + "<p>The following lease table reconciles amounts on the balance sheets.</p>"
        + _table(("Lease assets", "680", "504"), ("Lease liabilities", "633", "450"))
    )
    tagged = _tagged(html)["balance_sheet"]
    assert len(tagged) == 2 and not any("Lease" in t for t in tagged)


def test_microsoft_and_nike_wording() -> None:
    html = (
        "<p>INCOME STATEMENTS</p>"
        + _table(("Total revenue", "211,915", "198,270"), ("Net income", "72,361", "72,738"))
        + "<p>COMPREHENSIVE INCOME STATEMENTS</p>"
        + _table(("Net income", "72,361", "72,738"), ("Comprehensive income", "71,4", "63,0"))
        + "<p>CASH FLOWS S TATEMENTS</p>"
        + _table(
            ("Net cash from operations", "87,582", "89,035"),
            ("Net cash used in investing", "(22,680)", "(30,311)"),
        )
    )
    tagged = _tagged(html)
    assert set(tagged) == {"income", "cash_flow"}
    assert "Total revenue" in tagged["income"][0]


def test_title_a_few_lines_up() -> None:
    # PepsiCo: company, period and units lines sit between title and table.
    html = (
        "<p>Consolidated Statement of Income</p><p>PepsiCo, Inc. and Subsidiaries</p>"
        "<p>Fiscal years ended December 31, 2022, December 25, 2021</p>"
        "<p>(in millions except per share amounts)</p>"
        + _table(("Net Revenue", "86,392", "79,474"), ("Net income", "8,978", "7,679"))
    )
    assert set(_tagged(html)) == {"income"}


def test_self_titled_tables_between_page_numbers_stay_apart() -> None:
    # General Mills: each statement is one table opening with its title.
    html = (
        "<p>45</p>"
        + _table(
            ("Consolidated Statements of Earnings",),
            ("Net sales", "18,127.0", "17,626.6"),
            ("Net earnings", "2,339.8", "2,181.2"),
        )
        + "<p>46</p>"
        + _table(
            ("Consolidated Balance Sheets",),
            ("Total assets", "36,795.1", "30,806.7"),
            ("Total equity", "11,195.5", "10,152.6"),
        )
        + "<p>47</p>"
        + _table(
            ("Consolidated Statements of Cash Flows",),
            ("Net earnings", "2,346.0", "2,210.8"),
            ("Net cash provided by operating activities", "3,277.9", "3,676.2"),
            ("Net cash used by investing activities", "(530.5)", "(461.0)"),
        )
    )
    tagged = _tagged(html)
    assert set(tagged) == {"income", "balance_sheet", "cash_flow"}
    assert all(len(v) == 1 for v in tagged.values())
    assert "Cash Flows" in tagged["cash_flow"][0]


def test_footer_between_statement_halves() -> None:
    header = "<p>MGM Resorts</p><p>Consolidated Balance Sheets</p><p>(In thousands)</p>"
    footer = "<p>The accompanying notes are an integral part of these statements.</p><p>61</p>"
    html = (
        header
        + _table(("Cash", "4,703", "5,101"), ("Total assets", "45,692", "36,394"))
        + footer
        + header
        + _table(("Debt", "12,000", "11,000"), ("Total liabilities", "40,000", "30,000"))
    )
    assert len(_tagged(html)["balance_sheet"]) == 2


def test_statement_index_is_not_merged_into_the_statement() -> None:
    # CVS: the index table has page numbers and names the income statement.
    html = (
        _table(
            ("Consolidated Statements of Operations", "105"),
            ("Consolidated Balance Sheets", "107"),
            ("Consolidated Statements of Cash Flows", "108"),
        )
        + "<p>Index to Consolidated Financial Statements</p>"
        + "<p>Consolidated Statements of Operations</p>"
        + _table(("Revenues", "322,467", "292,111"), ("Net income", "4,149", "7,910"))
    )
    tagged = _tagged(html)
    assert set(tagged) == {"income"} and len(tagged["income"]) == 1


def test_pdf_style_positioned_layout_is_rebuilt_into_tables() -> None:
    # General Mills 2022: every text run is an absolutely positioned div.
    def run(top: int, left: int, text: str) -> str:
        return f'<div style="position:absolute;left:{left}px;top:{top}px;">{text}</div>'

    runs = [run(10, 60, "Consolidated Balance Sheets"), run(30, 60, "(In Millions)")]
    for i in range(110):
        top = 50 + 18 * i
        runs += [run(top, 60, "Other"), run(top, 110, f"line {i}"), run(top, 600, f"{i},0.1")]
        runs.append(run(top + 1, 720, f"({i}.5)"))
    runs += [run(3000, 60, "Total assets"), run(3000, 600, "31,091.3")]
    runs += [run(3020, 60, "Total equity"), run(3020, 600, "10,000.0")]
    html = f'<html><body><div style="position:relative">{"".join(runs)}</div></body></html>'
    doc = parse_html(html)
    tables = [b for b in doc.blocks if b.is_table]
    assert len(tables) == 1
    assert "Other line 3 | 3,0.1 | (3.5)" in tables[0].text
    assert doc.blocks[0].text == "Consolidated Balance Sheets"
    assert set(_tagged(html)) == {"balance_sheet"}


def test_positioned_layout_with_offset_labels_and_headings() -> None:
    def run(top: int, left: int, text: str) -> str:
        return f'<div style="position:absolute;left:{left}px;top:{top}px;">{text}</div>'

    runs = [run(10, 60, "Consolidated Balance Sheets")]
    runs += [run(40, 60, "Current assets:")]  # heading line inside the table
    for i in range(120):
        top = 60 + 18 * i
        runs += [run(top, 60, f"Item {i}"), run(top + 4, 600, f"{i}.5"), run(top + 4, 700, "1.0")]
    runs += [run(2300, 60, "Total assets"), run(2310, 600, "31,091.3")]  # label 10px above
    runs += [run(2330, 60, "Total equity"), run(2330, 600, "10,000.0")]
    html = f'<html><body><div style="position:relative">{"".join(runs)}</div></body></html>'
    tables = [b.text for b in parse_html(html).blocks if b.is_table]
    assert len(tables) == 1
    assert "Total assets | 31,091.3" in tables[0] and "Item 7 | 7.5 | 1.0" in tables[0]
    assert set(_tagged(html)) == {"balance_sheet"}


def test_subheading_line_between_cash_flow_tables() -> None:
    html = (
        "<p>Consolidated Statements of Cash Flows</p>"
        + _table(("Net earnings", "2,735.0", "2,346.0"), ("Other", "1.0", "2.0"))
        + "<p>Adjustments to reconcile net earnings to net cash provided by operating"
        " activities:</p>"
        + _table(
            ("Depreciation", "570.3", "601.3"),
            ("Net cash provided by operating activities", "3,316.3", "2,983.0"),
            ("Net cash used by investing activities", "(1,011.6)", "(530.5)"),
        )
    )
    assert len(_tagged(html)["cash_flow"]) == 2


def test_line_items_beat_size_when_choosing_the_statement() -> None:
    # PepsiCo: a larger reclassification note mentions "Income Statement".
    real = _table(
        ("Net Revenue", "86,392", "79,474"),
        ("Cost of sales", "40,576", "37,075"),
        ("Gross profit", "45,816", "42,399"),
        ("Operating Profit", "11,512", "11,162"),
        ("Provision for income taxes", "1,727", "2,142"),
        ("Net Income", "8,978", "7,679"),
        ("Diluted net income per share", "6.42", "5.49"),
    )
    note = _table(
        ("Affected Line Item in the Income Statement", "2022", "2021"),
        *[(f"Reclassification of item {i} to net revenue", "1,000", "2,000") for i in range(12)],
        ("Net income", "100", "200"),
    )
    html = "<p>Consolidated Statement of Income</p>" + real + "<p>Note 12</p>" + note
    assert "Gross profit" in _tagged(html)["income"][0]


def test_restatement_notes_and_quarterly_tables_are_not_statements() -> None:
    items = (
        ("Revenues", "93,392", "94,571"),
        ("Cost of products", "76,066", "80,790"),
        ("Operating earnings", "10,278", "5,834"),
        ("Net earnings", "8,197", "4,895"),
    )
    html = (
        "<p>The following shows the effects on our Consolidated Statements of Operations.</p>"
        + _table(("Reported", "Impact", "Restated"), *items, *items)
        + "<p>Consolidated Statements of Operations</p>"
        + _table(("Years ended", "2018", "2017"), *items)
        + "<p>Note 21. Quarterly results (unaudited)</p>"
        + _table(("Three Months Ended", "Dec. 31", "Sep. 30"), *items, *items, *items)
    )
    assert _tagged(html)["income"] == [
        "Years ended | 2018 | 2017\n" + "\n".join(" | ".join(r) for r in items)
    ]
