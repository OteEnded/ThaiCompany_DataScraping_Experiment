import argparse
import base64
import csv
import json
import re
import zlib
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import urljoin
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STORAGE_STATE = BASE_DIR / "storage_state.json"
DEFAULT_LOCAL_CONFIG_PATH = BASE_DIR / "f_local_config.json"
BASE_URL = "https://datawarehouse.dbd.go.th/"
FETCH_ALL_PAGES = -1
PAGE_SIZE = 10
MAX_FETCH_ALL_PAGES = 250000
DEFAULT_RESULTS_TIMEOUT_SECONDS = 90

STATUS_LABEL_TO_CODE = {
    "ยังดำเนินกิจการอยู่": "1",
    "ฟื้นฟู": "A",
    "คืนสู่ทะเบียน": "B",
}

JURISTIC_TYPE_LABEL_TO_CODE = {
    "บริษัทจำกัด": "5",
    "บริษัทมหาชนจำกัด": "7",
}

BUSINESS_SIZE_LABEL_TO_CODE = {
    "ธุรกิจขนาดเล็ก (S)": "S",
    "ธุรกิจขนาดกลาง (M)": "M",
    "ธุรกิจขนาดใหญ่ (L)": "L",
    "S": "S",
    "M": "M",
    "L": "L",
}

PROVINCE_LABEL_TO_CODE = {
    "กรุงเทพมหานคร": "10",
}

PACKED_COLUMNS = [
    "juristic_id",
    "company_name",
    "juristic_type",
    "status",
    "business_type_code",
    "business_type_name",
    "province",
    "registered_capital_baht",
    "total_revenue_baht",
    "net_profit_baht",
    "total_assets_baht",
    "shareholders_equity_baht",
    "profile_url",
]


def safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_") or "page"


def capture_page_dump(page, dumps_dir: Path, tag: str) -> None:
    slug = safe_name(tag)
    try:
        html = page.content()
        (dumps_dir / f"{slug}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


def dismiss_startup_overlays(page) -> None:
    # Cookie consent buttons.
    consent_selectors = [
        "button:has-text('ยอมรับทั้งหมด')",
        "button:has-text('ยอมรับเฉพาะที่จำเป็น')",
    ]
    for selector in consent_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                break
        except Exception:
            continue

    # Warning modal close button.
    warning_close_selectors = [
        "button:has-text('ปิด')",
        "div[role='dialog'] button:has-text('ปิด')",
    ]
    for selector in warning_close_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.click(timeout=2500)
                page.wait_for_timeout(800)
                break
        except Exception:
            continue

    # Generic floating/chat close controls.
    chat_close_selectors = [
        "button[aria-label='Close']",
        "button:has-text('x')",
        "button:has-text('X')",
    ]
    for selector in chat_close_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.click(timeout=1200)
                page.wait_for_timeout(300)
                break
        except Exception:
            continue


def parse_response_body(response):
    try:
        return response.json()
    except Exception:
        pass

    try:
        text = response.text()
    except Exception:
        return None

    if not isinstance(text, str) or not text.strip():
        return None

    try:
        return json.loads(text)
    except Exception:
        return text[:2000]


def extract_request_contract(request) -> dict:
    url = request.url
    method = request.method
    post_data = request.post_data or ""

    parsed = urlsplit(url)
    query = {}
    try:
        query = {k: v for k, v in parse_qs(parsed.query).items()}
    except Exception:
        query = {}

    headers = {}
    try:
        raw_headers = request.headers
        if isinstance(raw_headers, dict):
            for key in ("content-type", "accept", "authorization", "x-requested-with"):
                if key in raw_headers:
                    headers[key] = raw_headers[key]
    except Exception:
        headers = {}

    body = None
    if post_data:
        try:
            body = json.loads(post_data)
        except Exception:
            body = post_data

    return {
        "url": url,
        "path": parsed.path,
        "method": method,
        "query": query,
        "headers": headers,
        "body": body,
    }


def replay_infos_request(page, contract: dict, override_body: dict | None = None) -> dict:
    if not isinstance(contract, dict) or not contract.get("url"):
        return {"ok": False, "error": "missing_contract"}

    url = contract.get("url")
    method = str(contract.get("method") or "GET").upper()
    headers = contract.get("headers") or {}
    body = override_body if override_body is not None else contract.get("body")

    js = """
    async ({ url, method, headers, body }) => {
        const init = {
            method,
            headers: headers || {},
            credentials: 'include'
        };
        if (method !== 'GET' && method !== 'HEAD' && body !== null && body !== undefined) {
            if (typeof body === 'string') {
                init.body = body;
            } else {
                init.body = JSON.stringify(body);
                if (!init.headers['content-type']) {
                    init.headers['content-type'] = 'application/json';
                }
            }
        }

        try {
            const resp = await fetch(url, init);
            const text = await resp.text();
            let data = null;
            try {
                data = JSON.parse(text);
            } catch {
                data = text;
            }
            return {
                ok: resp.ok,
                status: resp.status,
                url,
                data
            };
        } catch (e) {
            return {
                ok: false,
                status: -1,
                url,
                error: String(e),
                data: null
            };
        }
    }
    """

    try:
        out = page.evaluate(js, {"url": url, "method": method, "headers": headers, "body": body})
    except Exception as exc:
        return {"ok": False, "error": f"evaluate_failed: {exc}"}

    data = out.get("data")
    extracted = []
    decrypted_data = None
    decrypted_error = None

    # Attempt decryption for encrypted payload shape {kid,salt,iv,ct}.
    if isinstance(data, dict) and all(k in data for k in ("kid", "salt", "iv", "ct")):
        auth = str((headers or {}).get("authorization") or "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        if token:
            try:
                jwt_payload = decode_jwt(token)
                enc_key = jwt_payload.get("encKey") if isinstance(jwt_payload, dict) else ""
                if isinstance(enc_key, str) and enc_key:
                    decrypted_data = decrypt_payload(enc_key, data, "/api/v1/company-profiles/infos")
                else:
                    decrypted_error = "encKey missing in token"
            except Exception as exc:
                decrypted_error = f"decrypt_exception: {exc}"

    if looks_like_company_list_payload(data):
        extracted = extract_company_candidates_from_payload(data, out.get("url", ""))
    elif looks_like_company_list_payload(decrypted_data):
        extracted = extract_company_candidates_from_payload(decrypted_data, out.get("url", ""))

    return {
        "ok": out.get("ok", False),
        "status": out.get("status", -1),
        "url": out.get("url", ""),
        "error": out.get("error"),
        "data": data,
        "decrypted_data": decrypted_data,
        "decrypted_error": decrypted_error,
        "extracted_companies": extracted,
        "extracted_count": len(extracted),
    }


def b64url_decode(value: str) -> bytes:
    value = value.strip()
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value)


def decode_jwt(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = b64url_decode(parts[1])
        data = json.loads(payload.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def decrypt_payload(enc_key: str, payload: dict, aad_hint: str = ""):
    if not isinstance(payload, dict):
        return payload
    if not all(k in payload for k in ("iv", "ct")):
        return payload
    if not enc_key:
        return payload

    aad_candidates = []
    if aad_hint:
        aad_candidates.append(aad_hint)
        if "?" in aad_hint:
            aad_candidates.append(aad_hint.split("?", 1)[0])
    if not aad_candidates:
        aad_candidates = [""]

    root_key = b64url_decode(enc_key)
    salt = b64url_decode(payload["salt"])
    iv = b64url_decode(payload["iv"])
    ct = b64url_decode(payload["ct"])

    last_exc = None
    for hint in aad_candidates:
        try:
            aad = f"bdw|v{payload['kid']}|{hint}".encode("utf-8")
            hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=aad)
            key = hkdf.derive(root_key)

            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(iv, ct, aad)

            try:
                plain = zlib.decompress(decrypted, 31)
            except Exception:
                try:
                    plain = zlib.decompress(decrypted)
                except Exception:
                    plain = decrypted

            text = plain.decode("utf-8")
            try:
                return json.loads(text)
            except Exception:
                return text
        except Exception as exc:
            last_exc = exc

    return {
        "_decrypt_error": f"{type(last_exc).__name__}: {last_exc}" if last_exc else "Unknown decrypt error",
        "_encrypted": payload,
    }


def looks_like_company_list_payload(data) -> bool:
    if isinstance(data, list):
        if not data:
            return False
        return isinstance(data[0], dict)

    if isinstance(data, dict):
        for key in ("items", "results", "content", "contents", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return True
    return False


def parse_num(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    text = text.replace(",", "").replace(" ", "")
    try:
        if "." in text:
            return float(text)
        return int(text)
    except Exception:
        return None


def to_csv_value(value):
    if value is None:
        return ""
    return value


def has_active_filters(filters: dict | None) -> bool:
    if not isinstance(filters, dict):
        return False
    for value in filters.values():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set, dict)):
            if value:
                return True
            continue
        if str(value).strip():
            return True
    return False


def normalize_code_list(values: list[str] | None, mapping: dict[str, str]) -> list[str]:
    if not values:
        return []

    normalized = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        normalized.append(mapping.get(text, text))
    return normalized


def build_filter_payload(base_body: dict | None, filters: dict | None) -> dict | None:
    if not isinstance(base_body, dict):
        return None

    filters = filters or {}
    payload = dict(base_body)

    province_codes = normalize_code_list(filters.get("province_codes"), PROVINCE_LABEL_TO_CODE)
    status_codes = normalize_code_list(filters.get("status_codes"), STATUS_LABEL_TO_CODE)
    juristic_type_codes = normalize_code_list(filters.get("juristic_type_codes"), JURISTIC_TYPE_LABEL_TO_CODE)
    business_size_codes = normalize_code_list(filters.get("business_size_codes"), BUSINESS_SIZE_LABEL_TO_CODE)

    if province_codes:
        payload["pvCodeList"] = province_codes
    if status_codes:
        payload["jpStatusList"] = status_codes
    if juristic_type_codes:
        payload["jpTypeList"] = juristic_type_codes
    if business_size_codes:
        payload["businessSizeList"] = business_size_codes

    numeric_fields = (
        ("capital_min", "capAmtMin"),
        ("capital_max", "capAmtMax"),
        ("revenue_min", "totalIncomeMin"),
        ("revenue_max", "totalIncomeMax"),
        ("net_profit_min", "netProfitMin"),
        ("net_profit_max", "netProfitMax"),
        ("assets_min", "totalAssetMin"),
        ("assets_max", "totalAssetMax"),
    )
    for source_key, payload_key in numeric_fields:
        if filters.get(source_key) is not None:
            payload[payload_key] = filters[source_key]

    return payload


def default_local_config() -> dict:
    return {
        "search_term": "บริษัท",
        "query": "บริษัท",
        "pages": 5,
        "headless": False,
        "channel": "chrome",
        "settle_seconds": 8,
        "cdp_url": "",
        "results_timeout_seconds": DEFAULT_RESULTS_TIMEOUT_SECONDS,
        "storage_state": str(DEFAULT_STORAGE_STATE),
        "use_storage_state": True,
        "filters": {
            "province_codes": [],
            "status_codes": [],
            "juristic_type_codes": [],
            "business_size_codes": [],
            "capital_min": None,
            "capital_max": None,
            "revenue_min": None,
            "revenue_max": None,
            "net_profit_min": None,
            "net_profit_max": None,
            "assets_min": None,
            "assets_max": None,
        },
    }


def load_local_config(config_path: Path) -> dict:
    if not config_path.exists():
        config = default_local_config()
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config file root must be a JSON object")

    config = default_local_config()
    config.update({k: v for k, v in raw.items() if k != "filters"})
    if isinstance(raw.get("filters"), dict):
        config["filters"].update(raw["filters"])

    pages = int(config.get("pages", 5))
    if pages == 0 or pages < FETCH_ALL_PAGES:
        raise ValueError("config.pages must be a positive integer or -1")
    config["pages"] = pages

    timeout_seconds = int(config.get("results_timeout_seconds", DEFAULT_RESULTS_TIMEOUT_SECONDS))
    config["results_timeout_seconds"] = max(10, timeout_seconds)

    settle_seconds = int(config.get("settle_seconds", 8))
    config["settle_seconds"] = max(0, settle_seconds)

    config["query"] = str(config.get("query", "บริษัท"))
    # Preferred key is search_term; keep query as backward-compatible alias.
    if str(config.get("search_term", "")).strip():
        config["query"] = str(config["search_term"]).strip()
    else:
        config["search_term"] = config["query"]

    config["headless"] = bool(config.get("headless", False))
    config["channel"] = str(config.get("channel", "chrome"))
    config["cdp_url"] = str(config.get("cdp_url", "")).strip()

    if config["channel"] not in ("chromium", "chrome", "msedge"):
        raise ValueError("config.channel must be one of: chromium, chrome, msedge")

    storage_state_raw = str(config.get("storage_state", str(DEFAULT_STORAGE_STATE)))
    storage_state_path = Path(storage_state_raw)
    if not storage_state_path.is_absolute():
        storage_state_path = (BASE_DIR / storage_state_path).resolve()
    config["storage_state"] = str(storage_state_path)
    config["use_storage_state"] = bool(config.get("use_storage_state", True))

    return config


def apply_filters_via_ui(page, filters: dict | None) -> bool:
    if not has_active_filters(filters):
        return False

    filters = filters or {}

    toggle = page.locator('.btn-filter-advanced.toggle-filter-advanced').first
    toggle.wait_for(state='visible', timeout=10000)
    toggle.click(timeout=5000)
    page.wait_for_timeout(1000)

    def choose_multiselect(label_text: str, values: list[str]) -> None:
        if not values:
            return

        heading = page.locator(f'.filter-advanced h5:has-text("{label_text}")').first
        box = heading.locator('xpath=..')
        combo = box.locator('.multiselect').first
        combo.click(timeout=5000)
        page.wait_for_timeout(700)

        for value in values:
            option = page.locator(f'.multiselect__content-wrapper .multiselect__option:has-text("{value}")').first
            option.click(timeout=5000)
            page.wait_for_timeout(250)

        page.keyboard.press('Escape')
        page.wait_for_timeout(350)

    def fill_range(label_text: str, minimum=None, maximum=None) -> None:
        if minimum is None and maximum is None:
            return

        heading = page.locator(f'.filter-advanced h5:has-text("{label_text}")').first
        box = heading.locator('xpath=..')
        inputs = box.locator('input.form-control.numeric')
        if minimum is not None:
            inputs.nth(0).fill(str(minimum))
        if maximum is not None:
            inputs.nth(1).fill(str(maximum))
        page.wait_for_timeout(150)

    choose_multiselect('จังหวัดที่ตั้ง', filters.get('province_codes') or [])
    choose_multiselect('สถานะ', filters.get('status_codes') or [])
    choose_multiselect('ประเภทนิติบุคคล', filters.get('juristic_type_codes') or [])
    choose_multiselect('ขนาดธุรกิจ', filters.get('business_size_codes') or [])

    fill_range('ทุนจดทะเบียน (บาท)', filters.get('capital_min'), filters.get('capital_max'))
    fill_range('รายได้รวม (บาท)', filters.get('revenue_min'), filters.get('revenue_max'))
    fill_range('กำไรสุทธิ (บาท)', filters.get('net_profit_min'), filters.get('net_profit_max'))
    fill_range('สินทรัพย์ (บาท)', filters.get('assets_min'), filters.get('assets_max'))

    page.locator('.filter-advanced .buttons .btn:has-text("ค้นหาข้อมูล")').first.click(timeout=5000)
    try:
        page.wait_for_load_state('networkidle', timeout=10000)
    except Exception:
        pass
    wait_for_table_data(page, timeout_ms=25000)
    page.wait_for_timeout(1500)
    return True


def write_packed_csv(companies: list[dict], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PACKED_COLUMNS)
        writer.writeheader()
        for row in companies:
            writer.writerow({col: to_csv_value(row.get(col)) for col in PACKED_COLUMNS})


def replay_infos_pages(
    page,
    contract: dict,
    pages: int,
    base_delay_ms: int = 900,
    max_retries: int = 2,
) -> tuple[list[dict], list[dict]]:
    if pages == 1:
        return [], []

    body_template = contract.get("body") if isinstance(contract, dict) else None
    if not isinstance(body_template, dict):
        return [], []

    all_rows = []
    stats = []
    fetch_all = pages == FETCH_ALL_PAGES
    final_page = MAX_FETCH_ALL_PAGES if fetch_all else pages

    for page_no in range(2, final_page + 1):
        page_body = dict(body_template)
        page_body["currentPage"] = page_no

        replay = None
        rows = []
        attempt = 0
        while attempt <= max_retries:
            replay = replay_infos_request(page, contract, override_body=page_body)
            replay["replay_page"] = page_no
            rows = replay.get("extracted_companies") or []

            status = int(replay.get("status") or -1)
            if rows or (200 <= status < 300):
                break

            attempt += 1
            page.wait_for_timeout(base_delay_ms + attempt * 700)

        for row in rows:
            row["source_page"] = page_no
        all_rows.extend(rows)

        stats.append(
            {
                "page": page_no,
                "ok": replay.get("ok", False) if replay else False,
                "status": replay.get("status", -1) if replay else -1,
                "rows": len(rows),
                "attempts": attempt + 1,
                "error": (replay.get("error") or replay.get("decrypted_error")) if replay else "no_replay_result",
            }
        )

        # Small stagger helps avoid burst-like request pattern.
        page.wait_for_timeout(base_delay_ms + (page_no % 3) * 250)

        if fetch_all and len(rows) < PAGE_SIZE:
            break

    return all_rows, stats


def extract_company_candidates_from_payload(data, source_url: str) -> list[dict]:
    rows = []

    if isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        for key in ("items", "results", "content", "contents", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                rows = [x for x in value if isinstance(x, dict)]
                if rows:
                    break

    extracted = []
    for row in rows:
        name = (
            row.get("jpName")
            or row.get("name")
            or row.get("companyName")
            or row.get("title")
            or ""
        )
        juristic_id = (
            row.get("jpNo")
            or row.get("juristicId")
            or row.get("id")
            or row.get("regNo")
            or ""
        )
        jp_type_raw = row.get("jpType")
        if isinstance(jp_type_raw, dict):
            jp_type = (
                jp_type_raw.get("jpTypeDesc")
                or jp_type_raw.get("jpTypeAbbr")
                or jp_type_raw.get("jpTypeCode")
                or ""
            )
        else:
            jp_type = jp_type_raw or row.get("jpTypeCode") or "7"

        status = ""
        if isinstance(row.get("jpStatus"), dict):
            status = row.get("jpStatus", {}).get("jpStatDesc") or ""
        if not status:
            status = row.get("jpStatDesc") or row.get("jpStatCode") or ""

        business_code = row.get("submitObjCode") or row.get("setupObjCode") or ""
        business_name = ""
        if isinstance(row.get("submitObjType"), dict):
            business_name = row.get("submitObjType", {}).get("objDesc") or ""
        if not business_name and isinstance(row.get("setupObjType"), dict):
            business_name = row.get("setupObjType", {}).get("objDesc") or ""

        province = ""
        if isinstance(row.get("locationProvince"), dict):
            province = row.get("locationProvince", {}).get("pvDesc") or ""
        if not province:
            province = row.get("pvDesc") or ""

        profile_url = ""
        if isinstance(juristic_id, str) and juristic_id.strip():
            profile_url = f"/company/profile/{juristic_id.strip()}"

        if name or juristic_id:
            extracted.append(
                {
                    "juristic_id": str(juristic_id).strip(),
                    "company_name": str(name).strip(),
                    "juristic_type": str(jp_type).strip(),
                    "status": str(status).strip(),
                    "business_type_code": str(business_code).strip(),
                    "business_type_name": str(business_name).strip(),
                    "province": str(province).strip(),
                    "registered_capital_baht": parse_num(row.get("capAmt")),
                    "total_revenue_baht": parse_num(row.get("totalIncome")),
                    "net_profit_baht": parse_num(row.get("netProfit")),
                    "total_assets_baht": parse_num(row.get("totalAsset")),
                    "shareholders_equity_baht": parse_num(row.get("totalEquity")),
                    # Backward-compatible aliases.
                    "name": str(name).strip(),
                    "jp_type": str(jp_type).strip(),
                    "profile_url": urljoin(BASE_URL, profile_url) if profile_url else "",
                    "source_url": source_url,
                }
            )

    return extracted


def extract_company_candidates_from_dom(page) -> list[dict]:
    links = page.evaluate(
        """
        () => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/company/profile/"]'));
            return anchors.map(a => ({
                text: (a.textContent || '').trim(),
                href: a.getAttribute('href') || ''
            }));
        }
        """
    )

    out = []
    for item in links:
        href = item.get("href", "")
        text = item.get("text", "")
        m = re.search(r"/company/profile/(\d{13})", href)
        juristic_id = m.group(1) if m else ""
        out.append(
            {
                "name": text,
                "juristic_id": juristic_id,
                "jp_type": "7",
                "profile_url": urljoin(BASE_URL, href) if href else "",
                "source_url": page.url,
            }
        )

    # Fallback extraction from table rows when profile anchors are not rendered in cells.
    table_rows = page.evaluate(
        """
        () => {
            const rows = Array.from(document.querySelectorAll('#table-filter-data tbody tr'));
            const out = [];
            for (const tr of rows) {
                const loading = (tr.textContent || '').toLowerCase().includes('loading');
                const tds = Array.from(tr.querySelectorAll('td'));
                if (loading || tds.length < 4) continue;

                const reg = (tds[2]?.textContent || '').trim();
                const name = (tds[3]?.textContent || '').trim();
                const jpType = (tds[4]?.textContent || '').trim();
                const status = (tds[5]?.textContent || '').trim();
                const bizCode = (tds[6]?.textContent || '').trim();
                const bizName = (tds[7]?.textContent || '').trim();
                const province = (tds[8]?.textContent || '').trim();
                const capAmt = (tds[9]?.textContent || '').trim();
                const totalIncome = (tds[10]?.textContent || '').trim();
                const netProfit = (tds[11]?.textContent || '').trim();
                const totalAsset = (tds[12]?.textContent || '').trim();
                const totalEquity = (tds[13]?.textContent || '').trim();

                out.push({
                    reg,
                    name,
                    jpType,
                    status,
                    bizCode,
                    bizName,
                    province,
                    capAmt,
                    totalIncome,
                    netProfit,
                    totalAsset,
                    totalEquity,
                });
            }
            return out;
        }
        """
    )
    for row in table_rows:
        juristic_id = str(row.get("reg") or "").strip()
        name = str(row.get("name") or "").strip()
        jp_type = str(row.get("jpType") or "").strip()
        if not (juristic_id or name):
            continue
        out.append(
            {
                "juristic_id": juristic_id,
                "company_name": name,
                "juristic_type": jp_type,
                "status": str(row.get("status") or "").strip(),
                "business_type_code": str(row.get("bizCode") or "").strip(),
                "business_type_name": str(row.get("bizName") or "").strip(),
                "province": str(row.get("province") or "").strip(),
                "registered_capital_baht": parse_num(row.get("capAmt")),
                "total_revenue_baht": parse_num(row.get("totalIncome")),
                "net_profit_baht": parse_num(row.get("netProfit")),
                "total_assets_baht": parse_num(row.get("totalAsset")),
                "shareholders_equity_baht": parse_num(row.get("totalEquity")),
                # Backward-compatible aliases.
                "name": name,
                "jp_type": jp_type,
                "profile_url": f"https://datawarehouse.dbd.go.th/company/profile/{juristic_id}" if juristic_id else "",
                "source_url": page.url,
            }
        )
    return out


def wait_for_table_data(page, timeout_ms: int = 20000) -> bool:
    try:
        page.wait_for_function(
            """
            () => {
                const filterButton = document.querySelector('.btn-filter-advanced.toggle-filter-advanced');
                if (filterButton && filterButton.offsetParent !== null) {
                    return true;
                }

                const totalNode = document.querySelector('#sTotalElements');
                const totalText = (totalNode?.textContent || '').trim();
                if (totalText) {
                    return true;
                }

                const tbody = document.querySelector('#table-filter-data tbody');
                if (!tbody) return false;
                const rows = Array.from(tbody.querySelectorAll('tr'));
                if (!rows.length) return false;

                for (const r of rows) {
                    const text = (r.textContent || '').toLowerCase();
                    const tdCount = r.querySelectorAll('td').length;
                    if (!text.includes('loading') && tdCount >= 4) {
                        return true;
                    }
                }
                return false;
            }
            """,
            timeout=timeout_ms,
        )
        return True
    except Exception:
        # Keep flow resilient; caller will still dump page and attempt extraction.
        return False


def scrape_company_list(
    query: str,
    pages: int,
    headless: bool,
    storage_state_path: Path | None,
    browser_channel: str,
    settle_seconds: int,
    cdp_url: str,
    results_timeout_seconds: int,
    filters: dict | None = None,
) -> dict:
    result = {
        "query": query,
        "pages_requested": pages,
        "pages_visited": 0,
        "status": "unknown",
        "error": None,
        "companies": [],
        "api_candidates": [],
        "api_hits": [],
        "infos_contract": None,
        "latest_infos_contract": None,
        "infos_replay": None,
        "api_replay_pages_added": 0,
        "filters": filters or {},
        "effective_infos_body": None,
        "debug": {
            "search_url": BASE_URL,
            "storage_state_used": str(storage_state_path) if storage_state_path and storage_state_path.exists() else None,
            "blocked_like_count": 0,
            "next_click_failures": 0,
            "api_replay_page_stats": [],
            "ui_filters_applied": False,
            "results_timeout_seconds": results_timeout_seconds,
        },
    }
    results_timeout_ms = max(10, results_timeout_seconds) * 1000
    dumps_dir = BASE_DIR / "dumps"
    dumps_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        connected_via_cdp = bool(cdp_url)
        if connected_via_cdp:
            browser = p.chromium.connect_over_cdp(cdp_url)
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context(locale="th-TH", timezone_id="Asia/Bangkok")
        else:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
            browser = p.chromium.launch(
                headless=headless,
                channel=browser_channel,
                args=launch_args,
            )
            context_kwargs = {}
            if storage_state_path and storage_state_path.exists():
                context_kwargs["storage_state"] = str(storage_state_path)
            context = browser.new_context(
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                viewport={"width": 1366, "height": 900},
                **context_kwargs,
            )
            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                """
            )
        page = context.new_page()

        def on_response(response):
            url = response.url
            if "/api/" not in url:
                return

            request = response.request
            if "/api/v1/company-profiles/infos" in url:
                current_contract = extract_request_contract(request)
                result["latest_infos_contract"] = current_contract
                if result.get("infos_contract") is None:
                    result["infos_contract"] = current_contract

            body = parse_response_body(response)
            if body is None:
                return

            if isinstance(body, str):
                lowered = body.lower()
                if "incapsula incident id" in lowered or "_incapsula_resource" in lowered:
                    result["debug"]["blocked_like_count"] += 1

            if looks_like_company_list_payload(body):
                candidates = extract_company_candidates_from_payload(body, url)
                if candidates:
                    result["api_candidates"].extend(candidates)

            result["api_hits"].append(
                {
                    "url": url,
                    "status": response.status,
                    "ok": response.ok,
                }
            )

        context.on("response", on_response)

        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        if settle_seconds > 0:
            page.wait_for_timeout(settle_seconds * 1000)
        capture_page_dump(page, dumps_dir, "f_01_landing")
        dismiss_startup_overlays(page)
        page.wait_for_timeout(1500)
        capture_page_dump(page, dumps_dir, "f_01_after_overlay_dismiss")

        # Prefer homepage large search box first, then fallback to header search input.
        search_input = page.locator("form.form-group.search.lg input.form-control").first
        if search_input.count() == 0:
            search_input = page.locator("input[placeholder*='ค้นหาด้วยชื่อหรือเลขทะเบียนนิติบุคคล รหัสประเภทธุรกิจ']").first
        if search_input.count() == 0:
            search_input = page.locator("input[placeholder*='ชื่อหรือเลขทะเบียนนิติบุคคล']").first
        if search_input.count() == 0:
            search_input = page.locator("form#form input.form-control").first
        if search_input.count() == 0:
            search_input = page.locator("input[type='text']").first
        if search_input.count() == 0:
            search_input = page.locator("input").first

        if search_input.count() == 0:
            result["status"] = "blocked_or_unavailable"
            result["error"] = "Cannot find DBD search input"
            capture_page_dump(page, dumps_dir, "f_page_unavailable")
            if storage_state_path:
                try:
                    context.storage_state(path=str(storage_state_path))
                except Exception:
                    pass
            if not connected_via_cdp:
                browser.close()
            result["api_hit_summary"] = {
                "total_hits": len(result["api_hits"]),
                "unique_urls": len({h.get('url') for h in result["api_hits"]}),
            }
            return result

        search_input.click()
        search_input.fill(query)
        page.wait_for_timeout(1000)
        submitted = False
        try:
            search_icon = page.locator("#searchicon").first
            if search_icon.count() == 0:
                search_icon = page.locator("form.form-group.search.lg .icon-search").first
            if search_icon.count() == 0:
                search_icon = page.locator("form#form .icon-search").first
            if search_icon.count() > 0:
                search_icon.click(timeout=3000)
                submitted = True
        except Exception:
            submitted = False

        if not submitted:
            try:
                page.keyboard.press("Enter")
                submitted = True
            except Exception:
                submitted = False

        # Wait for app navigation/update after submit.
        try:
            page.wait_for_load_state("networkidle", timeout=min(results_timeout_ms, 30000))
        except Exception:
            pass

        wait_for_table_data(page, timeout_ms=results_timeout_ms)
        page.wait_for_timeout(2000)
        capture_page_dump(page, dumps_dir, "f_02_after_search")

        # Fallback: direct result URL if submit path did not produce table/API activity.
        initial_probe = extract_company_candidates_from_dom(page)
        if not initial_probe and result.get("infos_contract") is None:
            try:
                direct_url = f"{BASE_URL}juristic/searchInfo?keyword={quote(query)}"
                page.goto(direct_url, wait_until="domcontentloaded", timeout=60000)
                dismiss_startup_overlays(page)
                wait_for_table_data(page, timeout_ms=results_timeout_ms)
                page.wait_for_timeout(1800)
                capture_page_dump(page, dumps_dir, "f_02b_direct_search_fallback")
            except Exception:
                pass

        active_filters = has_active_filters(filters)
        if active_filters:
            try:
                result["debug"]["ui_filters_applied"] = apply_filters_via_ui(page, filters)
                capture_page_dump(page, dumps_dir, "f_03_after_filters")
            except Exception as exc:
                result["debug"]["ui_filters_applied"] = False
                result["debug"]["filter_apply_error"] = str(exc)

        ui_page_limit = 1 if pages == FETCH_ALL_PAGES else pages
        for current_page in range(1, ui_page_limit + 1):
            dom_candidates = extract_company_candidates_from_dom(page)
            result["companies"].extend(dom_candidates)
            result["pages_visited"] = current_page
            capture_page_dump(page, dumps_dir, f"f_page_{current_page:03d}")

            if current_page >= ui_page_limit:
                break

            moved = False
            next_selectors = [
                "li.page-item.next a",
                "a[aria-label='Next']",
                "button:has-text('ถัดไป')",
                "a:has-text('ถัดไป')",
                "a:has-text('Next')",
            ]
            for selector in next_selectors:
                try:
                    loc = page.locator(selector).first
                    if loc.count() > 0:
                        loc.click(timeout=4000)
                        wait_for_table_data(page, timeout_ms=results_timeout_ms)
                        page.wait_for_timeout(1500)
                        capture_page_dump(page, dumps_dir, f"f_page_{current_page:03d}_after_next")
                        moved = True
                        break
                except Exception:
                    continue

            if not moved:
                result["debug"]["next_click_failures"] += 1
                break

        replay_contract_source = result.get("latest_infos_contract") or result.get("infos_contract")
        if replay_contract_source:
            active_filters = has_active_filters(filters)
            effective_body = replay_contract_source.get("body")
            if active_filters and not result["debug"].get("ui_filters_applied"):
                effective_body = build_filter_payload(replay_contract_source.get("body"), filters)
            result["effective_infos_body"] = effective_body
            if active_filters and not result["debug"].get("ui_filters_applied"):
                result["companies"] = []
            result["infos_replay"] = replay_infos_request(page, replay_contract_source, override_body=effective_body)
            if active_filters and result.get("infos_replay", {}).get("extracted_companies"):
                result["api_candidates"].extend(result["infos_replay"]["extracted_companies"])
            replay_contract = dict(replay_contract_source)
            if effective_body is not None:
                replay_contract["body"] = effective_body
            replay_rows, replay_stats = replay_infos_pages(page, replay_contract, pages=max(1, pages))
            result["debug"]["api_replay_page_stats"] = replay_stats
            if replay_rows:
                result["api_candidates"].extend(replay_rows)
                result["api_replay_pages_added"] = len(replay_rows)

        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass

        if not connected_via_cdp:
            browser.close()

    # Deduplicate by juristic_id first, fallback to profile_url.
    uniq = {}
    for item in result["companies"] + result["api_candidates"]:
        key = item.get("juristic_id") or item.get("profile_url") or ""
        if not key:
            continue
        if key not in uniq:
            uniq[key] = item

    result["companies"] = sorted(uniq.values(), key=lambda x: (x.get("juristic_id", ""), x.get("name", "")))
    result["status"] = "ok" if result["companies"] else "partial"

    # Keep api_hits compact for quick analysis.
    hits = result["api_hits"]
    result["api_hit_summary"] = {
        "total_hits": len(hits),
        "unique_urls": len({h.get('url') for h in hits}),
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="DBD company-list explorer via local JSON config")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_LOCAL_CONFIG_PATH),
        help="Path to local run config JSON (default: f_local_config.json)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (BASE_DIR / config_path).resolve()

    try:
        config = load_local_config(config_path)
    except Exception as exc:
        raise SystemExit(f"Invalid config at {config_path}: {exc}") from exc

    storage_state_path = Path(config["storage_state"]) if config.get("use_storage_state", True) else None
    filters = config.get("filters") if isinstance(config.get("filters"), dict) else {}

    data = scrape_company_list(
        query=config["query"],
        pages=config["pages"],
        headless=config["headless"],
        storage_state_path=storage_state_path,
        browser_channel=config["channel"],
        settle_seconds=config["settle_seconds"],
        cdp_url=config["cdp_url"],
        results_timeout_seconds=config["results_timeout_seconds"],
        filters=filters,
    )

    out_path = BASE_DIR / "f_search_result.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    packed_csv_path = BASE_DIR / "result_packed.csv"
    write_packed_csv(data.get("companies", []), packed_csv_path)

    dumps_dir = BASE_DIR / "dumps"
    dumps_dir.mkdir(exist_ok=True)
    (dumps_dir / "f_api_hits.json").write_text(json.dumps(data.get("api_hits", []), ensure_ascii=False, indent=2), encoding="utf-8")
    (dumps_dir / "f_infos_contract.json").write_text(json.dumps(data.get("infos_contract"), ensure_ascii=False, indent=2), encoding="utf-8")
    (dumps_dir / "f_infos_replay_result.json").write_text(json.dumps(data.get("infos_replay"), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved: {out_path}")
    print(f"Saved: {packed_csv_path}")
    print(f"Companies discovered: {len(data.get('companies', []))}")
    print(f"Pages visited: {data.get('pages_visited')}")
    if data.get("infos_contract"):
        print("Captured infos contract: yes")
    if data.get("infos_replay"):
        print(f"Infos replay extracted: {data['infos_replay'].get('extracted_count', 0)}")
    if data.get("api_replay_pages_added", 0) > 0:
        print(f"API replay rows added from next pages: {data['api_replay_pages_added']}")
    if data.get("error"):
        print(f"Run error: {data['error']}")
    if data.get("debug", {}).get("blocked_like_count", 0) > 0:
        print(f"Blocked-like responses: {data['debug']['blocked_like_count']}")


if __name__ == "__main__":
    main()
