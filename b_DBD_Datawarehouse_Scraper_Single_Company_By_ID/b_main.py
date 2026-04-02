import argparse
import base64
import json
import re
import time
import zlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STORAGE_STATE = BASE_DIR / "storage_state.json"
DEFAULT_LOCAL_CONFIG_PATH = BASE_DIR / "b_local_config.json"


def load_local_run_config(config_path: Path) -> dict:
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def parse_api_response_body(response):
    """Parse API response body with a tolerant fallback path.

    Some DBD endpoints return JSON payloads with non-standard headers, which
    can fail with response.json(). In that case, read text and parse manually.
    """
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
        blocked = "incapsula incident id" in text.lower() or "_incapsula_resource" in text.lower()
        if blocked:
            return {"_blocked_by_incapsula": True, "_raw_text": text[:500]}
        return {"_raw_text": text}


def extract_token_from_html(html: str) -> str:
    if not isinstance(html, str) or not html:
        return ""
    # Matches Nuxt public config token style: "token":"<jwt>"
    m = re.search(r'"token"\s*:\s*"([A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+)"', html)
    return m.group(1) if m else ""


def is_blocked_payload(data) -> bool:
    return isinstance(data, dict) and data.get("_blocked_by_incapsula") is True


def is_blocked_text(text: str) -> bool:
    if not isinstance(text, str):
        return False
    lowered = text.lower()
    return "incapsula incident id" in lowered or "_incapsula_resource" in lowered


def normalize_captured_payload(data):
    """Normalize payloads and flag anti-bot challenge responses.

    Returns a tuple: (normalized_data, blocked)
    """
    if is_blocked_payload(data):
        return data, True
    if is_blocked_text(data):
        return {"_blocked_by_incapsula": True, "_raw_text": data[:500]}, True
    return data, False


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


def normalize_aad_hint(url_or_path: str) -> str:
    if not url_or_path:
        return ""
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        parsed = urlparse(url_or_path)
        if parsed.query:
            return f"{parsed.path}?{parsed.query}"
        return parsed.path
    return url_or_path


def decrypt_payload(enc_key: str, payload: dict, aad_hint: str = ""):
    if not isinstance(payload, dict):
        return payload
    if not all(k in payload for k in ("iv", "ct")):
        return payload
    if not enc_key:
        return payload
    aad_hint = normalize_aad_hint(aad_hint)

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
        "_aad_hint": aad_hint,
        "_aad_candidates": aad_candidates,
        "_encrypted": payload,
    }


def collect_tokens_from_results(results: dict) -> list[str]:
    tokens = []
    for item in results.get("others", []):
        data = item.get("data")
        if isinstance(data, dict):
            for key in ("idToken", "token", "accessToken"):
                value = data.get(key)
                if isinstance(value, str) and value.count(".") >= 2:
                    tokens.append(value)
    return tokens


def try_decrypt_results(results: dict, token_candidates: list[str]) -> dict:
    selected_enc_key = ""
    selected_token_payload = {}
    now = int(time.time())

    decoded_tokens = []
    for token in token_candidates:
        payload = decode_jwt(token)
        enc_key = payload.get("encKey")
        if isinstance(enc_key, str) and enc_key:
            decoded_tokens.append((payload, enc_key))

    if decoded_tokens:
        valid = [x for x in decoded_tokens if int(x[0].get("exp", 0)) > now]
        pool = valid if valid else decoded_tokens
        selected_token_payload, selected_enc_key = max(pool, key=lambda x: int(x[0].get("exp", 0)))

    enc_keys = []
    for payload, enc_key in decoded_tokens:
        if enc_key not in enc_keys:
            enc_keys.append(enc_key)
    if selected_enc_key and selected_enc_key in enc_keys:
        enc_keys.remove(selected_enc_key)
        enc_keys.insert(0, selected_enc_key)

    api_paths = {
        "profile": results.get("debug", {}).get("profile_url", ""),
        "financial": results.get("debug", {}).get("financial_url", ""),
        "committees": results.get("debug", {}).get("committees_url", ""),
        "sign_committees": results.get("debug", {}).get("sign_committees_url", ""),
        "mergers": results.get("debug", {}).get("mergers_url", ""),
    }

    def decrypt_with_all_keys(payload: dict, aad_hint: str):
        if not enc_keys:
            return payload
        last_result = payload
        for key in enc_keys:
            candidate = decrypt_payload(key, payload, aad_hint)
            if not (isinstance(candidate, dict) and "_decrypt_error" in candidate):
                return candidate
            last_result = candidate
        return last_result

    decrypted = {
        "enc_key_found": bool(selected_enc_key),
        "token_payload": selected_token_payload,
        "enc_key_candidates": len(enc_keys),
        "source_status": results.get("debug", {}).get("status"),
        "source_debug": {
            "blocked_count": results.get("debug", {}).get("blocked_count", 0),
            "blocked_run": results.get("debug", {}).get("blocked_run", False),
            "attempts": results.get("debug", {}).get("attempts", 0),
            "storage_state_used": results.get("debug", {}).get("storage_state_used"),
        },
        "profile": decrypt_with_all_keys(results.get("profile"), api_paths["profile"]),
        "financial": decrypt_with_all_keys(results.get("financial"), api_paths["financial"]),
        "financial_sections": {},
        "committees": decrypt_with_all_keys(results.get("committees"), api_paths["committees"]),
        "sign_committees": decrypt_with_all_keys(results.get("sign_committees"), api_paths["sign_committees"]),
        "mergers": decrypt_with_all_keys(results.get("mergers"), api_paths["mergers"]),
        "others": [],
    }

    for key, section in results.get("financial_sections", {}).items():
        decrypted["financial_sections"][key] = {
            "url": section.get("url"),
            "data": decrypt_with_all_keys(section.get("data"), section.get("url", "")),
        }

    for item in results.get("others", []):
        decrypted["others"].append(
            {
                "url": item.get("url"),
                "data": decrypt_with_all_keys(item.get("data"), item.get("url", "")),
            }
        )

    return decrypted


def extract_company_key_from_profile_url(profile_url: str, fallback_juristic_id: str) -> tuple[str, str]:
        marker = "/api/v1/company-profiles/info/"
        if marker in profile_url:
                tail = profile_url.split(marker, 1)[1]
                parts = tail.split("/", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                        return parts[0], parts[1].split("?", 1)[0]
        return "7", fallback_juristic_id


def trigger_financial_fetches(page, token: str, jp_type: str, jp_no: str) -> None:
        thai_year = datetime.now().year + 543
        year_candidates = [thai_year, thai_year - 1, thai_year - 2, 2567, 2566, 2565, 2564, 2563]
        years = []
        for y in year_candidates:
                ys = str(y)
                if ys not in years:
                        years.append(ys)

        page.evaluate(
                """
                async ({ token, jpType, jpNo, years }) => {
                    const headers = token ? { Authorization: `Bearer ${token}` } : {};
                    const urls = [];
                    for (const y of years) {
                        urls.push(`/api/v1/fin/balancesheet/year/${jpType}/${jpNo}?fiscalYear=${y}`);
                        urls.push(`/api/v1/fin/submit/${jpType}/${jpNo}?fiscalYear=${y}`);
                    }
                    for (const url of urls) {
                        try {
                            await fetch(url, { headers, credentials: 'include' });
                        } catch (_) {
                        }
                    }
                }
                """,
                {"token": token, "jpType": jp_type, "jpNo": jp_no, "years": years},
        )


def fetch_api_payloads(page, token: str, urls: list[str]) -> list[dict]:
        return page.evaluate(
                """
                async ({ token, urls }) => {
                    const headers = token ? { Authorization: `Bearer ${token}` } : {};
                    const out = [];
                    for (const url of urls) {
                        try {
                            const resp = await fetch(url, { headers, credentials: 'include' });
                            const text = await resp.text();
                            let data = null;
                            try {
                                data = JSON.parse(text);
                            } catch (_) {
                                data = text || null;
                            }
                            out.push({ url, status: resp.status, ok: resp.ok, data });
                        } catch (e) {
                            out.push({ url, status: -1, ok: false, data: { _fetch_error: String(e) } });
                        }
                    }
                    return out;
                }
                """,
                {"token": token, "urls": urls},
        )


def open_profile_via_search(page, juristic_id: str) -> bool:
    """Open company profile using the homepage search flow.

    This mirrors real user behavior and avoids cases where direct profile URLs
    do not fully hydrate data in the frontend app.
    """
    page.goto("https://datawarehouse.dbd.go.th/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    search_input = page.locator("input[placeholder*='เลขทะเบียนนิติบุคคล']").first
    if search_input.count() == 0:
        search_input = page.locator("form#form input.form-control").first
    if search_input.count() == 0:
        return False

    search_input.click()
    search_input.fill(juristic_id)
    page.wait_for_timeout(1500)

    # Prefer explicit suggestion click (HAR flow), fallback to Enter.
    suggestion = page.locator("#suggestionContent a[href*='/company/profile/']").first
    if suggestion.count() > 0:
        try:
            suggestion.click(timeout=5000)
        except Exception:
            page.keyboard.press("Enter")
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(7000)
    return "/company/profile/" in page.url


def hydrate_profile_page(page, juristic_id: str) -> bool:
    """Attempt to open profile page via user-like flow with a direct fallback."""
    target_url = f"https://datawarehouse.dbd.go.th/company/profile/{juristic_id}"
    opened = False
    try:
        opened = open_profile_via_search(page, juristic_id)
    except Exception:
        opened = False

    if not opened:
        print("Search flow fallback to direct URL:", target_url)
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

    page.wait_for_timeout(12000)
    return "/company/profile/" in page.url


def trigger_finance_tab_clicks(page) -> None:
    finance_selectors = [
        "a:has-text('ข้อมูลงบการเงิน')",
        "button:has-text('ข้อมูลงบการเงิน')",
        "a:has-text('งบการเงิน')",
        "button:has-text('งบการเงิน')",
        "a:has-text('ประวัติการส่งงบการเงิน')",
        "button:has-text('ประวัติการส่งงบการเงิน')",
    ]
    for selector in finance_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.click(timeout=5000)
                page.wait_for_timeout(3000)
        except Exception:
            continue


def get_company_data(juristic_id: str, headless: bool = False, storage_state_path: Path | None = None):
    results = {
        "profile": None,
        "financial": None,
        "financial_sections": {},
        "committees": [],
        "sign_committees": [],
        "mergers": [],
        "others": [],
        "debug": {
            "captured_urls": [],
            "page_url": None,
            "page_title": None,
            "nuxt_store": None,
            "nuxt_token": None,
            "profile_url": None,
            "financial_url": None,
            "committees_url": None,
            "sign_committees_url": None,
            "mergers_url": None,
            "blocked_urls": [],
            "blocked_count": 0,
            "blocked_run": False,
            "status": "unknown",
            "attempts": 0,
            "storage_state_used": None,
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_kwargs = {}
        if storage_state_path and storage_state_path.exists():
            context_kwargs["storage_state"] = str(storage_state_path)
            results["debug"]["storage_state_used"] = str(storage_state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        def handle_response(response):
            url = response.url
            results["debug"]["captured_urls"].append(url)

            # Keep URL markers even if payload parsing fails.
            if "/company-profiles/info/" in url and not results["debug"].get("profile_url"):
                results["debug"]["profile_url"] = url
            elif "/company-profiles/committee-signs/" in url and not results["debug"].get("sign_committees_url"):
                results["debug"]["sign_committees_url"] = url
            elif "/company-profiles/committees/" in url and not results["debug"].get("committees_url"):
                results["debug"]["committees_url"] = url
            elif "/company-profiles/mergers/" in url and not results["debug"].get("mergers_url"):
                results["debug"]["mergers_url"] = url
            elif "/api/v1/fin/" in url and not results["debug"].get("financial_url"):
                results["debug"]["financial_url"] = url

            if "/api/" in url:
                data = parse_api_response_body(response)
                if data is None:
                    return

                data, blocked = normalize_captured_payload(data)
                if blocked:
                    results["debug"]["blocked_urls"].append(url)
                    return

                if "/company-profiles/info/" in url:
                    print("PROFILE FOUND:", url)
                    results["profile"] = data
                    results["debug"]["profile_url"] = url

                elif "/company-profiles/committee-signs/" in url:
                    print("SIGN COMMITTEES FOUND:", url)
                    results["sign_committees"] = data
                    results["debug"]["sign_committees_url"] = url

                elif "/company-profiles/committees/" in url:
                    print("COMMITTEES FOUND:", url)
                    results["committees"] = data
                    results["debug"]["committees_url"] = url

                elif "/company-profiles/mergers/" in url:
                    print("MERGERS FOUND:", url)
                    results["mergers"] = data
                    results["debug"]["mergers_url"] = url

                elif "financial" in url or "finance" in url:
                    print("FINANCIAL FOUND:", url)
                    results["financial"] = data
                    results["debug"]["financial_url"] = url

                elif "/api/v1/fin/" in url:
                    print("FIN ENDPOINT FOUND:", url)
                    path = normalize_aad_hint(url).split("?", 1)[0]
                    section_name = path.rsplit("/", 1)[0].split("/api/v1/fin/", 1)[-1].replace("/", "_")
                    key = f"{section_name}_{len(results['financial_sections']) + 1}"
                    results["financial_sections"][key] = {"url": url, "data": data}
                    results["financial"] = data
                    results["debug"]["financial_url"] = url

                else:
                    results["others"].append({
                        "url": url,
                        "data": data
                    })

        context.on("response", handle_response)

        print("Loading via search flow:", juristic_id)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            results["debug"]["attempts"] = attempt
            hydrate_profile_page(page, juristic_id)
            results["debug"]["page_url"] = page.url
            results["debug"]["page_title"] = page.title()

            trigger_finance_tab_clicks(page)

            profile_url = results.get("debug", {}).get("profile_url") or ""
            jp_type, jp_no = extract_company_key_from_profile_url(profile_url, juristic_id)
            try:
                token_for_fetch = page.evaluate("() => globalThis.__NUXT__?.config?.public?.token || ''")
            except Exception:
                token_for_fetch = ""

            try:
                trigger_financial_fetches(page, token_for_fetch, jp_type, jp_no)
                page.wait_for_timeout(3500)
            except Exception:
                pass

            try:
                jp_type_for_profile = "7"
                profile_no = juristic_id
                thai_year = datetime.now().year + 543
                years = [str(thai_year - i) for i in range(0, 7)]
                urls = [
                    f"/api/v1/company-profiles/info/{jp_type_for_profile}/{profile_no}",
                    f"/api/v1/company-profiles/committees/{jp_type_for_profile}/{profile_no}",
                    f"/api/v1/company-profiles/committee-signs/{jp_type_for_profile}/{profile_no}",
                    f"/api/v1/company-profiles/mergers/{jp_type_for_profile}/{profile_no}",
                ]
                for y in years:
                    urls.append(f"/api/v1/fin/balancesheet/year/{jp_type}/{jp_no}?fiscalYear={y}")
                    urls.append(f"/api/v1/fin/submit/{jp_type}/{jp_no}?fiscalYear={y}")

                fetched = fetch_api_payloads(page, token_for_fetch, urls)
                for item in fetched:
                    url = item.get("url", "")
                    data = item.get("data")
                    if data is None:
                        continue
                    data, blocked = normalize_captured_payload(data)
                    if blocked:
                        results["debug"]["blocked_urls"].append(url)
                        continue

                    if "/company-profiles/info/" in url and not results["profile"]:
                        results["profile"] = data
                        results["debug"]["profile_url"] = url
                    elif "/company-profiles/committee-signs/" in url and not results["sign_committees"]:
                        results["sign_committees"] = data
                        results["debug"]["sign_committees_url"] = url
                    elif "/company-profiles/committees/" in url and not results["committees"]:
                        results["committees"] = data
                        results["debug"]["committees_url"] = url
                    elif "/company-profiles/mergers/" in url and not results["mergers"]:
                        results["mergers"] = data
                        results["debug"]["mergers_url"] = url
                    elif "/api/v1/fin/" in url:
                        path = normalize_aad_hint(url).split("?", 1)[0]
                        section_name = path.rsplit("/", 1)[0].split("/api/v1/fin/", 1)[-1].replace("/", "_")
                        key = f"{section_name}_{len(results['financial_sections']) + 1}"
                        results["financial_sections"][key] = {"url": url, "data": data}
                        results["financial"] = data
                        results["debug"]["financial_url"] = url
            except Exception:
                pass

            got_profile = isinstance(results.get("profile"), dict)
            got_financial = isinstance(results.get("financial"), (dict, list))
            if got_profile and got_financial:
                break

            page.wait_for_timeout(3000 * attempt)

        try:
            nuxt_data = page.evaluate(
                """
                () => {
                  return {
                    token: globalThis.__NUXT__?.config?.public?.token || null,
                    profileStore: globalThis.__NUXT__?.state?.companyProfileStore || null,
                    financeStore: globalThis.__NUXT__?.state?.financeStore || null
                  };
                }
                """
            )
            results["debug"]["nuxt_token"] = nuxt_data.get("token")
            results["debug"]["nuxt_store"] = {
                "profileStore": nuxt_data.get("profileStore"),
                "financeStore": nuxt_data.get("financeStore"),
            }
        except Exception:
            pass

        # Fallback: extract token from HTML when runtime object is unavailable.
        if not results["debug"].get("nuxt_token"):
            try:
                html_token = extract_token_from_html(page.content())
                if html_token:
                    results["debug"]["nuxt_token"] = html_token
            except Exception:
                pass

        blocked_urls = list(dict.fromkeys(results.get("debug", {}).get("blocked_urls") or []))
        results["debug"]["blocked_urls"] = blocked_urls
        results["debug"]["blocked_count"] = len(blocked_urls)
        results["debug"]["blocked_run"] = len(blocked_urls) > 0
        has_profile = isinstance(results.get("profile"), dict)
        has_financial = isinstance(results.get("financial"), (dict, list))
        if has_profile and has_financial:
            results["debug"]["status"] = "ok"
        elif results["debug"]["blocked_run"]:
            results["debug"]["status"] = "blocked"
        else:
            results["debug"]["status"] = "partial"

        if not has_profile and not has_financial:
            debug_dir = BASE_DIR / "dumps"
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / "dbd_page.html").write_text(page.content(), encoding="utf-8")

        # Persist browser state so next run can reuse challenge-passed cookies.
        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass

        browser.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Capture DBD company data via local JSON config")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_LOCAL_CONFIG_PATH),
        help="Path to local run config JSON (default: b_local_config.json)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (BASE_DIR / config_path).resolve()
    run_cfg = load_local_run_config(config_path)

    juristic_id = str(run_cfg.get("juristic_id", "0107561000081")).strip() or "0107561000081"
    headless = bool(run_cfg.get("headless", False))
    no_storage_state = bool(run_cfg.get("no_storage_state", False))
    storage_state_value = str(run_cfg.get("storage_state", str(DEFAULT_STORAGE_STATE))).strip()

    storage_state_path = None
    if not no_storage_state:
        storage_state_path = Path(storage_state_value)
        if not storage_state_path.is_absolute():
            storage_state_path = (BASE_DIR / storage_state_path).resolve()

    data = get_company_data(juristic_id, headless=headless, storage_state_path=storage_state_path)
    token_candidates = collect_tokens_from_results(data)
    nuxt_token = data.get("debug", {}).get("nuxt_token")
    if isinstance(nuxt_token, str) and nuxt_token.count(".") >= 2:
        token_candidates.insert(0, nuxt_token)
    decrypted = try_decrypt_results(data, token_candidates)

    output_path = BASE_DIR / "dbd_result.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    output_decrypted_path = BASE_DIR / "dbd_result_decrypted.json"
    with output_decrypted_path.open("w", encoding="utf-8") as f:
        json.dump(decrypted, f, ensure_ascii=False, indent=2)

    print("\nSaved to dbd_result.json")
    print("Saved to dbd_result_decrypted.json")

    # quick preview
    if data["profile"]:
        print("\nCompany profile found")
    else:
        print("\nNo profile captured")

    if data["financial"]:
        print("Financial data found")
    else:
        print("No financial data captured")

    blocked_urls = data.get("debug", {}).get("blocked_urls") or []
    if blocked_urls:
        print(f"Incapsula blocked {len(blocked_urls)} API response(s)")
        print("Try non-headless mode and rerun if profile/financial is empty")

    status = data.get("debug", {}).get("status")
    if status == "ok":
        print("Run status: OK")
    elif status == "blocked":
        print("Run status: BLOCKED (challenge response captured instead of API JSON)")
    else:
        print(f"Run status: {status}")

    if data.get("debug", {}).get("storage_state_used"):
        print("Storage state loaded:", data["debug"]["storage_state_used"])
    elif not no_storage_state:
        print("Storage state file not found yet; it will be created after this run")

    if decrypted.get("enc_key_found"):
        print("encKey found in JWT payload")
    else:
        print("No encKey found in available JWT tokens")


if __name__ == "__main__":
    main()