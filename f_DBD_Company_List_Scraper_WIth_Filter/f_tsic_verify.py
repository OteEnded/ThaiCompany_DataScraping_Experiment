"""Verify that a TSIC-code search returns only companies of that business type."""
import collections, json
from pathlib import Path
from playwright.sync_api import sync_playwright
import f_main

CODE = "41002"
BASE_DIR = Path(__file__).resolve().parent

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
    allrows, codes = [], collections.Counter()
    for pg in (1, 2, 50):
        body = dict(base); body["keyword"] = CODE; body["currentPage"] = pg
        res = f_main.replay_infos_request(page, cap["c"], override_body=body)
        rows = res.get("extracted_companies") or []
        print(f"  page {pg:<3} rows={len(rows)}")
        for r in rows:
            codes[r.get("business_type_code")] += 1
            allrows.append(r)
        page.wait_for_timeout(2500)

    print(f"\nbusiness_type_code distribution across {len(allrows)} rows from keyword {CODE!r}:")
    for c, n in codes.most_common():
        print(f"   {c} : {n}")
    match = codes.get(CODE, 0)
    print(f"\n  on-target: {match}/{len(allrows)} = {100*match/max(1,len(allrows)):.1f}%")
    print("\n  sample names:")
    for r in allrows[:5]:
        print(f"   [{r.get('business_type_code')}] {r.get('company_name')}")
    browser.close()
