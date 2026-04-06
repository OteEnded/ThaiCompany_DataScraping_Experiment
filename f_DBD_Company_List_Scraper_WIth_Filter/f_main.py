import argparse
import base64
import csv
import json
import os
import re
import sys
import time
import traceback
import zlib
from datetime import datetime
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
LAST_RUN_LOG_PATH = BASE_DIR / "last_run.log"
LAST_PAGE_ON_PATH = BASE_DIR / "last_page_on.png"
LAST_PAGE_IN_PATH = BASE_DIR / "last_page_in.png"
BASE_URL = "https://datawarehouse.dbd.go.th/"
FETCH_ALL_PAGES = -1
PAGE_SIZE = 10
MAX_FETCH_ALL_PAGES = 250000
DEFAULT_RESULTS_TIMEOUT_SECONDS = 90
DEFAULT_FETCH_ALL_MAX_PAGES = 200
DEFAULT_API_ATTEMPT_TIMEOUT_SECONDS = 120
DEFAULT_STUCK_REFRESH_RETRIES = 4

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
    "กระบี่": "81",
    "กรุงเทพมหานคร": "10",
}

SORT_LABEL_TO_VALUE = {
    "ชื่อนิติบุคคล (ก-ฮ)": "jpName",
    "ประเภทนิติบุคคล (ก-ฮ)": "jpTypeName",
    "ประเภทธุรกิจ (ก-ฮ)": "submitObjCode",
    "จังหวัด (ก-ฮ)": "pvDesc",
    "ทุนจดทะเบียน (มาก-น้อย)": "capAmt",
    "รายได้ (มาก-น้อย)": "totalIncome",
    "กำไรสุทธิ (มาก-น้อย)": "netProfit",
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


class RunLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.run_id = datetime.now().strftime("%H%M%S") + f"-pid{os.getpid()}"
        self.log_path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][run:{self.run_id}] {message}"
        try:
            print(line)
        except UnicodeEncodeError:
            encoded = (line + "\n").encode(sys.stdout.encoding or "utf-8", errors="replace")
            sys.stdout.buffer.write(encoded)
            sys.stdout.flush()
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class IncrementalCSVWriter:
    def __init__(self, out_path: Path, logger: RunLogger | None = None):
        self.out_path = out_path
        self.logger = logger
        self.seen_keys = set()
        self._file = out_path.open("w", encoding="utf-8-sig", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=PACKED_COLUMNS)
        self._writer.writeheader()
        self._file.flush()
        if self.logger:
            self.logger.log(f"Initialized incremental CSV stream: {self.out_path.name}")

    @staticmethod
    def _row_key(row: dict) -> str:
        return str(row.get("juristic_id") or row.get("profile_url") or "").strip()

    def append_rows(self, rows: list[dict], source_label: str = "") -> int:
        appended = 0
        skipped = 0
        for row in rows or []:
            key = self._row_key(row)
            if not key:
                skipped += 1
                continue
            if key in self.seen_keys:
                skipped += 1
                continue
            self.seen_keys.add(key)
            self._writer.writerow({col: to_csv_value(row.get(col)) for col in PACKED_COLUMNS})
            appended += 1

        self._file.flush()
        if self.logger and (appended > 0 or skipped > 0):
            label = source_label or "unknown_source"
            self.logger.log(
                f"CSV stream append [{label}]: appended={appended}, skipped={skipped}, total_unique={len(self.seen_keys)}"
            )
        return appended

    def close(self) -> None:
        try:
            self._file.flush()
            self._file.close()
        except Exception:
            pass


def to_int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def extract_total_pages_hint(payload) -> int | None:
    if isinstance(payload, dict):
        for key in ("totalPages", "totalPage", "pageCount", "pagesCount"):
            hint = to_int_or_none(payload.get(key))
            if hint and hint > 0:
                return hint
        for sub_key in ("data", "result", "payload", "meta"):
            hint = extract_total_pages_hint(payload.get(sub_key))
            if hint:
                return hint
    return None


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_") or "page"


def capture_page_dump(page, dumps_dir: Path, tag: str) -> None:
    slug = safe_name(tag)
    try:
        html = page.content()
        (dumps_dir / f"{slug}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


def capture_waiting_page(page, reason: str, logger: RunLogger | None = None) -> None:
    try:
        page.screenshot(path=str(LAST_PAGE_ON_PATH), full_page=True)
        if logger:
            logger.log(f"Captured waiting page snapshot for '{reason}' -> {LAST_PAGE_ON_PATH.name}")
    except Exception as exc:
        if logger:
            logger.log(f"Failed to capture waiting page snapshot for '{reason}': {exc}")


def capture_ui_nav_page(page, reason: str, logger: RunLogger | None = None) -> None:
    try:
        page.screenshot(path=str(LAST_PAGE_IN_PATH), full_page=True)
        if logger:
            logger.log(f"Captured UI-nav snapshot for '{reason}' -> {LAST_PAGE_IN_PATH.name}")
    except Exception as exc:
        if logger:
            logger.log(f"Failed to capture UI-nav snapshot for '{reason}': {exc}")


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


def replay_infos_request(
    page,
    contract: dict,
    override_body: dict | None = None,
    request_timeout_ms: int = DEFAULT_API_ATTEMPT_TIMEOUT_SECONDS * 1000,
) -> dict:
    if not isinstance(contract, dict) or not contract.get("url"):
        return {"ok": False, "error": "missing_contract"}

    url = contract.get("url")
    method = str(contract.get("method") or "GET").upper()
    headers = contract.get("headers") or {}
    body = override_body if override_body is not None else contract.get("body")

    js = """
    async ({ url, method, headers, body, requestTimeoutMs }) => {
        const init = {
            method,
            headers: headers || {},
            credentials: 'include'
        };
        const timeoutMs = Number(requestTimeoutMs) || 0;
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
            const timeoutPromise = timeoutMs > 0
                ? new Promise((_, reject) => {
                    setTimeout(() => reject(new Error(`request_timeout_${timeoutMs}ms`)), timeoutMs);
                })
                : null;

            const resp = await (
                timeoutPromise
                    ? Promise.race([fetch(url, init), timeoutPromise])
                    : fetch(url, init)
            );

            if (!(resp instanceof Response)) {
                throw new Error('invalid_fetch_response');
            }
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
            const errText = String(e || '');
            const isTimeout = timeoutMs > 0 && errText.includes('request_timeout_');
            return {
                ok: false,
                status: isTimeout ? -2 : -1,
                url,
                error: isTimeout ? `request_timeout_${timeoutMs}ms` : errText,
                data: null
            };
        }
    }
    """

    try:
        out = page.evaluate(
            js,
            {
                "url": url,
                "method": method,
                "headers": headers,
                "body": body,
                "requestTimeoutMs": max(0, int(request_timeout_ms or 0)),
            },
        )
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


def normalize_code_list(values: list[str] | None, mapping: dict[str, str], keep_unmapped: bool = True) -> list[str]:
    if not values:
        return []

    normalized = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        mapped = mapping.get(text)
        if mapped is not None:
            normalized.append(mapped)
        elif keep_unmapped:
            normalized.append(text)
    return normalized


def build_filter_payload(base_body: dict | None, filters: dict | None) -> dict | None:
    if not isinstance(base_body, dict):
        return None

    filters = filters or {}
    payload = dict(base_body)

    province_raw = filters.get("province_codes") or []
    province_codes = normalize_code_list(province_raw, PROVINCE_LABEL_TO_CODE, keep_unmapped=False)
    if province_raw and len(province_codes) < len([str(x).strip() for x in province_raw if str(x).strip()]):
        unknown = [str(x).strip() for x in province_raw if str(x).strip() and str(x).strip() not in PROVINCE_LABEL_TO_CODE]
        raise ValueError(f"Unknown province label(s) for API mapping: {unknown}")
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


def apply_sort_to_payload(body: dict | None, sort_label: str | None) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, None
    label = str(sort_label or "").strip()
    if not label:
        return dict(body), None

    sort_value = SORT_LABEL_TO_VALUE.get(label)
    if not sort_value:
        return dict(body), None

    # pvDesc (province sort) breaks server-side pagination — server returns the same
    # first-province rows across all pages. Use jpName for stable API pagination instead;
    # output will be post-sorted by province after all pages are fetched.
    PAGINATION_STABLE_OVERRIDE = {"pvDesc": "jpName"}
    api_sort_value = PAGINATION_STABLE_OVERRIDE.get(sort_value, sort_value)

    out = dict(body)
    out["sortBy"] = api_sort_value
    return out, sort_value


def body_has_filter_keys(body: dict | None) -> bool:
    if not isinstance(body, dict):
        return False
    filter_keys = {
        "pvCodeList",
        "jpStatusList",
        "jpTypeList",
        "businessSizeList",
        "capAmtMin",
        "capAmtMax",
        "totalIncomeMin",
        "totalIncomeMax",
        "netProfitMin",
        "netProfitMax",
        "totalAssetMin",
        "totalAssetMax",
    }
    return any(k in body for k in filter_keys)


def default_local_config() -> dict:
    return {
        "search_term": "บริษัท",
        "query": "บริษัท",
        "sort_label": "จังหวัด (ก-ฮ)",
        "prefer_direct_search_url": True,
        "pages": 5,
        "headless": False,
        "channel": "chrome",
        "settle_seconds": 8,
        "cdp_url": "",
        "results_timeout_seconds": DEFAULT_RESULTS_TIMEOUT_SECONDS,
        "fetch_all_max_pages": DEFAULT_FETCH_ALL_MAX_PAGES,
        "stuck_refresh_retries": DEFAULT_STUCK_REFRESH_RETRIES,
        "api_replay_attempt_threshold": 2,
        "resume_from_page": 1,
        "track_progress_in_config": True,
        "use_ui_probe_rows_on_api_failure": True,
        "force_ui_probe_rows_for_test": False,
        "runtime_progress": {
            "last_page_extracted": 0,
            "updated_at": "",
        },
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

    fetch_all_max_pages = int(config.get("fetch_all_max_pages", DEFAULT_FETCH_ALL_MAX_PAGES))
    config["fetch_all_max_pages"] = max(2, fetch_all_max_pages)

    stuck_refresh_retries = int(config.get("stuck_refresh_retries", DEFAULT_STUCK_REFRESH_RETRIES))
    config["stuck_refresh_retries"] = max(3, min(5, stuck_refresh_retries))

    api_replay_attempt_threshold = int(config.get("api_replay_attempt_threshold", 2))
    config["api_replay_attempt_threshold"] = max(1, min(5, api_replay_attempt_threshold))

    resume_from_page = int(config.get("resume_from_page", 1))
    config["resume_from_page"] = max(1, resume_from_page)
    config["track_progress_in_config"] = bool(config.get("track_progress_in_config", True))
    if not isinstance(config.get("runtime_progress"), dict):
        config["runtime_progress"] = {"last_page_extracted": 0, "updated_at": ""}

    settle_seconds = int(config.get("settle_seconds", 8))
    config["settle_seconds"] = max(0, settle_seconds)

    config["query"] = str(config.get("query", "บริษัท"))
    # Preferred key is search_term; keep query as backward-compatible alias.
    if str(config.get("search_term", "")).strip():
        config["query"] = str(config["search_term"]).strip()
    else:
        config["search_term"] = config["query"]
    config["sort_label"] = str(config.get("sort_label", "จังหวัด (ก-ฮ)")).strip()
    config["prefer_direct_search_url"] = bool(config.get("prefer_direct_search_url", True))
    config["use_ui_probe_rows_on_api_failure"] = bool(config.get("use_ui_probe_rows_on_api_failure", True))
    config["force_ui_probe_rows_for_test"] = bool(config.get("force_ui_probe_rows_for_test", False))

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


def resolve_config_path(config_arg: str) -> Path:
    config_path = Path(config_arg)
    if config_path.is_absolute():
        return config_path

    # First honor cwd-relative input (natural CLI behavior).
    cwd_candidate = (Path.cwd() / config_path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    # Backward-compatible fallback: resolve relative to this script folder.
    return (BASE_DIR / config_path).resolve()


def persist_last_page_to_config(config_path: Path, last_page: int, logger: RunLogger | None = None) -> None:
    if not isinstance(last_page, int) or last_page < 1:
        return
    try:
        raw = {}
        if config_path.exists():
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        runtime_progress = raw.get("runtime_progress") if isinstance(raw.get("runtime_progress"), dict) else {}
        runtime_progress["last_page_extracted"] = int(last_page)
        runtime_progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
        raw["runtime_progress"] = runtime_progress
        # Convenience mirror for quick manual edits/reads.
        raw["last_page_extracted"] = int(last_page)
        config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        if logger:
            logger.log(f"Failed to persist progress to config: {exc}")


def wait_loader_overlay_clear(
    page,
    timeout_ms: int = 20000,
    logger: RunLogger | None = None,
    wait_reason: str = "loader_overlay",
) -> None:
    try:
        page.wait_for_function(
            """
            () => {
                const overlays = Array.from(document.querySelectorAll('.loader-overlay-full'));
                if (!overlays.length) return true;
                return overlays.every((el) => el.offsetParent === null);
            }
            """,
            timeout=timeout_ms,
        )
    except Exception as exc:
        if logger:
            logger.log(f"Wait timeout for {wait_reason} after {timeout_ms} ms: {exc}")
        capture_waiting_page(page, f"{wait_reason}_timeout", logger=logger)
        # Continue; caller may still succeed even if overlay watcher timed out.
        pass


def wait_filter_toggle_ready(page, timeout_ms: int = 45000, logger: RunLogger | None = None):
    toggle_selectors = [
        '.btn-filter-advanced.toggle-filter-advanced:visible',
        'button:has-text("ตัวกรองข้อมูลเพิ่มเติม"):visible',
        '.btn:has-text("ตัวกรองข้อมูลเพิ่มเติม"):visible',
    ]
    last_error = None

    # Poll readiness because DBD often renders the panel controls late.
    rounds = max(1, timeout_ms // 1500)
    for idx in range(rounds):
        toggle = None
        try:
            for selector in toggle_selectors:
                cand = page.locator(selector).first
                if cand.count() > 0:
                    toggle = cand
                    break

            if toggle is not None:
                wait_loader_overlay_clear(
                    page,
                    timeout_ms=4000,
                    logger=logger,
                    wait_reason="filter_toggle_overlay_clear",
                )
                toggle.wait_for(state='visible', timeout=1200)
                if toggle.is_enabled(timeout=1200):
                    return toggle
        except Exception as exc:
            last_error = exc
        if idx % 8 == 0:
            capture_waiting_page(page, "waiting_filter_toggle_ready", logger=logger)
        page.wait_for_timeout(900)

    capture_waiting_page(page, "filter_toggle_not_ready", logger=logger)
    raise TimeoutError(
        f"Filter panel toggle not ready within {timeout_ms} ms"
        + (f" ({last_error})" if last_error else "")
    )


def wait_filter_form_ready(page, timeout_ms: int = 45000, logger: RunLogger | None = None) -> None:
    required_labels = ["จังหวัดที่ตั้ง", "สถานะ", "ประเภทนิติบุคคล", "ขนาดธุรกิจ"]
    rounds = max(1, timeout_ms // 1200)
    last_state = {}
    for idx in range(rounds):
        wait_loader_overlay_clear(
            page,
            timeout_ms=3500,
            logger=logger,
            wait_reason="filter_form_overlay_clear",
        )
        try:
            state = page.evaluate(
                """
                ({ requiredLabels }) => {
                    const isInViewport = (el) => {
                        if (!el || el.offsetParent === null) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
                    };

                    const panelCandidates = Array.from(document.querySelectorAll('.filter-advanced, .offcanvas, .modal, .drawer, .sidebar'));
                    const panelVisible = panelCandidates.some((el) => el.offsetParent !== null);

                    const allHeadings = Array.from(document.querySelectorAll('h5, h4, .title, .filter-title'));
                    const visibleHeadings = allHeadings.filter((el) => isInViewport(el));
                    const headingTexts = visibleHeadings.map((el) => (el.textContent || '').trim());
                    const matchedLabelCount = requiredLabels.filter((label) =>
                        headingTexts.some((t) => t.includes(label))
                    ).length;

                    const submitCandidates = Array.from(document.querySelectorAll('button, .btn, a.btn'));
                    const submitButton = submitCandidates.find((el) => {
                        const txt = (el.textContent || '').trim();
                        return isInViewport(el) && txt.includes('ค้นหาข้อมูล');
                    }) || null;
                    const submitVisible = !!submitButton;
                    const submitDisabled = submitButton
                        ? !!submitButton.disabled || submitButton.getAttribute('aria-disabled') === 'true'
                        : true;

                    const allMulti = Array.from(document.querySelectorAll('.multiselect, [role="combobox"], .multiselect__select'));
                    const multiselectVisibleCount = allMulti.filter((el) => isInViewport(el)).length;

                    const overlays = Array.from(document.querySelectorAll('.loader-overlay-full'));
                    const activeOverlayCount = overlays.filter((el) => el.offsetParent !== null).length;

                    const hasPanelContainer = panelCandidates.some((el) => {
                        if (el.offsetParent === null) return false;
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 220 || rect.height < 220) return false;
                        return rect.bottom > 0 && rect.top < window.innerHeight;
                    });

                    const ready =
                        matchedLabelCount >= 3 &&
                        submitVisible &&
                        !submitDisabled &&
                        multiselectVisibleCount >= 2;

                    return {
                        ready,
                        panelVisible,
                        hasPanelContainer,
                        headingsCount: headingTexts.length,
                        matchedLabelCount,
                        submitVisible,
                        submitDisabled,
                        multiselectVisibleCount,
                        activeOverlayCount
                    };
                }
                """,
                {"requiredLabels": required_labels},
            )
            if isinstance(state, dict):
                last_state = state
            if isinstance(state, dict) and state.get("ready"):
                return
        except Exception:
            pass

        if idx % 8 == 0:
            if logger and last_state:
                logger.log(f"Still waiting filter form ready. state={json.dumps(last_state, ensure_ascii=False)}")
            capture_waiting_page(page, "waiting_filter_form_ready", logger=logger)
        page.wait_for_timeout(800)

    capture_waiting_page(page, "filter_form_not_ready", logger=logger)
    detail = json.dumps(last_state, ensure_ascii=False) if last_state else "{}"
    raise TimeoutError(f"Filter form not ready within {timeout_ms} ms; last_state={detail}")


def click_with_overlay_retry(
    locator,
    page,
    attempts: int = 5,
    timeout_ms: int = 5000,
    logger: RunLogger | None = None,
    wait_reason: str = "click_with_retry",
) -> None:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            wait_loader_overlay_clear(
                page,
                timeout_ms=4000,
                logger=logger,
                wait_reason=f"{wait_reason}_pre_click",
            )
            try:
                locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            locator.click(timeout=timeout_ms)
            wait_loader_overlay_clear(
                page,
                timeout_ms=5000,
                logger=logger,
                wait_reason=f"{wait_reason}_post_click",
            )
            return
        except Exception as exc:
            last_error = exc
            # Final-attempt fallback for stubborn offscreen elements in scrollable side panels.
            if attempt == attempts:
                try:
                    locator.click(timeout=timeout_ms, force=True)
                    wait_loader_overlay_clear(
                        page,
                        timeout_ms=5000,
                        logger=logger,
                        wait_reason=f"{wait_reason}_post_force_click",
                    )
                    if logger:
                        logger.log(f"Force-click fallback succeeded for {wait_reason}")
                    return
                except Exception as force_exc:
                    last_error = force_exc
            capture_waiting_page(page, f"{wait_reason}_attempt_{attempt}", logger=logger)
            page.wait_for_timeout(min(1800, 300 * attempt))
    raise RuntimeError(f"Click failed after {attempts} attempts: {last_error}")


def apply_filters_via_ui(page, filters: dict | None, logger: RunLogger | None = None) -> bool:
    if not has_active_filters(filters):
        return False

    filters = filters or {}

    if logger:
        logger.log("Waiting for advanced-filter toggle to become ready...")
    toggle = wait_filter_toggle_ready(page, timeout_ms=45000, logger=logger)
    pre_open = False
    try:
        wait_filter_form_ready(page, timeout_ms=3000, logger=None)
        pre_open = True
    except Exception:
        pre_open = False

    if pre_open:
        if logger:
            logger.log("Filter form already open; skip toggle click.")
    else:
        click_with_overlay_retry(
            toggle,
            page,
            attempts=6,
            timeout_ms=5000,
            logger=logger,
            wait_reason="open_filter_panel",
        )
        wait_filter_form_ready(page, timeout_ms=45000, logger=logger)
    page.wait_for_timeout(1000)

    def choose_multiselect(label_text: str, values: list[str]) -> None:
        if not values:
            return

        heading = page.locator(
            f'h5:has-text("{label_text}"):visible, h4:has-text("{label_text}"):visible'
        ).first
        if heading.count() == 0:
            capture_waiting_page(page, f"missing_filter_heading_{safe_name(label_text)}", logger=logger)
            raise RuntimeError(f"Filter heading not found for '{label_text}'")
        try:
            heading.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        box = heading.locator("xpath=ancestor::*[.//*[contains(@class,'multiselect') or @role='combobox']][1]")
        combo = box.locator('.multiselect:visible, [role="combobox"]:visible').first
        if combo.count() == 0:
            combo = page.locator('.multiselect:visible, [role="combobox"]:visible').first
        click_with_overlay_retry(
            combo,
            page,
            attempts=6,
            timeout_ms=5000,
            logger=logger,
            wait_reason=f"open_multiselect_{safe_name(label_text)}",
        )
        # Ensure dropdown is really open before selecting options.
        try:
            expanded = (combo.get_attribute("aria-expanded") or "").strip().lower()
            if expanded != "true":
                arrow = box.locator('.multiselect__select:visible, .multiselect__caret:visible').first
                if arrow.count() > 0:
                    click_with_overlay_retry(
                        arrow,
                        page,
                        attempts=3,
                        timeout_ms=4000,
                        logger=logger,
                        wait_reason=f"open_multiselect_arrow_{safe_name(label_text)}",
                    )
        except Exception:
            pass
        page.wait_for_timeout(700)

        for value in values:
            option = page.locator(
                f'.multiselect__content-wrapper .multiselect__option:has-text("{value}"):visible, '
                f'.multiselect__content-wrapper [role="option"]:has-text("{value}"):visible'
            ).first
            if option.count() > 0:
                click_with_overlay_retry(
                    option,
                    page,
                    attempts=4,
                    timeout_ms=5000,
                    logger=logger,
                    wait_reason=f"select_{safe_name(label_text)}_{safe_name(str(value))}",
                )
            else:
                # Fallback: type into multiselect input and confirm with Enter.
                typed = False
                input_box = box.locator('input.multiselect__input:visible, input[type="text"]:visible').first
                if input_box.count() > 0:
                    try:
                        input_box.fill("")
                    except Exception:
                        pass
                    try:
                        input_box.type(str(value), delay=30)
                        page.wait_for_timeout(500)
                        page.keyboard.press('Enter')
                        typed = True
                    except Exception:
                        typed = False

                if logger and typed:
                    logger.log(f"Selected '{value}' via type+enter fallback under '{label_text}'")
                elif logger and not typed:
                    logger.log(f"Option '{value}' not found for '{label_text}' and type fallback unavailable")
                if not typed:
                    capture_waiting_page(page, f"missing_option_{safe_name(label_text)}_{safe_name(str(value))}", logger=logger)
                    raise RuntimeError(f"Cannot select option '{value}' for '{label_text}'")
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

    submit_btn = page.locator(
        '.filter-advanced .buttons .btn:has-text("ค้นหาข้อมูล"), '
        'button:has-text("ค้นหาข้อมูล"):visible, .btn:has-text("ค้นหาข้อมูล"):visible'
    ).first
    click_with_overlay_retry(
        submit_btn,
        page,
        attempts=6,
        timeout_ms=5000,
        logger=logger,
        wait_reason="submit_filter_form",
    )
    try:
        page.wait_for_load_state('networkidle', timeout=10000)
    except Exception:
        pass
    wait_for_table_data(page, timeout_ms=25000, logger=logger, wait_reason="wait_filtered_result_table")
    page.wait_for_timeout(1500)
    return True


def apply_filters_with_refresh_recovery(
    page,
    filters: dict | None,
    results_timeout_ms: int,
    max_refresh_retries: int,
    logger: RunLogger | None = None,
    dumps_dir: Path | None = None,
) -> bool:
    if not has_active_filters(filters):
        return False

    retries = max(1, int(max_refresh_retries))
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            if logger:
                logger.log(f"Applying advanced filters via UI... attempt {attempt}/{retries}")
            applied = apply_filters_via_ui(page, filters, logger=logger)
            if logger and attempt > 1:
                logger.log(f"Advanced filters recovered after refresh cycle {attempt - 1}.")
            return applied
        except Exception as exc:
            last_error = exc
            if logger:
                logger.log(
                    f"Advanced filter apply attempt {attempt}/{retries} failed: {exc}"
                )
            capture_waiting_page(page, f"filter_apply_failed_attempt_{attempt}", logger=logger)

            if attempt >= retries:
                break

            if logger:
                logger.log(
                    f"Filter loading appears stuck. Refreshing page and retrying ({attempt + 1}/{retries})..."
                )
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                dismiss_startup_overlays(page)
                wait_for_table_data(
                    page,
                    timeout_ms=results_timeout_ms,
                    logger=logger,
                    wait_reason=f"filter_refresh_recovery_wait_{attempt}",
                )
                page.wait_for_timeout(1200)
                if dumps_dir is not None:
                    capture_page_dump(page, dumps_dir, f"f_refresh_recovery_{attempt:02d}")
            except Exception as refresh_exc:
                last_error = RuntimeError(
                    f"Refresh failed during recovery attempt {attempt}/{retries}: {refresh_exc}"
                )
                if logger:
                    logger.log(str(last_error))

    raise RuntimeError(
        f"Advanced filter apply failed after {retries} attempts with refresh recovery exhausted: {last_error}"
    )


def apply_sort_via_ui(page, sort_label: str, logger: RunLogger | None = None) -> bool:
    if not isinstance(sort_label, str) or not sort_label.strip():
        return False

    result = page.evaluate(
        """
        ({ sortLabel }) => {
            const normalize = (t) => (t || '').replace(/\s+/g, ' ').trim();
            const target = normalize(sortLabel);

            const selects = Array.from(document.querySelectorAll('select'))
                .filter((el) => el.offsetParent !== null && el.options && el.options.length > 0);

            for (const sel of selects) {
                const options = Array.from(sel.options || []);
                const idx = options.findIndex((o) => normalize(o.textContent).includes(target));
                if (idx < 0) continue;

                const beforeText = normalize(sel.options[sel.selectedIndex]?.textContent);
                sel.selectedIndex = idx;
                sel.dispatchEvent(new Event('input', { bubbles: true }));
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                const selectedText = normalize(sel.options[sel.selectedIndex]?.textContent);
                const selectedValue = sel.value;
                return { ok: true, beforeText, selectedText, selectedValue };
            }

            return { ok: false, reason: `Sort option not found for label: ${target}` };
        }
        """,
        {"sortLabel": sort_label},
    )

    ok = bool(isinstance(result, dict) and result.get("ok"))
    if logger:
        if ok:
            logger.log(
                f"Sort applied: '{result.get('beforeText')}' -> '{result.get('selectedText')}' (value={result.get('selectedValue')})"
            )
        else:
            logger.log(f"Sort apply skipped/failed: {result.get('reason') if isinstance(result, dict) else 'unknown'}")

    return ok


def write_packed_csv(companies: list[dict], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PACKED_COLUMNS)
        writer.writeheader()
        for row in companies:
            writer.writerow({col: to_csv_value(row.get(col)) for col in PACKED_COLUMNS})


def get_ui_page_signals(page) -> dict:
    try:
        value = page.evaluate(
            """
            () => {
                const parseNum = (txt) => {
                    if (!txt) return null;
                    const m = String(txt).replace(/,/g, '').match(/\d+/);
                    if (!m) return null;
                    const n = Number(m[0]);
                    return Number.isFinite(n) && n > 0 ? n : null;
                };

                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };

                let activePage = null;
                const activeCandidates = [
                    document.querySelector('li.page-item.active a'),
                    document.querySelector('li.page-item.active'),
                    document.querySelector('[aria-current="page"]'),
                    document.querySelector('.pagination .active')
                ].filter(Boolean);
                for (const el of activeCandidates) {
                    const n = parseNum(el.textContent || '');
                    if (n) {
                        activePage = n;
                        break;
                    }
                }

                let rowInferredPage = null;
                let firstRowIndex = null;
                const tr = document.querySelector('#table-filter-data tbody tr');
                if (tr) {
                    const tds = Array.from(tr.querySelectorAll('td'));
                    if (tds.length >= 2) {
                        const idx = parseNum(tds[1]?.textContent || '');
                        if (idx) {
                            firstRowIndex = idx;
                            rowInferredPage = Math.floor((idx - 1) / 10) + 1;
                        }
                    }
                }

                let inputPage = null;
                const inputCandidates = Array.from(
                    document.querySelectorAll(
                        '.pagination input[type="number"], .pagination input[type="text"], ul.nav.pager input.form-control.numeric, .nav.pager input.form-control.numeric, input[aria-label="page"]'
                    )
                )
                    .filter((el) => isVisible(el))
                    .sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                for (const input of inputCandidates) {
                    const n = parseNum(input.value || input.getAttribute('value') || input.textContent || '');
                    if (n) {
                        inputPage = n;
                        break;
                    }
                }

                if (!inputPage) {
                    const allInputs = Array.from(document.querySelectorAll('input[type="number"], input[type="text"]'));
                    for (const input of allInputs) {
                        if (!isVisible(input)) continue;
                        const parentText = String(input.closest('div, span, li, nav')?.textContent || '').replace(/\s+/g, ' ');
                        if (!/หน้า\s*\d*\s*\//i.test(parentText) && !/\b\d+\s*\/\s*[\d,]+\b/.test(parentText)) continue;
                        const n = parseNum(input.value || input.getAttribute('value') || '');
                        if (n) {
                            inputPage = n;
                            break;
                        }
                    }
                }

                let textPage = null;
                const pText = document.querySelector('.pagination')?.textContent || '';
                const m = pText.replace(/\s+/g, ' ').match(/หน้า\s*(\d+)\s*\//i);
                if (m && m[1]) {
                    const n = Number(m[1]);
                    if (Number.isFinite(n) && n > 0) textPage = n;
                }

                // Prefer row-inferred page when available because it reflects actual rendered list rows.
                let resolvedPage = rowInferredPage || activePage || inputPage || textPage || null;

                const sources = [rowInferredPage, activePage, inputPage, textPage].filter((n) => Number.isFinite(n));
                const unique = Array.from(new Set(sources));
                const hasDisagreement = unique.length > 1;

                return {
                    resolvedPage,
                    rowInferredPage,
                    activePage,
                    inputPage,
                    textPage,
                    firstRowIndex,
                    hasDisagreement,
                };
            }
            """
        )
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def get_ui_current_page_number(page) -> int | None:
    signals = get_ui_page_signals(page)
    value = signals.get("resolvedPage") if isinstance(signals, dict) else None
    return int(value) if isinstance(value, int) and value > 0 else None


def get_ui_total_pages_hint(page) -> int | None:
    try:
        value = page.evaluate(
            """
            () => {
                const parseNum = (txt) => {
                    if (!txt) return null;
                    const cleaned = String(txt).replace(/,/g, '').trim();
                    const n = Number(cleaned);
                    return Number.isFinite(n) && n > 0 ? n : null;
                };

                const extractFromText = (txt) => {
                    if (!txt) return null;
                    const compact = String(txt).replace(/\s+/g, ' ');

                    // Example: "หน้า 1 / 3,191"
                    let m = compact.match(/หน้า\s*\d+\s*\/\s*([\d,]+)/i);
                    if (m && m[1]) {
                        const n = parseNum(m[1]);
                        if (n) return n;
                    }

                    // Example fallback: "1 / 3191" in pagination container text.
                    m = compact.match(/\b\d+\s*\/\s*([\d,]{2,})\b/);
                    if (m && m[1]) {
                        const n = parseNum(m[1]);
                        if (n) return n;
                    }
                    return null;
                };

                const candidates = [
                    document.querySelector('.pagination')?.parentElement,
                    document.querySelector('.pagination'),
                    document.querySelector('#table-filter-data')?.parentElement,
                    document.querySelector('#table-filter-data')
                ].filter(Boolean);

                for (const el of candidates) {
                    const n = extractFromText(el.textContent || '');
                    if (n) return n;
                }
                return null;
            }
            """
        )
        if isinstance(value, int) and value > 0:
            return value
    except Exception:
        pass
    return None


def ui_probe_navigate_to_page(
    page,
    target_page: int,
    timeout_ms: int,
    logger: RunLogger | None = None,
    max_hops: int = 20,
) -> list[dict]:
    try:
        target_page = int(target_page)
    except Exception:
        if logger:
            logger.log(f"UI probe fallback skipped: invalid target_page={target_page}")
        return []

    if target_page <= 1:
        if logger:
            logger.log("UI probe fallback: target_page<=1, extracting current DOM rows")
        return extract_company_candidates_from_dom(page)

    current_page = get_ui_current_page_number(page) or 1
    if current_page > target_page:
        if logger:
            logger.log(
                f"UI probe skipped for target page {target_page}: current UI page {current_page} is ahead and cannot rewind safely"
            )
        return []

    if target_page - current_page > max_hops:
        if logger:
            logger.log(
                f"UI probe skipped for target page {target_page}: hop distance {target_page - current_page} exceeds max_hops={max_hops}"
            )
        return []

    if logger:
        logger.log(f"UI probe fallback: navigate current_page={current_page} -> target_page={target_page}")
    capture_ui_nav_page(page, f"ui_probe_start_target_{target_page}", logger=logger)

    def get_row_inferred_page() -> int | None:
        try:
            val = page.evaluate(
                """
                () => {
                    const parseNum = (txt) => {
                        const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                        if (!m) return null;
                        const n = Number(m[0]);
                        return Number.isFinite(n) && n > 0 ? n : null;
                    };
                    const tr = document.querySelector('#table-filter-data tbody tr');
                    if (!tr) return null;
                    const tds = Array.from(tr.querySelectorAll('td'));
                    if (tds.length < 2) return null;
                    const idx = parseNum(tds[1]?.textContent || '');
                    if (!idx) return null;
                    const inferred = Math.floor((idx - 1) / 10) + 1;
                    return Number.isFinite(inferred) && inferred > 0 ? inferred : null;
                }
                """
            )
            return int(val) if isinstance(val, int) and val > 0 else None
        except Exception:
            return None

    def reached_target_page(expected_page: int) -> bool:
        detected = get_ui_current_page_number(page)
        inferred = get_row_inferred_page()
        if inferred is not None:
            return inferred == expected_page
        return bool(detected and detected == expected_page)

    def log_page_signals(prefix: str) -> None:
        if not logger:
            return
        try:
            signals = get_ui_page_signals(page)
            if not isinstance(signals, dict) or not signals:
                return
            if signals.get("hasDisagreement"):
                logger.log(
                    f"{prefix}: page signal disagreement resolved={signals.get('resolvedPage')} "
                    f"row={signals.get('rowInferredPage')} active={signals.get('activePage')} "
                    f"input={signals.get('inputPage')} text={signals.get('textPage')} firstRowIndex={signals.get('firstRowIndex')}"
                )
        except Exception:
            pass

    def get_table_state() -> dict:
        try:
            return page.evaluate(
                """
                () => {
                    const tbody = document.querySelector('#table-filter-data tbody');
                    const rows = tbody ? Array.from(tbody.querySelectorAll('tr')) : [];
                    const loadingRows = rows.filter((r) => (r.textContent || '').toLowerCase().includes('loading')).length;
                    const dataRows = rows.filter((r) => {
                        const txt = (r.textContent || '').toLowerCase();
                        const tdCount = r.querySelectorAll('td').length;
                        return tdCount >= 4 && !txt.includes('loading');
                    }).length;
                    const totalText = (document.querySelector('#sTotalElements')?.textContent || '').trim();
                    const pagerText = (document.querySelector('ul.nav.pager, .nav.pager, .pagination')?.textContent || '').replace(/\s+/g, ' ').trim();
                    return {
                        hasTbody: !!tbody,
                        rowCount: rows.length,
                        loadingRows,
                        dataRows,
                        totalText,
                        pagerText,
                    };
                }
                """
            ) or {}
        except Exception:
            return {}

    def rescue_recommit_target(expected_page: int) -> bool:
        try:
            recommitted = bool(
                page.evaluate(
                    """
                    ({ target }) => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            if (style.visibility === 'hidden' || style.display === 'none') return false;
                            const r = el.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        };

                        const pagerRoots = Array.from(document.querySelectorAll('ul.nav.pager, .nav.pager, .pagination, [class*="pager"]'));
                        for (const root of pagerRoots) {
                            const txt = String(root.textContent || '').replace(/\s+/g, ' ');
                            if (!(/หน้า\s*\/?/i.test(txt) || /\b\d+\s*\/\s*[\d,]+\b/.test(txt))) continue;

                            const input = Array.from(root.querySelectorAll('input[type="number"], input[type="text"]')).find(isVisible);
                            if (input) {
                                input.focus();
                                input.value = String(target);
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true }));
                                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                                input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));

                                const controls = Array.from(root.querySelectorAll('button, a, [role="button"]')).filter(isVisible);
                                const arrow = controls
                                    .map((el) => {
                                        const txt2 = (el.textContent || '').trim().toLowerCase();
                                        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                                        const score = (/next|ถัดไป|>|›|»/.test(txt2) || /next/.test(aria)) ? 10 : 0;
                                        return { el, score };
                                    })
                                    .sort((a, b) => b.score - a.score)[0]?.el;
                                if (arrow) {
                                    arrow.click();
                                }
                                input.blur();
                                return true;
                            }
                        }
                        return false;
                    }
                    """,
                    {"target": expected_page},
                )
            )
            if recommitted:
                wait_for_table_data(
                    page,
                    timeout_ms=5000,
                    logger=logger,
                    wait_reason=f"ui_probe_rescue_recommit_{expected_page}",
                )
                page.wait_for_timeout(700)
            return recommitted
        except Exception:
            return False

    def wait_target_page_rows(expected_page: int, wait_ms: int) -> list[dict]:
        deadline = time.perf_counter() + max(1000, int(wait_ms)) / 1000.0
        retry_wait_ms = 1500
        poll_round = 0
        rescue_count = 0
        saw_target_signal = False
        rollback_count = 0
        while time.perf_counter() < deadline:
            poll_round += 1
            signals = get_ui_page_signals(page)
            detected = signals.get("resolvedPage") if isinstance(signals, dict) else None
            signal_candidates = []
            if isinstance(signals, dict):
                for key in ("rowInferredPage", "activePage", "inputPage", "textPage"):
                    val = signals.get(key)
                    if isinstance(val, int) and val > 0:
                        signal_candidates.append(val)
            has_target_signal = expected_page in signal_candidates
            if has_target_signal:
                saw_target_signal = True

            if poll_round % 2 == 0:
                log_page_signals(f"UI probe fallback poll={poll_round} expected={expected_page}")

            # DBD often shows target page briefly, then rolls back to previous page while table is still loading.
            # Detect that rollback and actively recommit target instead of waiting passively.
            if saw_target_signal and detected and detected != expected_page:
                rollback_count += 1
                if logger:
                    state = get_table_state()
                    logger.log(
                        "UI probe fallback: target-page rollback detected "
                        f"expected={expected_page} detected={detected} rollback_count={rollback_count} "
                        f"state={json.dumps(state, ensure_ascii=False)}"
                    )
                if rescue_count < 3:
                    rescue_count += 1
                    recommitted = rescue_recommit_target(expected_page)
                    if logger:
                        logger.log(
                            f"UI probe fallback: rollback rescue recommit target {expected_page} "
                            f"attempt={rescue_count}/3 success={recommitted}"
                        )
                if rollback_count >= 6:
                    if logger:
                        logger.log(
                            f"UI probe fallback: repeated rollback while targeting page {expected_page}; aborting delayed-wait loop"
                        )
                    capture_ui_nav_page(page, f"ui_probe_rollback_abort_{expected_page}", logger=logger)
                    return []
                page.wait_for_timeout(retry_wait_ms)
                continue

            if detected == expected_page:
                rows = extract_company_candidates_from_dom(page)
                if rows:
                    inferred = get_row_inferred_page()
                    if inferred is not None and inferred != expected_page:
                        if logger:
                            logger.log(
                                f"UI probe fallback: page mismatch detected after nav expected={expected_page} inferred_from_rows={inferred}; waiting/retrying"
                            )
                        page.wait_for_timeout(retry_wait_ms)
                        continue
                    if logger:
                        logger.log(
                            f"UI probe fallback: confirmed page {expected_page} with rows={len(rows)} after delayed-load wait"
                        )
                    return rows
                # Give table time to render when page number has changed but rows are still blank.
                wait_for_table_data(
                    page,
                    timeout_ms=2500,
                    logger=logger,
                    wait_reason=f"ui_probe_delayed_table_{expected_page}",
                )
                if logger and poll_round % 2 == 0:
                    state = get_table_state()
                    logger.log(
                        "UI probe fallback: target page reached but rows empty "
                        f"poll={poll_round} state={json.dumps(state, ensure_ascii=False)}"
                    )
                if poll_round % 3 == 0 and rescue_count < 3:
                    rescue_count += 1
                    recommitted = rescue_recommit_target(expected_page)
                    if logger:
                        logger.log(
                            f"UI probe fallback: rescue recommit target page {expected_page} "
                            f"attempt={rescue_count}/3 success={recommitted}"
                        )

            if poll_round % 4 == 0:
                capture_ui_nav_page(page, f"ui_probe_wait_rows_{expected_page}", logger=logger)
            page.wait_for_timeout(retry_wait_ms)

        if logger:
            logger.log(
                f"UI probe fallback: page {expected_page} reached but rows did not load within {wait_ms} ms"
            )
        capture_ui_nav_page(page, f"ui_probe_wait_rows_timeout_{expected_page}", logger=logger)
        return []

    # Try generic Thai paginator input jump ("หน้า [input] / total") without relying on .pagination class.
    try:
        jumped_generic = page.evaluate(
            """
            ({ target }) => {
                const parseNum = (txt) => {
                    const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                    if (!m) return null;
                    const n = Number(m[0]);
                    return Number.isFinite(n) && n > 0 ? n : null;
                };
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };

                const hasPaginatorHintInAncestors = (input) => {
                    const pager = input.closest('ul.nav.pager, .nav.pager, .pagination, [class*="pager"]');
                    if (!pager) return false;
                    const txt = String(pager.textContent || '').replace(/\s+/g, ' ').trim();
                    const hasPagerText = /หน้า\s*\/?/i.test(txt) || /\b\d+\s*\/\s*[\d,]+\b/.test(txt);
                    if (!hasPagerText) return false;
                    const inputCount = pager.querySelectorAll('input[type="number"], input[type="text"]').length;
                    return inputCount > 0 && inputCount <= 2;
                };

                const inputs = Array.from(document.querySelectorAll('input[type="number"], input[type="text"]')).filter(isVisible);
                for (const input of inputs) {
                    if (!hasPaginatorHintInAncestors(input)) {
                        continue;
                    }
                    input.focus();
                    input.value = String(target);
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
                    input.blur();
                    return true;
                }
                return false;
            }
            """,
            {"target": target_page},
        )
        if jumped_generic:
            if logger:
                logger.log("UI probe fallback: trying generic Thai paginator input jump")
            try:
                page.wait_for_function(
                    """
                    ({ target }) => {
                        const parseNum = (txt) => {
                            const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                            if (!m) return null;
                            const n = Number(m[0]);
                            return Number.isFinite(n) && n > 0 ? n : null;
                        };
                        const hasPaginatorHintInAncestors = (input) => {
                            const pager = input.closest('ul.nav.pager, .nav.pager, .pagination, [class*="pager"]');
                            if (!pager) return false;
                            const txt = String(pager.textContent || '').replace(/\s+/g, ' ').trim();
                            const hasPagerText = /หน้า\s*\/?/i.test(txt) || /\b\d+\s*\/\s*[\d,]+\b/.test(txt);
                            if (!hasPagerText) return false;
                            const inputCount = pager.querySelectorAll('input[type="number"], input[type="text"]').length;
                            return inputCount > 0 && inputCount <= 2;
                        };

                        const inputs = Array.from(document.querySelectorAll('input[type="number"], input[type="text"]'));
                        for (const input of inputs) {
                            if (!hasPaginatorHintInAncestors(input)) {
                                continue;
                            }
                            const n = parseNum(input.value || input.getAttribute('value') || '');
                            if (n === target) return true;
                        }
                        const active = document.querySelector('li.page-item.active, [aria-current="page"], .pagination .active');
                        const fromActive = active ? parseNum(active.textContent || '') : null;
                        return fromActive === target;
                    }
                    """,
                    arg={"target": target_page},
                    timeout=min(timeout_ms, 12000),
                )
                wait_for_table_data(
                    page,
                    timeout_ms=min(timeout_ms, 12000),
                    logger=logger,
                    wait_reason=f"ui_probe_input_generic_{target_page}",
                )
                page.wait_for_timeout(600)
                if not reached_target_page(target_page):
                    capture_ui_nav_page(page, f"ui_probe_generic_not_reached_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: generic jump did not confirm active page {target_page}"
                        )
                    raise RuntimeError("generic_jump_not_confirmed")
                rows = wait_target_page_rows(target_page, min(timeout_ms, 25000))
                if rows:
                    capture_ui_nav_page(page, f"ui_probe_generic_success_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: generic Thai paginator input jump succeeded for page {target_page} rows={len(rows)}"
                        )
                    return rows
            except Exception:
                if logger:
                    logger.log("UI probe fallback: generic Thai paginator input jump did not reach target page")
    except Exception:
        pass

    # Try Playwright-driven paginator input jump first (more reliable than JS-only event dispatch).
    input_jump_selectors = [
        "ul.nav.pager input.form-control.numeric",
        ".nav.pager input.form-control.numeric",
        ".pagination input[type='number']",
        ".pagination input[type='text']",
    ]
    for input_selector in input_jump_selectors:
        try:
            input_loc = page.locator(input_selector).first
            if input_loc.count() == 0:
                continue

            # Safety: only use inputs inside paginator-like text ("หน้า ... / ...").
            in_paginator = False
            try:
                in_paginator = bool(
                    input_loc.evaluate(
                        """
                        (input) => {
                            const pager = input.closest('ul.nav.pager, .nav.pager, .pagination, [class*="pager"]');
                            if (!pager) return false;
                            const txt = String(pager.textContent || '').replace(/\s+/g, ' ');
                            if (!(/หน้า\s*\/?/i.test(txt) || /\b\d+\s*\/\s*[\d,]+\b/.test(txt))) return false;
                            const inputCount = pager.querySelectorAll('input[type="number"], input[type="text"]').length;
                            return inputCount > 0 && inputCount <= 2;
                        }
                        """
                    )
                )
            except Exception:
                in_paginator = False
            if not in_paginator:
                continue

            if logger:
                logger.log(f"UI probe fallback: trying paginator input jump via '{input_selector}'")

            input_loc.click(timeout=4000)
            input_loc.fill(str(target_page), timeout=4000)
            input_loc.press("Enter", timeout=4000)

            # If Enter doesn't trigger page change on this UI, click only a LOCAL arrow in the same paginator area.
            try:
                clicked_local_arrow = bool(
                    input_loc.evaluate(
                        """
                        (input) => {
                            const isVisible = (el) => {
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                if (style.visibility === 'hidden' || style.display === 'none') return false;
                                const r = el.getBoundingClientRect();
                                return r.width > 0 && r.height > 0;
                            };

                            let root = input.closest('ul.nav.pager, .nav.pager, .pagination, [class*="pager"]');
                            if (!root) return false;

                            const controls = Array.from(root.querySelectorAll('button, a, [role="button"]')).filter(isVisible);
                            if (!controls.length) return false;
                            const scored = controls
                                .map((el) => {
                                    const txt = (el.textContent || '').trim();
                                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                                    const hasNumber = /\d+/.test(txt);
                                    const looksNext = /next|ถัดไป|›|»|>/.test(txt.toLowerCase()) || /next/.test(aria);
                                    let score = 0;
                                    if (looksNext) score += 100;
                                    if (!hasNumber) score += 20;
                                    return { el, score };
                                })
                                .sort((a, b) => b.score - a.score);
                            const target = scored[0]?.el;
                            if (!target) return false;
                            target.click();
                            return true;
                        }
                        """
                    )
                )
                if clicked_local_arrow and logger:
                    logger.log("UI probe fallback: clicked local paginator arrow after input")
            except Exception:
                pass

            try:
                page.wait_for_function(
                    """
                    ({ target }) => {
                        const parseNum = (txt) => {
                            const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                            if (!m) return null;
                            const n = Number(m[0]);
                            return Number.isFinite(n) && n > 0 ? n : null;
                        };
                        const isPageInput = (input) => {
                            if (!input) return false;
                            const pager = input.closest('ul.nav.pager, .nav.pager, .pagination, [class*="pager"]');
                            if (!pager) return false;
                            const txt = String(pager.textContent || '').replace(/\s+/g, ' ').trim();
                            const hasPagerText = /หน้า\s*\/?/i.test(txt) || /\b\d+\s*\/\s*[\d,]+\b/.test(txt);
                            if (!hasPagerText) return false;
                            const inputCount = pager.querySelectorAll('input[type="number"], input[type="text"]').length;
                            return inputCount > 0 && inputCount <= 2;
                        };
                        const inputs = Array.from(document.querySelectorAll('input[type="number"], input[type="text"]'));
                        for (const input of inputs) {
                            if (!isPageInput(input)) continue;
                            const fromInput = parseNum(input.value || input.getAttribute('value') || '');
                            if (fromInput === target) return true;
                        }
                        const active = document.querySelector('li.page-item.active, [aria-current="page"], .pagination .active');
                        const fromActive = active ? parseNum(active.textContent || '') : null;
                        return fromActive === target;
                    }
                    """,
                    arg={"target": target_page},
                    timeout=min(timeout_ms, 15000),
                )
                wait_for_table_data(
                    page,
                    timeout_ms=min(timeout_ms, 20000),
                    logger=logger,
                    wait_reason=f"ui_probe_input_playwright_{target_page}",
                )
                page.wait_for_timeout(800)
                if not reached_target_page(target_page):
                    capture_ui_nav_page(page, f"ui_probe_playwright_not_reached_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: Playwright jump did not confirm active page {target_page}"
                        )
                    raise RuntimeError("playwright_jump_not_confirmed")
                rows = wait_target_page_rows(target_page, min(timeout_ms, 25000))
                if rows:
                    capture_ui_nav_page(page, f"ui_probe_playwright_success_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: Playwright paginator input jump succeeded for page {target_page} rows={len(rows)}"
                        )
                    return rows
            except Exception:
                if logger:
                    logger.log("UI probe fallback: Playwright paginator input jump did not reach target page")
        except Exception:
            continue

    # Try paginator input jump first (UI shape: "หน้า [input] / total").
    try:
        jumped = page.evaluate(
            """
            ({ target }) => {
                const input = document.querySelector('.pagination input[type="number"], .pagination input[type="text"]');
                if (!input) return false;
                const targetText = String(target);
                input.focus();
                input.value = targetText;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
                input.blur();
                return true;
            }
            """,
            {"target": target_page},
        )
        if jumped:
            if logger:
                logger.log("UI probe fallback: trying paginator input jump")
            try:
                page.wait_for_function(
                    """
                    ({ target }) => {
                        const parseNum = (txt) => {
                            const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                            if (!m) return null;
                            const n = Number(m[0]);
                            return Number.isFinite(n) && n > 0 ? n : null;
                        };
                        const input = document.querySelector('.pagination input[type="number"], .pagination input[type="text"]');
                        const fromInput = input ? parseNum(input.value || input.getAttribute('value') || '') : null;
                        if (fromInput === target) return true;
                        const active = document.querySelector('li.page-item.active, [aria-current="page"], .pagination .active');
                        const fromActive = active ? parseNum(active.textContent || '') : null;
                        return fromActive === target;
                    }
                    """,
                    arg={"target": target_page},
                    timeout=min(timeout_ms, 15000),
                )
                wait_for_table_data(
                    page,
                    timeout_ms=min(timeout_ms, 20000),
                    logger=logger,
                    wait_reason=f"ui_probe_input_jump_{target_page}",
                )
                page.wait_for_timeout(1200)
                if not reached_target_page(target_page):
                    capture_ui_nav_page(page, f"ui_probe_input_not_reached_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: input jump did not confirm active page {target_page}"
                        )
                    raise RuntimeError("input_jump_not_confirmed")
                rows = wait_target_page_rows(target_page, min(timeout_ms, 25000))
                if rows:
                    capture_ui_nav_page(page, f"ui_probe_input_success_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: paginator input jump succeeded for page {target_page} rows={len(rows)}"
                        )
                    return rows
            except Exception:
                if logger:
                    logger.log("UI probe fallback: paginator input jump did not reach target page")
    except Exception:
        pass

    # Try direct numeric page button first.
    numeric_selectors = [
        f"li.page-item a:has-text('{target_page}')",
        f"a.page-link:has-text('{target_page}')",
        f"[aria-current='page']:has-text('{target_page}')",
    ]
    for selector in numeric_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                if logger:
                    logger.log(f"UI probe fallback: clicking numeric selector '{selector}'")
                loc.click(timeout=4000)
                page.wait_for_function(
                    """
                    ({ target }) => {
                        const parseNum = (txt) => {
                            const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                            if (!m) return null;
                            const n = Number(m[0]);
                            return Number.isFinite(n) && n > 0 ? n : null;
                        };
                        const input = document.querySelector('.pagination input[type="number"], .pagination input[type="text"]');
                        const fromInput = input ? parseNum(input.value || input.getAttribute('value') || '') : null;
                        if (fromInput === target) return true;
                        const active = document.querySelector('li.page-item.active, [aria-current="page"], .pagination .active');
                        const fromActive = active ? parseNum(active.textContent || '') : null;
                        return fromActive === target;
                    }
                    """,
                    arg={"target": target_page},
                    timeout=min(timeout_ms, 15000),
                )
                wait_for_table_data(
                    page,
                    timeout_ms=min(timeout_ms, 20000),
                    logger=logger,
                    wait_reason=f"ui_probe_page_{target_page}",
                )
                page.wait_for_timeout(1200)
                if not reached_target_page(target_page):
                    capture_ui_nav_page(page, f"ui_probe_numeric_not_reached_{target_page}", logger=logger)
                    if logger:
                        logger.log(
                            f"UI probe fallback: numeric click did not confirm active page {target_page}"
                        )
                    raise RuntimeError("numeric_jump_not_confirmed")
                rows = wait_target_page_rows(target_page, min(timeout_ms, 25000))
                if rows:
                    capture_ui_nav_page(page, f"ui_probe_numeric_success_{target_page}", logger=logger)
                return rows
        except Exception:
            continue

    # Fallback: advance by clicking next.
    next_selectors = [
        "li.page-item.next a",
        "a[aria-label='Next']",
        "button[aria-label='Next']",
        "button[aria-label='next']",
        "a[rel='next']",
        ".pagination button:has-text('>')",
        ".pagination a:has-text('>')",
        ".pagination button:last-of-type",
        ".pagination li:last-child a",
        "button:has-text('ถัดไป')",
        "a:has-text('ถัดไป')",
        "a:has-text('Next')",
    ]
    hops = 0
    while current_page < target_page and hops < max_hops:
        moved = False
        for selector in next_selectors:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    if logger:
                        logger.log(f"UI probe fallback: clicking next selector '{selector}' (hop {hops + 1})")
                    loc.click(timeout=4000)
                    prev_page = current_page
                    try:
                        page.wait_for_function(
                            """
                            ({ prev }) => {
                                const parseNum = (txt) => {
                                    const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                                    if (!m) return null;
                                    const n = Number(m[0]);
                                    return Number.isFinite(n) && n > 0 ? n : null;
                                };
                                const input = document.querySelector('.pagination input[type="number"], .pagination input[type="text"]');
                                const fromInput = input ? parseNum(input.value || input.getAttribute('value') || '') : null;
                                if (fromInput && fromInput > prev) return true;
                                const active = document.querySelector('li.page-item.active, [aria-current="page"], .pagination .active');
                                const fromActive = active ? parseNum(active.textContent || '') : null;
                                return !!(fromActive && fromActive > prev);
                            }
                            """,
                            arg={"prev": prev_page},
                            timeout=min(timeout_ms, 15000),
                        )
                    except Exception:
                        if logger:
                            logger.log(
                                f"UI probe fallback: next click did not advance page within timeout (selector='{selector}')"
                            )
                    wait_for_table_data(
                        page,
                        timeout_ms=min(timeout_ms, 20000),
                        logger=logger,
                        wait_reason=f"ui_probe_next_to_{target_page}",
                    )
                    page.wait_for_timeout(1000)
                    post_page = get_ui_current_page_number(page) or get_row_inferred_page()
                    if post_page and post_page > prev_page:
                        moved = True
                    else:
                        if logger:
                            logger.log(
                                f"UI probe fallback: next selector click produced no page advance (prev={prev_page}, now={post_page})"
                            )
                    break
            except Exception:
                continue

        if not moved:
            try:
                clicked_rightmost = page.evaluate(
                    """
                    () => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            if (style.visibility === 'hidden' || style.display === 'none') return false;
                            const r = el.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        };

                        const hasPaginatorText = (el) => {
                            const txt = String(el?.textContent || '').replace(/\s+/g, ' ');
                            return /หน้า\s*\d*\s*\//i.test(txt) || /\b\d+\s*\/\s*[\d,]+\b/.test(txt);
                        };

                        const roots = [
                            document.querySelector('.pagination')?.parentElement,
                            document.querySelector('.pagination'),
                            ...Array.from(document.querySelectorAll('div, nav, section, li')).filter((el) => hasPaginatorText(el)),
                        ].filter(Boolean);
                        if (!roots.length) return false;

                        const root = roots.find((r) => hasPaginatorText(r)) || roots[0];
                        const controls = Array.from(root.querySelectorAll('button, a, [role="button"]')).filter(isVisible);
                        if (!controls.length) return false;

                        const scored = controls
                            .map((el) => {
                                const txt = (el.textContent || '').trim();
                                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                                const r = el.getBoundingClientRect();
                                const hasNumber = /\d+/.test(txt);
                                const looksNext = /next|ถัดไป|›|»|>/.test(txt.toLowerCase()) || /next/.test(aria);
                                let score = 0;
                                if (looksNext) score += 100;
                                if (!hasNumber) score += 20;
                                score += r.left / 10;
                                return { el, score };
                            })
                            .sort((a, b) => b.score - a.score);

                        const target = scored[0]?.el;
                        if (!target) return false;
                        target.click();
                        return true;
                    }
                    """
                )
                if clicked_rightmost:
                    if logger:
                        logger.log(f"UI probe fallback: clicked rightmost paginator control (hop {hops + 1})")
                    prev_page = current_page
                    try:
                        page.wait_for_function(
                            """
                            ({ prev }) => {
                                const parseNum = (txt) => {
                                    const m = String(txt || '').replace(/,/g, '').match(/\d+/);
                                    if (!m) return null;
                                    const n = Number(m[0]);
                                    return Number.isFinite(n) && n > 0 ? n : null;
                                };
                                const input = document.querySelector('.pagination input[type="number"], .pagination input[type="text"]');
                                const fromInput = input ? parseNum(input.value || input.getAttribute('value') || '') : null;
                                if (fromInput && fromInput > prev) return true;
                                const active = document.querySelector('li.page-item.active, [aria-current="page"], .pagination .active');
                                const fromActive = active ? parseNum(active.textContent || '') : null;
                                return !!(fromActive && fromActive > prev);
                            }
                            """,
                            arg={"prev": prev_page},
                            timeout=min(timeout_ms, 15000),
                        )
                    except Exception:
                        if logger:
                            logger.log("UI probe fallback: rightmost control click did not advance page within timeout")
                    wait_for_table_data(
                        page,
                        timeout_ms=min(timeout_ms, 20000),
                        logger=logger,
                        wait_reason=f"ui_probe_rightmost_to_{target_page}",
                    )
                    page.wait_for_timeout(1000)
                    post_page = get_ui_current_page_number(page) or get_row_inferred_page()
                    if post_page and post_page > prev_page:
                        moved = True
                    else:
                        if logger:
                            logger.log(
                                f"UI probe fallback: rightmost click produced no page advance (prev={prev_page}, now={post_page})"
                            )
            except Exception:
                pass

        if not moved:
            capture_ui_nav_page(page, f"ui_probe_no_move_target_{target_page}", logger=logger)
            break

        hops += 1
        detected_page = get_ui_current_page_number(page)
        if detected_page:
            current_page = detected_page
        else:
            if logger:
                logger.log(
                    "UI probe fallback: current page number could not be detected after click; stopping further hops"
                )
            break

    if current_page == target_page:
        return wait_target_page_rows(target_page, min(timeout_ms, 30000))
    if logger:
        logger.log(
            f"UI probe fallback failed to reach target page {target_page}; ended at page {current_page}"
        )
    capture_ui_nav_page(page, f"ui_probe_fail_target_{target_page}", logger=logger)
    return []


def replay_infos_pages(
    page,
    contract: dict,
    pages: int,
    base_delay_ms: int = 900,
    max_retries: int = 2,
    total_pages_hint: int | None = None,
    start_page: int = 2,
    fetch_all_max_pages: int = DEFAULT_FETCH_ALL_MAX_PAGES,
    logger: RunLogger | None = None,
    on_page_rows=None,
    on_slow_or_failed_attempt=None,
    slow_attempt_seconds: float = float(DEFAULT_API_ATTEMPT_TIMEOUT_SECONDS),
    request_timeout_seconds: int = DEFAULT_API_ATTEMPT_TIMEOUT_SECONDS,
    ui_probe_trigger_attempt: int = 2,
    duplicate_heavy_min_new_rows: int = 0,
    duplicate_heavy_consecutive_limit: int = 3,
    use_ui_probe_rows_on_api_failure: bool = True,
    force_ui_probe_rows_for_test: bool = False,
) -> tuple[list[dict], list[dict]]:
    if pages == 1:
        return [], []

    body_template = contract.get("body") if isinstance(contract, dict) else None
    if not isinstance(body_template, dict):
        return [], []

    all_rows = []
    stats = []
    replay_started_at = time.perf_counter()
    fetch_all = pages == FETCH_ALL_PAGES
    final_page = MAX_FETCH_ALL_PAGES if fetch_all else pages
    if fetch_all:
        final_page = min(final_page, max(2, fetch_all_max_pages))
        if logger:
            logger.log(f"Fetch-all safety cap active: max_replay_pages={final_page}")
    if total_pages_hint and total_pages_hint > 0 and total_pages_hint >= 2:
        if final_page > total_pages_hint:
            if logger:
                logger.log(
                    f"Replay target shifted from page {final_page} to discovered max page {total_pages_hint}"
                )
            final_page = total_pages_hint
    # If fetch-all has no discovered total-pages hint, expose the safety-cap bound in logs.
    known_last_page = total_pages_hint if total_pages_hint else final_page
    known_last_is_cap_bound = fetch_all and not bool(total_pages_hint)
    eta_last_page_bound = min(final_page, known_last_page) if known_last_page else final_page
    duplicate_heavy_consecutive_count = 0
    ui_probe_trigger_attempt = max(1, min(max_retries + 1, int(ui_probe_trigger_attempt)))
    if logger:
        mode_text = "fetch-all" if fetch_all else str(pages)
        if known_last_is_cap_bound:
            known_text = f"<={known_last_page}"
        else:
            known_text = str(known_last_page) if known_last_page else "?"
        logger.log(
            f"API replay pagination started. target={mode_text}, resolved_last_page={known_text}, page_size={PAGE_SIZE}"
        )
        logger.log(
            f"API replay fallback threshold: ui_probe_trigger_attempt={ui_probe_trigger_attempt}"
        )

    current_page = max(2, int(start_page or 2))
    if current_page > final_page:
        if logger:
            logger.log(
                f"API replay skipped: start_page={current_page} is beyond resolved_last_page={final_page}"
            )
        return all_rows, stats
    while current_page <= final_page:
        page_no = current_page
        page_started_at = time.perf_counter()
        page_body = dict(body_template)
        page_body["currentPage"] = page_no
        endpoint = str(contract.get("url") or "") if isinstance(contract, dict) else ""
        method = str(contract.get("method") or "POST").upper() if isinstance(contract, dict) else "POST"
        if logger:
            if known_last_is_cap_bound:
                known_text = f"<={known_last_page}"
            else:
                known_text = str(known_last_page) if known_last_page else "?"
            if fetch_all:
                if known_last_is_cap_bound:
                    logger.log(f"API replay fetching {page_no}/{known_text} ..")
                else:
                    logger.log(f"API replay fetching {page_no}/{known_text} <={fetch_all_max_pages} ..")
            else:
                logger.log(f"API replay fetching {page_no}/{known_text} ..")

        replay = None
        rows = []
        attempt = 0
        ui_probe_done = False
        ui_probe_rows_cache = []
        used_forced_ui_rows = False

        if force_ui_probe_rows_for_test and on_slow_or_failed_attempt:
            try:
                if logger:
                    logger.log(f"Force-UI test mode: probing UI rows for page {page_no} before API request")
                forced_ui_rows = on_slow_or_failed_attempt(
                    page_no=page_no,
                    attempt_no=0,
                    status=-7,
                    error="force_ui_probe_rows_for_test",
                    elapsed_seconds=0.0,
                ) or []
                for row in forced_ui_rows:
                    row["source_page"] = page_no
                if forced_ui_rows:
                    ui_probe_rows_cache = forced_ui_rows
                    rows = forced_ui_rows
                    used_forced_ui_rows = True
                    ui_probe_done = True
                    replay = {
                        "ok": False,
                        "status": -7,
                        "error": "force_ui_probe_rows_for_test",
                        "decrypted_error": None,
                    }
                    if logger:
                        logger.log(
                            f"Force-UI test mode: using {len(forced_ui_rows)} UI rows for page {page_no} and skipping API replay"
                        )
            except Exception as forced_exc:
                if logger:
                    logger.log(f"Force-UI test mode probe failed for page {page_no}: {forced_exc}")

        while attempt <= max_retries:
            if used_forced_ui_rows:
                break

            attempt_started = time.perf_counter()
            if logger:
                logger.log(
                    f"API request page_fetch page={page_no} attempt={attempt + 1} method={method} endpoint={endpoint} body.currentPage={page_body.get('currentPage')}"
                )
            replay = replay_infos_request(
                page,
                contract,
                override_body=page_body,
                request_timeout_ms=max(1000, int(request_timeout_seconds) * 1000),
            )
            replay["replay_page"] = page_no
            rows = replay.get("extracted_companies") or []

            status = int(replay.get("status") or -1)
            attempt_elapsed = time.perf_counter() - attempt_started
            if logger:
                logger.log(
                    "API request page_fetch_result "
                    f"page={page_no} attempt={attempt + 1} "
                    f"status={status} ok={bool(replay.get('ok', False))} "
                    f"rows={len(rows)} elapsed={attempt_elapsed:.2f}s "
                    f"error={replay.get('error') or replay.get('decrypted_error') or ''}"
                )
            if logger and not rows and (200 <= status < 300):
                logger.log(
                    f"API page {page_no} returned HTTP {status} with empty rows; accepting empty page as terminal candidate"
                )
            if rows or (200 <= status < 300):
                break

            if logger and status == -2 and attempt < max_retries:
                logger.log(
                    f"API request timeout page={page_no} attempt={attempt + 1} timeout={request_timeout_seconds}s; retrying"
                )

            should_ui_probe = (attempt + 1) >= ui_probe_trigger_attempt
            if logger and on_slow_or_failed_attempt and not ui_probe_done and not should_ui_probe:
                logger.log(
                    f"UI probe not triggered yet for page {page_no}: "
                    f"attempt={attempt + 1} threshold={ui_probe_trigger_attempt} status={status}"
                )
            if (
                on_slow_or_failed_attempt
                and not ui_probe_done
                and should_ui_probe
            ):
                try:
                    if logger and attempt_elapsed >= slow_attempt_seconds:
                        logger.log(
                            f"API request page_fetch_timeout page={page_no} attempt={attempt + 1} elapsed={attempt_elapsed:.2f}s threshold={slow_attempt_seconds:.0f}s"
                        )
                    if logger:
                        logger.log(
                            f"API page {page_no} attempt {attempt + 1} reached probe threshold; triggering UI probe fallback"
                        )
                    ui_probe_rows = on_slow_or_failed_attempt(
                        page_no=page_no,
                        attempt_no=attempt + 1,
                        status=status,
                        error=replay.get("error") or replay.get("decrypted_error") or "",
                        elapsed_seconds=attempt_elapsed,
                    ) or []
                    for row in ui_probe_rows:
                        row["source_page"] = page_no
                    if ui_probe_rows:
                        ui_probe_rows_cache = ui_probe_rows
                        if logger:
                            logger.log(
                                f"UI probe fallback captured {len(ui_probe_rows)} rows for page {page_no} (held unless API retries fail)"
                            )
                except Exception as probe_exc:
                    if logger:
                        logger.log(f"UI probe fallback failed for page {page_no}: {probe_exc}")
                finally:
                    ui_probe_done = True

            attempt += 1
            if logger and attempt <= max_retries:
                logger.log(
                    f"API request page_fetch_retry page={page_no} next_attempt={attempt + 1} reason=status_{status}_and_rows_{len(rows)}"
                )
            page.wait_for_timeout(base_delay_ms + attempt * 700)

        using_ui_fallback_rows = False
        if not rows and ui_probe_rows_cache and use_ui_probe_rows_on_api_failure:
            rows = ui_probe_rows_cache
            using_ui_fallback_rows = True
            if logger:
                logger.log(
                    f"Using UI probe rows for page {page_no} because API retries returned no rows"
                )
        elif not rows and ui_probe_rows_cache and not use_ui_probe_rows_on_api_failure:
            if logger:
                logger.log(
                    f"Discarding UI probe rows for page {page_no} due to config: use_ui_probe_rows_on_api_failure=false"
                )

        for row in rows:
            row["source_page"] = page_no
        all_rows.extend(rows)
        appended_rows = len(rows)
        if on_page_rows and rows:
            try:
                callback_result = on_page_rows(page_no, rows)
                if isinstance(callback_result, int):
                    appended_rows = max(0, min(len(rows), callback_result))
            except Exception as exc:
                if logger:
                    logger.log(f"CSV stream callback failed for replay page {page_no}: {exc}")
        skipped_rows = max(0, len(rows) - appended_rows)

        if len(rows) >= PAGE_SIZE and appended_rows == duplicate_heavy_min_new_rows:
            duplicate_heavy_consecutive_count += 1
            if logger:
                logger.log(
                    "Duplicate-heavy replay page detected "
                    f"page={page_no} appended={appended_rows} skipped={skipped_rows} "
                    f"streak={duplicate_heavy_consecutive_count}/{duplicate_heavy_consecutive_limit}"
                )
        else:
            duplicate_heavy_consecutive_count = 0

        stats.append(
            {
                "page": page_no,
                "ok": replay.get("ok", False) if replay else False,
                "status": replay.get("status", -1) if replay else -1,
                "rows": len(rows),
                "appended_rows": appended_rows,
                "skipped_rows": skipped_rows,
                "attempts": attempt + 1,
                "duration_seconds": round(time.perf_counter() - page_started_at, 3),
                "error": (replay.get("error") or replay.get("decrypted_error")) if replay else "no_replay_result",
                "used_ui_fallback_rows": using_ui_fallback_rows,
                "used_forced_ui_rows": used_forced_ui_rows,
            }
        )
        if logger:
            source_mode = "api"
            if stats[-1]["used_forced_ui_rows"]:
                source_mode = "ui_forced"
            elif stats[-1]["used_ui_fallback_rows"]:
                source_mode = "ui_fallback"
            if known_last_is_cap_bound:
                known_text = f"<={known_last_page}"
            else:
                known_text = str(known_last_page) if known_last_page else "?"
            durations = [float(s.get("duration_seconds") or 0.0) for s in stats]
            avg_page_sec = (sum(durations) / len(durations)) if durations else 0.0
            elapsed_replay_sec = time.perf_counter() - replay_started_at
            eta_text = "unknown"
            if eta_last_page_bound:
                remaining_pages = max(0, eta_last_page_bound - page_no)
                eta_text = format_duration(avg_page_sec * remaining_pages)
            logger.log(
                f"API replay done {page_no}/{known_text}: status={stats[-1]['status']} rows={len(rows)} attempts={stats[-1]['attempts']} source={source_mode}"
            )
            logger.log(
                "API replay timing "
                f"page={stats[-1]['duration_seconds']:.2f}s "
                f"avg_page={avg_page_sec:.2f}s "
                f"elapsed={format_duration(elapsed_replay_sec)} "
                f"eta={eta_text}"
            )

        # Small stagger helps avoid burst-like request pattern.
        page.wait_for_timeout(base_delay_ms + (page_no % 3) * 250)

        if duplicate_heavy_consecutive_count >= duplicate_heavy_consecutive_limit:
            if logger:
                logger.log(
                    "Stopping replay early due to repeated duplicate-heavy pages "
                    f"(streak={duplicate_heavy_consecutive_count}, page={page_no}, "
                    f"min_new_rows_threshold={duplicate_heavy_min_new_rows})"
                )
            break

        if len(rows) < PAGE_SIZE:
            if logger:
                logger.log(
                    f"API replay reached last page at {page_no}: rows={len(rows)} < PAGE_SIZE({PAGE_SIZE})"
                )
            break

        current_page += 1

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


def wait_for_table_data(
    page,
    timeout_ms: int = 20000,
    logger: RunLogger | None = None,
    wait_reason: str = "wait_for_table_data",
) -> bool:
    started = time.perf_counter()
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
        if logger:
            logger.log(f"Table data ready ({wait_reason}) in {time.perf_counter() - started:.2f}s")
        return True
    except Exception:
        if logger:
            logger.log(f"Wait timeout for table data ({wait_reason}) after {timeout_ms} ms")
        capture_waiting_page(page, wait_reason, logger=logger)
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
    fetch_all_max_pages: int,
    stuck_refresh_retries: int,
    api_replay_attempt_threshold: int,
    resume_from_page: int,
    track_progress_in_config: bool,
    use_ui_probe_rows_on_api_failure: bool,
    force_ui_probe_rows_for_test: bool,
    sort_label: str,
    prefer_direct_search_url: bool,
    filters: dict | None = None,
    logger: RunLogger | None = None,
    csv_stream_writer: IncrementalCSVWriter | None = None,
    on_page_progress=None,
) -> dict:
    run_started_at = time.perf_counter()
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
        "timing": {
            "overall_seconds": None,
            "replay_pages_count": 0,
            "replay_avg_page_seconds": None,
            "replay_min_page_seconds": None,
            "replay_max_page_seconds": None,
        },
        "debug": {
            "search_url": BASE_URL,
            "storage_state_used": str(storage_state_path) if storage_state_path and storage_state_path.exists() else None,
            "prefer_direct_search_url": prefer_direct_search_url,
            "sort_label": sort_label,
            "sort_applied": False,
            "search_strategy_used": "",
            "blocked_like_count": 0,
            "next_click_failures": 0,
            "api_replay_page_stats": [],
            "ui_filters_applied": False,
            "results_timeout_seconds": results_timeout_seconds,
            "stuck_refresh_retries": stuck_refresh_retries,
            "api_replay_attempt_threshold": api_replay_attempt_threshold,
            "resume_from_page": resume_from_page,
            "track_progress_in_config": track_progress_in_config,
            "use_ui_probe_rows_on_api_failure": use_ui_probe_rows_on_api_failure,
            "force_ui_probe_rows_for_test": force_ui_probe_rows_for_test,
            "api_response_hits_by_endpoint": {},
            "infos_contract_updates": 0,
        },
    }
    results_timeout_ms = max(10, results_timeout_seconds) * 1000
    dumps_dir = BASE_DIR / "dumps"
    dumps_dir.mkdir(exist_ok=True)
    if logger:
        logger.log(
            f"Run started. query='{query}', pages={pages}, headless={headless}, channel={browser_channel}, timeout={results_timeout_seconds}s"
        )
        logger.log(f"Fetch-all safety max pages: {fetch_all_max_pages}")
        logger.log(
            f"Search strategy: direct_url_first={prefer_direct_search_url}, storage_state={'enabled' if storage_state_path else 'disabled'}"
        )
        logger.log(f"Active filters: {json.dumps(filters or {}, ensure_ascii=False)}")
        logger.log(
            f"Runtime toggles: use_ui_probe_rows_on_api_failure={use_ui_probe_rows_on_api_failure}, "
            f"force_ui_probe_rows_for_test={force_ui_probe_rows_for_test}, "
            f"api_replay_attempt_threshold={api_replay_attempt_threshold}, "
            f"resume_from_page={resume_from_page}, "
            f"track_progress_in_config={track_progress_in_config}"
        )

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
        if logger:
            logger.log("Browser ready. Opening landing page...")

        def on_response(response):
            url = response.url
            if "/api/" not in url:
                return

            endpoint_key = urlsplit(url).path or url
            endpoint_hits = result["debug"].setdefault("api_response_hits_by_endpoint", {})
            endpoint_hits[endpoint_key] = int(endpoint_hits.get(endpoint_key, 0)) + 1

            request = response.request
            if "/api/v1/company-profiles/infos" in url:
                current_contract = extract_request_contract(request)
                result["latest_infos_contract"] = current_contract
                result["debug"]["infos_contract_updates"] = int(result["debug"].get("infos_contract_updates", 0)) + 1
                if result.get("infos_contract") is None:
                    result["infos_contract"] = current_contract
                    if logger:
                        body = current_contract.get("body") if isinstance(current_contract, dict) else None
                        logger.log(
                            "Captured initial infos contract "
                            f"method={current_contract.get('method')} "
                            f"currentPage={(body or {}).get('currentPage')} "
                            f"sortBy={(body or {}).get('sortBy')}"
                        )
                elif logger and result["debug"]["infos_contract_updates"] % 10 == 0:
                    body = current_contract.get("body") if isinstance(current_contract, dict) else None
                    logger.log(
                        "Updated infos contract snapshot "
                        f"updates={result['debug']['infos_contract_updates']} "
                        f"currentPage={(body or {}).get('currentPage')} "
                        f"sortBy={(body or {}).get('sortBy')}"
                    )

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
            if logger and len(result["api_hits"]) % 50 == 0:
                logger.log(
                    f"API traffic snapshot: total_hits={len(result['api_hits'])}, "
                    f"unique_endpoints={len(result['debug'].get('api_response_hits_by_endpoint', {}))}"
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
        if logger:
            logger.log("Landing page ready, overlays handled.")

        # Prefer direct result URL first, then fallback to UI search-box submit.
        direct_url_loaded_ok = False
        if prefer_direct_search_url:
            direct_url = f"{BASE_URL}juristic/searchInfo?keyword={quote(query)}"
            try:
                if logger:
                    logger.log(f"Trying direct search URL: {direct_url}")
                page.goto(direct_url, wait_until="domcontentloaded", timeout=60000)
                dismiss_startup_overlays(page)
                wait_for_table_data(
                    page,
                    timeout_ms=results_timeout_ms,
                    logger=logger,
                    wait_reason="direct_search_results_wait",
                )
                page.wait_for_timeout(1800)
                capture_page_dump(page, dumps_dir, "f_02_direct_search_first")
                result["debug"]["search_strategy_used"] = "direct_url"
                direct_url_loaded_ok = True
                if logger:
                    logger.log("Direct URL search loaded successfully.")
            except Exception as exc:
                result["debug"]["search_strategy_used"] = "direct_url_failed"
                result["debug"]["direct_url_error"] = str(exc)
                if logger:
                    logger.log(f"Direct URL search failed: {exc}")

        direct_probe = extract_company_candidates_from_dom(page)
        has_direct_signal = bool(direct_probe) or result.get("infos_contract") is not None or direct_url_loaded_ok
        if logger:
            logger.log(
                f"Direct probe: dom_candidates={len(direct_probe)}, infos_contract_captured={bool(result.get('infos_contract'))}"
            )
            if direct_url_loaded_ok and not (direct_probe or result.get("infos_contract") is not None):
                logger.log("Direct URL load succeeded; skipping search-box keyword re-entry by design.")

        if not has_direct_signal:
            result["debug"]["search_strategy_used"] = "search_box_fallback"
            if logger:
                logger.log("Switching to search-box fallback path.")

            # Existing search-box approach retained as fallback path.
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

            wait_for_table_data(
                page,
                timeout_ms=results_timeout_ms,
                logger=logger,
                wait_reason="search_fallback_results_wait",
            )
            page.wait_for_timeout(2000)
            capture_page_dump(page, dumps_dir, "f_02_after_search_fallback")
            if logger:
                logger.log("Search-box fallback submitted and results area loaded.")

        active_filters = has_active_filters(filters)
        if active_filters:
            try:
                result["debug"]["ui_filters_applied"] = apply_filters_with_refresh_recovery(
                    page,
                    filters,
                    results_timeout_ms=results_timeout_ms,
                    max_refresh_retries=stuck_refresh_retries,
                    logger=logger,
                    dumps_dir=dumps_dir,
                )
                capture_page_dump(page, dumps_dir, "f_03_after_filters")
                if logger:
                    logger.log("Advanced filters applied successfully.")
            except Exception as exc:
                result["debug"]["ui_filters_applied"] = False
                result["debug"]["filter_apply_error"] = str(exc)
                result["debug"]["filter_apply_refresh_exhausted"] = True
                if logger:
                    logger.log(f"Advanced filter apply failed and stopped after refresh retries: {exc}")

        try:
            result["debug"]["sort_applied"] = apply_sort_via_ui(page, sort_label, logger=logger)
            if result["debug"]["sort_applied"]:
                wait_for_table_data(
                    page,
                    timeout_ms=results_timeout_ms,
                    logger=logger,
                    wait_reason="sort_apply_results_wait",
                )
                page.wait_for_timeout(1200)
                capture_page_dump(page, dumps_dir, "f_03b_after_sort")
        except Exception as exc:
            result["debug"]["sort_apply_error"] = str(exc)
            if logger:
                logger.log(f"Sort apply exception: {exc}")

        ui_page_limit = 1 if pages == FETCH_ALL_PAGES else pages
        if resume_from_page > 1:
            # Resume mode still performs full init/filter/sort pipeline, then hands off to replay from configured page.
            ui_page_limit = 1
        if logger:
            logger.log(
                f"UI crawl plan resolved: ui_page_limit={ui_page_limit}, pages_requested={pages}"
            )
        for current_page in range(1, ui_page_limit + 1):
            dom_candidates = extract_company_candidates_from_dom(page)
            result["companies"].extend(dom_candidates)
            if csv_stream_writer and dom_candidates:
                csv_stream_writer.append_rows(dom_candidates, source_label=f"ui_page_{current_page}")
            result["pages_visited"] = current_page
            capture_page_dump(page, dumps_dir, f"f_page_{current_page:03d}")
            if logger:
                logger.log(
                    f"UI page {current_page} captured: rows={len(dom_candidates)}, accumulated_ui_rows={len(result['companies'])}"
                )
            if on_page_progress and dom_candidates:
                try:
                    on_page_progress(current_page)
                except Exception as exc:
                    if logger:
                        logger.log(f"Progress callback failed on UI page {current_page}: {exc}")

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
                        wait_for_table_data(
                            page,
                            timeout_ms=results_timeout_ms,
                            logger=logger,
                            wait_reason=f"ui_pagination_next_wait_page_{current_page + 1}",
                        )
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
            if logger:
                logger.log(
                    "Replay contract ready: "
                    f"method={str(replay_contract_source.get('method') or 'POST').upper()}, "
                    f"url={replay_contract_source.get('url') or ''}"
                )
            active_filters = has_active_filters(filters)
            effective_body = replay_contract_source.get("body")
            need_fallback_payload = active_filters and (
                (not result["debug"].get("ui_filters_applied"))
                or (not body_has_filter_keys(effective_body))
            )
            if need_fallback_payload:
                if logger and body_has_filter_keys(effective_body) is False:
                    logger.log("Captured infos body has no filter keys; rebuilding filtered replay body from config.")
                try:
                    effective_body = build_filter_payload(replay_contract_source.get("body"), filters)
                except Exception as exc:
                    result["debug"]["filter_apply_error"] = (
                        (result["debug"].get("filter_apply_error") or "")
                        + f" | fallback_payload_error: {exc}"
                    ).strip(" |")
                    result["error"] = "Filter fallback payload mapping failed"
                    effective_body = None
            result["effective_infos_body"] = effective_body
            if active_filters and need_fallback_payload:
                result["companies"] = []
                if effective_body is None:
                    stop_reason = "Filter fallback payload invalid/unmapped"
                    if logger:
                        logger.log(f"Process stopped: {stop_reason}. Skipping replay.")
                        capture_waiting_page(page, stop_reason, logger)
                    result["status"] = "partial"
                    result["api_hit_summary"] = {
                        "total_hits": len(result["api_hits"]),
                        "unique_urls": len({h.get('url') for h in result["api_hits"]}),
                    }
                    return result

            effective_body, enforced_sort_value = apply_sort_to_payload(effective_body, sort_label)
            if enforced_sort_value:
                result["debug"]["sort_enforced_value"] = enforced_sort_value
                actual_api_sort = effective_body.get("sortBy") if isinstance(effective_body, dict) else None
                if logger:
                    if actual_api_sort and actual_api_sort != enforced_sort_value:
                        logger.log(f"Replay payload sortBy: requested={enforced_sort_value}, actual_api={actual_api_sort} (pvDesc pagination workaround)")
                    else:
                        logger.log(f"Replay payload sortBy: {actual_api_sort or enforced_sort_value}")
            elif logger:
                logger.log(f"Replay payload sortBy was not enforced (unmapped sort label): '{sort_label}'")

            result["infos_replay"] = replay_infos_request(
                page,
                replay_contract_source,
                override_body=effective_body,
                request_timeout_ms=DEFAULT_API_ATTEMPT_TIMEOUT_SECONDS * 1000,
            )
            if logger:
                logger.log(
                    "API request replay_probe "
                    f"method={str(replay_contract_source.get('method') or 'POST').upper()} "
                    f"endpoint={replay_contract_source.get('url') or ''}"
                )
            if logger:
                logger.log(
                    f"Replay probe done: status={result['infos_replay'].get('status')} extracted={result['infos_replay'].get('extracted_count', 0)}"
                )
            if csv_stream_writer and result.get("infos_replay", {}).get("extracted_companies"):
                csv_stream_writer.append_rows(
                    result["infos_replay"]["extracted_companies"],
                    source_label="api_probe",
                )
            total_pages_hint = extract_total_pages_hint(result["infos_replay"].get("data"))
            if not total_pages_hint:
                total_pages_hint = extract_total_pages_hint(result["infos_replay"].get("decrypted_data"))
            ui_total_pages_hint = get_ui_total_pages_hint(page)
            if not total_pages_hint and ui_total_pages_hint:
                total_pages_hint = ui_total_pages_hint
                result["debug"]["total_pages_hint_source"] = "ui_paginator"
                if logger:
                    logger.log(f"Total pages hint detected from UI paginator: {total_pages_hint}")
            elif total_pages_hint:
                result["debug"]["total_pages_hint_source"] = "api_payload"
                if ui_total_pages_hint and ui_total_pages_hint != total_pages_hint and logger:
                    logger.log(
                        f"Total pages hint mismatch: api_payload={total_pages_hint}, ui_paginator={ui_total_pages_hint}"
                    )
            if total_pages_hint:
                result["debug"]["total_pages_hint"] = total_pages_hint
                if logger:
                    logger.log(f"Total pages hint detected from API payload: {total_pages_hint}")
                
                # Validate filter effectiveness: if filters are active but page count is suspiciously high,
                # it indicates filters were not applied (server ignored them).
                if active_filters and total_pages_hint >= 5000:
                    stop_reason = f"Filter validation failed: page_count={total_pages_hint} (expected <5000 for filtered data, likely filters were ignored by server)"
                    if logger:
                        logger.log(f"Process stopped: {stop_reason}. Aborting replay.")
                        capture_waiting_page(page, stop_reason, logger)
                    result["status"] = "partial"
                    result["error"] = stop_reason
                    result["companies"] = []
                    result["api_hit_summary"] = {
                        "total_hits": len(result["api_hits"]),
                        "unique_urls": len({h.get('url') for h in result["api_hits"]}),
                    }
                    return result
            
            if active_filters and result.get("infos_replay", {}).get("extracted_companies"):
                result["api_candidates"].extend(result["infos_replay"]["extracted_companies"])
            replay_contract = dict(replay_contract_source)
            if effective_body is not None:
                replay_contract["body"] = effective_body

            def retry_ui_probe_with_refresh(page_no: int) -> list[dict]:
                if logger:
                    logger.log(
                        f"UI probe recovery: refreshing page and rebuilding filter context before retrying target_page={page_no}"
                    )
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                    dismiss_startup_overlays(page)
                    wait_for_table_data(
                        page,
                        timeout_ms=results_timeout_ms,
                        logger=logger,
                        wait_reason="ui_probe_recovery_reload_wait",
                    )
                    page.wait_for_timeout(1200)

                    if has_active_filters(filters):
                        apply_filters_with_refresh_recovery(
                            page,
                            filters,
                            results_timeout_ms=results_timeout_ms,
                            max_refresh_retries=stuck_refresh_retries,
                            logger=logger,
                            dumps_dir=dumps_dir,
                        )

                    apply_sort_via_ui(page, sort_label, logger=logger)
                    wait_for_table_data(
                        page,
                        timeout_ms=results_timeout_ms,
                        logger=logger,
                        wait_reason="ui_probe_recovery_after_filters_sort",
                    )
                    page.wait_for_timeout(1000)

                    recovered_rows = ui_probe_navigate_to_page(
                        page,
                        target_page=page_no,
                        timeout_ms=results_timeout_ms,
                        logger=logger,
                    )
                    if logger:
                        logger.log(
                            f"UI probe recovery retry result: target_page={page_no}, rows_seen={len(recovered_rows)}"
                        )
                    return recovered_rows
                except Exception as recovery_exc:
                    if logger:
                        logger.log(f"UI probe recovery failed for target_page={page_no}: {recovery_exc}")
                    return []

            def on_replay_probe_attempt(page_no: int, attempt_no: int, status: int, error: str, elapsed_seconds: float):
                ui_rows = ui_probe_navigate_to_page(
                    page,
                    target_page=page_no,
                    timeout_ms=results_timeout_ms,
                    logger=logger,
                )
                if not ui_rows:
                    ui_rows = retry_ui_probe_with_refresh(page_no)
                if logger:
                    logger.log(
                        f"UI probe fallback probe page={page_no} attempt={attempt_no} status={status} elapsed={elapsed_seconds:.2f}s rows_seen={len(ui_rows)}"
                    )
                return ui_rows

            replay_rows, replay_stats = replay_infos_pages(
                page,
                replay_contract,
                pages=pages,
                total_pages_hint=total_pages_hint,
                start_page=max(2, int(resume_from_page or 1)),
                fetch_all_max_pages=fetch_all_max_pages,
                logger=logger,
                on_page_rows=(
                    (
                        lambda page_no, rows: (
                            (
                                csv_stream_writer.append_rows(rows, source_label=f"api_page_{page_no}")
                                if csv_stream_writer
                                else len(rows)
                            )
                            if not on_page_progress
                            else (
                                (
                                    on_page_progress(page_no),
                                    csv_stream_writer.append_rows(rows, source_label=f"api_page_{page_no}") if csv_stream_writer else len(rows)
                                )[1]
                            )
                        )
                    )
                ),
                on_slow_or_failed_attempt=on_replay_probe_attempt,
                ui_probe_trigger_attempt=api_replay_attempt_threshold,
                use_ui_probe_rows_on_api_failure=use_ui_probe_rows_on_api_failure,
                force_ui_probe_rows_for_test=force_ui_probe_rows_for_test,
            )
            result["debug"]["api_replay_page_stats"] = replay_stats
            if replay_stats:
                replay_durations = [float(s.get("duration_seconds") or 0.0) for s in replay_stats]
                result["timing"]["replay_pages_count"] = len(replay_stats)
                result["timing"]["replay_avg_page_seconds"] = round(sum(replay_durations) / len(replay_durations), 3)
                result["timing"]["replay_min_page_seconds"] = round(min(replay_durations), 3)
                result["timing"]["replay_max_page_seconds"] = round(max(replay_durations), 3)
            if replay_rows:
                result["api_candidates"].extend(replay_rows)
                result["api_replay_pages_added"] = len(replay_rows)
            if logger:
                inferred_last_page = None
                if replay_stats:
                    inferred_last_page = replay_stats[-1].get("page")
                if not inferred_last_page and total_pages_hint:
                    inferred_last_page = total_pages_hint
                result["debug"]["last_page_number"] = inferred_last_page
                logger.log(
                    f"Filtered list total pages: {inferred_last_page if inferred_last_page else 'unknown'}"
                )
                logger.log(
                    f"Replay pagination finished: pages={len(replay_stats)}, added_rows={result.get('api_replay_pages_added', 0)}"
                )
        else:
            stop_reason = "No API contract captured after filter application"
            if logger:
                logger.log(f"Process stopped: {stop_reason}. Skipping API replay pagination.")
                capture_waiting_page(page, stop_reason, logger)
        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass

        if not connected_via_cdp:
            browser.close()

    # Deduplicate by juristic_id first, fallback to profile_url.
    ui_source_rows = len(result.get("companies") or [])
    api_source_rows = len(result.get("api_candidates") or [])
    if logger:
        logger.log(
            f"Pre-dedup source counts: ui_rows={ui_source_rows}, api_rows={api_source_rows}, combined={ui_source_rows + api_source_rows}"
        )
    uniq = {}
    for item in result["companies"] + result["api_candidates"]:
        key = item.get("juristic_id") or item.get("profile_url") or ""
        if not key:
            continue
        if key not in uniq:
            uniq[key] = item

    # If config requests province sort, post-sort by province since server-side pvDesc breaks pagination.
    if sort_label and SORT_LABEL_TO_VALUE.get(sort_label) == "pvDesc":
        result["companies"] = sorted(uniq.values(), key=lambda x: (x.get("province") or "", x.get("juristic_id") or ""))
    else:
        # Preserve fetch order (UI/API order already reflects requested sort); avoid re-sorting by ID.
        result["companies"] = list(uniq.values())
    result["status"] = "ok" if result["companies"] else "partial"
    if logger:
        logger.log(
            f"Post-process complete: unique_companies={len(result['companies'])}, status={result['status']}"
        )

    # Keep api_hits compact for quick analysis.
    hits = result["api_hits"]
    result["api_hit_summary"] = {
        "total_hits": len(hits),
        "unique_urls": len({h.get('url') for h in hits}),
    }
    if logger:
        logger.log(
            f"API hit summary: total_hits={result['api_hit_summary']['total_hits']}, unique_urls={result['api_hit_summary']['unique_urls']}"
        )
        endpoint_hits = result.get("debug", {}).get("api_response_hits_by_endpoint", {})
        if endpoint_hits:
            top_hits = sorted(endpoint_hits.items(), key=lambda kv: kv[1], reverse=True)[:5]
            logger.log(f"API endpoint hit breakdown(top5): {json.dumps(top_hits, ensure_ascii=False)}")

    result["timing"]["overall_seconds"] = round(time.perf_counter() - run_started_at, 3)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="DBD company-list explorer via local JSON config")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_LOCAL_CONFIG_PATH),
        help="Path to local run config JSON (default: f_local_config.json)",
    )
    args = parser.parse_args()

    config_path = resolve_config_path(args.config)

    try:
        config = load_local_config(config_path)
    except Exception as exc:
        raise SystemExit(f"Invalid config at {config_path}: {exc}") from exc

    logger = RunLogger(LAST_RUN_LOG_PATH)
    logger.log(f"Loaded config from: {config_path}")

    storage_state_path = Path(config["storage_state"]) if config.get("use_storage_state", True) else None
    filters = config.get("filters") if isinstance(config.get("filters"), dict) else {}
    resume_from_page = max(1, int(config.get("resume_from_page", 1)))
    track_progress_in_config = bool(config.get("track_progress_in_config", True))
    packed_csv_path = BASE_DIR / "result_packed.csv"
    csv_stream_writer = IncrementalCSVWriter(packed_csv_path, logger=logger)

    out_path = BASE_DIR / "f_search_result.json"
    last_progress_page = {"value": 0}

    def on_page_progress(page_no: int) -> None:
        if not isinstance(page_no, int) or page_no < 1:
            return
        if page_no <= last_progress_page["value"]:
            return
        last_progress_page["value"] = page_no
        if track_progress_in_config:
            persist_last_page_to_config(config_path, page_no, logger=logger)
        logger.log(f"Progress checkpoint updated: last_page_extracted={page_no}")

    if logger:
        logger.log(
            f"Resume control: resume_from_page={resume_from_page}, track_progress_in_config={track_progress_in_config}"
        )

    try:
        data = scrape_company_list(
            query=config["query"],
            pages=config["pages"],
            headless=config["headless"],
            storage_state_path=storage_state_path,
            browser_channel=config["channel"],
            settle_seconds=config["settle_seconds"],
            cdp_url=config["cdp_url"],
            results_timeout_seconds=config["results_timeout_seconds"],
            fetch_all_max_pages=config["fetch_all_max_pages"],
            stuck_refresh_retries=config["stuck_refresh_retries"],
            api_replay_attempt_threshold=config["api_replay_attempt_threshold"],
            resume_from_page=resume_from_page,
            track_progress_in_config=track_progress_in_config,
            use_ui_probe_rows_on_api_failure=config["use_ui_probe_rows_on_api_failure"],
            force_ui_probe_rows_for_test=config["force_ui_probe_rows_for_test"],
            sort_label=config["sort_label"],
            prefer_direct_search_url=config["prefer_direct_search_url"],
            filters=filters,
            logger=logger,
            csv_stream_writer=csv_stream_writer,
            on_page_progress=on_page_progress,
        )

        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        write_packed_csv(data.get("companies", []), packed_csv_path)

        dumps_dir = BASE_DIR / "dumps"
        dumps_dir.mkdir(exist_ok=True)
        (dumps_dir / "f_api_hits.json").write_text(json.dumps(data.get("api_hits", []), ensure_ascii=False, indent=2), encoding="utf-8")
        (dumps_dir / "f_infos_contract.json").write_text(json.dumps(data.get("infos_contract"), ensure_ascii=False, indent=2), encoding="utf-8")
        (dumps_dir / "f_infos_replay_result.json").write_text(json.dumps(data.get("infos_replay"), ensure_ascii=False, indent=2), encoding="utf-8")

        logger.log(f"Saved outputs: {out_path.name}, {packed_csv_path.name} (csv was streamed during fetch)")
        logger.log(f"Run summary: companies={len(data.get('companies', []))}, pages_visited_ui={data.get('pages_visited')}")
        timing = data.get("timing") if isinstance(data.get("timing"), dict) else {}
        overall_sec = float(timing.get("overall_seconds") or 0.0)
        replay_pages_count = int(timing.get("replay_pages_count") or 0)
        replay_avg = timing.get("replay_avg_page_seconds")
        replay_min = timing.get("replay_min_page_seconds")
        replay_max = timing.get("replay_max_page_seconds")
        logger.log(
            "Timing summary: "
            f"overall={format_duration(overall_sec)} ({overall_sec:.2f}s), "
            f"replay_pages={replay_pages_count}, "
            f"avg_page={(f'{float(replay_avg):.2f}s' if replay_avg is not None else 'n/a')}, "
            f"min_page={(f'{float(replay_min):.2f}s' if replay_min is not None else 'n/a')}, "
            f"max_page={(f'{float(replay_max):.2f}s' if replay_max is not None else 'n/a')}"
        )
        if data.get("infos_contract"):
            logger.log("Captured infos contract: yes")
        if data.get("infos_replay"):
            logger.log(f"Infos replay extracted: {data['infos_replay'].get('extracted_count', 0)}")
        if data.get("api_replay_pages_added", 0) > 0:
            logger.log(f"API replay rows added from next pages: {data['api_replay_pages_added']}")
        if data.get("error"):
            logger.log(f"Run error: {data['error']}")
        if data.get("debug", {}).get("blocked_like_count", 0) > 0:
            logger.log(f"Blocked-like responses: {data['debug']['blocked_like_count']}")
    except Exception as exc:
        logger.log(f"FATAL: process crashed with exception: {exc}")
        tb_text = traceback.format_exc()
        for line in tb_text.strip().splitlines():
            logger.log(f"TRACE: {line}")
        crash_out_path = BASE_DIR / "f_search_result_crash.json"
        crash_payload = {
            "status": "crashed",
            "error": str(exc),
            "traceback": tb_text,
            "timestamp": datetime.now().isoformat(),
        }
        crash_out_path.write_text(json.dumps(crash_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.log(f"Run crashed. Crash details saved: {crash_out_path}")
        raise SystemExit(1)
    finally:
        csv_stream_writer.close()


if __name__ == "__main__":
    main()
