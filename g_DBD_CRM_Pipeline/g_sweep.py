"""Stage 1 DISCOVER - adaptive juristic-ID prefix sweep.

Replaces process `f`'s single-broad-keyword seed, which DBD blocked server-side
on 2026-09-16 (`บริษัท` and `จำกัด` now return HTTP 400 "be more specific").

Why ID prefixes work (verified 2026-09-16, see f_AI_Local_Context.md):
- the search matches registration numbers as SUBSTRINGS, so querying prefix P
  returns a superset of companies whose id starts with P; filtering locally with
  startswith(P) yields exactly that bucket with nothing missed
- every company has exactly one 13-digit id, so the union over prefixes covers
  the registry exactly once - coverage is provable, not inferred from "rows < 10"
- bucket size shrinks ~10x per added digit, so job size is tunable

Each bucket is an independent resumable unit recorded in `sweep_buckets`, so an
interruption costs one small bucket rather than a whole run's position - the
failure mode that cost the 2026-04-10 run its place at page 3060.

Browser/session/Imperva handling lives in `g_session.py`; the DBD API contract
and decrypt come from process `f`, so there is one implementation, not two.

Usage:
    python g_sweep.py --list-sets
    python g_sweep.py --set set1 --dry-run
    python g_sweep.py --set set1
    python g_sweep.py --set set1 --prefixes 0107
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent / "f_DBD_Company_List_Scraper_WIth_Filter"))

from playwright.sync_api import sync_playwright  # noqa: E402

import g_session  # noqa: E402
import g_store  # noqa: E402


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def filters_hash(filters: dict) -> str:
    return hashlib.sha256(
        json.dumps(filters, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


OPTIONAL_BUCKET_COLS = (
    "total_pages", "pages_done", "rows_on_prefix", "rows_seen",
    "started_at", "finished_at", "note",
)


def record(conn, prefix, fhash, state, set_name, **kw) -> None:
    """Upsert one bucket row keyed on (prefix, filters_hash).

    The statement is built from the fields actually supplied. Passing NULL
    explicitly would defeat the column DEFAULTs (SQLite applies a DEFAULT only
    when the column is omitted), and would also clobber existing counters on
    update - so unsupplied fields are left out entirely.
    """
    fields = {
        "prefix": prefix,
        "filters_hash": fhash,
        "state": state,
        "set_name": set_name,
    }
    for col in OPTIONAL_BUCKET_COLS:
        # `note` is included even when None, since clearing it is meaningful.
        if col in kw and (kw[col] is not None or col == "note"):
            fields[col] = kw[col]

    cols = list(fields)
    updates = ", ".join(
        f"{c}=excluded.{c}" for c in cols if c not in ("prefix", "filters_hash")
    )
    conn.execute(
        "INSERT INTO sweep_buckets (" + ",".join(cols) + ") "
        "VALUES (" + ",".join("?" * len(cols)) + ") "
        "ON CONFLICT(prefix,filters_hash) DO UPDATE SET " + updates,
        [fields[c] for c in cols],
    )
    conn.commit()


class BlockedError(RuntimeError):
    """Imperva returned a block page; the session identity is burned."""


# Transient per-request failures that deserve a retry rather than failing the
# bucket. -2 is f_main's request-timeout sentinel, -1 its generic evaluate
# failure; 5xx are DBD server hiccups seen throughout the April runs.
TRANSIENT_STATUSES = (-1, -2, 500, 502, 503, 504)

# 429 is different in kind: the server is telling us to slow down, not failing.
# Retrying quickly makes it worse, and marking the bucket failed (the pre-fix
# behaviour) discarded 8 buckets in 31 seconds on 2026-09-16.
RATE_LIMIT_BACKOFF_MS = (60000, 120000, 240000)


class RateLimited(RuntimeError):
    """DBD returned 429 and kept returning it after full backoff."""


def fetch_with_token_refresh(sess, prefix, filters, page_no, max_attempts: int = 4):
    """Fetch one page, handling token expiry and transient failures.

    Two distinct problems, both of which previously killed buckets:
    - HTTP 401: DBD's JWT lives ~15 min. Expiry is a session event, not a bucket
      failure; treating it as one silently marked 12 buckets `error` on
      2026-09-16. Re-seed and retry the same page.
    - status -2 / -1 / 5xx: transient timeouts and server hiccups.
      `replay_infos_request` is single-shot with no retry of its own (unlike
      f_main's paging loop), so one slow response ended the bucket.
    """
    if sess.needs_reseed():
        sess.reseed()

    last = None
    rate_limit_hits = 0
    for attempt in range(1, max_attempts + 1):
        res = sess.fetch(prefix, filters, page_no)
        last = res

        if res["blocked"] or res["ok"]:
            return res

        if res["status"] == 429:
            # Back off hard and retry the SAME page. Never fail the bucket on a
            # rate limit - the data is there, the server just wants us slower.
            if rate_limit_hits >= len(RATE_LIMIT_BACKOFF_MS):
                raise RateLimited(
                    f"429 persisted at {prefix} page {page_no} after "
                    f"{rate_limit_hits} backoffs totalling "
                    f"{sum(RATE_LIMIT_BACKOFF_MS) // 1000}s"
                )
            wait_ms = RATE_LIMIT_BACKOFF_MS[rate_limit_hits]
            rate_limit_hits += 1
            log(f"  RATE LIMITED at {prefix} page {page_no}; "
                f"backing off {wait_ms // 1000}s (attempt {rate_limit_hits}/"
                f"{len(RATE_LIMIT_BACKOFF_MS)})")
            sess.wait(wait_ms)
            continue

        if res["status"] == 401:
            log(f"  token expired at {prefix} page {page_no}; re-seeding")
            if not sess.reseed():
                raise g_session.SessionDead("re-seed failed after 401")
            continue

        if res["status"] in TRANSIENT_STATUSES and attempt < max_attempts:
            backoff = 1500 * attempt
            log(f"  {prefix} page {page_no}: transient status={res['status']}, "
                f"retry {attempt + 1}/{max_attempts} in {backoff}ms")
            sess.wait(backoff)
            continue

        return res
    return last


def sweep_bucket(sess, conn, prefix, filters, fhash, args, set_name) -> dict:
    """Page through one prefix bucket, storing only rows whose id starts with it."""
    probe = fetch_with_token_refresh(sess, prefix, filters, 1)
    if probe["blocked"]:
        raise BlockedError(f"blocked while probing {prefix}")
    if not probe["ok"]:
        log(f"  {prefix}: probe failed status={probe['status']}")
        record(conn, prefix, fhash, "error", set_name,
               note=f"probe status {probe['status']}")
        return {"state": "error"}

    total_pages = probe["total_pages"] or 0
    on_first = sum(1 for r in probe["rows"]
                   if str(r.get("juristic_id") or "").startswith(prefix))

    # Too big for one bucket - caller descends a digit.
    if total_pages > args.max_pages:
        log(f"  {prefix}: {total_pages} pages > budget {args.max_pages} -> split")
        record(conn, prefix, fhash, "split", set_name, total_pages=total_pages,
               note="exceeded page budget")
        return {"state": "split"}

    # Sparse bucket. Only safe to call empty when page 1 IS the whole bucket:
    # results are ordered by company NAME, not juristic id, so on-prefix rows can
    # land on any page. Concluding "empty" from page-1 evidence on a multi-page
    # bucket would silently drop rows.
    if total_pages <= 1 and on_first == 0:
        log(f"  {prefix}: single page, 0/{len(probe['rows'])} on-prefix -> empty")
        record(conn, prefix, fhash, "empty", set_name, total_pages=total_pages,
               pages_done=1, rows_on_prefix=0, rows_seen=len(probe["rows"]),
               note="single page, no on-prefix rows")
        return {"state": "empty"}

    if args.dry_run:
        log(f"  {prefix}: {total_pages} pages, {on_first}/{len(probe['rows'])} on-prefix (dry-run)")
        return {"state": "dry", "total_pages": total_pages}

    record(conn, prefix, fhash, "running", set_name, total_pages=total_pages,
           started_at=g_store.now_iso(), note=None)

    seen = on_prefix = inserted = changed = 0

    def absorb(rows):
        nonlocal seen, on_prefix, inserted, changed
        for row in rows:
            seen += 1
            if str(row.get("juristic_id") or "").startswith(prefix):
                on_prefix += 1
                r = g_store.upsert(conn, row, source_ref=f"sweep:{set_name or '-'}:{prefix}")
                inserted += r == "inserted"
                changed += r == "changed"

    absorb(probe["rows"])
    conn.commit()

    for pno in range(2, total_pages + 1):
        if sess.should_rotate():
            conn.commit()
            if not sess.rotate():
                record(conn, prefix, fhash, "partial", set_name, pages_done=pno - 1,
                       rows_on_prefix=on_prefix, rows_seen=seen,
                       note="session rotation failed")
                raise BlockedError("could not re-open a session after rotation")

        res = fetch_with_token_refresh(sess, prefix, filters, pno)
        if res["blocked"]:
            record(conn, prefix, fhash, "partial", set_name, pages_done=pno - 1,
                   rows_on_prefix=on_prefix, rows_seen=seen,
                   note=f"imperva block at page {pno}")
            conn.commit()
            raise BlockedError(f"blocked at {prefix} page {pno}")

        if not res["ok"]:
            log(f"  {prefix}: page {pno} failed status={res['status']}, bucket partial")
            record(conn, prefix, fhash, "partial", set_name, pages_done=pno - 1,
                   rows_on_prefix=on_prefix, rows_seen=seen,
                   note=f"page {pno} status {res['status']}")
            return {"state": "partial"}

        absorb(res["rows"])
        if pno % 10 == 0:
            record(conn, prefix, fhash, "running", set_name, pages_done=pno,
                   rows_on_prefix=on_prefix, rows_seen=seen, note=None)
        sess.wait(args.page_delay_ms)

    record(conn, prefix, fhash, "done", set_name, total_pages=total_pages,
           pages_done=total_pages, rows_on_prefix=on_prefix, rows_seen=seen,
           finished_at=g_store.now_iso(), note=None)
    log(f"  {prefix}: done pages={total_pages} on_prefix={on_prefix}/{seen} "
        f"new={inserted} changed={changed}")
    return {"state": "done"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Adaptive juristic-ID prefix sweep")
    ap.add_argument("--db", default=str(BASE_DIR / "dbd_companies.sqlite3"))
    ap.add_argument("--config", default=str(BASE_DIR / "g_local_config.json"))
    ap.add_argument("--sets-config", default=str(BASE_DIR / "g_sets_config.json"))
    ap.add_argument("--set", dest="set_name", default="",
                    help="named capital band from g_sets_config.json, e.g. set1")
    ap.add_argument("--sets", default="", help="comma-separated sets to run in order")
    ap.add_argument("--list-sets", action="store_true")
    ap.add_argument("--prefixes", default="", help="comma-separated; default: from config")
    ap.add_argument("--max-pages", type=int, default=200, help="per-bucket page budget")
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--limit-buckets", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--headless", action="store_true")
    # Imperva-safety controls
    ap.add_argument("--rotate-after-pages", type=int, default=1500,
                    help="start a fresh browser identity after this many pages")
    ap.add_argument("--reseed-after-seconds", type=int, default=600,
                    help="refresh the JWT after this long (DBD token TTL is ~15 min)")
    ap.add_argument("--page-delay-ms", type=int, default=1200)
    ap.add_argument("--bucket-delay-ms", type=int, default=2000)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    sets_path = Path(args.sets_config)
    sets_cfg = json.loads(sets_path.read_text(encoding="utf-8")) if sets_path.exists() else {}
    all_sets = sets_cfg.get("sets", {})

    if args.list_sets:
        log("collection plan:")
        for name in sets_cfg.get("run_order", list(all_sets)):
            s = all_sets.get(name, {})
            log(f"  {name:12} {s.get('label','')[:34]:36} "
                f"~{s.get('estimate_companies',0):>7} companies "
                f"~{s.get('estimate_pages',0):>6} pages  [{s.get('status','?')}]")
        t = sets_cfg.get("totals", {})
        log(f"  {'TOTAL':12} {'':36} ~{t.get('estimate_companies',0):>7} companies "
            f"~{t.get('estimate_pages',0):>6} pages")
        return

    if args.sets.strip():
        run_sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    elif args.set_name:
        run_sets = [args.set_name]
    else:
        run_sets = [""]  # fall back to g_local_config api_filters

    for s in run_sets:
        if s and s not in all_sets:
            raise SystemExit(f"unknown set {s!r}; known: {', '.join(all_sets)}")

    conn = g_store.connect(Path(args.db))
    base_prefixes = (
        [p.strip() for p in args.prefixes.split(",") if p.strip()]
        if args.prefixes.strip() else list(cfg.get("seed_prefixes") or [])
    )
    if not base_prefixes:
        raise SystemExit("no prefixes to sweep")

    with sync_playwright() as p:
        sess = g_session.SweepSession(
            p, headless=args.headless,
            rotate_after_pages=args.rotate_after_pages,
            reseed_after_seconds=args.reseed_after_seconds, log=log,
        )
        if not sess.open():
            log("FATAL: could not open an initial session")
            return

        try:
            for set_name in run_sets:
                if set_name:
                    filters = dict(sets_cfg.get("common_filters") or {})
                    filters.update(all_sets[set_name].get("filters") or {})
                    log(f"=== {set_name}: {all_sets[set_name].get('label','')} ===")
                else:
                    filters = cfg.get("api_filters") or {}
                    log("=== ad-hoc filters from g_local_config.json ===")

                # Keyed per filter set, so each band tracks its own coverage and
                # a prior band's buckets never look already-done.
                fhash = filters_hash(filters)
                done = {
                    r["prefix"] for r in conn.execute(
                        "SELECT prefix FROM sweep_buckets WHERE state IN ('done','empty') "
                        "AND filters_hash=?", (fhash,)
                    )
                }
                queue = [x for x in base_prefixes if x not in done]
                log(f"  {len(queue)} buckets queued, {len(done)} already complete")

                processed = 0
                while queue:
                    if args.limit_buckets and processed >= args.limit_buckets:
                        log(f"  bucket limit reached; {len(queue)} left")
                        break
                    prefix = queue.pop(0)
                    if prefix in done:
                        continue

                    # A bucket can fail two recoverable ways: Imperva blocks the
                    # identity, or the browser goes away (crash, or someone closes
                    # the window). Both are handled the same - get a fresh session
                    # and retry the bucket once. Rows already stored are merged by
                    # juristic_id, so a retry from page 1 costs requests, not data.
                    res = None
                    for attempt in (1, 2):
                        try:
                            res = sweep_bucket(sess, conn, prefix, filters, fhash,
                                               args, set_name)
                            break
                        except RateLimited as exc:
                            # Not a failure we can engineer around: the server
                            # wants fewer requests. Stop cleanly and leave the
                            # bucket pending so a later run resumes it.
                            log(f"  RATE LIMIT PERSISTED: {exc}")
                            log("  stopping the run. Progress is checkpointed - "
                                "resume later, ideally with a larger --page-delay-ms.")
                            record(conn, prefix, fhash, "pending", set_name,
                                   note="stopped: rate limited")
                            return
                        except (BlockedError, g_session.SessionDead) as exc:
                            blocked = isinstance(exc, BlockedError)
                            label = "IMPERVA BLOCK" if blocked else "SESSION LOST"
                            log(f"  {label}: {str(exc)[:110]}")
                            if attempt == 2:
                                log("  failed twice; stopping this run "
                                    "(progress is checkpointed - just re-run to resume)")
                                return
                            # A block needs a real cooldown; a closed window does not.
                            cooldown = 45000 if blocked else 5000
                            log(f"  recovering with a fresh session (attempt {attempt + 1}/2)")
                            if not sess.rotate(cooldown_ms=cooldown):
                                log("  FATAL: cannot open a new session; stopping")
                                return
                    if res is None:
                        return

                    processed += 1
                    if res["state"] == "split":
                        if len(prefix) >= args.max_depth:
                            log(f"  {prefix}: at max depth, leaving as-is")
                        else:
                            queue = [prefix + d for d in "0123456789"] + queue
                    try:
                        sess.wait(args.bucket_delay_ms)
                    except g_session.SessionDead:
                        log("  session lost between buckets; reopening")
                        if not sess.rotate(cooldown_ms=5000):
                            log("  FATAL: cannot open a new session; stopping")
                            return
        finally:
            sess.close()

    log("sweep finished. store now holds:")
    for k, v in g_store.stats(conn).items():
        log(f"  {k:26} {v}")
    conn.close()


if __name__ == "__main__":
    main()
