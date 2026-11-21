"""Daily automation: in-process scheduler (Asia/Kolkata) + CLI entry point.

Production (Vercel) is driven by QStash schedules (scheduler/qstash_schedules.py); this module is the local
in-process clock and the fallback tick. Both run the same independent jobs from scheduler/jobs.py:
research · generate · publish_due · analytics · maintenance. Comment-to-DM is event-driven and not scheduled here.
"""

import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.append(str(Path(__file__).resolve().parent.parent))

from store import get_setting, get_settings, now_ist, recover_stale_jobs, set_setting, start_job  # noqa: E402
import workflow  # noqa: E402

GRACE = timedelta(minutes=30)  # a daily job only starts within 30 min of its time (a late restart never runs a stale job)


def next_runs() -> Dict[str, str]:
    from scheduler import jobs
    out = jobs.next_runs()
    out["pipeline"] = out.get("generate", "")  # older dashboard label ("next build")
    return out


def tick(now: Optional[datetime] = None) -> list:
    """Local in-process scheduler / Vercel fallback (/api/cron/tick). Runs the same split jobs QStash triggers in production:
    housekeeping, each daily job inside its window (retried with backoff), and publish_due when an approved post is due.
    Returns the kinds started (used by tests)."""
    from scheduler import jobs
    s, now = get_settings(), now or now_ist()
    try:  # housekeeping on every tick: orphaned jobs, posts stuck in Publishing, undelivered webhook events
        recover_stale_jobs(15)
        workflow.recover_stuck_publishing()
        from automation import webhook_inbox
        webhook_inbox.sweep()
    except Exception as e:
        print(f"[scheduler] recovery: {e}")
    if s.get("scheduler_enabled", "1") != "1":
        return []
    started = []
    for kind in jobs.due_daily(now, GRACE):
        code, res = jobs.run(kind, trigger="scheduled", now=now)
        if "skipped" not in res:
            started.append(kind)
    if workflow.due_post():
        code, res = jobs.run("publish_due", trigger="scheduled", now=now)
        if "skipped" not in res:
            started.append("publish_due")
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
