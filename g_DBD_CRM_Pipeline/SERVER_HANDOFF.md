# Server Handoff — DBD CRM Pipeline

> For whoever (human or Claude Code) runs this pipeline on a server.
> Written 2026-09-17 after sets 1–2 completed on a Windows workstation.
>
> **Read `HOW_IT_WORKS.md` first** for the mechanism. This file covers only what
> changes when moving to a server.

---

## ⚠️ Blocker #1 — the sweep needs a display

`g_sweep.py` launches **non-headless Chrome**. On a headless Linux server there is
no X display and Playwright will fail to launch.

**Do NOT just set `--headless`.** It has never been tested against DBD, and
`b_AI_Local_Context.md` records that headless runs get blocked by Imperva where
non-headless runs succeed. Switching to headless as a convenience is the single
most likely way to break this pipeline on day one.

**Use a virtual display instead:**

```bash
sudo apt-get install -y xvfb
xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  python g_sweep.py --sets set3 ...
```

Or run a persistent display:

```bash
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
python g_sweep.py --sets set3 ...
```

If you must try headless, treat it as an experiment: run **one small bucket**
(`--prefixes 0755 --set set3`) and confirm `status=200` with real rows before
trusting it. Record the result in `g_AI_Local_Context.md` either way — that
answers a question this project has never resolved.

## ⚠️ Blocker #2 — real Chrome, not bundled Chromium

The code uses `channel="chrome"`, i.e. **Google Chrome**, not Playwright's
bundled Chromium. This was a deliberate fix: bundled Chromium has a different UA
and missing codecs, and contributed to the Imperva block on 2026-09-16.

```bash
# Debian/Ubuntu
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt-get update && sudo apt-get install -y google-chrome-stable

# then
pip install playwright cryptography requests
python -m playwright install-deps
```

`python -m playwright install chromium` is **not** sufficient on its own — the
code asks for the `chrome` channel specifically.

---

## What to move

### 1. The whole repository, not just this folder

`g_sweep.py` and `g_session.py` import `f_main` from the sibling folder:

```python
sys.path.insert(0, str(BASE_DIR.parent / "f_DBD_Company_List_Scraper_WIth_Filter"))
import f_main
```

The DBD API contract, decrypt, and request replay all live in process `f`. Moving
only `g_DBD_CRM_Pipeline/` will fail on import.

### 2. The SQLite store — gitignored, must be copied by hand

```
g_DBD_CRM_Pipeline/dbd_companies.sqlite3       ~90 MB   ← the data
g_DBD_CRM_Pipeline/dbd_companies.sqlite3-wal   ~5 MB    ← recent writes
g_DBD_CRM_Pipeline/dbd_companies.sqlite3-shm            ← shared memory index
```

**Checkpoint the WAL before copying**, or copy all three files together.
Copying only the `.sqlite3` file loses everything still in the WAL:

```bash
# with the sweep STOPPED:
python -c "import sqlite3; c=sqlite3.connect('dbd_companies.sqlite3'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
# now dbd_companies.sqlite3 is self-contained and safe to copy alone
```

Verify after the move:

```bash
python g_main.py stats      # company count must match the source machine
```

### 3. Not needed on the server

`crm_companies.csv` is a generated snapshot — regenerate with
`python g_main.py export`. Runtime artifacts (`sweep_sets123.log`,
`last_page_*.png`, `last_run.log`) are disposable.

---

## Running on the server

```bash
cd g_DBD_CRM_Pipeline

# check what remains
python g_sweep.py --list-sets
python g_main.py coverage

# resume (adjust --sets to what is unfinished)
xvfb-run -a python g_sweep.py --sets set3 \
    --max-pages 200 --rotate-after-pages 1500 --reseed-after-seconds 540 \
    --page-delay-ms 1800 --bucket-delay-ms 3000
```

Long runs survive disconnects with `nohup`, `tmux` or `screen`:

```bash
nohup xvfb-run -a python g_sweep.py --sets set3 ... >> sweep.log 2>&1 &
```

### Non-negotiable parameters

| flag | value | why |
|---|---|---|
| `--page-delay-ms` | **≥1800** | 1200ms triggered HTTP 429 after 23 min |
| `--reseed-after-seconds` | **540** | the JWT expires at ~900s; 540 leaves margin |
| `--rotate-after-pages` | 1500 | keeps any one Imperva visitor ID under ~15k records |

Lowering the page delay will trip rate limiting. The backoff handles it, but
throughput gets worse, not better.

### Rules when resuming

1. **Do not edit `g_sets_config.json` filters.** Bucket completion is keyed on
   `(prefix, filters_hash)`. Changing a filter makes every completed bucket for
   that set look unfinished and it re-sweeps from scratch.
2. **Pass every set you want run.** `--sets set3` alone will not touch set4.
3. Buckets left `running`/`partial`/`error` by an interruption re-run from page 1
   automatically — they are not in the skip list. No manual reset needed, though
   resetting them to `pending` makes `coverage` read more honestly.

---

## State as of this handoff (2026-09-17)

```
companies        107,941        <- sets 1-3 COMPLETE and verified
collected today   76,216        (April baseline was 31,725)
changes logged   110,501
duplicate ids          0

set1  ✅ complete   2,674 pages · 19,939 rows · 19,966 in band (est 20,000)
set2  ✅ complete   6,920 pages · 53,038 rows · 53,059 in band (est 52,000)
set3  ✅ complete   4,008 pages · 29,965 in band (est 29,000)
set4-7   not started (~688,000 companies, ~76 hours at ~150 rec/min)
```

Verification run 2026-09-17, all checks PASS:
- no `running`/`partial`/`error` buckets in any set
- all 78 seed prefixes resolved in each of set1/set2/set3
- all 26 split parents have 10 resolved children
- 0 duplicate juristic_ids; `PRAGMA integrity_check` = ok
- all three capital bands within 3.3% of the planning estimates

Sets 1-3 now cover every operating Thai company (บริษัทจำกัด + บริษัทมหาชนจำกัด)
with registered capital ≥5M. The store is WAL-checkpointed and self-contained.

---

## Known issues to be aware of

1. **Sparse-prefix waste.** A 4-digit prefix matches mid-ID substrings, so sparse
   provincial prefixes pull in Bangkok noise. Worst observed: `0555` cost ~900
   pages for ~30 rows, because `0555` appears inside every `010555…` Bangkok ID.
   Overall set2 efficiency was still 83%.

   **A possible optimization, deliberately NOT applied:** the province is encoded
   in the prefix (`0555` → province 55), and the API has a server-side
   `pvCodeList` filter. Adding it per-bucket would strip the cross-province noise
   and could cut `0555` from ~900 pages to ~3. **The risk:** a company's ID
   province is fixed at registration but its current province can change — the
   history table already shows 4 relocations. Filtering by `pvCodeList` would
   silently drop those. Validate with a two-pass approach (filtered sweep for
   speed, unfiltered pass on affected prefixes for relocations) before trusting
   it. Worth doing before sets 4–7; not worth the correctness risk for sets 1–3.

2. **No mid-bucket resume.** An interrupted bucket restarts from page 1. Capped at
   200 pages, so worst case ~10 minutes of re-fetching.

2b. **Network drops are handled, but note why.** On 2026-09-17 the workstation
   slept mid-run; Playwright raised `net::ERR_NETWORK_CHANGED` during a token
   re-seed and it propagated past the sweep's handler, ending the run. Chromium
   net errors are now classified as recoverable (discard the browser, open a new
   one) and `SweepSession.open()` retries 3x with 15s/45s/90s backoff so a blip
   does not kill a long run. Relevant on a server too - VPN flaps and transient
   DNS failures produce the same errors.

3. **Stage 2 enrichment unbuilt.** Process `b` returns 88 fields including
   address, phone, email and directors — but on the one company sampled
   (OSOTSPA), `phoneNo`, `email` and `webSite1-4` were all null. Sample ~20
   companies and measure fill rates before committing to a six-figure enrichment
   run.

4. **CRM sink undecided.** `g_main.py export` writes CSV/JSON; `CRM_COLUMNS` is
   kept separate from the storage schema so an API adapter drops in without
   touching the store.

---

## For a fresh Claude Code instance

Read in this order:

1. `AI_CarryOn.md` (repo root) — project-wide state and history
2. `g_DBD_CRM_Pipeline/HOW_IT_WORKS.md` — the mechanism, with diagrams
3. `g_DBD_CRM_Pipeline/g_AI_Local_Context.md` — process-g design detail
4. `f_DBD_Company_List_Scraper_WIth_Filter/f_AI_Local_Context.md` — the DBD
   contract, the 2026-09-16 diagnosis, and the measured guard behaviour
5. This file

**Context you cannot get from the code:**

- DBD blocklists the keywords `บริษัท` and `จำกัด` server-side (HTTP 400). Any
  approach that seeds on a generic legal-form word is dead. This is why the
  ID-prefix sweep exists.
- Never reuse a stale `storage_state.json`. An April session file caused
  `Access denied / Error 15` because it carried a five-month-old Imperva visitor
  ID that had pulled ~32,000 records.
- TSIC business-type codes were tested as a partition key and **disproved**
  (30% on-target, ~25× count shortfall). Do not revisit.
- The API page size is hard-locked at 10. `pageSize`, `size`, `limit`,
  `perPage`, `rowsPerPage`, `itemsPerPage` are all ignored.
- HTTP 429 is a short cooldown (~2 min), not a daily quota — verified by probe.
- The commit convention is `OteEnded[type]: description`, and the project policy
  is **do not commit or push unless the user explicitly asks**.
