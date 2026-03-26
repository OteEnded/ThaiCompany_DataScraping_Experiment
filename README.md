# Thai Company Data Scraping Experiment

Repository name: ThaiCompany_DataScraping_Experiment

This repository is a multi-source data collection and analysis playground focused on company data from Thai market and registry sources.

This workspace is organized into five process folders:

- `x/` — AI-powered web search (Brave + SiliconFlow LLM)
- `y/` — DBD DataWarehouse scraper with HKDF/AES-GCM decryption
- `z/` — AI summary generator from `y` outputs
- `s_sdk/` — Settrade SDK wrapper (market data, account info via settrade-v2)
- `s_scape/` — Settrade web scraper (company profile, shareholders, trading history via Playwright)

Root-level shared files:

- `config.json` — API keys and credentials for all processes
- `config.example.json` — template for creating your local `config.json`

## Folder Layout

```text
AI_Search/
  config.json
  README.md
  x/
    x.py
    dumps/
      final_result.txt
      last_brave_search_result.json
      siliconflow_search_query_built_result.json
  y/
    y.py
    dbd_result.json
    dbd_result_decrypted.json
    debug/
      dbd_page.html
  z/
    z.py
    z_compact_data.json
    z_summary.md
  s_sdk/
    s.py
    settrade_company_data.json
    settrade_company_data.md
  s_scape/
    s_scrape.py
    settrade_{SYMBOL}.json
    settrade_{SYMBOL}.md
```

## End-to-End Flow

1. **x** — Search + LLM experimentation (Brave Search API + SiliconFlow).
2. **y** — Scrape and decrypt DBD company registration data by juristic ID.
3. **z** — Generate a human-readable markdown summary from y results.
4. **s_sdk** — Query Settrade market data and brokerage account via official SDK.
5. **s_scape** — Scrape public Settrade data (no login required) for any SET symbol.

## Run Commands

From workspace root:

```powershell
# Search / LLM
python x/x.py

# DBD scraper (company registration data)
python y/y.py --juristic-id 70107561000081

# AI summary from DBD output
python z/z.py

# Settrade SDK (market data + account)
python s_sdk/s.py

# Settrade web scraper — outputs settrade_{SYMBOL}.json + .md
python s_scape/s_scrape.py --symbol OSP --headless
python s_scape/s_scrape.py --symbol AOT --headless
```

## Result Examples (Per Folder)

### x/ (Search + LLM)

Generated files:
- `x/dumps/siliconflow_search_query_built_result.json`
- `x/dumps/last_brave_search_result.json`
- `x/dumps/final_result.txt`

Example (`x/dumps/siliconflow_search_query_built_result.json`):

```json
{
  "user_input": "บรษท โอสถสภา จำกด (มหาชน) OSP",
  "decision": {
    "action": "search_web",
    "query": "บรษท โอสถสภา จำกด (มหาชน) OSP"
  },
  "built_query": "บรษท โอสถสภา จำกด (มหาชน) OSP"
}
```

### y/ (DBD Capture + Decryption)

Generated files:
- `y/dbd_result.json`
- `y/dbd_result_decrypted.json`
- `y/debug/dbd_page.html` (optional debug dump)

Example (`y/dbd_result_decrypted.json`):

```json
{
  "enc_key_found": true,
  "enc_key_candidates": 1,
  "profile": null,
  "financial": null,
  "financial_sections": {},
  "others": [
    {
      "url": "https://datawarehouse.dbd.go.th/api/refresh",
      "data": {
        "idToken": "..."
      }
    }
  ]
}
```

### z/ (AI Summary)

Generated files:
- `z/z_compact_data.json`
- `z/z_summary.md`

Example (`z/z_compact_data.json`):

```json
{
  "profile_snapshot": {
    "name_th": null,
    "name_en": null,
    "juristic_id": null
  },
  "financial_deep_dive": {
    "latest_financial": {},
    "yearly_financials": [],
    "submit_history": []
  }
}
```

### s_sdk/ (Settrade SDK)

Generated files:
- `s_sdk/settrade_company_data.json`
- `s_sdk/settrade_company_data.md`

Example (`s_sdk/settrade_company_data.json`):

```json
{
  "source": "settrade_v2",
  "symbol": "AOT",
  "retrieved_at": "2026-03-26T08:28:49.247566Z",
  "quote": {
    "last": 54.25,
    "change": -0.75,
    "percentChange": -1.36,
    "marketStatus": "Open2",
    "pe": 41.79,
    "pbv": 5.38
  },
  "candlestick": {
    "lastSequence": 264558,
    "time": [1770829200, 1770915600, 1771174800]
  },
  "snapshot": {
    "last_price": 54.25,
    "market_status": "Open2"
  }
}
```

### s_scape/ (Settrade Web Scraper)

Generated files:
- `s_scape/settrade_{SYMBOL}.json`
- `s_scape/settrade_{SYMBOL}.md`

Example (`s_scape/settrade_OSP.json`):

```json
{
  "symbol": "OSP",
  "scraped_at": "2026-03-26T15:29:37.969452",
  "profile": {
    "name": "บริษัท โอสถสภา จำกัด (มหาชน)",
    "market": "SET",
    "industry": "AGRO",
    "sector": "FOOD"
  },
  "info": {
    "last": 14.2,
    "change": -0.4,
    "percentChange": -2.739726,
    "marketStatus": "Open2"
  },
  "shareholder": {
    "totalShareholder": 33323,
    "percentScriptless": 97.13
  },
  "historical": [
    {
      "date": "2026-03-25T00:00:00+07:00",
      "close": 14.6
    }
  ],
  "corporate_action": [
    {
      "caType": "XD",
      "recordDate": "2026-05-08T00:00:00+07:00"
    }
  ]
}
```

## Settrade Scraper Data (`s_scape/s_scrape.py`)

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

## Dependencies

Install required Python packages in your active Python environment:

```powershell
pip install requests playwright cryptography settrade-v2
python -m playwright install chromium
```

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
- account numbers and `pin` if you will run `s_sdk/s.py`

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

- `z/z.py` reads from `y/dbd_result_decrypted.json` and writes to `z/z_summary.md`.
- `x/x.py` writes outputs under `x/dumps/` (not `x/result.md`).
- `y/y.py` can return empty profile/financial payloads when DBD anti-bot blocks full page hydration; retry in non-headless mode and wait for full page render.
- `s_scape/s_scrape.py` launches a headless Chromium browser to obtain a live session, then calls Settrade's REST APIs via in-page `fetch()` — direct `requests` calls get 403.
- Keep `config.json` at root so all processes can share API keys and credentials.

## What We Have Done So Far

- Built and verified `x/x.py` for Brave Search + SiliconFlow LLM flow.
- Built and verified `y/y.py` for DBD capture + decryption pipeline, with anti-bot caveat documented.
- Built and verified `z/z.py` summary generation from decrypted DBD output.
- Added `s_sdk/s.py` integration with Settrade SDK for quote/candlestick and account-related access.
- Built `s_scape/s_scrape.py` to fetch public Settrade data (`profile`, `info`, `overview`, `shareholder`, `historical-trading`, `corporate-action`).
- Added repository hygiene files: `.gitignore`, `config.example.json`, and updated documentation.

## Reference Links

- Settrade SDK (Python quick start): https://developer.settrade.com/open-api/document/reference/sdkv2/introduction/python/quick-start
- Settrade Company Snapshot page: https://www.settrade.com/th/equities/company-snapshot
- SetSmart login: https://www.setsmart.com/ssm/login
- Brave API dashboard (keys): https://api-dashboard.search.brave.com/app/keys
- SiliconFlow billing page: https://cloud.siliconflow.com/me/bills
- DBD DataWarehouse: https://datawarehouse.dbd.go.th/
