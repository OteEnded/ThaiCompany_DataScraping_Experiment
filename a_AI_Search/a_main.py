import argparse
import json
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None


def load_config() -> dict[str, str]:
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


CONFIG = load_config()
BRAVE_API_KEY = CONFIG.get("BRAVE_API_KEY", "")
SILICONFLOW_API_KEY = CONFIG.get("SILICONFLOW_API_KEY", "")
DUMPS_DIR = Path(__file__).with_name("dumps")
DEFAULT_LOCAL_CONFIG_PATH = Path(__file__).with_name("a_local_config.json")


def load_local_run_config(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def dump_json_file(filename: str, payload: Any) -> None:
    DUMPS_DIR.mkdir(exist_ok=True)
    path = DUMPS_DIR / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def dump_text_file(filename: str, content: str) -> None:
    DUMPS_DIR.mkdir(exist_ok=True)
    path = DUMPS_DIR / filename
    with path.open("w", encoding="utf-8") as f:
        f.write(content)


def web_search(query: str, count: int = 5) -> list[dict[str, str]]:
    if requests is None or not BRAVE_API_KEY:
        return []

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"X-Subscription-Token": BRAVE_API_KEY}
    params = {"q": query, "count": count}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
    except Exception:
        return []

    results = []
    for r in data.get("web", {}).get("results", []):
        results.append(
            {
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "url": r.get("url", ""),
            }
        )
    return results


def ask_llm(prompt: str) -> str:
    if requests is None:
        return "Cannot call LLM because 'requests' is not installed. Install it with: pip install requests"

    if not SILICONFLOW_API_KEY:
        return "Cannot call LLM because SILICONFLOW_API_KEY is missing in config.json."

    url = "https://api.siliconflow.com/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": "Qwen/QwQ-32B",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=30)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"LLM request failed: {exc}"


def agent(user_input: str) -> str:
    decision_raw = ask_llm(
        f"""
You are an AI assistant.

User input:
{user_input}

Decide:
- search_web (if need external info)
- answer_directly

Return STRICT JSON:
{{
  "action": "...",
  "query": "..."
}}
"""
    )

    try:
        decision = json.loads(decision_raw)
    except Exception:
        decision = {"action": "search_web", "query": user_input}

    built_query = decision.get("query") or user_input
    if any(char.isdigit() for char in user_input):
        built_query += " เลขนิติบุคคล บริษัท"

    dump_json_file(
        "siliconflow_search_query_built_result.json",
        {
            "user_input": user_input,
            "decision_raw": decision_raw,
            "decision": decision,
            "built_query": built_query,
        },
    )

    if decision.get("action") == "search_web":
        results = web_search(built_query)
        dump_json_file("last_brave_search_result.json", results)

        final = ask_llm(
            f"""
User question: {user_input}

Search results:
{results}

Answer clearly.
If unsure, say you are unsure.
"""
        )
        dump_text_file("final_result.txt", final)
        return final

    dump_json_file("last_brave_search_result.json", [])
    final = ask_llm(user_input)
    dump_text_file("final_result.txt", final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple web+LLM agent via local JSON config")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_LOCAL_CONFIG_PATH),
        help="Path to local run config JSON (default: a_local_config.json)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (Path(__file__).resolve().parent / config_path).resolve()
    run_cfg = load_local_run_config(config_path)

    default_query = str(
        run_cfg.get("default_query", "หาข้อมูล บริษัทที่ tax id 0105551234567")
    ).strip() or "หาข้อมูล บริษัทที่ tax id 0105551234567"
    query_from_config = run_cfg.get("query")
    prompt_if_missing = bool(run_cfg.get("prompt_if_query_missing", True))

    if isinstance(query_from_config, str) and query_from_config.strip():
        user_query = query_from_config.strip()
    elif prompt_if_missing:
        try:
            user_query = input("Enter prompt (leave blank for default): ").strip()
        except EOFError:
            user_query = ""
    else:
        user_query = ""

    final_query = user_query or default_query
    print(agent(final_query))


if __name__ == "__main__":
    main()