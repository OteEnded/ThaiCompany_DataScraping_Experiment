# Temp Prod Runbook (Process F)

## Purpose
This runbook is for manual CI/CD team execution of process F using `f_main.py` with a stable temp-prod config.

## Files used
- Script: `f_main.py`
- Config: `f_local_config.temp_prod.json`
- Outputs: `f_search_result.json`, `result_packed.csv`
- Runtime log: `last_run.log`

## One-time setup
```powershell
pip install requests playwright cryptography
python -m playwright install chromium
```

## Execute (recommended)
Run from workspace root:
```powershell
python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_local_config.temp_prod.json
```

## Success checks
1. `f_search_result.json` has `"status": "ok"` or `"status": "partial"` (with data).
2. `result_packed.csv` exists and has rows.
3. `last_run.log` includes:
   - run summary line
   - API replay page progress
   - final timing summary

## Notes
- This config keeps `force_ui_probe_rows_for_test=false` for real temp-prod behavior.
- If the site is unstable, rerun with same config and warmed `storage_state.json`.
- Keep proof-only script `f_ui_probe_page5_test.py` out of CI/CD runtime path.

## Resume and Progress Checkpoint
- Temp-prod config supports replay continuation:
   - `resume_from_page`
   - `track_progress_in_config`
   - `runtime_progress.last_page_extracted`
- Recommended usage:
   1. First run: keep `resume_from_page=1`.
   2. If interrupted: set `resume_from_page` to last successful page checkpoint and rerun.
   3. For full restart: reset `resume_from_page=1` and clear `runtime_progress.last_page_extracted`.
