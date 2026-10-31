"""Ledger demo UI (weeks 3 to 8). Run: ``streamlit run ui/streamlit_app.py``

Talks to the FastAPI service at LEDGER_API (default http://localhost:8000),
or, when LEDGER_API is "inprocess", builds Ledger in this process (handy for
a quick local look; it skips the API's daily quota guard, so a public demo
should use the API, as deploy/hf-space/start.sh does).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledger.answer.sanitize import strip_markdown_links  # noqa: E402
from ledger.obs.dashboard import daily_stats, load_requests  # noqa: E402
from ledger.retrieve.coverage import coverage_lines  # noqa: E402

API = os.environ.get("LEDGER_API", "http://localhost:8000")
EXAMPLES = [
    "What was Apple's revenue in fiscal year 2023, and how did it change from 2022?",
    "What was Microsoft's operating margin in fiscal year 2023?",
    "How much did Nike's net income change from fiscal year 2022 to 2023?",
    "What was Costco's revenue in fiscal year 2009?",  # a refusal: not ingested
    "What will Apple's revenue be in fiscal year 2031?",  # a refusal: future
]

INDEX_STATUS = ROOT / "data" / "index-status.txt"  # why deploy/hf-space/start.sh found no index

st.set_page_config(page_title="Ledger", page_icon="📒", layout="wide")


class QuotaUsedUp(Exception):
    """The API's daily quota (or the provider's free tier) is spent; ``str(e)`` is for the user."""


@st.cache_resource
def _inprocess() -> Any:
    from ledger.factory import build_ledger

    return build_ledger()


def _client_headers() -> dict[str, str]:
    """Pass the visitor's address on, so the API's per-client quota sees them, not this server."""
    try:
        fwd = st.context.headers.get("X-Forwarded-For")
    except Exception:  # no request context (tests, old Streamlit)
        fwd = None
    return {"X-Forwarded-For": fwd} if fwd else {}


def ask(question: str, tickers: list[str], years: list[int]) -> dict[str, Any]:
    if API == "inprocess":
        from ledger.retrieve.filters import Filters

        a = _inprocess().ask(question, Filters(tickers=tickers, years=years))
        return dict(a.model_dump())
    r = httpx.post(
        f"{API}/ask",
        json={"question": question, "tickers": tickers, "years": years},
        headers=_client_headers(),
        timeout=120,
    )
    if r.status_code in (429, 503):
        detail = r.json().get("detail")
        if isinstance(detail, dict) and detail.get("error") in (
            "daily_quota_exhausted",
            "model_busy",
        ):
            raise QuotaUsedUp(detail["message"])
    r.raise_for_status()
    return dict(r.json())


def documents() -> list[dict[str, Any]]:
    """The filings the server has indexed (empty if it cannot be reached yet)."""
    if st.session_state.get("docs"):
        return list(st.session_state["docs"])
    try:
        if API == "inprocess":
            docs = _inprocess().retriever.index.documents()
        else:
            docs = httpx.get(f"{API}/documents", timeout=120).json()
    except Exception:
        return []
    st.session_state["docs"] = docs
    return list(docs)


def index_ready() -> bool:
    """False until at least one filing is indexed (a fresh Space starts empty)."""
    return bool(documents())


def feedback(request_id: str, up: bool) -> None:
    if API != "inprocess":
        httpx.post(f"{API}/feedback", json={"request_id": request_id, "thumbs_up": up}, timeout=10)


def render_answer(a: dict[str, Any]) -> None:
    if a["refused"]:
        st.warning(f"**{a['answer']}** {a.get('refusal_reason') or ''}")
        if a["closest_passages"]:
            st.caption("Closest passages found:")
            for c in a["closest_passages"]:
                st.markdown(
                    f"- [{c['company']} FY{c['fiscal_year']}, {c['section']}]"
                    f"({c['source_url']}): _{strip_markdown_links(c['quote'])}…_"
                )
        return

    if a["verified"] is True:
        st.success(
            "✔ Checked: the arithmetic recomputes and each figure appears in the cited text. "
            "That does not prove it picked the right line item or year, so check the sources."
        )
    elif a["verified"] is False:
        st.error("⚠ The verifier could not confirm a number below. Check the sources.")

    text = strip_markdown_links(a["answer"])
    for c in a["citations"]:
        text = text.replace(f"[{c['n']}]", f"[[{c['n']}]]({c['source_url']})")
    st.markdown(text)

    for cl in a["claims"]:
        if cl.get("calculation"):
            badge = {"verified": "✔", "mismatch": "✘", "ungrounded": "✘"}.get(
                cl.get("verifier_status") or "", "·"
            )
            st.caption(f"{badge} `{cl['calculation']} = {cl['result']}`")

    st.markdown("**Sources**")
    for c in a["citations"]:
        st.markdown(
            f"[{c['n']}] [{c['company']} 10-K FY{c['fiscal_year']}, {c['section']}]"
            f"({c['source_url']})  \n> {strip_markdown_links(c['quote'])}…"
        )

    cols = st.columns(6)
    cols[0].metric("Latency", f"{a['latency_ms'] / 1000:.1f}s")
    cols[1].metric("Cost (list price)", f"${a['cost_usd']:.4f}")
    cols[2].metric("Cache", "hit" if a["cache_hit"] else "miss")
    cols[3].metric("Regenerated", "yes" if a["regenerated"] else "no")
    if cols[4].button("👍", key="up"):
        feedback(a["request_id"], True)
    if cols[5].button("👎", key="down"):
        feedback(a["request_id"], False)


tab_ask, tab_dash = st.tabs(["Ask", "Dashboard"])

with tab_ask:
    st.title("📒 Ledger")
    st.write(
        "Ask about a company's annual report. Every sentence cites the filing; every "
        "number is re-checked by a calculator before you see it."
    )
    with st.sidebar:
        st.header("Filters")
        tickers = [
            t.strip().upper()
            for t in st.text_input("Tickers (comma separated)").split(",")
            if t.strip()
        ]
        years = [int(y) for y in st.multiselect("Fiscal years", list(range(2026, 2014, -1)))]
        st.caption("Leave empty to detect company and year from the question.")
        st.divider()
        st.caption("Not investment advice. Answers come only from ingested 10-K filings.")

    with st.spinner("Loading the filings index…"):
        ready = index_ready()
    if ready:
        lines = coverage_lines(documents())
        with st.sidebar.expander(f"Companies loaded ({len(lines)})"):
            st.caption(
                "Years are the calendar year each report's period ends in, so a retailer's "
                "year ending in January 2023 appears as 2023 even if the company calls it "
                "fiscal 2022."
            )
            st.markdown("\n".join(f"- {line}" for line in lines))
    if not ready:
        reason = INDEX_STATUS.read_text().strip() if INDEX_STATUS.exists() else ""
        st.error(
            "No filings are loaded on this server yet, so there is nothing to ask about. "
            + (reason + " " if reason else "")
            + "The owner can fix this by following docs/deploy-demo.md "
            "(set LEDGER_INDEX_URL to the demo index); locally, run `ledger download` "
            "then `ledger ingest`."
        )
    else:
        example = st.selectbox("Try an example", ["", *EXAMPLES])
        question = st.text_input("Question", value=example, max_chars=1000)
        if st.button("Ask", type="primary") and question:
            with st.spinner("Searching, drafting and verifying…"):
                try:
                    st.session_state["answer"] = ask(question, tickers, years)
                except QuotaUsedUp as e:
                    st.session_state.pop("answer", None)
                    st.warning(f"**Daily quota used up.** {e}")
                except httpx.HTTPStatusError as e:
                    st.error(e.response.json().get("detail", str(e)))
                except httpx.HTTPError:
                    st.error("The Ledger API is not reachable right now. Try again in a minute.")
        if "answer" in st.session_state:
            render_answer(st.session_state["answer"])

with tab_dash:
    st.header("Requests")
    rows = daily_stats(load_requests(ROOT / "data" / "traces" / "requests.jsonl"))
    if not rows:
        st.info("No requests logged yet.")
    else:
        import pandas as pd

        df = pd.DataFrame(rows).set_index("day")
        c1, c2 = st.columns(2)
        c1.subheader("Latency (ms)")
        c1.line_chart(df[["latency_p50_ms", "latency_p95_ms"]])
        c2.subheader("Cost per request (USD, list price)")
        c2.line_chart(df[["cost_per_request_usd"]])
        c1.subheader("Requests per day")
        c1.bar_chart(df[["requests"]])
        c2.subheader("Rates")
        c2.line_chart(df[["error_rate", "refusal_rate", "verifier_flag_rate", "cache_hit_rate"]])
        st.dataframe(df)
