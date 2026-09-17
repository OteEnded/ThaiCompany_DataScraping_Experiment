"""Test whether juristic-ID prefixes work as an exhaustive search partition."""
import collections
from pathlib import Path
from playwright.sync_api import sync_playwright
import f_main

TESTS = ["0105", "010756", "0107561", "0125", "0993"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome",
                                args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(locale="th-TH", timezone_id="Asia/Bangkok")
    page = ctx.new_page()
    cap = {"c": None}
    ctx.on("response", lambda r: cap.__setitem__("c", f_main.extract_request_contract(r.request))
           if "/api/v1/company-profiles/infos" in r.url and cap["c"] is None else None)

    page.goto(f_main.BASE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    f_main.dismiss_startup_overlays(page)
    box = page.locator("form.form-group.search.lg input.form-control").first
    box.click(); box.fill("โอสถสภา"); page.wait_for_timeout(800)
    icon = page.locator("#searchicon").first
    icon.click(timeout=3000) if icon.count() else box.press("Enter")
    page.wait_for_timeout(10000)

    if not cap["c"]:
        print("!! no contract"); browser.close(); raise SystemExit
    base = dict(cap["c"].get("body") or {})

    for kw in TESTS:
        body = dict(base); body["keyword"] = kw; body["currentPage"] = 1
        res = f_main.replay_infos_request(page, cap["c"], override_body=body)
        rows = res.get("extracted_companies") or []
        payload = res.get("decrypted_data") or res.get("data")
        tp = f_main.extract_total_pages_hint(payload)
        msg = ""
        if isinstance(payload, dict):
            for k in ("message", "msg", "errorMessage"):
                if isinstance(payload.get(k), str) and payload[k].strip():
                    msg = payload[k].strip()[:60]; break
        starts = sum(1 for r in rows if str(r.get("juristic_id") or "").startswith(kw))
        contains = sum(1 for r in rows if kw in str(r.get("juristic_id") or ""))
        print(f"  {kw:9} http={res.get('status'):<4} rows={len(rows):<3} pages={str(tp):<7} "
              f"prefix_match={starts}/{len(rows)} substr={contains}/{len(rows)}  {msg}")
        for r in rows[:3]:
            print(f"        {r.get('juristic_id')}  {str(r.get('company_name'))[:42]}")
        page.wait_for_timeout(2500)
    browser.close()
