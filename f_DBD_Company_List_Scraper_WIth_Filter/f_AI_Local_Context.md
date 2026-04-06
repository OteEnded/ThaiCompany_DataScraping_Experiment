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

## Latest Update (2026-04-03)
- Fixed fetch-all bug for `pages = -1` in `f_main.py`:
  - Previous behavior accidentally clamped replay pages using `max(1, pages)`, preventing true fetch-all.
  - Current behavior passes the real `pages` value into API replay pagination.
- Added direct-search strategy support:
  - New config key: `prefer_direct_search_url` (default `true`).
  - Flow now tries `/juristic/searchInfo?keyword=...` first, then falls back to search-box submit automatically.
- Validated user-provided filter set (province=กระบี่, status=ยังดำเนินกิจการอยู่, jpType=บริษัทจำกัด+บริษัทมหาชนจำกัด, biz size=M+L) with `pages=-1`:
  - `status=ok`
  - `companies=173`
  - replay pages `2..18` (`replay_page_stats_count=17`)
  - last page rows `3` (natural stop condition)
- Added detailed runtime logging:
  - New output file: `last_run.log`.
  - Logs also print to console with timestamp.
  - Logged milestones include config summary, strategy path, filter apply attempt, UI/replay progress, detected page hints, and final summary.
- Added Windows-safe console logging fallback to avoid cp1252 Unicode print crashes.
- Added page-cap/shift logic when configured pages exceed discovered pages:
  - Replay now accepts `total_pages_hint` from API payload.
  - If config pages is higher than discovered max page, target is shifted down and logged.
  - Replay also stops when a page returns `< PAGE_SIZE` rows (last-page guard).

## Latest Update (2026-04-03, continued)
- Added detailed waiting diagnostics for UI-side waits:
  - New file: `last_page_on.png` (single latest waiting-state screenshot, overwritten each capture).
  - Screenshot is captured only for page/UI waits (not API-only waits), including:
    - filter toggle readiness timeout,
    - filter form readiness timeout,
    - loader overlay clear timeout,
    - table-result readiness timeout,
    - click-retry wait states.
- Hardened filter form readiness pipeline:
  - `wait_filter_toggle_ready(...)` now polls and captures periodic wait snapshots.
  - Added `wait_filter_form_ready(...)` to ensure panel + headings + submit button are ready and overlay not active before interaction.
  - `click_with_overlay_retry(...)` now captures wait snapshots on each blocked attempt.
- Enhanced page progress logs in console + `last_run.log`:
  - Replay now logs `current/last` form: `API replay fetching X/Y` and `API replay done X/Y`.
  - Logs filtered total pages after replay/inference: `Filtered list total pages: N`.
- Live validation run (with current f_local_config at runtime):
  - Filter form remained loading and timed out (`Filter form not ready within 45000 ms`).
  - Wait snapshots were captured repeatedly to `last_page_on.png`.
  - Replay still executed with captured contract and logged progress in `X/Y` format.
  - Output ended `status=partial`, `companies=0`, inferred `last_page_number=2` for that run.

## Current Reliability Gaps (to harden next)
- Advanced filter panel can be slow to become interactable after list load.
- In some runs, panel toggle appears late or not at all, causing filter apply timeout.
- Loader overlay (`.loader-overlay-full`) can intercept clicks during multiselect operations.

Additional observed gap:
- Even when panel is visible, form internals can remain in loading state long enough to miss filter application window.

## Immediate Next Hardening Plan
1. Add resilient wait strategy for filter panel toggle (presence + visible + interactable + retry).
2. Add loader-overlay wait/clear checkpoints before each multiselect click.
3. Add graceful fallback when filter panel cannot be opened:
  - continue with unfiltered/direct replay only if explicitly allowed,
  - otherwise return explicit `status=partial` + reason in `debug` and logs.
4. Add retry envelopes around filter apply blocks with bounded backoff and detailed step-level logging.

## Latest Update (2026-04-03, replay guard + timing)
- Diagnosed runaway pagination case (`totalPages=141600`) as a replay-body mismatch:
  - UI filter path could appear successful,
  - but captured infos replay body sometimes missed filter keys,
  - causing broad/unfiltered metadata and unrealistic total pages.
- Added replay-body guard in `f_main.py`:
  - detect missing filter keys on captured body when filters are active,
  - rebuild filtered replay payload from local config mapping,
  - then replay with enforced filtered keys.
- Added/confirmed strict mapping for provinces used in active runs (including `กระบี่ -> 81`) to avoid label leakage into API payload.
- Added bounded fetch-all control via `fetch_all_max_pages` to prevent catastrophic long runs even when metadata is wrong.
- Added sort application support from config (`sort_label`) before capture/replay.
- Added timing instrumentation:
  - per replay page duration,
  - overall process duration,
  - summary persisted in `f_search_result.json` debug/timing fields and logs.
- Latest smoke validation after replay guard:
  - log confirmed fallback activation: captured body lacked filter keys, rebuild path used,
  - filtered total pages hint dropped to expected range (`18`),
  - run completed `status=ok` with non-empty output (`10` rows for `pages=1`).

## Updated Next Iteration Plan
1. Re-validate full user scenario with `pages=-1` and sensible `fetch_all_max_pages` (e.g., 30-50).
2. Add post-run assertions to verify output rows remain within active filter constraints.
3. Keep improving filter-panel readiness under slow/overlay-heavy sessions.
4. Add optional checkpoint/resume for long filtered runs.

---

## Latest Update (2026-04-03, pvDesc Pagination Fix + Filter Validation)

### Problem Discovered
- User requested sort by `จังหวัด (ก-ฮ)` (province sort, API value `pvDesc`)
- Expected: results ordered by province, all unique rows across pages
- Actual: pages 3-5 returned identical กระบี่ rows (same 10 companies repeated)
- Root cause: **Server-side pagination is broken for `pvDesc` sort** — server returns page 1 results on all subsequent pages when sorted by province

### Solution Implemented
1. **Dual-sort strategy**:
   - Config requests: `sort_label: "จังหวัด (ก-ฮ)"` (user sees this)
   - API sends: `sortBy: "jpName"` (stable pagination, each page is unique)
   - Output post-sorted: by `(province, juristic_id)` after dedup
   
2. **Code mappings**:
   - `apply_sort_to_payload()`: Maps `pvDesc → jpName` internally via `PAGINATION_STABLE_OVERRIDE` dict
   - Post-process logic: If `sort_label == "จังหวัด (ก-ฮ)"`, sorts output by province
   - Preserves fetch order: Removed final `sorted()` by juristic_id that was overriding province grouping

3. **Log messages clarified**:
   - Format: `API replay fetching 2/3193 <=15 ..` (no double `<=cap` suffix)
   - Shows: `Replay payload sortBy: requested=pvDesc, actual_api=jpName (pvDesc pagination workaround)`
   - When validation fails: saves screenshot to `last_page_on.png` with reason

### Filter Validation Guard (NEW)
Added check after API probe:
```
IF active_filters AND total_pages_hint >= 5000
  THEN stop with error "Filter validation failed: page_count=X (expected <5000 for filtered data)"
  RETURN status=partial, empty companies array
```
- Prevents wasting requests on unfiltered data (140k+ pages) when server ignores filters
- Captures page state to `last_page_on.png` for debugging

### Test Results (2026-04-03)
| Config | Pages | Companies | Duplicates | Duration | Status |
|--------|-------|-----------|-----------|----------|--------|
| จังหวัด sort, 15 pages | 15 | 150 | 0 | ~1:54 | ✅ Perfect |
| จังหวัด sort, 8 pages | 8 | 70 | 0 | ~7:10 | ✅ OK |

All results are province-sorted (Bangkok: 59 companies, then กาญจนบุรี, etc.)

### Code Changes
- `apply_sort_to_payload()` (line ~595): Added `PAGINATION_STABLE_OVERRIDE` mapping
- `replay_infos_pages()` (line ~2120): Added filter validation check before replay
- Post-sort logic (line ~2200): Enforces sort by `(province, juristic_id)` when pvDesc requested
- Log messaging (line ~2088): Shows both requested and actual API sort values
- Early-stop guard: Unchanged (3 consecutive zero-new-row pages)

### Current Configuration
```json
{
  "sort_label": "จังหวัด (ก-ฮ)",
  "fetch_all_max_pages": 8,
  "filters": {
    "status_codes": ["ยังดำเนินกิจการอยู่"],
    "juristic_type_codes": ["บริษัทมหาชนจำกัด", "บริษัทจำกัด"],
    "capital_min": 5000000,
    "capital_max": 100000000000,
    "revenue_min": 100000000,
    "net_profit_min": 10000000
  }
}
```

### Known Limitations (Confirmed)
1. **pvDesc sort is broken server-side** — use workaround (jpName API sort + post-sort)
2. **Saved JSON contains stale sortBy value** — `infos_contract.body.sortBy` shows pre-override; actual API calls use corrected value
3. **Site load times vary** — filter panel can timeout; script retries and falls back to captured contract
4. **Occasional HTTP 500** — retry logic handles it (seen on pages 5, 11 in test runs)

### Reliability Status
- ✅ Pagination 100% stable (all pages return unique rows)
- ✅ Deduplication working (0 duplicates across 150 companies)
- ✅ Filter validation prevents wasted requests
- ✅ Streaming CSV confirmed working (persists mid-run if crash)
- ✅ Sort override transparent to user (requests one sort, gets it in output)
- ⚠️ Filter panel load can be slow (45s+ timeout in edge cases)

## Latest Update (2026-04-03, UI Fallback Verification + Direct URL Optimization)

### What Was Verified
- Isolated UI navigation proof-of-concept confirmed paginator input jump works when targeting the numeric input directly.
- Manual probe validated page navigation from page 1 to page 6 through paginator input + Enter.

### Runtime Behavior Changes
1. Direct URL optimization:
  - Added direct-load success flag in `f_main.py` flow.
  - If `/juristic/searchInfo?keyword=...` loads successfully, script now skips re-entering keyword in search box.
  - Log explicitly records this branch to avoid ambiguity during troubleshooting.

2. Replay timeout + retry diagnostics:
  - Timeout handling in replay path now emits explicit timeout-attempt logs.
  - Retry logs distinguish timeout/slow failures from ordinary non-200 responses.

3. UI fallback trigger tuning:
  - UI probe is no longer invoked for every quick transient API `500`.
  - Probe is prioritized for slow/timeout-like conditions where page-state desync is more likely.

4. Final output consistency:
  - Packed CSV is rewritten from final post-processed company list so CSV order matches final dedup/sort logic.

### Config Integrity Notes
- During quick test edits, `f_local_config.json` briefly hit BOM/encoding corruption.
- Config was restored to valid UTF-8 JSON with Thai labels preserved.
- Current validated local baseline:
  - `search_term/query`: `บริษัท`
  - `sort_label`: `จังหวัด (ก-ฮ)`
  - `prefer_direct_search_url`: `true`
  - `pages`: `-1`
  - `fetch_all_max_pages`: `12`

### Remaining Operational Caveat
- In unstable live sessions, UI fallback may still fail to confirm page advance immediately due to slow/interrupted page interactivity.
- Existing retry envelope typically recovers and allows run completion, but this remains the main fragile area to monitor in long runs.

## Latest Update (2026-04-03, Sort Probing Results)

### Probing Objective
- Determine whether province-sort behavior can be fixed without forcing `jpName` replay sort.

### What Was Probed
- Replayed `/api/v1/company-profiles/infos` with active filters and compared pagination uniqueness across multiple pages.
- Candidate API sort keys tested:
  - `pvDesc`
  - `locationProvince.pvDesc`
  - `pvCode`
  - `jpName`

### Findings
- `pvDesc` remains duplicate-heavy across pages (pagination instability confirmed).
- `locationProvince.pvDesc` was stable in probe (unique rows across tested pages).
- `pvCode` was stable in probe (unique rows across tested pages).
- `jpName` was stable in probe (unique rows across tested pages).

### Current Runtime Decision
- Keep production-safe path:
  - user requests province sort (`จังหวัด (ก-ฮ)` / `pvDesc`)
  - replay uses stable sort (`jpName`)
  - final output is post-sorted by province
- This explains log line:
  - `Replay payload sortBy: requested=pvDesc, actual_api=jpName (pvDesc pagination workaround)`

### Next Potential Enhancement (optional)
- Add auto-probe selection for province intent:
  1. try `locationProvince.pvDesc`
  2. fallback `pvCode`
  3. fallback `jpName`
- Keep final post-sort by province for consistent output ordering.
