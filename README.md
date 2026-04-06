# Thai Company Data Scraping Experiment

Repository name: ThaiCompany_DataScraping_Experiment

This repository is a multi-source data collection and analysis playground focused on company data from Thai market and registry sources.

## Quick Start (How To Run)

Install required Python packages in your active Python environment:

```powershell
pip install requests playwright cryptography settrade-v2
python -m playwright install chromium
```

Create your local config file from the template:

```powershell
Copy-Item config.example.json config.json
```

Then edit `config.json` with your own keys and credentials.

This workspace is organized into six process folders:

- `a_AI_Search/` — AI-powered web search (Brave + SiliconFlow LLM)
- `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/` — DBD DataWarehouse scraper with HKDF/AES-GCM decryption
- `c_DBD_Company_AI_Summary/` — AI-powered company + financial summary from `b` outputs
- `d_Settrade_SDK/` — Settrade SDK wrapper (market data, account info via settrade-v2)
- `e_Settrade_Scraper/` — Settrade web scraper (company profile, shareholders, trading history via Playwright)
- `f_DBD_Company_List_Scraper_WIth_Filter/` — DBD company-list scraper with advanced filters (UI + API hybrid)

Root-level shared files:

- `config.json` — API keys and credentials for all processes
- `config.example.json` — template for creating your local `config.json`

## Folder Layout

```text
AI_Search/
  config.json
  README.md
  result_examples/
    a_AI_Search/
    b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/
    c_DBD_Company_AI_Summary/
    d_Settrade_SDK/
    e_Settrade_Scraper/
    f_DBD_Company_List_Scraper_WIth_Filter/
  a_AI_Search/
    a_main.py
    dumps/
      final_result.txt
      last_brave_search_result.json
      siliconflow_search_query_built_result.json
  b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/
    b_main.py
    dbd_result.json
    dbd_result_decrypted.json
    dumps/
      dbd_page.html
  c_DBD_Company_AI_Summary/
    c_main.py
    z_compact_data.json
    z_summary.md
  d_Settrade_SDK/
    d_main.py
    settrade_company_data.json
    settrade_company_data.md
  e_Settrade_Scraper/
    e_main.py
    settrade_{SYMBOL}.json
    settrade_{SYMBOL}.md
  f_DBD_Company_List_Scraper_WIth_Filter/
    f_main.py
    f_local_config.json
    f_local_config_option.md
    f_search_result.json
    result_packed.csv
    dumps/
```

## End-to-End Flow

1. **a** — Search + LLM experimentation (Brave Search API + SiliconFlow).
2. **b** — Scrape and decrypt DBD company registration data by juristic ID.
3. **c** — Generate a human-readable markdown summary from b results.
4. **d** — Query Settrade market data and brokerage account via official SDK.
5. **e** — Scrape public Settrade data (no login required) for any SET symbol.
6. **f** — Scrape DBD company list results with advanced filters and API-assisted pagination.

## Run Commands

From workspace root:

```powershell
# a — Search / LLM
python a_AI_Search/a_main.py

# b — DBD scraper (recommended, non-headless + persistent session state)
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081

# b — DBD scraper headless
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --headless

# c — AI summary from DBD output (run b first)
python c_DBD_Company_AI_Summary/c_main.py

# d — Settrade SDK (market data + account)
python d_Settrade_SDK/d_main.py

# e — Settrade web scraper — outputs settrade_{SYMBOL}.json + .md
python e_Settrade_Scraper/e_main.py --symbol OSP --headless
python e_Settrade_Scraper/e_main.py --symbol AOT --headless

# f — DBD company-list scraper (config-driven)
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.json
```

Process `f` reference docs:
- `f_DBD_Company_List_Scraper_WIth_Filter/README.md`
- `f_DBD_Company_List_Scraper_WIth_Filter/f_local_config_option.md`

Process `f` notable runtime files:
- `f_DBD_Company_List_Scraper_WIth_Filter/last_run.log` (timestamped runtime trace)
- `f_DBD_Company_List_Scraper_WIth_Filter/last_page_on.png` (latest UI wait-state capture)

Process `f` notable config controls:
- `prefer_direct_search_url` (direct URL first, search-box fallback)
- `sort_label` (UI sort selection before capture/replay)
- `pages = -1` with `fetch_all_max_pages` safety cap
- `resume_from_page` (continue replay from configured page after init/filter/sort)
- `track_progress_in_config` + `runtime_progress.last_page_extracted` (checkpoint persistence)

Process `f` recent hardening (2026-04-06):
- UI row-confirmation retry waits were increased from `700ms` to `1500ms` in both:
  - `f_DBD_Company_List_Scraper_WIth_Filter/f_main.py`
  - `f_DBD_Company_List_Scraper_WIth_Filter/f_ui_probe_page5_test.py`
- UI page-nav rollback hardening:
  - removed ambiguous pager-arrow auto-click after input+Enter in UI probe/recommit paths,
  - prevents accidental `next` vs `previous` mismatch when both controls are visible.
- Focused proof run passed (`--target-page 3`):
  - `status=ok`, `page1_rows=10`, `target_rows=10`, `target_success=true`.
- New output lineage field:
  - `data_from_page` added to process-`f` JSON/CSV rows to track page-of-origin.
  - `data_retreive_at` added to process-`f` rows for capture-time sorting.
  - `data_retrieve_approch` added to process-`f` rows with values: `api_replay` or `navigate_ui`.
  - wiring confirmed for UI rows, API replay rows, and probe rows.
  - full uninterrupted live 3-page proof artifact still pending stable run window.
- Dedicated proof runner exists for strict no-filter validation:
  - `python f_DBD_Company_List_Scraper_WIth_Filter/f_ui_probe_page5_test.py --config f_local_config.ui_probe_nofilter_test.json`
- Temporary proof artifacts are intentionally disposable:
  - `tmp_ui_probe_page5_test.log`, `tmp_ui_probe_page5_result.json`, `tmp_ui_probe_page3_test.log`, `tmp_ui_probe_page3_result.json`, `last_page_on.png`, `last_page_in.png`, `last_run.log`

## Result Examples (From Latest Run)

To keep this README short, full examples are stored in `result_examples/`:

- a (AI_Search):
  - [result_examples/a_AI_Search/siliconflow_search_query_built_result.json](result_examples/a_AI_Search/siliconflow_search_query_built_result.json)
  - [result_examples/a_AI_Search/last_brave_search_result.json](result_examples/a_AI_Search/last_brave_search_result.json)
  - [result_examples/a_AI_Search/final_result.txt](result_examples/a_AI_Search/final_result.txt)
- b (DBD Scraper):
  - [result_examples/b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result.json](result_examples/b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result.json)
  - [result_examples/b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result_decrypted.json](result_examples/b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result_decrypted.json)
- c (Financial Summary):
  - [result_examples/c_DBD_Company_AI_Summary/z_compact_data.json](result_examples/c_DBD_Company_AI_Summary/z_compact_data.json)
  - [result_examples/c_DBD_Company_AI_Summary/z_summary.md](result_examples/c_DBD_Company_AI_Summary/z_summary.md)
- d (Settrade SDK):
  - [result_examples/d_Settrade_SDK/settrade_company_data.json](result_examples/d_Settrade_SDK/settrade_company_data.json)
  - [result_examples/d_Settrade_SDK/settrade_company_data.md](result_examples/d_Settrade_SDK/settrade_company_data.md)
- e (Settrade Scraper):
  - [result_examples/e_Settrade_Scraper/settrade_OSP.json](result_examples/e_Settrade_Scraper/settrade_OSP.json)
  - [result_examples/e_Settrade_Scraper/settrade_OSP.md](result_examples/e_Settrade_Scraper/settrade_OSP.md)
- f (DBD Company List + Filter):
  - [result_examples/f_DBD_Company_List_Scraper_WIth_Filter/f_search_result.json](result_examples/f_DBD_Company_List_Scraper_WIth_Filter/f_search_result.json)
  - [result_examples/f_DBD_Company_List_Scraper_WIth_Filter/result_packed.csv](result_examples/f_DBD_Company_List_Scraper_WIth_Filter/result_packed.csv)

Notes for b examples:
- `dbd_result.json` may contain `_raw_text` payloads when DBD returns Incapsula challenge HTML instead of API JSON.
- `dbd_result_decrypted.json` can show `enc_key_found=false` (or empty profile/financial) when no valid JWT/encKey is available during that run.
- Check `debug.blocked_urls` in `dbd_result.json` to confirm anti-bot blocking.
- `debug.status` in `dbd_result.json` reports one of `ok`, `partial`, or `blocked`.
- `source_status` in `dbd_result_decrypted.json` mirrors the upstream run status for quick downstream checks.

## Settrade Scraper Data (`e_Settrade_Scraper/e_main.py`)

Fetches six public endpoints for any SET symbol (no authentication required):

| Field | Source |
|---|---|
| Company profile (name, market, ISIN, par, free float, etc.) | `/api/set/stock/{sym}/profile` |
| Live trading info (last price, volume, bid/offer) | `/api/set/stock/{sym}/info` |
| Indices membership + ESG rating + CG score | `/api/set/stock/{sym}/overview` |
| Major shareholders | `/api/set/stock/{sym}/shareholder` |
| OHLCV history (~6 months, unauthenticated cap) | `/api/set/stock/{sym}/historical-trading` |
| Dividends and corporate actions | `/api/set/stock/{sym}/corporate-action` |

> Financial statements (income statement, balance sheet, financial ratios) require Settrade login and are not available via the public API.

## Config Setup

1. Create your local config file from the template:

```powershell
Copy-Item config.example.json config.json
```

2. Open `config.json` and fill in all required values:
- `BRAVE_API_KEY`
- `SILICONFLOW_API_KEY`
- `SETTRADE.app_id`
- `SETTRADE.app_secret`
- `SETTRADE.broker_id`
- `SETTRADE.app_code`
- `SETTRADE.username`
- account numbers and `pin` if you will run `d_Settrade_SDK/d_main.py`

3. Keep `config.json` local only (it is gitignored).

Minimal structure:

```json
{
  "BRAVE_API_KEY": "YOUR_BRAVE_API_KEY",
  "SILICONFLOW_API_KEY": "YOUR_SILICONFLOW_API_KEY",
  "SETTRADE": {
    "username": "YOUR_SETTRADE_USERNAME",
    "app_id": "YOUR_SETTRADE_APP_ID",
    "app_secret": "YOUR_SETTRADE_APP_SECRET",
    "broker_id": "SANDBOX_OR_BROKER_ID",
    "app_code": "SANDBOX_OR_APP_CODE",
    "equity_account_no": "YOUR_EQUITY_ACCOUNT_NO",
    "derivatives_account_no": "YOUR_DERIVATIVES_ACCOUNT_NO",
    "default_symbol": "AOT",
    "pin": "YOUR_SETTRADE_PIN",
    "is_auto_queue": false
  }
}
```

## Notes

- `c_DBD_Company_AI_Summary/c_main.py` reads from `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result_decrypted.json` and writes summary outputs in `c_DBD_Company_AI_Summary/`.
- `a_AI_Search/a_main.py` writes outputs under `a_AI_Search/dumps/`.
- `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py` uses homepage search-flow first (same as manual tax-id search) and then falls back to direct profile URL.
- `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py` can return empty profile/financial payloads when DBD anti-bot (Incapsula) blocks API responses.
- For best chance to get valid `b` results, run non-headless and let the page finish rendering:

```powershell
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081
```

- `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py` reuses browser session cookies in `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/storage_state.json` across runs to improve reliability after a successful/challenge-passed session.
- To disable this behavior for a clean one-off run:

```powershell
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --no-storage-state
```

- When blocked, details are logged in `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result.json` under `debug.blocked_urls`.
- `e_Settrade_Scraper/e_main.py` launches a headless Chromium browser to obtain a live session, then calls Settrade REST APIs via in-page `fetch()` (direct plain `requests` calls can get 403).
- Keep `config.json` at root so all processes can share API keys and credentials.

## What We Have Done So Far

- Built and verified `a_AI_Search/a_main.py` for Brave Search + SiliconFlow LLM flow.
- Built and verified `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py` for DBD capture + decryption pipeline, with anti-bot caveat documented.
- Built and verified `c_DBD_Company_AI_Summary/c_main.py` summary generation from decrypted DBD output.
- Added `d_Settrade_SDK/d_main.py` integration with Settrade SDK for quote/candlestick and account-related access.
- Built `e_Settrade_Scraper/e_main.py` to fetch public Settrade data (`profile`, `info`, `overview`, `shareholder`, `historical-trading`, `corporate-action`).
- Added and validated `f_DBD_Company_List_Scraper_WIth_Filter/f_main.py` for DBD list extraction with advanced filters and API replay pagination.
- Added repository hygiene files: `.gitignore`, `config.example.json`, and updated documentation.

## Reference Links

- Settrade SDK (Python quick start): https://developer.settrade.com/open-api/document/reference/sdkv2/introduction/python/quick-start
- Settrade Company Snapshot page: https://www.settrade.com/th/equities/company-snapshot
- SetSmart login: https://www.setsmart.com/ssm/login
- Brave API dashboard (keys): https://api-dashboard.search.brave.com/app/keys
- SiliconFlow billing page: https://cloud.siliconflow.com/me/bills
- DBD DataWarehouse: https://datawarehouse.dbd.go.th/
