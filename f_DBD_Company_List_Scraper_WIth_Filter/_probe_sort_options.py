from pathlib import Path
import json
from playwright.sync_api import sync_playwright

base = Path(r"c:/data/AI_Search/f_DBD_Company_List_Scraper_WIth_Filter")
storage = base / "storage_state.json"
url = "https://datawarehouse.dbd.go.th/juristic/searchInfo?keyword=%E0%B8%9A%E0%B8%A3%E0%B8%B4%E0%B8%A9%E0%B8%B1%E0%B8%97"

with sync_playwright() as p:
    kwargs = {"headless": False, "channel": "chromium"}
    browser = p.chromium.launch(**kwargs)
    context_kwargs = {}
    if storage.exists():
        context_kwargs["storage_state"] = str(storage)
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    result = page.evaluate('''
    () => {
      const normalize = (t) => (t || '').replace(/\s+/g, ' ').trim();
      const selects = Array.from(document.querySelectorAll('select'))
        .filter((el) => el.offsetParent !== null && el.options && el.options.length > 0);

      const groups = [];
      for (const sel of selects) {
        const options = Array.from(sel.options || []).map((o) => ({
          value: String(o.value || '').trim(),
          label: normalize(o.textContent)
        })).filter((x) => x.label);
        if (!options.length) continue;

        const selected = sel.options && sel.selectedIndex >= 0 ? normalize(sel.options[sel.selectedIndex].textContent) : '';
        const signature = options.map((x) => x.label).join(' | ');
        groups.push({ selected, options, signature });
      }

      // de-duplicate by exact option-label signature
      const seen = new Set();
      const uniqueGroups = [];
      for (const g of groups) {
        if (seen.has(g.signature)) continue;
        seen.add(g.signature);
        uniqueGroups.push(g);
      }

      // Heuristic: sorting select usually contains Thai alpha-order marker "(ก-ฮ)"
      let likelySort = null;
      for (const g of uniqueGroups) {
        if (g.options.some((o) => o.label.includes('(ก-ฮ)') || o.label.includes('(ฮ-ก)'))) {
          likelySort = g;
          break;
        }
      }

      return {
        select_count: selects.length,
        unique_group_count: uniqueGroups.length,
        likely_sort_options: likelySort ? likelySort.options : [],
        unique_groups: uniqueGroups
      };
    }
    ''')

    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
