"""API + workflow tests. Isolated temp DB/output; all Meta/GitHub network calls are mocked.

Run:  python -m pytest tests -q
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sonu_ai_lab_test_"))
os.environ.update(CMS_DB_PATH=str(TMP / "test.db"), CMS_OUTPUT_DIR=str(TMP / "out"), CMS_DISABLE_SCHEDULER="1")
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "dashboard"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as webapp  # noqa: E402  (runs migrate() on the temp DB)
import workflow  # noqa: E402
from automation.comment_responder import CommentResponder  # noqa: E402
from config import IST  # noqa: E402
from generator import creative  # noqa: E402
from research.harvester import recommend_format  # noqa: E402
from scheduler import daily_runner  # noqa: E402
from store import execute, get_setting, one, set_setting  # noqa: E402

client = TestClient(webapp.app)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(creative, "fetch_readme", lambda url: {"install": ["pip install demo-tool"], "images": [], "features": []})


def seed_topic(**kw):
    t = dict(title="acme/demo-tool", source="GitHub", url=f"https://github.com/acme/demo-{datetime.now().timestamp()}",
             description="An open-source local-first tool that turns prompts into short videos with one command.",
             category="Trending GitHub", published_date="2026-11-01", verification_status="VERIFIED",
             verification_note="ok", why_it_matters="1,200 stars in 19 days.", source_kind="github",
             facts_json=json.dumps(["1,200 GitHub stars", "Created 2026-11-01", "Written in Python", "License: MIT", "Last commit 2026-11-19"]),
             opportunity_score=80, status="NEW", preview_image_url="")
    t.update(kw)
    cols = ",".join(t)
    return execute(f"INSERT INTO topics ({cols}) VALUES ({','.join('?' * len(t))})", tuple(t.values()))


def fake_render(cid):
    """Write placeholder JPGs and mark rendered, without launching a browser."""
    c = workflow.load_carousel(cid)
    d = workflow.carousel_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, len(c["slide_data"]["slides"]) + 1):
        (d / f"slide_{i:02d}.jpg").write_bytes(b"\xff\xd8\xff")
    execute("UPDATE carousels SET rendered_at=? WHERE id=?", ("9999-12-31 00:00:00", cid))


# ---------------------------------------------------------------- settings
def test_settings_validation_and_auto_mode_confirmation():
    r = client.post("/api/settings", json={"target_publish_time": "25:99"})
    assert r.status_code == 400 and "target_publish_time" in r.json()["fields"]
    r = client.post("/api/settings", json={"publishing_mode": "AUTO"})
    assert r.status_code == 400 and get_setting("publishing_mode") == "REVIEW"
    r = client.post("/api/settings", json={"publishing_mode": "AUTO", "confirm_auto": True})
    assert r.status_code == 200 and get_setting("publishing_mode") == "AUTO"
    r = client.post("/api/settings", json={"publishing_mode": "AUTO", "research_time": "09:40"})  # already AUTO: no re-confirm
    assert r.status_code == 200 and get_setting("research_time") == "09:40"
    client.post("/api/settings", json={"publishing_mode": "REVIEW"})
    assert client.post("/api/settings", json={"auto_categories": "Not A Category"}).status_code == 400


# ---------------------------------------------------------------- creative
def test_format_never_padded_and_news_single():
    news = {"category": "AI Industry News", "facts": ["10 points on Hacker News"], "description": ""}
    assert recommend_format(news)["format"] == "SINGLE"
    tid = seed_topic(description="short")  # thin material
    c = client.post("/api/carousels", json={"topic_id": tid, "slides": 10}).json()
    assert c["slide_count"] < 10 and c["note"] and "not padded" in c["note"]
    assert c["slide_data"]["slides"][-1]["layout"] == "cta"


def test_create_edit_cta_sync_and_limits():
    tid = seed_topic()
    c = client.post("/api/carousels", json={"topic_id": tid}).json()
    assert c["status"] == "DRAFT" and 1 <= c["slide_count"] <= 10 and c["qc"]["checks"]
    r = client.put(f"/api/carousels/{c['id']}", json={"cta_keyword": "repo!"}).json()
    assert r["cta_keyword"] == "REPO"
    assert any(s.get("keyword") == "REPO" for s in r["slide_data"]["slides"])
    assert client.put(f"/api/carousels/{c['id']}", json={"slides": [{"layout": "point"}] * 11}).status_code == 400
    html = client.get(f"/api/carousels/{c['id']}/slides/{r['slide_count']}.html").text  # CTA slide
    assert "<section" in html and "REPO" in html


def test_submit_requires_fresh_render():
    c = client.post("/api/carousels", json={"topic_id": seed_topic()}).json()
    r = client.post(f"/api/carousels/{c['id']}/submit")
    assert r.status_code == 400 and "Render" in r.json()["error"]
    fake_render(c["id"])
    assert client.post(f"/api/carousels/{c['id']}/submit").json()["status"] == "PENDING_APPROVAL"


# ---------------------------------------------------------------- publishing
def queued_post():
    c = client.post("/api/carousels", json={"topic_id": seed_topic()}).json()
    fake_render(c["id"])
    client.post(f"/api/carousels/{c['id']}/submit")
    return c["id"]


def test_publish_requires_confirmation():
    cid = queued_post()
    assert client.post(f"/api/carousels/{cid}/publish", json={}).status_code == 400


def test_publish_failure_never_marks_published(monkeypatch):
    cid = queued_post()
    monkeypatch.setattr(workflow.meta, "_get", lambda *a, **k: {"ok": False, "error": "Session has expired"})
    res = workflow.publish(cid)
    assert res["success"] is False
    c = one("SELECT status, error_message FROM carousels WHERE id=?", (cid,))
    assert c["status"] == "PUBLISH_FAILED" and "expired" in c["error_message"]


def test_publish_success_records_meta_ids(monkeypatch):
    cid = queued_post()
    monkeypatch.setattr(workflow.meta, "_get", lambda *a, **k: {"ok": True, "data": {"username": "tester"}})
    monkeypatch.setattr(workflow.media, "public_url", lambda p: "https://cdn.example/x.jpg")
    monkeypatch.setattr(workflow.meta, "publish_carousel", lambda urls, cap: {"success": True, "post_id": "1790001"})
    monkeypatch.setattr(workflow.meta, "publish_single_image", lambda url, cap: {"success": True, "post_id": "1790001"})
    monkeypatch.setattr(workflow.meta, "get_permalink", lambda mid: "https://www.instagram.com/p/ABC123/")
    assert workflow.publish(cid)["success"]
    c = one("SELECT * FROM carousels WHERE id=?", (cid,))
    assert c["status"] == "PUBLISHED" and c["ig_media_id"] == "1790001" and c["permalink"].endswith("/p/ABC123/")
    assert client.put(f"/api/carousels/{cid}", json={"caption": "x" * 100}).status_code == 400  # published = read-only


# ---------------------------------------------------------------- comment-to-DM
class FakeResponder(CommentResponder):
    def __init__(self, comments):
        self.calls, self.comments = [], comments

    def get_post_comments(self, media_id):
        return True, self.comments, ""

    def send_private_reply(self, cid, text):
        self.calls.append(("private", cid)); return True, ""

    def reply_publicly(self, cid, text):
        self.calls.append(("public", cid)); return True, ""

    msgs, following = 0, False

    def user_message_count(self, igsid):
        return self.msgs, ""

    def follower_status(self, igsid):
        return self.following, ""

    def send_dm(self, igsid, text, button=None):
        self.calls.append(("dm", button or "text")); return True, ""

    def send_image(self, igsid, url):
        self.calls.append(("image", url)); return True, ""


def test_dm_button_flow_follow_gate_and_guide_delivery():
    r = client.post("/api/campaigns", json={"name": "Flow", "keyword": "PACK", "media_id": "1790002", "resource_pack": "guide text",
                                            "follow_gate": True, "active": True}).json()
    execute("UPDATE campaigns SET guide_images=? WHERE id=?", (json.dumps(["https://img/1.jpg", "https://img/2.jpg"]), r["id"]))
    camp = one("SELECT * FROM campaigns WHERE id=?", (r["id"],))
    fr = FakeResponder([{"id": "p1", "text": "pack", "from": {"id": "u9", "username": "z"}}])
    fr.scan_campaign(camp, dry_run=False)                       # comment → private reply with button
    assert one("SELECT status FROM dm_deliveries WHERE comment_id='p1'")["status"] == "AWAITING_TAP"
    fr.calls.clear(); fr.scan_campaign(camp, dry_run=False)     # no tap yet → nothing sent
    assert fr.calls == []
    fr.msgs = 1; fr.scan_campaign(camp, dry_run=False)          # tapped, not following → nudge with button
    assert fr.calls == [("dm", "I'm following ✅")]
    assert one("SELECT status FROM dm_deliveries WHERE comment_id='p1'")["status"] == "AWAITING_FOLLOW"
    fr.calls.clear(); fr.msgs, fr.following = 2, True
    fr.scan_campaign(camp, dry_run=False)                       # tapped again, now following → guide text + pages
    assert fr.calls == [("dm", "text"), ("image", "https://img/1.jpg"), ("image", "https://img/2.jpg")]
    assert one("SELECT status FROM dm_deliveries WHERE comment_id='p1'")["status"] == "RESOURCE_SENT"


def test_own_comments_are_recorded_not_messaged():
    set_setting("connected_handle", "@me.lab")
    r = client.post("/api/campaigns", json={"name": "Own", "keyword": "AGENT", "media_id": "1790003", "resource_pack": "x", "active": True}).json()
    camp = one("SELECT * FROM campaigns WHERE id=?", (r["id"],))
    fr = FakeResponder([{"id": "o1", "text": "Agent", "from": {"id": "me", "username": "me.lab"}}])
    rep = fr.scan_campaign(camp, dry_run=False)
    assert fr.calls == [] and rep["matches"] == [] and len(rep["skipped_own"]) == 1
    assert one("SELECT status FROM dm_deliveries WHERE comment_id='o1'")["status"] == "SKIPPED_SELF"
    set_setting("connected_handle", "")


def test_pack_post_and_guide(monkeypatch):
    monkeypatch.setattr(creative, "fetch_readme", lambda url: {"install": ["pip install x"], "images": [], "features": ["Feature one is useful", "Feature two is useful", "Feature three"]})
    ids = [seed_topic(cost_type="Open Source", category="Video & Animation") for _ in range(3)]
    c = client.post("/api/carousels", json={"topic_ids": ids}).json()
    assert [s["layout"] for s in c["slide_data"]["slides"]] == ["pack_cover", "showcase", "showcase", "showcase", "cta"]
    assert c["headline"] == "3 free AI video tools trending this week"
    assert "pip install x" in c["resource_pack"] and len(c["resource_pack"]) <= 1000
    g = client.get(f"/api/carousels/{c['id']}/guide.html").text
    assert g.count('class="g"') == 7  # index page + overview & setup page per tool
    assert client.post("/api/carousels", json={"topic_ids": [ids[0]]}).status_code == 400


def test_dm_private_only_follow_gate_and_dedupe():
    r = client.post("/api/campaigns", json={"name": "Test", "keyword": "agent", "media_id": "1790001", "resource_pack": "link",
                                            "follow_gate": True, "public_reply_enabled": False, "active": True}).json()
    camp = one("SELECT * FROM campaigns WHERE id=?", (r["id"],))
    comments = [{"id": "c1", "text": "AGENT please", "from": {"id": "u1", "username": "a"}},
                {"id": "c2", "text": "magenta", "from": {"id": "u2", "username": "b"}},  # 'agent' inside a word: no match
                {"id": "c3", "text": "nice post", "from": {"id": "u3", "username": "c"}}]
    fr = FakeResponder(comments)
    preview = fr.scan_campaign(camp, dry_run=True)
    assert [m["comment_id"] for m in preview["matches"]] == ["c1"] and fr.calls == []  # dry run sends nothing
    fr.scan_campaign(camp, dry_run=False)
    assert fr.calls == [("private", "c1")]  # private reply only, no public reply
    assert one("SELECT status FROM dm_deliveries WHERE comment_id='c1'")["status"] == "AWAITING_TAP"
    fr.calls.clear()
    fr.scan_campaign(camp, dry_run=False)
    assert fr.calls == []  # never messaged twice


def test_live_scan_requires_active_and_confirm():
    r = client.post("/api/campaigns", json={"name": "Paused", "keyword": "REPO", "resource_pack": "x"}).json()
    assert client.post(f"/api/campaigns/{r['id']}/scan", json={"live": True, "confirm": True}).status_code == 400
    assert client.post("/api/campaigns", json={"name": "Bad", "keyword": "X", "resource_pack": "x"}).status_code == 400


# ---------------------------------------------------------------- scheduler
def test_scheduler_fires_once_inside_window(monkeypatch):
    started = []
    monkeypatch.setattr(daily_runner, "start_job", lambda kind, fn, trigger: started.append(kind) or {"started": True})
    set_setting("research_time", "17:30"); set_setting("target_publish_time", "19:00"); set_setting("scheduler_enabled", "1")
    for k in ("last_research_slot", "last_pipeline_slot"):
        execute("DELETE FROM settings WHERE key=?", (k,))
    day = datetime(2026, 11, 21, tzinfo=IST)
    assert daily_runner.tick(day.replace(hour=17, minute=10)) == []           # too early
    assert daily_runner.tick(day.replace(hour=17, minute=31)) == ["research"]  # fires
    assert daily_runner.tick(day.replace(hour=17, minute=40)) == []           # once per day
    assert daily_runner.tick(day.replace(hour=20, minute=0)) == []            # pipeline window (19:00–19:30) missed
    set_setting("scheduler_enabled", "0")
    assert daily_runner.tick(day.replace(hour=19, minute=5)) == []


# ---------------------------------------------------------------- real render (headless browser)
@pytest.mark.skipif(not creative.find_browser(), reason="no Edge/Chrome installed")
def test_real_render_produces_instagram_jpgs():
    slides = [{"layout": "cover", "kicker": "Test", "title": "Hello", "body": "World"}, {"layout": "cta", "keyword": "AGENT", "items": ["x"]}]
    paths = creative.render_to_jpgs(creative.slide_document(slides, {}, "@h", "SONU AI LAB"), 2, TMP / "render", ["a.jpg", "b.jpg"])
    from PIL import Image
    assert [Image.open(p).size for p in paths] == [(1080, 1350), (1080, 1350)]


# ---------------------------------------------------------------- cloud: login, cron, webhooks, Postgres dialect
def test_login_protects_api(monkeypatch):
    monkeypatch.setattr(webapp, "APP_PASSWORD", "s3cret-pass")
    c = TestClient(webapp.app)
    assert c.get("/api/state").status_code == 401
    assert c.get("/api/health").status_code == 200 and c.get("/").status_code == 200
    assert c.post("/api/login", json={"password": "nope"}).status_code == 401
    assert c.post("/api/login", json={"password": "s3cret-pass"}).status_code == 200
    assert c.get("/api/state").status_code == 200  # session cookie now set
    c.post("/api/logout")
    assert c.get("/api/state").status_code == 401


def test_cron_needs_secret(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.get("/api/cron/research").status_code == 401
    monkeypatch.setenv("CRON_SECRET", "abc")
    assert client.get("/api/cron/research", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_webhook_verify_and_wake(monkeypatch):
    tok = webapp.webhook_token()
    ok = client.get("/api/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": tok, "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert client.get("/api/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"}).status_code == 403
    seen = []
    monkeypatch.setattr(webapp.responder, "scan_campaign", lambda camp, dry_run, log: seen.append((camp["media_id"], dry_run)) or {"matches": [], "followups": []})
    monkeypatch.setattr(webapp.responder, "reload", lambda: None)
    monkeypatch.setattr(webapp.meta, "app_secret", "")
    client.post("/api/campaigns", json={"name": "WH", "keyword": "HOOK", "media_id": "1790999", "resource_pack": "x", "active": True})
    client.post("/api/webhooks/instagram", json={"object": "instagram", "entry": [{"changes": [{"field": "comments", "value": {"media": {"id": "1790999"}}}]}]})
    assert ("1790999", False) in seen


def test_postgres_dialect_translation():
    from store import to_pg
    assert to_pg("INSERT OR IGNORE INTO t (a) VALUES (?)") == "INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING"
    assert "ON CONFLICT (key) DO UPDATE" in to_pg("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)")
    assert to_pg("SELECT 1 WHERE a LIKE ?") == "SELECT 1 WHERE a LIKE %s"


def test_postgres_insert_returning_only_for_id_tables(monkeypatch):
    import store
    sent = []

    class FakeCur:
        description = None
        rowcount = 1
        def execute(self, q, a): sent.append(q)
        def fetchall(self): return []

    class FakeRaw:
        def cursor(self): return FakeCur()
    monkeypatch.setattr(store, "IS_PG", True)
    c = store.Conn.__new__(store.Conn); c.raw = FakeRaw()
    c.execute("INSERT INTO secrets (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("a", "b"))
    c.execute("INSERT INTO events (ts, kind) VALUES (?, ?)", ("t", "k"))
    assert "RETURNING" not in sent[0] and sent[1].endswith("RETURNING id")
