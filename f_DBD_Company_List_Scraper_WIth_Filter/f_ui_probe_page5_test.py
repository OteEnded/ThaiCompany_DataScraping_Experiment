import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from f_main import BASE_URL
from f_main import DEFAULT_LOCAL_CONFIG_PATH
from f_main import DEFAULT_STORAGE_STATE
from f_main import RunLogger
from f_main import dismiss_startup_overlays
from f_main import extract_company_candidates_from_dom
from f_main import load_local_config
from f_main import ui_probe_navigate_to_page
from f_main import wait_for_table_data


def wait_for_loaded_list_rows(page, timeout_ms: int, logger: RunLogger | None = None, label: str = "page") -> list[dict]:
    deadline = time.perf_counter() + max(1000, int(timeout_ms)) / 1000.0
    poll = 0
    while time.perf_counter() < deadline:
        poll += 1

        # Keep this for diagnostics/readiness side effects, but require real extracted rows to pass.
        wait_for_table_data(
            page,
            timeout_ms=2500,
            logger=logger,
            wait_reason=f"{label}_loaded_rows_wait",
        )

        rows = extract_company_candidates_from_dom(page)
        if rows:
            if logger:
                logger.log(f"{label}: loaded rows confirmed rows={len(rows)} poll={poll}")
            return rows

        if logger and poll % 2 == 0:
            logger.log(f"{label}: still waiting for loaded rows poll={poll}")
        page.wait_for_timeout(700)

    if logger:
        logger.log(f"{label}: loaded rows not confirmed within {timeout_ms} ms")
    return []


def run_ui_page5_probe(config_path: Path, out_path: Path, log_path: Path) -> int:
    logger = RunLogger(log_path)
    config = load_local_config(config_path)

    search_term = str(config.get("search_term") or config.get("query") or "บริษัท").strip() or "บริษัท"
    headless = bool(config.get("headless", False))
    channel = str(config.get("channel", "chromium"))
    results_timeout_seconds = int(config.get("results_timeout_seconds", 180))
    results_timeout_ms = max(10, results_timeout_seconds) * 1000
    settle_seconds = int(config.get("settle_seconds", 8))

    # No-filter proof runner by design.
    logger.log(
        "UI probe page-5 proof started "
        f"query='{search_term}', headless={headless}, channel={channel}, timeout={results_timeout_seconds}s"
    )

    storage_state_path = None
    use_storage_state = bool(config.get("use_storage_state", True))
    if use_storage_state:
        raw_storage_state = str(config.get("storage_state") or str(DEFAULT_STORAGE_STATE)).strip()
        if raw_storage_state:
            storage_state_path = Path(raw_storage_state)
            if not storage_state_path.is_absolute():
                storage_state_path = (config_path.parent / storage_state_path).resolve()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel=channel)
        context_kwargs = {}
        if storage_state_path and storage_state_path.exists():
            context_kwargs["storage_state"] = str(storage_state_path)
            logger.log(f"Using storage_state: {storage_state_path}")
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        logger.log("Opening landing page...")
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        dismiss_startup_overlays(page)
        page.wait_for_timeout(600)

        direct_url = f"{BASE_URL}juristic/searchInfo?keyword={quote(search_term)}"
        logger.log(f"Loading direct results URL: {direct_url}")
        page.goto(direct_url, wait_until="domcontentloaded", timeout=60000)
        dismiss_startup_overlays(page)

        ready = wait_for_table_data(
            page,
            timeout_ms=results_timeout_ms,
            logger=logger,
            wait_reason="ui_probe_page5_initial_wait",
        )
        if not ready:
            logger.log("Initial results table not ready within timeout")

        if settle_seconds > 0:
            page.wait_for_timeout(settle_seconds * 1000)

        page1_rows = wait_for_loaded_list_rows(
            page,
            timeout_ms=results_timeout_ms,
            logger=logger,
            label="page1",
        )
        logger.log(f"Page-1 rows observed: {len(page1_rows)}")

        if not page1_rows:
            logger.log("Aborting page-5 navigation because page-1 list is not loaded with extractable rows")
            result = {
                "status": "partial",
                "run": {
                    "pid": os.getpid(),
                    "config_path": str(config_path),
                    "query": search_term,
                    "target_page": 5,
                    "no_filter_mode": True,
                },
                "evidence": {
                    "page1_rows": 0,
                    "page5_rows": 0,
                    "page5_success": False,
                    "blocked_reason": "page1_not_loaded",
                },
                "companies_page5": [],
            }
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.log(f"Saved probe result JSON: {out_path}")

            if storage_state_path:
                try:
                    context.storage_state(path=str(storage_state_path))
                    logger.log(f"Updated storage_state: {storage_state_path}")
                except Exception as exc:
                    logger.log(f"Failed to update storage_state: {exc}")

            context.close()
            browser.close()
            return 2

        page5_rows = ui_probe_navigate_to_page(
            page,
            target_page=5,
            timeout_ms=results_timeout_ms,
            logger=logger,
        )
        logger.log(f"Page-5 rows observed after UI probe: {len(page5_rows)}")

        result = {
            "status": "ok" if page5_rows else "partial",
            "run": {
                "pid": os.getpid(),
                "config_path": str(config_path),
                "query": search_term,
                "target_page": 5,
                "no_filter_mode": True,
            },
            "evidence": {
                "page1_rows": len(page1_rows),
                "page5_rows": len(page5_rows),
                "page5_success": bool(page5_rows),
            },
            "companies_page5": page5_rows,
        }

        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.log(f"Saved probe result JSON: {out_path}")

        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
                logger.log(f"Updated storage_state: {storage_state_path}")
            except Exception as exc:
                logger.log(f"Failed to update storage_state: {exc}")

        context.close()
        browser.close()

    return 0 if page5_rows else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="No-filter UI probe: jump to page 5 and scrape rows")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_LOCAL_CONFIG_PATH),
        help="Path to JSON config (default: f_local_config.json)",
    )
    parser.add_argument(
        "--out",
        default="tmp_ui_probe_page5_result.json",
        help="Output JSON file path (default: tmp_ui_probe_page5_result.json)",
    )
    parser.add_argument(
        "--log",
        default="tmp_ui_probe_page5_test.log",
        help="Log file path (default: tmp_ui_probe_page5_test.log)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parent / config_path
    config_path = config_path.resolve()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parent / out_path
    out_path = out_path.resolve()

    log_path = Path(args.log)
    if not log_path.is_absolute():
        log_path = Path(__file__).resolve().parent / log_path
    log_path = log_path.resolve()

    code = run_ui_page5_probe(config_path=config_path, out_path=out_path, log_path=log_path)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
