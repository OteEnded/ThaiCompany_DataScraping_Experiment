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
- `sort_label`: UI sort label to apply before capture/replay (optional).
- `prefer_direct_search_url`: use direct result URL first, then fallback to search-box submit.
- `pages`: page count (`-1` means fetch until end).
- `fetch_all_max_pages`: hard cap for fetch-all mode to avoid runaway replay.
- `headless`: browser mode.
- `channel`: `chromium | chrome | msedge`.
- `settle_seconds`: extra wait after landing.
- `results_timeout_seconds`: long wait budget for slow result loading.
- `resume_from_page`: replay continuation start page (default 1).
- `track_progress_in_config`: enable writing latest extracted page back to config.
- `runtime_progress.last_page_extracted`: persisted latest extracted page checkpoint.
- `runtime_progress.updated_at`: timestamp of last checkpoint update.
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
5. Validate captured body and rebuild filtered replay payload from config when filter keys are missing.
6. Replay API request for pages 2..N (or continue from configured `resume_from_page`).

---

## Runtime Logs and Diagnostics
Process `f` writes runtime telemetry to:
- `last_run.log`: timestamped run logs (also mirrored to console).
- `last_page_on.png`: latest UI wait-state screenshot (overwritten each capture).

Log highlights:
- Strategy decision (direct URL vs search-box fallback)
- Filter readiness/apply milestones
- Replay progress in `current/last` format
- Total pages hint and bounded replay target
- Per-page duration and overall run duration summary

Probe/test helper files used during UI fallback validation:
- `f_ui_probe_page5_test.py`: dedicated no-filter proof runner with strict page-1-loaded gate before page-5 jump.
- `tmp_ui_probe_page5_test.log`: temporary proof log (generated on demand).
- `tmp_ui_probe_page5_result.json`: temporary proof result (generated on demand).
- `tmp_ui_probe_page3_test.log`: temporary focused target-page-3 proof log (generated on demand).
- `tmp_ui_probe_page3_result.json`: temporary focused target-page-3 proof result (generated on demand).

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
- Filter payload guard that enforces config-derived filters when captured replay body is incomplete.
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
- Fetch-all mode (`pages = -1`) can still be long; always set a sensible `fetch_all_max_pages` cap.
- DBD can enter an infinite-loading UI state where readiness signals appear but extractable data rows never materialize.
- In that state, strict row-gated probes can legitimately return `partial`/blocked outcomes even when paginator text appears valid.

### Latest Runtime Hardening (2026-04-06)
- Slower retry cadence for UI row-confirmation loops:
  - `f_main.py` and `f_ui_probe_page5_test.py` now wait `1500ms` between loaded-row retry polls (previously `700ms`).
- Main benefit:
  - Reduced overly-aggressive retry churn while waiting for real table rows during slow UI transitions.
- Operational note:
  - Keep using strict gate: do not navigate to target page until page-1 rows are truly extractable.
  - If DBD remains loading-only for too long, stop the run and retry later rather than forcing navigation.

### Latest Page-Nav Fix (2026-04-06)
- Fixed rollback risk where page could move to target (for example page 3) and then snap back to page 2.
- Root cause in prior logic: after paginator input + Enter, runtime could still click a local pager arrow heuristically.
- Hardening applied in `f_main.py`:
  - removed auto-arrow click from input-jump path,
  - removed auto-arrow click from rescue recommit path,
  - kept target-page verification via multi-signal page checks and row-confirmation waits.
- Focused validation run (no-filter, `--target-page 3`) completed with:
  - status `ok`,
  - page-1 rows `10`,
  - page-3 rows `10`,
  - `target_success=true`.

### Latest Output Lineage Update (2026-04-06)
- Added per-row lineage field: `data_from_page`.
- Field is populated for all row sources:
  - UI extraction rows,
  - API replay rows,
  - replay-probe rows.
- `result_packed.csv` now includes `data_from_page`.
- Validation status:
  - logic and schema wiring confirmed,
  - uninterrupted live 3-page run evidence is still pending a stable execution window.

### Province Sort Caveat (Important)
- UI label `จังหวัด (ก-ฮ)` maps to API `sortBy=pvDesc`.
- Live probing confirmed `pvDesc` is pagination-unstable: many duplicate companies can repeat across pages.
- Current runtime intentionally uses a stable API sort for replay (`jpName`) and then post-sorts final output by province.
- This is why logs may show:
  - `Replay payload sortBy: requested=pvDesc, actual_api=jpName (pvDesc pagination workaround)`

Probing summary (filtered scenario, 5-page sample):
- `pvDesc`: duplicate-heavy across pages (unstable)
- `locationProvince.pvDesc`: unique rows across tested pages (stable in probe)
- `pvCode`: unique rows across tested pages (stable in probe)
- `jpName`: unique rows across tested pages (stable in probe)

Note:
- Stable alternatives above were verified by probing and are candidates for future auto-selection logic.
- Current production-safe behavior remains `pvDesc -> jpName` with final province post-sort.

---

## Recommended Workflow
1. Adjust `f_local_config.json` (search term, pages, filters).
2. Run script with default config command.
3. Check `f_search_result.json` and `result_packed.csv`.
4. If partial/blocked, inspect `dumps/` and increase timeout or re-run with warmed session.
