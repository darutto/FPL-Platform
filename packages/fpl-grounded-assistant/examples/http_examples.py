"""
FPL Grounded Assistant — HTTP integration examples.
====================================================
Phase 4d: external integration examples and client fixtures.

Shows how to call ``POST /ask`` and ``GET /health`` for each supported scenario.
Uses FastAPI ``TestClient`` for in-process execution — no running server needed.

To call a live server instead, replace ``make_client()`` / ``TestClient`` with
``requests.Session`` pointed at your server URL::

    import requests
    session = requests.Session()
    resp = session.post("http://localhost:8000/ask",
                        json={"question": "should I captain Haaland"})
    body = resp.json()

Scenarios covered
-----------------
supported_ok               -- captain score for a known player
supported_ambiguous        -- player name matches multiple entries
supported_not_found        -- supported intent, player not in registry
supported_missing_arguments -- ranking intent without candidates_list
unsupported_intent         -- question outside the supported intent set
malformed_request          -- missing required 'question' field → HTTP 422
service_not_ready          -- bootstrap not initialised → HTTP 503

Key HTTP status contract
-------------------------
- HTTP 200  -- request was processed (inspect ``supported`` / ``outcome`` in body)
- HTTP 422  -- malformed request (missing or invalid ``question`` field)
- HTTP 503  -- service not ready (bootstrap not yet initialised)

Domain outcomes are always carried in the JSON body, never in the HTTP status.

Run directly::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python examples/http_examples.py

Or import from a test runner::

    from examples.http_examples import HTTP_SCENARIOS, HTTP_EDGE_CASES, run_http_scenario
"""
from __future__ import annotations

from typing import Any

import fpl_server
from fastapi.testclient import TestClient
from fpl_grounded_assistant import STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP


# ---------------------------------------------------------------------------
# Client factory helpers
# ---------------------------------------------------------------------------

def make_client(bootstrap: dict[str, Any]) -> TestClient:
    """Return a TestClient with *bootstrap* pre-injected.

    Injects the bootstrap before creating the TestClient so the lifespan
    ``if _bootstrap is None`` guard skips the live ``assemble_captain_context()``
    fetch.

    In production, replace with ``requests.Session`` pointed at your server URL.
    """
    fpl_server._init_bootstrap(bootstrap)
    return TestClient(fpl_server.app, raise_server_exceptions=True)


def make_uninitialised_client() -> TestClient:
    """Return a TestClient with the bootstrap cleared — triggers HTTP 503 on /ask.

    Used only for the ``service_not_ready`` scenario.  Call ``make_client()``
    immediately after to restore a valid state for subsequent requests.
    """
    fpl_server._bootstrap = None  # type: ignore[assignment]
    return TestClient(fpl_server.app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

HTTP_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "supported_ok",
        "payload": {"question": "should I captain Haaland"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Captain score for a known player. HTTP 200. "
            "supported=True, outcome='ok' in JSON body."
        ),
    },
    {
        "id": "supported_ambiguous",
        "payload": {"question": "who is Doe"},
        "bootstrap": AMBIGUOUS_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ambiguous",
        "note": (
            "Ambiguous player name. HTTP 200. "
            "supported=True, outcome='ambiguous' — inspect body for detail."
        ),
    },
    {
        "id": "supported_not_found",
        "payload": {"question": "should I captain xyznotaplayer999"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "not_found",
        "note": (
            "Player not found. HTTP 200. "
            "supported=True, outcome='not_found' — inspect body for detail."
        ),
    },
    {
        "id": "supported_missing_arguments",
        "payload": {"question": "top captains this week"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "missing_arguments",
        "note": (
            "Ranking intent without candidates. HTTP 200. "
            "supported=True, outcome='missing_arguments' — inspect body."
        ),
    },
    {
        "id": "unsupported_intent",
        "payload": {"question": "Is Haaland fit to play?"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": False,
        "expected_outcome": "unsupported_intent",
        "note": (
            "Out-of-scope question. HTTP 200 (transport OK). "
            "supported=False, outcome='unsupported_intent' in JSON body. "
            "Domain outcome is in the body, not the HTTP status code."
        ),
    },
]

HTTP_EDGE_CASES: list[dict[str, Any]] = [
    {
        "id": "malformed_request",
        "payload": {},  # missing required 'question' field
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 422,
        "note": (
            "Missing required 'question' field. HTTP 422 (request validation error). "
            "Use HTTP status 422 to detect malformed payloads."
        ),
    },
    {
        "id": "service_not_ready",
        "payload": {"question": "should I captain Haaland"},
        "bootstrap": None,  # uninitialised — triggers 503
        "expected_status": 503,
        "note": (
            "Bootstrap not initialised at startup. HTTP 503 (service unavailable). "
            "Should not occur in normal operation (lifespan initialises bootstrap)."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_http_scenario(scenario: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run a single HTTP scenario and return ``(status_code, json_body)``.

    Creates a fresh TestClient with the appropriate bootstrap for each call.
    For ``bootstrap=None``, clears the server state to trigger the 503 path,
    then the next ``make_client()`` call will restore a valid bootstrap.

    Parameters
    ----------
    scenario:
        One entry from ``HTTP_SCENARIOS`` or ``HTTP_EDGE_CASES``.

    Returns
    -------
    tuple[int, dict]
        HTTP status code and parsed JSON body (empty dict on parse failure).
    """
    if scenario.get("bootstrap") is None:
        client = make_uninitialised_client()
    else:
        client = make_client(scenario["bootstrap"])

    resp = client.post("/ask", json=scenario["payload"])
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("FPL HTTP Integration Examples\n")

    # Health check
    client = make_client(STANDARD_BOOTSTRAP)
    health = client.get("/health")
    print(f"GET /health → HTTP {health.status_code}  {health.json()}\n")

    # POST /ask scenarios
    print("POST /ask — domain scenarios\n")
    all_pass = True
    for s in HTTP_SCENARIOS + HTTP_EDGE_CASES:
        status, body = run_http_scenario(s)
        ok = status == s["expected_status"]
        label = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        supported = body.get("supported", "—")
        outcome   = body.get("outcome",   "—")
        print(f"[{label}] {s['id']}  HTTP {status}  (expected {s['expected_status']})")
        print(f"       {s['note']}")
        if body:
            print(f"       supported={supported}  outcome={outcome}")
        print()

    print("All scenarios passed." if all_pass else "Some scenarios FAILED.")
