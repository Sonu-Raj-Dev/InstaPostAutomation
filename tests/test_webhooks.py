"""Phase 3: webhook inbox + QStash. No real network (conftest blocks it); QStash and Meta are faked.

Run:  python -m pytest tests -q
"""
import base64
import hashlib
import hmac
import json
import threading
import time

import pytest
import requests

import test_app as base
import qstash_client
from automation import webhook_inbox
from store import execute, one, query, update

client = base.client
SECRET = "test-meta-app-secret"
CUR, NXT = "sig_current_test_key", "sig_next_test_key"


def sign_meta(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def qstash_jwt(body: bytes, url: str, key: str = CUR, exp_in: int = 300, iss: str = "Upstash", pad_body: bool = True) -> str:
    h = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    bh = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode()
    now = int(time.time())
    p = b64u(json.dumps({"iss": iss, "sub": url, "exp": now + exp_in, "nbf": now - 1, "iat": now, "jti": "j1",
                         "body": bh if pad_body else bh.rstrip("=")}).encode())
    return f"{h}.{p}.{b64u(hmac.new(key.encode(), f'{h}.{p}'.encode(), hashlib.sha256).digest())}"


def comment_payload(*comments, media="1790777"):
    return {"object": "instagram", "entry": [{"id": "IG", "time": 1790000000, "changes": [
        {"field": "comments", "value": {"id": cid, "text": text, "from": {"id": f"u-{cid}", "username": f"user{cid}"}, "media": {"id": media}}}
        for cid, text in comments]}]}


def post_webhook(payload, sig=True, secret=SECRET):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if sig:
        headers["x-hub-signature-256"] = sign_meta(body, secret)
    return client.post("/api/webhooks/instagram", content=body, headers=headers)


class FakeQStash:
    def __init__(self):
        self.published, self.down = [], False

    def __call__(self, method, url, data=None, headers=None, timeout=None, **kw):
        assert url.startswith("https://qstash.upstash.io/v2/publish/"), url
        if self.down:
            raise requests.ConnectionError("qstash down")
        self.published.append({"url": url, "body": json.loads(data), "headers": headers})

        class R:
            status_code = 200
            text = ""
            def json(self_inner): return {"messageId": f"msg_{len(self.published)}"}
        return R()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    monkeypatch.setenv("APP_URL", "https://insta-test.example")
    for k in ("QSTASH_TOKEN", "QSTASH_CURRENT_SIGNING_KEY", "QSTASH_NEXT_SIGNING_KEY"):
        monkeypatch.delenv(k, raising=False)
    seen = []
    monkeypatch.setattr(webhook_inbox, "HANDLER", lambda ev: seen.append(ev["id"]) or {"status": "PROCESSED", "handled": ev["event_key"]})

    monkeypatch.setattr(webhook_inbox, "_background", lambda fn, *a: fn(*a))  # run the local worker inline
    return seen


@pytest.fixture
def qstash(env, monkeypatch):
    monkeypatch.setenv("QSTASH_TOKEN", "test-qstash-token")
    monkeypatch.setenv("QSTASH_CURRENT_SIGNING_KEY", CUR)
    monkeypatch.setenv("QSTASH_NEXT_SIGNING_KEY", NXT)
    fake = FakeQStash()
    monkeypatch.setattr(qstash_client.requests, "request", fake)
    return fake


def ev(key):
    return one("SELECT * FROM webhook_events WHERE event_key=?", (key,))


# ---------------------------------------------------------------- Meta webhook endpoint
def test_verification_challenge():
    tok = base.webapp.webhook_token()
    r = client.get("/api/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": tok, "hub.challenge": "9911"})
    assert r.status_code == 200 and r.text == "9911"
    assert client.get("/api/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"}).status_code == 403


def test_missing_app_secret_rejects_and_stores_nothing(env, monkeypatch):
    monkeypatch.delenv("META_APP_SECRET")
    monkeypatch.setattr(base.webapp.meta, "app_secret", "")
    r = post_webhook(comment_payload(("ms1", "AGENT")), secret="anything")
    assert r.status_code == 503 and ev("comment:ms1") is None


def test_unsigned_and_invalid_signatures_rejected(env):
    assert post_webhook(comment_payload(("us1", "AGENT")), sig=False).status_code == 403
    assert post_webhook(comment_payload(("us2", "AGENT")), secret="wrong-secret").status_code == 403
    assert ev("comment:us1") is None and ev("comment:us2") is None


def test_valid_event_is_persisted_with_comment_fields(env):
    r = post_webhook(comment_payload(("vc1", "Send me AGENT pls")))
    assert r.status_code == 200 and r.json()["stored"] == 1
    e = ev("comment:vc1")
    assert e["comment_id"] == "vc1" and e["media_id"] == "1790777" and e["sender_id"] == "u-vc1" and e["sender_username"] == "uservc1"
    assert e["text"] == "Send me AGENT pls" and e["ig_account_id"] == "IG" and e["received_at"].endswith("Z")
    assert e["status"] == "PROCESSED" and env == [e["id"]]  # local mode, no QStash: processed in the background worker


def test_duplicate_delivery_is_stored_and_processed_once(env):
    p = comment_payload(("dup1", "AGENT"))
    assert post_webhook(p).json()["stored"] == 1
    assert post_webhook(p).json()["stored"] == 0
    assert len(query("SELECT id FROM webhook_events WHERE comment_id='dup1'")) == 1 and len(env) == 1


def test_unique_comment_id_constraint_at_db_level(env):
    sql = "INSERT OR IGNORE INTO webhook_events (event_key, comment_id, kind, received_at) VALUES (?,?,?,?)"
    assert update(sql, ("comment:uq1", "uq1", "comment", "x")) == 1
    assert update(sql, ("other-key", "uq1", "comment", "x")) == 0  # same comment id under another key is still refused


def test_concurrent_comments_each_stored_once(env):
    def send(i):
        post_webhook(comment_payload((f"cc{i}", "AGENT"), (f"cc{i}", "AGENT")))  # each payload also repeats its own comment
    threads = [threading.Thread(target=send, args=(i,)) for i in range(8)] + [threading.Thread(target=send, args=(3,))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rows = query("SELECT comment_id FROM webhook_events WHERE comment_id LIKE 'cc%'")
    assert sorted(r["comment_id"] for r in rows) == sorted(f"cc{i}" for i in range(8))


def test_echo_messages_ignored_and_dm_taps_stored(env):
    payload = {"object": "instagram", "entry": [{"id": "IG", "messaging": [
        {"sender": {"id": "IG"}, "message": {"mid": "m-echo", "text": "hi", "is_echo": True}, "timestamp": 1},
        {"sender": {"id": "u7"}, "message": {"mid": "m-tap", "text": "Send me the access", "quick_reply": {"payload": "SEND_ME_THE_ACCESS"}}, "timestamp": 2}]}]}
    assert post_webhook(payload).json()["stored"] == 1
    assert ev("message:m-echo") is None and ev("message:m-tap")["text"] == "SEND_ME_THE_ACCESS"


# ---------------------------------------------------------------- QStash queueing
def test_new_event_is_queued_on_qstash(qstash):
    r = post_webhook(comment_payload(("q1", "AGENT")))
    assert r.json()["queued"] == 1
    e = ev("comment:q1")
    assert e["status"] == "QUEUED" and e["qstash_message_id"] == "msg_1"
    pub = qstash.published[0]
    assert pub["url"].endswith("/v2/publish/https://insta-test.example/api/queue/webhook-event")
    assert pub["body"] == {"event_id": e["id"]} and pub["headers"]["Authorization"] == "Bearer test-qstash-token"
    assert pub["headers"]["Upstash-Retries"] == "3" and pub["headers"]["Upstash-Deduplication-Id"] == f"wh-event-{e['id']}"


def test_qstash_down_keeps_event_pending_then_sweep_recovers(qstash, env):
    qstash.down = True
    assert post_webhook(comment_payload(("qd1", "AGENT"))).status_code == 200  # Meta still gets 200
    e = ev("comment:qd1")
    assert e["status"] == "PENDING" and "QStash unreachable" in e["error"]
    update("UPDATE webhook_events SET received_at='2000-01-01T00:00:00Z' WHERE id=?", (e["id"],))
    qstash.down = False
    out = webhook_inbox.sweep()
    assert out["requeued"] >= 1 and ev("comment:qd1")["status"] == "QUEUED"


def test_sweep_processes_inline_without_qstash(env, monkeypatch):
    monkeypatch.setattr(webhook_inbox, "ON_VERCEL", True)  # Vercel without QStash: stays PENDING for the sweep
    post_webhook(comment_payload(("sw1", "AGENT")))
    e = ev("comment:sw1")
    assert e["status"] == "PENDING" and "not configured" in e["error"]
    update("UPDATE webhook_events SET received_at='2000-01-01T00:00:00Z' WHERE id=?", (e["id"],))
    webhook_inbox.sweep()
    assert ev("comment:sw1")["status"] == "PROCESSED"


# ---------------------------------------------------------------- QStash callback (signed)
def call_queue(event_id, key=CUR, url=None, body=None, **jwt_kw):
    raw = body if body is not None else json.dumps({"event_id": event_id}).encode()
    url = url or qstash_client.destination(webhook_inbox.PROCESS_PATH)
    signed_body = json.dumps({"event_id": event_id}).encode()
    return client.post("/api/queue/webhook-event", content=raw,
                       headers={"upstash-signature": qstash_jwt(signed_body, url, key=key, **jwt_kw), "content-type": "application/json"})


def queued_event(qstash, cid):
    post_webhook(comment_payload((cid, "AGENT")))
    return ev(f"comment:{cid}")["id"]


def test_signed_callback_processes_event_once(qstash, env):
    eid = queued_event(qstash, "cb1")
    r = call_queue(eid)
    assert r.status_code == 200 and r.json()["status"] == "PROCESSED" and ev("comment:cb1")["status"] == "PROCESSED"
    again = call_queue(eid)  # QStash redelivery
    assert again.status_code == 200 and "skipped" in again.json() and env.count(eid) == 1


def test_next_signing_key_and_unpadded_body_hash_accepted(qstash, env):
    eid = queued_event(qstash, "cb2")
    assert call_queue(eid, key=NXT, pad_body=False).status_code == 200


@pytest.mark.parametrize("kw", [dict(key="sig_attacker"), dict(url="https://evil.example/api/queue/webhook-event"),
                                dict(exp_in=-120), dict(iss="NotUpstash"), dict(body=b'{"event_id": 999999}')])
def test_bad_qstash_signatures_rejected(qstash, env, kw):
    eid = queued_event(qstash, f"bad{abs(hash(str(kw))) % 10**6}")
    r = call_queue(eid, **kw)
    assert r.status_code == 401 and ev(one("SELECT event_key FROM webhook_events WHERE id=?", (eid,))["event_key"])["status"] == "QUEUED"


def test_callback_without_keys_configured_rejected(env, monkeypatch):
    r = client.post("/api/queue/webhook-event", content=b'{"event_id":1}', headers={"upstash-signature": "a.b.c"})
    assert r.status_code == 401


# ---------------------------------------------------------------- idempotent processing, retries, recovery
def test_concurrent_processing_runs_handler_once(env, monkeypatch):
    monkeypatch.setattr(webhook_inbox, "ON_VERCEL", True)
    post_webhook(comment_payload(("pc1", "AGENT")))
    eid = ev("comment:pc1")["id"]
    calls = []
    monkeypatch.setattr(webhook_inbox, "HANDLER", lambda e: (calls.append(1), time.sleep(0.2), {"status": "PROCESSED"})[2])
    threads = [threading.Thread(target=webhook_inbox.process_event, args=(eid,)) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and ev("comment:pc1")["status"] == "PROCESSED"


def test_failure_is_retryable_then_final(env, monkeypatch):
    monkeypatch.setattr(webhook_inbox, "ON_VERCEL", True)
    post_webhook(comment_payload(("fl1", "AGENT")))
    eid = ev("comment:fl1")["id"]

    def boom(e):
        raise RuntimeError("Graph API down")
    monkeypatch.setattr(webhook_inbox, "HANDLER", boom)
    codes = [webhook_inbox.process_event(eid)[0] for _ in range(webhook_inbox.MAX_ATTEMPTS)]
    assert codes[:-1] == [500] * (webhook_inbox.MAX_ATTEMPTS - 1) and codes[-1] == 200  # last attempt: stop QStash retrying
    e = ev("comment:fl1")
    assert e["status"] == "FAILED" and "Graph API down" in e["error"] and e["attempts"] == webhook_inbox.MAX_ATTEMPTS
    assert webhook_inbox.process_event(eid)[1]["skipped"]  # no more automatic attempts
    monkeypatch.setattr(webhook_inbox, "HANDLER", lambda e: {"status": "PROCESSED"})
    assert client.post(f"/api/inbox/events/{eid}/retry").json()["ok"]  # dashboard retry
    assert webhook_inbox.process_event(eid)[0] == 200 and ev("comment:fl1")["status"] == "PROCESSED"


def test_stale_processing_is_reclaimed(env, monkeypatch):
    monkeypatch.setattr(webhook_inbox, "ON_VERCEL", True)
    post_webhook(comment_payload(("st1", "AGENT")))
    eid = ev("comment:st1")["id"]
    update("UPDATE webhook_events SET status='PROCESSING', processing_started_at='2000-01-01T00:00:00Z', attempts=1 WHERE id=?", (eid,))
    assert webhook_inbox.sweep()["processed"] >= 1 and ev("comment:st1")["status"] == "PROCESSED"


def test_no_campaign_event_is_ignored_not_failed(env, monkeypatch):
    monkeypatch.setattr(webhook_inbox, "HANDLER", webhook_inbox._default_handler)
    post_webhook(comment_payload(("ig1", "AGENT"), media="no-such-media"))
    assert ev("comment:ig1")["status"] == "IGNORED"


def test_inbox_api_requires_login_paths_and_reports_health(env):
    r = client.get("/api/inbox/events").json()
    assert "counts" in r and r["app_secret_configured"] is True and r["qstash"]["configured"] is False
    assert not "/api/inbox/".startswith(base.webapp.OPEN_PATHS)  # admin endpoints are not under the public prefixes
