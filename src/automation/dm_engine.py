"""Comment-to-DM engine (Phase 4): one code path for webhook events and live scans.

Comment flow:  verify the comment with Instagram → match a campaign keyword (case-insensitive, several per campaign)
→ eligibility (not our own account, within Meta's 7-day private-reply window, commenter not already served by this campaign)
→ CLAIM the comment in dm_deliveries (UNIQUE comment_id) → only the claimer sends ONE private reply → record result + history.
DM flow (their tap / reply opens the 24 h window):  claim the waiting delivery (AWAITING_* → DELIVERING) → follow gate → guide.

Meta rules respected: one private reply per comment, only within 7 days of the comment; every later message answers a
message the person sent us. Nothing here sends unsolicited DMs.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from store import get_setting, log_event, one, query, ts, update, utc_now

PRIVATE_REPLY_WINDOW = timedelta(days=7)
MAX_SEND_ATTEMPTS = 3
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613}         # transient / rate limits
WAITING = ("AWAITING_TAP", "AWAITING_FOLLOW", "AWAITING_REPLY")
SERVED = WAITING + ("RESOURCE_SENT", "NOT_FOLLOWING", "SENDING", "DELIVERING", "UNCERTAIN")  # we already messaged this person


class RetryLater(Exception):
    """A transient failure: the queue retries the event (bounded), the claim makes the retry safe."""


# ---------------------------------------------------------------- matching
def keywords_of(c: Dict[str, Any]) -> List[str]:
    words = [c.get("keyword") or ""] + re.split(r"[,\n]+", c.get("keywords") or "")
    out = []
    for w in words:
        w = w.strip()
        if w and w.lower() not in (x.lower() for x in out):
            out.append(w)
    return out


def keyword_hit(c: Dict[str, Any], text: str) -> Optional[str]:
    """Whole-word, case-insensitive: 'agent' and 'AGENT!' match AGENT, 'agents' / 'reagent' don't."""
    for k in keywords_of(c):
        if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", text or "", re.I):
            return k
    return None


def render(template: str, **vals: str) -> str:
    out = template or ""
    for k, v in vals.items():
        out = out.replace("{" + k + "}", v or "")
    return out


def classify(meta_err: Dict[str, Any]) -> str:
    """uncertain: Meta may have sent it (never auto-retry) · retryable: transient · final: don't retry (permissions, window, user)."""
    if not meta_err:
        return "final"
    if meta_err.get("uncertain"):
        return "uncertain"
    if meta_err.get("code") in RETRYABLE_CODES or (meta_err.get("http_status") or 0) >= 500:
        return "retryable"
    return "final"


def _log(delivery_id: Optional[int], campaign_id: int, step: str, ok: bool, detail: str = ""):
    update("INSERT INTO dm_delivery_log (delivery_id, campaign_id, at, step, ok, detail) VALUES (?,?,?,?,?,?)",
           (delivery_id, campaign_id, utc_now(), step, 1 if ok else 0, (detail or "")[:1000]))


def _fmt(meta_err: Dict[str, Any], fallback: str) -> str:
    if not meta_err:
        return fallback
    ids = " · ".join(x for x in [f"code {meta_err['code']}" if meta_err.get("code") is not None else "",
                                  f"subcode {meta_err['subcode']}" if meta_err.get("subcode") else "",
                                  f"fbtrace {meta_err['fbtrace_id']}" if meta_err.get("fbtrace_id") else ""] if x)
    return f"{meta_err.get('message') or fallback}{f' [{ids}]' if ids else ''}"


def _responder(r=None):
    if r is not None:
        return r
    from automation.comment_responder import CommentResponder
    return CommentResponder()


# ---------------------------------------------------------------- comment → private reply
def _record_skip(campaign: Dict[str, Any], comment: Dict[str, Any], status: str, why: str, event_id: Optional[int]) -> Dict[str, Any]:
    frm = comment.get("from") or {}
    if update("""INSERT OR IGNORE INTO dm_deliveries (campaign_id, comment_id, username, igsid, comment_text, status, error, event_id,
                 created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
              (campaign["id"], comment["id"], frm.get("username", ""), frm.get("id", ""), comment.get("text", ""), status, why, event_id, ts(), ts())):
        d = one("SELECT id FROM dm_deliveries WHERE comment_id=?", (comment["id"],))
        _log(d["id"], campaign["id"], status.lower(), True, why)
    return {"status": status, "error": why}


def deliver_for_comment(campaign: Dict[str, Any], comment: Dict[str, Any], event_id: Optional[int] = None, responder=None) -> Dict[str, Any]:
    """comment = {"id", "text", "timestamp"?, "from": {"id", "username"}} as returned by the Graph API."""
    frm = comment.get("from") or {}
    username, igsid, cid = frm.get("username") or comment.get("username", ""), frm.get("id", ""), comment["id"]
    me = (get_setting("connected_handle", "") or "").lstrip("@").lower()
    if me and username.lower() == me:
        return _record_skip(campaign, comment, "SKIPPED_SELF", "Your own comment: Instagram can't DM the account itself. Test from another account.", event_id)
    stamp = comment.get("timestamp") or ""
    try:
        when = datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if stamp else None
    except ValueError:
        when = None
    if when and datetime.now(timezone.utc) - when > PRIVATE_REPLY_WINDOW:
        return _record_skip(campaign, comment, "SKIPPED_EXPIRED", "Comment is older than 7 days: Meta no longer allows a private reply.", event_id)
    if igsid and one(f"SELECT id FROM dm_deliveries WHERE campaign_id=? AND igsid=? AND comment_id!=? AND status IN ({','.join('?' * len(SERVED))})",
                     (campaign["id"], igsid, cid, *SERVED)):
        return _record_skip(campaign, comment, "SKIPPED_DUPLICATE_USER", "This person already received this campaign's reply.", event_id)

    # ---- claim: exactly one worker gets to message this comment
    claimed = update("""INSERT OR IGNORE INTO dm_deliveries (campaign_id, comment_id, username, igsid, comment_text, status, error, event_id,
                        attempts, user_msgs, created_at, updated_at) VALUES (?,?,?,?,?,'SENDING','',?,1,0,?,?)""",
                     (campaign["id"], cid, username, igsid, comment.get("text", ""), event_id, ts(), ts()))
    row = one("SELECT * FROM dm_deliveries WHERE comment_id=?", (cid,))
    if not claimed:
        retry = (row["status"] == "FAILED" and row.get("retryable") and (row["attempts"] or 0) < MAX_SEND_ATTEMPTS and
                 update("UPDATE dm_deliveries SET status='SENDING', attempts=attempts+1, updated_at=? WHERE id=? AND status='FAILED' AND retryable=1 AND attempts < ?",
                        (ts(), row["id"], MAX_SEND_ATTEMPTS)))
        if not retry:
            return {"status": row["status"], "duplicate": True, "delivery_id": row["id"]}
        row = one("SELECT * FROM dm_deliveries WHERE id=?", (row["id"],))
    did = row["id"]
    _log(did, campaign["id"], "claimed", True, f"attempt {row['attempts']}" + (f", event #{event_id}" if event_id else ""))

    r = _responder(responder)
    opener = render(campaign.get("private_reply") or get_setting("dm_opener", "Thanks for commenting! Tap below and I'll send it."),
                    username=username, keyword=keyword_hit(campaign, comment.get("text", "")) or campaign.get("keyword", ""),
                    guide_url=campaign.get("guide_url", ""))
    sent, err = r.send_private_reply(cid, opener)
    meta_err = dict(getattr(r, "last_error", None) or {})
    if sent:
        update("UPDATE dm_deliveries SET status='AWAITING_TAP', error='', retryable=0, last_error_json='', sent_at=?, updated_at=? WHERE id=?",
               (utc_now(), ts(), did))
        _log(did, campaign["id"], "private_reply", True, "sent; waiting for their tap")
        if campaign.get("public_reply_enabled") and campaign.get("public_reply_text"):
            ok, e = r.reply_publicly(cid, render(campaign["public_reply_text"], username=username))
            _log(did, campaign["id"], "public_reply", ok, e)
        return {"status": "AWAITING_TAP", "delivery_id": did}

    kind = classify(meta_err)
    text = _fmt(meta_err, err or "Private reply failed")
    if kind == "uncertain":
        status, retryable, text = "UNCERTAIN", 0, f"Meta didn't answer, so the reply may or may not have been sent. Not retried automatically to avoid a double message. ({text})"
    else:
        status, retryable = "FAILED", 1 if kind == "retryable" and row["attempts"] < MAX_SEND_ATTEMPTS else 0
    update("UPDATE dm_deliveries SET status=?, error=?, retryable=?, last_error_json=?, updated_at=? WHERE id=?",
           (status, text[:1000], retryable, json.dumps(meta_err)[:2000], ts(), did))
    _log(did, campaign["id"], "private_reply", False, text)
    return {"status": status, "error": text, "retryable": bool(retryable), "delivery_id": did}


def handle_comment_event(ev: Dict[str, Any], responder=None) -> Dict[str, Any]:
    camps = query("SELECT * FROM campaigns WHERE active=1 AND media_id=? ORDER BY id", (ev["media_id"],)) if ev.get("media_id") else []
    if not camps:
        return {"status": "IGNORED", "reason": "no active campaign for this post"}
    r = _responder(responder)
    ok, comment, meta_err = r.get_comment(ev["comment_id"])
    if not ok:
        if classify(meta_err) == "final":
            return {"status": "IGNORED", "reason": f"comment can't be read from Instagram (deleted or no access): {_fmt(meta_err, 'unknown error')}"}
        raise RetryLater(f"couldn't verify the comment yet: {_fmt(meta_err, 'unknown error')}")
    media = str((comment.get("media") or {}).get("id", ev["media_id"]))
    if media != ev["media_id"]:
        camps = query("SELECT * FROM campaigns WHERE active=1 AND media_id=? ORDER BY id", (media,))
    camp = next((c for c in camps if keyword_hit(c, comment.get("text", ""))), None)
    if not camp:
        return {"status": "IGNORED", "reason": "no campaign keyword in the comment"}
    res = deliver_for_comment(camp, comment, event_id=ev.get("id"), responder=r)  # one private reply per comment: first matching campaign wins
    if res.get("retryable"):
        raise RetryLater(res["error"])
    return {"status": "PROCESSED", "campaign_id": camp["id"], "delivery": res}


# ---------------------------------------------------------------- their DM → follow gate / guide
def handle_message_event(ev: Dict[str, Any], responder=None) -> Dict[str, Any]:
    rows = query(f"SELECT * FROM dm_deliveries WHERE igsid=? AND status IN ({','.join('?' * len(WAITING))}) ORDER BY id DESC",
                 (ev["sender_id"], *WAITING)) if ev.get("sender_id") else []
    if not rows:
        return {"status": "IGNORED", "reason": "no delivery is waiting for this person"}
    r, done = _responder(responder), []
    for d in rows:
        if not update(f"UPDATE dm_deliveries SET status='DELIVERING', updated_at=? WHERE id=? AND status IN ({','.join('?' * len(WAITING))})",
                      (ts(), d["id"], *WAITING)):
            continue  # another worker already took this tap
        camp = one("SELECT * FROM campaigns WHERE id=?", (d["campaign_id"],))
        if not camp or not camp.get("active"):
            update("UPDATE dm_deliveries SET status=?, updated_at=? WHERE id=?", (d["status"], ts(), d["id"]))
            continue
        r.last_error = {}
        status, fstat, err, attempts = r._advance(camp, d)
        kind = classify(dict(getattr(r, "last_error", None) or {}))
        if status == "FAILED" and kind == "retryable" and not (err or "").startswith("Text sent"):
            update("UPDATE dm_deliveries SET status=?, error=?, updated_at=? WHERE id=?", (d["status"], err[:1000], ts(), d["id"]))
            _log(d["id"], camp["id"], "deliver", False, f"transient, will retry: {err}")
            raise RetryLater(err)
        n, _ = r.user_message_count(d["igsid"]) if hasattr(r, "user_message_count") else (None, "")
        update("UPDATE dm_deliveries SET status=?, follower_status=?, error=?, attempts=?, user_msgs=COALESCE(?, user_msgs), sent_at=?, updated_at=? WHERE id=?",
               (status, fstat, err[:1000], attempts, n, utc_now() if status == "RESOURCE_SENT" else d.get("sent_at") or "", ts(), d["id"]))
        _log(d["id"], camp["id"], "deliver" if status in ("RESOURCE_SENT", "FAILED") else "follow_gate", status != "FAILED", f"{status} {err}".strip())
        if status == "RESOURCE_SENT":
            log_event("dm", f"Guide sent to @{d['username'] or d['igsid']} for “{camp['keyword']}”", camp["id"])
        done.append({"delivery_id": d["id"], "status": status, "error": err})
    return {"status": "PROCESSED" if done else "IGNORED", "deliveries": done}


def handle_event(ev: Dict[str, Any], responder=None) -> Dict[str, Any]:
    return handle_comment_event(ev, responder) if ev["kind"] == "comment" else handle_message_event(ev, responder)


def retry_delivery(delivery_id: int, force_uncertain: bool = False) -> Dict[str, Any]:
    """Dashboard retry. FAILED (not final) → resend the private reply. UNCERTAIN only with explicit confirmation (it may double-message)."""
    d = one("SELECT * FROM dm_deliveries WHERE id=?", (delivery_id,))
    if not d:
        return {"ok": False, "error": "Delivery not found"}
    allowed = ("FAILED", "UNCERTAIN") if force_uncertain else ("FAILED",)
    if d["status"] not in allowed:
        return {"ok": False, "error": f"Only failed deliveries can be retried (this one is {d['status']})"
                                      + ("; UNCERTAIN needs explicit confirmation" if d["status"] == "UNCERTAIN" else "")}
    camp = one("SELECT * FROM campaigns WHERE id=?", (d["campaign_id"],))
    if not camp or not camp.get("active"):
        return {"ok": False, "error": "Campaign is paused or deleted"}
    if not update("UPDATE dm_deliveries SET status='FAILED', retryable=1, attempts=0 WHERE id=? AND status=?", (delivery_id, d["status"])):
        return {"ok": False, "error": "Delivery changed meanwhile; reload"}
    r = _responder()
    ok, comment, meta_err = r.get_comment(d["comment_id"])
    if not ok:
        update("UPDATE dm_deliveries SET retryable=0, error=? WHERE id=?", (f"Retry: comment can't be read: {_fmt(meta_err, 'error')}"[:1000], delivery_id))
        return {"ok": False, "error": _fmt(meta_err, "comment can't be read")}
    res = deliver_for_comment(camp, comment, event_id=d.get("event_id"), responder=r)
    return {"ok": res["status"] == "AWAITING_TAP", **res}
