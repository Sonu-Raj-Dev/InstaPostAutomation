"""Comment-to-DM (v4): the button flow creators use, inside Meta's rules.

  1. Comment contains the keyword → ONE private reply: opener text + quick-reply button "Send me the access".
  2. Person taps the button (that's a DM from them, which opens the 24h window and allows a profile lookup).
  3. Follow gate on:  following → deliver; not following → "Oops, follow first" + button "I'm following ✅"
     (re-checked on every tap, max 3 nudges, then NOT_FOLLOWING — no spam).
  4. Deliver = the guide: copyable text (commands + links) followed by the rendered guide pages as images.
Public comment replies are only sent when a campaign explicitly enables them.
Without a webhook (local app) taps are picked up by polling the conversation every few minutes.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

sys.path.append(str(Path(__file__).resolve().parent.parent))
from store import execute, get_setting, query, ts  # noqa: E402

load_dotenv()
logger = logging.getLogger("CommentResponder")
BASE = "https://graph.facebook.com/v22.0"
TAP_ACCESS, TAP_FOLLOWING = "Send me the access", "I'm following ✅"
MAX_NUDGES = 3


class CommentResponder:
    def __init__(self):
        self.reload()

    def reload(self):
        load_dotenv(override=True)
        from meta_graph_client import _saved_token
        self.access_token = _saved_token() or os.getenv("META_ACCESS_TOKEN", "")
        self.ig_user_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "")

    # ---------------------------------------------------------- Graph calls (overridden in tests)
    def _call(self, method: str, path: str, **kw) -> Tuple[bool, Dict[str, Any]]:
        try:
            r = requests.request(method, f"{BASE}/{path}", timeout=20,
                                 params={**kw.pop("params", {}), "access_token": self.access_token}, **kw)
            data = r.json()
        except Exception as e:
            return False, {"error": str(e)}
        if r.status_code == 200 and "error" not in data:
            return True, data
        return False, {"error": (data.get("error") or {}).get("message", str(data)[:300])}

    def _send(self, recipient: Dict[str, str], message: Dict[str, Any]) -> Tuple[bool, str]:
        ok, d = self._call("POST", "me/messages", json={"recipient": recipient, "message": message})
        return ok, "" if ok else d["error"]

    @staticmethod
    def _buttons(text: str, *titles: str) -> Dict[str, Any]:
        return {"text": text, "quick_replies": [{"content_type": "text", "title": t[:20], "payload": t.upper().replace(" ", "_")[:40]} for t in titles]}

    def get_post_comments(self, media_id: str) -> Tuple[bool, List[Dict[str, Any]], str]:
        ok, d = self._call("GET", f"{media_id}/comments", params={"fields": "id,text,username,from{id,username},timestamp", "limit": 50})
        return ok, d.get("data", []) if ok else [], "" if ok else d["error"]

    def send_private_reply(self, comment_id: str, text: str) -> Tuple[bool, str]:
        ok, err = self._send({"comment_id": comment_id}, self._buttons(text, TAP_ACCESS))
        if not ok and "quick" in err.lower():  # some accounts reject buttons on private replies → plain text
            ok, err = self._send({"comment_id": comment_id}, {"text": f"{text}\n\nReply \"send\" to get it."})
        return ok, err

    def send_dm(self, igsid: str, text: str, button: Optional[str] = None) -> Tuple[bool, str]:
        return self._send({"id": igsid}, self._buttons(text, button) if button else {"text": text})

    def send_image(self, igsid: str, url: str) -> Tuple[bool, str]:
        return self._send({"id": igsid}, {"attachment": {"type": "image", "payload": {"url": url}}})

    def reply_publicly(self, comment_id: str, text: str) -> Tuple[bool, str]:
        ok, d = self._call("POST", f"{comment_id}/replies", params={"message": text})
        return ok, "" if ok else d["error"]

    def user_message_count(self, igsid: str) -> Tuple[Optional[int], str]:
        """Messages the person has sent us (a quick-reply tap arrives as a message)."""
        ok, d = self._call("GET", "me/conversations", params={"platform": "instagram", "user_id": igsid,
                                                              "fields": "messages.limit(25){from}"})
        if not ok:
            return None, d["error"]
        return sum(1 for conv in d.get("data", []) for m in (conv.get("messages") or {}).get("data", [])
                   if (m.get("from") or {}).get("id") == igsid), ""

    def follower_status(self, igsid: str) -> Tuple[Optional[bool], str]:
        ok, d = self._call("GET", igsid, params={"fields": "username,is_user_follow_business"})
        return (bool(d.get("is_user_follow_business")), "") if ok else (None, d["error"])

    # ---------------------------------------------------------- delivery
    def deliver(self, campaign: Dict[str, Any], igsid: str) -> Tuple[bool, str]:
        ok, err = self.send_dm(igsid, campaign.get("resource_pack") or "Here's your guide 👇")
        if not ok:
            return False, err
        for url in json.loads(campaign.get("guide_images") or "[]")[:6]:
            ok, err = self.send_image(igsid, url)
            if not ok:
                return False, f"Text sent, image failed: {err}"
        return True, ""

    # ---------------------------------------------------------- scan
    def scan_campaign(self, campaign: Dict[str, Any], dry_run: bool = True, log=logger.info) -> Dict[str, Any]:
        if not campaign.get("media_id"):
            return {"success": False, "error": "Campaign has no associated post (media id)."}
        ok, comments, err = self.get_post_comments(campaign["media_id"])
        if not ok:
            return {"success": False, "error": f"Could not read comments: {err}"}
        kw = re.compile(rf"\b{re.escape(campaign['keyword'].strip())}\b", re.I)
        handled = {r["comment_id"] for r in query("SELECT comment_id FROM dm_deliveries")}
        me = get_setting("connected_handle", "").lstrip("@").lower()
        who = lambda c: ((c.get("from") or {}).get("username") or c.get("username", "")).lower()  # noqa: E731
        new = [c for c in comments if kw.search(c.get("text", "")) and c["id"] not in handled]
        own = [c for c in new if me and who(c) == me]  # Instagram can't DM the account itself
        matches = [c for c in new if c not in own]
        log(f"{len(comments)} comments read, {len(matches)} new keyword matches, {len(own)} of your own skipped")
        report_own = [{"comment_id": c["id"], "username": who(c), "text": c.get("text", ""), "status": "SKIPPED_SELF"} for c in own]
        if not dry_run:
            for c in own:  # recorded once so it shows in the UI and isn't re-checked
                execute("""INSERT OR IGNORE INTO dm_deliveries (campaign_id, comment_id, username, comment_text, status, error, created_at, updated_at)
                           VALUES (?,?,?,?,'SKIPPED_SELF',?,?,?)""",
                        (campaign["id"], c["id"], who(c), c.get("text", ""),
                         "Your own comment: Instagram can't DM the account itself. Test from another account.", ts(), ts()))
        opener = campaign.get("private_reply") or get_setting("dm_opener", "Thanks for commenting! Tap below and I'll send it.")
        report = {"success": True, "dry_run": dry_run, "comments_read": len(comments), "matches": [], "followups": [], "skipped_own": report_own}

        for c in matches:
            frm = c.get("from") or {}
            username, igsid = frm.get("username") or c.get("username", ""), frm.get("id", "")
            entry = {"comment_id": c["id"], "username": username, "text": c.get("text", ""), "action": f"private reply + button “{TAP_ACCESS}”"}
            if not dry_run:
                sent, e = self.send_private_reply(c["id"], opener)
                status = "AWAITING_TAP" if sent else "FAILED"
                if sent and campaign.get("public_reply_enabled") and campaign.get("public_reply_text"):
                    self.reply_publicly(c["id"], campaign["public_reply_text"])
                execute("""INSERT OR IGNORE INTO dm_deliveries (campaign_id, comment_id, username, igsid, comment_text,
                           status, error, user_msgs, created_at, updated_at) VALUES (?,?,?,?,?,?,?,0,?,?)""",
                        (campaign["id"], c["id"], username, igsid, c.get("text", ""), status, e, ts(), ts()))
                entry.update(status=status, error=e)
                log(f"@{username}: {status} {e}")
            report["matches"].append(entry)

        # taps: anyone who messaged us since our last message moves forward
        for d in query("SELECT * FROM dm_deliveries WHERE campaign_id=? AND status IN ('AWAITING_TAP','AWAITING_FOLLOW','AWAITING_REPLY')", (campaign["id"],)):
            if not d["igsid"]:
                continue
            n, e = self.user_message_count(d["igsid"])
            fu = {"username": d["username"], "tapped": None if n is None else n > (d["user_msgs"] or 0), "error": e}
            if n is not None and n > (d["user_msgs"] or 0) and not dry_run:
                status, fstat, err, attempts = self._advance(campaign, d)
                execute("UPDATE dm_deliveries SET status=?, follower_status=?, error=?, user_msgs=?, attempts=?, updated_at=? WHERE id=?",
                        (status, fstat, err, n, attempts, ts(), d["id"]))
                fu.update(status=status, follower_status=fstat, error=err)
                log(f"@{d['username']}: {status} {err}")
            report["followups"].append(fu)
        return report

    def _advance(self, campaign: Dict[str, Any], d: Dict[str, Any]):
        attempts = (d.get("attempts") or 0)
        if campaign.get("follow_gate"):
            following, e = self.follower_status(d["igsid"])
            if following is None:
                return d["status"], "UNKNOWN", e, attempts
            if not following:
                if attempts >= MAX_NUDGES:
                    return "NOT_FOLLOWING", "NOT_FOLLOWING", "", attempts
                msg = campaign.get("follow_gate_message") or get_setting("dm_not_following", "Follow first, then tap below.")
                ok, e = self.send_dm(d["igsid"], msg, TAP_FOLLOWING)
                return ("AWAITING_FOLLOW" if ok else "FAILED"), "NOT_FOLLOWING", e, attempts + 1
        ok, e = self.deliver(campaign, d["igsid"])
        return ("RESOURCE_SENT" if ok else "FAILED"), ("FOLLOWING" if campaign.get("follow_gate") else "NOT_CHECKED"), e, attempts
