"""Database access (SQLite locally, Postgres on Vercel), settings, event log and the background job runner."""

import json
import os
import re
import sqlite3
import threading
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from config import DB_PATH, IST, ON_VERCEL


def now_ist() -> datetime:
    return datetime.now(IST)


def ts() -> str:
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")


# DATABASE_URL (Neon/Vercel Postgres) switches the whole app to Postgres; otherwise the local SQLite file.
PG_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
IS_PG = PG_URL.startswith("postgres")
_INSERT_TABLE = re.compile(r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", re.I)


def to_pg(sql: str) -> str:
    """Translate the small SQLite dialect this app uses into Postgres."""
    s = sql
    if re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+settings", s, re.I):
        s = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", s, flags=re.I)
        s = s.rstrip().rstrip(";") + " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    elif re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", s, re.I):
        s = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", s, flags=re.I)
        s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    s = s.replace("CURRENT_TIMESTAMP", "to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS')")
    s = s.replace("%", "%%").replace("?", "%s")
    return s


class _Result:
    def __init__(self, rows, rowcount, lastrowid):
        self._rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class Conn:
    """Same surface as sqlite3.Connection for what this app uses: execute(), commit(), context manager."""

    def __init__(self):
        if IS_PG:
            import psycopg
            from psycopg.rows import dict_row
            self.raw = psycopg.connect(PG_URL, row_factory=dict_row, connect_timeout=15)
        else:
            self.raw = sqlite3.connect(DB_PATH, timeout=15)
            self.raw.row_factory = sqlite3.Row

    def execute(self, sql: str, args=()):
        if not IS_PG:
            return self.raw.execute(sql, args)
        q = to_pg(sql)
        m = _INSERT_TABLE.match(sql)
        if m and m.group(1).lower() not in ("settings", "secrets") and "RETURNING" not in q.upper():  # key-value tables have no id
            q += " RETURNING id"
        cur = self.raw.cursor()
        cur.execute(q, args)
        rows = cur.fetchall() if cur.description else []
        return _Result(rows, cur.rowcount, rows[0]["id"] if (m and rows) else None)

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc, *a):
        try:
            self.raw.rollback() if exc else self.raw.commit()
        finally:
            self.raw.close()


def get_db() -> Conn:
    return Conn()


def query(sql: str, args=()) -> list:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(sql: str, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args=()):
    with get_db() as conn:
        return conn.execute(sql, args).lastrowid


def get_secret(key: str) -> str:
    """Credentials saved from the UI (e.g. a renewed Meta token). Never part of /api/settings."""
    row = one("SELECT value FROM secrets WHERE key=?", (key,))
    return row["value"] if row else ""


def set_secret(key: str, value: str):
    if IS_PG:
        execute("INSERT INTO secrets (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))
    else:
        execute("INSERT OR REPLACE INTO secrets (key, value) VALUES (?, ?)", (key, value))


def get_settings() -> Dict[str, str]:
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}


def get_setting(key: str, default: str = "") -> str:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: Any):
    execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, str(value)))


def log_event(kind: str, message: str, ref: str = ""):
    execute("INSERT INTO events (ts, kind, message, ref) VALUES (?,?,?,?)", (ts(), kind, message, str(ref)))


# ---------------------------------------------------------------- jobs

class JobContext:
    def __init__(self, job_id: int):
        self.id = job_id
        self._log = []

    def stage(self, name: str, progress: int):
        self.log(f"→ {name}")
        execute("UPDATE jobs SET stage=?, progress=? WHERE id=?", (name, progress, self.id))

    def log(self, msg: str):
        self._log.append(f"[{now_ist().strftime('%H:%M:%S')}] {msg}")
        execute("UPDATE jobs SET log=? WHERE id=?", ("\n".join(self._log), self.id))


_running: Dict[str, int] = {}
_lock = threading.Lock()


def start_job(kind: str, fn: Callable[[JobContext], Any], trigger: str = "manual",
              ref_id: Optional[int] = None, background: bool = True) -> Dict[str, Any]:
    """Run fn in a thread, recording stage/progress/log/result in the jobs table.
    One job per kind at a time (ponytail: per-kind lock; per-ref locks if parallel publishes are ever needed)."""
    with _lock:
        if kind in _running:
            return {"started": False, "error": f"A {kind} job is already running", "job_id": _running[kind]}
        job_id = execute("INSERT INTO jobs (kind, trigger, status, started_at, ref_id) VALUES (?,?,?,?,?)",
                         (kind, trigger, "RUNNING", ts(), ref_id))
        _running[kind] = job_id

    def run():
        ctx = JobContext(job_id)
        try:
            result = fn(ctx) or {}
            failed = isinstance(result, dict) and result.get("success") is False
            execute("UPDATE jobs SET status=?, progress=?, finished_at=?, result_json=?, error=? WHERE id=?",
                    ("FAILED" if failed else "SUCCESS", 100, ts(), json.dumps(result, default=str),
                     (result.get("error") or "") if failed else "", job_id))
            log_event(kind, f"{kind} job #{job_id} {'failed: ' + str(result.get('error')) if failed else 'completed'}", job_id)
        except Exception as e:
            ctx.log(traceback.format_exc())
            execute("UPDATE jobs SET status='FAILED', finished_at=?, error=? WHERE id=?", (ts(), str(e), job_id))
            log_event(kind, f"{kind} job #{job_id} crashed: {e}", job_id)
        finally:
            with _lock:
                _running.pop(kind, None)

    if background and not ON_VERCEL:  # serverless: threads die with the request, so run inline
        threading.Thread(target=run, daemon=True, name=f"job-{kind}-{job_id}").start()
    else:
        run()
    return {"started": True, "job_id": job_id}


def recover_stale_jobs():
    """Jobs left RUNNING by a previous process can never finish."""
    execute("UPDATE jobs SET status='FAILED', error='Interrupted: server restarted', finished_at=? WHERE status='RUNNING'", (ts(),))
