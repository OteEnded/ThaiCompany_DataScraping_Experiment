"""SQLite system of record for DBD company data.

Replaces the truncate-on-every-run CSV model used by process `f`
(`IncrementalCSVWriter` opens with mode "w"), which is why the 31,725 records
collected in April survive only as hand-archived CSVs in Downloads.

Design notes:
- keyed on `juristic_id`, so re-running a sweep merges instead of overwriting
- `content_hash` covers only the business fields, so re-seeing an unchanged row
  updates `last_seen_at` but does not register a change
- every field-level change is appended to `company_history`, which is what makes
  "keep track" possible rather than just "have a snapshot"
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

# Business fields, in stable order. content_hash is computed over exactly these.
BUSINESS_FIELDS = [
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

MONEY_FIELDS = {
    "registered_capital_baht",
    "total_revenue_baht",
    "net_profit_baht",
    "total_assets_baht",
    "shareholders_equity_baht",
}

# Incoming CSV headers -> store column. The April exports carry two misspelled
# headers; process `f` must keep them for compatibility, so they are mapped here
# instead of being renamed at the source.
COLUMN_ALIASES = {
    "data_retreive_at": "data_retrieved_at",
    "data_retrieve_approch": "data_source_approach",
    "data_retrieved_at": "data_retrieved_at",
    "data_source_approach": "data_source_approach",
}

DDL = """
CREATE TABLE IF NOT EXISTS companies (
    juristic_id              TEXT PRIMARY KEY,
    company_name             TEXT,
    juristic_type            TEXT,
    status                   TEXT,
    business_type_code       TEXT,
    business_type_name       TEXT,
    province                 TEXT,
    registered_capital_baht  INTEGER,
    total_revenue_baht       INTEGER,
    net_profit_baht          INTEGER,
    total_assets_baht        INTEGER,
    shareholders_equity_baht INTEGER,
    profile_url              TEXT,
    data_from_page           INTEGER,
    data_retrieved_at        TEXT,
    data_source_approach     TEXT,
    first_seen_at            TEXT NOT NULL,
    last_seen_at             TEXT NOT NULL,
    last_changed_at          TEXT,
    content_hash             TEXT NOT NULL,
    source_ref               TEXT
);

CREATE INDEX IF NOT EXISTS idx_companies_province ON companies(province);
CREATE INDEX IF NOT EXISTS idx_companies_btype    ON companies(business_type_code);
CREATE INDEX IF NOT EXISTS idx_companies_status   ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_prefix4  ON companies(substr(juristic_id,1,4));

CREATE TABLE IF NOT EXISTS company_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    juristic_id TEXT NOT NULL,
    changed_at  TEXT NOT NULL,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_jid ON company_history(juristic_id);

-- Tracks which ID-prefix buckets have been swept, so a sweep is resumable and
-- coverage is auditable rather than inferred.
--
-- Keyed on (prefix, filters_hash): the same prefix is swept once per capital
-- band, so the filter set must be part of the identity or set2 would look
-- already-done because set1 had visited that prefix.
CREATE TABLE IF NOT EXISTS sweep_buckets (
    prefix          TEXT NOT NULL,
    filters_hash    TEXT NOT NULL,
    total_pages     INTEGER,
    pages_done      INTEGER NOT NULL DEFAULT 0,
    rows_on_prefix  INTEGER NOT NULL DEFAULT 0,
    rows_seen       INTEGER NOT NULL DEFAULT 0,
    state           TEXT NOT NULL DEFAULT 'pending',
    set_name        TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    note            TEXT,
    PRIMARY KEY (prefix, filters_hash)
);
CREATE INDEX IF NOT EXISTS idx_buckets_set ON sweep_buckets(set_name, state);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_money(value) -> int | None:
    """Normalize money columns.

    The single navigate_ui export writes '42000000.0' where api_replay exports
    write '42000000'; both must land on the same integer.
    """
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if s == "" or s.lower() in ("none", "null", "-"):
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def parse_int(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def normalize_row(raw: dict) -> dict | None:
    """Map a CSV/scraper row onto store columns. Returns None if unusable."""
    row = {}
    for k, v in raw.items():
        if k is None:
            continue
        key = COLUMN_ALIASES.get(k.strip(), k.strip())
        row[key] = v

    jid = str(row.get("juristic_id") or "").strip()
    if not jid:
        return None

    out = {"juristic_id": jid}
    for f in BUSINESS_FIELDS:
        v = row.get(f)
        if f in MONEY_FIELDS:
            out[f] = parse_money(v)
        else:
            s = None if v is None else str(v).strip()
            out[f] = s or None
    out["data_from_page"] = parse_int(row.get("data_from_page"))
    out["data_retrieved_at"] = str(row.get("data_retrieved_at") or "").strip() or None
    out["data_source_approach"] = str(row.get("data_source_approach") or "").strip() or None
    return out


def content_hash(row: dict) -> str:
    payload = json.dumps(
        {f: row.get(f) for f in BUSINESS_FIELDS}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _migrate_sweep_buckets(conn: sqlite3.Connection) -> None:
    """v1 keyed sweep_buckets on prefix alone, which collides once more than one
    capital band is swept. Rebuild it on (prefix, filters_hash)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sweep_buckets)")]
    if not cols or "set_name" in cols:
        return  # absent (fresh DDL will create it) or already migrated

    conn.execute("ALTER TABLE sweep_buckets RENAME TO sweep_buckets_v1")
    conn.executescript(DDL)
    conn.execute(
        "INSERT OR IGNORE INTO sweep_buckets "
        "(prefix, filters_hash, total_pages, pages_done, rows_on_prefix, rows_seen, "
        " state, set_name, started_at, finished_at, note) "
        "SELECT prefix, COALESCE(filters_hash,'legacy'), total_pages, pages_done, "
        "       rows_on_prefix, rows_seen, state, NULL, started_at, finished_at, note "
        "FROM sweep_buckets_v1"
    )
    conn.execute("DROP TABLE sweep_buckets_v1")
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _migrate_sweep_buckets(conn)
    conn.executescript(DDL)
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def upsert(conn: sqlite3.Connection, raw: dict, source_ref: str = "") -> str:
    """Insert or merge one row.

    Returns 'inserted' | 'changed' | 'unchanged' | 'skipped'.
    """
    row = normalize_row(raw)
    if row is None:
        return "skipped"

    ts = now_iso()
    h = content_hash(row)
    existing = conn.execute(
        "SELECT * FROM companies WHERE juristic_id=?", (row["juristic_id"],)
    ).fetchone()

    if existing is None:
        cols = (
            ["juristic_id"]
            + BUSINESS_FIELDS
            + [
                "data_from_page",
                "data_retrieved_at",
                "data_source_approach",
                "first_seen_at",
                "last_seen_at",
                "last_changed_at",
                "content_hash",
                "source_ref",
            ]
        )
        vals = (
            [row["juristic_id"]]
            + [row[f] for f in BUSINESS_FIELDS]
            + [
                row["data_from_page"],
                row["data_retrieved_at"],
                row["data_source_approach"],
                ts,
                ts,
                ts,
                h,
                source_ref,
            ]
        )
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            "INSERT INTO companies (" + ",".join(cols) + ") VALUES (" + placeholders + ")",
            vals,
        )
        return "inserted"

    if existing["content_hash"] == h:
        conn.execute(
            "UPDATE companies SET last_seen_at=? WHERE juristic_id=?",
            (ts, row["juristic_id"]),
        )
        return "unchanged"

    for f in BUSINESS_FIELDS:
        old, new = existing[f], row[f]
        if old != new:
            conn.execute(
                "INSERT INTO company_history(juristic_id,changed_at,field,old_value,new_value) "
                "VALUES (?,?,?,?,?)",
                (
                    row["juristic_id"],
                    ts,
                    f,
                    None if old is None else str(old),
                    None if new is None else str(new),
                ),
            )

    sets = ", ".join(f + "=?" for f in BUSINESS_FIELDS)
    conn.execute(
        "UPDATE companies SET " + sets + ", data_from_page=?, data_retrieved_at=?, "
        "data_source_approach=?, last_seen_at=?, last_changed_at=?, content_hash=?, "
        "source_ref=? WHERE juristic_id=?",
        [row[f] for f in BUSINESS_FIELDS]
        + [
            row["data_from_page"],
            row["data_retrieved_at"],
            row["data_source_approach"],
            ts,
            ts,
            h,
            source_ref,
            row["juristic_id"],
        ],
    )
    return "changed"


def stats(conn: sqlite3.Connection) -> dict:
    def q(sql):
        return conn.execute(sql).fetchone()[0]

    return {
        "companies": q("SELECT COUNT(*) FROM companies"),
        "changes_recorded": q("SELECT COUNT(*) FROM company_history"),
        "distinct_provinces": q("SELECT COUNT(DISTINCT province) FROM companies"),
        "distinct_business_types": q("SELECT COUNT(DISTINCT business_type_code) FROM companies"),
        "distinct_prefix4": q("SELECT COUNT(DISTINCT substr(juristic_id,1,4)) FROM companies"),
        "with_revenue": q("SELECT COUNT(*) FROM companies WHERE total_revenue_baht IS NOT NULL"),
        "buckets_tracked": q("SELECT COUNT(*) FROM sweep_buckets"),
    }
