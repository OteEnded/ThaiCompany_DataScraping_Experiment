"""
Settrade stock data scraper.

Uses a headless browser to call Settrade's REST APIs with the live browser session.
Confirmed working endpoints (all return 200 without login):
  profile, info, overview, shareholder, historical-trading, corporate-action.
Financial statements are not available via REST API without authentication.

Usage:
    python s_scrape.py --symbol OSP
    python s_scrape.py --symbol AOT --headless
"""

import argparse
import datetime
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent

# Confirmed working REST endpoints (probed 2025-03)
ENDPOINTS = {
    "profile":          "/api/set/stock/{sym}/profile",
    "info":             "/api/set/stock/{sym}/info",
    "overview":         "/api/set/stock/{sym}/overview",
    "shareholder":      "/api/set/stock/{sym}/shareholder",
    "historical":      "/api/set/stock/{sym}/historical-trading?period=MAX",
    "corporate_action": "/api/set/stock/{sym}/corporate-action",
}

FETCH_JS = """
async (endpoints) => {
    const results = {};
    for (const [key, path] of Object.entries(endpoints)) {
        try {
            const resp = await fetch(path, {credentials: 'include'});
            let body = null;
            if (resp.ok) {
                try { body = await resp.json(); } catch {}
            }
            results[key] = {status: resp.status, ok: resp.ok, body: body};
        } catch(e) {
            results[key] = {status: 'error', ok: false, body: null, error: String(e)};
        }
    }
    return results;
}
"""


def scrape(symbol: str, headless: bool = True) -> dict:
    sym = symbol.upper()
    endpoints = {k: v.format(sym=sym) for k, v in ENDPOINTS.items()}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        # Load Settrade to get session cookies
        page.goto(
            "https://www.settrade.com/th/equities/company-snapshot",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)

        print(f"Fetching data for {sym}...")
        raw = page.evaluate(FETCH_JS, endpoints)
        browser.close()

    data = {
        "symbol": sym,
        "scraped_at": datetime.datetime.now().isoformat(),
    }
    for key, result in raw.items():
        status = result.get("status")
        body = result.get("body")
        if result.get("ok") and body:
            data[key] = body
            print(f"  [{status}] OK  {key}")
        else:
            data[key] = None
            print(f"  [{status}] --  {key}")

    return data


def _md_value(v) -> str:
    if v is None:
        return ""
    return str(v)


def save(data: dict) -> None:
    sym = data["symbol"]

    # ── JSON ─────────────────────────────────────────────────────────────
    json_path = BASE_DIR / f"settrade_{sym}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {json_path}")

    # ── Markdown summary ──────────────────────────────────────────────────
    profile = data.get("profile") or {}
    info = data.get("info") or {}
    overview = data.get("overview") or {}
    shareholders = data.get("shareholder") or {}
    corp_actions = data.get("corporate_action") or []
    hist = data.get("historical") or []

    md = [
        f"# {sym} — Settrade Data",
        f"",
        f"**Scraped:** {data.get('scraped_at', '')}",
        f"",
        "## Company Profile",
        f"- Name: {_md_value(profile.get('name'))}",
        f"- Market: {_md_value(profile.get('market'))}",
        f"- Industry: {_md_value(profile.get('industry'))} / Sector: {_md_value(profile.get('sector'))}",
        f"- Security Type: {_md_value(profile.get('securityType'))} ({_md_value(profile.get('securityTypeName'))})",
        f"- Status: {_md_value(profile.get('status'))}",
        f"- Listed Date: {_md_value(profile.get('listedDate'))}",
        f"- Fiscal Year End: {_md_value(profile.get('fiscalYearEnd'))}",
        f"- Par Value: {_md_value(profile.get('par'))} {_md_value(profile.get('currency'))}",
        f"- Listed Shares: {_md_value(profile.get('listedShare'))}",
        f"- IPO Price: {_md_value(profile.get('ipo'))}",
        f"- Free Float: {_md_value(profile.get('percentFreeFloat'))}%",
        f"- Foreign Limit: {_md_value(profile.get('percentForeignLimit'))}%",
        f"- Foreign Room: {_md_value(profile.get('percentForeignRoom'))}%",
        f"- ISIN (Local): {_md_value(profile.get('isinLocal'))}",
        f"- ISIN (Foreign): {_md_value(profile.get('isinForeign'))}",
        "",
        "## Trading Info (Latest)",
        f"- Last Price: {_md_value(info.get('last'))} THB",
        f"- Prior Close: {_md_value(info.get('prior'))}",
        f"- Change: {_md_value(info.get('change'))} ({_md_value(info.get('percentChange'))}%)",
        f"- Open: {_md_value(info.get('open'))}  High: {_md_value(info.get('high'))}  Low: {_md_value(info.get('low'))}",
        f"- Average: {_md_value(info.get('average'))}",
        f"- Floor / Ceiling: {_md_value(info.get('floor'))} / {_md_value(info.get('ceiling'))}",
        f"- Total Volume: {_md_value(info.get('totalVolume'))}",
        f"- Total Value: {_md_value(info.get('totalValue'))}",
        "",
        "## Overview",
        f"- Indices: {', '.join(overview.get('indices') or [])}",
        f"- CG Score: {_md_value(overview.get('cgScore'))}",
        f"- SET ESG Rating: {_md_value(overview.get('setesgRating'))}",
        f"- CAC Flag: {_md_value(overview.get('cacFlag'))}",
        f"- Logo: {_md_value(overview.get('logoUrl'))}",
        "",
        "## Major Shareholders",
    ]

    major = shareholders.get("majorShareholders") or [] if isinstance(shareholders, dict) else []
    for sh in major[:10]:
        md.append(
            f"  {sh.get('sequence', '')}. {sh.get('name', '')} "
            f"— {sh.get('percentOfShare', '')}% "
            f"({sh.get('numberOfShare', ''):,} shares)"
            if isinstance(sh.get("numberOfShare"), (int, float))
            else f"  {sh.get('sequence', '')}. {sh.get('name', '')} — {sh.get('percentOfShare', '')}%"
        )

    if isinstance(shareholders, dict):
        md += [
            "",
            f"- Book Close Date: {_md_value(shareholders.get('bookCloseDate'))}",
            f"- Total Shareholders: {_md_value(shareholders.get('totalShareholder'))}",
            f"- % Scriptless: {_md_value(shareholders.get('percentScriptless'))}%",
        ]

    md += ["", "## Corporate Actions (up to 10 recent)"]
    for ca in corp_actions[:10]:
        md.append(
            f"  - [{ca.get('caType', '')}] Record: {ca.get('recordDate', '')} "
            f"| Pay: {ca.get('paymentDate', '')} "
            f"| {ca.get('remark') or ''}"
        )

    if hist:
        last_rec = hist[0]
        oldest_rec = hist[-1]
        md += [
            "",
            f"## Historical Trading ({len(hist)} trading days, max ~6mo for unauthenticated access)",
            f"  Latest:  {last_rec.get('date', '')} | Close={last_rec.get('close', '')} "
            f"| Vol={last_rec.get('totalVolume', '')}",
            f"  Oldest:  {oldest_rec.get('date', '')} | Close={oldest_rec.get('close', '')} "
            f"| Vol={oldest_rec.get('totalVolume', '')}",
        ]

    md_path = BASE_DIR / f"settrade_{sym}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Saved: {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Settrade stock data scraper")
    parser.add_argument("--symbol", "-s", default="OSP", help="SET symbol, e.g. OSP, AOT")
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly (no window)")
    args = parser.parse_args()

    data = scrape(args.symbol, headless=args.headless)
    save(data)
    print(f"\nDone — {args.symbol}")


if __name__ == "__main__":
    main()

