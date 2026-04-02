# Process A: Web + LLM Agent

## Overview
Process a is a lightweight research agent that combines:
- Brave Web Search API for retrieval.
- SiliconFlow chat completion API for reasoning and answer generation.

The flow:
1. Decide whether to search web or answer directly.
2. Optionally enrich query when a juristic/tax-like number is detected.
3. Summarize final answer with the LLM.
4. Persist debug artifacts for traceability.

---

## Folder Contents
- a_main.py: main process entrypoint.
- a_local_config.json: local runtime config for query behavior.
- a_AI_Local_Context.md: process notes and progress.
- dumps/: debug artifacts from each run.
  - siliconflow_search_query_built_result.json
  - last_brave_search_result.json
  - final_result.txt

---

## Requirements
Install once in workspace root:

```powershell
pip install requests
```

Also ensure root config file exists:
- ../config.json with BRAVE_API_KEY and SILICONFLOW_API_KEY.

---

## Run
Default run (uses local config):

```powershell
python a_AI_Search/a_main.py
```

Explicit config path:

```powershell
python a_AI_Search/a_main.py --config a_AI_Search/a_local_config.json
```

---

## Config Model
The script reads runtime options from a_local_config.json.

Key fields:
- query: fixed query text to run directly. Set null to allow prompt/default behavior.
- prompt_if_query_missing: if true and query is empty, prompt in terminal.
- default_query: fallback when no input/query is supplied.

Notes:
- API keys are not in a_local_config.json; they are read from ../config.json.
- If Brave key is missing, web search returns empty results and the script still attempts LLM response.

---

## Output
Run artifacts are written into dumps/:
- siliconflow_search_query_built_result.json: decision + built query.
- last_brave_search_result.json: retrieved search snippets.
- final_result.txt: final answer text.

---

## Known Caveats
- If requests is not installed, LLM calls cannot run.
- If SILICONFLOW_API_KEY is missing, response will indicate configuration error.
- Decision parsing expects strict JSON from LLM; fallback path forces search_web action.

---

## Recommended Workflow
1. Fill BRAVE_API_KEY and SILICONFLOW_API_KEY in root config.json.
2. Set query/default behavior in a_local_config.json.
3. Run process and inspect dumps/final_result.txt.
4. If response quality is weak, refine query text and rerun.
