# AI_CarryOn.md — Project Context Dump

> **Purpose:** Full context handoff for any AI agent continuing work on this repository.
> Last updated: 2026-09-17 (sets 1-3 COMPLETE and verified: 107,941 companies; server handoff prepared - see g_DBD_CRM_Pipeline/SERVER_HANDOFF.md). Previously 2026-09-16 (site revalidated after 5-month gap: Imperva stale-session block solved; DBD broad-query guard discovered — `บริษัท` seed is permanently blocked; ID-prefix sweep verified as replacement). Repository: `ThaiCompany_DataScraping_Experiment`

## How to Use This File

This file is a **living document**. It is the single source of truth for project state, progress, and plans.

**Rules for every AI agent working on this project:**
- **Read this file first** before doing any work, every session.
- For process-specific details, immediately read the corresponding `<<id>>_AI_Local_Context.md` in that process folder.
- **Update this file immediately** whenever:
  - A module or file is modified
  - A bug is fixed or a new issue is found
  - A plan or next step changes
  - A run is validated (update git state, example data, known issues as needed)
  - A new feature or module is added
- Keep the "Last updated" date in the header current.
- Keep an **Update Log** section at the end of this file and append a short entry for each meaningful change.
- Update section 9 (Git State) after every commit/push.
- Update section 10 (Suggested Next Steps) to reflect what was done and reprioritize what remains.
- Do NOT let this file go stale — an outdated `AI_CarryOn.md` is worse than none.

---

## Current Handoff Snapshot (2026-09-16)

### Repository state
- Workspace: `c:\Data\Repo\ThaiCompany_DataScraping_Experiment`
- Branch: `main`
- Remote: `https://github.com/OteEnded/ThaiCompany_DataScraping_Experiment.git`
- HEAD and `origin/main`: `5db80f3` — `OteEnded[feat]: add retrieve timestamp and source approach fields`
- The branch has no staged changes, but the worktree is not clean because process-f runtime output and one edited local config are present.

### Current local changes
- Modified: `f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.temp_prod.json`
- Untracked generated files: `f_search_result_crash.json`, `last_page_in.png`, `last_page_on.png`, and `last_run.log` under the process-f folder.
- Do not discard the temp-prod config before preserving its checkpoint values if the long run needs to continue.

### Process-f continuation state
- The temp-prod config currently has `pages=-1`, `fetch_all_max_pages=3300`, `resume_from_page=3060`, and `runtime_progress.last_page_extracted=3181`.
- The config also has a top-level `last_page_extracted=3181` and timestamp `2026-04-10T17:30:53`.
- Important config drift: two keys are misspelled locally as `usui_probe_rows_on_api_failure` and `forcee__ui_probe_rows_for_test`; the committed schema uses `use_ui_probe_rows_on_api_failure` and `force_ui_probe_rows_for_test`. Review/fix this before relying on those options.
- Active filters in the temp-prod config: status `ยังดำเนินกิจการอยู่`, juristic types `บริษัทมหาชนจำกัด` and `บริษัทจำกัด`, capital minimum `5,000,000`, revenue minimum `100,000,000`, net profit minimum `10,000,000`; no province or business-size filter.
- Run command from repository root:
  `python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_local_config.temp_prod.json`
- The config path is resolved relative to the script folder. Therefore, when running from the repository root, pass only `f_local_config.temp_prod.json`, not the folder-prefixed relative path.
- The site is intermittently unstable and can remain in infinite loading. Runtime outputs are disposable; `f_search_result.json` and `result_packed.csv` are the primary data outputs.

### What the latest code provides
- UI initialization plus encrypted DBD API replay with retry/backoff.
- Advanced filters, stable replay sorting workaround for province sort, bounded fetch-all, resume checkpoints, rollback-aware page confirmation, and runtime timing/progress logs.
- Per-row lineage/capture fields: `data_from_page`, `data_retreive_at`, and `data_retrieve_approch` (`api_replay` or `navigate_ui`). Preserve the existing spellings for compatibility unless intentionally migrating the schema.

### ⚠️ SUPERSEDED — the resume plan above no longer works (2026-09-16)
Do NOT simply rerun the temp-prod config. It will fail. Two blockers were found
and diagnosed when the site was revalidated after the 5-month gap:

1. **Imperva block (SOLVED, config only).** The April `storage_state.json` carried
   a persistent Imperva visitor ID (the identity that pulled ~32,000 records) plus
   session cookies dead for five months — a stronger bot signal than no cookies at
   all. Fixed by `use_storage_state:false` (stale file archived to
   `storage_state.stale_april.bak`), `prefer_direct_search_url:false`, and
   `channel:"chrome"`. No code change was required.

2. **Broad-query guard (DESIGN CHANGE REQUIRED).** DBD now rejects the seed keyword
   server-side with HTTP 400: `กรุณาระบุคำค้นหาให้เฉพาะเจาะจงมากขึ้น`. Both
   `บริษัท` and `จำกัด` are blocklisted; `ห้างหุ้นส่วน` and ordinary business words
   still pass, so this is a narrow blocklist, not a volume limit. Filters do not
   help — the guard runs before filtering. **`search_term: "บริษัท"` in every
   process-f config is permanently non-functional.**

**Verified replacement: juristic-ID prefix sweep.** Search matches registration
numbers as substrings, so prefix `P` returns a superset of companies whose ID
starts with `P`; filter locally with `startswith(P)` for a provably complete
bucket. 78 four-digit prefixes cover the registry; only `0105` (1,702 pages) needs
splitting; ~3,200 pages total — the same work as April, but in independently
resumable units. Full evidence tables in
`f_DBD_Company_List_Scraper_WIth_Filter/f_AI_Local_Context.md`.

### Recommended next action
1. Read the 2026-09-16 sections of `f_AI_Local_Context.md` before touching process f.
2. Implement the adaptive ID-prefix sweep as a new seed mode in `f_main.py`
   (keep the existing capture/decrypt/filter/pagination machinery — all of it was
   exercised and confirmed working during this session's probes).
3. Fix the output accumulation bug: `IncrementalCSVWriter` opens with mode `"w"`
   (f_main.py ~line 117), so every run truncates. The 31,725 archived records
   survive only because of manual copying to `Downloads/DBD Data/DBD Data Set 0/`.
   Prefer moving the system of record to a store keyed on `juristic_id`.
4. Reuse `is_blocked_text()` from process `b` inside `f` so Imperva pages fail fast
   instead of burning `results_timeout_seconds * stuck_refresh_retries` (~12 min).
5. Correct the misspelled temp-prod keys (`usui_probe_rows_on_api_failure`,
   `forcee__ui_probe_rows_for_test`) if those options are needed.
6. Do not commit credentials, storage state, screenshots, or runtime logs unless
   explicitly requested.

## 1. Project Purpose

Multi-source data collection and analysis playground for Thai company/market data. Combines:
- Thai company registry (DBD DataWarehouse) scraping + decryption
- Thai stock exchange (Settrade) market data
- Web search + LLM-powered query answering

No production deployment — this is a research/experimentation workspace.

---

## 2. Repository Layout

```
AI_Search/
  config.json              ← Local credentials (gitignored)
  config.example.json      ← Template for config.json
  README.md
  AI_CarryOn.md            ← This file
  .gitignore
  result_examples/         ← Committed reference outputs from each module
    a_AI_Search/
    b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/
    c_DBD_Company_AI_Summary/
    d_Settrade_SDK/
    e_Settrade_Scraper/
    f_DBD_Company_List_Scraper_WIth_Filter/
  a_AI_Search/             ← AI web search agent (Brave + SiliconFlow LLM)
    a_main.py
    dumps/
  b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/  ← DBD DataWarehouse scraper + HKDF/AES-GCM decryption
    b_main.py
    dbd_result.json          (last raw run output — not committed)
    dbd_result_decrypted.json (last decrypted run — not committed)
    storage_state.json       (Playwright session — gitignored)
    dumps/
  c_DBD_Company_AI_Summary/ ← AI-powered company + financial summary from b output
    c_main.py
    z_compact_data.json      (last compact output — not committed)
    z_summary.md             (last summary — not committed)
  d_Settrade_SDK/          ← Settrade official SDK wrapper
    d_main.py
    settrade_company_data.json
    settrade_company_data.md
  e_Settrade_Scraper/      ← Settrade web scraper (Playwright, no login)
    e_main.py
    probe*.py              (probe/experiment scripts, not for production)
    settrade_OSP.json
    settrade_OSP.md
  f_DBD_Company_List_Scraper_WIth_Filter/  ← DBD company list scraper from search + pagination + filters
    f_main.py
    f_search_result.json
    result_packed.csv
    storage_state.json
    dumps/
  g_DBD_CRM_Pipeline/      ← CRM pipeline: SQLite system of record + prefix sweep + exports
    g_main.py              (CLI: import-csv / stats / coverage / changes / export)
    g_store.py             (schema, normalization, upsert with change history)
    g_sweep.py             (Stage 1 adaptive juristic-ID prefix sweep)
    g_session.py           (browser session rotation + Imperva block detection)
    g_sets_config.json     (capital-band collection plan, sets 1-7)
    g_local_config.json    (78 seed prefixes + ad-hoc filters)
    dbd_companies.sqlite3  (the store - gitignored)
```

---

## 3. Config (`config.json`)

Copy `config.example.json` → `config.json` and fill real values. Structure:

```json
{
  "BRAVE_API_KEY": "...",
  "SILICONFLOW_API_KEY": "...",
  "SETTRADE": {
    "app_id": "...",
    "app_secret": "...",
    "broker_id": "...",
    "app_code": "...",
    "equity_account_no": "...",
    "derivatives_account_no": "...",
    "default_symbol": "AOT",
    "pin": "...",
    "is_auto_queue": false
  }
}
```

All modules load `config.json` from the workspace root via `Path(__file__).resolve().parent.parent / "config.json"`.

---

## 4. Dependencies

```powershell
pip install requests playwright cryptography settrade-v2
python -m playwright install chromium
```

Python 3.11.9 confirmed working (`C:/Users/OteServerI/AppData/Local/Programs/Python/Python311/python.exe`).

---

## 5. Module Details

High-level summary only. Detailed process documentation now lives inside each process folder.

### 5.1 a — AI Search
- Folder: `a_AI_Search/`
- Main script: `a_main.py`
- Purpose: LLM-driven web search orchestration (Brave + SiliconFlow)
- Local details: `a_AI_Search/a_AI_Local_Context.md`

### 5.2 b — DBD Datawarehouse Scraper (Single Company by ID)
- Folder: `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/`
- Main script: `b_main.py`
- Purpose: capture + decrypt DBD company data by juristic ID
- Local details: `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_AI_Local_Context.md`

### 5.3 c — DBD Company AI Summary
- Folder: `c_DBD_Company_AI_Summary/`
- Main script: `c_main.py`
- Purpose: summarize process `b` output into compact JSON + markdown analysis
- Local details: `c_DBD_Company_AI_Summary/c_AI_Local_Context.md`

### 5.4 d — Settrade SDK
- Folder: `d_Settrade_SDK/`
- Main script: `d_main.py`
- Purpose: pull market + account data via `settrade-v2`
- Local details: `d_Settrade_SDK/d_AI_Local_Context.md`

### 5.5 e — Settrade Scraper
- Folder: `e_Settrade_Scraper/`
- Main script: `e_main.py`
- Purpose: scrape public Settrade company snapshot endpoints via Playwright
- Local details: `e_Settrade_Scraper/e_AI_Local_Context.md`

### 5.6 f — DBD Company List Scraper With Filter
- Folder: `f_DBD_Company_List_Scraper_WIth_Filter/`
- Main script: `f_main.py`
- Purpose: scrape DBD company list search results (`บริษัท`) with pagination, then evolve to filter-based list extraction
- Local details: `f_DBD_Company_List_Scraper_WIth_Filter/f_AI_Local_Context.md`

### 5.7 g — DBD CRM Pipeline
- Folder: `g_DBD_CRM_Pipeline/`
- Main scripts: `g_main.py` (store CLI), `g_sweep.py` (Stage 1 discovery), `g_session.py` (Imperva safety), `g_store.py` (schema/upsert)
- Purpose: durable system of record for DBD company data + CRM-facing exports
- Created 2026-09-16 after DBD blocked process `f`'s broad-keyword seed
- Local details: `g_DBD_CRM_Pipeline/g_AI_Local_Context.md`

### Process-Detail Rule
For any process-specific debugging, implementation, endpoint contracts, schema notes, or operational caveats, read that process's `<<id>>_AI_Local_Context.md` first.

---

## 6. End-to-End Data Flow

```
a_AI_Search/a_main.py  →  Brave Search + LLM answer  →  a_AI_Search/dumps/final_result.txt

b_DBD_.../b_main.py  →  DBD scrape + decrypt  →  b_DBD_.../dbd_result_decrypted.json
    ↓
c_DBD_Company_AI_Summary/c_main.py  →  compact JSON + summary  →  c_DBD_Company_AI_Summary/z_compact_data.json, z_summary.md

d_Settrade_SDK/d_main.py  →  Settrade SDK  →  d_Settrade_SDK/settrade_company_data.json
e_Settrade_Scraper/e_main.py --symbol OSP  →  e_Settrade_Scraper/settrade_OSP.json
f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --query บริษัท  →  f_DBD_Company_List_Scraper_WIth_Filter/f_search_result.json
```

`b → c` is the main chained pipeline. All other modules are independent.

---

## 7. Validated Example Data

Test company used throughout development:

| Field | Value |
|---|---|
| Company (TH) | โอสถสภา จำกัด (มหาชน) |
| Company (EN) | OSOTSPA PUBLIC COMPANY LIMITED |
| Juristic ID | `0107561000081` |
| Stock Symbol | OSP |
| jpType | 7 (Public Company) |
| Status | ยังดำเนินกิจการอยู่ (Operating) |
| Fiscal Year | 2567 |
| Revenue (2567) | 19,820M THB |
| Net Profit (2567) | 1,822M THB (−27% YoY) |
| Total Assets | 25,154M THB |
| Equity | 16,137M THB |
| D/E | 0.56 |
| ROE | 11.14% |
| 5-year trend | 2563–2567 (ROE declining, D/E rising, current ratio falling) |
| Committees | 17 members |
| Mergers | Transformed from โอสถสภา จำกัด (`0105517010074`) on 2018-04-02 |

Run examples committed in `result_examples/`.

---

## 8. Known Issues & Edge Cases

- Global caveat: process `b` anti-bot behavior (Incapsula) can affect `b -> c` chain quality.
- Global caveat: process `d` output depends on valid Settrade credentials and environment.
- Detailed issue lists are maintained in local context files:
  - `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_AI_Local_Context.md`
  - `c_DBD_Company_AI_Summary/c_AI_Local_Context.md`
  - `d_Settrade_SDK/d_AI_Local_Context.md`
  - `e_Settrade_Scraper/e_AI_Local_Context.md`
  - `f_DBD_Company_List_Scraper_WIth_Filter/f_AI_Local_Context.md`

---

## 9. Git State

- **Git:** Already initialized in the workspace root (`c:\data\AI_Search`)
- **Remote:** `https://github.com/OteEnded/ThaiCompany_DataScraping_Experiment.git`
- **Branch:** `main`
- **Last commit:** `5db80f3` — "OteEnded[feat]: add retrieve timestamp and source approach fields"
- **Commit message convention:** `OteEnded[type]: description` (e.g., `OteEnded[fix]:`, `OteEnded[feat]:`, `OteEnded[refactor]:`)

**Current pending local changes:**
- `f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.temp_prod.json` contains the active resume checkpoint and the misspelled local keys documented in the handoff snapshot above.
- Runtime artifacts are untracked: `f_search_result_crash.json`, `last_page_in.png`, `last_page_on.png`, and `last_run.log` under process `f`.
- The source/docs changes for process-f row lineage and capture metadata are already present in commit `5db80f3`.

Notes:
- Latest focused proof (`--target-page 3`) passed with `target_success=true` and `target_rows=10`.
- Row metadata features (`data_from_page`, `data_retreive_at`, `data_retrieve_approch`) are implemented and schema wiring is confirmed.
- Uninterrupted live 3-page proof remains pending stable run window/deploy feedback.
- Temporary proof artifacts are disposable and should be cleaned after each verification cycle.
- Process `f` is currently idle (no active test run) while DBD remains intermittently loading-only.

**Gitignored files (do NOT commit):**
- `config.json` (credentials)
- `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/storage_state.json` (Playwright session cookies)

**⚠️ Commit/push policy:**
- Do **NOT** commit or push automatically after every edit.
- Only commit and push when the user **explicitly asks** (e.g., "commit and push", "commit this").
- Until then, edits stay local. Update this file to track what is pending commit if needed.

---

## 10. Suggested Next Steps

Priority order based on current state:

1. **Re-run no-filter proof once DBD stabilizes**
  Use `f_ui_probe_page5_test.py --target-page 3` and confirm stability across repeated runs (not just single-run pass).

2. **Optional sort auto-selection enhancement in f**
  For province intent, auto-probe and choose stable API sort (`locationProvince.pvDesc` → `pvCode` → `jpName`) while preserving final province post-sort.

3. **Run bounded full validation in f (`pages=-1`)**
  Validate real filtered fetch-all behavior with `fetch_all_max_pages` cap and confirm output remains non-empty and constrained.

4. **Add post-run filter assertions in f**
  Validate exported rows against active filter constraints (e.g., province/status/type) and flag mismatch runs.

5. **Improve filter-panel stability in f**
  Continue hardening overlay-aware interactions and readiness checks for slow UI states (refresh-retry is now in place and validated).

6. **c guard for blocked b output**
  Add hard stop when `source_status != "ok"` before summary generation.

7. **Test b with different juristic IDs**
  Verify scraper generalization beyond OSOTSPA.

8. **Add `e` results to `result_examples/`**
  Refresh examples for additional symbols.

9. **Add `d` results to `result_examples/`**
  Refresh SDK examples (requires valid credentials).

10. **Connect a + b pipelines**
  Optional orchestration layer from search results to DBD scrape.

---

## 11. Quick Reference — Run Commands

```powershell
# Install (one-time)
pip install requests playwright cryptography settrade-v2
python -m playwright install chromium
Copy-Item config.example.json config.json   # then edit config.json

# a — web search agent
python a_AI_Search/a_main.py --query "your question here"

# b — DBD scraper (RECOMMENDED: non-headless, with storage state)
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081

# b — headless (only after storage_state.json exists from a prior non-headless run)
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --headless

# c — financial summary (run b first)
python c_DBD_Company_AI_Summary/c_main.py

# d — Settrade SDK (requires credentials in config.json)
python d_Settrade_SDK/d_main.py

# e — Settrade web scraper (no login required)
python e_Settrade_Scraper/e_main.py --symbol OSP --headless
python e_Settrade_Scraper/e_main.py --symbol AOT --headless

# f — DBD company list scraper with pagination/filter exploration
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.json
```

---

## 12. Update Log

- 2026-04-02: Added per-process local context files (`a` to `e`) and slimmed `AI_CarryOn.md` to high-level summary.
- 2026-04-02: Expanded process `b` local context with Playwright usage details and UI/API endpoint discovery iterations.
- 2026-04-02: Added process `b` anti-bot execution policy (headless quick-check, non-headless fallback standard).
- 2026-04-02: Added rule requiring ongoing Update Log entries for meaningful project changes.
- 2026-04-02: Added new process `f` scaffold for DBD company-list search/pagination and filter exploration.
- 2026-04-02: Hardened `f_main.py` to emit debug artifacts + structured status when DBD search input is unavailable (anti-bot/challenge state).
- 2026-04-02: Process `f` reached real DBD search table and successfully dumped first-page company list (10 rows) to `f_search_result.json`.
- 2026-04-02: Process `f` now captures `/api/v1/company-profiles/infos` request contract and replays/decrypts API response to extract company list payload.
- 2026-04-02: Process `f` now extracts full target column set and exports clean `result_packed.csv` from JSON mapping.
- 2026-04-02: Process `f` added hybrid pagination (UI page 1 + API replay pages 2..N with retry/backoff) and validated 5-page run with 50 unique companies.
- 2026-04-02: Process `f` migrated run options to `f_local_config.json`; `f_main.py` now uses `--config` as optional override.
- 2026-04-02: Added `f_local_config_option.md` with full harvested filter options and suggested search terms (`บริษัท`, `ห้างหุ้นส่วน`).
- 2026-04-02: Validated requested 10-page filtered run in process `f` with 100 rows and stable replay page stats.
- 2026-04-02: Added process-`f` `README.md` documenting architecture, run/config workflow, filter API contract, anti-bot strategy, and outputs.
- 2026-04-03: Process `f` fixed replay-body mismatch causing unfiltered `totalPages` spikes (e.g., 141600) by rebuilding filtered payload from config when captured body lacks filter keys.
- 2026-04-03: Process `f` added bounded fetch-all control (`fetch_all_max_pages`), config sort support (`sort_label`), and per-page/overall timing summaries.
- 2026-04-03: Synced process `f` docs (`README.md`, `f_local_config_option.md`, `f_AI_Local_Context.md`) and this carry-on file with latest behavior.
- 2026-04-03: Validated process `f` 18-page run end-to-end (`status=ok`, `companies=180`, duplicate-free final output) with retries on transient API 500/timeout.
- 2026-04-03: Added process `f` stuck-loading filter recovery (refresh + retry envelope with bounded retries and explicit exhaustion logging).
- 2026-04-03: Probed province-sort alternatives and confirmed `pvDesc` is duplicate-heavy; documented stable candidates (`locationProvince.pvDesc`, `pvCode`, `jpName`) and retained production-safe workaround.
- 2026-04-03: Updated `result_examples/f_DBD_Company_List_Scraper_WIth_Filter/` with latest validated run outputs (`f_search_result.json`, `result_packed.csv`).
- 2026-04-06: Process `f` increased UI loaded-row retry wait from `700ms` to `1500ms` in both main runtime and dedicated no-filter proof runner.
- 2026-04-06: Process `f` no-filter proof had one successful validation (page1 rows confirmed, page5 rows extracted), followed by intermittent infinite-loading recurrence.
- 2026-04-06: Cleaned temporary process-`f` proof artifacts (`last_page_in.png`, `last_page_on.png`, `last_run.log`, `tmp_ui_probe_page5_test.log`, `tmp_ui_probe_page5_result.json`) and synced docs/context files.
- 2026-04-06: Process `f` added rollback-aware UI page detection/recommit handling for transient target-page snapback.
- 2026-04-06: Process `f` added config-driven replay resume and progress checkpoints (`resume_from_page`, `track_progress_in_config`, `runtime_progress.last_page_extracted`).
- 2026-04-06: Synced process-`f` config schema across all active local config files and cleaned unused files (`_probe_sort_options.py`, `f_search_result_crash.json`).
- 2026-04-06: Process `f` fixed ambiguous paginator-arrow behavior after input+Enter (removed auto-arrow clicks in probe/recommit input paths), ran focused no-filter proof on target page 3 (`status=ok`, `target_rows=10`), updated docs/context, and cleaned temporary page-3 probe artifacts.
- 2026-04-06: Process `f` added row lineage field `data_from_page` across UI/API/probe paths and packed CSV schema, rechecked logic, and synced docs with current validation status (live uninterrupted 3-page artifact still pending stable execution window).
- 2026-04-06: Process `f` added per-row capture timestamp `data_retreive_at` and per-row source approach `data_retrieve_approch` (`api_replay`/`navigate_ui`) across UI/API/probe paths, and synced docs/context.
- 2026-09-16: Refreshed this carry-on file with the current `5db80f3` repository state, process-f checkpoint (`resume_from_page=3060`, `last_page_extracted=3181`), local config key drift, generated artifacts, and continuation guidance.
- 2026-09-16: Revalidated process `f` against the live site after the 5-month gap. Diagnosed and solved the Imperva `Error 15` block as a stale-session problem (April visitor ID + dead session cookies), not a site change — fixed by config only.
- 2026-09-16: Discovered DBD's server-side broad-query guard (HTTP 400). `บริษัท` and `จำกัด` are blocklisted; the guard runs before filters and cannot be bypassed via the API. The single-broad-keyword seed design for process `f` is permanently dead.
- 2026-09-16: Tested and DISPROVED TSIC business-type codes as a partition key (30% on-target; ~25x count shortfall vs the archived dataset). Do not build coverage claims on it.
- 2026-09-16: Verified juristic-ID prefix sweep as the exhaustive replacement partition (substring matching, filters compose, deep pagination intact). Sizing cross-validated within 2% against the April dataset: ~3,200 pages across 78 four-digit prefixes.
- 2026-09-16: Confirmed the archived dataset position: 32,260 raw rows / 31,725 unique juristic_ids in `Downloads/DBD Data/DBD Data Set 0/`, covering pages 1-3181 with genuine gaps only at pages 232-233. Documented the `"w"`-mode CSV truncation bug that makes manual archiving load-bearing.
- 2026-09-16: Added process-`f` probe utilities: `f_guard_probe.py`, `f_tsic_verify.py`, `f_idprefix_probe.py`, `f_sweep_size_probe.py`, plus `f_local_config.smoke_test.json`.
- 2026-09-16: Added process `g` (`g_DBD_CRM_Pipeline/`) — SQLite system of record keyed on `juristic_id` with field-level change history, replacing the truncate-on-every-run CSV model. Migrated all 18 archived April CSVs: inserted=31725, changed=1, unchanged=534, skipped=0; totals reconcile exactly with the independent unique-id count.
- 2026-09-16: Discovered via process `g` change tracking that DBD has published fiscal year 2568 financials. The archived April dataset is FY2567, so revenue/profit/assets/equity are stale for every record. A 148-page resweep of prefix `0107` changed 1,107 of 1,163 companies across exactly those four fields.
- 2026-09-16: Confirmed the DBD infos API page size is hard-locked at 10 rows; `pageSize`, `size`, `limit`, `rowsPerPage`, `perPage` and `itemsPerPage` are all ignored. Bulk collection cost is therefore floored at one fetch per 10 companies.
- 2026-09-16: Encoded the full collection plan as capital bands (sets 1-7, ~790,000 companies / ~79,000 pages) in `g_sets_config.json`. Set 0 (the April dataset) is a subset of sets 1-3 on capital, so sets 1-3 refresh it as a side effect.
- 2026-09-16: Added `g_session.py` Imperva-safety layer: session rotation on a page budget, no persisted storage state, jittered waits, explicit block-page detection with rotate-and-retry recovery.
- 2026-09-16: Started the sets 1-3 collection run (~101,000 companies, ~10,100 pages) at the observed ~2s/page. Resumable per bucket via `sweep_buckets`.
- 2026-09-17: Completed set1 (19,939 rows / 2,674 pages) and set2 (53,038 rows / 6,920 pages) of the capital-band collection plan; store passed 83,000 companies, +51,000 over the April baseline. set3 running.
- 2026-09-17: Five failure classes were found and fixed by running the sweep in production, all now handled automatically: NULL/DEFAULT insert crash, `TargetClosedError` on browser close, JWT expiry at ~15 min (HTTP 401, was silently discarding buckets), single-shot request timeouts, and HTTP 429 rate limiting (~2 min cooldown, verified by probe - not a daily quota).
- 2026-09-17: Measured operating envelope: API page size hard-locked at 10 rows; safe rate ~20 pages/min (1200ms page delay tripped 429 after 23 min, 1800ms did not); JWT TTL ~15 min so re-seed at 540s; throughput ~150 new records/min; set2 on-prefix efficiency 83%.
- 2026-09-17: Documented a sparse-prefix inefficiency (a 4-digit prefix substring-matches mid-ID, so `0555` cost ~900 pages for ~30 rows) and a possible `pvCodeList` optimization that is deliberately NOT applied because it would silently drop relocated companies. See SERVER_HANDOFF.md.
- 2026-09-17: Added `g_DBD_CRM_Pipeline/SERVER_HANDOFF.md` and `HOW_IT_WORKS.md`; marked `f_local_config.temp_prod.json` as non-functional (its seed keyword is blocked).
- 2026-09-17: **Sets 1-3 complete and verified.** 107,941 companies (April baseline 31,725, +76,216 collected), 110,501 change records, 13,602 pages fetched, 0 duplicate juristic_ids. Verification passed on every check: no unresolved buckets in any set, 78/78 seed prefixes resolved per set, all 26 split parents have 10 resolved children, `PRAGMA integrity_check` ok. Capital bands landed within 3.3% of the planning estimates (set1 19,966/20,000; set2 53,059/52,000; set3 29,965/29,000). The store covers every operating Thai company (บริษัทจำกัด + บริษัทมหาชนจำกัด) with registered capital >=5M.
- 2026-09-17: Sixth production failure class found and fixed: the workstation slept mid-run and Playwright's `net::ERR_NETWORK_CHANGED` was re-raised rather than treated as recoverable, ending the run. Chromium net errors are now classified as session-dead, and `SweepSession.open()` retries 3x with 15s/45s/90s backoff.
- 2026-09-17: Store WAL-checkpointed (100.6 MB, self-contained) and `crm_companies.csv` exported (107,941 rows, 57.9 MB), ready to move to a server.
