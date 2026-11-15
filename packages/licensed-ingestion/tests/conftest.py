from __future__ import annotations

import pytest
import requests
import requests.adapters


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """No test reaches Sportmonks or FPL: the job's network entry points are requests' (as in sportmonks-client)."""
    def _refuse(*args, **kwargs):
        raise AssertionError("live network call attempted in a test")

    monkeypatch.setattr(requests.Session, "request", _refuse)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _refuse)
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
