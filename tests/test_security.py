"""Phase 8: security checks across the new endpoints. Run: python -m pytest tests -q"""
import json

import pytest

import test_app as base
from store import set_secret, set_setting

client = base.client
TOKEN = "EAAsecretTOKENvalue0123456789abcdef"

ADMIN = [("GET", "/api/automation/overview"), ("POST", "/api/automation/run/research"), ("GET", "/api/scheduler/status"),
         ("POST", "/api/scheduler/sync"), ("GET", "/api/inbox/events"), ("POST", "/api/inbox/sweep"), ("POST", "/api/inbox/events/1/retry"),
         ("POST", "/api/meta/audit"), ("GET", "/api/meta/audit"), ("GET", "/api/deliveries/1/log"), ("POST", "/api/deliveries/1/retry"),
         ("POST", "/api/carousels/1/schedule"), ("DELETE", "/api/carousels/1/schedule"), ("POST", "/api/carousels/1/reconcile"),
         ("POST", "/api/carousels/1/publish"), ("GET", "/api/settings")]


def test_admin_endpoints_require_login(monkeypatch):
    monkeypatch.setattr(base.webapp, "APP_PASSWORD", "a-strong-password")
    for method, path in ADMIN:
        r = client.request(method, path, json={})
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without login"


def test_public_endpoints_verify_their_own_signatures(monkeypatch):
    monkeypatch.setattr(base.webapp, "APP_PASSWORD", "a-strong-password")
    monkeypatch.setenv("META_APP_SECRET", "s")
    monkeypatch.setenv("CRON_SECRET", "c")
    assert client.post("/api/webhooks/instagram", content=b"{}").status_code == 403         # Meta signature required
    assert client.post("/api/queue/webhook-event", content=b"{}").status_code == 401        # QStash signature required
    assert client.post("/api/queue/job/research", content=b"{}").status_code == 401
    assert client.get("/api/cron/maintenance").status_code == 401                           # CRON_SECRET required


def test_tokens_never_returned_by_the_api(monkeypatch):
    set_secret("meta_access_token", TOKEN)
    monkeypatch.setenv("META_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", TOKEN + "page")
    monkeypatch.setenv("QSTASH_TOKEN", "qstash_secret_token_value")
    try:
        for path in ("/api/settings", "/api/state", "/api/automation/overview", "/api/scheduler/status", "/api/inbox/events", "/api/meta/audit"):
            body = client.get(path).text
            assert TOKEN not in body and "qstash_secret_token_value" not in body, f"secret leaked by {path}"
    finally:
        set_secret("meta_access_token", "")


def test_stored_error_text_is_scrubbed():
    from meta_graph_client import _scrub
    assert _scrub(f"GET /v22.0/x?access_token={TOKEN}&fields=a") == "GET /v22.0/x?access_token=***&fields=a"
    assert TOKEN not in _scrub(f"input_token={TOKEN}&client_secret=abc")
