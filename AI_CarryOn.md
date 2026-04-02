# AI_CarryOn.md — Project Context Dump

> **Purpose:** Full context handoff for any AI agent continuing work on this repository.
> Last updated: 2026-04-02 (process f API contract/replay/decrypt + packed CSV export). Repository: `ThaiCompany_DataScraping_Experiment`

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
  f_DBD_Company_List_Scraper_WIth_Filter/  ← DBD company list scraper from search + pagination + filters (in progress)
    f_main.py
    f_search_result.json
    result_packed.csv
    storage_state.json
    dumps/
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
- **Last commit:** `1d7412f` — "OteEnded[docs]: update AI_CarryOn git state after docs split"
- **Commit message convention:** `OteEnded[type]: description` (e.g., `OteEnded[fix]:`, `OteEnded[feat]:`, `OteEnded[refactor]:`)

**Pending local changes (not committed yet):**
- `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_AI_Local_Context.md` updated with Playwright iteration history and anti-bot execution policy.
- `f_DBD_Company_List_Scraper_WIth_Filter/` actively developed (`f_main.py`, `f_AI_Local_Context.md`, `dumps/`, `result_packed.csv`).
- `f_main.py` now supports: config-driven runs via `f_local_config.json`, UI+API hybrid filters, slow-load readiness detection, endpoint contract capture, replay + decrypt with retry/backoff, and packed CSV export.
- Process `f` validated 10-page filtered extraction (100 rows) using UI-applied filters + API replay pages 2..10.
- `f_local_config_option.md` added with full combobox option lists and config usage (including search-term suggestions).
- `f_DBD_Company_List_Scraper_WIth_Filter/README.md` added with full process documentation and operating guide.
- `result_examples/f_DBD_Company_List_Scraper_WIth_Filter/` created for future sample outputs.

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

1. **Add filter automation in f**
  Convert manual filter flow into scriptable selector actions + configurable filter inputs.

2. **Scale f pagination beyond 5 pages**
  Add pacing/checkpoint controls for longer runs while minimizing anti-bot triggers.

3. **Run broader extraction validation in f**
  Compare UI-extracted rows vs replay-decrypted API rows across larger page ranges.

4. **c guard for blocked b output**
  Add hard stop when `source_status != "ok"` before summary generation.

5. **Test b with different juristic IDs**
  Verify scraper generalization beyond OSOTSPA.

6. **Add `e` results to `result_examples/`**
  Refresh examples for additional symbols.

7. **Add `d` results to `result_examples/`**
  Refresh SDK examples (requires valid credentials).

8. **Connect a + b pipelines**
  Optional orchestration layer from search results to DBD scrape.

9. **Multiple juristic IDs in one b run**
  Add batch mode while reusing warmed session state.

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
