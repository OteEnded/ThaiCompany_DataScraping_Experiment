# Process F: DBD Company List Scraper (UI + API Hybrid)

## Overview
Process `f` scrapes DBD company list results from DataWarehouse with pagination and optional advanced filters.

It uses a hybrid strategy:
- UI path to open search and apply filters reliably.
- API replay path for efficient page-by-page extraction.
- Decrypt flow for encrypted API responses.

Primary goals:
- Collect large company lists safely and consistently.
- Support advanced filter combinations.
- Export clean JSON and packed CSV.

---

## Folder Contents
- `f_main.py`: main scraper script.
- `f_local_config.json`: local runtime config.
- `f_local_config_option.md`: config guide and harvested filter options.
- `f_search_result.json`: latest full JSON output.
- `result_packed.csv`: packed CSV output.
- `f_AI_Local_Context.md`: process history and current status.
- `dumps/`: debug and reverse-engineering artifacts.
  - `f_api_hits.json`
  - `f_infos_contract.json`
  - `f_infos_replay_result.json`
  - `f_filter_options_labels.json`
  - page dumps (`f_01_*.html`, `f_02_*.html`, etc.)

---

## Requirements
Install once in workspace root:

```powershell
pip install requests playwright cryptography
python -m playwright install chromium
```

Python 3.11+ recommended.

---

## Run
Default run (uses local config):

```powershell
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py
```

Explicit config path:

```powershell
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.json
```

---

## Config Model
The script reads runtime options from `f_local_config.json`.

Key fields:
- `search_term`: preferred search term key (default: `บริษัท`).
- `query`: backward-compatible alias of `search_term`.
- `pages`: page count (`-1` means fetch until end).
- `headless`: browser mode.
- `channel`: `chromium | chrome | msedge`.
- `settle_seconds`: extra wait after landing.
- `results_timeout_seconds`: long wait budget for slow result loading.
- `storage_state`: path to Playwright storage state.
- `use_storage_state`: enable/disable storage state use.
- `filters`: advanced filter object.

Suggested search terms:
- `บริษัท`
- `ห้างหุ้นส่วน`

Detailed option list is maintained in `f_local_config_option.md`.

---

## Filter Support
Advanced filter UI fields are supported:
- จังหวัดที่ตั้ง (`province_codes`)
- สถานะ (`status_codes`)
- ประเภทนิติบุคคล (`juristic_type_codes`)
- ขนาดธุรกิจ (`business_size_codes`)
- ทุนจดทะเบียน (min/max)
- รายได้รวม (min/max)
- กำไรสุทธิ (min/max)
- สินทรัพย์ (min/max)

Runtime behavior:
1. Wait for list readiness (table rows OR filter button visible OR total count visible).
2. Open advanced filter panel and apply selected values.
3. Submit filter search in UI.
4. Capture latest `infos` API request contract.
5. Replay API request for pages 2..N.

---

## Reverse-Engineered API Contract
Endpoint:
- `POST /api/v1/company-profiles/infos`

Base body keys:
- `keyword`
- `type`
- `sortBy`
- `currentPage`

Filter body keys observed from UI apply:
- `pvCodeList`
- `jpStatusList`
- `jpTypeList`
- `businessSizeList`
- `capAmtMin`, `capAmtMax`
- `totalIncomeMin`, `totalIncomeMax`
- `netProfitMin`, `netProfitMax`
- `totalAssetMin`, `totalAssetMax`

---

## Anti-Bot and Reliability Strategy
The target site can be unstable and may block requests (e.g., Imperva Error 15).

Resilience features in script:
- Overlay dismissal (cookie/warning/chat UI).
- Direct search URL fallback when submit flow is flaky.
- Multi-signal result readiness check with long timeout.
- API replay retries/backoff for transient errors.
- Storage-state reuse to keep session continuity.
- Structured blocked/partial statuses instead of hard crash.

If blocked:
- Re-run non-headless.
- Keep `storage_state.json` warmed.
- Increase `results_timeout_seconds`.

---

## Output Schema
Main list rows are normalized into these keys:
- `juristic_id`
- `company_name`
- `juristic_type`
- `status`
- `business_type_code`
- `business_type_name`
- `province`
- `registered_capital_baht`
- `total_revenue_baht`
- `net_profit_baht`
- `total_assets_baht`
- `shareholders_equity_baht`
- `profile_url`

CSV (`result_packed.csv`) uses a fixed column order and UTF-8 BOM for spreadsheet compatibility.

---

## Debug Artifacts
Important debug fields in `f_search_result.json`:
- `status`
- `error`
- `infos_contract`
- `latest_infos_contract`
- `effective_infos_body`
- `api_hit_summary`
- `debug.ui_filters_applied`
- `debug.filter_apply_error`
- `debug.api_replay_page_stats`

Use `dumps/` files to inspect request/response flow and HTML snapshots.

---

## Known Caveats
- Site performance and anti-bot behavior vary by session/time.
- Some runs may not expose list API immediately.
- Fetch-all mode (`pages = -1`) can be very long; use cautiously.

---

## Recommended Workflow
1. Adjust `f_local_config.json` (search term, pages, filters).
2. Run script with default config command.
3. Check `f_search_result.json` and `result_packed.csv`.
4. If partial/blocked, inspect `dumps/` and increase timeout or re-run with warmed session.
