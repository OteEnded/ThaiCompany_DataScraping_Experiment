import json
import os
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent


def load_config(path: str = "config.json") -> dict[str, Any]:
    cfg = Path(path)
    if not cfg.exists():
        return {}
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


CONFIG = load_config(str(ROOT_DIR / "config.json"))
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY") or CONFIG.get("SILICONFLOW_API_KEY", "YOUR_TOKEN_HERE")
MODEL = "Qwen/QwQ-32B"


def load_data(path: str = "dbd_result_decrypted.json") -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")
    return data


def _latest_submit(financial: Any) -> dict[str, Any]:
    if not isinstance(financial, list):
        return {}
    rows = [r for r in financial if isinstance(r, dict)]
    if not rows:
        return {}

    def score(row: dict[str, Any]) -> int:
        try:
            return int(row.get("submitYear") or -1)
        except Exception:
            return -1

    return max(rows, key=score)


def _sort_rows_by_year(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def year_of(row: dict[str, Any]) -> int:
        for key in ("fiscalYear", "submitYear"):
            value = row.get(key)
            try:
                return int(value)
            except Exception:
                continue
        return -1

    return sorted(rows, key=year_of)


def _extract_financial_deep_dive(data: dict[str, Any]) -> dict[str, Any]:
    sections = data.get("financial_sections", {})
    if not isinstance(sections, dict):
        sections = {}

    statement_rows: list[dict[str, Any]] = []
    submit_rows: list[dict[str, Any]] = []

    for _, section in sections.items():
        if not isinstance(section, dict):
            continue
        payload = section.get("data")
        if isinstance(payload, dict):
            daily = payload.get("finStatementDailyDtos")
            if isinstance(daily, list):
                statement_rows.extend([r for r in daily if isinstance(r, dict)])
        elif isinstance(payload, list):
            submit_rows.extend([r for r in payload if isinstance(r, dict)])

    statement_rows = _sort_rows_by_year(statement_rows)
    submit_rows = _sort_rows_by_year(submit_rows)

    yearly_financials = []
    for row in statement_rows:
        yearly_financials.append(
            {
                "fiscal_year": row.get("fiscalYear"),
                "revenue": row.get("totalIncome"),
                "net_profit": row.get("netProfit"),
                "assets": row.get("assets") or row.get("totalAsset") or row.get("totalAssets"),
                "equity": row.get("equity") or row.get("totalequity") or row.get("totalEquity"),
                "debt_to_equity": row.get("debtToEquity"),
                "debt_to_asset": row.get("debtToAsset"),
                "current_ratio": row.get("currentRatio"),
                "gross_profit_margin": row.get("grossProfitMargin"),
                "operating_profit_margin": row.get("operatingProfitMargin"),
                "net_profit_margin": row.get("netProfitMargin"),
                "return_on_asset": row.get("returnOnAsset"),
                "return_on_equity": row.get("returnOnEquity"),
            }
        )

    submit_history = []
    for row in submit_rows:
        submit_history.append(
            {
                "submit_year": row.get("submitYear"),
                "submit_date": row.get("submitDate"),
                "auditor_code": row.get("auCode"),
                "status_code": row.get("statusCode"),
            }
        )

    return {
        "latest_financial": yearly_financials[-1] if yearly_financials else {},
        "yearly_financials": yearly_financials,
        "submit_history": submit_history,
    }


def extract_summary_fields(data: dict[str, Any]) -> dict[str, Any]:
    p = data.get("profile", {})
    if not isinstance(p, dict):
        p = {}

    latest_submit = _latest_submit(data.get("financial"))
    deep = _extract_financial_deep_dive(data)

    status = None
    if isinstance(p.get("jpStatus"), dict):
        status = p["jpStatus"].get("jpStatDesc") or p["jpStatus"].get("jpStatCode")
    if not status:
        status = p.get("jpStatCode")

    business = None
    if isinstance(p.get("businessType"), dict):
        business = p["businessType"].get("businessTypeDesc")
    if not business:
        business = p.get("setupObjNameKeyin")

    profile_snapshot = {
        "name_th": p.get("jpName"),
        "name_en": p.get("jpNameE"),
        "juristic_id": p.get("jpNo"),
        "status": status,
        "business": business,
        "fiscal_year": p.get("fiscalYear"),
        "revenue": p.get("totalIncome"),
        "net_profit": p.get("netProfit"),
        "profit_growth_pct": p.get("netProfitPctGrowth"),
        "total_assets": p.get("totalAsset"),
        "equity": p.get("totalEquity"),
        "debt_to_equity": p.get("debtToEquity"),
        "latest_submit_year": latest_submit.get("submitYear"),
        "latest_submit_date": latest_submit.get("submitDate"),
    }

    return {
        "profile_snapshot": profile_snapshot,
        "financial_deep_dive": deep,
    }


def _fmt_num(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
    return str(value)


def local_human_summary(compact_data: dict[str, Any]) -> str:
    profile = compact_data.get("profile_snapshot", {})
    deep = compact_data.get("financial_deep_dive", {})
    latest = deep.get("latest_financial", {}) if isinstance(deep, dict) else {}
    yearly = deep.get("yearly_financials", []) if isinstance(deep, dict) else []

    lines = [
        "Company Overview",
        f"- Name (TH): {profile.get('name_th') or 'N/A'}",
        f"- Name (EN): {profile.get('name_en') or 'N/A'}",
        f"- Juristic ID: {profile.get('juristic_id') or 'N/A'}",
        f"- Status: {profile.get('status') or 'N/A'}",
        f"- Business: {profile.get('business') or 'N/A'}",
        "",
        "Financial Snapshot (Detailed)",
        f"- Fiscal Year: {latest.get('fiscal_year') or profile.get('fiscal_year') or 'N/A'}",
        f"- Revenue: {_fmt_num(latest.get('revenue') or profile.get('revenue'))}",
        f"- Net Profit: {_fmt_num(latest.get('net_profit') or profile.get('net_profit'))}",
        f"- Assets: {_fmt_num(latest.get('assets') or profile.get('total_assets'))}",
        f"- Equity: {_fmt_num(latest.get('equity') or profile.get('equity'))}",
        f"- Debt to Equity: {_fmt_num(latest.get('debt_to_equity') or profile.get('debt_to_equity'))}",
        f"- Debt to Asset: {_fmt_num(latest.get('debt_to_asset'))}",
        f"- Current Ratio: {_fmt_num(latest.get('current_ratio'))}",
        f"- Gross Profit Margin (%): {_fmt_num(latest.get('gross_profit_margin'))}",
        f"- Operating Profit Margin (%): {_fmt_num(latest.get('operating_profit_margin'))}",
        f"- Net Profit Margin (%): {_fmt_num(latest.get('net_profit_margin'))}",
        f"- ROA (%): {_fmt_num(latest.get('return_on_asset'))}",
        f"- ROE (%): {_fmt_num(latest.get('return_on_equity'))}",
        "",
        "Yearly Financial Trend",
    ]

    if yearly:
        for row in yearly:
            lines.append(
                "- "
                f"{row.get('fiscal_year')}: Revenue={_fmt_num(row.get('revenue'))}, "
                f"NetProfit={_fmt_num(row.get('net_profit'))}, "
                f"D/E={_fmt_num(row.get('debt_to_equity'))}, "
                f"ROE={_fmt_num(row.get('return_on_equity'))}%"
            )
    else:
        lines.append("- No detailed yearly financial rows available")

    lines.extend(
        [
            "",
            "Risk Notes",
            "- Evaluate margin trend vs revenue trend for earnings quality.",
            "- Monitor leverage and liquidity ratios for solvency pressure.",
            "- Review filing history consistency and auditor continuity.",
        ]
    )

    return "\n".join(lines)


def summarize_with_ai(compact_data: dict[str, Any]) -> str | None:
    if not SILICONFLOW_API_KEY or SILICONFLOW_API_KEY == "YOUR_TOKEN_HERE":
        return None

    url = "https://api.siliconflow.com/v1/chat/completions"

    prompt = f"""
You are a senior business and financial analyst.

Create a detailed but readable analysis in Thai language.
Focus heavily on financial statement interpretation (งบการเงิน) with concrete numbers.

Data:
{json.dumps(compact_data, ensure_ascii=False, indent=2)}

Output requirements:
1. ภาพรวมบริษัท (สั้น)
2. วิเคราะห์งบการเงินเชิงลึก
- รายได้ กำไร สินทรัพย์ ส่วนของผู้ถือหุ้น
- อัตราส่วนสำคัญ: Net Profit Margin, Debt-to-Equity, Current Ratio, ROA, ROE
- แนวโน้มรายปีจาก yearly_financials (ถ้ามี) โดยชี้ปีที่ดีขึ้น/แย่ลง
3. ความเสี่ยงหลักอย่างน้อย 3 ข้อ (เชื่อมโยงกับตัวเลข)
4. มุมมองเชิงปฏิบัติสำหรับผู้บริหาร/นักลงทุน

Style:
- อ่านง่าย เป็นหัวข้อชัดเจน
- ยึดข้อมูลเป็นหลัก ไม่เดาเกินข้อมูล
- ถ้าค่าไหนไม่มี ให้ระบุว่าไม่มีข้อมูล
"""

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1200,
    }

    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=60)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"API Error: {exc}")
        return None


def main() -> None:
    raw_data = load_data(str(ROOT_DIR / "b_DBD_Datawarehouse_Scraper_Single_Company_By_ID" / "dbd_result_decrypted.json"))
    compact = extract_summary_fields(raw_data)

    print("Compact Data:")
    print(json.dumps(compact, ensure_ascii=False, indent=2))

    print("\nGenerating detailed summary...\n")
    ai_summary = summarize_with_ai(compact)

    if ai_summary:
        final_summary = ai_summary
        print("AI summary generated.")
    else:
        final_summary = local_human_summary(compact)
        print("Using local detailed summary (API unavailable).")

    print("\nRESULT:\n")
    print(final_summary)

    output_path = BASE_DIR / "z_summary.md"
    output_path.write_text(final_summary, encoding="utf-8")
    print(f"\nSaved: {output_path}")

    compact_path = BASE_DIR / "z_compact_data.json"
    compact_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {compact_path}")


if __name__ == "__main__":
    main()
