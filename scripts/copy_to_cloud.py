"""One-time copy of your local SQLite data into the cloud Postgres (Neon) database.

    set DATABASE_URL=postgres://...   (from Vercel → Storage → your database → .env.local tab)
    python scripts/copy_to_cloud.py

Copies research, posts, campaigns, DM deliveries, events and settings. Secrets (tokens) are NOT copied —
paste your Meta token in the cloud app's Settings. Unpublished drafts are marked "not rendered" because
their images live on this PC; re-render them in the cloud app. Safe to re-run: existing ids are skipped.
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "data" / "content_store.db"
URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
if not URL.startswith("postgres"):
    sys.exit("Set DATABASE_URL to your Neon/Vercel Postgres connection string first.")

sys.path.insert(0, str(ROOT / "src"))
from db.migrate_v2 import migrate  # noqa: E402  (DATABASE_URL set → creates the Postgres schema)

import psycopg  # noqa: E402

migrate()
src = sqlite3.connect(LOCAL)
src.row_factory = sqlite3.Row
TABLES = ["topics", "carousels", "campaigns", "dm_deliveries", "events", "settings"]
with psycopg.connect(URL) as pg:
    for t in TABLES:
        pg_cols = [r[0] for r in pg.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,))]
        rows = [dict(r) for r in src.execute(f"SELECT * FROM {t}")]
        n = 0
        for r in rows:
            r = {k: v for k, v in r.items() if k in pg_cols}
            if t == "carousels" and r.get("status") != "PUBLISHED":
                r["rendered_json"], r["guide_json"], r["rendered_at"] = "[]", "[]", ""
            if t == "settings" and r["key"] in ("dm_last_poll", "dm_last_error"):
                continue
            conflict = "(key)" if t == "settings" else "(id)"
            cols = ", ".join(r)
            cur = pg.execute(f"INSERT INTO {t} ({cols}) VALUES ({', '.join(['%s'] * len(r))}) ON CONFLICT {conflict} DO NOTHING", list(r.values()))
            n += cur.rowcount
        if t != "settings":
            pg.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE((SELECT MAX(id) FROM {t}), 1))")
        print(f"{t}: {n} of {len(rows)} rows copied")
print("Done. Open the cloud app, sign in, and paste your Meta token in Settings.")
