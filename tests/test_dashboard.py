"""Phase 6: the automation overview must reflect real database state (no hardcoded success). Run: python -m pytest tests -q"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import test_app as base
from scheduler import jobs
from store import execute, one, set_setting, ts, update

client = base.client


def overview():
    r = client.get("/api/automation/overview")
    assert r.status_code == 200
    return r.json()


def add_job(kind, status, error="", started=None):
    return execute("INSERT INTO jobs (kind, trigger, status, started_at, finished_at, error) VALUES (?,?,?,?,?,?)",
                   (kind, "test", status, started or ts(), ts() if status != "RUNNING" else None, error))


def test_job_status_and_failure_message_shown():
    add_job("analytics", "SUCCESS")
    jid = add_job("analytics", "FAILED", "Couldn't read recent media: Session has expired")
    a = overview()["systems"]["analytics"]
    assert a["status"] == "FAILED" and a["last"]["id"] == jid and a["failed_7d"] >= 1 and a["success_7d"] >= 1
    assert a["latest_error"]["error"] == "Couldn't read recent media: Session has expired"
    add_job("analytics", "SUCCESS")
    assert overview()["systems"]["analytics"]["status"] == "OK"  # a later success clears the status (error stays in history)


def test_running_job_reported_live():
    jid = add_job("research", "RUNNING")
    update("UPDATE jobs SET stage='GitHub Discovery', progress=40 WHERE id=?", (jid,))
    r = overview()["systems"]["research"]
    assert r["status"] == "RUNNING" and r["running"]["stage"] == "GitHub Discovery"
    update("UPDATE jobs SET status='SUCCESS', finished_at=? WHERE id=?", (ts(), jid))


def test_generation_counts_legacy_pipeline_runs_too():
    add_job("pipeline", "FAILED", "No verified, unused topic")
    g = overview()["systems"]["generate"]
    assert g["last"]["kind"] == "pipeline" and g["status"] == "FAILED"
    add_job("generate", "SUCCESS")


def test_scheduler_status_and_next_runs():
    set_setting("scheduler_enabled", "1"); set_setting("research_time", "09:35")
    o = overview()
    assert o["enabled"] and o["systems"]["research"]["next_at"] and o["times"]["research"] == "09:35"
    set_setting("scheduler_enabled", "0")
    assert overview()["systems"]["research"]["next_at"] is None
    set_setting("scheduler_enabled", "1")


def test_publishing_post_counts():
    cid = base.queued_post()
    when = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    import workflow
    workflow.schedule_post(cid, when)
    p = overview()["systems"]["publishing"]["posts"]
    assert p["scheduled"] >= 1 and p["next_scheduled"]["scheduled_for"] <= when
    workflow.unschedule_post(cid)


def test_webhook_health_reflects_real_events(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "x")
    monkeypatch.delenv("QSTASH_TOKEN", raising=False)
    set_setting("webhook_verified_at", "")
    tok = base.webapp.webhook_token()
    client.get("/api/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": tok, "hub.challenge": "1"})
    execute("""INSERT INTO webhook_events (event_key, comment_id, kind, status, received_at, error, attempts)
               VALUES ('comment:dash-f1','dash-f1','comment','FAILED',?, 'Graph API down', 5)""", (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    set_setting("webhook_last_received_at", "2026-11-21T10:00:00Z")
    o = overview()
    w = o["webhook"]
    assert w["verified_at"].endswith("Z") and w["app_secret_configured"] is True and w["last_received_at"] == "2026-11-21T10:00:00Z"
    assert w["events"]["FAILED"] >= 1 and w["qstash"]["configured"] is False
    assert w["subscription"]["checked_at"] == "" and "Meta configuration check" in w["subscription"]["note"]   # unknown, not faked
    c = o["systems"]["comments"]
    assert c["status"] == "FAILED" and c["failed_7d"] >= 1 and c["latest_error"]["error"] == "Graph API down"


def test_dm_delivery_status_and_failed_count():
    camp = client.post("/api/campaigns", json={"name": "Dash", "keyword": "DASH", "media_id": "1799001", "resource_pack": "x"}).json()
    execute("""INSERT INTO dm_deliveries (campaign_id, comment_id, status, error, created_at, updated_at, sent_at)
               VALUES (?, 'dash-ok', 'RESOURCE_SENT', '', ?, ?, ?)""", (camp["id"], ts(), ts(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    execute("""INSERT INTO dm_deliveries (campaign_id, comment_id, status, error, created_at, updated_at)
               VALUES (?, 'dash-bad', 'FAILED', 'This message is sent outside of allowed window. [code 10 · subcode 2534022]', ?, ?)""", (camp["id"], ts(), ts()))
    o = overview()
    d = o["systems"]["dm"]
    assert d["status"] == "FAILED" and "outside of allowed window" in d["latest_error"]["error"] and d["counts"]["RESOURCE_SENT"] >= 1
    assert o["webhook"]["failed_dm_count"] >= 1 and o["webhook"]["last_dm_at"]


def wait_job(jid, timeout=10):
    import time
    end = time.time() + timeout
    while time.time() < end:
        j = one("SELECT status, trigger, error FROM jobs WHERE id=?", (jid,))
        if j["status"] != "RUNNING":
            return j
        time.sleep(0.05)
    raise AssertionError("job still running")


def test_run_now_uses_lease_and_requires_confirm_for_publishing(monkeypatch):
    ran = []
    monkeypatch.setitem(jobs.JOBS["analytics"], "fn", lambda ctx: ran.append(1) or {"success": True, "posts_updated": 0})
    r = client.post("/api/automation/run/analytics", json={}).json()
    j = wait_job(r["job_id"])   # locally "Run now" runs in a background thread
    assert r["started"] and j["status"] == "SUCCESS" and j["trigger"] == "manual" and ran
    assert client.post("/api/automation/run/publish_due", json={}).status_code == 400            # confirm required
    assert client.post("/api/automation/run/nope", json={}).status_code == 404
    holder = jobs.acquire("analytics")                                                          # a scheduled run holds the lease
    r = client.post("/api/automation/run/analytics", json={}).json()
    j = wait_job(r["job_id"])
    assert j["status"] == "FAILED" and "already in progress" in j["error"]
    jobs.release("analytics", holder)


def test_inbox_events_listing_for_dm_page():
    r = client.get("/api/inbox/events?limit=5").json()
    assert isinstance(r["events"], list) and "counts" in r and len(r["events"]) <= 5
