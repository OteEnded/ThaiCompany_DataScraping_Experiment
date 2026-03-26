"""Probe to discover Settrade's financial statement API patterns."""
from playwright.sync_api import sync_playwright
import json

SYM = "OSP"

FINANCIAL_PATTERNS = [
    "/api/set/stock/{sym}/financial-statement?fsType=QY&period=5Y&lang=th",
    "/api/set/stock/{sym}/financial-statement?type=annual&language=th",
    "/api/set/stock/{sym}/financial-statement?account=S&period=A&lang=th",
    "/api/set/stock/{sym}/financial-ratio?fsType=QY&period=5Y",
    "/api/set/stock/{sym}/financial-ratio",
    "/api/set/stock/{sym}/financials?language=th",
    "/api/set/stock/{sym}/historical-trading?period=1D",
    "/api/set/stock/{sym}/dividend",
    "/api/set/stock/{sym}/dividend?lang=th",
    "/api/set/stock/{sym}/dividend?period=5Y",
    "/api/set/stock/{sym}/company-snapshot?lang=th",
    "/api/set/company-snapshot/list?symbols={sym}&lang=th",
    "/api/set/company-snapshot/list?symbols={sym}&lang=en",
    "/api/set/stock/{sym}/financialratio",
    "/api/set/stock/{sym}/financial_ratio",
]

JS_FETCH = """
async (paths) => {
    const out = {};
    for (const p of paths) {
        try {
            const r = await fetch(p, {credentials: 'include'});
            let body = null;
            try { body = await r.json(); } catch(e) { body = null; }
            out[p] = {s: r.status, body: body};
        } catch(e) {
            out[p] = {s: 'error', body: null};
        }
    }
    return out;
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = ctx.new_page()

    intercepted = {}
    def on_resp(r):
        if "settrade.com/api" in r.url and SYM in r.url:
            try:
                intercepted[r.url] = {"status": r.status, "body": r.json()}
            except Exception:
                pass
    ctx.on("response", on_resp)

    # Load the financial-statement quote page to get session
    page.goto(
        f"https://www.settrade.com/th/equities/quote/{SYM}/financial-statement",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(5000)

    print("Intercepted by page load:")
    for url in intercepted:
        print(f"  {intercepted[url]['status']} {url}")

    # Probe financial patterns
    patterns_to_probe = [pt.format(sym=SYM) for pt in FINANCIAL_PATTERNS]
    results = page.evaluate(JS_FETCH, patterns_to_probe)

    print("\n── Financial API probe ─────────────────────────────")
    working = {}
    for path, r in results.items():
        status = r.get("s")
        body = r.get("body")
        mark = "OK " if status == 200 and body else "---"
        print(f"  [{mark}] [{status}] {path}")
        if status == 200 and body:
            print(f"         -> {str(body)[:200]}")
            working[path] = body

    # Also intercept via page navigation tab clicks
    tabs = page.locator("a[href*='financial'], button:has-text('Financial'), li:has-text('Financial')")
    print(f"\nFinancial tab elements found: {tabs.count()}")
    for i in range(min(tabs.count(), 5)):
        print(f"  {tabs.nth(i).text_content()} | {tabs.nth(i).get_attribute('href')}")

    out = {
        "symbol": SYM,
        "page": "financial-statement",
        "intercepted": intercepted,
        "probe": results,
        "working": working,
    }
    with open("s_scape/probe_financial.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nSaved: s_scape/probe_financial.json")
    page.screenshot(path="s_scape/probe_financial.png")
    browser.close()
