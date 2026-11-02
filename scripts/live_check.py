"""Drive the deployed demo in a real browser and check it answers.

    python scripts/live_check.py URL [--real]

Opens the page (waking it if the app has gone to sleep), waits for the filings list, asks a
question Ledger refuses without a model call, and with ``--real`` one real question (one free
Gemini request on the live quota). Prints what the sidebar says about forwarding entries.
"""

from __future__ import annotations

import argparse
import re
import sys

from playwright.sync_api import Frame, Page, sync_playwright

WAIT_MS = 600_000  # a sleeping app needs minutes to wake and download the index


def app_frame(page: Page) -> Frame | Page:
    """Streamlit Community Cloud serves the app in an iframe; a local server does not."""
    page.wait_for_load_state("domcontentloaded")
    deadline = WAIT_MS / 1000
    waited = 0.0
    while waited < deadline:
        wake = page.get_by_role("button", name=re.compile("get this app back up", re.I))
        if wake.count():
            wake.first.click()
        for frame in page.frames:
            if frame.get_by_label("Question", exact=True).count():
                return frame
        if page.get_by_label("Question", exact=True).count():
            return page
        page.wait_for_timeout(2000)
        waited += 2
    raise SystemExit("The question box never appeared: the app did not start in 10 minutes.")


def ask(app: Frame | Page, question: str) -> None:
    box = app.get_by_label("Question", exact=True)
    box.fill(question)
    box.press("Enter")  # commit the value before clicking
    app.get_by_role("button", name="Ask", exact=True).click()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(args.url, timeout=120_000)
        app = app_frame(page)
        loaded = app.get_by_text(re.compile(r"Companies loaded \(\d+\)")).first
        loaded.wait_for(timeout=WAIT_MS)
        text = loaded.inner_text()
        print("sidebar:", text)
        assert int(re.search(r"\((\d+)\)", text).group(1)) >= 30, "the demo index did not load"

        app.get_by_text("About this demo").first.click()
        note = app.get_by_text(re.compile("Forwarding entries seen")).first.inner_text()
        print("diagnostic:", re.search(r"Forwarding entries seen[^.]*\.", note).group(0))

        ask(app, "Should I buy Tesla stock?")
        app.get_by_text(re.compile("investment advice", re.I)).first.wait_for(timeout=120_000)
        print("advice question refused")
        if args.real:
            ask(app, "What was Apple's revenue in fiscal year 2023?")
            app.get_by_text(re.compile("383,285")).first.wait_for(timeout=180_000)
            print("real question answered with the cited figure")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
