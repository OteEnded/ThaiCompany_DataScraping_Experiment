"""Browser session management and Imperva-safety controls for the sweep.

Context: DBD sits behind Imperva, which tracks a PERSISTENT visitor id
(`visid_incap_*`). In April a single identity pulled ~32,000 records over five
days and ended up flagged - reusing that session file was the cause of the
`Access denied / Error 15` block on 2026-09-16.

The full collection plan is ~82,000 requests, roughly 2.5x that volume, so
session hygiene has to be a built-in feature rather than an afterthought:

- rotate the browser session every `rotate_after_pages`, so no single visitor id
  accumulates the whole run's volume
- never persist or reload `storage_state.json`; every session starts clean
- jitter every wait, so the request cadence is not machine-regular
- detect Imperva block pages explicitly and fail fast, instead of burning
  `results_timeout_seconds * stuck_refresh_retries` (~12 min) on a stalled page
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "f_DBD_Company_List_Scraper_WIth_Filter"))

import f_main  # noqa: E402

# Substrings that identify an Imperva challenge/block response. Mirrors the
# detection process `b` uses (`is_blocked_text`); kept here so the sweep does not
# depend on importing process b.
BLOCK_MARKERS = (
    "incapsula incident id",
    "_incapsula_resource",
    "access denied",
    "request unsuccessful",
    "powered by imperva",
)

SEED_KEYWORD = "โอสถสภา"  # narrow, known-good; used ONLY to make DBD issue a token


class SessionDead(RuntimeError):
    """The browser/page went away (crashed, or the window was closed).

    This is the failure that killed the 2026-04-10 run at page 3060 and again on
    2026-09-16 at bucket 0105535: an unhandled TargetClosedError propagates out
    and takes the whole run with it. Treat it as a recoverable session-level
    event - reopen and retry the bucket - rather than a fatal error.
    """


# Playwright surfaces a closed browser/page a few different ways depending on
# which call was in flight when it went away.
_DEAD_MARKERS = (
    "target page, context or browser has been closed",
    "target closed",
    "browser has been closed",
    "connection closed",
    "websocket error",
    "page closed",
)


def is_session_dead(exc: BaseException) -> bool:
    return any(m in str(exc).lower() for m in _DEAD_MARKERS)


def looks_blocked(res: dict) -> bool:
    """True if a replay result carries an Imperva block/challenge page."""
    for key in ("data", "decrypted_data"):
        v = res.get(key)
        if isinstance(v, str):
            low = v.lower()
            if any(m in low for m in BLOCK_MARKERS):
                return True
    err = str(res.get("error") or "").lower()
    return any(m in err for m in BLOCK_MARKERS)


def jitter(base_ms: int, spread: float = 0.45) -> int:
    """Randomize a wait so cadence is not machine-regular."""
    lo = int(base_ms * (1.0 - spread))
    hi = int(base_ms * (1.0 + spread))
    return random.randint(max(50, lo), max(60, hi))


class SweepSession:
    """A browser session with a captured API contract and a page budget.

    Deliberately does NOT use storage_state: each rotation should present a fresh
    Imperva visitor identity rather than accumulating history on one.
    """

    def __init__(self, playwright, headless: bool = False, rotate_after_pages: int = 1500,
                 reseed_after_seconds: int = 600, log=print):
        self._p = playwright
        self.headless = headless
        self.rotate_after_pages = rotate_after_pages
        # DBD's JWT carries the encKey and expires in ~15 minutes (measured
        # 2026-09-16: session ready 11:33:13, first 401 at 11:48:32). Re-seed
        # comfortably inside that window rather than waiting for the 401.
        self.reseed_after_seconds = reseed_after_seconds
        self.log = log
        self.browser = None
        self.ctx = None
        self.page = None
        self.contract = None
        self.contract_at = 0.0
        self._cap: dict = {}
        self.pages_this_session = 0
        self.session_index = 0
        self.reseed_count = 0

    def open(self) -> bool:
        try:
            return self._open()
        except Exception as exc:
            self.log(f"  session open failed: {str(exc)[:120]}")
            self.close()
            return False

    def _open(self) -> bool:
        self.session_index += 1
        self.browser = self._p.chromium.launch(
            headless=self.headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.ctx = self.browser.new_context(locale="th-TH", timezone_id="Asia/Bangkok")
        self.page = self.ctx.new_page()

        # Always overwrite, never setdefault: a re-seed must pick up the NEW
        # contract (with a fresh JWT), not keep the stale one.
        self._cap = {}
        self.ctx.on(
            "response",
            lambda r: self._cap.__setitem__("c", f_main.extract_request_contract(r.request))
            if "/api/v1/company-profiles/infos" in r.url else None,
        )

        if not self._seed_search():
            self.close()
            return False

        self.pages_this_session = 0
        self.log(f"  session {self.session_index} ready")
        return True

    def _seed_search(self) -> bool:
        """Load the site and run one narrow search so DBD issues a fresh token."""
        self._cap.pop("c", None)
        self.page.goto(f_main.BASE_URL, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(jitter(4000))
        f_main.dismiss_startup_overlays(self.page)

        box = None
        for sel in (
            "form.form-group.search.lg input.form-control",
            "input[placeholder*='ชื่อหรือเลขทะเบียนนิติบุคคล']",
            "form#form input.form-control",
            "input[type='text']",
        ):
            loc = self.page.locator(sel).first
            if loc.count() > 0:
                box = loc
                break
        if box is None:
            self.log("  seed: search box not found (blocked or layout change)")
            return False

        box.click()
        box.fill(SEED_KEYWORD)
        self.page.wait_for_timeout(jitter(1000))
        icon = self.page.locator("#searchicon").first
        if icon.count() > 0:
            icon.click(timeout=5000)
        else:
            box.press("Enter")
        self.page.wait_for_timeout(jitter(9000))

        contract = self._cap.get("c")
        if not contract:
            self.log("  seed: failed to capture API contract")
            return False
        self.contract = contract
        self.contract_at = time.time()
        return True

    def token_age(self) -> float:
        return time.time() - self.contract_at if self.contract_at else 1e9

    def needs_reseed(self) -> bool:
        return self.token_age() >= self.reseed_after_seconds

    def reseed(self) -> bool:
        """Get a fresh JWT without discarding the browser identity.

        Cheaper than a full rotation: token expiry is not an Imperva problem, so
        there is no reason to throw away a working visitor session over it.
        """
        if self.page is None:
            raise SessionDead("no page")
        self.reseed_count += 1
        self.log(f"  re-seeding token (age {self.token_age():.0f}s, "
                 f"reseed #{self.reseed_count})")
        try:
            ok = self._seed_search()
        except Exception as exc:
            if is_session_dead(exc):
                raise SessionDead(str(exc)) from None
            raise
        if not ok:
            self.log("  re-seed failed")
        return ok

    def close(self) -> None:
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        self.browser = self.ctx = self.page = None

    def rotate(self, cooldown_ms: int = 12000) -> bool:
        """Close the current identity and start a fresh one."""
        self.log(f"  rotating session after {self.pages_this_session} pages")
        self.close()
        # A brief gap between identities; back-to-back launches look scripted.
        time.sleep(jitter(cooldown_ms) / 1000.0)
        return self.open()

    def should_rotate(self) -> bool:
        return self.pages_this_session >= self.rotate_after_pages

    def wait(self, ms: int) -> None:
        """Jittered pause that reports a dead browser instead of crashing the run."""
        if self.page is None:
            raise SessionDead("no page")
        try:
            self.page.wait_for_timeout(jitter(ms))
        except Exception as exc:
            if is_session_dead(exc):
                raise SessionDead(str(exc)) from None
            raise

    def fetch(self, keyword: str, filters: dict, page_no: int) -> dict:
        """One API replay. Returns the normalized shape the sweep consumes."""
        if self.page is None:
            raise SessionDead("no page")
        body = dict(self.contract.get("body") or {})
        body["keyword"] = keyword
        body["currentPage"] = page_no
        body.update(filters)
        try:
            res = f_main.replay_infos_request(self.page, self.contract, override_body=body)
        except Exception as exc:
            if is_session_dead(exc):
                raise SessionDead(str(exc)) from None
            raise
        self.pages_this_session += 1

        # replay_infos_request catches its own exceptions and reports them in
        # `error`, so a dead browser can arrive as a value rather than a raise.
        if is_session_dead(Exception(str(res.get("error") or ""))):
            raise SessionDead(str(res.get("error")))

        payload = res.get("decrypted_data") or res.get("data")
        return {
            "ok": bool(res.get("ok")) and res.get("status") == 200,
            "status": res.get("status"),
            "blocked": looks_blocked(res),
            "rows": res.get("extracted_companies") or [],
            "total_pages": f_main.extract_total_pages_hint(payload),
        }
