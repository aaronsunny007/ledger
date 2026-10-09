"""ING-1: download 10-K filings from SEC EDGAR as HTML.

SEC's fair-access rules: identify yourself in the User-Agent and stay under
10 requests per second. This client sends at most ~8 per second and retries
politely on 429/5xx. HTML is fetched rather than PDF so tables survive.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

SEC_WWW = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"


@dataclass
class Filing:
    ticker: str
    company: str
    cik: int
    form: str
    accession: str
    report_date: str  # period of report, YYYY-MM-DD
    filing_date: str
    primary_document: str

    @property
    def fiscal_year(self) -> int:
        # Fiscal year = calendar year the period ends in (Walmart's FY2024
        # ends January 2024), matching how FinanceBench names documents.
        return int(self.report_date[:4])

    @property
    def url(self) -> str:
        acc = self.accession.replace("-", "")
        return f"{SEC_WWW}/Archives/edgar/data/{self.cik}/{acc}/{self.primary_document}"

    @property
    def doc_id(self) -> str:
        return f"{self.ticker}_{self.fiscal_year}_{self.form.replace('-', '')}"


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        min_interval_s: float = 0.125,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
    ):
        if "@" not in user_agent:
            raise ValueError("SEC requires a contact email in the User-Agent (SEC_USER_AGENT).")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60,
            transport=transport,
            follow_redirects=True,
        )
        self._min_interval = min_interval_s
        self._last = 0.0
        self._max_retries = max_retries
        self._tickers: dict[str, tuple[int, str]] | None = None

    def get(self, url: str) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            resp = self._client.get(url)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self._max_retries:
                backoff = 2 ** (attempt + 1)
                log.warning("EDGAR %s on %s, retrying in %ss", resp.status_code, url, backoff)
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("unreachable")

    def get_json(self, url: str) -> Any:
        return self.get(url).json()

    def lookup(self, ticker: str) -> tuple[int, str]:
        """Ticker -> (CIK, company title)."""
        if self._tickers is None:
            data = self.get_json(f"{SEC_WWW}/files/company_tickers.json")
            self._tickers = {
                row["ticker"].upper(): (int(row["cik_str"]), row["title"]) for row in data.values()
            }
        try:
            return self._tickers[ticker.upper()]
        except KeyError as e:
            raise KeyError(f"Unknown ticker {ticker!r} in SEC company_tickers.json") from e

    def filings(
        self, ticker: str, form: str = "10-K", since_year: int | None = None
    ) -> list[Filing]:
        """Filings of ``form``, newest first.

        The submissions endpoint lists roughly the latest 1,000 filings; for
        large companies older 10-Ks sit in extra pages, which are fetched
        only when ``since_year`` reaches back past the recent list.
        """
        cik, title = self.lookup(ticker)
        data = self.get_json(f"{SEC_DATA}/submissions/CIK{cik:010d}.json")
        company = data.get("name") or title
        pages = [data["filings"]["recent"]]
        out = self._parse_page(pages[0], ticker, company, cik, form)
        oldest = min((f.fiscal_year for f in out), default=9999)
        if since_year is not None and since_year < oldest:
            for extra in data["filings"].get("files", []):
                page = self.get_json(f"{SEC_DATA}/submissions/{extra['name']}")
                out.extend(self._parse_page(page, ticker, company, cik, form))
        return out

    @staticmethod
    def _parse_page(
        page: dict[str, Any], ticker: str, company: str, cik: int, form: str
    ) -> list[Filing]:
        out = []
        for i, f in enumerate(page["form"]):
            if f != form or not page["reportDate"][i]:
                continue
            out.append(
                Filing(
                    ticker=ticker.upper(),
                    company=company,
                    cik=cik,
                    form=f,
                    accession=page["accessionNumber"][i],
                    report_date=page["reportDate"][i],
                    filing_date=page["filingDate"][i],
                    primary_document=page["primaryDocument"][i],
                )
            )
        return out

    def company_facts(self, ticker: str) -> Any:
        """XBRL company facts, the source of guaranteed-correct numeric answers."""
        cik, _ = self.lookup(ticker)
        return self.get_json(f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik:010d}.json")


def download_filings(
    client: EdgarClient,
    ticker: str,
    years: list[int],
    raw_dir: Path,
    form: str = "10-K",
) -> list[Path]:
    """Save each wanted filing to ``raw_dir/TICKER/YEAR/`` with a meta.json.

    Idempotent: a filing already on disk is not fetched again.
    """
    saved = []
    wanted = set(years)
    for filing in client.filings(ticker, form, since_year=min(years, default=None)):
        if filing.fiscal_year not in wanted:
            continue
        wanted.discard(filing.fiscal_year)  # newest first; skip amendments of the same year
        dest = raw_dir / filing.ticker / str(filing.fiscal_year)
        html_path = dest / "filing.htm"
        if html_path.exists():
            log.info("skip %s (already downloaded)", filing.doc_id)
        else:
            dest.mkdir(parents=True, exist_ok=True)
            html_path.write_bytes(client.get(filing.url).content)
            (dest / "meta.json").write_text(
                json.dumps({**asdict(filing), "url": filing.url, "doc_id": filing.doc_id}, indent=2)
            )
            log.info("saved %s", filing.doc_id)
        saved.append(html_path)
    if wanted:
        log.warning("%s: no %s found for fiscal year(s) %s", ticker, form, sorted(wanted))
    return saved
