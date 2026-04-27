"""
run_phase_v2_container_startup_tests.py
========================================
V2 container startup slice: classifier client initialization safety.

Proves that ``_try_init_classifier_from_env()`` (called from the lifespan)
correctly wires or omits ``_classifier_client`` depending on environment
state, and that every failure path falls back to deterministic routing.

Sections
--------
A  _try_init_classifier_from_env — no env var --> stays None               (2)
B  _try_init_classifier_from_env — env var set, package absent --> None    (2)
C  _try_init_classifier_from_env — env var + mock package --> client built  (3)
D  _try_init_classifier_from_env — construction error --> None              (2)
E  Lifespan guard — pre-injected stub is NOT overwritten                   (3)
F  Cold-start /ask smoke — no key --> deterministic routing, status 200     (3)
G  Cold-start /ask smoke — mock client wired --> classifier used             (3)
"""
from __future__ import annotations

import os
import sys
import types
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

from fastapi.testclient import TestClient
import fpl_server
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

BS = STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def check(cond: bool, label: str) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        print(f"  FAIL: {label}")


def section(name: str) -> None:
    print(f"\n{name}")


def _reset() -> None:
    """Reset server state between test sections."""
    fpl_server._init_classifier_client(None)
    fpl_server._init_bootstrap(BS)
    fpl_server._clear_sessions()


def _remove_env_key() -> None:
    os.environ.pop("ANTHROPIC_API_KEY", None)


def _set_env_key(value: str = "test-key-xyz") -> None:
    os.environ["ANTHROPIC_API_KEY"] = value


def _clear_all_provider_keys() -> None:
    """Remove every LLM provider API key so no path silently builds a client."""
    for _k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(_k, None)


def _set_provider(name: str) -> "str | None":
    """Set DEFAULT_PROVIDER; returns previous value for restore."""
    prev = os.environ.get("DEFAULT_PROVIDER")
    os.environ["DEFAULT_PROVIDER"] = name
    return prev


def _restore_provider(prev: "str | None") -> None:
    if prev is None:
        os.environ.pop("DEFAULT_PROVIDER", None)
    else:
        os.environ["DEFAULT_PROVIDER"] = prev


def _remove_mock_anthropic() -> None:
    sys.modules.pop("anthropic", None)


def _install_mock_anthropic(raise_on_construct: bool = False) -> type:
    """Inject a minimal fake ``anthropic`` module into sys.modules.

    Returns the mock client class so callers can isinstance-check.
    Replaces any real anthropic package for the duration of the test.
    """

    class _MockMessages:
        def create(self, **kwargs: Any) -> Any:
            class _Block:
                text = (
                    '{"intent": "captain_score", '
                    '"canonical_question": "should I captain Salah", '
                    '"confidence": 0.95, "language": "en"}'
                )
            class _Msg:
                content = [_Block()]
            return _Msg()

    class _MockAnthropicClient:
        def __init__(self, api_key: str | None = None) -> None:
            if raise_on_construct:
                raise RuntimeError("simulated construction failure")
            self.api_key = api_key
            self.messages = _MockMessages()

    mock_module = types.ModuleType("anthropic")
    mock_module.Anthropic = _MockAnthropicClient  # type: ignore[attr-defined]
    sys.modules["anthropic"] = mock_module
    return _MockAnthropicClient


# ---------------------------------------------------------------------------
# Section A — no env var --> _classifier_client stays None (2)
# ---------------------------------------------------------------------------

# DEFAULT_PROVIDER defaults to "gemini"; this section proves that with no key
# for ANY provider the classifier slot stays None.
section("A -- no provider key set --> _classifier_client stays None")

_reset()
_clear_all_provider_keys()
os.environ.pop("DEFAULT_PROVIDER", None)  # ensure "gemini" default path
_remove_mock_anthropic()

fpl_server._try_init_classifier_from_env()

check(
    fpl_server._classifier_client is None,
    "A1: no env var --> _classifier_client is None after _try_init_classifier_from_env()",
)

# Calling it again is idempotent
fpl_server._try_init_classifier_from_env()
check(
    fpl_server._classifier_client is None,
    "A2: repeated call with no env var stays None",
)

_reset()


# ---------------------------------------------------------------------------
# Section B — env var set but anthropic package absent --> None (2)
# ---------------------------------------------------------------------------

# Force DEFAULT_PROVIDER=anthropic so this section actually exercises the
# Anthropic import path, not the Gemini default.
section("B -- DEFAULT_PROVIDER=anthropic, package absent --> _classifier_client stays None")

_reset()
_clear_all_provider_keys()
_remove_mock_anthropic()          # ensure no mock in sys.modules
_set_env_key("sk-ant-test-abc")   # set ANTHROPIC_API_KEY
_prev_prov_b = _set_provider("anthropic")

# anthropic may or may not be installed in this environment.
_anthropic_is_installed = "anthropic" in sys.modules or __import__("importlib").util.find_spec("anthropic") is not None

if not _anthropic_is_installed:
    fpl_server._try_init_classifier_from_env()
    check(
        fpl_server._classifier_client is None,
        "B1: anthropic key set, package absent --> _classifier_client is None",
    )
    check(
        True,
        "B2: _try_init_classifier_from_env() did not raise with package absent",
    )
else:
    # anthropic IS installed: the success path is covered by section C with a mock.
    # Here we still verify no crash; client will be built (skip None check).
    try:
        fpl_server._try_init_classifier_from_env()
        check(True, "B1: skipped (anthropic installed) — success path in C")
        check(True, "B2: _try_init_classifier_from_env() did not raise")
    except Exception:
        check(False, "B1: unexpected exception with anthropic installed")
        check(False, "B2: unexpected exception with anthropic installed")

_restore_provider(_prev_prov_b)
_clear_all_provider_keys()
_reset()


# ---------------------------------------------------------------------------
# Section C — env var + mock package --> client is built (3)
# ---------------------------------------------------------------------------

# DEFAULT_PROVIDER=anthropic so the function takes the Anthropic branch,
# finds the mock module, and builds the mock client.
section("C -- DEFAULT_PROVIDER=anthropic, env var + mock package --> client built")

_reset()
_prev_prov_c = _set_provider("anthropic")
MockClient = _install_mock_anthropic()
_set_env_key("sk-ant-mock-key")

try:
    fpl_server._try_init_classifier_from_env()

    check(
        fpl_server._classifier_client is not None,
        "C1: anthropic key + mock package --> _classifier_client is not None",
    )
    check(
        isinstance(fpl_server._classifier_client, MockClient),
        "C2: built client is the expected mock Anthropic instance",
    )
    # Guard against None to prevent crash if C1 failed
    check(
        fpl_server._classifier_client is not None
        and fpl_server._classifier_client.api_key == "sk-ant-mock-key",  # type: ignore[union-attr]
        "C3: built client carries the API key",
    )
finally:
    _restore_provider(_prev_prov_c)
    _clear_all_provider_keys()
    _remove_mock_anthropic()
    _reset()


# ---------------------------------------------------------------------------
# Section D — construction error --> _classifier_client stays None (2)
# ---------------------------------------------------------------------------

# DEFAULT_PROVIDER=anthropic so the function takes the Anthropic branch
# and hits the raise-on-construct mock.
section("D -- DEFAULT_PROVIDER=anthropic, construction error --> stays None")

_reset()
_prev_prov_d = _set_provider("anthropic")
_install_mock_anthropic(raise_on_construct=True)
_set_env_key("sk-ant-bad-key")

try:
    no_raise = True
    try:
        fpl_server._try_init_classifier_from_env()
    except Exception:
        no_raise = False

    check(no_raise, "D1: construction error does not propagate from _try_init_classifier_from_env()")
    check(
        fpl_server._classifier_client is None,
        "D2: construction error --> _classifier_client stays None (deterministic fallback)",
    )
finally:
    _restore_provider(_prev_prov_d)
    _clear_all_provider_keys()
    _remove_mock_anthropic()
    _reset()


# ---------------------------------------------------------------------------
# Section E — lifespan guard: pre-injected stub is NOT overwritten (3)
# ---------------------------------------------------------------------------

section("E -- lifespan guard: pre-injected stub survives lifespan")


class _StubBlock:
    def __init__(self, t: str) -> None:
        self.text = t


class _StubMessages:
    def create(self, **kwargs: Any) -> Any:
        class _Msg:
            content = [_StubBlock(
                '{"intent": "captain_score", '
                '"canonical_question": "should I captain Salah", '
                '"confidence": 0.95, "language": "en"}'
            )]
        return _Msg()


class _StubClient:
    def __init__(self) -> None:
        self.messages = _StubMessages()


stub_e = _StubClient()

# Pre-inject the stub BEFORE calling _try_init_classifier_from_env
fpl_server._init_bootstrap(BS)
fpl_server._init_classifier_client(stub_e)
_install_mock_anthropic()
_set_env_key("sk-ant-should-not-be-used")

# Simulate what the lifespan does (the real guard is: if _classifier_client is None)
if fpl_server._classifier_client is None:
    fpl_server._try_init_classifier_from_env()

check(
    fpl_server._classifier_client is stub_e,
    "E1: pre-injected stub is not overwritten when lifespan guard fires",
)
check(
    fpl_server._classifier_client is not None,
    "E2: classifier_client is not None after pre-injection + guard",
)

# Confirm that if we DO call it directly it would replace (guard is caller's responsibility).
# DEFAULT_PROVIDER=anthropic ensures the Anthropic mock branch is taken and
# a client is actually built — not the Gemini path which may have no key.
_prev_prov_e3 = _set_provider("anthropic")
fpl_server._init_classifier_client(None)
fpl_server._try_init_classifier_from_env()
_restore_provider(_prev_prov_e3)
check(
    fpl_server._classifier_client is not None,
    "E3: _try_init_classifier_from_env() builds client when slot is explicitly cleared",
)

_clear_all_provider_keys()
_remove_mock_anthropic()
_reset()


# ---------------------------------------------------------------------------
# Section F — cold-start /ask, no key --> deterministic routing, 200 (3)
# ---------------------------------------------------------------------------

# Clear ALL provider keys so no provider path silently builds a classifier;
# deterministic routing is the guaranteed fallback when no classifier is wired.
section("F -- cold-start /ask, no provider key --> deterministic routing")

_reset()
_clear_all_provider_keys()
os.environ.pop("DEFAULT_PROVIDER", None)
_remove_mock_anthropic()

# Trigger the lifespan via context-manager form
fpl_server._init_bootstrap(BS)   # skip live fetch
with TestClient(fpl_server.app, raise_server_exceptions=True) as client_f:
    resp_f = client_f.post("/ask", json={"question": "should I captain Salah"})

body_f: dict = {}
try:
    body_f = resp_f.json()
except Exception:
    pass

check(resp_f.status_code == 200, "F1: cold-start /ask returns 200")
check(body_f.get("intent") == "captain_score", "F2: cold-start deterministic route: captain_score")
check(body_f.get("outcome") == "ok", "F3: cold-start deterministic outcome: ok")

_reset()


# ---------------------------------------------------------------------------
# Section G — cold-start /ask, mock client wired --> classifier used (3)
# ---------------------------------------------------------------------------

# DEFAULT_PROVIDER=anthropic ensures the lifespan's _try_init_classifier_from_env()
# takes the Anthropic branch, finds the mock module, and builds the mock client.
section("G -- cold-start /ask, DEFAULT_PROVIDER=anthropic + mock --> classifier fires")

_reset()
_clear_all_provider_keys()
_remove_mock_anthropic()
_prev_prov_g = _set_provider("anthropic")
MockClientG = _install_mock_anthropic()
_set_env_key("sk-ant-mock-g")

fpl_server._init_bootstrap(BS)
# Reset classifier so the lifespan guard will call _try_init_classifier_from_env
fpl_server._init_classifier_client(None)

try:
    with TestClient(fpl_server.app, raise_server_exceptions=True) as client_g:
        resp_g = client_g.post(
            "/ask",
            json={"question": "is Saka worth captaining?", "debug": True},
        )

    body_g: dict = {}
    try:
        body_g = resp_g.json()
    except Exception:
        pass

    check(resp_g.status_code == 200, "G1: mock-client cold-start /ask returns 200")
    check(body_g.get("intent") == "captain_score", "G2: mock classifier routes natural phrasing -> captain_score")
    debug_g = body_g.get("debug") or {}
    check(
        debug_g.get("classification_source") == "llm_classifier",
        "G3: debug.classification_source == 'llm_classifier' when mock classifier fired",
    )
finally:
    _restore_provider(_prev_prov_g)
    _clear_all_provider_keys()
    _remove_mock_anthropic()
    _reset()


# ---------------------------------------------------------------------------
# Section H — /ready vs /health probe semantics (4)
# ---------------------------------------------------------------------------
# /health is liveness-only: always 200 while the process runs.
# /ready is readiness: 503 until bootstrap is loaded, then 200.
# The Docker HEALTHCHECK must target /ready so the container is only marked
# healthy after data is available, not merely after the process binds.
# ---------------------------------------------------------------------------

section("H -- /ready vs /health probe semantics")

fpl_server._init_bootstrap(BS)   # bootstrap loaded
with TestClient(fpl_server.app, raise_server_exceptions=False) as client_h:
    check(
        client_h.get("/health").status_code == 200,
        "H1: /health returns 200 when bootstrap loaded",
    )
    check(
        client_h.get("/ready").status_code == 200,
        "H2: /ready returns 200 when bootstrap loaded",
    )
    check(
        client_h.get("/ready").json() == {"status": "ready"},
        "H3: /ready body is {status: ready}",
    )

    # Clear bootstrap to simulate the "bootstrap not yet fetched" window
    fpl_server._bootstrap = None  # type: ignore[assignment]
    check(
        client_h.get("/health").status_code == 200,
        "H4: /health still 200 when bootstrap not loaded (liveness-only)",
    )
    check(
        client_h.get("/ready").status_code == 503,
        "H5: /ready returns 503 when bootstrap not loaded (readiness gate)",
    )

_reset()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"V2 container startup: {_PASS}/{total} PASS")
if _FAIL:
    print(f"                      {_FAIL} FAIL")
    sys.exit(1)
else:
    print("                      All assertions passed.")
    sys.exit(0)
