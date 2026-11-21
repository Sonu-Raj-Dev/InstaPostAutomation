"""Scheduled jobs (Phase 5): research · generate · publish_due · analytics · maintenance. Comment processing is NOT here:
it runs per webhook event (automation/webhook_inbox.py).

Guarantees, all database-backed (serverless instances share nothing in memory):
* job_locks lease → at most one run of a kind at a time across instances; an expired lease (dead function) is taken over.
* jobs.slot_key → a daily job succeeds at most once per day (QStash redelivery / a second trigger is skipped).
* Every run is a row in `jobs` (execution history: trigger, slot, status, stage, log, result, error).
* Retries: under QStash a failed run returns HTTP 500 and QStash retries with exponential backoff (3 retries:
  ~12 s, ~2.5 min, ~30 min). The local/fallback tick retries with 2 → 4 → 8 min backoff, max 3 failures per slot.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import workflow
from config import IST
from store import now_ist, one, query, recover_stale_jobs, start_job, update

LEASE_MIN = 6          # longer than Vercel's 300 s function limit
MAX_SLOT_FAILURES = 3


def run_maintenance(ctx) -> Dict[str, Any]:
    """Recovery: orphaned jobs, posts stuck in Publishing (reconciled with Meta, never re-published), undelivered webhook events."""
    from automation import webhook_inbox
    out, errors = {}, []
    for name, step in (("stale_jobs", lambda: recover_stale_jobs(15)), ("stuck_posts", workflow.recover_stuck_publishing),
                       ("webhook_sweep", webhook_inbox.sweep)):
        try:  # each step runs even if another fails
            out[name] = step()
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}"[:300])
    ctx.log(f"maintenance: {out}" + (f"; errors: {errors}" if errors else ""))
    return {"success": not errors, **out, **({"error": "; ".join(errors)} if errors else {})}


JOBS: Dict[str, Dict[str, Any]] = {
    "research": {"fn": lambda ctx: workflow.run_research(ctx), "daily": True},
    "generate": {"fn": lambda ctx: workflow.run_generate(ctx), "daily": True},
    "publish_due": {"fn": lambda ctx: workflow.run_publish_due(ctx), "daily": False},
    "analytics": {"fn": lambda ctx: workflow.run_analytics(ctx), "daily": True},
    "maintenance": {"fn": run_maintenance, "daily": False},
}
DAILY = [k for k, v in JOBS.items() if v["daily"]]


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slot_key(kind: str, now: Optional[datetime] = None) -> str:
    return f"{kind}:{(now or now_ist()).astimezone(IST):%Y-%m-%d}" if JOBS[kind]["daily"] else ""


# ---------------------------------------------------------------- lease lock
def acquire(kind: str, minutes: int = LEASE_MIN) -> Optional[str]:
    holder, now = uuid.uuid4().hex, datetime.now(timezone.utc)
    update("INSERT OR IGNORE INTO job_locks (kind, holder, lease_until) VALUES (?, '', '')", (kind,))
    got = update("UPDATE job_locks SET holder=?, lease_until=? WHERE kind=? AND (lease_until='' OR lease_until IS NULL OR lease_until < ?)",
                 (holder, _utc(now + timedelta(minutes=minutes)), kind, _utc(now)))
    return holder if got else None


def release(kind: str, holder: str):
    update("UPDATE job_locks SET lease_until='', holder='' WHERE kind=? AND holder=?", (kind, holder))


# ---------------------------------------------------------------- run one job
def run(kind: str, trigger: str = "qstash", now: Optional[datetime] = None) -> Tuple[int, Dict[str, Any]]:
    """→ (http_status, result). 500 = failed and worth retrying (QStash retries); 200 otherwise (done, skipped, nothing to do)."""
    if kind not in JOBS:
        return 404, {"error": f"unknown job {kind}"}
    slot = slot_key(kind, now)
    if slot and one("SELECT id FROM jobs WHERE slot_key=? AND status='SUCCESS'", (slot,)):
        return 200, {"skipped": "already completed for this slot", "slot": slot}
    holder = acquire(kind)
    if not holder:
        return 200, {"skipped": f"a {kind} job is already running"}
    try:
        if slot and one("SELECT id FROM jobs WHERE slot_key=? AND status='SUCCESS'", (slot,)):  # re-check under the lock
            return 200, {"skipped": "already completed for this slot", "slot": slot}
        r = start_job(kind, JOBS[kind]["fn"], trigger=trigger, background=False, slot_key=slot)
    finally:
        release(kind, holder)
    if not r.get("started"):
        return 200, {"skipped": r.get("error", "not started")}
    job = one("SELECT id, status, error, result_json FROM jobs WHERE id=?", (r["job_id"],))
    failed = job["status"] == "FAILED"
    return (500 if failed else 200), {"job_id": job["id"], "kind": kind, "slot": slot, "status": job["status"], "error": job["error"]}


# ---------------------------------------------------------------- when is a daily job due (local thread / fallback tick)
def daily_at(kind: str, day: datetime) -> datetime:
    h, m = map(int, workflow.schedule_times()[{"research": "research", "generate": "generate", "analytics": "analytics"}[kind]].split(":"))
    return day.astimezone(IST).replace(hour=h, minute=m, second=0, microsecond=0)


def retry_allowed(slot: str, now: datetime) -> bool:
    """No success yet, fewer than MAX_SLOT_FAILURES failures, and the 2/4/8-minute backoff since the last failure has passed."""
    if one("SELECT id FROM jobs WHERE slot_key=? AND status IN ('SUCCESS','RUNNING')", (slot,)):
        return False
    fails = query("SELECT finished_at FROM jobs WHERE slot_key=? AND status='FAILED' ORDER BY id DESC", (slot,))
    if len(fails) >= MAX_SLOT_FAILURES:
        return False
    if fails and fails[0]["finished_at"]:
        last = datetime.strptime(fails[0]["finished_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)  # jobs timestamps are IST (legacy format)
        return now.astimezone(IST) >= last + timedelta(minutes=2 ** len(fails))
    return True


def due_daily(now: datetime, grace: timedelta) -> list:
    out = []
    for kind in DAILY:
        t = daily_at(kind, now)
        if t <= now.astimezone(IST) < t + grace and retry_allowed(slot_key(kind, now), now):
            out.append(kind)
    return out


def next_runs(now: Optional[datetime] = None) -> Dict[str, str]:
    """Next run per daily job (IST ISO), for the dashboard."""
    now = (now or now_ist()).astimezone(IST)
    out = {}
    for kind in DAILY:
        t = daily_at(kind, now)
        if t <= now or one("SELECT id FROM jobs WHERE slot_key=? AND status='SUCCESS'", (slot_key(kind, now),)):
            t += timedelta(days=1)
        out[kind] = t.isoformat()
    h, m = map(int, workflow.schedule_times()["publish"].split(":"))
    p = now.replace(hour=h, minute=m, second=0, microsecond=0)
    out["publish"] = (p if p > now else p + timedelta(days=1)).isoformat()
    return out
