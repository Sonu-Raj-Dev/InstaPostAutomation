"""Phase 7: read-only Meta configuration audit. Graph API faked; asserts only GET is used and no token leaks."""
import json

import pytest

import test_app as base
import meta_audit
from store import get_settings, set_setting

client = base.client
USER_TOKEN, PAGE_TOKEN = "EAAuser_SECRET_123", "EAApage_SECRET_456"


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b, self.text = status, body, json.dumps(body)

    def json(self):
        return self._b


class FakeMeta:
    def __init__(self, token_type="USER", scopes=None, fields=("comments",), page_subscribed=False):
        self.methods, self.token_type = [], token_type
        self.scopes = scopes if scopes is not None else ["instagram_basic", "instagram_content_publish", "pages_show_list", "instagram_manage_comments"]
        self.fields, self.page_subscribed = fields, page_subscribed

    def __call__(self, method, url, params=None, timeout=None, **kw):
        self.methods.append(method)
        path = url.split("/v22.0/", 1)[1]
        if path == "debug_token":
            return Resp({"data": {"is_valid": True, "type": self.token_type, "app_id": "111", "application": "SONU AI LAB",
                                  "expires_at": 0, "scopes": self.scopes, "granular_scopes": [{"scope": "instagram_basic", "target_ids": ["17841"]}]}})
        ig = {"id": "17841", "username": "sonu.ai.lab", "name": "Sonu", "followers_count": 10}
        if path == "me/accounts":
            return Resp({"data": [{"id": "PAGE1", "name": "Sonu AI Lab", "access_token": PAGE_TOKEN, "instagram_business_account": ig}]})
        if path == "me":
            return Resp({"id": "PAGE1", "name": "Sonu AI Lab", "instagram_business_account": ig})
        if path == "111/subscriptions":
            return Resp({"data": [{"object": "instagram", "active": True, "callback_url": "https://app.example/api/webhooks/instagram",
                                   "fields": [{"name": f} for f in self.fields]}]})
        if path == "111":
            return Resp({"name": "SONU AI LAB", "category": "Business"})
        if path == "PAGE1/subscribed_apps":
            assert params["access_token"] == PAGE_TOKEN  # Page-level check uses the Page token
            return Resp({"data": [{"id": "111", "subscribed_fields": ["feed"]}] if self.page_subscribed else []})
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def fake(monkeypatch):
    f = FakeMeta()
    monkeypatch.setattr(meta_audit.requests, "request", f)
    monkeypatch.delenv("META_PAGE_ACCESS_TOKEN", raising=False)
    return f


def run(**kw):
    return meta_audit.run(token=USER_TOKEN, app_id="111", app_secret=kw.pop("app_secret", "appsecret"), ig_user_id="17841")


def test_user_token_audit_reports_gaps_and_never_leaks_tokens(fake):
    r = run()
    dump = json.dumps(r)
    assert USER_TOKEN not in dump and PAGE_TOKEN not in dump and "appsecret" not in dump
    assert set(fake.methods) == {"GET"}                                           # read-only
    assert r["token"]["type"] == "USER" and r["token"]["never_expires"] and r["token"]["valid"]
    assert r["page"] == {"id": "PAGE1", "name": "Sonu AI Lab"} and r["instagram"]["username"] == "sonu.ai.lab" and r["instagram"]["matches_configured_id"]
    assert "instagram_manage_messages" in r["permissions"]["missing"]
    assert r["webhook_fields"] == {"comments": True, "messages": False, "all": ["comments"]}
    assert r["page_subscribed"] is False and r["messaging"]["ok"] is False
    acts = " | ".join(r["actions"])
    assert "instagram_manage_messages" in acts and "'messages' field" in acts and "subscribed_apps" in acts and "META_PAGE_ACCESS_TOKEN" in acts
    assert "Not exposed" in r["app"]["mode"] and "Not exposed" in r["app"]["advanced_access"]   # never guessed


def test_page_token_and_complete_setup(monkeypatch):
    f = FakeMeta(token_type="PAGE", scopes=list(meta_audit.NEEDED), fields=("comments", "messages"), page_subscribed=True)
    monkeypatch.setattr(meta_audit.requests, "request", f)
    r = meta_audit.run(token=PAGE_TOKEN, app_id="111", app_secret="s", ig_user_id="17841")
    assert r["errors"] == [] and r["actions"] == [] and r["page_subscribed"] is True and r["messaging"]["node"] == "me"


def test_without_app_secret_subscriptions_are_unknown_not_assumed(fake):
    r = run(app_secret="")
    assert r["webhook_fields"]["comments"] is None and any("META_APP_SECRET" in e for e in r["errors"])


def test_configured_account_mismatch_is_flagged(fake):
    r = meta_audit.run(token=USER_TOKEN, app_id="111", app_secret="s", ig_user_id="999")
    assert any("differs" in e for e in r["errors"])


def test_audit_endpoint_feeds_webhook_health(fake, monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", USER_TOKEN)
    monkeypatch.setenv("META_APP_ID", "111"); monkeypatch.setenv("META_APP_SECRET", "appsecret"); monkeypatch.setenv("INSTAGRAM_ACCOUNT_ID", "17841")
    monkeypatch.setattr(meta_audit, "_saved_token", lambda: "")
    monkeypatch.setattr(base.webapp.meta, "reload", lambda: None)
    r = client.post("/api/meta/audit").json()
    assert r["webhook_fields"]["comments"] is True and USER_TOKEN not in get_settings()["meta_audit_json"]
    sub = client.get("/api/automation/overview").json()["webhook"]["subscription"]
    assert sub["comments"] is True and sub["messages"] is False and sub["page_subscribed"] is False and sub["checked_at"]
    assert client.get("/api/meta/audit").json()["checked_at"] == r["checked_at"]


def test_failed_checks_are_unknown_not_negative(monkeypatch):
    f = FakeMeta()
    real = f.__call__

    def flaky(method, url, params=None, timeout=None, **kw):
        if url.endswith("/debug_token"):
            raise meta_audit.requests.exceptions.SSLError("certificate verify failed: self-signed certificate")
        if url.endswith("PAGE1/subscribed_apps"):
            return Resp({"error": {"code": 200, "message": "(#200) Requires pages_manage_metadata permission to manage the object"}}, 400)
        return real(method, url, params, timeout)
    monkeypatch.setattr(meta_audit.requests, "request", flaky)
    r = run()
    assert any(e.startswith("Couldn't check the token") for e in r["errors"]) and not any("not valid" in e for e in r["errors"])
    assert r["page_subscribed"] is None and any("pages_manage_metadata" in a for a in r["actions"])
