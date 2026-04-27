"""
V2 Phase 1f — HTTP contract fixture verifier.
==============================================
Loads ``http_contract_fixtures.json`` and verifies every fixture against the
in-process FastAPI server via ``TestClient``.

Design
------
* **No new semantics** — fixtures describe what the existing server already
  does.  A fixture failure is a parity gap between the doc and the code, not a
  new behavioral requirement.
* **Fixture-driven** — all test data lives in ``http_contract_fixtures.json``
  so downstream consumers can read the same source of truth without running
  Python.
* **Self-contained** — no pytest, no network, no LLM calls needed.

Invariant assertions
--------------------
Each fixture's ``expected.body`` entry supports:

  ``value``          exact equality check for a scalar field
  ``not_value``      field must NOT equal this value
  ``presence``       "non-null" or "null" — checks that the field is/is not None
  ``required_keys``  list of keys that must all exist on a dict field

Dot-notation keys like ``"debug.classification_source"`` are resolved by
splitting on ``"."`` and walking the body dict.

Run::

    cd packages/fpl-grounded-assistant
    python run_phase_v2_http_contract_tests.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB  = lambda name: os.path.join(_PKGS, name)
for _pkg in [
    _HERE,
    _SIB("fpl-api-client"),
    _SIB("fpl-data-core"),
    _SIB("fpl-player-registry"),
    _SIB("fpl-query-tools"),
    _SIB("fpl-tool-contract"),
    _SIB("fpl-tool-runner"),
    _SIB("fpl-captain-engine"),
    _SIB("fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

import fpl_server
from fastapi.testclient import TestClient
from fpl_grounded_assistant import STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURES_PATH = os.path.join(_HERE, "http_contract_fixtures.json")

with open(_FIXTURES_PATH, encoding="utf-8") as _f:
    _FIXTURES: dict[str, Any] = json.load(_f)

ASK_FIXTURES:         list[dict[str, Any]] = _FIXTURES["ask_fixtures"]
SESSION_ASK_FIXTURES: list[dict[str, Any]] = _FIXTURES["session_ask_fixtures"]
PROBE_FIXTURES:       list[dict[str, Any]] = _FIXTURES.get("probe_fixtures", [])


# ---------------------------------------------------------------------------
# Bootstrap selection
#
# The ambiguous fixture uses AMBIGUOUS_BOOTSTRAP; everything else uses
# STANDARD_BOOTSTRAP.  This mirrors the existing http_examples.py pattern.
# ---------------------------------------------------------------------------

_AMBIGUOUS_IDS = {"ask_ambiguous"}


def _bootstrap_for(fixture: dict[str, Any]) -> dict[str, Any]:
    return AMBIGUOUS_BOOTSTRAP if fixture["id"] in _AMBIGUOUS_IDS else STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def _make_ask_client(bootstrap: dict[str, Any]) -> TestClient:
    fpl_server._init_bootstrap(bootstrap)
    return TestClient(fpl_server.app, raise_server_exceptions=True)


def _fresh_session_client() -> TestClient:
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._clear_sessions()
    return TestClient(fpl_server.app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Body traversal helper
# ---------------------------------------------------------------------------

def _get_nested(body: dict[str, Any], dotted_key: str) -> Any:
    """Resolve a dot-notation key against a response body dict.

    Returns ``_MISSING`` sentinel when the key is absent at any level.
    """
    parts = dotted_key.split(".")
    current: Any = body
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


_MISSING = object()


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _assert(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        print(f"  [PASS] {label}")
        _passed += 1
    else:
        print(f"  [FAIL] {label}{(' -- ' + detail) if detail else ''}")
        _failed += 1


def _check_body_invariants(
    fixture_id: str,
    body: dict[str, Any],
    expected_body: dict[str, Any],
) -> None:
    """Apply all invariant assertions from ``expected.body`` to a response body."""
    for key, spec in expected_body.items():
        if key == "note":
            continue
        if not isinstance(spec, dict):
            continue

        actual = _get_nested(body, key)

        if "value" in spec:
            expected_val = spec["value"]
            _assert(
                f"{fixture_id} / {key} == {expected_val!r}",
                actual == expected_val,
                f"got {actual!r}",
            )

        if "not_value" in spec:
            not_val = spec["not_value"]
            _assert(
                f"{fixture_id} / {key} != {not_val!r}",
                actual != not_val,
                f"got {actual!r}",
            )

        if "presence" in spec:
            presence = spec["presence"]
            if presence == "non-null":
                _assert(
                    f"{fixture_id} / {key} is non-null",
                    actual is not _MISSING and actual is not None,
                    f"got {actual!r}",
                )
            elif presence == "null":
                _assert(
                    f"{fixture_id} / {key} is null",
                    actual is None or actual is _MISSING,
                    f"got {actual!r}",
                )

        if "required_keys" in spec:
            if actual is _MISSING or actual is None or not isinstance(actual, dict):
                _assert(
                    f"{fixture_id} / {key} has required keys",
                    False,
                    f"field is {actual!r} (not a dict)",
                )
            else:
                missing_keys = [k for k in spec["required_keys"] if k not in actual]
                _assert(
                    f"{fixture_id} / {key} has all required keys",
                    len(missing_keys) == 0,
                    f"missing keys: {missing_keys!r}",
                )


# ---------------------------------------------------------------------------
# Section A — POST /ask fixtures
# ---------------------------------------------------------------------------

print("\n=== Section A: POST /ask fixtures ===\n")

for fixture in ASK_FIXTURES:
    fid = fixture["id"]
    request_body = fixture["request"]
    expected = fixture["expected"]
    expected_status = expected["http_status"]

    bootstrap = _bootstrap_for(fixture)
    client = _make_ask_client(bootstrap)

    # For the service_not_ready fixture (if present) we would clear bootstrap,
    # but that fixture is in HTTP_EDGE_CASES, not here.
    resp = client.post("/ask", json=request_body)
    _assert(
        f"{fid} / HTTP {expected_status}",
        resp.status_code == expected_status,
        f"got HTTP {resp.status_code}",
    )

    if expected_status == 200 and "body" in expected:
        try:
            body = resp.json()
        except Exception:
            body = {}
        _check_body_invariants(fid, body, expected["body"])


# ---------------------------------------------------------------------------
# Section B — POST /session/{id}/ask fixtures
# ---------------------------------------------------------------------------

print("\n=== Section B: POST /session/{id}/ask fixtures ===\n")

for fixture in SESSION_ASK_FIXTURES:
    fid = fixture["id"]
    request_body = fixture["request"]
    expected = fixture["expected"]
    expected_status = expected["http_status"]

    client = _fresh_session_client()

    # Precondition: session_not_found uses a fake session_id
    if fixture.get("precondition") == "session_id is not in the active session registry":
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = client.post(f"/session/{fake_id}/ask", json=request_body)
        _assert(
            f"{fid} / HTTP {expected_status}",
            resp.status_code == expected_status,
            f"got HTTP {resp.status_code}",
        )
        continue

    # Create a real session
    create_resp = client.post("/session")
    _assert(f"{fid} / session created", create_resp.status_code == 200,
            f"got {create_resp.status_code}")
    if create_resp.status_code != 200:
        continue
    session_id = create_resp.json()["session_id"]

    # Run any setup turns first
    for setup_turn in fixture.get("setup_turns", []):
        client.post(f"/session/{session_id}/ask", json=setup_turn)

    # Run the fixture turn
    resp = client.post(f"/session/{session_id}/ask", json=request_body)
    _assert(
        f"{fid} / HTTP {expected_status}",
        resp.status_code == expected_status,
        f"got HTTP {resp.status_code}",
    )

    if expected_status == 200 and "body" in expected:
        try:
            body = resp.json()
        except Exception:
            body = {}
        _check_body_invariants(fid, body, expected["body"])


# ---------------------------------------------------------------------------
# Section C — JSON fixture structural integrity
# ---------------------------------------------------------------------------

print("\n=== Section C: fixture structural integrity ===\n")

# Confirm fixture file can be loaded and has expected top-level keys
_assert("fixtures file has _meta", "_meta" in _FIXTURES)
_assert("fixtures file has ask_fixtures", "ask_fixtures" in _FIXTURES)
_assert("fixtures file has session_ask_fixtures", "session_ask_fixtures" in _FIXTURES)
_assert("fixtures file has http_status_contract", "http_status_contract" in _FIXTURES)

meta = _FIXTURES.get("_meta", {})
_assert("_meta has intent_hint_contract", "intent_hint_contract" in meta)
hint_contract = meta.get("intent_hint_contract", {})
_assert("intent_hint allowlist has 7 values",
        len(hint_contract.get("allowlist", [])) == 7,
        str(hint_contract.get("allowlist")))
_assert("intent_hint_contract has 7 invariants",
        len(hint_contract.get("invariants", [])) == 7,
        str(len(hint_contract.get("invariants", []))))

# All ask fixtures have required keys
for fx in ASK_FIXTURES:
    for key in ("id", "request", "expected"):
        _assert(f"ask_fixtures/{fx.get('id','?')} has '{key}'", key in fx)

# All session ask fixtures have required keys
for fx in SESSION_ASK_FIXTURES:
    for key in ("id", "request", "expected"):
        _assert(f"session_ask_fixtures/{fx.get('id','?')} has '{key}'", key in fx)

# intent_hint fixtures are present in both surfaces
ask_ids = {fx["id"] for fx in ASK_FIXTURES}
session_ids = {fx["id"] for fx in SESSION_ASK_FIXTURES}

_assert("ask: intent_hint_valid present", "ask_intent_hint_valid" in ask_ids)
_assert("ask: intent_hint_deterministic_wins present", "ask_intent_hint_deterministic_wins" in ask_ids)
_assert("ask: intent_hint_invalid_safe present", "ask_intent_hint_invalid_safe" in ask_ids)
_assert("session: intent_hint_valid present", "session_ask_intent_hint_valid" in session_ids)
_assert("session: per-turn isolation present", "session_ask_intent_hint_per_turn_isolation" in session_ids)

# Probe fixtures structural checks
_assert("fixtures file has probe_fixtures", "probe_fixtures" in _FIXTURES)
probe_ids = {fx["id"] for fx in PROBE_FIXTURES}
for key in ("id", "method", "path", "precondition", "expected"):
    for fx in PROBE_FIXTURES:
        _assert(f"probe/{fx.get('id','?')} has '{key}'", key in fx)
_assert("probe: health liveness (loaded) present",     "health_liveness_bootstrap_loaded"     in probe_ids)
_assert("probe: health liveness (not loaded) present", "health_liveness_bootstrap_not_loaded" in probe_ids)
_assert("probe: ready (loaded) present",               "ready_bootstrap_loaded"               in probe_ids)
_assert("probe: ready (not loaded) present",           "ready_bootstrap_not_loaded"           in probe_ids)

# http_status_contract covers the 503 readiness semantics
status_contract = _FIXTURES.get("http_status_contract", {})
_assert("http_status_contract documents 503 readiness semantics",
        "503" in status_contract and "/ready" in status_contract.get("503", ""))


# ---------------------------------------------------------------------------
# Section D — probe fixtures (GET /health and GET /ready)
# ---------------------------------------------------------------------------

print("\n=== Section D: probe fixtures (GET /health and GET /ready) ===\n")

for fixture in PROBE_FIXTURES:
    fid        = fixture["id"]
    path       = fixture["path"]
    precond    = fixture.get("precondition", "bootstrap_loaded")
    expected   = fixture["expected"]
    exp_status = expected["http_status"]

    # Always pre-load bootstrap before creating the TestClient.
    # The lifespan guard (if _bootstrap is None: ...) then skips the live
    # assemble_captain_context() call.  For bootstrap_not_loaded fixtures we
    # clear the module-level variable INSIDE the context — after the lifespan
    # has already fired — to test endpoint runtime behavior without triggering
    # the retry loop.
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)

    with TestClient(fpl_server.app, raise_server_exceptions=False) as probe_client:
        if precond == "bootstrap_not_loaded":
            fpl_server._bootstrap = None   # type: ignore[assignment]
        resp = probe_client.get(path)

    _assert(
        f"{fid} / HTTP {exp_status}",
        resp.status_code == exp_status,
        f"got HTTP {resp.status_code}",
    )

    if exp_status == 200 and "body" in expected:
        try:
            body = resp.json()
        except Exception:
            body = {}
        _check_body_invariants(fid, body, expected["body"])

# Restore clean state after probe section
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*55}")
total = _passed + _failed
print(f"V2 Phase 1f HTTP contract: {_passed}/{total} passed")
if _failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All fixture verification checks passed.")
