"""Run the demo UI the way Streamlit Community Cloud does and ask it questions.

    LEDGER_API=embedded GEMINI_API_KEY=... python scripts/streamlit_smoke.py [--real]

Uses Streamlit's own test runner, so the real script runs: it downloads the index, loads the
embedding model, starts the API in-process, then answers. Without ``--real`` no model call is
made (the questions are ones Ledger refuses before calling Gemini). Prints the process's memory,
which has to fit Community Cloud's limit (2.7 GB at the time of writing).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_LIMIT_MB = 2000  # headroom under Community Cloud's 2.7 GB


def _widget(items: list, label: str):  # type: ignore[no-untyped-def]
    return next(w for w in items if w.label == label)


def _ask(at, question: str) -> None:  # type: ignore[no-untyped-def]
    _widget(at.text_input, "Question").set_value(question).run()
    _widget(at.button, "Ask").click().run()
    assert not at.exception, [e.value for e in at.exception]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--real", action="store_true", help="also ask one real question (1 request)"
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.setdefault("LEDGER_API", "embedded")
    import psutil
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "ui" / "streamlit_app.py"), default_timeout=1200)
    started = time.monotonic()
    at.run()
    print(f"first load: {time.monotonic() - started:.0f} s")
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]  # "No filings are loaded"

    labels = [e.label for e in at.sidebar.expander]
    loaded = next(label for label in labels if label.startswith("Companies loaded"))
    print("sidebar:", loaded)
    assert int(loaded.split("(")[1].rstrip(")")) >= 30, "the demo index did not load"

    _ask(at, "Should I buy Tesla stock?")
    assert any("investment advice" in w.value for w in at.warning), [w.value for w in at.warning]
    _ask(at, "What was the revenue last year?")
    assert any("which company" in w.value for w in at.warning), [w.value for w in at.warning]
    print("probes passed: advice refused, no-company refused")

    if args.real:
        _ask(at, "What was Apple's revenue in fiscal year 2023?")
        text = " ".join(m.value for m in at.markdown)
        assert "383,285" in text, text[:400]
        print("real question answered with the cited figure")

    rss = psutil.Process().memory_info().rss / 1e6
    print(f"memory: {rss:.0f} MB resident (limit to stay under: {MEMORY_LIMIT_MB} MB)")
    assert rss < MEMORY_LIMIT_MB, "too much memory for Streamlit Community Cloud"
    return 0


if __name__ == "__main__":
    sys.exit(main())
