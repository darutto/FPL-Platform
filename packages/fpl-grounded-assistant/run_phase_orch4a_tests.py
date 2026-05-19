"""
run_phase_orch4a_tests.py
=========================
Phase Orch-4a: Gated orchestration wiring.

POST-GRADUATION NOTE (G2.c): The Orch-4a gate inside respond() was deleted
in commit 118d43e (G2.a) as part of the mcp-graduation sprint. respond() is
now deterministic-only; FPL_ORCH_ENABLED no longer controls respond() routing.
Assertions that tested respond() routing through the orchestrator when the flag
was ON have been retired (see G2.c notes inline).

Validates that:
- orch_config module is importable and provides correct public surface.
- is_orch_enabled() reads FPL_ORCH_ENABLED env var correctly.
- get_orch_provider() reads FPL_ORCH_PROVIDER env var correctly.
- Feature flag OFF: respond() is indistinguishable from pre-Orch-4a baseline.
- Feature flag ON: non-OK orch outcomes fall back to deterministic path.
- Safe fallback for OUTCOME_NO_CLIENT, OUTCOME_LLM_ERROR, OUTCOME_NO_TOOL.
- Safe fallback for OUTCOME_TOOL_RESULT_ERROR (non-ok tool status).
- FinalResponse shape is unchanged (no contract drift) in both modes.
- All three call surfaces (CLI/HTTP/session) share the same respond() code path.
- _orch_result_to_final_response maps tool_chosen -> intent correctly.
- Regression: Orch-3b, Orch-3a, Orch-2a invariants still green.
- Regression: respond() deterministic baseline still green.

Sections
--------
A  orch_config module              -- importability, public surface
B  is_orch_enabled()               -- env var reading
C  get_orch_provider()             -- env var reading
D  Flag OFF baseline parity        -- respond() unchanged when OFF
E  Flag ON happy path              -- respond() + FinalResponse shape (orch-routing assertions retired)
F  Flag ON fallback paths          -- non-OK outcomes fall back to deterministic
G  _orch_result_to_final_response  -- mapping shape and intent coverage
H  FinalResponse shape invariants  -- no contract drift in either mode
I  Shared call surface proof       -- CLI/HTTP/session all use respond()
J  Regression: deterministic path  -- representative intents still green
K  Regression: Orch-2a/3a/3b       -- registry and orchestrator still green

Run from packages/fpl-grounded-assistant::

    python run_phase_orch4a_tests.py
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

# ---------------------------------------------------------------------------
# Ensure flag is OFF before any imports that may read it
# ---------------------------------------------------------------------------
os.environ.pop("FPL_ORCH_ENABLED", None)
os.environ.pop("FPL_ORCH_PROVIDER", None)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.orch_config import (
    is_orch_enabled,
    get_orch_provider,
    ORCH_ENABLED_ENV,
    ORCH_PROVIDER_ENV,
    _TRUTHY,
)
from fpl_grounded_assistant.final_response import (
    FinalResponse,
    FinalResponseDebug,
    _orch_result_to_final_response,
    respond,
)
from fpl_grounded_assistant.orchestrator import (
    OrchestratorResult,
    OUTCOME_OK as ORCH_OUTCOME_OK,
    OUTCOME_NO_CLIENT,
    OUTCOME_LLM_ERROR,
    OUTCOME_NO_TOOL,
    OUTCOME_UNKNOWN_TOOL,
    OUTCOME_TOOL_ERROR,
    OUTCOME_TOOL_RESULT_ERROR,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    DEFAULT_ORCH_MODEL,
)
from fpl_grounded_assistant.dispatcher import (
    _TOOL_TO_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_PLAYER_RESOLVE,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_RANK_CANDIDATES,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,
    INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
    INTENT_PLAYER_SUMMARY,
    INTENT_UNSUPPORTED,
    OUTCOME_OK as DISP_OUTCOME_OK,
)
from fpl_grounded_assistant.tool_schema_registry import TOOL_NAMES, _ALL_SCHEMAS
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant import respond as pkg_respond  # package-level import

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


def _set_flag(value: str | None, provider: str | None = None) -> None:
    """Set or clear FPL_ORCH_ENABLED and FPL_ORCH_PROVIDER."""
    if value is None:
        os.environ.pop(ORCH_ENABLED_ENV, None)
    else:
        os.environ[ORCH_ENABLED_ENV] = value
    if provider is None:
        os.environ.pop(ORCH_PROVIDER_ENV, None)
    else:
        os.environ[ORCH_PROVIDER_ENV] = provider


# ---------------------------------------------------------------------------
# Mock clients
# ---------------------------------------------------------------------------

class _AnthropicToolClient:
    """Anthropic-shaped tool_use response (reused from Orch-3b tests)."""

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self.messages = self
        self.call_count: int = 0

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        self.call_count += 1
        _name  = self._tool_name
        _input = dict(self._tool_input)

        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_orch4a"
            name  = _name
            input = _input

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


class _RaisingClient:
    """Simulates LLM API failure."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, **kwargs) -> None:
        raise RuntimeError("simulated LLM failure")


class _NoToolClient:
    """Returns plain-text response with no tool_use block."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _TextBlock:
            type = "text"
            text = "I don't know."

        class _Response:
            content     = [_TextBlock()]
            stop_reason = "end_turn"

        return _Response()


# ---------------------------------------------------------------------------
# Section A: orch_config module
# ---------------------------------------------------------------------------

print("\n=== A: orch_config module ===")

ok(callable(is_orch_enabled),                   "A1: is_orch_enabled is callable")
ok(callable(get_orch_provider),                 "A2: get_orch_provider is callable")
ok(isinstance(ORCH_ENABLED_ENV, str) and ORCH_ENABLED_ENV,
   "A3: ORCH_ENABLED_ENV is non-empty str")
ok(isinstance(ORCH_PROVIDER_ENV, str) and ORCH_PROVIDER_ENV,
   "A4: ORCH_PROVIDER_ENV is non-empty str")
ok(isinstance(_TRUTHY, frozenset),              "A5: _TRUTHY is a frozenset")
ok("1" in _TRUTHY,                              "A6: '1' is truthy")
ok("true" in _TRUTHY,                          "A7: 'true' is truthy")
ok("yes" in _TRUTHY,                           "A8: 'yes' is truthy")
ok("on" in _TRUTHY,                            "A9: 'on' is truthy")
ok(callable(_orch_result_to_final_response),    "A10: _orch_result_to_final_response callable")


# ---------------------------------------------------------------------------
# Section B: is_orch_enabled()
# ---------------------------------------------------------------------------

print("\n=== B: is_orch_enabled() ===")

# Flag absent — OFF
_set_flag(None)
ok(is_orch_enabled() is False,                  "B1: absent -> False")

# Flag empty — OFF
_set_flag("")
ok(is_orch_enabled() is False,                  "B2: empty string -> False")

# Flag zero — OFF
_set_flag("0")
ok(is_orch_enabled() is False,                  "B3: '0' -> False")

# Truthy values — ON
for _v in ("1", "true", "TRUE", "True", "yes", "YES", "on", "ON"):
    _set_flag(_v)
    ok(is_orch_enabled() is True,               f"B4-on: '{_v}' -> True")

# Case-insensitivity
_set_flag("TRUE")
ok(is_orch_enabled() is True,                   "B5: 'TRUE' -> True")
_set_flag("True")
ok(is_orch_enabled() is True,                   "B6: 'True' -> True")

# Non-truthy values — OFF
for _v in ("false", "no", "off", "enabled", "yes_please"):
    _set_flag(_v)
    ok(is_orch_enabled() is False,              f"B7-off: '{_v}' -> False")

# Restore
_set_flag(None)
ok(is_orch_enabled() is False,                  "B8: cleared -> False again")


# ---------------------------------------------------------------------------
# Section C: get_orch_provider()
# ---------------------------------------------------------------------------

print("\n=== C: get_orch_provider() ===")

# Absent — None
_set_flag(None)
ok(get_orch_provider() is None,                 "C1: absent -> None")

# Empty — None
os.environ[ORCH_PROVIDER_ENV] = ""
ok(get_orch_provider() is None,                 "C2: empty -> None")
os.environ.pop(ORCH_PROVIDER_ENV)

# Known providers
os.environ[ORCH_PROVIDER_ENV] = PROVIDER_ANTHROPIC
ok(get_orch_provider() == PROVIDER_ANTHROPIC,   "C3: 'anthropic' -> PROVIDER_ANTHROPIC")

os.environ[ORCH_PROVIDER_ENV] = PROVIDER_OPENAI
ok(get_orch_provider() == PROVIDER_OPENAI,      "C4: 'openai' -> PROVIDER_OPENAI")

os.environ[ORCH_PROVIDER_ENV] = PROVIDER_GEMINI
ok(get_orch_provider() == PROVIDER_GEMINI,      "C5: 'gemini' -> PROVIDER_GEMINI")

# Whitespace stripped
os.environ[ORCH_PROVIDER_ENV] = "  anthropic  "
ok(get_orch_provider() == PROVIDER_ANTHROPIC,   "C6: whitespace stripped")

# Clear
os.environ.pop(ORCH_PROVIDER_ENV, None)
ok(get_orch_provider() is None,                 "C7: cleared -> None again")


# ---------------------------------------------------------------------------
# Section D: Flag OFF — baseline parity
# ---------------------------------------------------------------------------

print("\n=== D: flag OFF baseline parity ===")

_set_flag(None)
ok(is_orch_enabled() is False,                  "D0: flag confirmed OFF")

# D1-D2: captain score — unchanged
_r_d1 = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(_r_d1.intent  == "captain_score",            "D1: captain_score intent unchanged (flag OFF)")
ok(_r_d1.outcome == DISP_OUTCOME_OK,            "D2: captain_score outcome unchanged (flag OFF)")

# D3-D4: player summary
_r_d2 = respond("tell me about Salah", STANDARD_BOOTSTRAP)
ok(_r_d2.intent  == "player_summary",           "D3: player_summary intent unchanged (flag OFF)")
ok(_r_d2.outcome == DISP_OUTCOME_OK,            "D4: player_summary outcome unchanged (flag OFF)")

# D5-D6: chip advice
_r_d3 = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(_r_d3.intent  == "chip_advice",              "D5: chip_advice intent unchanged (flag OFF)")
ok(_r_d3.outcome == DISP_OUTCOME_OK,            "D6: chip_advice outcome unchanged (flag OFF)")

# D7-D8: unsupported still unsupported
_r_d4 = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(_r_d4.outcome == "unsupported_intent",       "D7: unsupported_intent unchanged (flag OFF)")
ok(not _r_d4.supported,                         "D8: unsupported.supported False (flag OFF)")

# D9: FinalResponse shape complete
ok(hasattr(_r_d1, "final_text"),                "D9: FinalResponse has final_text")
ok(hasattr(_r_d1, "intent"),                    "D10: FinalResponse has intent")
ok(hasattr(_r_d1, "outcome"),                   "D11: FinalResponse has outcome")
ok(hasattr(_r_d1, "supported"),                 "D12: FinalResponse has supported")
ok(hasattr(_r_d1, "review_passed"),             "D13: FinalResponse has review_passed")
ok(hasattr(_r_d1, "llm_used"),                  "D14: FinalResponse has llm_used")
ok(hasattr(_r_d1, "debug"),                     "D15: FinalResponse has debug")


# ---------------------------------------------------------------------------
# Section E: Flag ON happy path
# ---------------------------------------------------------------------------

print("\n=== E: flag ON happy path ===")

# E1-E8: get_current_gameweek — clean no-arg happy path
_mock_e1 = _AnthropicToolClient("get_current_gameweek", {})
_set_flag("1")
ok(is_orch_enabled() is True,                   "E0: flag confirmed ON")

_r_e1 = respond("what gameweek is it", STANDARD_BOOTSTRAP, client=_mock_e1)

ok(isinstance(_r_e1, FinalResponse),            "E1: respond() returns FinalResponse")
ok(_r_e1.outcome == DISP_OUTCOME_OK,            "E2: orchestrated outcome == OUTCOME_OK")
ok(_r_e1.supported is True,                     "E3: orchestrated supported == True")
ok(_r_e1.intent == INTENT_CURRENT_GAMEWEEK,     "E4: intent mapped from tool_chosen")
ok(_r_e1.review_passed is True,                 "E5: review_passed == True (grounded orch output)")
# G2.c: E6 deleted — tested Orch-4a gate behavior removed in commit 118d43e
ok(isinstance(_r_e1.final_text, str) and _r_e1.final_text,
   "E7: final_text is non-empty str")
ok(_r_e1.debug is None,                         "E8: debug is None by default")

# E9-E12: captain score with player query
_mock_e2 = _AnthropicToolClient("get_captain_score", {"query": "Haaland"})
_r_e2 = respond("should I captain Haaland", STANDARD_BOOTSTRAP, client=_mock_e2)

ok(_r_e2.outcome == DISP_OUTCOME_OK,            "E9: captain_score orch -> OUTCOME_OK")
ok(_r_e2.intent == INTENT_CAPTAIN_SCORE,        "E10: captain_score intent mapped correctly")
ok(isinstance(_r_e2.final_text, str) and _r_e2.final_text,
   "E11: captain_score final_text non-empty")
# G2.c: E12 deleted — tested Orch-4a gate behavior removed in commit 118d43e

# E13-E14: resolve_player intent mapping
_mock_e3 = _AnthropicToolClient("resolve_player", {"query": "Salah"})
_r_e3 = respond("who is Salah", STANDARD_BOOTSTRAP, client=_mock_e3)
ok(_r_e3.outcome == DISP_OUTCOME_OK,            "E13: resolve_player orch -> OUTCOME_OK")
ok(_r_e3.intent == INTENT_PLAYER_RESOLVE,       "E14: resolve_player intent mapped correctly")

# E15: include_debug=True populates FinalResponseDebug with orch metadata
_mock_e4 = _AnthropicToolClient("get_current_gameweek", {})
_r_e4 = respond("what gw", STANDARD_BOOTSTRAP, client=_mock_e4, include_debug=True)
ok(_r_e4.debug is not None,                     "E15: debug populated when include_debug=True")
ok(isinstance(_r_e4.debug, FinalResponseDebug), "E16: debug is FinalResponseDebug instance")
# G2.c: E17 deleted — tested Orch-4a gate behavior removed in commit 118d43e
ok(isinstance(_r_e4.debug.model, str),          "E18: debug.model is str")

# Restore
_set_flag(None)


# ---------------------------------------------------------------------------
# Section F: Flag ON fallback paths
# ---------------------------------------------------------------------------

print("\n=== F: flag ON fallback paths ===")

_set_flag("1")

# F1-F4: LLM raises exception -> fallback to deterministic
_mock_f1 = _RaisingClient()
_r_f1 = respond("should I captain Haaland", STANDARD_BOOTSTRAP, client=_mock_f1)
# Orch raises -> OUTCOME_LLM_ERROR -> fall through -> deterministic path
# But deterministic also uses client for ask_llm... and client raises.
# Deterministic ask_llm_safe catches the error and uses fallback text.
ok(isinstance(_r_f1, FinalResponse),            "F1: raising client -> FinalResponse (no crash)")
ok(isinstance(_r_f1.final_text, str) and _r_f1.final_text,
   "F2: raising client -> final_text non-empty (safe fallback)")

# F3-F5: No tool_use in response -> OUTCOME_NO_TOOL -> fall through to deterministic
_mock_f2 = _NoToolClient()
_r_f2 = respond("should I captain Haaland", STANDARD_BOOTSTRAP, client=_mock_f2)
ok(isinstance(_r_f2, FinalResponse),            "F3: no-tool client -> FinalResponse (no crash)")
ok(isinstance(_r_f2.final_text, str) and _r_f2.final_text,
   "F4: no-tool client -> final_text non-empty (deterministic fallback)")
# Without orchestration the deterministic path runs: intent should be captain_score
ok(_r_f2.intent == INTENT_CAPTAIN_SCORE,        "F5: no-tool fallback -> deterministic intent")

# F6-F8: Unknown tool name -> OUTCOME_UNKNOWN_TOOL -> fall through to deterministic
_mock_f3 = _AnthropicToolClient("totally_unknown_tool_xyz", {})
_r_f3 = respond("should I captain Haaland", STANDARD_BOOTSTRAP, client=_mock_f3)
ok(isinstance(_r_f3, FinalResponse),            "F6: unknown-tool orch -> FinalResponse (no crash)")
ok(isinstance(_r_f3.final_text, str) and _r_f3.final_text,
   "F7: unknown-tool orch -> final_text non-empty (deterministic fallback)")
ok(_r_f3.intent == INTENT_CAPTAIN_SCORE,        "F8: unknown-tool fallback -> deterministic intent")

# F9-F11: OUTCOME_TOOL_RESULT_ERROR (missing required arg) -> fall through
_mock_f4 = _AnthropicToolClient("get_captain_score", {})   # missing "query"
_r_f4 = respond("captain score", STANDARD_BOOTSTRAP, client=_mock_f4)
ok(isinstance(_r_f4, FinalResponse),            "F9: tool_result_error -> FinalResponse (no crash)")
ok(isinstance(_r_f4.final_text, str) and _r_f4.final_text,
   "F10: tool_result_error -> final_text non-empty (deterministic fallback)")
# Deterministic path handles "captain score" question
ok(isinstance(_r_f4.intent, str),               "F11: tool_result_error fallback -> intent is str")

# F12: No client + flag ON -> OUTCOME_NO_CLIENT -> fall through to deterministic
_saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    _r_f5 = respond("what gameweek is it", STANDARD_BOOTSTRAP)
    ok(isinstance(_r_f5, FinalResponse),        "F12: no-client flag-ON -> FinalResponse (no crash)")
    ok(isinstance(_r_f5.final_text, str) and _r_f5.final_text,
       "F13: no-client flag-ON -> final_text non-empty")
except Exception as exc:
    ok(False, f"F12: respond raised: {exc}")
    ok(False, "F13: (skipped)")
finally:
    if _saved_key is not None:
        os.environ["ANTHROPIC_API_KEY"] = _saved_key

# Restore
_set_flag(None)


# ---------------------------------------------------------------------------
# Section G: _orch_result_to_final_response mapping
# ---------------------------------------------------------------------------

print("\n=== G: _orch_result_to_final_response mapping ===")

# Build a minimal successful OrchestratorResult
def _make_orch_result(tool_name: str, answer: str) -> OrchestratorResult:
    return OrchestratorResult(
        question="test",
        tool_chosen=tool_name,
        tool_args={"query": "test"},
        tool_output={"status": "ok"},
        answer_text=answer,
        llm_used=True,
        model=DEFAULT_ORCH_MODEL,
        outcome=ORCH_OUTCOME_OK,
        error=None,
    )

# G1-G5: basic mapping
_result_g1 = _make_orch_result("get_captain_score", "Haaland is a strong captain choice.")
_fr_g1 = _orch_result_to_final_response(_result_g1)

ok(isinstance(_fr_g1, FinalResponse),           "G1: returns FinalResponse instance")
ok(_fr_g1.outcome == DISP_OUTCOME_OK,           "G2: outcome == OUTCOME_OK")
ok(_fr_g1.supported is True,                    "G3: supported == True")
ok(_fr_g1.intent == INTENT_CAPTAIN_SCORE,       "G4: intent mapped from tool_chosen")
ok(_fr_g1.review_passed is True,                "G5: review_passed == True")
ok(_fr_g1.llm_used is True,                     "G6: llm_used from OrchestratorResult")
ok(_fr_g1.final_text == "Haaland is a strong captain choice.",
   "G7: final_text == answer_text")
ok(_fr_g1.debug is None,                        "G8: debug is None by default")

# G9-G10: include_debug=True
_fr_g1d = _orch_result_to_final_response(_result_g1, include_debug=True)
ok(_fr_g1d.debug is not None,                   "G9: debug populated with include_debug=True")
ok(_fr_g1d.debug.classification_source == "orchestrator",
   "G10: classification_source == 'orchestrator'")

# G11: all tool names map to correct intents
for _tool, _expected_intent in _TOOL_TO_INTENT.items():
    _r = _make_orch_result(_tool, "answer")
    _fr = _orch_result_to_final_response(_r)
    ok(_fr.intent == _expected_intent,
       f"G11-intent: tool '{_tool}' -> intent '{_expected_intent}'")

# G12: unknown tool_chosen -> INTENT_UNSUPPORTED
_r_unk = OrchestratorResult(
    question="test",
    tool_chosen="totally_unknown",
    tool_args={},
    tool_output={"status": "ok"},
    answer_text="unknown",
    llm_used=True,
    model="none",
    outcome=ORCH_OUTCOME_OK,
    error=None,
)
_fr_unk = _orch_result_to_final_response(_r_unk)
ok(_fr_unk.intent == INTENT_UNSUPPORTED,        "G12: unknown tool -> INTENT_UNSUPPORTED")

# G13-G20: metadata field behavior after Orch-4b
# get_captain_score -> captain populated; all other fields None (different intents)
ok(_fr_g1.comparison is None,                   "G13: comparison is None (not compare_players)")
ok(_fr_g1.captain is not None,                  "G14: captain populated for get_captain_score (Orch-4b)")
ok(_fr_g1.transfer is None,                     "G15: transfer is None (not transfer_advice)")
ok(_fr_g1.chip is None,                         "G16: chip is None (not chip_advice)")
ok(_fr_g1.fixture_run is None,                  "G17: fixture_run is None (not fixture_run)")
ok(_fr_g1.differential is None,                 "G18: differential is None (not differential)")
ok(_fr_g1.captain_ranking is None,              "G19: captain_ranking is None (not rank_candidates)")
ok(_fr_g1.sub_responses is None,                "G20: sub_responses always None (single-intent)")


# ---------------------------------------------------------------------------
# Section H: FinalResponse shape invariants
# ---------------------------------------------------------------------------

print("\n=== H: FinalResponse shape invariants ===")

# Same required fields present in both flag-OFF and flag-ON responses
_set_flag(None)
_r_hoff = respond("should I captain Haaland", STANDARD_BOOTSTRAP)

_set_flag("1")
_mock_h = _AnthropicToolClient("get_captain_score", {"query": "Haaland"})
_r_hon = respond("should I captain Haaland", STANDARD_BOOTSTRAP, client=_mock_h)
_set_flag(None)

_fields = [
    "final_text", "outcome", "supported", "intent",
    "review_passed", "llm_used", "debug",
    "comparison", "captain", "captain_ranking", "sub_responses",
    "transfer", "chip", "fixture_run", "differential",
]
for _f in _fields:
    ok(hasattr(_r_hoff, _f), f"H1-off-field: FinalResponse[OFF] has '{_f}'")
    ok(hasattr(_r_hon, _f),  f"H2-on-field:  FinalResponse[ON] has '{_f}'")

# Type contracts hold for both
ok(isinstance(_r_hoff.final_text, str) and _r_hoff.final_text,
   "H3: OFF final_text non-empty str")
ok(isinstance(_r_hon.final_text, str) and _r_hon.final_text,
   "H4: ON final_text non-empty str")
ok(isinstance(_r_hoff.outcome, str),            "H5: OFF outcome is str")
ok(isinstance(_r_hon.outcome, str),             "H6: ON outcome is str")
ok(isinstance(_r_hoff.supported, bool),         "H7: OFF supported is bool")
ok(isinstance(_r_hon.supported, bool),          "H8: ON supported is bool")
ok(isinstance(_r_hoff.intent, str),             "H9: OFF intent is str")
ok(isinstance(_r_hon.intent, str),              "H10: ON intent is str")
ok(isinstance(_r_hoff.review_passed, bool),     "H11: OFF review_passed is bool")
ok(isinstance(_r_hon.review_passed, bool),      "H12: ON review_passed is bool")
ok(isinstance(_r_hoff.llm_used, bool),          "H13: OFF llm_used is bool")
ok(isinstance(_r_hon.llm_used, bool),           "H14: ON llm_used is bool")

# Frozen (immutable) in both cases
try:
    _r_hon.outcome = "modified"  # type: ignore[misc]
    ok(False, "H15: ON FinalResponse is NOT frozen (should be)")
except (AttributeError, TypeError):
    ok(True,  "H15: ON FinalResponse is frozen (immutable)")


# ---------------------------------------------------------------------------
# Section I: Shared call surface proof
# ---------------------------------------------------------------------------

print("\n=== I: shared call surface proof ===")

# All three surfaces import from the same respond() function.
# We verify by importing from each module and confirming identity.
from fpl_grounded_assistant.final_response import respond as _fr_respond
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP as _SB

# Package-level respond is the same object as final_response.respond
ok(pkg_respond is _fr_respond,                  "I1: pkg respond is final_response.respond")

# CLI imports respond from final_response
import fpl_cli as _cli_mod
import importlib
import inspect
_cli_src = inspect.getsource(_cli_mod)
ok("from fpl_grounded_assistant" in _cli_src and "respond" in _cli_src,
   "I2: fpl_cli.py imports respond from fpl_grounded_assistant")

# HTTP server imports respond from final_response
import fpl_server as _srv_mod
_srv_src = inspect.getsource(_srv_mod)
ok("from fpl_grounded_assistant" in _srv_src and "respond" in _srv_src,
   "I3: fpl_server.py imports respond from fpl_grounded_assistant")

# Session imports respond from final_response
from fpl_grounded_assistant.conversation_state import ConversationState
_cs_src = inspect.getsource(ConversationState)
ok(True,                                        "I4: ConversationState is importable")

# ConversationSession wraps respond()
from fpl_grounded_assistant.conversation_state import ConversationSession
ok(callable(ConversationSession),               "I5: ConversationSession is callable")

# The flag affects all call paths because they all call the same respond()
# Verify by running a session.respond() call with flag ON and orch mock
_set_flag("1")
_mock_i = _AnthropicToolClient("get_captain_score", {"query": "Haaland"})
_session = ConversationSession()
_r_session = _session.respond(
    "should I captain Haaland", STANDARD_BOOTSTRAP, client=_mock_i
)
ok(isinstance(_r_session, FinalResponse),       "I6: ConversationSession.respond returns FinalResponse")
ok(_r_session.outcome == DISP_OUTCOME_OK,       "I7: session.respond orch path -> OUTCOME_OK")
ok(_r_session.intent == INTENT_CAPTAIN_SCORE,   "I8: session.respond orch -> correct intent")
# G2.c: I9 deleted — tested Orch-4a gate behavior removed in commit 118d43e
_set_flag(None)


# ---------------------------------------------------------------------------
# Section J: Regression — deterministic path
# ---------------------------------------------------------------------------

print("\n=== J: regression: deterministic path ===")

_set_flag(None)  # ensure deterministic path

_r_j1 = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(_r_j1.intent  == "captain_score",            "J1: captain_score intent")
ok(_r_j1.outcome == DISP_OUTCOME_OK,            "J2: captain_score outcome")

_r_j2 = respond("tell me about Salah", STANDARD_BOOTSTRAP)
ok(_r_j2.intent  == "player_summary",           "J3: player_summary intent")
ok(_r_j2.outcome == DISP_OUTCOME_OK,            "J4: player_summary outcome")

_r_j3 = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(_r_j3.intent  == "chip_advice",              "J5: chip_advice intent")
ok(_r_j3.outcome == DISP_OUTCOME_OK,            "J6: chip_advice outcome")

_r_j4 = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(_r_j4.outcome == "unsupported_intent",       "J7: unsupported still unsupported")
ok(not _r_j4.supported,                         "J8: unsupported.supported == False")

_r_j5 = respond("good differentials", STANDARD_BOOTSTRAP)
ok(_r_j5.intent == "differential_picks",        "J9: differential_picks intent")
ok(_r_j5.supported is True,                     "J10: differential_picks supported")


# ---------------------------------------------------------------------------
# Section K: Orch-2a/3a/3b regression
# ---------------------------------------------------------------------------

print("\n=== K: orch regression ===")

from fpl_grounded_assistant.tool_schema_registry import (
    list_tool_schemas, get_tool_schema, validate_tool_schema_shape,
)
from fpl_grounded_assistant.orchestrator import (
    ask_orchestrated, _ALL_OUTCOMES,
)

# Orch-2a: registry integrity
_names = list_tool_schemas()
ok(len(_names) == 10,                           "K1: 10 tools in registry")
ok(_names == sorted(_names),                    "K2: names sorted")
for _s in _ALL_SCHEMAS:
    ok(validate_tool_schema_shape(_s),          f"K3-valid: '{_s.name}' validates")

# Orch-3a: outcome constants
ok(len(_ALL_OUTCOMES) >= 7,                     "K4: _ALL_OUTCOMES has 7+ values")

# Orch-3b: provider constants
ok(isinstance(PROVIDER_ANTHROPIC, str),         "K5: PROVIDER_ANTHROPIC str")
ok(isinstance(PROVIDER_OPENAI, str),            "K6: PROVIDER_OPENAI str")
ok(isinstance(PROVIDER_GEMINI, str),            "K7: PROVIDER_GEMINI str")

# to_gemini() still works
_s0 = _ALL_SCHEMAS[0]
_gem = _s0.to_gemini()
ok("name" in _gem and "parameters" in _gem,     "K8: to_gemini() still works")

# ask_orchestrated() still callable and isolated
_mock_k = _AnthropicToolClient("get_current_gameweek", {})
_rk = ask_orchestrated("what gw", STANDARD_BOOTSTRAP, client=_mock_k)
ok(_rk.outcome == ORCH_OUTCOME_OK,              "K9: ask_orchestrated direct call still works")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase Orch-4a: {_pass}/{total} assertions passed.")
if _fail:
    print(f"               {_fail} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
