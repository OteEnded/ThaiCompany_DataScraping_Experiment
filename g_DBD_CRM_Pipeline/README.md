# Process g — DBD → CRM Pipeline

Turns the DBD DataWarehouse experiments (processes `a`–`f`) into a repeatable
pipeline with a durable system of record and CRM-shaped exports.

## Why

Process `f` proved the DBD extraction technique but stored results in CSVs that
are **rewritten from scratch on every run** (`IncrementalCSVWriter` opens with
mode `"w"`). Five April sessions collected 31,725 companies, and they survived
only because each run's CSV was manually copied to `Downloads/` before the next
run overwrote it. This module makes the store durable and the history explicit.

## Quick start

```powershell
# 1. Load the archived April dataset (idempotent - safe to re-run)
python g_main.py import-csv --path "C:\Users\<you>\Downloads\DBD Data\DBD Data Set 0"

# 2. Inspect
python g_main.py stats
python g_main.py coverage
python g_main.py changes --limit 20

# 3. Export for the CRM
python g_main.py export --out crm_companies.csv
python g_main.py export --out high_value.csv --min-revenue 500000000

# 4. Collect new data (non-headless; a Chrome window opens)
python g_sweep.py --dry-run --limit-buckets 10   # size buckets, write nothing
python g_sweep.py --prefixes 0107                # one bucket
python g_sweep.py                                # full sweep, all 78 seeds
```

## Pipeline stages

| Stage | Where | Status |
|---|---|---|
| 1 DISCOVER | `g_sweep.py` (drives `f_main`) | built |
| 2 ENRICH | `b_main.get_company_data()` | **not built** — see below |
| 3 NORMALIZE | `g_store.normalize_row()` | built |
| 4 STORE | `g_store.py` → SQLite | built |
| 5 EXPORT | `g_main.py export` | built (CSV/JSON) |

Stage 2 is intentionally deferred. Process `b` returns 88 fields including
address, phone, email and directors — but on the one company sampled so far
(OSOTSPA) `phoneNo`, `email` and `webSite1-4` were all null. Measure the real
fill rate on ~20 companies before committing to a 31,725-company enrichment run.

## The store

SQLite, keyed on `juristic_id`.

- `companies` — current state, 12 business fields + lineage + `first_seen_at` /
  `last_seen_at` / `last_changed_at` / `content_hash`
- `company_history` — every field-level change, appended
- `sweep_buckets` — per-prefix sweep progress, so coverage is auditable
- re-running a sweep **merges**; it never truncates

`content_hash` covers only the business fields, so re-seeing an unchanged row
updates `last_seen_at` without recording a spurious change.

## Stage 1: why ID-prefix sweeping

On 2026-09-16 DBD began rejecting the old broad seed keyword server-side —
`บริษัท` and `จำกัด` now return HTTP 400 *"please be more specific"*, and the
guard runs **before** filters, so filtering cannot rescue it.

Juristic-ID prefixes replace it:

- the search matches registration numbers as **substrings**, so querying prefix
  `P` returns a superset of companies whose ID starts with `P`; filtering locally
  with `startswith(P)` yields that bucket exactly, with nothing missed
- every company has exactly one 13-digit ID, so the union over prefixes covers
  the registry **exactly once** — coverage is provable, not inferred
- buckets shrink ~10× per added digit, so job size is tunable
- each bucket is independently resumable; an interruption costs one small bucket
  instead of a whole run's position

The sweep probes page 1 of a prefix, reads `totalPages`, then splits the bucket
(if over budget), marks it empty (only when page 1 *is* the whole bucket), or
pages through it.

Measured: ~3,200 pages for a full filtered sweep across 78 seed prefixes — the
same work as the April run, but in resumable units. Only `0105` needs splitting.

## Operational notes

- **Run non-headless** with `channel="chrome"`.
- **Never reuse a stale `storage_state.json`.** The April session file carried an
  Imperva visitor ID that had pulled ~32,000 records, plus five-month-dead
  session cookies; presenting it triggered `Access denied / Error 15`. A clean
  session passes.
- Keep per-session volume modest — Imperva tracks a persistent visitor ID.
- `g_sweep.py` seeds the API contract with one narrow search (`โอสถสภา`) purely
  to make DBD issue a valid token. That keyword is never swept.

## Outputs (all gitignored)

- `dbd_companies.sqlite3` — the store
- `crm_companies.csv` / `.json` — CRM exports

See `g_AI_Local_Context.md` for design detail, measurements and open issues.
