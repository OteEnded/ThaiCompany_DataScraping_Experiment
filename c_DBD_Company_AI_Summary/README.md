# Process C: DBD Company AI Summary

## Overview
Process c transforms decrypted DBD company data into:
- Compact structured financial snapshot (JSON).
- Human-readable analytical summary (Markdown, Thai-focused).

It can generate summary in two modes:
- AI mode via SiliconFlow API (preferred when API key is available).
- Local fallback mode using deterministic template rendering.

---

## Folder Contents
- c_main.py: compaction + summary generator.
- c_AI_Local_Context.md: process notes and progress.
- z_compact_data.json: extracted compact financial dataset.
- z_summary.md: generated summary output.

---

## Input Dependency
Process c expects decrypted data from process b:
- ../b_DBD_Datawarehouse_Scraper_Single_Company_By_ID/dbd_result_decrypted.json

Run process b first to refresh source data.

---

## Requirements
Install once in workspace root:

```powershell
pip install requests
```

Optional for AI mode:
- SILICONFLOW_API_KEY in root config.json or environment variable.

---

## Run

```powershell
python c_DBD_Company_AI_Summary/c_main.py
```

No local run config file is required for process c in current design.

---

## Data Extraction Model
The compaction step derives:
- profile_snapshot: identity, status, business, latest financial headline values.
- financial_deep_dive.latest_financial: latest detailed yearly row.
- financial_deep_dive.yearly_financials: sorted historical rows.
- financial_deep_dive.submit_history: filing history metadata.

Key metrics surfaced include:
- Revenue, Net Profit, Assets, Equity.
- Debt-to-Equity, Debt-to-Asset, Current Ratio.
- Gross/Operating/Net margins, ROA, ROE.

---

## Output
- z_compact_data.json: machine-friendly analytics payload for reuse.
- z_summary.md: executive-style textual analysis.

Summary structure targets:
1. Company overview.
2. Deep financial analysis with concrete numbers.
3. Key risk points.
4. Practical management/investor perspective.

---

## Known Caveats
- Missing or sparse financial sections in source data reduce analysis depth.
- AI mode depends on external API availability and credentials.
- Fallback summary remains useful but less context-rich than AI mode.

---

## Recommended Workflow
1. Run process b for latest decrypted source.
2. Run process c.
3. Review z_compact_data.json for structured validation.
4. Review z_summary.md for narrative output.
