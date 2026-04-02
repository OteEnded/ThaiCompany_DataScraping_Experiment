# e_AI_Local_Context.md

## Scope
Process `e` scrapes public Settrade company snapshot data using Playwright and in-page fetch calls.
No login required for the currently used endpoints.

## Entrypoint
- Script: `e_main.py`
- Run:
  - `python e_Settrade_Scraper/e_main.py --symbol OSP`
  - `python e_Settrade_Scraper/e_main.py --symbol AOT --headless`

## Outputs
In process folder:
- `settrade_{SYMBOL}.json`
- `settrade_{SYMBOL}.md`

## Confirmed Endpoints (No Auth)
- `/api/set/stock/{sym}/profile`
- `/api/set/stock/{sym}/info`
- `/api/set/stock/{sym}/overview`
- `/api/set/stock/{sym}/shareholder`
- `/api/set/stock/{sym}/historical-trading?period=MAX`
- `/api/set/stock/{sym}/corporate-action`

## Internal Flow
1. Launch browser context and open Settrade company snapshot page
2. Execute `FETCH_JS` in page context to request endpoint set
3. Collect response body/status per endpoint
4. Assemble normalized result payload and render markdown summary

## Probe Scripts
- `probe*.py` files are exploratory/debug utilities and not part of core flow.
- They were updated to use `e_Settrade_Scraper/` path outputs after folder rename.

## Known Limitations
- Financial statement API paths typically require authentication and are not reliably available in this scraper flow.
- Endpoint availability can change based on Settrade frontend/API updates.

## Maintenance Notes
- Keep endpoint list/version aligned with live site behavior
- If endpoint contracts change, update JSON parsing and markdown rendering together
