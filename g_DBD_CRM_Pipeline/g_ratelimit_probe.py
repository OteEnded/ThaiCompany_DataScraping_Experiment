"""Single-request probe: is the 429 a short cooldown or a longer quota?

Makes ONE API call (plus the seed search) and reports the status. Deliberately
minimal - the point is to test the limit, not to add load to it.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "f_DBD_Company_List_Scraper_WIth_Filter"))
from playwright.sync_api import sync_playwright
import g_session

with sync_playwright() as p:
    sess = g_session.SweepSession(p, headless=False, log=print)
    if not sess.open():
        print("RESULT: could not even seed a session (search/token blocked)")
        raise SystemExit
    res = sess.fetch("0145", {"jpStatusList": ["1"], "jpTypeList": ["5", "7"],
                              "capAmtMin": 100000001}, 1)
    print()
    print(f"RESULT: status={res['status']} ok={res['ok']} rows={len(res['rows'])} "
          f"pages={res['total_pages']} blocked={res['blocked']}")
    if res["status"] == 429:
        print("  -> still rate limited; this is not a short cooldown")
    elif res["ok"]:
        print("  -> limit has lifted; it was a short cooldown")
    sess.close()
