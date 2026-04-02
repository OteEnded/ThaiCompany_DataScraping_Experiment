# a_AI_Local_Context.md

## Scope
Process `a` handles AI-powered web search orchestration:
- Build/decide search intent with LLM
- Query Brave Search API when needed
- Generate final answer with SiliconFlow LLM

## Entrypoint
- Script: `a_main.py`
- Run:
  - `python a_AI_Search/a_main.py`
  - `python a_AI_Search/a_main.py --query "หา บริษัท tax id 0105551234567"`

## Inputs
- `config.json` keys:
  - `BRAVE_API_KEY`
  - `SILICONFLOW_API_KEY`
- Optional CLI `--query`

## Outputs
Written to `a_AI_Search/dumps/`:
- `siliconflow_search_query_built_result.json` (decision + built query)
- `last_brave_search_result.json` (raw search result list)
- `final_result.txt` (final LLM response)

## Internal Flow
1. Load config from workspace root (`Path(__file__).resolve().parent.parent / "config.json"`)
2. Call `ask_llm(...)` to decide action (`search_web` vs direct answer)
3. If searching:
   - `web_search(query, count=5)` calls Brave API
   - call LLM again with search results as context
4. Persist all artifacts to `dumps/`

## Key Functions
- `load_config()`
- `web_search(query, count=5)`
- `ask_llm(prompt)`
- `agent(user_input)`

## Known Limitations
- No strict schema validation on model output; fallback path used when parse fails
- No retries/backoff for API calls
- Final response quality depends on external model behavior

## Maintenance Notes
- Keep dump files lightweight and deterministic where possible
- If adding new output artifacts, update `.gitignore` and top-level docs
- If changing prompt format, keep decision JSON contract stable
