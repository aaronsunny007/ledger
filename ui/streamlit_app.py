"""Ledger demo UI (weeks 3 to 8). Run: ``streamlit run ui/streamlit_app.py``

Talks to the FastAPI service at LEDGER_API (default http://localhost:8000),
or, when LEDGER_API is "inprocess", builds Ledger in this process, which is
how the free Hugging Face Space runs it as a single container.
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

from ledger.obs.dashboard import daily_stats, load_requests  # noqa: E402

API = os.environ.get("LEDGER_API", "http://localhost:8000")
EXAMPLES = [
    "What was Apple's revenue in fiscal year 2023, and how did it change from 2022?",
    "What was Microsoft's operating margin in fiscal year 2023?",
    "How much did Nike's net income change from fiscal year 2022 to 2023?",
    "What was Costco's revenue in fiscal year 2009?",  # a refusal: not ingested
    "What will Apple's revenue be in fiscal year 2031?",  # a refusal: future
]

st.set_page_config(page_title="Ledger", page_icon="📒", layout="wide")


@st.cache_resource
def _inprocess() -> Any:
    from ledger.factory import build_ledger

    return build_ledger()


def ask(question: str, tickers: list[str], years: list[int]) -> dict[str, Any]:
    if API == "inprocess":
        from ledger.retrieve.filters import Filters

        a = _inprocess().ask(question, Filters(tickers=tickers, years=years))
        return dict(a.model_dump())
    r = httpx.post(
        f"{API}/ask", json={"question": question, "tickers": tickers, "years": years}, timeout=120
    )
    r.raise_for_status()
    return dict(r.json())


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
                    f"({c['source_url']}): _{c['quote']}…_"
                )
        return

    if a["verified"] is True:
        st.success("✔ Every number re-computed by the verifier")
    elif a["verified"] is False:
        st.error("⚠ The verifier could not confirm a number below. Check the sources.")

    text = a["answer"]
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
            f"({c['source_url']})  \n> {c['quote']}…"
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

    example = st.selectbox("Try an example", ["", *EXAMPLES])
    question = st.text_input("Question", value=example, max_chars=1000)
    if st.button("Ask", type="primary") and question:
        with st.spinner("Searching, drafting and verifying…"):
            try:
                st.session_state["answer"] = ask(question, tickers, years)
            except httpx.HTTPStatusError as e:
                st.error(e.response.json().get("detail", str(e)))
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
