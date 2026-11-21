"""Test-wide safety net: no test may reach the real network (Instagram, GitHub, image hosts).
Mocks replace requests.request / requests.get where a test needs HTTP; anything unmocked fails loudly."""
import pytest
import requests


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    def blocked(self, method, url, *a, **k):
        raise AssertionError(f"Real network call blocked in tests: {method} {str(url).split('?')[0]}")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
