"""Idempotent schema migration (v2 + v3). Safe to run on every app start.

v2: topic provenance, adaptive carousel fields, settings, post_insights.
v3: verification + scoring fields, editable carousel design/caption fields,
    jobs + events (real automation history), Comment-to-DM campaigns + deliveries.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DB_PATH, LEGACY_CATEGORY_MAP, CMS_ROOT


def _add_cols(c, table, cols):
    existing = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    for name, decl in cols:
        if name not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
  id SERIAL PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL, url TEXT UNIQUE, description TEXT, pillar TEXT,
  opportunity_score REAL, created_at TEXT, status TEXT DEFAULT 'NEW', category TEXT DEFAULT 'AI Developer Tools',
  published_date TEXT, verified_date TEXT, why_it_matters TEXT, target_audience TEXT, practical_use_case TEXT,
  cost_type TEXT DEFAULT 'Free', stars INTEGER DEFAULT 0, language TEXT DEFAULT '', preview_image_url TEXT DEFAULT '',
  verification_status TEXT DEFAULT 'UNVERIFIED', verification_note TEXT DEFAULT '', usefulness INTEGER DEFAULT 0,
  relevance INTEGER DEFAULT 0, suggested_format TEXT DEFAULT '', suggested_slides INTEGER DEFAULT 0,
  facts_json TEXT DEFAULT '[]', source_kind TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS carousels (
  id SERIAL PRIMARY KEY, topic_id INTEGER, headline TEXT NOT NULL, caption TEXT NOT NULL, slide_count INTEGER DEFAULT 10,
  quality_score INTEGER, status TEXT DEFAULT 'PENDING_APPROVAL', scheduled_for TEXT, metricool_post_id TEXT, created_at TEXT,
  post_format TEXT DEFAULT 'CAROUSEL', slide_data_json TEXT DEFAULT '', permalink TEXT DEFAULT '', published_at TEXT DEFAULT '',
  error_message TEXT DEFAULT '', design_json TEXT DEFAULT '', hashtags TEXT DEFAULT '', cta_keyword TEXT DEFAULT '',
  resource_pack TEXT DEFAULT '', qc_json TEXT DEFAULT '', ig_media_id TEXT DEFAULT '', updated_at TEXT DEFAULT '',
  rendered_at TEXT DEFAULT '', reject_reason TEXT DEFAULT '', rendered_json TEXT DEFAULT '[]', guide_json TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_insights (
  id SERIAL PRIMARY KEY, post_id TEXT UNIQUE NOT NULL, impressions INTEGER DEFAULT 0, reach INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0, saved INTEGER DEFAULT 0, shares INTEGER DEFAULT 0, engagement_rate REAL DEFAULT 0.0, category TEXT,
  slide_count INTEGER, post_format TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id SERIAL PRIMARY KEY, kind TEXT NOT NULL, trigger TEXT DEFAULT 'manual', status TEXT DEFAULT 'RUNNING', stage TEXT DEFAULT '',
  progress INTEGER DEFAULT 0, started_at TEXT, finished_at TEXT, error TEXT DEFAULT '', log TEXT DEFAULT '', result_json TEXT DEFAULT '',
  ref_id INTEGER);
CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, ts TEXT, kind TEXT, message TEXT, ref TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS campaigns (
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, keyword TEXT NOT NULL, media_id TEXT DEFAULT '', carousel_id INTEGER,
  active INTEGER DEFAULT 0, private_reply TEXT DEFAULT '', follow_gate INTEGER DEFAULT 1, follow_gate_message TEXT DEFAULT '',
  resource_pack TEXT DEFAULT '', public_reply_enabled INTEGER DEFAULT 0, public_reply_text TEXT DEFAULT '', created_at TEXT,
  updated_at TEXT DEFAULT '', guide_images TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS dm_deliveries (
  id SERIAL PRIMARY KEY, campaign_id INTEGER, comment_id TEXT UNIQUE, username TEXT DEFAULT '', igsid TEXT DEFAULT '',
  comment_text TEXT DEFAULT '', status TEXT DEFAULT 'MATCHED', follower_status TEXT DEFAULT 'UNKNOWN', error TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT DEFAULT '', user_msgs INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
"""


def migrate_pg():
    from store import get_db, ts
    with get_db() as c:
        c.raw.execute("SELECT pg_advisory_xact_lock(727274)")  # serverless instances start in parallel; one migrates at a time
        for stmt in [x.strip() for x in PG_SCHEMA.split(";") if x.strip()]:
            c.raw.execute(stmt)
        for k, v in {**DEFAULTS, "theme_v4": "1", "ts_ist": "1"}.items():
            c.raw.execute("INSERT INTO settings (key, value, updated_at) VALUES (%s, %s, %s) ON CONFLICT (key) DO NOTHING", (k, v, ts()))


DEFAULTS = {
    "publishing_mode": "REVIEW",
    "target_publish_time": "19:00",
    "research_time": "17:30",
    "timezone": "Asia/Kolkata",
    "min_qc_score": "85",
    "max_posts_per_day": "1",
    "auto_categories": "AI Industry News,Trending GitHub,AI Developer Tools,AI Creator Tools,Video & Animation,Open-Source Projects,Tutorials & Workflows",
    "scheduler_enabled": "1",
    "max_research_items": "40",
    "default_cta_keyword": "AGENT",
    "default_hashtags": "#AITools #AIAgents #OpenSource #GitHub #AIForCreators #Automation",
    "default_theme": "midnight",
    "default_accent": "#4C7DFF",
    "brand_name": "SONU AI LAB",
    "creator_handle": "@sonu2967_02",
    "auto_dm": "1",
    "dm_follow_gate": "1",
    "dm_poll_minutes": "2",
    "dm_opener": "Hi! Thanks for commenting 😊\nTap below and I'll send you the full guide ✨",
    "dm_not_following": "Oops! Looks like you haven't followed yet 👀\nFollow the account, then tap the button below and I'll send it right away.",
}


def migrate(db_path=None):
    from store import IS_PG
    if IS_PG:
        return migrate_pg()
    db_path = Path(db_path or DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, source TEXT NOT NULL,
        url TEXT UNIQUE, description TEXT, pillar TEXT, opportunity_score INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'NEW')""")
    c.execute("""CREATE TABLE IF NOT EXISTS carousels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, topic_id INTEGER, headline TEXT NOT NULL,
        caption TEXT NOT NULL, slide_count INTEGER DEFAULT 10, quality_score INTEGER,
        status TEXT DEFAULT 'PENDING_APPROVAL', scheduled_for TEXT, metricool_post_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (topic_id) REFERENCES topics (id))""")

    _add_cols(c, "topics", [
        ("category", "TEXT DEFAULT 'AI Developer Tools'"), ("published_date", "TEXT"),
        ("verified_date", "TEXT"), ("why_it_matters", "TEXT"), ("target_audience", "TEXT"),
        ("practical_use_case", "TEXT"), ("cost_type", "TEXT DEFAULT 'Free'"),
        ("stars", "INTEGER DEFAULT 0"), ("language", "TEXT DEFAULT ''"),
        ("preview_image_url", "TEXT DEFAULT ''"),
        # v3
        ("verification_status", "TEXT DEFAULT 'UNVERIFIED'"), ("verification_note", "TEXT DEFAULT ''"),
        ("usefulness", "INTEGER DEFAULT 0"), ("relevance", "INTEGER DEFAULT 0"),
        ("suggested_format", "TEXT DEFAULT ''"), ("suggested_slides", "INTEGER DEFAULT 0"),
        ("facts_json", "TEXT DEFAULT '[]'"), ("source_kind", "TEXT DEFAULT ''"),
    ])
    _add_cols(c, "carousels", [
        ("post_format", "TEXT DEFAULT 'CAROUSEL'"), ("slide_data_json", "TEXT DEFAULT ''"),
        ("permalink", "TEXT DEFAULT ''"), ("published_at", "TEXT DEFAULT ''"),
        ("error_message", "TEXT DEFAULT ''"),
        # v3
        ("design_json", "TEXT DEFAULT ''"), ("hashtags", "TEXT DEFAULT ''"),
        ("cta_keyword", "TEXT DEFAULT ''"), ("resource_pack", "TEXT DEFAULT ''"),
        ("qc_json", "TEXT DEFAULT ''"), ("ig_media_id", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''"), ("rendered_at", "TEXT DEFAULT ''"),
        ("reject_reason", "TEXT DEFAULT ''"),
    ])

    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    defaults = DEFAULTS
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    # Old default list used retired category names
    c.execute("UPDATE settings SET value=? WHERE key='auto_categories' AND value LIKE '%Creator & Video Tools%'",
              (defaults["auto_categories"],))

    c.execute("""CREATE TABLE IF NOT EXISTS post_insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT UNIQUE NOT NULL, impressions INTEGER DEFAULT 0,
        reach INTEGER DEFAULT 0, likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0, saved INTEGER DEFAULT 0,
        shares INTEGER DEFAULT 0, engagement_rate REAL DEFAULT 0.0, category TEXT, slide_count INTEGER,
        post_format TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    # v3 tables
    c.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, trigger TEXT DEFAULT 'manual',
        status TEXT DEFAULT 'RUNNING', stage TEXT DEFAULT '', progress INTEGER DEFAULT 0,
        started_at TEXT, finished_at TEXT, error TEXT DEFAULT '', log TEXT DEFAULT '',
        result_json TEXT DEFAULT '', ref_id INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, message TEXT, ref TEXT DEFAULT '')""")
    c.execute("""CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, keyword TEXT NOT NULL,
        media_id TEXT DEFAULT '', carousel_id INTEGER, active INTEGER DEFAULT 0,
        private_reply TEXT DEFAULT '', follow_gate INTEGER DEFAULT 1, follow_gate_message TEXT DEFAULT '',
        resource_pack TEXT DEFAULT '', public_reply_enabled INTEGER DEFAULT 0, public_reply_text TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT '')""")
    c.execute("""CREATE TABLE IF NOT EXISTS dm_deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, comment_id TEXT UNIQUE,
        username TEXT DEFAULT '', igsid TEXT DEFAULT '', comment_text TEXT DEFAULT '',
        status TEXT DEFAULT 'MATCHED', follower_status TEXT DEFAULT 'UNKNOWN',
        error TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT '')""")

    # v3 stores IST wall-clock timestamps; shift rows written with SQLite's UTC CURRENT_TIMESTAMP once
    if not c.execute("SELECT 1 FROM settings WHERE key='ts_ist'").fetchone():
        c.execute("UPDATE carousels SET created_at=datetime(created_at, '+330 minutes') WHERE slide_data_json='' OR slide_data_json IS NULL")
        for table in ("topics", "campaigns", "dm_deliveries"):
            c.execute(f"UPDATE {table} SET created_at=datetime(created_at, '+330 minutes') WHERE created_at IS NOT NULL")
        c.execute("INSERT INTO settings (key, value) VALUES ('ts_ist', '1')")

    # v4: campaign guide images + button-flow tracking; posts default to the bright Studio 3D look
    _add_cols(c, "campaigns", [("guide_images", "TEXT DEFAULT '[]'")])
    _add_cols(c, "carousels", [("rendered_json", "TEXT DEFAULT '[]'"), ("guide_json", "TEXT DEFAULT '[]'")])
    c.execute("CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    _add_cols(c, "dm_deliveries", [("user_msgs", "INTEGER DEFAULT 0"), ("attempts", "INTEGER DEFAULT 0")])
    if not c.execute("SELECT 1 FROM settings WHERE key='theme_v4'").fetchone():
        c.execute("UPDATE settings SET value='studio' WHERE key='default_theme'")
        c.execute("INSERT INTO settings (key, value) VALUES ('theme_v4', '1')")

    # Normalise legacy categories
    for old, new in LEGACY_CATEGORY_MAP.items():
        c.execute("UPDATE topics SET category=? WHERE category=?", (new, old))

    # One-time import of the legacy hardcoded AGENT funnel so already-handled comments are never re-messaged
    if not c.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone() and db_path == DB_PATH:
        c.execute("""INSERT INTO campaigns (name, keyword, media_id, active, private_reply, follow_gate,
                     follow_gate_message, resource_pack, public_reply_enabled)
                     VALUES (?,?,?,?,?,?,?,?,0)""", (
            "AGENT — legacy funnel (imported, paused)", "AGENT", "18079972970567863", 0,
            "Thanks for commenting! Here is the resource pack you asked for:",
            1, "Follow the account, then reply DONE here and I will send the pack.",
            "https://github.com/anthropics/anthropic-quickstarts"))
        legacy = CMS_ROOT / "data" / "replied_comments.json"
        if legacy.exists():
            try:
                for cid in json.loads(legacy.read_text()):
                    c.execute("INSERT OR IGNORE INTO dm_deliveries (campaign_id, comment_id, status) VALUES (1, ?, 'LEGACY_PROCESSED')", (cid,))
            except Exception:
                pass

    conn.commit()
    conn.close()


if __name__ == "__main__":
    migrate()
    print("Migration complete.")
