"""
Probe: look for financial data in the rendered HTML and intercept ALL requests
on the five-years financial statement page.
"""
from playwright.sync_api import sync_playwright
import json, re

SYM = "OSP"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = ctx.new_page()

    all_requests = []
    all_apis = {}

    def on_req(req):
        url = req.url
        if "settrade.com/api" in url:
            all_requests.append({"url": url, "method": req.method})

    def on_resp(r):
        if "settrade.com/api" in r.url:
            try:
                body = r.json()
                all_apis[r.url] = {"status": r.status, "body": body}
            except Exception:
                all_apis[r.url] = {"status": r.status, "body": None}

    ctx.on("request", on_req)
    ctx.on("response", on_resp)

    print(f"Loading financial page for {SYM}...")
    page.goto(
        f"https://www.settrade.com/th/equities/quote/{SYM}/financial-statement/five-years",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    # Wait for SPA to render (Vue/React hydration)
    page.wait_for_timeout(12000)

    # Scroll to trigger lazy components
    page.evaluate("window.scrollTo(0, 800)")
    page.wait_for_timeout(3000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3000)

    # Check for financial table in DOM
    html_snippet = page.evaluate("""
        () => {
            // look for tables with numbers
            const tables = Array.from(document.querySelectorAll('table, .financial-table, [class*=financial]'));
            if (tables.length > 0) return tables[0].outerHTML.substring(0, 2000);
            
            // look for main content area
            const main = document.querySelector('main') || document.querySelector('#app') || document.body;
            return main ? main.innerText.substring(0, 2000) : 'no content';
        }
    """)
    print("\n── Page content snippet ───────────────────────────")
    print(html_snippet[:1500])

    print("\n── ALL API requests fired ─────────────────────────")
    for req in all_requests:
        print(f"  {req['method']} {req['url']}")

    print("\n── API responses with OSP ─────────────────────────")
    for url, info in all_apis.items():
        if SYM in url:
            print(f"  [{info['status']}] {url}")
            if info["body"]:
                print(f"    -> {str(info['body'])[:150]}")

    with open("s_scape/probe_fiveyears2.json", "w", encoding="utf-8") as f:
        json.dump({"requests": all_requests, "responses": all_apis}, f, ensure_ascii=False, indent=2)
    print("\nSaved: s_scape/probe_fiveyears2.json")

    page.screenshot(path="s_scape/probe_fiveyears.png")
    browser.close()
