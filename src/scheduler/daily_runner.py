"""Daily automation: in-process scheduler (Asia/Kolkata) + CLI entry point.

* research_time        → research job
* target_publish_time  → pipeline job (Review Mode: queue for approval; Auto Mode: publish if QC passes)
A slot fires once per day, and only within GRACE minutes of its time, so restarting the server late
never triggers a stale run.
"""

import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.append(str(Path(__file__).resolve().parent.parent))

from store import get_setting, get_settings, now_ist, set_setting, start_job  # noqa: E402
import workflow  # noqa: E402

GRACE = timedelta(minutes=30)
SLOTS = [("research", "research_time", workflow.run_research), ("pipeline", "target_publish_time", workflow.run_pipeline)]


def _at(hhmm: str, day: datetime) -> Optional[datetime]:
    try:
        h, m = map(int, hhmm.split(":")[:2])
        return day.replace(hour=h, minute=m, second=0, microsecond=0)
    except Exception:
        return None


def next_runs() -> Dict[str, str]:
    s, now = get_settings(), now_ist()
    out = {}
    for kind, key, _ in SLOTS:
        t = _at(s.get(key, ""), now)
        if t is None:
            continue
        done_today = s.get(f"last_{kind}_slot") == now.strftime("%Y-%m-%d")
        if t <= now or done_today:
            t += timedelta(days=1)
        out[kind] = t.isoformat()
    return out


def tick(now: Optional[datetime] = None) -> list:
    """Start any slot that is due. Returns the kinds started (used by tests)."""
    s, now = get_settings(), now or now_ist()
    if s.get("scheduler_enabled", "1") != "1":
        return []
    started = []
    for kind, key, fn in SLOTS:
        t = _at(s.get(key, ""), now)
        today = now.strftime("%Y-%m-%d")
        if t and t <= now < t + GRACE and s.get(f"last_{kind}_slot") != today:
            set_setting(f"last_{kind}_slot", today)
            if start_job(kind, fn, trigger="scheduled")["started"]:
                started.append(kind)
    return started


_dm_busy = threading.Lock()


def poll_dms(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Auto Comment-to-DM: scan every active campaign every dm_poll_minutes. Quiet unless something happens."""
    from automation.comment_responder import CommentResponder
    from store import execute, log_event, query
    s, now = get_settings(), now or now_ist()
    if s.get("auto_dm", "1") != "1":
        return {"skipped": "auto_dm off"}
    last = s.get("dm_last_poll", "")
    every = max(1, int(s.get("dm_poll_minutes", "2") or 2))
    if last and (now - datetime.fromisoformat(last)).total_seconds() < every * 60:
        return {"skipped": "not due"}
    camps = query("SELECT * FROM campaigns WHERE active=1 AND media_id!=''")
    set_setting("dm_last_poll", now.isoformat())
    if not camps or not _dm_busy.acquire(blocking=False):
        return {"skipped": "nothing to do"}
    try:
        r = CommentResponder()
        sent = 0
        for camp in camps:
            rep = r.scan_campaign(camp, dry_run=False, log=lambda *a: None)
            if not rep.get("success"):
                err = rep.get("error", "")
                if "does not exist" in err:  # post deleted / unreachable → stop polling it
                    execute("UPDATE campaigns SET active=0, updated_at=? WHERE id=?", (now.strftime("%Y-%m-%d %H:%M:%S"), camp["id"]))
                    log_event("dm", f"Auto-reply paused for “{camp['name']}”: Instagram says the post no longer exists", camp["id"])
                    set_setting("dm_last_error", "")
                    continue
                set_setting("dm_last_error", f"{now:%H:%M} {err[:200]}")
                continue
            set_setting("dm_last_error", "")
            if rep.get("skipped_own"):
                log_event("dm", f"Skipped {len(rep['skipped_own'])} comment(s) from your own account on “{camp['name'][:40]}” — Instagram can't DM itself; test from another account", camp["id"])
            n = len(rep["matches"]) + sum(1 for f in rep["followups"] if f.get("status"))
            if n:
                sent += n
                log_event("dm", f"“{camp['keyword']}”: {len(rep['matches'])} new comment(s), {n - len(rep['matches'])} follow-up(s)", camp["id"])
        return {"campaigns": len(camps), "actions": sent}
    finally:
        _dm_busy.release()


def start_scheduler(interval: int = 30):
    def loop():
        while True:
            try:
                tick()
                poll_dms()
            except Exception as e:  # never let the clock die
                print(f"[scheduler] {e}")
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True, name="scheduler").start()


class DailyAutomationEngine:
    """Kept for CLI / MCP compatibility."""

    def run_daily_pipeline(self) -> Dict[str, Any]:
        return start_job("pipeline", workflow.run_pipeline, trigger="cli", background=False)

    def get_setting(self, key: str, default: str) -> str:
        return get_setting(key, default)


if __name__ == "__main__":
    from db.migrate_v2 import migrate
    migrate()
    print(json.dumps(DailyAutomationEngine().run_daily_pipeline(), indent=2))
