# AI_CarryOn.md — Project Context Dump

> **Purpose:** Full context handoff for any AI agent continuing work on this repository.
> Last updated: 2026-04-02 (rename refactor committed). Repository: `ThaiCompany_DataScraping_Experiment`

## How to Use This File

This file is a **living document**. It is the single source of truth for project state, progress, and plans.

**Rules for every AI agent working on this project:**
- **Read this file first** before doing any work, every session.
- **Update this file immediately** whenever:
  - A module or file is modified
  - A bug is fixed or a new issue is found
  - A plan or next step changes
  - A run is validated (update git state, example data, known issues as needed)
  - A new feature or module is added
- Keep the "Last updated" date in the header current.
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

### 5.1 `a_AI_Search/a_main.py` — Web Search Agent

**What it does:** Takes a user query, uses SiliconFlow LLM to decide whether to search the web (via Brave Search API), then answers with LLM.

**Run:**
```powershell
python a_AI_Search/a_main.py
python a_AI_Search/a_main.py --query "หา บริษัท tax id 0105551234567"
```

**Outputs (in `a_AI_Search/dumps/`):**
- `siliconflow_search_query_built_result.json` — LLM's search decision + built query
- `last_brave_search_result.json` — raw Brave Search results
- `final_result.txt` — LLM's final answer

**Key internals:**
- `web_search(query, count=5)` → calls `api.search.brave.com/res/v1/web/search`
- `ask_llm(prompt)` → calls SiliconFlow `Qwen/QwQ-32B`
- `agent(user_input)` → orchestrates decide→search→answer loop
- No auth required beyond API keys in `config.json`

---

### 5.2 `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py` — DBD DataWarehouse Scraper ⚠️ Most Complex Module

**What it does:** Uses Playwright (Chromium) to navigate DBD DataWarehouse (`datawarehouse.dbd.go.th`), intercept encrypted API responses, decrypt them via HKDF/AES-GCM, and save raw + decrypted results.

**Run:**
```powershell
# Default (non-headless, with storage state — recommended)
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081

# Headless mode
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --headless

# Disable storage state (fresh session)
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --no-storage-state

# Different company
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id <ANY_13_DIGIT_JURISTIC_ID>
```

**Outputs (in `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/`):**
- `dbd_result.json` — raw captured/encrypted payloads + debug info
- `dbd_result_decrypted.json` — decrypted version with all company data
- `storage_state.json` — saved Playwright cookies/localStorage (gitignored)

#### Anti-Bot System (Imperva Incapsula)

The site uses Incapsula anti-bot protection. When blocked:
- API responses are HTML strings containing `_Incapsula_Resource` or `Incapsula incident ID`
- These are NOT valid JSON — they look like valid HTTP 200 responses

**Detection functions:**
```python
def is_blocked_payload(data) -> bool:
    return isinstance(data, dict) and data.get("_blocked_by_incapsula") is True

def is_blocked_text(text: str) -> bool:
    if not isinstance(text, str): return False
    lowered = text.lower()
    return "incapsula incident id" in lowered or "_incapsula_resource" in lowered

def normalize_captured_payload(data):
    """Returns (normalized_data, blocked: bool)"""
    if is_blocked_payload(data): return data, True
    if is_blocked_text(data): return {"_blocked_by_incapsula": True, "_raw_text": data[:500]}, True
    return data, False
```

Applied in BOTH the Playwright response handler AND the in-page `fetch()` fallback.

#### Retry Loop

Up to 3 attempts per run with exponential back-off:
```python
max_attempts = 3
for attempt in range(1, max_attempts + 1):
    results["debug"]["attempts"] = attempt
    hydrate_profile_page(page, juristic_id)
    trigger_finance_tab_clicks(page)
    # ... fetch + capture ...
    got_profile = isinstance(results.get("profile"), dict)
    got_financial = isinstance(results.get("financial"), (dict, list))
    if got_profile and got_financial:
        break
    page.wait_for_timeout(3000 * attempt)
```

#### Storage State (Session Persistence)

Saves Playwright browser cookies after a successful run, reuses them next time to skip Incapsula re-challenges:
```python
DEFAULT_STORAGE_STATE = BASE_DIR / "storage_state.json"
# Loaded: context_kwargs["storage_state"] = str(storage_state_path)
# Saved after run: context.storage_state(path=str(storage_state_path))
```

First run after fresh clone: run **non-headless** to let Incapsula pass (visible browser solves challenge automatically). Subsequent runs can use `--headless`.

#### Decryption Pipeline

1. JWT `encKey` extracted from `__NUXT__` runtime config (or HTML fallback)
2. HKDF-SHA256: `info = f"bdw|v{kid}|{aad_hint}".encode()` with extracted `salt`
3. AES-GCM decrypt CT with derived key and `iv`
4. Try zlib decompress (wbits=31 first, then raw), then UTF-8 decode, then JSON parse

#### `debug` Fields in Output

| Field | Meaning |
|---|---|
| `debug.status` | `"ok"` / `"partial"` / `"blocked"` / `"unknown"` |
| `debug.blocked_count` | Number of Incapsula-blocked API calls |
| `debug.blocked_run` | `true` if any API was blocked |
| `debug.attempts` | How many retry attempts were made |
| `debug.storage_state_used` | Path to loaded storage state file (or null) |

In `dbd_result_decrypted.json`:
| Field | Meaning |
|---|---|
| `enc_key_found` | `true` = JWT encKey was found and decryption attempted |
| `source_status` | Mirror of `debug.status` from raw result |
| `source_debug` | Mirror of key debug fields |

#### Key API Endpoints Captured

All under `https://datawarehouse.dbd.go.th`:
- `/api/v1/company-profiles/info/{jpType}/{jpNo}` — company profile
- `/api/v1/company-profiles/committees/{jpType}/{jpNo}` — board members
- `/api/v1/company-profiles/committee-signs/{jpType}/{jpNo}` — signing authority
- `/api/v1/company-profiles/mergers/{jpType}/{jpNo}` — merger/transform history
- `/api/v1/fin/balancesheet/year/{jpType}/{jpNo}?fiscalYear={year}` — financial statements
- `/api/v1/fin/submit/{jpType}/{jpNo}?fiscalYear={year}` — filing submission history

`jpType` for most Thai juristic entities = `"7"`. `jpNo` = the 13-digit juristic ID.

---

### 5.3 `c_DBD_Company_AI_Summary/c_main.py` — Financial Summary Generator

**What it does:** Reads `y/dbd_result_decrypted.json`, extracts key financial fields, generates a compact JSON + markdown summary (via SiliconFlow LLM or local fallback).

**Run:**
```powershell
python c_DBD_Company_AI_Summary/c_main.py
```

**Outputs (in `c_DBD_Company_AI_Summary/`):**
- `z_compact_data.json` — structured financial snapshot
- `z_summary.md` — human-readable analysis

**Key functions:**
- `extract_summary_fields(data)` → builds `profile_snapshot` + `financial_deep_dive`
- `summarize_with_ai(compact_data)` → SiliconFlow LLM Thai-language analysis (Qwen/QwQ-32B)
- `local_human_summary(compact_data)` → plain-text fallback when no API key

**LLM prompt:** Thai-language financial analysis with sections: ภาพรวมบริษัท, วิเคราะห์งบการเงินเชิงลึก, ความเสี่ยงหลัก, มุมมองเชิงปฏิบัติ.

**Important:** Always run `b` first to get fresh `dbd_result_decrypted.json`. If `source_status != "ok"`, c will produce incorrect/empty summaries.

---

### 5.4 `d_Settrade_SDK/d_main.py` — Settrade SDK Wrapper

**What it does:** Uses official `settrade-v2` Python SDK to query live market data and brokerage account info.

**Run:**
```powershell
python d_Settrade_SDK/d_main.py
```

**Outputs (in `d_Settrade_SDK/`):**
- `settrade_company_data.json` — market data + account info
- `settrade_company_data.md` — human-readable summary

**Requires:** Valid Settrade developer credentials in `config.json` (`SETTRADE.app_id`, `app_secret`, `broker_id`, `app_code`, `derivatives_account_no`).

All modules load config from the workspace root: `Path(__file__).resolve().parent.parent / "config.json"`.

**Key functions:**
- `build_investor(settrade_cfg)` → creates `settrade_v2.Investor` instance
- `retrieve_account_info(investor, cfg)` → gets derivatives account info
- `retrieve_company_market_data(investor, symbol, interval, limit)` → quote + candlestick

---

### 5.5 `e_Settrade_Scraper/e_main.py` — Settrade Web Scraper

**What it does:** Uses Playwright to load Settrade website, then calls Settrade REST APIs from within the browser session (no login required).

**Run:**
```powershell
python e_Settrade_Scraper/e_main.py --symbol OSP
python e_Settrade_Scraper/e_main.py --symbol AOT --headless
```

**Outputs (in `e_Settrade_Scraper/`):**
- `settrade_{SYMBOL}.json` — all captured API data
- `settrade_{SYMBOL}.md` — formatted summary

**Confirmed working endpoints (no auth):**
- `/api/set/stock/{sym}/profile`
- `/api/set/stock/{sym}/info`
- `/api/set/stock/{sym}/overview`
- `/api/set/stock/{sym}/shareholder`
- `/api/set/stock/{sym}/historical-trading?period=MAX`
- `/api/set/stock/{sym}/corporate-action`

Financial statements require login — NOT captured by this scraper.

**`probe*.py` files** in `e_Settrade_Scraper/` are experiment/debug scripts from early development. Not part of the main flow.

---

## 6. End-to-End Data Flow

```
a_AI_Search/a_main.py  →  Brave Search + LLM answer  →  a_AI_Search/dumps/final_result.txt

b_DBD_.../b_main.py  →  DBD scrape + decrypt  →  b_DBD_.../dbd_result_decrypted.json
    ↓
c_DBD_Company_AI_Summary/c_main.py  →  compact JSON + summary  →  c_DBD_Company_AI_Summary/z_compact_data.json, z_summary.md

d_Settrade_SDK/d_main.py  →  Settrade SDK  →  d_Settrade_SDK/settrade_company_data.json
e_Settrade_Scraper/e_main.py --symbol OSP  →  e_Settrade_Scraper/settrade_OSP.json
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

### b — Incapsula Blocking
- **Symptom:** `debug.status = "blocked"`, `blocked_count > 0`, profile/financial are null or `{"_blocked_by_incapsula": true}`
- **Fix:** Run non-headless (`python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py` without `--headless`). The visible browser is less likely to get challenged. After first successful run, `storage_state.json` is saved and future runs (even headless) reuse the authenticated session.
- **If still blocked:** Delete `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/storage_state.json` and run non-headless again to get a fresh session.

### b — Wrong juristic ID format
- Correct: `0107561000081` (13 digits, starts with 0)
- Wrong: `70107561000081` (14 digits — old test value, incorrect)

### c — Running on blocked b output
- If `source_status != "ok"`, c will produce partial/empty compact data and a misleading summary
- Always check `source_status` in `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result_decrypted.json` before running c
- **Not yet implemented:** c guard that aborts when source_status is not ok (suggested next step)

### s_sdk — Sandbox vs Live
- `broker_id` and `app_code` values determine sandbox vs live environment
- Sandbox values: per Settrade documentation at `developer.settrade.com`
- Live brokerage account required for real account data

---

## 9. Git State

- **Git:** Already initialized in the workspace root (`c:\data\AI_Search`)
- **Remote:** `https://github.com/OteEnded/ThaiCompany_DataScraping_Experiment.git`
- **Branch:** `main`
- **Last commit:** `c00a987` — "OteEnded[fix]: stabilize y anti-bot flow and refresh examples"
- **Commit message convention:** `OteEnded[type]: description` (e.g., `OteEnded[fix]:`, `OteEnded[feat]:`, `OteEnded[refactor]:`)

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

1. **c guard for blocked b output**
   Add check in `c_DBD_Company_AI_Summary/c_main.py` `main()`:
   ```python
   source_status = raw_data.get("source_status")
   if source_status and source_status != "ok":
       print(f"ERROR: b output has source_status='{source_status}'. Run b first (non-headless).")
       return
   ```

2. **Test b with different juristic IDs**
   Run `python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id <OTHER_ID>` to verify the scraper generalizes beyond OSOTSPA. The storage state is shared per domain (same cookies for all companies on `datawarehouse.dbd.go.th`).

3. **Add `e` results to `result_examples/`**
   Currently `result_examples/e_Settrade_Scraper/` is empty. Run `python e_Settrade_Scraper/e_main.py --symbol AOT --headless` and commit results.

4. **Add `d` results to `result_examples/`**
   `result_examples/d_Settrade_SDK/` is empty. Requires live Settrade credentials to run.

5. **Connect a + b pipelines**
   a can search for company names and return juristic IDs; b can then scrape the found company. Currently no cross-module orchestration exists.

6. **Multiple juristic IDs in one b run**
   Add `--juristic-ids` list support (loop `get_company_data()` calls) so a batch of companies can be scraped in a single session while reusing the warm Incapsula-bypassed cookies.

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
```
