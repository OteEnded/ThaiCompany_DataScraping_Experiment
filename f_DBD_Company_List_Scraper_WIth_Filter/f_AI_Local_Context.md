# f_AI_Local_Context.md

## Scope
Process `f` explores and scrapes company-list results from DBD DataWarehouse search pages.

Initial objective:
- Use broad query term `บริษัท` to trigger large result set.
- Iterate paginated list (10 rows per page on UI) and collect company candidates.

Long-term objective:
- Add filter-driven list extraction (targeted cohorts) instead of only broad query paging.

## Entrypoint
- Script: `f_main.py`
- Local run config: `f_local_config.json` (primary place to set query/pages/filter/timeouts)
- Search-term key in config: `search_term` (preferred, default `บริษัท`; `query` retained as backward-compatible alias)
- Run with default local config:
  - `python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py`
- Run with explicit config path:
  - `python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.json`

## Current Outputs
- `README.md` (process-level documentation: architecture, config, filter contract, anti-bot behavior, outputs)
- `f_search_result.json`
- `result_packed.csv` (clean packed export)
- `dumps/f_api_hits.json`
- `dumps/f_infos_contract.json`
- `dumps/f_infos_replay_result.json`
- `dumps/f_filter_options_labels.json` (single-pass harvested combobox labels)
- `dumps/f_page_unavailable.html` (saved when search box is unavailable, often anti-bot/challenge state)
- `storage_state.json` (session state, optional)
- `f_local_config_option.md` (config usage + filter option reference)

## Current Approach
1. Open `https://datawarehouse.dbd.go.th/`
2. Fill main search box with query term and submit
3. If submit path is flaky, fallback to direct result URL `/juristic/searchInfo?keyword=...`
4. Wait for search results using multiple readiness signals (table rows, filter button visibility, or total-count text)
5. Collect page-1 companies from visible table/DOM
6. Capture `/api/v1/company-profiles/infos` request contract
7. Replay infos API for `currentPage=2..N` with decrypt + retry/backoff
8. In fetch-all mode (`--pages -1`), keep replaying until a page returns fewer than 10 rows
9. Deduplicate companies by juristic ID and export JSON/CSV

## Anti-Bot / Reliability Notes
- Reuse same policy as process `b`:
  - Headless for quick extractability checks
  - Non-headless fallback when blocked/partial
- Persist `storage_state.json` after good sessions

Current observed behavior:
- Headless smoke test can hit `Cannot find DBD search input`.
- Script now returns structured output with `status=blocked_or_unavailable` instead of crashing.
- Next practical step is non-headless run to warm session and verify selectors in real page state.

## Open Discovery Questions
- What exact endpoint powers the paginated company search list?
- Which query/filter params map to UI filters?
- Can pagination be driven directly via API params once endpoint is confirmed?
- Is there rate-limiting or anti-bot behavior specific to list search flow?

## Latest Discovery (2026-04-02)
- Successful first-page extraction achieved (10 companies) from the visible search table.
- Observed list endpoint call: `/api/v1/company-profiles/infos`.
- Result output file confirmed: `f_search_result.json` with `status="ok"`.
- Current extractor strategy uses table-cell parsing as primary source and API payload parsing as secondary.
- Captured full request contract (method/headers/body) to `dumps/f_infos_contract.json`.
- Implemented in-page replay of infos endpoint and dumped to `dumps/f_infos_replay_result.json`.
- Replay response is encrypted; now decrypted automatically using JWT `encKey` (HKDF/AES-GCM), producing decrypted payload with `contents` rows.
- Added full-column extraction for table schema and mapped to stable English keys:
  - `juristic_id`, `company_name`, `juristic_type`, `status`,
  - `business_type_code`, `business_type_name`, `province`,
  - `registered_capital_baht`, `total_revenue_baht`, `net_profit_baht`, `total_assets_baht`, `shareholders_equity_baht`,
  - `profile_url`.
- Added packed CSV export (`result_packed.csv`) using fixed column order and UTF-8 BOM for Excel compatibility.
- Added hybrid pagination mode: page 1 from UI + pages 2..N from API replay (`currentPage`) to reduce repeated UI clicks.
- Added API replay retry/backoff and page-level replay stats (`debug.api_replay_page_stats`).
- Latest validation run with `--pages 5` produced 50 unique companies (10/page across pages 1..5) without blocked-like responses.
- Added `--pages -1` sentinel to mean fetch all pages until the endpoint naturally ends.
- Fetch-all stop condition is currently `rows < 10` on a replayed page, matching the observed DBD page size.
- Fetch-all mode was only statically validated and wired into the flow; no full end-to-end run was executed because the result set is extremely large.
- Traversed the advanced filter UI after list load and confirmed the panel toggle selector is `.btn-filter-advanced.toggle-filter-advanced`.
- Confirmed filter payload keys via live UI apply on `/api/v1/company-profiles/infos`:
  - `pvCodeList`, `jpStatusList`, `jpTypeList`, `businessSizeList`
  - `capAmtMin/Max`, `totalIncomeMin/Max`, `netProfitMin/Max`, `totalAssetMin/Max`
- Confirmed one live filter example:
  - กรุงเทพมหานคร -> `pvCodeList: ["10"]`
  - ยังดำเนินกิจการอยู่ + ฟื้นฟู + คืนสู่ทะเบียน -> `jpStatusList: ["1", "A", "B"]`
  - บริษัทจำกัด -> `jpTypeList: ["5"]`
  - ธุรกิจขนาดใหญ่ (L) -> `businessSizeList: ["L"]`
  - money mins at 10,000,000 produced 5,393 matching rows in live UI test.
- Added initial CLI filter support in `f_main.py` for province/status/juristic-type/business-size plus min/max money fields, using the replayed infos API body.
- Added slower-load tolerance: result readiness now accepts filter-button visibility and total-count text, not only populated table rows.
- Added `--results-timeout-seconds` (default 90) because DBD can take a long time to render the result list before the filter panel toggle appears.
- Moved runtime options from many CLI args to local JSON config (`f_local_config.json`), with `--config` as optional override path.
- Harvested filter combobox labels in one pass (no per-option re-query) and exported full lists:
  - provinces: 77
  - statuses: 11
  - juristic types: 8
  - business sizes: 3
- Added `f_local_config_option.md` documenting config schema, run usage, reverse-engineered filter payload keys, and all harvested combobox options.
- Validated user-requested filter set for 10 pages (2026-04-02):
  - status: ยังดำเนินกิจการอยู่
  - juristic types: บริษัทมหาชนจำกัด + บริษัทจำกัด
  - capital: 5,000,000 ถึง 100,000,000
  - revenue min: 100,000,000
  - net profit min: 10,000,000
  - province/business-size/asset range left empty
  - result: `status=ok`, `companies=100`, `pages_requested=10`, replay pages 2..10 all `200` with 10 rows each.
- Added explicit local-config search term support (`search_term`) with default `บริษัท` and fallback compatibility with old `query` key.
- Added suggested search terms in options guide: `บริษัท`, `ห้างหุ้นส่วน`.
- Added folder-level `README.md` describing full process flow, reverse-engineered filter API contract, config-driven run model, and operational troubleshooting.

## Next Iteration Plan
1. Expand code mappings for more provinces/statuses/juristic types discovered from the UI
2. Add resume/checkpoint support for very large `--pages -1` runs
3. Scale filtered runs from 1-5 pages to larger batches with pacing controls
4. Add optional CSV/JSON export split by filter set and run timestamp
5. Add validation checks between UI-filtered rows and replay-decrypted API rows

## Maintenance Notes
- Keep this file updated each time endpoint/filter understanding improves
- Record selector changes and endpoint contract changes with short dated notes
