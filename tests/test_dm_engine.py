"""Phase 4: comment-to-DM engine. The Graph API is faked at CommentResponder._call, so the real responder + engine logic runs.
No real network (conftest blocks it). Run:  python -m pytest tests -q
"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import test_app as base
from test_webhooks import post_webhook, comment_payload, SECRET
from automation import dm_engine, webhook_inbox
from automation.comment_responder import CommentResponder
from meta_graph_client import _error
from store import execute, one, query, set_setting, update

client = base.client
MEDIA = "1791001"


def now_iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")


class FakeIG(CommentResponder):
    """Stateful Instagram: comments, private replies, DMs, follower lookups, conversations."""

    def __init__(self):
        self.access_token, self.ig_user_id = "test-token", "IG"
        self.comments, self.sent, self.lock = {}, [], threading.RLock()
        self.reply_outcomes = []      # queue of None (ok) or error dicts for private replies
        self.following, self.msgs, self.delay = True, 1, 0.0

    def add_comment(self, cid, text, user="fan", uid=None, media=MEDIA, days_ago=0):
        self.comments[cid] = {"id": cid, "text": text, "timestamp": now_iso(days_ago), "from": {"id": uid or f"u-{user}", "username": user},
                              "media": {"id": media}}

    def _fail(self, err):
        self.last_error = err
        return False, {"error": err["message"], "meta": err}

    def _call(self, method, path, **kw):
        params, body = kw.get("params", {}), kw.get("json") or {}
        if method == "GET" and path in self.comments:
            return True, self.comments[path]
        if method == "GET" and "fields" in params and params["fields"].startswith("id,text"):
            return self._fail(_error(400, {"error": {"code": 100, "message": "Unsupported get request. Object does not exist"}}, "", "meta"))
        if method == "POST" and path.endswith("/messages"):
            rec = body["recipient"]
            time.sleep(self.delay)
            with self.lock:
                if "comment_id" in rec and self.reply_outcomes:
                    out = self.reply_outcomes.pop(0)
                    if out:
                        return self._fail(out)
                self.sent.append(("private" if "comment_id" in rec else "dm", rec.get("comment_id") or rec.get("id"), body["message"]))
            return True, {"message_id": f"m{len(self.sent)}"}
        if method == "POST" and path.endswith("/replies"):
            self.sent.append(("public", path.split("/")[0], params.get("message")))
            return True, {"id": "r1"}
        if method == "GET" and params.get("fields") == "username,is_user_follow_business":
            return True, {"username": "x", "is_user_follow_business": self.following}
        if method == "GET" and path == "me/conversations":
            return True, {"data": [{"messages": {"data": [{"from": {"id": params["user_id"]}}] * self.msgs}}]}
        raise AssertionError(f"FakeIG has no route for {method} {path}")

    def private_replies(self, cid=None):
        return [s for s in self.sent if s[0] == "private" and (cid is None or s[1] == cid)]


@pytest.fixture
def ig(monkeypatch):
    fake = FakeIG()
    monkeypatch.setattr(dm_engine, "_responder", lambda r=None: r or fake)
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    monkeypatch.delenv("QSTASH_TOKEN", raising=False)
    monkeypatch.setattr(webhook_inbox, "_background", lambda fn, *a: fn(*a))  # local worker inline
    monkeypatch.setattr(webhook_inbox, "HANDLER", webhook_inbox._default_handler)
    set_setting("connected_handle", "@sonu.ai.lab")
    return fake


_n = [0]


def campaign(keyword="AGENT", keywords="", media=MEDIA, **kw):
    _n[0] += 1
    media = media if media != MEDIA else f"17910{_n[0]:05d}"
    body = {"name": f"C{_n[0]}", "keyword": keyword, "keywords": keywords, "media_id": media, "resource_pack": "Guide text",
            "private_reply": "Hi {username}! Tap below for the {keyword} guide", "follow_gate": kw.pop("follow_gate", False), "active": True, **kw}
    r = client.post("/api/campaigns", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def comment_event(ig, camp, cid, text, **kw):
    ig.add_comment(cid, text, media=camp["media_id"], **kw)
    return post_webhook(comment_payload((cid, text), media=camp["media_id"]))


def delivery(cid):
    return one("SELECT * FROM dm_deliveries WHERE comment_id=?", (cid,))


# ---------------------------------------------------------------- matching
def test_agent_uppercase_triggers_one_private_reply(ig):
    c = campaign()
    comment_event(ig, c, "k1", "AGENT please", user="ana")
    d = delivery("k1")
    assert d["status"] == "AWAITING_TAP" and d["sent_at"].endswith("Z") and d["igsid"] == "u-ana"
    (kind, target, msg), = ig.private_replies("k1")
    assert msg["text"] == "Hi ana! Tap below for the AGENT guide" and msg["quick_replies"][0]["title"] == "Send me the access"


def test_lowercase_agent_matches(ig):
    c = campaign()
    comment_event(ig, c, "k2", "agent", user="bo")
    assert delivery("k2")["status"] == "AWAITING_TAP"


@pytest.mark.parametrize("text", ["agents", "reagent", "AGENTIC stuff", "no keyword here"])
def test_partial_words_do_not_match(ig, text):
    c = campaign()
    comment_event(ig, c, f"pw-{text}", text)
    assert delivery(f"pw-{text}") is None and ig.private_replies() == []


def test_multiple_keywords_per_campaign(ig):
    c = campaign(keywords="guide, link")
    assert one("SELECT keywords FROM campaigns WHERE id=?", (c["id"],))["keywords"] == "GUIDE,LINK"
    comment_event(ig, c, "mk1", "Can I get the Guide?", user="u1")
    comment_event(ig, c, "mk2", "link!!", user="u2")
    assert delivery("mk1")["status"] == delivery("mk2")["status"] == "AWAITING_TAP"


def test_multiple_campaigns_on_one_post_send_only_one_reply(ig):
    a = campaign(keyword="AGENT")
    b = campaign(keyword="PROMPT", media=a["media_id"])
    comment_event(ig, a, "mc1", "AGENT and PROMPT", user="both")
    assert len(ig.private_replies("mc1")) == 1 and delivery("mc1")["campaign_id"] == a["id"]  # Meta: one private reply per comment
    comment_event(ig, b, "mc2", "prompt", user="p1")
    assert delivery("mc2")["campaign_id"] == b["id"]


def test_existing_campaign_and_keyword_preserved(ig):
    c = campaign(keyword="AGENT")
    client.put(f"/api/campaigns/{c['id']}", json={"guide_url": "https://example.com/guide"})
    row = one("SELECT keyword, keywords, guide_url FROM campaigns WHERE id=?", (c["id"],))
    assert row["keyword"] == "AGENT" and row["keywords"] == "" and row["guide_url"] == "https://example.com/guide"


def test_campaign_validation(ig):
    assert client.post("/api/campaigns", json={"name": "x", "keyword": "AGENT", "keywords": "A", "media_id": "1791999"}).status_code == 400
    assert client.post("/api/campaigns", json={"name": "x", "keyword": "AGENT", "guide_url": "http://insecure", "media_id": "1791999"}).status_code == 400


# ---------------------------------------------------------------- duplicates and eligibility
def test_duplicate_comment_event_sends_once(ig):
    c = campaign()
    comment_event(ig, c, "dc1", "AGENT")
    post_webhook(comment_payload(("dc1", "AGENT"), media=c["media_id"]))      # Meta redelivery
    dm_engine.handle_comment_event({"id": None, "comment_id": "dc1", "media_id": c["media_id"]})  # stray reprocessing
    assert len(ig.private_replies("dc1")) == 1


def test_concurrent_workers_same_comment_send_once(ig):
    c = campaign()
    ig.add_comment("cw1", "AGENT", media=c["media_id"])
    ig.delay = 0.1
    camp = one("SELECT * FROM campaigns WHERE id=?", (c["id"],))
    threads = [threading.Thread(target=dm_engine.deliver_for_comment, args=(camp, ig.comments["cw1"])) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ig.private_replies("cw1")) == 1 and delivery("cw1")["status"] == "AWAITING_TAP"


def test_same_person_second_comment_is_not_messaged_again(ig):
    c = campaign()
    comment_event(ig, c, "sp1", "AGENT", user="rep", uid="u-rep")
    comment_event(ig, c, "sp2", "agent again", user="rep", uid="u-rep")
    assert delivery("sp2")["status"] == "SKIPPED_DUPLICATE_USER" and len(ig.private_replies()) == 1


def test_own_account_comment_skipped(ig):
    c = campaign()
    comment_event(ig, c, "own1", "AGENT", user="sonu.ai.lab")
    assert delivery("own1")["status"] == "SKIPPED_SELF" and ig.private_replies() == []


def test_comment_older_than_7_days_skipped(ig):
    c = campaign()
    comment_event(ig, c, "old1", "AGENT", days_ago=8)
    assert delivery("old1")["status"] == "SKIPPED_EXPIRED" and ig.private_replies() == []


def test_forged_or_deleted_comment_is_never_messaged(ig):
    c = campaign()
    post_webhook(comment_payload(("ghost1", "AGENT"), media=c["media_id"]))  # not on Instagram
    e = one("SELECT status, result_json FROM webhook_events WHERE comment_id='ghost1'")
    assert e["status"] == "IGNORED" and "can't be read" in e["result_json"] and delivery("ghost1") is None


# ---------------------------------------------------------------- failures, retries
def test_invalid_recipient_is_final_failure_with_details(ig):
    c = campaign()
    ig.reply_outcomes = [_error(400, {"error": {"code": 10, "error_subcode": 2534022, "message": "This message is sent outside of allowed window.", "fbtrace_id": "TR9"}}, "", "meta")]
    comment_event(ig, c, "ir1", "AGENT")
    d = delivery("ir1")
    assert d["status"] == "FAILED" and d["retryable"] == 0 and "outside of allowed window" in d["error"] and "fbtrace TR9" in d["error"]
    assert json.loads(d["last_error_json"])["subcode"] == 2534022
    assert one("SELECT status FROM webhook_events WHERE comment_id='ir1'")["status"] == "PROCESSED"  # final: no queue retries
    log = client.get(f"/api/deliveries/{d['id']}/log").json()
    assert [x["step"] for x in log] == ["claimed", "private_reply"] and log[1]["ok"] == 0


def test_transient_failure_retried_by_queue_then_succeeds(ig):
    c = campaign()
    ig.reply_outcomes = [_error(400, {"error": {"code": 4, "message": "Application request limit reached"}}, "", "meta")]
    comment_event(ig, c, "tr1", "AGENT")
    assert delivery("tr1")["status"] == "FAILED" and delivery("tr1")["retryable"] == 1
    ev = one("SELECT id, status FROM webhook_events WHERE comment_id='tr1'")
    assert ev["status"] == "FAILED"                          # handed back to the queue
    code, _ = webhook_inbox.process_event(ev["id"])          # QStash retry
    assert code == 200 and delivery("tr1")["status"] == "AWAITING_TAP" and len(ig.private_replies("tr1")) == 1


def test_retry_attempts_are_bounded(ig):
    c = campaign()
    lim = _error(400, {"error": {"code": 4, "message": "limit"}}, "", "meta")
    ig.reply_outcomes = [lim] * 10
    comment_event(ig, c, "rb1", "AGENT")
    eid = one("SELECT id FROM webhook_events WHERE comment_id='rb1'")["id"]
    for _ in range(6):
        webhook_inbox.process_event(eid)
    d = delivery("rb1")
    assert d["attempts"] == dm_engine.MAX_SEND_ATTEMPTS and d["retryable"] == 0 and d["status"] == "FAILED"


def test_uncertain_reply_is_not_auto_retried(ig):
    c = campaign()
    ig.reply_outcomes = [_error(0, {}, "No answer from Meta within 20s", "timeout", uncertain=True)]
    comment_event(ig, c, "un1", "AGENT")
    d = delivery("un1")
    assert d["status"] == "UNCERTAIN" and d["retryable"] == 0
    assert not client.post(f"/api/deliveries/{d['id']}/retry", json={}).json()["ok"]          # needs explicit confirmation
    r = client.post(f"/api/deliveries/{d['id']}/retry", json={"confirm_uncertain": True}).json()
    assert r["ok"] and delivery("un1")["status"] == "AWAITING_TAP"


def test_manual_retry_of_failed_delivery(ig):
    c = campaign()
    ig.reply_outcomes = [_error(400, {"error": {"code": 10, "message": "Permission error"}}, "", "meta")]
    comment_event(ig, c, "mr1", "AGENT")
    r = client.post(f"/api/deliveries/{delivery('mr1')['id']}/retry", json={}).json()
    assert r["ok"] and len(ig.private_replies("mr1")) == 1


# ---------------------------------------------------------------- their DM → guide
def tap(ig, uid, mid):
    return post_webhook({"object": "instagram", "entry": [{"id": "IG", "messaging": [
        {"sender": {"id": uid}, "message": {"mid": mid, "text": "Send me the access", "quick_reply": {"payload": "SEND_ME_THE_ACCESS"}}, "timestamp": 5}]}]})


def test_tap_delivers_guide_with_link(ig):
    c = campaign(guide_url="https://example.com/g")
    execute("UPDATE campaigns SET guide_images=? WHERE id=?", (json.dumps(["https://img.example/1.jpg"]), c["id"]))
    comment_event(ig, c, "tp1", "AGENT", user="tapper", uid="u-tapper")
    tap(ig, "u-tapper", "mid-tp1")
    d = delivery("tp1")
    assert d["status"] == "RESOURCE_SENT" and d["sent_at"]
    dms = [s for s in ig.sent if s[0] == "dm"]
    assert "Full guide: https://example.com/g" in dms[0][2]["text"] and dms[1][2]["attachment"]["payload"]["url"] == "https://img.example/1.jpg"


def test_follow_gate_then_delivery(ig):
    c = campaign(follow_gate=True)
    comment_event(ig, c, "fg1", "AGENT", user="nofollow", uid="u-nf")
    ig.following = False
    tap(ig, "u-nf", "mid-fg1")
    assert delivery("fg1")["status"] == "AWAITING_FOLLOW"
    ig.following, ig.msgs = True, 2
    tap(ig, "u-nf", "mid-fg2")
    assert delivery("fg1")["status"] == "RESOURCE_SENT"


def test_concurrent_taps_deliver_once(ig):
    c = campaign()
    comment_event(ig, c, "ct1", "AGENT", user="dbl", uid="u-dbl")
    ig.delay = 0.1
    evs = [{"kind": "message", "sender_id": "u-dbl", "id": None}] * 4
    threads = [threading.Thread(target=dm_engine.handle_message_event, args=(e,)) for e in evs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([s for s in ig.sent if s[0] == "dm" and s[1] == "u-dbl"]) == 1 and delivery("ct1")["status"] == "RESOURCE_SENT"


def test_message_from_stranger_is_ignored(ig):
    tap(ig, "u-stranger", "mid-x")
    assert one("SELECT status FROM webhook_events WHERE event_key='message:mid-x'")["status"] == "IGNORED"
    assert [s for s in ig.sent if s[1] == "u-stranger"] == []


def test_live_scan_uses_the_same_claim(ig):
    c = campaign()
    ig.add_comment("ls1", "AGENT", media=c["media_id"], user="scan")
    comment_event(ig, c, "ls1", "AGENT", user="scan")              # webhook handled it first
    camp = one("SELECT * FROM campaigns WHERE id=?", (c["id"],))
    ig.get_post_comments = lambda media_id: (True, [ig.comments["ls1"]], "")
    ig.scan_campaign(camp, dry_run=False)                          # manual live scan afterwards
    assert len(ig.private_replies("ls1")) == 1
