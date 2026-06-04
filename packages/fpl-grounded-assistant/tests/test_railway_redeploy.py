"""
tests/test_railway_redeploy.py
==============================
Unit tests for ``fpl_grounded_assistant.railway_redeploy``.

Six scenarios (H5b §9):
1. Happy path — returns deployment id string.
2. Mutation body shape — query + variables in posted JSON.
3. Auth header — Authorization: Bearer <token>.
4. HTTP 401 — raises RailwayRedeployError with "401" in message.
5. GraphQL error in 200 body — raises RailwayRedeployError.
6. CLI missing env — exits 1, stderr mentions missing var name.

Loading strategy
----------------
Uses the importlib file-loading pattern from ``test_owned_store_sync.py``
to bypass ``fpl_grounded_assistant/__init__.py``, which eagerly imports
the full dispatcher/harness graph and fails outside a fully wired
environment. The module is loaded directly from its file and registered in
``sys.modules`` so that attribute-level patching (``monkeypatch.setattr``)
works against the module object directly — bypassing ``__init__.py``
entirely.

Patching note: we patch ``requests`` on the loaded module object directly
(``monkeypatch.setattr(_mod, "requests", fake_requests)``) rather than
using the string-based ``patch("fpl_grounded_assistant.railway_redeploy.requests.post")``,
because the string form triggers a normal ``importlib.import_module`` call
that re-enters ``fpl_grounded_assistant/__init__.py`` and fails with
``ModuleNotFoundError`` on uninstalled sibling packages (same failure mode
seen in H5).
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os
import subprocess
import sys as _sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path / module loading
# ---------------------------------------------------------------------------
_HERE = _os.path.dirname(_os.path.abspath(__file__))       # tests/
_PKG  = _os.path.dirname(_HERE)                            # fpl-grounded-assistant/
_PKG_SRC = _os.path.join(_PKG, "fpl_grounded_assistant")   # fpl_grounded_assistant/

if _PKG not in _sys.path:
    _sys.path.insert(0, _PKG)

_MODULE_PATH = _os.path.join(_PKG_SRC, "railway_redeploy.py")

pytestmark = pytest.mark.skipif(
    not _os.path.exists(_MODULE_PATH),
    reason="railway_redeploy.py not yet present",
)


def _load_module(name: str, filepath: str):
    spec = _ilu.spec_from_file_location(name, filepath)
    assert spec is not None and spec.loader is not None
    mod = _ilu.module_from_spec(spec)
    _sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        _sys.modules.pop(name, None)
        raise
    return mod


if _os.path.exists(_MODULE_PATH):
    _mod = _load_module("fpl_grounded_assistant.railway_redeploy", _MODULE_PATH)
    redeploy_service = _mod.redeploy_service
    RailwayRedeployError = _mod.RailwayRedeployError
else:  # pragma: no cover — skip guard
    _mod = None
    redeploy_service = None
    RailwayRedeployError = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_MUTATION_NAME = "serviceInstanceRedeploy"

_SERVICE_ID = "svc-111"
_ENV_ID = "env-222"
_TOKEN = "tok-abc"
_DEP_ID = "dep-abc123"


def _make_ok_response(deployment_id: str = _DEP_ID) -> MagicMock:
    """Return a mock requests.Response with 200 and a happy GraphQL body."""
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {
        "data": {
            _MUTATION_NAME: {
                "latestDeployment": {"id": deployment_id}
            }
        }
    }
    return resp


def _make_error_response(status_code: int = 401) -> MagicMock:
    """Return a mock requests.Response with a non-2xx status."""
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status_code
    resp.text = f"HTTP {status_code} error"
    return resp


def _make_graphql_error_response(message: str = "service not found") -> MagicMock:
    """Return a 200 response that carries a GraphQL errors array."""
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {
        "errors": [{"message": message}]
    }
    return resp


def _fake_requests(post_return_value: MagicMock) -> MagicMock:
    """Build a fake ``requests`` module whose ``post`` is a pre-configured mock."""
    fake = MagicMock(name="requests")
    fake.post.return_value = post_return_value
    # Preserve the real exceptions so isinstance checks in the module work.
    import requests as _real_requests
    fake.exceptions = _real_requests.exceptions
    return fake


# ---------------------------------------------------------------------------
# Test 1 — Happy path
# ---------------------------------------------------------------------------
def test_happy_path_returns_deployment_id(monkeypatch):
    """redeploy_service returns the deployment id from the GraphQL response."""
    fake = _fake_requests(_make_ok_response("abc123"))
    monkeypatch.setattr(_mod, "requests", fake)

    result = redeploy_service(_SERVICE_ID, _ENV_ID, _TOKEN)

    assert result == "abc123"


# ---------------------------------------------------------------------------
# Test 2 — Mutation body shape
# ---------------------------------------------------------------------------
def test_mutation_body_shape(monkeypatch):
    """Posted JSON must have 'query' (str containing mutation name) and 'variables'."""
    fake = _fake_requests(_make_ok_response())
    monkeypatch.setattr(_mod, "requests", fake)

    redeploy_service(_SERVICE_ID, _ENV_ID, _TOKEN)

    # Extract the 'json' keyword argument from the post() call.
    call_kwargs = fake.post.call_args.kwargs
    body = call_kwargs.get("json")
    if body is None:
        # Fallback: positional args — post(url, json=...) or post(url, data=...)
        call_args = fake.post.call_args.args
        body = call_args[1] if len(call_args) > 1 else None

    assert body is not None, "Expected a JSON body to be passed to requests.post"
    assert "query" in body, "Posted JSON must contain 'query'"
    assert isinstance(body["query"], str), "'query' must be a string"
    assert _MUTATION_NAME in body["query"], (
        f"'query' must reference the mutation '{_MUTATION_NAME}'"
    )
    assert "variables" in body, "Posted JSON must contain 'variables'"
    variables = body["variables"]
    assert "serviceId" in variables, "'variables' must contain 'serviceId'"
    assert "environmentId" in variables, "'variables' must contain 'environmentId'"
    assert variables["serviceId"] == _SERVICE_ID
    assert variables["environmentId"] == _ENV_ID


# ---------------------------------------------------------------------------
# Test 3 — Auth header
# ---------------------------------------------------------------------------
def test_auth_header(monkeypatch):
    """Request must carry 'Authorization: Bearer <token>' header."""
    fake = _fake_requests(_make_ok_response())
    monkeypatch.setattr(_mod, "requests", fake)

    redeploy_service(_SERVICE_ID, _ENV_ID, _TOKEN)

    call_kwargs = fake.post.call_args.kwargs
    headers = call_kwargs.get("headers", {})
    assert "Authorization" in headers, "Missing Authorization header"
    assert headers["Authorization"] == f"Bearer {_TOKEN}", (
        f"Expected 'Bearer {_TOKEN}', got {headers['Authorization']!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — HTTP 401
# ---------------------------------------------------------------------------
def test_http_401_raises_error(monkeypatch):
    """HTTP 401 response must raise RailwayRedeployError with '401' in message."""
    fake = _fake_requests(_make_error_response(401))
    monkeypatch.setattr(_mod, "requests", fake)

    with pytest.raises(RailwayRedeployError) as exc_info:
        redeploy_service(_SERVICE_ID, _ENV_ID, _TOKEN)

    assert "401" in str(exc_info.value), (
        f"Expected '401' in error message, got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# Test 5 — GraphQL error in 200 body
# ---------------------------------------------------------------------------
def test_graphql_error_in_200_raises_error(monkeypatch):
    """200 response with 'errors' array must raise RailwayRedeployError."""
    error_msg = "service not found"
    fake = _fake_requests(_make_graphql_error_response(error_msg))
    monkeypatch.setattr(_mod, "requests", fake)

    with pytest.raises(RailwayRedeployError) as exc_info:
        redeploy_service(_SERVICE_ID, _ENV_ID, _TOKEN)

    message_lower = str(exc_info.value).lower()
    assert "service not found" in message_lower or "graphql" in message_lower, (
        f"Expected 'service not found' or 'graphql' in error, got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# Test 6 — CLI missing env var exits 1 with clear message
# ---------------------------------------------------------------------------
def test_cli_missing_env_exits_1():
    """Running railway_redeploy.py with RAILWAY_API_TOKEN absent must exit 1
    and write 'RAILWAY_API_TOKEN' to stderr."""
    env_without_token = {
        k: v for k, v in _os.environ.items()
        if k not in {"RAILWAY_API_TOKEN", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID"}
    }

    result = subprocess.run(
        [_sys.executable, _MODULE_PATH],
        env=env_without_token,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, (
        f"Expected exit code 1, got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "RAILWAY_API_TOKEN" in result.stderr, (
        f"Expected 'RAILWAY_API_TOKEN' in stderr, got: {result.stderr!r}"
    )
