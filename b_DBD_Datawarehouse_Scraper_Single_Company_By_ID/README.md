# Process B: DBD Single Company Scraper (By Juristic ID)

## Overview
Process b captures company profile and related datasets from DBD DataWarehouse for one juristic ID.

Core capabilities:
- Browser automation with Playwright.
- API interception for profile/financial and related sections.
- Optional encrypted payload decryption using JWT encKey + HKDF/AES-GCM.
- Anti-bot aware status signaling (ok/partial/blocked).

---

## Folder Contents
- b_main.py: main scraper and decrypt pipeline.
- b_local_config.json: local runtime config.
- b_AI_Local_Context.md: process notes and milestones.
- dbd_result.json: raw captured result.
- dbd_result_decrypted.json: decrypted/normalized result.
- storage_state.json: persisted browser session state.
- datawarehouse.dbd.go.th.har: optional capture artifact.
- dumps/: debug pages/artifacts.

---

## Requirements
Install once in workspace root:

```powershell
pip install playwright cryptography
python -m playwright install chromium
```

Python 3.11+ recommended.

---

## Run
Default run (uses local config):

```powershell
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py
```

Explicit config path:

```powershell
python b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_main.py --config b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/b_local_config.json
```

---

## Config Model
The script reads runtime options from b_local_config.json.

Key fields:
- juristic_id: DBD juristic number to load.
- headless: browser mode.
- storage_state: path to session state JSON.
- no_storage_state: disable loading/saving storage state.

Behavior:
- If no_storage_state is false, process loads and then updates storage_state to preserve a warmed session.
- Relative storage_state paths are resolved from process b folder.

---

## Output Schema
Main output files:
- dbd_result.json: raw captures, debug info, and API payloads.
- dbd_result_decrypted.json: decrypted payloads when encKey is available.

Important debug keys include:
- debug.status: ok | partial | blocked.
- debug.blocked_urls / blocked_count.
- debug.nuxt_token.
- source URLs for intercepted API endpoints.

---

## Anti-Bot / Reliability Notes
The target site may return challenge pages (Imperva/Incapsula).

Mitigations built in:
- Multiple capture attempts.
- Blocked-response detection from payload/text markers.
- HTML token fallback extraction.
- Session reuse via storage_state.

If blocked repeatedly:
- Set headless to false.
- Reuse the same storage state file across reruns.
- Retry later if site behavior is unstable.

---

## Recommended Workflow
1. Set juristic_id in b_local_config.json.
2. Run process b and verify debug.status.
3. Use dbd_result_decrypted.json as downstream input for process c.
4. If blocked/partial, rerun with warmed session and non-headless mode.
