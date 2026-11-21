"""Phase 5: QStash scheduler + independent jobs. No real network (conftest); QStash faked at the HTTP layer.
Run:  python -m pytest tests -q
"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

import test_app as base
from test_webhooks import qstash_jwt, CUR, NXT
import qstash_client
import workflow
from config import IST
from generator import creative
from scheduler import daily_runner, jobs, qstash_schedules
from store import execute, get_settings, one, query, set_setting, update

client = base.client


class FakeQStashSchedules:
    def __init__(self):
        self.schedules = {"other-app-schedule": {"scheduleId": "other-app-schedule", "cron": "0 0 * * *", "destination": "https://elsewhere"}}
        self.calls = []

    def __call__(self, method, url, data=None, headers=None, timeout=None, **kw):
        self.calls.append((method, url))
        api = "https://qstash.upstash.io/v2/schedules"
        assert url.startswith(api), url
        assert headers["Authorization"] == "Bearer test-qstash-token"

        class R:
            def __init__(s, code=200, body=None): s.status_code, s._b, s.text = code, body, json.dumps(body)
            def json(s): return s._b
        if method == "POST":
            sid = headers["Upstash-Schedule-Id"]
            self.schedules[sid] = {"scheduleId": sid, "cron": headers["Upstash-Cron"], "destination": url[len(api) + 1:],
                                   "retries": headers["Upstash-Retries"], "method": headers["Upstash-Method"]}
            return R(200, {"scheduleId": sid})
        if method == "GET":
            return R(200, list(self.schedules.values()))
        if method == "DELETE":
            self.schedules.pop(url.rsplit("/", 1)[1], None)
            return R(200, {})
        raise AssertionError(method)


@pytest.fixture
def qs(monkeypatch):
    monkeypatch.setenv("QSTASH_TOKEN", "test-qstash-token")
    monkeypatch.setenv("QSTASH_CURRENT_SIGNING_KEY", CUR)
    monkeypatch.setenv("QSTASH_NEXT_SIGNING_KEY", NXT)
    monkeypatch.setenv("APP_URL", "https://insta-test.example")
    fake = FakeQStashSchedules()
    monkeypatch.setattr(qstash_client.requests, "request", fake)
    for k, v in {"research_time": "09:35", "target_publish_time": "10:03", "generate_time": "", "analytics_time": "23:30",
                 "scheduler_enabled": "1", "timezone": "Asia/Kolkata"}.items():
        set_setting(k, v)
    return fake


@pytest.fixture
def stub_jobs(monkeypatch):
    ran = []
    for k in jobs.JOBS:
        monkeypatch.setitem(jobs.JOBS[k], "fn", (lambda kk: lambda ctx: ran.append(kk) or {"success": True})(k))
    return ran


# ---------------------------------------------------------------- times and timezone
def test_ist_to_utc_conversion():
    assert workflow.ist_to_utc("2026-11-21T19:00") == "2026-11-21T13:30:00Z"
    assert workflow.ist_to_utc("2026-11-22T02:00") == "2026-11-21T20:30:00Z"   # crosses midnight
    assert workflow.utc_to_ist("2026-11-21T13:30:00Z") == "2026-11-21 19:00"


def test_generate_time_defaults_to_45_min_before_publishing():
    t = workflow.schedule_times({"research_time": "09:35", "target_publish_time": "10:03", "generate_time": ""})
    assert t == {"research": "09:35", "generate": "09:18", "publish": "10:03", "analytics": "23:30"}
    assert workflow.schedule_times({"target_publish_time": "00:20"})["generate"] == "23:35"  # wraps past midnight


def test_next_publish_time_today_or_tomorrow():
    s = {"target_publish_time": "19:00"}
    assert workflow.next_publish_utc(s, datetime(2026, 11, 21, 18, 0, tzinfo=IST)) == "2026-11-21T13:30:00Z"
    assert workflow.next_publish_utc(s, datetime(2026, 11, 21, 19, 30, tzinfo=IST)) == "2026-11-22T13:30:00Z"


# ---------------------------------------------------------------- QStash schedules
def test_schedules_built_from_dashboard_times(qs):
    out = qstash_schedules.sync()
    assert out["ok"], out
    s = qs.schedules
    assert s["sal-research"]["cron"] == "CRON_TZ=Asia/Kolkata 35 9 * * *"
    assert s["sal-generate"]["cron"] == "CRON_TZ=Asia/Kolkata 18 9 * * *"
    assert s["sal-publish"]["cron"] == "CRON_TZ=Asia/Kolkata 3 10 * * *"
    assert s["sal-analytics"]["cron"] == "CRON_TZ=Asia/Kolkata 30 23 * * *"
    assert s["sal-tick"]["cron"] == "*/10 * * * *"
    assert s["sal-publish"]["destination"] == "https://insta-test.example/api/queue/job/publish_due"
    assert all(v["retries"] == "3" and v["method"] == "POST" for k, v in s.items() if k.startswith("sal-"))
    assert len([k for k in s if k.startswith("sal-")]) == 5  # within the free plan's 10 schedules


def test_saving_times_in_dashboard_replaces_schedules_without_duplicates(qs):
    qstash_schedules.sync()
    r = client.post("/api/settings", json={"research_time": "08:00", "target_publish_time": "21:15"}).json()
    assert r["schedule_sync"]["ok"]
    s = qs.schedules
    assert s["sal-research"]["cron"].endswith(" 0 8 * * *") and s["sal-publish"]["cron"].endswith(" 15 21 * * *")
    assert s["sal-generate"]["cron"].endswith(" 30 20 * * *")
    assert len([k for k in s if k.startswith("sal-")]) == 5            # upsert by id: still 5, no duplicates
    assert "other-app-schedule" in s                                   # schedules we don't own are never touched


def test_obsolete_schedules_removed_and_pause_clears_ours(qs):
    qs.schedules["sal-pipeline"] = {"scheduleId": "sal-pipeline", "cron": "x", "destination": "old"}  # from an older version
    out = qstash_schedules.sync()
    assert "sal-pipeline" in out["deleted"] and "sal-pipeline" not in qs.schedules
    client.post("/api/settings", json={"scheduler_enabled": "0"})
    assert [k for k in qs.schedules if k.startswith("sal-")] == [] and "other-app-schedule" in qs.schedules
    client.post("/api/settings", json={"scheduler_enabled": "1"})
    assert len([k for k in qs.schedules if k.startswith("sal-")]) == 5


def test_sync_without_qstash_reports_clearly(monkeypatch):
    monkeypatch.delenv("QSTASH_TOKEN", raising=False)
    out = qstash_schedules.sync()
    assert not out["ok"] and "not configured" in out["error"]


# ---------------------------------------------------------------- signed job endpoint
def call_job(kind, key=CUR, url_kind=None):
    url = qstash_client.destination(f"/api/queue/job/{url_kind or kind}")
    return client.post(f"/api/queue/job/{kind}", content=b"{}", headers={"upstash-signature": qstash_jwt(b"{}", url, key=key)})


def test_signed_job_callback_runs_job_once_per_slot(qs, stub_jobs):
    execute("DELETE FROM jobs WHERE slot_key LIKE 'analytics:%'")
    r1 = call_job("analytics")
    assert r1.status_code == 200 and r1.json()["status"] == "SUCCESS" and r1.json()["slot"].startswith("analytics:")
    r2 = call_job("analytics")                                     # QStash redelivery / duplicate trigger
    assert r2.status_code == 200 and "already completed" in r2.json()["skipped"] and stub_jobs.count("analytics") == 1


def test_job_callback_rejects_bad_signatures(qs, stub_jobs):
    assert call_job("research", key="sig_attacker").status_code == 401
    assert call_job("research", url_kind="analytics").status_code == 401   # token for another job's URL
    assert client.post("/api/queue/job/research", content=b"{}").status_code == 401
    assert "research" not in stub_jobs


def test_tick_runs_maintenance_and_due_posts(qs, stub_jobs, monkeypatch):
    monkeypatch.setattr(workflow, "due_post", lambda now_utc=None: {"id": 1, "scheduled_for": "2000-01-01T00:00:00Z"})
    r = call_job("tick")
    assert r.status_code == 200 and "maintenance" in stub_jobs and "publish_due" in stub_jobs


# ---------------------------------------------------------------- retries, recovery, concurrency
def test_failed_job_returns_500_so_qstash_retries(qs, monkeypatch):
    monkeypatch.setitem(jobs.JOBS["analytics"], "fn", lambda ctx: {"success": False, "error": "Graph API down"})
    execute("DELETE FROM jobs WHERE slot_key LIKE 'analytics:%'")
    r = call_job("analytics")
    assert r.status_code == 500 and r.json()["status"] == "FAILED" and "Graph API down" in r.json()["error"]


def test_local_tick_retries_with_backoff_then_stops(monkeypatch):
    calls = []

    def flaky(ctx):
        calls.append(1)
        return {"success": False, "error": "temporary"}
    for k in jobs.JOBS:
        monkeypatch.setitem(jobs.JOBS[k], "fn", lambda ctx: {"success": True})
    monkeypatch.setitem(jobs.JOBS["research"], "fn", flaky)
    set_setting("research_time", "06:00"); set_setting("scheduler_enabled", "1")
    day = datetime(2031, 3, 3, 6, 0, tzinfo=IST)

    def at(minute):  # finished_at of failed jobs is "now" in IST; shift it to the simulated time
        daily_runner.tick(day + timedelta(minutes=minute))
        update("UPDATE jobs SET finished_at=? WHERE slot_key='research:2031-03-03' AND status='FAILED' AND finished_at NOT LIKE '2031-%'",
               ((day + timedelta(minutes=minute)).strftime("%Y-%m-%d %H:%M:%S"),))
    at(0); at(1)                     # fail #1, then 1 min later: still inside the 2-min backoff
    assert len(calls) == 1
    at(3)                            # after 2 min → retry (fail #2)
    at(6)                            # 4-min backoff not over
    assert len(calls) == 2
    at(8); at(25)                    # retry #3 at 8 min, then stop: 3 failures is the limit
    assert len(calls) == 3


def test_concurrent_triggers_run_job_once(monkeypatch):
    calls = []
    monkeypatch.setitem(jobs.JOBS["generate"], "fn", lambda ctx: (calls.append(1), time.sleep(0.3), {"success": True})[2])
    day = datetime(2032, 5, 5, 12, 0, tzinfo=IST)
    results = []
    threads = [threading.Thread(target=lambda: results.append(jobs.run("generate", "qstash", now=day))) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and sum(1 for c, r in results if "skipped" in r) == 4


def test_expired_lease_is_taken_over():
    update("INSERT OR IGNORE INTO job_locks (kind, holder, lease_until) VALUES ('maintenance', '', '')")
    update("UPDATE job_locks SET holder='dead-function', lease_until='2000-01-01T00:00:00Z' WHERE kind='maintenance'")
    h = jobs.acquire("maintenance")
    assert h and jobs.acquire("maintenance") is None
    jobs.release("maintenance", h)
    assert jobs.acquire("maintenance")
    update("UPDATE job_locks SET lease_until='' WHERE kind='maintenance'")


def test_maintenance_closes_stale_running_jobs(monkeypatch):
    monkeypatch.setattr(workflow, "recover_stuck_publishing", lambda *a, **k: [])  # other tests leave stuck posts (would need Meta)
    jid = execute("INSERT INTO jobs (kind, status, started_at) VALUES ('research','RUNNING','2001-01-01 00:00:00')")
    code, res = jobs.run("maintenance", "test")
    assert code == 200 and one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "FAILED", res.get("error")


def test_maintenance_step_failure_does_not_block_other_steps(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Meta unreachable")
    monkeypatch.setattr(workflow, "recover_stuck_publishing", boom)
    jid = execute("INSERT INTO jobs (kind, status, started_at) VALUES ('research','RUNNING','2001-01-01 00:00:00')")
    code, res = jobs.run("maintenance", "test")
    assert code == 500 and "Meta unreachable" in res["error"]                       # reported → QStash retries
    assert one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "FAILED"   # but stale jobs were still closed


# ---------------------------------------------------------------- generate / publish_due / per-post schedule
@pytest.fixture
def content(monkeypatch):
    monkeypatch.setattr(creative, "fetch_readme", lambda url: {"install": ["pip install demo-tool"], "images": [], "features": []})
    monkeypatch.setattr(workflow, "render", lambda cid, only=None, ctx=None: base.fake_render(cid))
    set_setting("min_qc_score", "0"); set_setting("max_posts_per_day", "100")
    published = []
    monkeypatch.setattr(workflow, "publish", lambda cid, ctx=None: published.append(cid) or {"success": True, "media_id": "M1"})
    yield published
    set_setting("min_qc_score", "85"); set_setting("max_posts_per_day", "1")


class Ctx:
    def stage(self, *a): pass
    def log(self, *a): pass


def test_generate_in_auto_mode_schedules_for_publishing_time(content):
    base.seed_topic(opportunity_score=999)
    set_setting("publishing_mode", "AUTO"); set_setting("target_publish_time", "19:00")
    try:
        r = workflow.run_generate(Ctx())
    finally:
        set_setting("publishing_mode", "REVIEW")
    c = one("SELECT status, scheduled_for, approved_at FROM carousels WHERE id=?", (r["carousel_id"],))
    assert r["status"] == "SCHEDULED" and c["status"] == "PENDING_APPROVAL" and c["approved_at"].endswith("Z")
    assert c["scheduled_for"].endswith("T13:30:00Z") and content == []    # generate never publishes itself


def test_generate_in_review_mode_waits_for_approval(content):
    base.seed_topic(opportunity_score=998)
    r = workflow.run_generate(Ctx())
    c = one("SELECT status, scheduled_for, approved_at FROM carousels WHERE id=?", (r["carousel_id"],))
    assert r["status"] == "PENDING_APPROVAL" and c["approved_at"] in ("", None) and content == []


def test_publish_due_exact_time(content):
    cid = base.queued_post()
    when = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    workflow.schedule_post(cid, when)
    assert workflow.due_post() is None or workflow.due_post()["id"] != cid      # not before its time
    assert workflow.due_post(when)["id"] == cid                                  # exactly at its time
    update("UPDATE carousels SET scheduled_for=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), cid))
    r = workflow.run_publish_due(Ctx())
    assert r["carousel_id"] == cid and content == [cid]


def test_legacy_rows_without_approval_are_never_auto_published(content):
    cid = base.queued_post()
    update("UPDATE carousels SET scheduled_for='2000-01-01T00:00:00Z', approved_at='' WHERE id=?", (cid,))  # old unused column value
    assert workflow.due_post() is None or workflow.due_post()["id"] != cid


def test_missed_schedule_is_not_published_late(content):
    cid = base.queued_post()
    workflow.schedule_post(cid, (datetime.now(timezone.utc) - timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for _ in range(5):
        r = workflow.run_publish_due(Ctx())
        if r.get("carousel_id") == cid:
            break
    assert r["status"] == "MISSED" and cid not in content and one("SELECT approved_at FROM carousels WHERE id=?", (cid,))["approved_at"] == ""


def test_daily_limit_respected(content):
    set_setting("max_posts_per_day", "0")
    cid = base.queued_post()
    workflow.schedule_post(cid, (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    r = workflow.run_publish_due(Ctx())
    assert r["status"] in ("LIMIT", "MISSED") and cid not in content
    workflow.unschedule_post(cid)


def test_schedule_api_converts_ist_and_validates(content):
    cid = base.queued_post()
    future_ist = (datetime.now(IST) + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
    at = future_ist.strftime("%Y-%m-%dT%H:%M")
    assert client.post(f"/api/carousels/{cid}/schedule", json={"at": at}).status_code == 400            # confirm required
    r = client.post(f"/api/carousels/{cid}/schedule", json={"at": at, "confirm": True})
    assert r.status_code == 200 and r.json()["scheduled_for"] == future_ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert client.post(f"/api/carousels/{cid}/schedule", json={"at": "2001-01-01T10:00", "confirm": True}).status_code == 400  # past
    assert client.delete(f"/api/carousels/{cid}/schedule").json()["approved_at"] == ""


def test_scheduler_status_endpoint(qs):
    r = client.get("/api/scheduler/status").json()
    assert r["qstash_configured"] and r["times"]["generate"] == "09:18" and set(r["next_runs"]) >= {"research", "generate", "publish", "analytics"}
    assert set(r["wanted"]) == {"sal-research", "sal-generate", "sal-publish", "sal-analytics", "sal-tick"}
