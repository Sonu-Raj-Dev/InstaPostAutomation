"""Keep QStash schedules in line with the dashboard settings (Phase 5).

Five schedules, all ids prefixed "sal-" (only those are ever touched):
  sal-research   daily at Research time          → /api/queue/job/research
  sal-generate   daily at Generate time           → /api/queue/job/generate   (auto: 45 min before Publishing time)
  sal-publish    daily at Publishing time         → /api/queue/job/publish_due
  sal-analytics  daily at Analytics time          → /api/queue/job/analytics
  sal-tick       every 10 minutes                 → /api/queue/job/tick  (maintenance + posts scheduled for other times)
Cron runs in the dashboard timezone via CRON_TZ (default Asia/Kolkata), so no manual IST→UTC conversion is needed here.

Free-plan budget (verified 2026-11-21: 1,000 messages/day, 10 schedules): 4 daily + 144 ticks ≈ 148 messages/day,
plus retries only on failure. Leaves ~850/day for webhook events.
"""

import json
from typing import Any, Dict, Tuple

import qstash_client
import workflow
from store import get_settings, set_setting, utc_now

PREFIX = "sal-"
TICK_CRON = "*/10 * * * *"


def desired(s: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
    if s.get("scheduler_enabled", "1") != "1":
        return {}  # paused: all our schedules are removed
    tz = s.get("timezone") or "Asia/Kolkata"
    t = workflow.schedule_times(s)

    def daily(hhmm: str) -> str:
        h, m = hhmm.split(":")[:2]
        return f"CRON_TZ={tz} {int(m)} {int(h)} * * *"
    return {"sal-research": ("/api/queue/job/research", daily(t["research"])),
            "sal-generate": ("/api/queue/job/generate", daily(t["generate"])),
            "sal-publish": ("/api/queue/job/publish_due", daily(t["publish"])),
            "sal-analytics": ("/api/queue/job/analytics", daily(t["analytics"])),
            "sal-tick": ("/api/queue/job/tick", TICK_CRON)}


def sync() -> Dict[str, Any]:
    """Upsert every wanted schedule first (by fixed id → never duplicated), then delete only obsolete "sal-" schedules.
    Upsert-before-delete means there is never a moment with no schedule."""
    if not qstash_client.configured():
        out = {"ok": False, "error": "QStash is not configured (QSTASH_TOKEN). Scheduled jobs won't run on Vercel until it is."}
        set_setting("qstash_sync_error", out["error"])
        return out
    want = desired(get_settings())
    out: Dict[str, Any] = {"ok": True, "upserted": [], "deleted": [], "errors": []}
    for sid, (path, cron) in want.items():
        r = qstash_client.upsert_schedule(sid, path, cron)
        (out["upserted"].append({"id": sid, "cron": cron, "path": path}) if r["ok"] else out["errors"].append(f"{sid}: {r['error']}"))
    lst = qstash_client.list_schedules()
    if lst["ok"]:
        for sch in lst["schedules"]:
            sid = sch.get("scheduleId", "")
            if sid.startswith(PREFIX) and sid not in want:
                d = qstash_client.delete_schedule(sid)
                (out["deleted"].append(sid) if d["ok"] else out["errors"].append(f"delete {sid}: {d['error']}"))
    else:
        out["errors"].append(f"list: {lst['error']}")
    out["ok"] = not out["errors"]
    set_setting("qstash_sync_at", utc_now())
    set_setting("qstash_sync_error", "; ".join(out["errors"])[:500])
    set_setting("qstash_schedules", json.dumps(out["upserted"]))
    return out
