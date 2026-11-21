"""Durable webhook inbox: Meta event → row in webhook_events → QStash → process_event() (idempotent).

* The webhook request only verifies, stores and enqueues (no Graph API calls), so Meta always gets a fast 200.
* Duplicate deliveries are absorbed by UNIQUE(event_key) / UNIQUE(comment_id): only a newly stored event is queued.
* process_event() claims a row atomically (UPDATE … WHERE status IN …), so QStash retries or a sweep never run it twice at once.
* If QStash is down or not configured, events stay PENDING and sweep() picks them up (scheduler tick / dashboard). Nothing is dropped.
All timestamps in this table are UTC.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import qstash_client
from config import ON_VERCEL
from store import log_event, one, query, update, utc_now

PROCESS_PATH = "/api/queue/webhook-event"
MAX_ATTEMPTS = 5          # then the event stays FAILED for a human to look at (retry from the dashboard)
STALE_PROCESSING_MIN = 5  # a processor can't run longer than the 300 s function limit
REQUEUE_AFTER_MIN = 10    # QUEUED but never delivered (QStash outage, quota) → enqueue again


def _utc_minus(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- parse + store
def parse(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Meta payload → normalised events. Comments carry their own data (id, text, from, media)."""
    for entry in payload.get("entry") or []:
        acct = str(entry.get("id", ""))
        for ch in entry.get("changes") or []:
            v = ch.get("value") or {}
            if ch.get("field") in ("comments", "live_comments") and v.get("id"):
                frm = v.get("from") or {}
                yield {"event_key": f"comment:{v['id']}", "comment_id": str(v["id"]), "kind": "comment", "field": ch["field"],
                       "ig_account_id": acct, "media_id": str((v.get("media") or {}).get("id", "")), "sender_id": str(frm.get("id", "")),
                       "sender_username": frm.get("username", ""), "text": v.get("text") or "", "event_time": str(entry.get("time", "")), "raw": ch}
        for m in entry.get("messaging") or []:
            msg, pb = m.get("message") or {}, m.get("postback") or {}
            if msg.get("is_echo"):  # our own outgoing DM echoed back
                continue
            sender = str((m.get("sender") or {}).get("id", ""))
            mid = msg.get("mid") or pb.get("mid") or f"{sender}:{m.get('timestamp', '')}"
            text = (msg.get("quick_reply") or {}).get("payload") or msg.get("text") or pb.get("payload") or pb.get("title") or ""
            yield {"event_key": f"message:{mid}", "comment_id": None, "kind": "message", "field": "messages", "ig_account_id": acct,
                   "media_id": "", "sender_id": sender, "sender_username": "", "text": text, "event_time": str(m.get("timestamp", "")), "raw": m}


def store(events: Iterable[Dict[str, Any]]) -> List[int]:
    """Insert each event once. Returns ids of events that are NEW (duplicates return nothing)."""
    new = []
    for e in events:
        n = update("""INSERT OR IGNORE INTO webhook_events (event_key, comment_id, kind, field, ig_account_id, media_id, sender_id,
                      sender_username, text, event_time, raw_json, status, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,'PENDING',?)""",
                   (e["event_key"], e["comment_id"], e["kind"], e["field"], e["ig_account_id"], e["media_id"], e["sender_id"],
                    e["sender_username"], e["text"][:2000], e["event_time"], json.dumps(e["raw"])[:20000], utc_now()))
        if n:
            new.append(one("SELECT id FROM webhook_events WHERE event_key=?", (e["event_key"],))["id"])
    return new


def _background(fn: Callable, *args):
    """Local app only (a long-lived process); serverless never uses this."""
    threading.Thread(target=fn, args=args, daemon=True, name="webhook-event").start()


# ---------------------------------------------------------------- queue
def enqueue(event_id: int, dedup: str = "") -> Dict[str, Any]:
    r = qstash_client.publish(PROCESS_PATH, {"event_id": event_id}, dedup_id=dedup or f"wh-event-{event_id}")
    if r["ok"]:
        update("UPDATE webhook_events SET status='QUEUED', queued_at=?, qstash_message_id=?, error='' WHERE id=? AND status IN ('PENDING','FAILED','QUEUED')",
               (utc_now(), r.get("message_id", ""), event_id))
    else:
        update("UPDATE webhook_events SET error=? WHERE id=? AND status='PENDING'", (f"Not queued yet: {r['error']}"[:500], event_id))
    return r


def dispatch(event_ids: List[int]) -> Dict[str, int]:
    """Called right after storing. QStash when configured; locally without QStash a background thread; otherwise PENDING for sweep()."""
    out = {"queued": 0, "pending": 0, "local": 0}
    for eid in event_ids:
        if qstash_client.configured():
            out["queued" if enqueue(eid)["ok"] else "pending"] += 1
        elif not ON_VERCEL:
            _background(process_event, eid)
            out["local"] += 1
        else:
            update("UPDATE webhook_events SET error='Not queued: QStash is not configured; the scheduler sweep will process it' WHERE id=?", (eid,))
            out["pending"] += 1
    return out


# ---------------------------------------------------------------- process (idempotent)
def _default_handler(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Per-event comment-to-DM (Phase 4 engine): verifies the comment with Instagram, claims it, sends at most one private reply."""
    from automation import dm_engine
    return dm_engine.handle_event(ev)


HANDLER: Callable[[Dict[str, Any]], Dict[str, Any]] = _default_handler


def process_event(event_id: int) -> Tuple[int, Dict[str, Any]]:
    """→ (http_status, result). 500 only for a retryable failure, so QStash retries; everything else 200."""
    claimed = update("""UPDATE webhook_events SET status='PROCESSING', processing_started_at=?, attempts=attempts+1
                        WHERE id=? AND attempts < ? AND (status IN ('PENDING','QUEUED','FAILED')
                        OR (status='PROCESSING' AND processing_started_at < ?))""",
                     (utc_now(), event_id, MAX_ATTEMPTS, _utc_minus(STALE_PROCESSING_MIN)))
    ev = one("SELECT * FROM webhook_events WHERE id=?", (event_id,))
    if not ev:
        return 200, {"skipped": "unknown event"}
    if not claimed:
        return 200, {"skipped": f"event is {ev['status']} (attempts {ev['attempts']})"}
    try:
        res = HANDLER(ev) or {}
        status = res.pop("status", "PROCESSED")
        update("UPDATE webhook_events SET status=?, processed_at=?, result_json=?, error='' WHERE id=?",
               (status, utc_now(), json.dumps(res, default=str)[:5000], event_id))
        return 200, {"status": status, **res}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:500]
        update("UPDATE webhook_events SET status='FAILED', error=? WHERE id=?", (msg, event_id))
        last = ev["attempts"] >= MAX_ATTEMPTS
        if last:
            log_event("dm", f"Webhook event #{event_id} failed {MAX_ATTEMPTS} times: {msg[:120]}", event_id)
        return (200 if last else 500), {"status": "FAILED", "error": msg, "final": last}


# ---------------------------------------------------------------- recovery
def sweep(limit: int = 25, inline: Optional[bool] = None) -> Dict[str, Any]:
    """Re-drive events that never finished: PENDING (QStash down/not configured), QUEUED but never delivered,
    PROCESSING but stale, FAILED with attempts left. Re-enqueues via QStash, or processes inline when QStash isn't set up."""
    inline = (not qstash_client.configured()) if inline is None else inline
    rows = query("""SELECT id, status, attempts FROM webhook_events WHERE attempts < ? AND (
                      (status='PENDING' AND received_at < ?) OR (status='QUEUED' AND queued_at < ?)
                      OR (status='PROCESSING' AND processing_started_at < ?) OR (status='FAILED' AND (processed_at='' OR processed_at < ?)))
                    ORDER BY id LIMIT ?""",
                 (MAX_ATTEMPTS, _utc_minus(1), _utc_minus(REQUEUE_AFTER_MIN), _utc_minus(STALE_PROCESSING_MIN), _utc_minus(2), limit))
    out = {"found": len(rows), "requeued": 0, "processed": 0, "errors": []}
    for r in rows:
        if inline:
            code, res = process_event(r["id"])
            out["processed"] += 1
            if code != 200:
                out["errors"].append({"id": r["id"], "error": res.get("error")})
        else:
            q = enqueue(r["id"], dedup=f"wh-event-{r['id']}-retry-{r['attempts']}-{utc_now()[:16]}")
            out["requeued"] += q["ok"]
            if not q["ok"]:
                out["errors"].append({"id": r["id"], "error": q["error"]})
    return out


def retry_failed(event_id: int) -> Dict[str, Any]:
    """Dashboard 'Retry' for an event that used all its attempts. Safe: delivery is idempotent per comment (dm_deliveries)."""
    n = update("UPDATE webhook_events SET status='PENDING', attempts=0, error='' WHERE id=? AND status='FAILED'", (event_id,))
    if not n:
        return {"ok": False, "error": "Only FAILED events can be retried"}
    return dispatch([event_id]) | {"ok": True}
