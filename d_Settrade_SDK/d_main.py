import json
from datetime import datetime
from pathlib import Path
from typing import Any
import argparse


def load_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config.json must contain a JSON object")
    return data


def validate_settrade_config(cfg: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    settrade_cfg = cfg.get("SETTRADE")
    if not isinstance(settrade_cfg, dict):
        raise ValueError("Missing SETTRADE object in config.json")

    required_keys = ["app_id", "app_secret", "broker_id", "app_code"]
    placeholders = {"", "YOUR_BROKER_ID", "YOUR_APP_CODE", "YOUR_ACCOUNT_NO"}
    missing = []

    for key in required_keys:
        value = str(settrade_cfg.get(key, "")).strip()
        if value in placeholders:
            missing.append(key)

    derivatives_account = str(settrade_cfg.get("derivatives_account_no", "")).strip()
    legacy_account = str(settrade_cfg.get("account_no", "")).strip()
    if derivatives_account in placeholders and legacy_account in placeholders:
        missing.append("derivatives_account_no")

    return settrade_cfg, missing


def build_investor(settrade_cfg: dict[str, Any]):
    from settrade_v2 import Investor

    return Investor(
        app_id=settrade_cfg["app_id"],
        app_secret=settrade_cfg["app_secret"],
        broker_id=settrade_cfg["broker_id"],
        app_code=settrade_cfg["app_code"],
        is_auto_queue=bool(settrade_cfg.get("is_auto_queue", False)),
    )


def retrieve_account_info(investor, settrade_cfg: dict[str, Any]) -> dict[str, Any]:
    derivatives_account_no = (
        str(settrade_cfg.get("derivatives_account_no", "")).strip()
        or str(settrade_cfg.get("account_no", "")).strip()
    )
    deri = investor.Derivatives(account_no=derivatives_account_no)
    return deri.get_account_info()


def retrieve_company_market_data(investor, symbol: str, interval: str, limit: int) -> dict[str, Any]:
    market = investor.MarketData()
    quote = market.get_quote_symbol(symbol)
    candles = market.get_candlestick(symbol=symbol, interval=interval, limit=limit)

    latest_candle = {}
    if isinstance(candles, dict) and candles.get("time"):
        idx = len(candles["time"]) - 1
        ts = candles["time"][idx]
        latest_candle = {
            "time_unix": ts,
            "time_iso": datetime.utcfromtimestamp(ts).isoformat() + "Z",
            "open": candles.get("open", [None])[idx],
            "high": candles.get("high", [None])[idx],
            "low": candles.get("low", [None])[idx],
            "close": candles.get("close", [None])[idx],
            "volume": candles.get("volume", [None])[idx],
            "value": candles.get("value", [None])[idx],
        }

    payload = {
        "source": "settrade_v2",
        "symbol": symbol,
        "retrieved_at": datetime.utcnow().isoformat() + "Z",
        "quote": quote,
        "candlestick": candles,
        "snapshot": {
            "last_price": quote.get("last") if isinstance(quote, dict) else None,
            "change": quote.get("change") if isinstance(quote, dict) else None,
            "percent_change": quote.get("percentChange") if isinstance(quote, dict) else None,
            "pe": quote.get("pe") if isinstance(quote, dict) else None,
            "pbv": quote.get("pbv") if isinstance(quote, dict) else None,
            "eps": quote.get("eps") if isinstance(quote, dict) else None,
            "market_status": quote.get("marketStatus") if isinstance(quote, dict) else None,
            "latest_candle": latest_candle,
        },
    }
    return payload


def save_company_data_files(company_data: dict[str, Any]) -> None:
    base_dir = Path(__file__).resolve().parent
    json_path = base_dir / "settrade_company_data.json"
    md_path = base_dir / "settrade_company_data.md"

    json_path.write_text(json.dumps(company_data, ensure_ascii=False, indent=2), encoding="utf-8")

    quote = company_data.get("quote", {}) if isinstance(company_data, dict) else {}
    snap = company_data.get("snapshot", {}) if isinstance(company_data, dict) else {}
    latest = snap.get("latest_candle", {}) if isinstance(snap, dict) else {}

    lines = [
        f"# Settrade Company Data: {company_data.get('symbol', 'N/A')}",
        "",
        f"- Retrieved At: {company_data.get('retrieved_at', 'N/A')}",
        f"- Instrument Type: {quote.get('instrumentType', 'N/A')}",
        f"- Last Price: {snap.get('last_price', 'N/A')}",
        f"- Change: {snap.get('change', 'N/A')} ({snap.get('percent_change', 'N/A')}%)",
        f"- PE: {snap.get('pe', 'N/A')}",
        f"- PBV: {snap.get('pbv', 'N/A')}",
        f"- EPS: {snap.get('eps', 'N/A')}",
        f"- Market Status: {snap.get('market_status', 'N/A')}",
        "",
        "## Latest Candle",
        f"- Time: {latest.get('time_iso', 'N/A')}",
        f"- Open: {latest.get('open', 'N/A')}",
        f"- High: {latest.get('high', 'N/A')}",
        f"- Low: {latest.get('low', 'N/A')}",
        f"- Close: {latest.get('close', 'N/A')}",
        f"- Volume: {latest.get('volume', 'N/A')}",
        f"- Value: {latest.get('value', 'N/A')}",
        "",
        "## Raw Files",
        "- JSON: s/settrade_company_data.json",
        "- Markdown: s/settrade_company_data.md",
    ]

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")


def main() -> None:
    try:
        from settrade_v2.errors import SettradeError
    except ImportError:
        print("settrade-v2 is not installed.")
        print("Install with: pip install settrade-v2")
        return

    parser = argparse.ArgumentParser(description="Settrade SDK retrieval helper")
    parser.add_argument(
        "--mode",
        choices=["account-info", "company-data", "both"],
        default="company-data",
        help="Choose data to retrieve",
    )
    parser.add_argument("--symbol", default=None, help="SET symbol for company/market data")
    parser.add_argument("--interval", default="1d", help="Candlestick interval (example: 1d, 5m)")
    parser.add_argument("--limit", type=int, default=30, help="Candlestick points to fetch")
    args = parser.parse_args()

    cfg = load_config()
    settrade_cfg, missing = validate_settrade_config(cfg)

    if missing:
        print("Please fill these fields in config.json -> SETTRADE before trying:")
        for field in missing:
            print(f"- {field}")
        return

    investor = build_investor(settrade_cfg)
    symbol = args.symbol or str(settrade_cfg.get("default_symbol", "AOT"))

    try:
        if args.mode in ("account-info", "both"):
            account_info = retrieve_account_info(investor, settrade_cfg)
            print("Account info:")
            print(json.dumps(account_info, ensure_ascii=False, indent=2))

        if args.mode in ("company-data", "both"):
            company_data = retrieve_company_market_data(investor, symbol, args.interval, args.limit)
            print("Company market data:")
            print(json.dumps(company_data.get("snapshot", {}), ensure_ascii=False, indent=2))
            save_company_data_files(company_data)
    except SettradeError as e:
        print("---- error message ----")
        print(e)
        print("---- error code ----")
        print(getattr(e, "code", None))
        print("---- status code ----")
        print(getattr(e, "status_code", None))


if __name__ == "__main__":
    main()
