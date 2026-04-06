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

## Latest Update (2026-04-06, Page Rollback Observation + Paused State)

### Observed Live Behavior
- During UI navigation tests, paginator briefly showed target page `3`, then reverted to page `2`.
- This matches a DBD UI rollback pattern where paginator input/active state can change optimistically before table data commit, then snap back when load stalls.
- Current site state again entered infinite loading (table `Loading...` persists, rows not materialized).

### Hardening Added
- `f_main.py` page detection now collects multi-source page signals (`rowInferredPage`, `activePage`, `inputPage`, `textPage`) and resolves with row-first priority.
- Added disagreement diagnostics logging when page sources conflict.
- Added rollback-aware handling in `wait_target_page_rows(...)`:
  - detect when target signal was seen then reverted,
  - attempt bounded recommit rescue,
  - abort delayed-wait loop after repeated rollback cycles instead of hanging silently.

### Probe Utility Update
- `f_ui_probe_page5_test.py` now supports `--target-page` for focused verification (ex: page `3` mismatch checks).

### Operational State
- No active `f_main.py`/`f_ui_probe_page5_test.py` process is running.
- Per user request, testing is paused and will resume only after user signal.

## Latest Update (2026-04-06, Resume From Config Page + Progress Checkpoint)

### Feature Added
- Added config-driven resume control so the run can do normal init flow (open URL, apply filters/sort, capture contract) and then continue replay from a configured page.

### New Config Keys
- `resume_from_page` (int, default `1`):
  - `1` = normal flow from page 1 behavior.
  - `>=2` = skip multi-page UI crawl and start replay from that page.
- `track_progress_in_config` (bool, default `true`): persist progress checkpoints during run.
- `runtime_progress.last_page_extracted` + `runtime_progress.updated_at`:
  - updated while pages are extracted.
  - mirrored to top-level `last_page_extracted` for quick manual read.

### Runtime Behavior
- Progress is now checkpointed into the same config file each time a higher page is extracted.
- On next run, user can set `resume_from_page` to desired continuation page number.
- This is intended to reduce repeated work when long runs are interrupted by unstable DBD loading states.

## Latest Update (2026-04-06, Hold + Config Schema Sync + Cleanup)

### Hold State
- Live UI tests are paused due to recurring infinite-loading behavior.
- No new test execution was started after hold instruction.

### Config Schema Sync Completed
- Synced resume/progress keys across all active process-`f` configs:
  - `f_local_config.json`
  - `f_local_config.temp_prod.json`
  - `f_local_config.ui_probe_test.json`
  - `f_local_config.ui_probe_nofilter_test.json`
- Added/kept keys:
  - `resume_from_page`
  - `track_progress_in_config`
  - `runtime_progress.last_page_extracted`
  - `runtime_progress.updated_at`

### Cleanup Completed
- Removed unused/temporary process-`f` files:
  - `_probe_sort_options.py`
  - `f_search_result_crash.json`
  - `tmp_ui_probe_page3_test.log`
  - `last_page_in.png`

### Documentation Sync
- Updated process docs to reflect:
  - rollback-aware page navigation handling,
  - config-driven replay resume/checkpoint keys,
  - temp-prod runbook steps for restart-from-checkpoint workflow.

## Latest Update (2026-04-06, UI-Probe Wait Tuning + Cleanup)

### Runtime Tuning Applied
- Increased retry wait interval in no-filter proof script:
  - `f_ui_probe_page5_test.py`: page-1 loaded-row retry wait changed from `700ms` to `1500ms`.
- Mirrored the same slower retry cadence in main runtime path:
  - `f_main.py` (`wait_target_page_rows`): retry waits changed from `700ms` to `1500ms`.

### Validation Outcome
- A clean no-filter proof run succeeded after wait tuning:
  - page-1 loaded rows confirmed (`10` rows), then UI jumped to page `5`, page-5 rows extracted (`10`).
  - Result file showed `status=ok` with `page1_rows=10`, `page5_rows=10`.
- Subsequent verification run encountered DBD infinite-loading behavior again (table readiness signals but no extractable loaded rows for extended period).
- Long-running verification process was intentionally stopped to avoid unnecessary waiting.

### Cleanup Completed
- Removed generated test/debug artifacts from the latest proof cycles:
  - `last_page_in.png`
  - `last_page_on.png`
  - `last_run.log`
  - `tmp_ui_probe_page5_result.json`
  - `tmp_ui_probe_page5_test.log`
- Workspace is now clean of temporary proof artifacts; only source/doc files remain modified.

### Current State
- No active `f_ui_probe_page5_test.py` or `f_main.py` Python run remains.
- Code is ready for re-run once DBD site exits infinite-loading state.
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

## Latest Update (2026-04-06, Proof Run + Context Refresh)

### User Request Covered
- User asked to prove whether the new UI delayed-load/navigation hardening is fixed, and update this local context file with current state.

### Proof Runs Executed Today
1. Forced UI test with filters
  - Config: `f_local_config.ui_probe_test.json`
  - Run ID: `101500-pid9144`
  - Outcome: run progressed to filter-toggle wait and became unreliable in this session; not a clean end-to-end proof run.

2. Forced UI test without filters (isolation run for pagination behavior)
  - Config: `f_local_config.ui_probe_nofilter_test.json` (new)
  - Run ID: `101601-pid20684`
  - Confirmed evidence from `last_run.log`:
    - page 1 loaded and captured rows (`UI page 1 captured: rows=10`)
    - UI probe moved to target page 2 (`navigate current_page=1 -> target_page=2`)
    - delayed-load logic detected loading-only table state on page 2 (`rowCount=1, loadingRows=1, dataRows=0`)
    - rescue recommit logic executed (`rescue recommit target page 2 attempt=1/3 success=True`)
    - still no rows within delayed-load wait (`page 2 reached but rows did not load within 25000 ms`)

### Current Conclusion (evidence-based)
- UI fallback reliability is improved in code and diagnostics (recommit + delayed-load checks are running as designed), but the issue is **not yet proven fixed** for stable UI-only page extraction beyond page 1 in live runs.
- In the latest proof run, page 2 remained in loading-row state despite rescue attempts.

### Artifacts / Config Added Today
- New test config: `f_local_config.ui_probe_nofilter_test.json`
- Updated runtime evidence: `last_run.log`, `last_page_in.png`, `last_page_on.png`

### Recommended Next Hardening Step
1. Add a deterministic row-refresh escape path when table state is `loadingRows>0 && dataRows=0` for repeated polls on a confirmed target page:
  - trigger controlled local context rebuild (small reload + paginator reacquire) and re-enter target page once,
  - then hard-fail page with explicit reason if still loading-only.

## Latest Update (2026-04-06, Temp Handoff for Manual CI/CD)

### What Was Added For Proof Control
- Added dedicated proof runner: `f_ui_probe_page5_test.py`
- Added strict pre-navigation gate:
  - page-5 jump is blocked until page-1 has real extracted data rows
  - if page-1 rows never load within timeout, run aborts with explicit blocked reason (`page1_not_loaded`)

### Current Live-Site Constraint
- DBD web session was unstable during the latest runs.
- Logs repeatedly showed loading-only table states while waiting for page-1 rows.
- Because of site instability, a full end-to-end live proof (page-1 loaded -> jump page-5 -> page-5 rows extracted) is still pending.

### What Is Already Proven In Code/Logs
- Guard logic is active and prevents premature navigation.
- While page-1 rows are unavailable, script remains in page-1 wait loop and does not jump to page 5.

### Re-Proof Checklist (when site is stable)
1. Run:
  - `python f_DBD_Company_List_Scraper_WIth_Filter/f_ui_probe_page5_test.py --config f_local_config.ui_probe_nofilter_test.json`
2. Confirm in log:
  - page-1 loaded rows detected (`loaded_rows > 0`)
  - navigation attempt to page 5 starts only after that point
  - page-5 rows extracted successfully
3. Save proof artifact:
  - `tmp_ui_probe_page5_result.json` with non-zero `target_page_rows`

### Temp Deployment Note
- Keep this branch focused on runtime guard behavior and reproducible proof flow.
- Treat transient loading-only failures as environment instability unless guard sequencing regresses.

## Latest Update (2026-04-06, Web Down Pause + Resume Marker)

### Current Status
- Testing paused by user request while DBD site behavior is unstable/down.
- No-filter proof flow was re-attempted to isolate pagination only:
  - page-1 loaded-row gate remained active,
  - repeated `Table data ready` events did not guarantee real row availability,
  - page transitions still intermittently stalled in loading-only states.

### Important Clarification Captured
- `Table data ready` currently means table/readiness checks passed, not guaranteed `dataRows > 0` on target page.
- Navigation validation now depends on page-consistency checks (active page + row-index inference), not input value only.

### Last Reliable Evidence Before Pause
- Filtered forced-UI run captured contract and entered UI probe fallback.
- UI probe attempted target-page movement and recommit, but target page remained loading-only (`loadingRows=1`, `dataRows=0`) through timeout windows.
- No stable end-to-end proof yet of: page-1 loaded -> jump page-5 -> page-5 rows extracted.

### Resume Checklist (on user signal)
1. Use no-filter dedicated probe first:
  - `python f_DBD_Company_List_Scraper_WIth_Filter/f_ui_probe_page5_test.py --config f_local_config.ui_probe_nofilter_test.json`
2. Confirm sequence strictly in log:
  - page-1 `loaded rows confirmed`
  - navigation attempt to page 5
  - target-page rows extracted (`page5_rows > 0`)
3. Save/result proof artifact:
  - `tmp_ui_probe_page5_result.json`
4. If still loading-only, keep run as environment-failure evidence and wait for next stable window.

## Latest Update (2026-04-06, Page-3 Rollback Fix Verified + Cleanup)

### User Observation Addressed
- Reported behavior: navigation briefly shows page `3` then returns to page `2`.
- Probable cause: once both pager arrows are present (`previous` + `next`), heuristic arrow clicks can select the wrong control.

### Code Fix Applied
- Updated `f_main.py` UI probe/recommit logic to avoid heuristic arrow clicking after paginator input submit.
- Input path now relies on:
  - set target page in paginator input,
  - send Enter,
  - verify via multi-signal page detection + row-confirmation wait.

### Focused Validation Run (Completed)
- Command intent: no-filter probe, `--target-page 3`.
- Result artifacts:
  - `tmp_ui_probe_page3_result.json`
  - `tmp_ui_probe_page3_test.log`
- Verified outcome:
  - `status=ok`
  - `page1_rows=10`
  - `target_rows=10`
  - `target_success=true`
- Logs show delayed-loading on target page was recovered through bounded recommit attempts, then rows materialized on page 3.

### Cleanup State
- Temporary page-3 proof artifacts are disposable and were cleaned after documentation sync.
- Process remains idle and ready for next validation window.

## Latest Update (2026-04-06, data_from_page Lineage Field)

### Feature Added
- Added new result column: `data_from_page`.
- Goal: preserve page-of-origin lineage for every exported row.

### Mapping Rules Implemented
- UI extracted rows: `data_from_page = current UI page`.
- API replay rows: `data_from_page = replay currentPage`.
- Replay probe rows: `data_from_page = probe page` (typically page 1).

### Output Impact
- `result_packed.csv` includes `data_from_page` in packed column schema.
- JSON row objects now carry the same page lineage key.

### Validation Status
- Code-path logic is implemented and consistent across UI/API/probe paths.
- Live validation remains partially constrained by intermittent target-site instability (interrupted long Playwright runs).
- Current state to carry forward:
  - schema wiring confirmed,
  - full uninterrupted 3-page proof artifact still pending stable run window.
