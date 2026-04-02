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

## Execution Policy (Anti-Bot Aware)
- Non-headless RPA-style execution is acceptable and preferred for reliability when anti-bot is active.
- Use headless as a quick extraction check first when desired.
- If headless run is partial/blocked or missing key sections, immediately rerun non-headless.
- Treat non-headless as the fallback standard path, not an exception.

Recommended run order:
1. Optional quick test: headless run
2. If data is incomplete or blocked: rerun non-headless
3. Keep/refresh `storage_state.json` from successful non-headless runs

## How Playwright Is Used
Playwright is used as a browser-level orchestrator, not only for UI clicks.

Main usage pattern:
1. Launch Chromium (`headless` optional)
2. Create browser context with optional `storage_state.json`
3. Register a global response listener (`context.on("response", handle_response)`) to capture API payloads
4. Navigate and hydrate page through user-like search flow
5. Click finance-related tabs to trigger additional network requests
6. Run in-page `fetch()` calls (`page.evaluate`) as fallback for endpoints that UI did not trigger
7. Extract token from `__NUXT__` runtime (fallback: HTML regex)
8. Save context storage state for next run

Why this hybrid approach:
- UI interactions alone were not always sufficient to trigger all desired API calls
- Direct HTTP calls outside browser lost session/challenge context
- In-page `fetch()` keeps browser cookies/session/challenge state intact

Key Playwright mechanics used:
- `sync_playwright()` lifecycle
- `browser.new_context(storage_state=...)`
- `context.on("response", ...)` response interception
- resilient selector strategy with multiple Thai label variants
- `page.evaluate(...)` for controlled in-page API fetches
- controlled waits/backoff between attempts

## UI/Endpoint Discovery Iteration History
This process was built iteratively from failure signals and traffic inspection.

Iteration 1: direct profile navigation + passive response capture
- Open profile URL directly and listen for `/api/` responses.
- Result: unstable capture; often missing key profile/financial payloads.

Iteration 2: user-like search flow
- Added homepage search behavior and suggestion click/Enter fallback.
- Result: better app hydration and improved API trigger reliability.

Iteration 3: finance-tab trigger strategy
- Added explicit tab clicks for Thai labels related to financial data.
- Used multiple selector variants to handle UI text differences.
- Result: more finance endpoints fired, but still inconsistent for some runs.

Iteration 4: response parsing hardening
- Added tolerant parsing path: `response.json()` then `response.text()` fallback.
- Result: exposed that many "successful" responses were actually challenge HTML.

Iteration 5: Incapsula detection + normalization
- Added blocked detection for dict markers and raw text HTML signatures.
- Unified via `normalize_captured_payload(...)` in both capture paths.
- Result: blocked data no longer treated as valid API payload.

Iteration 6: in-page fetch fallback
- Added `page.evaluate` fetch loop over known profile/finance endpoints.
- Keeps browser session/auth/challenge context while forcing endpoint calls.
- Result: improved completeness for committees/mergers/financial sections.

Iteration 7: token extraction resilience
- Extract token from `__NUXT__` first; fallback to HTML regex token extraction.
- Result: better decryption success even when runtime object is unavailable.

Iteration 8: retry + backoff + storage state
- Added 3-attempt loop with increasing wait and cookie/session reuse.
- Result: stable `status=ok` runs became repeatable.

Practical debugging loop used during iteration:
1. Run scraper and inspect `debug.status`, `blocked_count`, captured URLs
2. Inspect saved HTML fallback when profile/financial are missing
3. Compare which endpoint families fired vs expected list
4. Add selector variants or fetch fallback URLs
5. Re-run and validate decrypted output (`source_status`, presence of key sections)

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
