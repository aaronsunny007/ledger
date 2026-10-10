"""ING-2: parse SEC 10-K HTML into sectioned blocks, keeping tables as tables.

The output is a flat list of ``Block``s in document order. Each block knows
the 10-K Item it sits under (Item 7 MD&A, Item 8 statements, ...), whether it
is a table, the nearest HTML anchor (for the citation viewer) and, for
tables, the reporting unit ("in millions") so numbers can be scaled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

ITEM_TITLES = {
    "1": "Item 1. Business",
    "1A": "Item 1A. Risk Factors",
    "1B": "Item 1B. Unresolved Staff Comments",
    "1C": "Item 1C. Cybersecurity",
    "2": "Item 2. Properties",
    "3": "Item 3. Legal Proceedings",
    "4": "Item 4. Mine Safety Disclosures",
    "5": "Item 5. Market for Common Equity",
    "6": "Item 6. Reserved",
    "7": "Item 7. MD&A",
    "7A": "Item 7A. Market Risk",
    "8": "Item 8. Financial Statements",
    "9": "Item 9. Changes in Accountants",
    "9A": "Item 9A. Controls and Procedures",
    "9B": "Item 9B. Other Information",
    "9C": "Item 9C. Foreign Jurisdictions",
    "10": "Item 10. Directors and Officers",
    "11": "Item 11. Executive Compensation",
    "12": "Item 12. Security Ownership",
    "13": "Item 13. Relationships",
    "14": "Item 14. Accountant Fees",
    "15": "Item 15. Exhibits",
    "16": "Item 16. Form 10-K Summary",
}

_ITEM_RE = re.compile(r"^\s*item\s*(\d{1,2}[abc]?)\s*[\.:\-\u2014\u2013]?\s*", re.IGNORECASE)
_UNITS_RE = re.compile(
    r"\(\s*(?:dollars\s+|amounts\s+|\$\s*)?in\s+(thousands|millions|billions)", re.IGNORECASE
)
_BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "tr"}
_WS = re.compile(r"\s+")


@dataclass
class Block:
    text: str
    section: str
    is_table: bool = False
    anchor: str = ""
    units: str = ""  # "thousands" | "millions" | "billions" | ""
    statement: str = ""  # balance_sheet | income | cash_flow, set by ingest.statements


@dataclass
class ParsedDoc:
    title: str
    blocks: list[Block] = field(default_factory=list)

    def sections(self) -> list[str]:
        seen: dict[str, None] = {}
        for b in self.blocks:
            seen.setdefault(b.section, None)
        return list(seen)


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def _hidden(tag: Tag) -> bool:
    style = str(tag.get("style", "")).replace(" ", "").lower()
    return "display:none" in style


def table_to_text(table: Tag) -> str:
    """Render a table as ``cell | cell`` rows.

    SEC tables split "$", "(1,234" and ")" into separate cells; those are
    glued back together so each number reads as one token.
    """
    lines = []
    for tr in table.find_all("tr"):
        cells: list[str] = []
        for td in tr.find_all(["td", "th"]):
            t = _clean(td.get_text(" "))
            if not t:
                continue
            if cells and (t in {")", "%", ")%"} or cells[-1] in {"$", "£", "€", "("}):
                cells[-1] = (cells[-1] + t).replace("$ ", "$")
            else:
                cells.append(t)
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _item_heading(text: str) -> str | None:
    if len(text) > 160:
        return None
    m = _ITEM_RE.match(text)
    if not m:
        return None
    key = m.group(1).upper()
    return ITEM_TITLES.get(key)


_DOC_END = re.compile(r"</html\s*>", re.IGNORECASE)

_TOP = re.compile(r"top:\s*(-?[\d.]+)px", re.IGNORECASE)
_LEFT = re.compile(r"left:\s*(-?[\d.]+)px", re.IGNORECASE)
_FIGURE_CELL = re.compile(r"[$€£(\-\u2014\u2013]*\s*[\d,.]*\d[\d,.]*\s*\)?\s*%?|[\u2014\u2013-]")
# Filings converted from PDF place every text run in its own absolutely
# positioned div; below this many there is nothing to rebuild.
_MIN_POSITIONED = 200
_SAME_LINE_PX = 5.0


def _positioned(tag: Tag) -> tuple[float, float] | None:
    style = str(tag.get("style", ""))
    if "absolute" not in style:
        return None
    top, left = _TOP.search(style), _LEFT.search(style)
    return (float(top.group(1)), float(left.group(1))) if top and left else None


def _rebuild_positioned(soup: BeautifulSoup) -> None:
    """Turn a PDF-style layout of positioned divs back into lines and tables.

    Runs on the same line (same ``top`` within a few pixels, per page) are
    ordered by ``left``. A line with figures after its label becomes a table
    row, consecutive rows one table; other lines become paragraphs. Without
    this such filings parse to tens of thousands of fragments and no tables.
    """
    if soup.find("table"):
        return
    leaves = [d for d in soup.find_all("div") if not d.find("div") and _positioned(d)]
    if len(leaves) < _MIN_POSITIONED:
        return
    pages: dict[int, tuple[Tag, list[tuple[float, float, str]]]] = {}
    for d in leaves:
        pos = _positioned(d)
        text = _clean(d.get_text(" "))
        if pos is None or not text or not isinstance(d.parent, Tag):
            continue
        pages.setdefault(id(d.parent), (d.parent, []))[1].append((pos[0], pos[1], text))
    for page, runs in pages.values():
        runs.sort()
        lines: list[list[tuple[float, str]]] = []
        line_top = None
        for top, left, text in runs:
            if line_top is None or top - line_top > _SAME_LINE_PX:
                lines.append([])
                line_top = top
            lines[-1].append((left, text))
        rows = _join_label_lines([_merge_runs([t for _, t in sorted(line)]) for line in lines])
        page.clear()
        table: Tag | None = None
        for i, row in enumerate(rows):
            heading = len(row) == 1 and len(row[0]) <= 80
            upcoming = any(_figure_row(r) for r in rows[i + 1 : i + 3])
            # Headings inside a statement ("Current assets:") stay in its table.
            if _figure_row(row) or (table is not None and heading and upcoming):
                if table is None:
                    table = soup.new_tag("table")
                    page.append(table)
                tr = soup.new_tag("tr")
                for c in row:
                    td = soup.new_tag("td")
                    td.string = c
                    tr.append(td)
                table.append(tr)
            else:
                table = None
                para = soup.new_tag("p")
                para.string = " ".join(row)
                page.append(para)


def _is_figure(cell: str) -> bool:
    return bool(_FIGURE_CELL.fullmatch(cell))


def _merge_runs(cells: list[str]) -> list[str]:
    """Glue label fragments of one line; keep each figure in its own cell."""
    merged: list[str] = []
    for c in cells:
        if merged and not _is_figure(c) and not _is_figure(merged[-1]):
            merged[-1] += " " + c
        else:
            merged.append(c)
    return merged


def _figure_row(row: list[str]) -> bool:
    return len(row) >= 2 and any(_is_figure(c) for c in row)


def _join_label_lines(rows: list[list[str]]) -> list[list[str]]:
    """A label set a few pixels above its figures is one row with them."""
    out: list[list[str]] = []
    for row in rows:
        prev = out[-1] if out else None
        if (
            prev is not None
            and len(prev) == 1
            and not _is_figure(prev[0])
            and len(prev[0]) <= 80
            and all(_is_figure(c) for c in row)
        ):
            out[-1] = prev + row
        else:
            out.append(row)
    return out


def parse_html(html: str | bytes) -> ParsedDoc:
    """Parse one HTML document, or several concatenated ones.

    The downloader appends a filing's EX-13 exhibit after the main document;
    an HTML parser would drop everything after the first ``</html>``, so each
    document is parsed in turn and its blocks appended.
    """
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    parts = [p for p in _DOC_END.split(text) if p.strip()]
    doc = _parse_one(parts[0] if parts else text, "Cover")
    for extra in parts[1:]:
        more = _parse_one(extra, "Exhibit 13. Annual Report")
        doc.blocks.extend(more.blocks)
    return doc


def _parse_one(html: str, start_section: str) -> ParsedDoc:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "head"]):
        t.decompose()
    for t in soup.find_all(_hidden):
        t.decompose()
    for t in soup.find_all(re.compile(r"^ix:header$", re.IGNORECASE)):
        t.decompose()
    _rebuild_positioned(soup)

    title = _clean(soup.title.get_text()) if soup.title else ""
    doc = ParsedDoc(title=title)
    state = {"section": start_section, "anchor": "", "last_text": ""}
    body = soup.body or soup

    def emit_text(text: str) -> None:
        text = _clean(text)
        if not text:
            return
        heading = _item_heading(text)
        if heading:
            state["section"] = heading
        doc.blocks.append(Block(text=text, section=state["section"], anchor=state["anchor"]))
        state["last_text"] = text

    def walk(node: Tag) -> None:
        buf: list[str] = []

        def flush() -> None:
            if buf:
                emit_text(" ".join(buf))
                buf.clear()

        for child in node.children:
            if isinstance(child, NavigableString):
                buf.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            anchor = child.get("id") or child.get("name")
            if anchor:
                state["anchor"] = str(anchor)
            if child.name == "table":
                flush()
                text = table_to_text(child)
                if not text:
                    continue
                if "|" not in text:  # layout table holding a single paragraph
                    emit_text(text)
                    continue
                units_m = _UNITS_RE.search(text) or _UNITS_RE.search(state["last_text"])
                doc.blocks.append(
                    Block(
                        text=text,
                        section=state["section"],
                        is_table=True,
                        anchor=state["anchor"],
                        units=units_m.group(1).lower() if units_m else "",
                    )
                )
            elif child.name in _BLOCK_TAGS or child.find(["p", "div", "table"]):
                flush()
                if child.find(["p", "div", "table", "li"]):
                    walk(child)
                else:
                    emit_text(child.get_text(" "))
            else:
                buf.append(child.get_text(" "))
        flush()

    walk(body)
    return doc
