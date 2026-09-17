"""Probe the DBD broad-query guard.

Goal: find out WHERE the "กรุณาระบุคำค้นหาให้เฉพาะเจาะจงมากขึ้น" guard lives
(UI only, or server-side on /api/v1/company-profiles/infos) and which request
shapes still return rows. Read-only: performs a handful of requests, writes no
project outputs except its own JSON report.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import f_main

BASE_DIR = Path(__file__).resolve().parent
REPORT = BASE_DIR / "dumps" / "f_guard_probe_report.json"

PROD_FILTERS = {
    "jpStatusList": ["1"],
    "jpTypeList": ["5", "7"],
    "capAmtMin": 5000000,
    "capAmtMax": 100000000000,
    "totalIncomeMin": 100000000,
    "netProfitMin": 10000000,
}

# Each variant: (label, body-overrides applied on top of captured contract body)
VARIANTS = [
    ("A_tsic_41002_plain",        {"keyword": "41002"}),
    ("B_tsic_41002_filters",      {"keyword": "41002", **PROD_FILTERS}),
    ("C_tsic_45101_plain",        {"keyword": "45101"}),
    ("D_tsic_47300_filters",      {"keyword": "47300", **PROD_FILTERS}),
    ("E_tsic_41002_deep_page50",  {"keyword": "41002", "_page": 50}),
    ("F_tsic_41002_filt_page20",  {"keyword": "41002", **PROD_FILTERS, "_page": 20}),
    ("G_partnership_word",        {"keyword": "ห้างหุ้นส่วน"}),
    ("H_jpname_word",             {"keyword": "จำกัด"}),
]


def summarize(res: dict) -> dict:
    payload = res.get("decrypted_data") or res.get("data")
    total_pages = f_main.extract_total_pages_hint(payload)
    msg = ""
    if isinstance(payload, dict):
        for k in ("message", "msg", "errorMessage", "description", "status"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                msg = v.strip()[:160]
                break
    return {
        "http_status": res.get("status"),
        "ok": res.get("ok"),
        "rows": res.get("extracted_count", 0),
        "total_pages": total_pages,
        "decrypt_error": res.get("decrypted_error"),
        "server_message": msg,
        "payload_keys": list(payload.keys())[:12] if isinstance(payload, dict) else type(payload).__name__,
    }


def main() -> None:
    seed = sys.argv[1] if len(sys.argv) > 1 else "โอสถสภา"
    report = {"seed_keyword": seed, "variants": {}}
    captured = {"contract": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(locale="th-TH", timezone_id="Asia/Bangkok")
        page = ctx.new_page()

        def on_response(response):
            if "/api/v1/company-profiles/infos" in response.url and captured["contract"] is None:
                captured["contract"] = f_main.extract_request_contract(response.request)

        ctx.on("response", on_response)

        print(f"[1] landing page ...")
        page.goto(f_main.BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        f_main.dismiss_startup_overlays(page)

        print(f"[2] seed search via search box: {seed!r}")
        selectors = [
            "form.form-group.search.lg input.form-control",
            "input[placeholder*='ค้นหาด้วยชื่อหรือเลขทะเบียนนิติบุคคล รหัสประเภทธุรกิจ']",
            "input[placeholder*='ชื่อหรือเลขทะเบียนนิติบุคคล']",
            "form#form input.form-control",
            "input[type='text']",
            "input",
        ]
        box = None
        for sel in selectors:
            loc = page.locator(sel).first
            if loc.count() > 0:
                box = loc
                print(f"    search box matched: {sel}")
                break
        if box is None:
            print("!! no search input found")
            report["error"] = "no_search_input"
            REPORT.parent.mkdir(exist_ok=True)
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()
            return

        box.click()
        box.fill(seed)
        page.wait_for_timeout(1000)
        try:
            icon = page.locator("#searchicon").first
            if icon.count() == 0:
                icon = page.locator("form.form-group.search.lg .icon-search").first
            if icon.count() > 0:
                icon.click(timeout=3000)
            else:
                box.press("Enter")
        except Exception:
            box.press("Enter")
        page.wait_for_timeout(10000)

        if not captured["contract"]:
            print("!! never captured infos contract - seed search may have failed")
            report["error"] = "no_contract_captured"
            REPORT.parent.mkdir(exist_ok=True)
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()
            return

        base_body = dict(captured["contract"].get("body") or {})
        report["captured_body"] = base_body
        print(f"[3] contract captured. base body = {base_body}")

        for label, overrides in VARIANTS:
            body = dict(base_body)
            ov = dict(overrides)
            page_no = ov.pop("_page", 1)
            body.update(ov)
            body["currentPage"] = page_no
            res = f_main.replay_infos_request(page, captured["contract"], override_body=body)
            s = summarize(res)
            report["variants"][label] = {"body": overrides, "page": page_no, **s}
            print(f"    {label:30} rows={s['rows']:<4} pages={str(s['total_pages']):<7} "
                  f"http={s['http_status']} msg={s['server_message'][:60]}")
            page.wait_for_timeout(2500)

        browser.close()

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {REPORT}")


if __name__ == "__main__":
    main()
