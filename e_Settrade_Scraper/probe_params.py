"""Quick probe for SET.OR.TH financial statement API patterns."""
from playwright.sync_api import sync_playwright

SYM = "OSP"
PATHS = [
    f"/api/set/stock/{SYM}/financial-statement?fsType=QY&period=5Y",
    f"/api/set/stock/{SYM}/financial-ratio?fsType=QY&period=5Y",
    f"/api/set/stock/{SYM}/dividend",
    f"/api/set/stock/{SYM}/balance-sheet",
    f"/api/set/stock/{SYM}/income-statement",
    f"/api/set/stock/{SYM}/cash-flow",
    f"/api/set/stock/{SYM}/key-financial-ratio",
    f"/api/set/stock/{SYM}/financial-highlight",
    f"/api/set/stock/{SYM}/earnings",
    f"/api/set/stock/{SYM}/annual-report",
    f"/api/set/stock/{SYM}/financial-data",
    f"/api/set/stock/{SYM}/corporate-action",
]

JS = """
async (paths) => {
    const out = {};
    for (const p of paths) {
        const r = await fetch(p, {credentials: 'include'});
        let b = null;
        try { b = await r.json(); } catch {}
        out[p] = {s: r.status, body: b ? JSON.stringify(b).substring(0, 300) : null};
    }
    return out;
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = ctx.new_page()
    page.goto("https://www.settrade.com/th/equities/quote/OSP/financial-statement/five-years", wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(3000)

    results = page.evaluate(JS, PATHS)
    for path, r in results.items():
        s = r.get("s")
        body = r.get("body")
        mark = "OK" if s == 200 and body and body != "[]" else "--"
        print(f"[{mark}][{s}] {path}")
        if body and body != "[]":
            print(f"        {body[:250]}")
    browser.close()
