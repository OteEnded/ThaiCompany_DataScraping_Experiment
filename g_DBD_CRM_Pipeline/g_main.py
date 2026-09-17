"""Process g - DBD -> CRM pipeline.

Stage 4 (STORE) and Stage 5 (EXPORT) of the pipeline. Discovery/enrichment stay
in processes `f` and `b`; this module owns the durable system of record and the
CRM-facing exports.

Usage:
    python g_main.py import-csv --path "<folder or file>"
    python g_main.py stats
    python g_main.py export --out crm_companies.csv
    python g_main.py coverage
    python g_main.py changes --limit 50
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import g_store

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "dbd_companies.sqlite3"

# CRM-facing column order. Kept separate from the storage schema so the sink can
# change without touching the store.
CRM_COLUMNS = [
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
    "first_seen_at",
    "last_seen_at",
    "last_changed_at",
]


def iter_csv_files(path: Path):
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from sorted(path.glob("*.csv"))
    else:
        raise SystemExit(f"path not found: {path}")


def cmd_import_csv(args) -> None:
    conn = g_store.connect(Path(args.db))
    totals = Counter()
    per_file = []

    for f in iter_csv_files(Path(args.path)):
        counts = Counter()
        with f.open(encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                counts[g_store.upsert(conn, raw, source_ref=f.name)] += 1
        conn.commit()
        totals.update(counts)
        per_file.append((f.name, counts))
        print(
            f"  {f.name:34} inserted={counts['inserted']:<6} "
            f"changed={counts['changed']:<5} unchanged={counts['unchanged']:<6} "
            f"skipped={counts['skipped']}"
        )

    print("\n  TOTAL  inserted={} changed={} unchanged={} skipped={}".format(
        totals["inserted"], totals["changed"], totals["unchanged"], totals["skipped"]
    ))
    print("\n  store now holds:")
    for k, v in g_store.stats(conn).items():
        print(f"    {k:26} {v}")
    conn.close()


def cmd_stats(args) -> None:
    conn = g_store.connect(Path(args.db))
    for k, v in g_store.stats(conn).items():
        print(f"  {k:26} {v}")

    print("\n  top provinces:")
    for r in conn.execute(
        "SELECT province, COUNT(*) n FROM companies GROUP BY province "
        "ORDER BY n DESC LIMIT 10"
    ):
        print(f"    {str(r['province'])[:28]:30} {r['n']}")

    print("\n  field fill rates:")
    total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] or 1
    for f in g_store.BUSINESS_FIELDS:
        n = conn.execute(
            f"SELECT COUNT(*) FROM companies WHERE {f} IS NOT NULL AND {f} != ''"
        ).fetchone()[0]
        print(f"    {f:28} {n:>7} ({100 * n / total:5.1f}%)")
    conn.close()


def cmd_coverage(args) -> None:
    """Coverage by 4-digit ID prefix - the sweep's unit of work."""
    conn = g_store.connect(Path(args.db))
    rows = conn.execute(
        "SELECT substr(juristic_id,1,4) p, COUNT(*) n FROM companies "
        "GROUP BY p ORDER BY n DESC"
    ).fetchall()
    total = sum(r["n"] for r in rows)
    print(f"  {len(rows)} distinct 4-digit prefixes, {total} companies\n")
    print(f"  {'prefix':8} {'companies':>10} {'est.pages':>10}")
    for r in rows[: args.limit]:
        print(f"  {r['p']:8} {r['n']:>10} {-(-r['n'] // 10):>10}")
    if len(rows) > args.limit:
        print(f"  ... {len(rows) - args.limit} more")
    print(f"\n  estimated pages for a full filtered sweep: ~{sum(-(-r['n'] // 10) for r in rows)}")

    swept = conn.execute("SELECT COUNT(*) FROM sweep_buckets WHERE state='done'").fetchone()[0]
    print(f"  buckets marked done in sweep_buckets: {swept}")
    conn.close()


def cmd_changes(args) -> None:
    conn = g_store.connect(Path(args.db))
    rows = conn.execute(
        "SELECT h.*, c.company_name FROM company_history h "
        "LEFT JOIN companies c USING(juristic_id) "
        "ORDER BY h.changed_at DESC, h.id DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    if not rows:
        print("  no changes recorded yet")
    for r in rows:
        print(f"  {r['changed_at']}  {r['juristic_id']}  {str(r['company_name'])[:26]:28} "
              f"{r['field']}: {str(r['old_value'])[:20]} -> {str(r['new_value'])[:20]}")
    conn.close()


def cmd_export(args) -> None:
    conn = g_store.connect(Path(args.db))
    where, params = "", []
    if args.min_revenue is not None:
        where = "WHERE total_revenue_baht >= ?"
        params.append(args.min_revenue)

    rows = conn.execute(
        f"SELECT {','.join(CRM_COLUMNS)} FROM companies {where} ORDER BY juristic_id",
        params,
    ).fetchall()

    out = Path(args.out)
    if out.suffix.lower() == ".json":
        out.write_text(
            json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(CRM_COLUMNS)
            for r in rows:
                w.writerow([r[c] for c in CRM_COLUMNS])
    print(f"  exported {len(rows)} rows -> {out}")
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="DBD -> CRM pipeline store")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import-csv", help="merge CSV file(s) into the store")
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_import_csv)

    p = sub.add_parser("stats", help="store summary and field fill rates")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("coverage", help="coverage by 4-digit ID prefix")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("changes", help="recent field-level changes")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_changes)

    p = sub.add_parser("export", help="write a CRM-shaped CSV/JSON")
    p.add_argument("--out", default="crm_companies.csv")
    p.add_argument("--min-revenue", type=int, default=None)
    p.set_defaults(func=cmd_export)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
