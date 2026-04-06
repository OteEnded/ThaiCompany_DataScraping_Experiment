# Process F Progress Report

Report date: 2026-04-03  
Project: ThaiCompany_DataScraping_Experiment  
Scope: Process F (DBD Company List Scraper With Filter)

## 1. Executive Summary
Process F has progressed from early UI-only scraping into a stable hybrid data pipeline that combines UI interaction and API replay. The current implementation successfully handles filtered multi-page extraction, encrypted response handling, and transient backend instability (HTTP 500/502/timeouts) with retry and fallback logic.

Most important outcome:
- We completed validated filtered runs with clean output generation and duplicate control.
- Latest validated 18-page run produced 180 unique companies with status ok.

Current maturity:
- Strong for research and controlled operational runs.
- Remaining fragility is concentrated in filter-panel UI readiness under slow page states.

## 2. Objectives and Business Value
Primary objective:
- Extract large, filterable company lists from DBD DataWarehouse with high reliability and structured export.

Business value delivered:
- Faster and more repeatable company list collection.
- Reusable extraction flow for filtered cohorts.
- Improved auditability through runtime logs and debug artifacts.
- Better confidence in data quality through deduplication and validation guards.

## 3. What Has Been Done (Completed Work)
### 3.1 Core architecture completed
- Implemented hybrid strategy:
  - UI path for search and advanced filter application.
  - API replay path for efficient pagination at scale.
- Added encrypted payload decryption flow (HKDF/AES-GCM path in runtime).

### 3.2 Reliability hardening completed
- Added direct URL-first search path with fallback to search box.
- Added advanced filter apply retry with refresh recovery loop.
- Added overlay-aware click/retry handling and readiness waits.
- Added timeout-safe API replay retry/backoff.
- Added UI probe fallback for slow/failed API attempts.

### 3.3 Data integrity controls completed
- Added replay-body filter guard:
  - If captured replay body lacks filter keys while filters are active, payload is rebuilt from config mapping.
- Added suspicious-page-count filter validation stop:
  - If filtered run reports unrealistic high page count, run stops as partial to avoid bad export.
- Added deduplication by juristic id/profile fallback.

### 3.4 Pagination and sort stability fixes completed
- Fixed fetch-all behavior for pages = -1.
- Added fetch-all safety cap via fetch_all_max_pages.
- Added total pages hint handling and last-page guard.
- Implemented province sort stability workaround:
  - Requested province sort (pvDesc intent) uses stable replay sort for pagination.
  - Final output is post-sorted by province to preserve user-facing expectation.

### 3.5 Observability and output improvements completed
- Added timestamped runtime logging to last_run.log.
- Added waiting-state screenshot capture to last_page_on.png.
- Added replay progress logs and timing summary fields.
- Added packed CSV streaming during run and final sync with processed output.

## 4. Process Flow (Current)
1. Open DBD landing page.
2. Try direct search URL first for keyword-based result page.
3. Apply advanced filters in UI (with readiness/recovery handling).
4. Capture latest infos API request contract.
5. Validate/rebuild replay payload when needed.
6. Replay API pages (page 2..N) with retries and pacing.
7. Handle slow/failure cases with optional UI probe fallback.
8. Deduplicate and post-process final list.
9. Export outputs:
  - f_search_result.json
  - result_packed.csv
  - diagnostics and logs

## 5. Validation and Results
### 5.1 Key validated runs
- 10-page filtered validation completed successfully (100 rows).
- 18-page validation completed successfully:
  - status: ok
  - companies: 180
  - duplicate-free final output
  - transient failures recovered during replay

### 5.2 Runtime behavior observed in latest validation
- Filter panel required refresh-retry cycles before becoming usable.
- API replay encountered occasional 500/502/timeouts.
- Retries and fallback logic recovered the run without final data loss.

## 6. Deliverables Produced
Operational artifacts:
- f_main.py (hardened runtime logic)
- f_local_config.json (current validated config baseline)
- README.md (process documentation)
- f_AI_Local_Context.md (detailed historical context)
- f_local_config_option.md (config schema and option references)

Run outputs:
- f_search_result.json
- result_packed.csv
- last_run.log
- last_page_on.png
- dumps/* debug artifacts

## 7. Risks and Current Gaps
High priority risk:
- Advanced filter panel UI can remain non-interactable in some slow sessions.

Medium priority risks:
- Backend replay endpoint intermittently returns 500/502 or timeout.
- Province native API sort key remains pagination-unstable; workaround is required.

Operational impact:
- Longer run times and occasional partial outcomes when UI readiness fails repeatedly.

## 8. Mitigations in Place
- Refresh-and-retry envelope for stuck filter UI.
- Overlay and readiness checks before interactions.
- API retry/backoff and timeout handling.
- Filter payload rebuild guard to enforce active filter intent.
- Early stop on suspicious page-count validation failure.
- Incremental CSV streaming to reduce risk of full-run data loss.

## 9. Recommended Next Steps
1. Add automatic stable-sort selector for province intent (probe-based candidate fallback).
2. Add post-run filter assertions against exported rows (status/type/province constraints).
3. Improve filter-panel robustness with stronger pre-open health checks.
4. Run bounded fetch-all validation with cap scenarios and compare quality/runtime.
5. Add checkpoint/resume for long runs to reduce restart cost after interruption.

## 10. Manager Status View
Overall status: On track with technical risk managed.

What is complete:
- Core hybrid scraper architecture.
- Reliability and replay hardening.
- Multi-page filtered extraction validated.
- Structured outputs and diagnostics integrated.

What remains:
- Final hardening around slow UI filter panel behavior.
- Additional quality assertions and long-run resilience upgrades.

Confidence level:
- High confidence for controlled filtered runs.
- Moderate confidence for long-running sessions under unstable site conditions.

## 11. Suggested Reporting Cadence
Recommended update cadence to manager:
- Daily short update during hardening phase:
  - run success rate
  - median runtime
  - retry/fallback frequency
  - data quality check pass/fail
- Weekly milestone summary with risk trend and next sprint goals.

## 12. One-Line Summary for Management
Process F has moved from experimental scraping to a resilient hybrid pipeline with validated filtered multi-page output, and is now in final reliability hardening focused on unstable UI filter states.