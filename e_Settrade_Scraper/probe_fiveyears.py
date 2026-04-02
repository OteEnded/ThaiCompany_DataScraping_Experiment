"""Probe the five-years financial statement page to find API patterns."""
from playwright.sync_api import sync_playwright
import json

SYM = "OSP"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = ctx.new_page()

    apis = {}

    def on_resp(r):
        if "settrade.com/api" in r.url:
            try:
                body = r.json()
                apis[r.url] = {"status": r.status, "body": body}
            except Exception:
                apis[r.url] = {"status": r.status, "body": None}

    ctx.on("response", on_resp)

    page.goto(
        f"https://www.settrade.com/th/equities/quote/{SYM}/financial-statement/five-years",
        wait_until="networkidle",
        timeout=45000,
    )
    page.wait_for_timeout(5000)
    # scroll to trigger lazy-loaded components
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3000)

    print("APIs called:")
    for url, info in sorted(apis.items()):
        body_preview = str(info["body"])[:100] if info["body"] else ""
        print(f"  [{info['status']}] {url}")
        if info["body"] and SYM in url:
            print(f"         -> {body_preview}")

    # Save
    with open("e_Settrade_Scraper/probe_fiveyears.json", "w", encoding="utf-8") as f:
        json.dump(apis, f, ensure_ascii=False, indent=2)
    print("\nSaved: e_Settrade_Scraper/probe_fiveyears.json")

    page.screenshot(path="e_Settrade_Scraper/probe_fiveyears.png")
    browser.close()
