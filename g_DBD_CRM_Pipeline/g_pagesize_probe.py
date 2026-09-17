"""Probe whether the DBD infos API accepts a page-size parameter.

At the observed 10 rows/page, the full 790,000-company plan costs 79,000 page
fetches. If the endpoint honours a larger page size, that number drops by the
same factor - the single highest-leverage optimization available, and worth
five minutes of probing before committing to weeks of scraping.

Tries the common spellings, and verifies the server actually RETURNED more rows
rather than just accepting the field and ignoring it.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent / "f_DBD_Company_List_Scraper_WIth_Filter"))

from playwright.sync_api import sync_playwright  # noqa: E402

import f_main  # noqa: E402

TEST_PREFIX = "0107"
CANDIDATES = [
    ("baseline (no size field)", {}),
    ("pageSize=100", {"pageSize": 100}),
    ("pageSize=50", {"pageSize": 50}),
    ("size=100", {"size": 100}),
    ("limit=100", {"limit": 100}),
    ("rowsPerPage=100", {"rowsPerPage": 100}),
    ("perPage=100", {"perPage": 100}),
    ("itemsPerPage=100", {"itemsPerPage": 100}),
    ("pageSize=20", {"pageSize": 20}),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(locale="th-TH", timezone_id="Asia/Bangkok")
        page = ctx.new_page()
        cap: dict = {}
        ctx.on(
            "response",
            lambda r: cap.setdefault("c", f_main.extract_request_contract(r.request))
            if "/api/v1/company-profiles/infos" in r.url else None,
        )

        page.goto(f_main.BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        f_main.dismiss_startup_overlays(page)
        box = page.locator("form.form-group.search.lg input.form-control").first
        box.click()
        box.fill("โอสถสภา")
        page.wait_for_timeout(800)
        icon = page.locator("#searchicon").first
        if icon.count():
            icon.click(timeout=3000)
        else:
            box.press("Enter")
        page.wait_for_timeout(10000)

        if not cap.get("c"):
            print("!! no contract captured")
            browser.close()
            return

        base = dict(cap["c"].get("body") or {})
        print(f"\n  {'variant':28} {'rows':>5} {'pages':>8}  note")
        baseline_pages = None
        for label, extra in CANDIDATES:
            body = dict(base)
            body["keyword"] = TEST_PREFIX
            body["currentPage"] = 1
            body.update(extra)
            res = f_main.replay_infos_request(page, cap["c"], override_body=body)
            rows = res.get("extracted_companies") or []
            payload = res.get("decrypted_data") or res.get("data")
            tp = f_main.extract_total_pages_hint(payload)
            if baseline_pages is None:
                baseline_pages = tp
            note = ""
            if len(rows) > 10:
                note = f"*** MORE ROWS ({len(rows)}) ***"
            elif tp and baseline_pages and tp < baseline_pages:
                note = f"*** FEWER PAGES ({baseline_pages} -> {tp}) ***"
            print(f"  {label:28} {len(rows):>5} {str(tp):>8}  {note}")
            page.wait_for_timeout(2200)

        browser.close()


if __name__ == "__main__":
    main()
