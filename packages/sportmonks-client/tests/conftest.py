from __future__ import annotations

import json
from pathlib import Path

import pytest

from sportmonks_client.errors import SportmonksRequestError
from sportmonks_client.transport import TransportResponse

FIXTURES = Path(__file__).parent / "fixtures"


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
