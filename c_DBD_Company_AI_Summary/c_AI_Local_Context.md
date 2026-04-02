# c_AI_Local_Context.md

## Scope
Process `c` reads decrypted DBD output from process `b`, builds compact structured data, and generates a human-readable company + financial summary.

## Entrypoint
- Script: `c_main.py`
- Run:
  - `python c_DBD_Company_AI_Summary/c_main.py`

## Inputs
- Required source file:
  - `b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result_decrypted.json`
- Optional API key for model summary:
  - `SILICONFLOW_API_KEY` (env var or `config.json`)

## Outputs
In process folder:
- `z_compact_data.json` (structured summary payload)
- `z_summary.md` (AI or local fallback narrative)

## Internal Flow
1. Load decrypted source JSON from process `b`
2. Extract normalized profile + financial rows
3. Build:
   - `profile_snapshot`
   - `financial_deep_dive` (`latest_financial`, `yearly_financials`, `submit_history`)
4. Try AI summary via SiliconFlow (`Qwen/QwQ-32B`)
5. If unavailable/fails, produce deterministic local summary text
6. Write compact JSON and markdown summary

## Key Functions
- `extract_summary_fields(data)`
- `_extract_financial_deep_dive(data)`
- `summarize_with_ai(compact_data)`
- `local_human_summary(compact_data)`

## Known Issues / Guardrails
- If source from `b` is blocked/partial, summary can be misleading.
- Recommended improvement: hard fail when `source_status != "ok"` before summarizing.

Suggested guard snippet:
```python
source_status = raw_data.get("source_status")
if source_status and source_status != "ok":
    print(f"ERROR: b output has source_status='{source_status}'. Run b first (non-headless).")
    return
```

## Maintenance Notes
- Keep compact schema stable for downstream usage
- If prompt format changes, ensure local fallback still covers equivalent sections
- Any source-field mapping changes should remain backward compatible where possible
