# Process E: Settrade Browser Scraper (REST via Session)

## Overview
Process e uses Playwright browser session to call public Settrade REST endpoints without SDK login.

Captured endpoint groups:
- profile
- info
- overview
- shareholder
- historical-trading
- corporate-action

Financial statement endpoints are typically unavailable in this unauthenticated path.

---

## Folder Contents
- e_main.py: main scraper entrypoint.
- e_local_config.json: local runtime config.
- e_AI_Local_Context.md: process notes and progress.
- probe*.py: exploratory endpoint probes.
- settrade_<SYMBOL>.json: per-symbol raw output.
- settrade_<SYMBOL>.md: per-symbol markdown summary.

---

## Requirements
Install once in workspace root:

```powershell
pip install playwright
python -m playwright install chromium
```

---

## Run
Default run (uses local config):

```powershell
python e_Settrade_Scraper/e_main.py
```

Explicit config path:

```powershell
python e_Settrade_Scraper/e_main.py --config e_Settrade_Scraper/e_local_config.json
```

---

## Config Model
Runtime options are read from e_local_config.json.

Key fields:
- symbol: target stock symbol, e.g. OSP, AOT.
- headless: browser mode.

Behavior:
- Symbol is normalized to uppercase before endpoint calls.
- Output files are generated per symbol.

---

## Output
For symbol OSP, sample outputs are:
- settrade_OSP.json
- settrade_OSP.md

JSON contains endpoint payload sections; unavailable endpoints are set to null.
Markdown summarizes:
- Company profile.
- Latest trading snapshot.
- Overview indicators.
- Major shareholders.
- Corporate actions.
- Historical trading range summary.

---

## Known Caveats
- Data coverage depends on endpoint accessibility at runtime.
- Some payloads may be missing despite HTTP success.
- Unauthenticated flow generally does not expose full financial statements.

---

## Recommended Workflow
1. Set symbol/headless in e_local_config.json.
2. Run process e.
3. Validate endpoint status lines in terminal logs.
4. Review generated settrade_<SYMBOL>.json and .md.
