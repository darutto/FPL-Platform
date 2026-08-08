from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
import requests.adapters

from sportmonks_client.errors import SportmonksRequestError
from sportmonks_client.transport import TransportResponse

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """Structural guard: FI-8 forbids any live Sportmonks call before FI-9.

    Patches every HTTP entry point this package's dependencies expose --
    `requests` is the only one (`requirements.txt`). If an HTTP client is ever
    added, its entry point joins this guard in the same change.

    This guards the *boundary*, not `RequestsTransport`. That class is a wrapper:
    `transport.py:28` is `self._session = session or requests.Session()`, with
    the call at line 34. Patching the wrapper's constructor was measured at
    18 failed / 49 passed -- it breaks the 12 legitimate constructions in
    `test_config_transport.py` (which inject MagicMock sessions and never reach
    the network), including `test_live_smoke_opt_in_without_token_fails_without_network`,
    the test that proves the very property this guard enforces. Patching here
    passes all 67 and additionally catches any call that bypasses
    `RequestsTransport` entirely.
    """
    def _refuse(*args, **kwargs):
        raise AssertionError(
            "live network call attempted in a test; FI-8 forbids any live "
            "Sportmonks call before FI-9"
        )

    monkeypatch.setattr(requests.Session, "request", _refuse)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _refuse)


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def request(self, method, url, *, params, timeout):
        self.calls.append((method, url, dict(params), timeout))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(body, status=200, headers=None):
    return TransportResponse(status, headers or {}, body)


@pytest.fixture
def endpoint_payloads(): return load_fixture("endpoint_payloads.json")


@pytest.fixture
def edge_cases(): return load_fixture("edge_cases.json")
