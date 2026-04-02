"""Phase 3 probe:
 1. Load the search page to get browser session/cookies
 2. Try direct API URL patterns via in-page fetch() with live session
 3. Also try keyboard-navigate the dropdown after typing symbol
"""
from playwright.sync_api import sync_playwright
import json

SYMBOL = "OSP"

# Common Settrade API patterns to probe directly
API_PATTERNS = [
    "/api/set/stock/{sym}/company-snapshot",
    "/api/set/stock/{sym}/profile",
    "/api/set/stock/{sym}/info",
    "/api/set/stock/{sym}/company-profile",
    "/api/set/stock/{sym}/financial-statement",
    "/api/set/stock/{sym}/financials",
    "/api/set/stock/{sym}/financial-statement/fs-type-list",
    "/api/set/stock/{sym}/financial-ratio",
    "/api/set/stock/{sym}/dividend",
    "/api/set/stock/{sym}/shareholder",
    "/api/set/stock/{sym}/snapshot",
    "/api/set/stock/{sym}/overview",
    "/api/set/stock/{sym}",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    intercepted = {}

    def on_resp(response):
        url = response.url
        if "settrade.com/api" in url and SYMBOL.upper() in url.upper():
            try:
                data = response.json()
                intercepted[url] = data
                print(f"  SYMBOL API HIT: {url}")
            except Exception:
                pass

    context.on("response", on_resp)

    # Load page to establish live session / cookies
    page.goto("https://www.settrade.com/th/equities/company-snapshot", wait_until="domcontentloaded", timeout=30000)
    print("Loaded:", page.url)
    page.wait_for_timeout(4000)

    # ── Approach A: type + ArrowDown + Enter ────────────────────────────
    search_input = page.locator("input[placeholder='ใส่ชื่อย่อหลักทรัพย์, ชื่อบริษัท']")
    if search_input.count() == 0:
        search_input = page.locator("#__BVID__213___input__")
    print(f"Search input found: {search_input.count() > 0}")

    search_input.click()
    search_input.type(SYMBOL, delay=150)
    print(f"Typed: {SYMBOL}")
    page.wait_for_timeout(2500)

    # Dump dropdown HTML for debugging
    dropdown_html = page.evaluate("""
        () => {
            const candidates = [
                document.querySelector('[role=listbox]'),
                document.querySelector('.dropdown-menu'),
                document.querySelector('[class*=typeahead]'),
                document.querySelector('ul[id*=BVID]'),
            ];
            for (const el of candidates) {
                if (el) return el.outerHTML.substring(0, 2000);
            }
            return 'no dropdown found';
        }
    """)
    print("\nDropdown HTML snippet:\n", dropdown_html[:800])

    # Navigate with keyboard: ArrowDown selects first item, Enter confirms
    print("\nAttempting ArrowDown + Enter keyboard selection...")
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_timeout(8000)

    print("After keyboard select - URL:", page.url)
    print("Intercepted symbol APIs so far:", list(intercepted.keys()))

    # ── Approach B: probe direct API endpoints via browser fetch() ───────
    print("\nProbing direct API patterns via browser fetch()...")
    patterns_to_probe = [p.format(sym=SYMBOL) for p in API_PATTERNS]
    probe_results = page.evaluate(
        """
        async (patterns) => {
            const results = {};
            for (const path of patterns) {
                try {
                    const resp = await fetch(path, {credentials: 'include'});
                    let body = null;
                    if (resp.ok) {
                        try { body = await resp.json(); }
                        catch { body = await resp.text(); }
                    }
                    results[path] = {status: resp.status, ok: resp.ok, body: body};
                } catch(e) {
                    results[path] = {status: 'error', error: String(e)};
                }
            }
            return results;
        }
        """,
        patterns_to_probe,
    )

    print("\n── Direct API probe results ───────────────────────")
    working = {}
    for path, result in probe_results.items():
        status = result.get("status")
        ok = result.get("ok")
        body = result.get("body")
        body_preview = str(body)[:150] if body else "empty"
        mark = "OK " if ok and body else "---"
        print(f"  [{mark}] [{status}] {path}")
        if ok and body:
            print(f"          -> {body_preview}")
            working[path] = body

    # ── Save all results ─────────────────────────────────────────────────
    output = {
        "symbol": SYMBOL,
        "intercepted_symbol_apis": intercepted,
        "direct_api_probe": probe_results,
        "working_endpoints": working,
    }
    with open("e_Settrade_Scraper/probe_api_dump.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSaved: e_Settrade_Scraper/probe_api_dump.json")

    page.screenshot(path="e_Settrade_Scraper/probe_screenshot.png")
    print("Screenshot: e_Settrade_Scraper/probe_screenshot.png")

    browser.close()
