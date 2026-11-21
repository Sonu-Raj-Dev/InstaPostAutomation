"""Phase 2: manual publishing reliability. Every Graph API call goes to FakeGraph, which raises on any URL it
doesn't know, so these tests cannot reach the real Instagram account.

Run:  python -m pytest tests -q
"""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
import requests

import test_app as base  # shares the isolated temp DB, app client and post helpers
import meta_graph_client as mgc
import workflow
from store import execute, one, update

client = base.client
SLIDE = "https://cdn.example/slide_{}.jpg"


class Resp:
    def __init__(self, status=200, body=None, ctype="application/json"):
        self.status_code, self._body, self.headers = status, body or {}, {"content-type": ctype}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def meta_err(code, msg, subcode=None, status=400):
    return Resp(status, {"error": {"message": msg, "type": "OAuthException", "code": code, "error_subcode": subcode, "fbtrace_id": "TRACE1"}})


class FakeGraph:
    """Minimal stateful stand-in for graph.facebook.com + the image CDN."""

    def __init__(self):
        self.calls, self.lock = [], threading.RLock()
        self.scopes = ["instagram_basic", "instagram_content_publish"]
        self.account = Resp(200, {"id": "IG", "username": "sonu.ai.lab"})
        self.bad_images = {}            # url -> Resp
        self.child_fail_at = None       # 1-based child index that Meta rejects
        self.parent_fail = None         # Resp for the CAROUSEL container call
        self.single_fail = None         # Resp for the single-image container call
        self.status = {}                # container id -> list of status_code values (last one repeats)
        self.publish_mode = "ok"        # ok | error | timeout_published | timeout_not_published
        self.publish_delay = 0.0
        self.published = {}             # container id -> media id
        self.n = 0

    def _next(self, prefix):
        with self.lock:
            self.n += 1
            return f"{prefix}{self.n}"

    def __call__(self, method, url, timeout=None, params=None, **kw):
        params = dict(params or {})
        if url.startswith("https://cdn.example/"):
            return self.bad_images.get(url, Resp(200, {}, "image/jpeg"))
        assert url.startswith(mgc.GRAPH_BASE_URL + "/"), f"unexpected network call: {url}"
        path = url[len(mgc.GRAPH_BASE_URL) + 1:]
        assert params.get("access_token") or params.get("input_token"), "Graph call without a token"
        with self.lock:
            self.calls.append((method, path, {k: v for k, v in params.items() if k != "access_token"}))
        if path == "debug_token":
            return Resp(200, {"data": {"is_valid": True, "scopes": self.scopes}})
        if method == "GET" and path == "IG" and params.get("fields") == "username":
            return self.account
        if method == "POST" and path == "IG/media":
            if params.get("media_type") == "CAROUSEL":
                return self.parent_fail or Resp(200, {"id": self._next("P")})
            if params.get("is_carousel_item"):
                idx = sum(1 for c in self.calls if c[1] == "IG/media" and c[2].get("is_carousel_item"))
                if self.child_fail_at == idx:
                    return meta_err(9004, "Media download has failed.", 2207052)
                return Resp(200, {"id": self._next("C")})
            return self.single_fail or Resp(200, {"id": self._next("S")})
        if method == "POST" and path == "IG/media_publish":
            import time
            time.sleep(self.publish_delay)
            cid = params["creation_id"]
            if self.publish_mode == "error":
                return meta_err(9007, "Media ID is not available", 2207027)
            if self.publish_mode in ("ok", "timeout_published"):
                with self.lock:
                    self.published.setdefault(cid, self._next("M"))
            if self.publish_mode.startswith("timeout"):
                raise requests.Timeout("read timed out")
            return Resp(200, {"id": self.published[cid]})
        if method == "GET" and path == "IG/media":
            return Resp(200, {"data": [{"id": m, "caption": self.caption, "timestamp": "2099-01-01T00:00:00+0000"} for m in self.published.values()]})
        if method == "GET" and params.get("fields") == "status_code,status":
            if path in self.published:
                return Resp(200, {"status_code": "PUBLISHED", "id": path})
            seq = self.status.get(path, ["FINISHED"])
            code = seq.pop(0) if len(seq) > 1 else seq[0]
            return Resp(200, {"status_code": code, "status": "Error: unsupported format" if code == "ERROR" else "", "id": path})
        if method == "GET" and params.get("fields") == "permalink":
            return Resp(200, {"permalink": f"https://www.instagram.com/p/{path}/"})
        raise AssertionError(f"FakeGraph has no route for {method} {path}")

    def publish_calls(self):
        return [c for c in self.calls if c[1] == "IG/media_publish"]


@pytest.fixture
def graph(monkeypatch):
    g = FakeGraph()
    g.caption = ""
    monkeypatch.setattr(mgc.requests, "request", g)
    monkeypatch.setattr(mgc.requests, "get", lambda url, params=None, timeout=None, **kw: g("GET", url, timeout, params))
    monkeypatch.setattr(mgc.time, "sleep", lambda s: None)
    monkeypatch.setattr(workflow.time, "sleep", lambda s: None)
    monkeypatch.setattr(mgc, "POLL_TIMEOUT_S", 1)
    meta = workflow.meta  # never read the real .env token in tests
    monkeypatch.setattr(meta, "reload", lambda: (setattr(meta, "access_token", "test-token"), setattr(meta, "ig_user_id", "IG")))
    monkeypatch.setattr(workflow, "auto_campaign", lambda cid, mid, log=None: None)
    return g


def post(slides=3):
    """A queued post whose rendered slides are public HTTPS JPEGs (what Vercel Blob gives in production)."""
    cid = base.queued_post()
    c = workflow.load_carousel(cid)
    sd = c["slide_data"]
    sd["slides"] = sd["slides"][:slides]
    execute("UPDATE carousels SET slide_data_json=?, rendered_json=?, rendered_at=?, slide_count=? WHERE id=?",
            (json.dumps(sd), json.dumps([SLIDE.format(i) for i in range(1, slides + 1)]), "9999-12-31 00:00:00", slides, cid))
    return cid


def row(cid):
    return one("SELECT * FROM carousels WHERE id=?", (cid,))


def caption_of(cid):
    return workflow._caption(workflow.load_carousel(cid))


# ---------------------------------------------------------------- happy paths
def test_single_image_publish(graph):
    cid = post(1)
    graph.caption = caption_of(cid)
    res = workflow.publish(cid)
    r = row(cid)
    assert res["success"] and r["status"] == "PUBLISHED" and r["publish_stage"] == "PUBLISHED"
    assert r["ig_container_id"].startswith("S") and r["ig_media_id"].startswith("M") and r["permalink"]
    assert r["publish_attempt_at"].endswith("Z")  # new timestamps are UTC
    assert not any(c[2].get("is_carousel_item") for c in graph.calls)


def test_carousel_publish_checks_every_child_then_parent(graph):
    cid = post(3)
    res = workflow.publish(cid)
    r = row(cid)
    assert res["success"] and r["status"] == "PUBLISHED"
    children = json.loads(r["ig_children_json"])
    assert len(children) == 3 and r["ig_container_id"].startswith("P")
    polled = [c[1] for c in graph.calls if c[2].get("fields") == "status_code,status"]
    assert set(children) <= set(polled) and r["ig_container_id"] in polled
    assert len(graph.publish_calls()) == 1


def test_processing_delay_is_waited_out(graph):
    cid = post(2)
    graph.status["P3"] = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    assert workflow.publish(cid)["success"]


# ---------------------------------------------------------------- failures keep Meta's details
def test_child_container_failure_keeps_meta_error(graph):
    cid = post(3)
    graph.child_fail_at = 2
    res = workflow.publish(cid)
    r = row(cid)
    assert not res["success"] and r["status"] == "PUBLISH_FAILED" and r["publish_stage"] == "UPLOADING"
    e = json.loads(r["publish_error_json"])
    assert e["code"] == 9004 and e["subcode"] == 2207052 and e["fbtrace_id"] == "TRACE1" and e["http_status"] == 400 and e["slide"] == 2
    assert "Slide 2" in r["error_message"] and "public HTTPS JPEG" in r["error_message"] and "fbtrace TRACE1" in r["error_message"]
    assert graph.publish_calls() == []


def test_parent_container_failure(graph):
    cid = post(2)
    graph.parent_fail = meta_err(100, "Invalid parameter", 2207028)
    res = workflow.publish(cid)
    r = row(cid)
    assert not res["success"] and r["status"] == "PUBLISH_FAILED" and r["publish_stage"] == "PROCESSING"
    assert json.loads(r["publish_error_json"])["code"] == 100 and graph.publish_calls() == []


def test_expired_token(graph):
    cid = post(2)
    graph.account = meta_err(190, "Error validating access token: Session has expired", 463)
    res = workflow.publish(cid)
    r = row(cid)
    assert not res["success"] and r["status"] == "PUBLISH_FAILED" and r["publish_stage"] == "VALIDATING"
    assert "expired" in r["error_message"] and "Renew it in Settings" in r["error_message"]


def test_missing_publish_permission(graph):
    cid = post(2)
    graph.scopes = ["instagram_basic"]
    res = workflow.publish(cid)
    assert not res["success"] and "instagram_content_publish" in row(cid)["error_message"]
    assert not any(c[1] == "IG/media" for c in graph.calls)


def test_permission_error_from_meta_is_explained(graph):
    cid = post(1)
    graph.single_fail = meta_err(10, "Application does not have permission for this action")
    workflow.publish(cid)
    assert "missing a permission" in row(cid)["error_message"]


def test_invalid_image_url_stops_before_meta(graph):
    cid = post(2)
    graph.bad_images[SLIDE.format(2)] = Resp(404, {}, "text/html")
    res = workflow.publish(cid)
    r = row(cid)
    assert not res["success"] and "Slide 2" in r["error_message"] and "HTTP 404" in r["error_message"]
    assert not any(c[1] == "IG/media" for c in graph.calls)


def test_non_jpeg_and_non_https_images_rejected():
    assert mgc.check_image_url("http://cdn.example/x.jpg")[0] is False


def test_wrong_content_type_rejected(graph):
    cid = post(1)
    graph.bad_images[SLIDE.format(1)] = Resp(200, {}, "image/png")
    workflow.publish(cid)
    assert "image/jpeg" in row(cid)["error_message"]


def test_processing_timeout(graph):
    cid = post(2)
    graph.status["P3"] = ["IN_PROGRESS"]
    res = workflow.publish(cid)
    r = row(cid)
    assert not res["success"] and r["status"] == "PUBLISH_FAILED" and "still processing" in r["error_message"]
    assert graph.publish_calls() == []


def test_container_error_status(graph):
    cid = post(2)
    graph.status["C1"] = ["ERROR"]
    workflow.publish(cid)
    assert "could not process" in row(cid)["error_message"]


# ---------------------------------------------------------------- uncertain media_publish: reconcile, never blind-retry
def test_publish_timeout_but_live_is_marked_published(graph):
    cid = post(2)
    graph.publish_mode = "timeout_published"
    graph.caption = caption_of(cid)
    res = workflow.publish(cid)
    r = row(cid)
    assert res["success"] and r["status"] == "PUBLISHED" and r["ig_media_id"].startswith("M")
    assert len(graph.publish_calls()) == 1


def test_publish_timeout_not_live_allows_safe_retry(graph):
    cid = post(2)
    graph.publish_mode = "timeout_not_published"
    res = workflow.publish(cid)
    assert not res["success"] and row(cid)["status"] == "PUBLISH_FAILED" and "NOT published" in row(cid)["error_message"]
    graph.publish_mode = "ok"
    assert workflow.publish(cid)["success"] and row(cid)["status"] == "PUBLISHED"


def test_retry_after_failure_never_republishes_a_live_post(graph):
    """Earlier attempt went live but the app recorded a failure: the retry must detect it, not post twice."""
    cid = post(2)
    graph.caption = caption_of(cid)
    assert workflow.publish(cid)["success"]
    parent = row(cid)["ig_container_id"]
    update("UPDATE carousels SET status='PUBLISH_FAILED', ig_media_id='' WHERE id=?", (cid,))  # simulate the lost response
    res = workflow.publish(cid)
    assert res["success"] and row(cid)["status"] == "PUBLISHED" and len(graph.publish_calls()) == 1
    assert row(cid)["ig_container_id"] == parent


def test_definite_publish_error(graph):
    cid = post(2)
    graph.publish_mode = "error"
    workflow.publish(cid)
    r = row(cid)
    assert r["status"] == "PUBLISH_FAILED" and r["publish_stage"] == "PUBLISHING" and "9007" in r["error_message"]


# ---------------------------------------------------------------- duplicates and concurrency
def test_duplicate_button_clicks(graph):
    cid = post(2)
    assert workflow.publish(cid)["success"]
    again = workflow.publish(cid)
    assert not again["success"] and len(graph.publish_calls()) == 1
    assert client.post(f"/api/carousels/{cid}/publish", json={"confirm": True}).status_code == 400  # API refuses too


def test_concurrent_publishing_attempts(graph):
    cid = post(2)
    graph.publish_delay = 0.2
    results = []
    threads = [threading.Thread(target=lambda: results.append(workflow.publish(cid))) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(1 for r in results if r["success"]) == 1
    assert sum(1 for r in results if r.get("duplicate")) == 5
    assert len(graph.publish_calls()) == 1 and row(cid)["status"] == "PUBLISHED"


def test_claim_is_atomic_at_db_level():
    cid = post(1)
    sql = "UPDATE carousels SET status='PUBLISHING' WHERE id=? AND status IN ('PENDING_APPROVAL','PUBLISH_FAILED')"
    assert update(sql, (cid,)) == 1 and update(sql, (cid,)) == 0


# ---------------------------------------------------------------- recovery of stuck PUBLISHING posts
def _stuck(cid, container="", minutes=30):
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    update("UPDATE carousels SET status='PUBLISHING', publish_stage='PUBLISHING', publish_attempt_at=?, ig_container_id=? WHERE id=?",
           (at, container, cid))


def test_stuck_before_container_is_failed_safely(graph):
    cid = post(2)
    _stuck(cid)
    out = workflow.recover_stuck_publishing()
    assert {"id": cid, "result": "failed_safe_to_retry"} in out and row(cid)["status"] == "PUBLISH_FAILED"


def test_stuck_but_live_is_reconciled_to_published(graph):
    cid = post(2)
    graph.caption = caption_of(cid)
    graph.published["P99"] = "M777"
    _stuck(cid, "P99")
    workflow.recover_stuck_publishing()
    assert row(cid)["status"] == "PUBLISHED" and row(cid)["ig_media_id"] == "M777"


def test_stuck_not_live_becomes_retryable_then_publishes(graph):
    cid = post(2)
    graph.status["P98"] = ["FINISHED"]
    _stuck(cid, "P98")
    r = client.post(f"/api/carousels/{cid}/reconcile").json()
    assert r["results"][0]["result"] == "failed_safe_to_retry" and row(cid)["status"] == "PUBLISH_FAILED"
    assert workflow.publish(cid)["success"]


def test_stuck_post_with_media_id_is_published_without_meta_call(graph):
    cid = post(2)
    _stuck(cid)
    update("UPDATE carousels SET ig_media_id='M555' WHERE id=?", (cid,))
    workflow.recover_stuck_publishing(cid)
    assert row(cid)["status"] == "PUBLISHED" and row(cid)["ig_media_id"] == "M555"
    assert not any(c[2].get("fields") == "status_code,status" for c in graph.calls)


def test_recent_publishing_is_left_alone(graph):
    cid = post(2)
    _stuck(cid, "P97", minutes=1)  # may still be running in another function
    assert workflow.recover_stuck_publishing() == [] and row(cid)["status"] == "PUBLISHING"
    assert workflow.publish(cid).get("duplicate")


def test_unreachable_meta_leaves_stuck_post_untouched(graph, monkeypatch):
    cid = post(2)
    _stuck(cid, "P96")
    monkeypatch.setattr(workflow.meta, "container_status", lambda c: {"ok": False, "error": {"message": "down", "uncertain": True, "http_status": 0}})
    out = workflow.recover_stuck_publishing(cid)
    assert out[0]["result"] == "still_publishing" and row(cid)["status"] == "PUBLISHING"


def test_stale_running_jobs_are_failed():
    from store import recover_stale_jobs, ts
    jid = execute("INSERT INTO jobs (kind, status, started_at) VALUES ('publish','RUNNING','2000-01-01 00:00:00')")
    fresh = execute("INSERT INTO jobs (kind, status, started_at) VALUES ('publish','RUNNING',?)", (ts(),))
    recover_stale_jobs(15)
    assert one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "FAILED"
    assert one("SELECT status FROM jobs WHERE id=?", (fresh,))["status"] == "RUNNING"
    update("UPDATE jobs SET status='FAILED' WHERE id=?", (fresh,))


# ---------------------------------------------------------------- secrets never leak into errors
def test_token_is_scrubbed_from_network_errors(graph, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("Max retries exceeded with url: /v22.0/IG/media?access_token=SECRET_TOKEN_123&image_url=x")
    monkeypatch.setattr(mgc.requests, "request", boom)
    r = workflow.meta.request("POST", "IG/media", image_url="x")
    assert "SECRET_TOKEN_123" not in json.dumps(r) and r["error"]["uncertain"]
