# d_AI_Local_Context.md

## Scope
Process `d` uses the official `settrade-v2` SDK to retrieve market and account-level data.

## Entrypoint
- Script: `d_main.py`
- Run:
  - `python d_Settrade_SDK/d_main.py`

## Inputs
From `config.json -> SETTRADE`:
- `app_id`
- `app_secret`
- `broker_id`
- `app_code`
- `derivatives_account_no` (or legacy `account_no` fallback)
- optional `default_symbol`, `is_auto_queue`

## Outputs
In process folder:
- `settrade_company_data.json`
- `settrade_company_data.md`

## Internal Flow
1. Validate SETTRADE config and detect missing placeholders
2. Build `Investor` client (`settrade_v2.Investor`)
3. Pull derivatives account info
4. Pull market quote + candlestick for target symbol
5. Build merged payload and write JSON/MD outputs

## Key Functions
- `validate_settrade_config(cfg)`
- `build_investor(settrade_cfg)`
- `retrieve_account_info(investor, settrade_cfg)`
- `retrieve_company_market_data(investor, symbol, interval, limit)`

## Known Limitations
- Requires valid credentials and environment alignment (sandbox/live)
- Output completeness depends on account permissions

## Maintenance Notes
- Keep placeholder detection list synced with `config.example.json`
- Avoid hardcoding account identifiers in code or committed artifacts
