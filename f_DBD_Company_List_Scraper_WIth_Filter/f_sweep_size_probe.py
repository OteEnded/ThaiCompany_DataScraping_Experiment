"""Confirm filters compose with ID-prefix keywords, and size the filtered sweep."""
from playwright.sync_api import sync_playwright
import f_main

PROD = {"jpStatusList": ["1"], "jpTypeList": ["5", "7"],
        "capAmtMin": 5000000, "capAmtMax": 100000000000,
        "totalIncomeMin": 100000000, "netProfitMin": 10000000}

TESTS = [("0105", False), ("0105", True), ("010556", True), ("0107561", True),
         ("0125", True), ("0203", True)]

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

    print(f"  {'prefix':10} {'filters':8} {'rows':5} {'pages':9} on_prefix")
    for kw, use_f in TESTS:
        body = dict(base); body["keyword"] = kw; body["currentPage"] = 1
        if use_f: body.update(PROD)
        res = f_main.replay_infos_request(page, cap["c"], override_body=body)
        rows = res.get("extracted_companies") or []
        tp = f_main.extract_total_pages_hint(res.get("decrypted_data") or res.get("data"))
        on = sum(1 for r in rows if str(r.get("juristic_id") or "").startswith(kw))
        print(f"  {kw:10} {str(use_f):8} {len(rows):<5} {str(tp):9} {on}/{len(rows)}")
        page.wait_for_timeout(2500)
    browser.close()
