# g_AI_Local_Context.md

## Scope
Process `g` is the CRM-facing pipeline: it owns the durable system of record for
DBD company data and the exports that feed a CRM. Discovery and enrichment stay
in processes `f` and `b`; `g` does not reimplement the DBD contract.

Created 2026-09-16, after site revalidation showed that process `f`'s
single-broad-keyword seed had been blocked server-side by DBD.

## Why this process exists

Two problems made a separate store necessary:

1. **Output truncation.** `f_main.py`'s `IncrementalCSVWriter` opens with mode
   `"w"` (~line 117), so every run overwrites `result_packed.csv`. `resume_from_page`
   resumes *fetching* but nothing merges prior sessions. The 31,725 records
   collected over five April sessions survived only because they were manually
   copied to `Downloads/DBD Data/DBD Data Set 0/` after each run. The crashed
   2026-04-10 run truncated the working CSV to 10 rows, which is exactly the
   failure this store prevents.
2. **"Keep track" needs history.** A CRM feed needs to know what *changed*, not
   just what the latest snapshot says. CSV dumps cannot express that.

## Pipeline stages

```
STAGE 1  DISCOVER   g_sweep.py (drives f_main)  -> juristic-id universe + list fields
STAGE 2  ENRICH     (not built) b_main.get_company_data() per id
STAGE 3  NORMALIZE  g_store.normalize_row()
STAGE 4  STORE      g_store.py  -> SQLite, keyed on juristic_id, with history
STAGE 5  EXPORT     g_main.py export -> CRM-shaped CSV/JSON
```

Stage 2 is deliberately unbuilt. Process `b` returns 88 profile fields including
address, phone, email and directors, but on the one sampled company
(OSOTSPA, `0107561000081`) `phoneNo`, `email` and `webSite1-4` were all null.
Sample ~20 companies and measure real fill rates before committing to a
31,725-company enrichment run against an anti-bot-protected endpoint.

## Files
- `g_store.py` — schema, normalization, upsert with change detection
- `g_main.py` — CLI: `import-csv`, `stats`, `coverage`, `changes`, `export`
- `g_sweep.py` — Stage 1 adaptive juristic-ID prefix sweep
- `g_local_config.json` — API filters + 78 seed prefixes
- `dbd_companies.sqlite3` — the store (gitignored)

## Store design

`companies` is keyed on `juristic_id`, so re-running a sweep merges rather than
overwrites. `content_hash` is computed over the 12 business fields only, so
re-seeing an unchanged row bumps `last_seen_at` without registering a change.
Every field-level difference is appended to `company_history`.

Two normalizations are applied on the way in:
- money fields: the single `navigate_ui` export writes `42000000.0` where
  `api_replay` exports write `42000000`; both land on the same integer
- column aliases: April exports carry the misspelled headers `data_retreive_at`
  and `data_retrieve_approch`. Process `f` must keep those spellings for
  compatibility, so `g_store.COLUMN_ALIASES` maps them to `data_retrieved_at`
  and `data_source_approach` at import instead of renaming at the source.

`sweep_buckets` records per-prefix progress, which makes a sweep resumable and
its coverage auditable rather than inferred.

## Migration result (2026-09-16)
Imported all 18 archived CSVs from `Downloads/DBD Data/DBD Data Set 0/`:

```
inserted=31725  changed=1  unchanged=534  skipped=0
```

- 31,725 matches the independently counted unique-id total exactly
- 534 unchanged = the intentional page-range overlap duplicates, merged silently
- 1 changed = a genuine company rename caught across two overlapping April files:
  `0105567140354` หนิงโป หงหยวน คอนสตรัคชั่น -> ซิงเซิ่ง คอนสตรัคชั่น (ไทย)
- all 12 business fields are 100% filled across all 31,725 rows
- 77 provinces, 862 business type codes, 78 four-digit id prefixes

## Stage 1: adaptive ID-prefix sweep

DBD blocked the old seed (`บริษัท`, `จำกัด` -> HTTP 400, guard runs before
filters). ID prefixes replace it because:
- search matches registration numbers as SUBSTRINGS, so prefix `P` returns a
  superset of ids starting with `P`; filtering locally with `startswith(P)` gives
  that exact bucket with nothing missed
- every company has exactly one 13-digit id, so the union over prefixes covers
  the registry exactly once — provable coverage
- bucket size shrinks ~10x per digit, so jobs are tunable

Algorithm: probe page 1 of a prefix, read `totalPages`, then either
- `> --max-pages` -> mark `split`, push the ten children `P0..P9` onto the queue
- `totalPages <= 1` and 0 on-prefix rows -> mark `empty`, skip. The bound is
  deliberate: results are ordered by company NAME, not by juristic id, so
  on-prefix rows can land on any page. Concluding 'empty' from page-1 evidence
  alone would silently drop rows from a multi-page bucket; it is only sound
  when page 1 is the entire bucket.
- otherwise page through, keeping only rows where `juristic_id.startswith(P)`

Sizing (measured against the live API, production filters applied):
- `0105` unfiltered 70,406 pages; filtered 1,702 — filters cut it ~41x
- `0105` is the only seed bucket exceeding a 200-page budget. Verified against
  the store: its real children are `01054` (68 companies) and `01055`
  (16,658); `01050`-`01053` hold nothing and are correctly marked empty.
  `01055` still exceeds the budget and splits again one digit deeper.
- 48 of 78 buckets hold <= 100 companies
- full sweep ~3,200 pages, cross-validating within 2% against the April run's
  3,188 pages

## Operational notes
- Run non-headless with `channel="chrome"`. Do NOT reuse a stale
  `storage_state.json`: the April session carried an Imperva visitor id that had
  pulled ~32,000 records plus five-month-dead session cookies, and presenting it
  triggered `Access denied / Error 15`.
- `g_sweep.py` seeds the API contract with one narrow search (`โอสถสภา`). That
  keyword only exists to make DBD issue a valid token; it is never swept.
- Keep per-session volume modest. Imperva tracks a persistent visitor id, and the
  April pattern (32,000 records through one identity over five days) is what got
  that identity flagged.

## Known gaps / next steps
1. Stage 2 enrichment is unbuilt pending a contact-field fill-rate sample.
2. The CRM sink is undecided; `g_main.py export` writes CSV/JSON and
   `CRM_COLUMNS` is intentionally separate from the storage schema so an API
   adapter can be added without touching the store.
3. Pages 232-233 are the only genuine gaps in the archived April coverage.
4. No rate-limit pacing beyond fixed waits (1.2s between pages, 1.5s between
   buckets); tune against observed Imperva behaviour.
5. `g_sweep.py` has no mid-bucket resume — an interrupted bucket is marked
   `partial` and re-runs from page 1. Acceptable while buckets stay small.
6. Sparse multi-page buckets are swept in full rather than sampled, which
   costs some wasted fetches. That is the deliberate price of not risking
   dropped rows; see the `empty` rule above.
