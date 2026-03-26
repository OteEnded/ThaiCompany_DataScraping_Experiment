import argparse
import base64
import json
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


def get_company_data(juristic_id: str, headless: bool = False):
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
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        def handle_response(response):
            url = response.url
            results["debug"]["captured_urls"].append(url)

            if "/api/" in url:
                try:
                    data = response.json()
                except Exception:
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

        target_url = f"https://datawarehouse.dbd.go.th/company/profile/{juristic_id}"
        print("Loading:", target_url)
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        results["debug"]["page_url"] = page.url
        results["debug"]["page_title"] = page.title()

        page.wait_for_timeout(15000)

        # Trigger financial API calls by opening finance-related tabs.
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
                    page.wait_for_timeout(4000)
            except Exception:
                continue

        # Fallback: trigger finance endpoints directly with the active browser session.
        profile_url = results.get("debug", {}).get("profile_url") or ""
        jp_type, jp_no = extract_company_key_from_profile_url(profile_url, juristic_id)
        try:
            token_for_fetch = page.evaluate("() => globalThis.__NUXT__?.config?.public?.token || ''")
        except Exception:
            token_for_fetch = ""
        try:
            trigger_financial_fetches(page, token_for_fetch, jp_type, jp_no)
            page.wait_for_timeout(5000)
        except Exception:
            pass

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

        if not results["profile"] and not results["financial"]:
            debug_dir = BASE_DIR / "dumps"
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / "dbd_page.html").write_text(page.content(), encoding="utf-8")

        browser.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Capture DBD company data with Playwright")
    parser.add_argument(
        "--juristic-id",
        default="70107561000081",
        help="Juristic ID to open on DBD DataWarehouse",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )
    args = parser.parse_args()

    data = get_company_data(args.juristic_id, headless=args.headless)
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

    if decrypted.get("enc_key_found"):
        print("encKey found in JWT payload")
    else:
        print("No encKey found in available JWT tokens")


if __name__ == "__main__":
    main()