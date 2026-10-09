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
