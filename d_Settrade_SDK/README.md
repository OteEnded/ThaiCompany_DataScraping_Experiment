# Process D: Settrade SDK Retrieval

## Overview
Process d uses settrade-v2 SDK to retrieve:
- Derivatives account information.
- Equity market data snapshot + candlestick series.

It supports account-only, market-only, or both modes and writes reusable output files.

---

## Folder Contents
- d_main.py: SDK retrieval entrypoint.
- d_local_config.json: local runtime config.
- d_AI_Local_Context.md: process notes and progress.
- settrade_company_data.json: latest company market payload.
- settrade_company_data.md: human-readable snapshot summary.

---

## Requirements
Install once in workspace root:

```powershell
pip install settrade-v2
```

Root config.json must contain SETTRADE credentials:
- app_id
- app_secret
- broker_id
- app_code
- derivatives_account_no (or legacy account_no)

---

## Run
Default run (uses local config):

```powershell
python d_Settrade_SDK/d_main.py
```

Explicit config path:

```powershell
python d_Settrade_SDK/d_main.py --config d_Settrade_SDK/d_local_config.json
```

---

## Config Model
Runtime options come from d_local_config.json.

Key fields:
- mode: account-info | company-data | both.
- symbol: target stock symbol (null means use SETTRADE.default_symbol from root config).
- interval: candle interval (example 1d, 5m).
- limit: candle point count.

Validation behavior:
- Invalid mode falls back to company-data.
- Non-numeric limit falls back to 30.

---

## Output
When mode includes company-data, files are updated:
- settrade_company_data.json
- settrade_company_data.md

JSON includes:
- quote payload.
- candlestick payload.
- computed snapshot fields (last price, change, PE/PBV/EPS, latest candle).

---

## Known Caveats
- Requires valid broker/app credentials and account permission.
- SDK/API errors are printed with message/code/status for troubleshooting.
- Account-info mode can fail if account mapping is not valid in credentials.

---

## Recommended Workflow
1. Fill SETTRADE credentials in root config.json.
2. Set mode/symbol/interval/limit in d_local_config.json.
3. Run process d and verify output files.
4. If errors occur, inspect returned code/status and validate credentials.
