"""SQLite access, settings, event log and the background job runner."""

import json
import sqlite3
import threading
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from config import DB_PATH, IST


def now_ist() -> datetime:
    return datetime.now(IST)


def ts() -> str:
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, args=()) -> list:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(sql: str, args=()) -> Optional[dict]:
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args=()) -> int:
    conn = get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


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

    if background:
        threading.Thread(target=run, daemon=True, name=f"job-{kind}-{job_id}").start()
    else:
        run()
    return {"started": True, "job_id": job_id}


def recover_stale_jobs():
    """Jobs left RUNNING by a previous process can never finish."""
    execute("UPDATE jobs SET status='FAILED', error='Interrupted: server restarted', finished_at=? WHERE status='RUNNING'", (ts(),))
