# b_AI_Local_Context.md

## Scope
Process `b` captures DBD DataWarehouse data for one juristic ID and decrypts encrypted API payloads.
This is the most complex process due to anti-bot protections and cryptographic payload handling.

## Entrypoint
- Script: `b_main.py`
- Run (recommended):
  - `python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081`
- Headless:
  - `python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --headless`
- Disable storage state:
  - `python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --juristic-id 0107561000081 --no-storage-state`

## Outputs
In process folder:
- `dbd_result.json` (raw captured payloads + debug)
- `dbd_result_decrypted.json` (decrypted output)
- `storage_state.json` (session cookies/localStorage, gitignored)
- `dumps/dbd_page.html` fallback debug page when no data is captured

## Capture/Decrypt Pipeline
1. Playwright opens DBD site and hydrates profile page
2. Intercepts `/api/` responses and also performs in-page `fetch()` fallback
3. Detects blocked payloads (Imperva Incapsula)
4. Extracts JWT token (`__NUXT__` runtime first, HTML regex fallback)
5. Derives AES key via HKDF-SHA256 using `encKey`, `salt`, `kid`, `aad`
6. AES-GCM decrypt; zlib decompress if needed; parse JSON/text

## Anti-Bot Handling
Incapsula challenge responses are HTML (often HTTP 200) and must be filtered.
Implemented guards:
- `is_blocked_payload(data)` for dict marker payloads
- `is_blocked_text(text)` for string HTML challenge detection
- `normalize_captured_payload(data)` shared normalization path

Applied in both:
- Playwright response handler
- In-page fetch fallback loop

## Reliability Controls
- Retry loop up to 3 attempts (`debug.attempts`)
- Backoff: `page.wait_for_timeout(3000 * attempt)`
- Session persistence via storage state:
  - load if exists
  - save after run

## Debug/Status Fields
In `dbd_result.json -> debug`:
- `status`: `ok | partial | blocked | unknown`
- `blocked_count`, `blocked_run`
- `attempts`
- `storage_state_used`
- captured endpoint URLs

In decrypted output:
- `enc_key_found`
- `source_status`
- `source_debug`

## Key Endpoints
- `/api/v1/company-profiles/info/{jpType}/{jpNo}`
- `/api/v1/company-profiles/committees/{jpType}/{jpNo}`
- `/api/v1/company-profiles/committee-signs/{jpType}/{jpNo}`
- `/api/v1/company-profiles/mergers/{jpType}/{jpNo}`
- `/api/v1/fin/balancesheet/year/{jpType}/{jpNo}?fiscalYear={year}`
- `/api/v1/fin/submit/{jpType}/{jpNo}?fiscalYear={year}`

## Known Issues / Operational Guidance
- If blocked, run non-headless first to warm cookies/challenge session
- If still blocked, delete `storage_state.json` and retry non-headless
- Juristic ID must be 13 digits; prior 14-digit test value was invalid

## Maintenance Notes
- Keep blocked detection logic centralized (avoid divergent checks)
- Preserve `source_status/source_debug` contract because process `c` depends on it
- Any endpoint additions should update both capture and decrypt mapping
