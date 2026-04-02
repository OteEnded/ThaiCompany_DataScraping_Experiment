"""
Clean probe: company-snapshot page, type OSP, enter to select, capture what fires.
No explicit fetch calls - only intercept what the PAGE itself calls.
"""
from playwright.sync_api import sync_playwright
import json, time

SYM = "OSP"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = ctx.new_page()

    log = []

    def on_resp(r):
        url = r.url
        if "settrade.com/api" in url:
            try:
                body = r.json()
                log.append({"t": time.time(), "status": r.status, "url": url, "body": body})
                print(f"  [{r.status}] {url}")
            except Exception:
                log.append({"t": time.time(), "status": r.status, "url": url, "body": None})

    ctx.on("response", on_resp)

    # Phase 1: load the page, note what fires
    print("=== Loading company-snapshot page ===")
    t0 = time.time()
    page.goto("https://www.settrade.com/th/equities/company-snapshot", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    print(f"  -- page load phase done in {time.time()-t0:.1f}s, {len(log)} API calls")

    # Phase 2: type OSP
    print("\n=== Typing OSP ===")
    n_before = len(log)
    search_input = page.locator("input[placeholder='ใส่ชื่อย่อหลักทรัพย์, ชื่อบริษัท']")
    if search_input.count() == 0:
        search_input = page.locator("#__BVID__213___input__")
    print(f"  Input found: {search_input.count() > 0}")
    search_input.click()
    search_input.type(SYM, delay=200)
    page.wait_for_timeout(3000)
    print(f"  -- after typing: {len(log) - n_before} new API calls")

    # Show dropdown HTML for debugging
    dd_html = page.evaluate("""
        () => {
            const el = document.querySelector('[role=listbox], [id*=BVID__213__], [class*=typeahead] ul, .autocomplete-results');
            return el ? el.outerHTML.substring(0, 2000) : 'not found';
        }
    """)
    print(f"  Dropdown HTML: {dd_html[:500]}")

    # Phase 3a: try ArrowDown + Enter
    print("\n=== Keyboard selection: ArrowDown + Enter ===")
    n_before2 = len(log)
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(800)
    highlighted = page.evaluate("() => document.activeElement ? document.activeElement.textContent : 'none'")
    print(f"  Active element text: {highlighted[:80]}")
    page.keyboard.press("Enter")
    page.wait_for_timeout(8000)
    new_apis = log[n_before2:]
    print(f"  -- {len(new_apis)} new APIs fired after Enter:")
    for entry in new_apis:
        print(f"     [{entry['status']}] {entry['url']}")

    # Phase 3b: If no result, try clicking the first visible result
    if not any(SYM in e["url"] for e in new_apis):
        print("\n=== Trying click on first dropdown item ===")
        n_b3 = len(log)
        # Try multiple potential selectors for dropdown option
        for sel in [
            f"[id*=BVID__213__] li:first-child",
            f"[id*=BVID] .autocomplete-result:first-child",
            f"ul[id*=BVID] > li:first-child",
            f"li[id*=BVID]:first-child",
        ]:
            loc = page.locator(sel)
            if loc.count() > 0:
                print(f"  Clicking: {sel} text='{loc.first.text_content()[:30]}'")
                try:
                    loc.first.click(timeout=3000)
                    page.wait_for_timeout(6000)
                    break
                except Exception as e:
                    print(f"  Error: {e}")
        print(f"  -- {len(log) - n_b3} new APIs after click")
        for entry in log[n_b3:]:
            print(f"     [{entry['status']}] {entry['url']}")

    print(f"\n=== Summary: {len(log)} total API calls ===")
    
    # Also dump full page HTML after interaction
    html = page.content()
    has_numbers = any(n in html for n in ["รายได้", "กำไร", "revenue", "profit"])
    print(f"Financial keywords in HTML: {has_numbers}")

    with open("e_Settrade_Scraper/probe_clean.json", "w", encoding="utf-8") as f:
        json.dump({"log": log}, f, ensure_ascii=False, indent=2)
    print("Saved: e_Settrade_Scraper/probe_clean.json")
    page.screenshot(path="e_Settrade_Scraper/probe_clean.png")
    browser.close()
