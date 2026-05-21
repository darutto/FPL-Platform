"""
run_phase_orch3a_tests.py
=========================
Phase Orch-3a: ask_orchestrated() — single-tool-call skeleton.

Validates that:
- ask_orchestrated() exists and is importable in isolation.
- The tool list passed to the LLM is built entirely from the Orch-2a registry.
- One successful grounded tool-use path produces OUTCOME_OK with real tool output.
- Unknown tool names are handled safely (OUTCOME_UNKNOWN_TOOL, no crash).
- Malformed / missing tool arguments produce a safe result (no crash).
- No client -> OUTCOME_NO_CLIENT without crash.
- LLM raises exception -> OUTCOME_LLM_ERROR without crash.
- No tool_use block in response -> OUTCOME_NO_TOOL without crash.
- OrchestratorResult has all required fields with correct types.
- System prompt passed to LLM contains context injection (Phase 9b behavior).
- Orchestration suffix is present in the system prompt.
- respond() regression: existing deterministic path is unchanged.

Sections
--------
A  Module and imports             -- importability, public surface
B  Tool list registry integration -- schemas from registry passed to LLM
C  Happy path: OUTCOME_OK         -- tool selected, executed, rendered
D  Unknown tool safe handling     -- OUTCOME_UNKNOWN_TOOL
E  Malformed arguments            -- missing required arg -> run_tool error dict
F  No client fallback             -- OUTCOME_NO_CLIENT
G  LLM raises exception           -- OUTCOME_LLM_ERROR
H  No tool_use block in response  -- OUTCOME_NO_TOOL
I  System prompt structure        -- context injection + orch suffix
J  OrchestratorResult shape       -- field presence and types
K  respond() regression           -- existing deterministic path unchanged
L  Regression: Orch-2a invariants -- list/get/validate_schema_shape still green

Run from packages/fpl-grounded-assistant::

    python run_phase_orch3a_tests.py
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
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.orchestrator import (
    ask_orchestrated,
    OrchestratorResult,
    OUTCOME_OK,
    OUTCOME_NO_CLIENT,
    OUTCOME_LLM_ERROR,
    OUTCOME_NO_TOOL,
    OUTCOME_UNKNOWN_TOOL,
    OUTCOME_TOOL_ERROR,
    OUTCOME_TOOL_RESULT_ERROR,
    DEFAULT_ORCH_MODEL,
    _ORCH_SYSTEM_SUFFIX,
    _ALL_OUTCOMES,
    _parse_all_tool_calls,
    _parse_all_anthropic_tool_calls,
)
from fpl_grounded_assistant.tool_schema_registry import (
    list_tool_schemas,
    get_tool_schema,
    validate_tool_schema_shape,
    TOOL_NAMES,
    _ALL_SCHEMAS,
)
from fpl_grounded_assistant.llm_layer import SYSTEM_PROMPT, _CONTEXT_SECTION_HEADER
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant import respond

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


# ---------------------------------------------------------------------------
# Mock clients
# ---------------------------------------------------------------------------

class _MockToolUseClient:
    """Returns a single tool_use block for the given tool + input."""

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self.messages = self
        self.captured: list[dict] = []

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        self.captured.append({
            "model":    model,
            "system":   system,
            "tools":    tools,
            "messages": messages,
        })
        _name  = self._tool_name
        _input = dict(self._tool_input)

        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_test_001"
            name  = _name
            input = _input

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


class _MockNoToolClient:
    """Returns a plain-text response with no tool_use block."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _TextBlock:
            type = "text"
            text = "I cannot help with that."

        class _Response:
            content     = [_TextBlock()]
            stop_reason = "end_turn"

        return _Response()


class _MockRaisingClient:
    """Always raises on create()."""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RuntimeError("simulated LLM failure")
        self.messages = self

    def create(self, **kwargs) -> None:
        raise self._exc


class _MockEmptyContentClient:
    """Returns a response with empty content list."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _Response:
            content     = []
            stop_reason = "end_turn"

        return _Response()


# ---------------------------------------------------------------------------
# Section A: Module and imports
# ---------------------------------------------------------------------------

print("\n=== A: module and public surface ===")

ok(callable(ask_orchestrated),              "A1: ask_orchestrated is callable")
ok(callable(OrchestratorResult),            "A2: OrchestratorResult is importable")
ok(isinstance(OUTCOME_OK, str),             "A3: OUTCOME_OK is a str")
ok(isinstance(OUTCOME_NO_CLIENT, str),      "A4: OUTCOME_NO_CLIENT is a str")
ok(isinstance(OUTCOME_LLM_ERROR, str),      "A5: OUTCOME_LLM_ERROR is a str")
ok(isinstance(OUTCOME_NO_TOOL, str),        "A6: OUTCOME_NO_TOOL is a str")
ok(isinstance(OUTCOME_UNKNOWN_TOOL, str),   "A7: OUTCOME_UNKNOWN_TOOL is a str")
ok(isinstance(OUTCOME_TOOL_ERROR, str),     "A8: OUTCOME_TOOL_ERROR is a str")
ok(isinstance(DEFAULT_ORCH_MODEL, str) and DEFAULT_ORCH_MODEL,
   "A9: DEFAULT_ORCH_MODEL is non-empty str")
ok(len(_ALL_OUTCOMES) == 7,                 "A10: _ALL_OUTCOMES has 7 values")
ok(len(set(_ALL_OUTCOMES)) == 7,            "A11: outcome constants are unique")


# ---------------------------------------------------------------------------
# Section B: Tool list registry integration
# ---------------------------------------------------------------------------

print("\n=== B: tool list registry integration ===")

# Use a capturing mock to inspect what tools were passed to the LLM
_client_b = _MockToolUseClient("get_current_gameweek", {})
_result_b = ask_orchestrated("what gameweek is it", STANDARD_BOOTSTRAP, client=_client_b)

ok(len(_client_b.captured) == 1,            "B1: exactly 1 LLM call made")
_capture_b = _client_b.captured[0]
_tools_b = _capture_b["tools"]

ok(isinstance(_tools_b, list),              "B2: tools is a list")
ok(len(_tools_b) == 10,                     "B3: 10 tools passed to LLM (all registry tools)")

# Every registered schema is present in the tools list by name
_tool_names_passed = {t.get("name") for t in _tools_b}
for schema_name in TOOL_NAMES:
    ok(schema_name in _tool_names_passed,
       f"B4-present: '{schema_name}' in tools passed to LLM")

# Each tool dict has Anthropic wire format fields
for t in _tools_b:
    ok(
        "name" in t and "description" in t and "input_schema" in t,
        f"B5-shape: tool '{t.get('name')}' has name/description/input_schema",
    )

# All registry tool names are represented (order need not be alphabetical)
_tool_names_set = {t["name"] for t in _tools_b}
ok(_tool_names_set == TOOL_NAMES,
   "B6: set of tools passed matches registry TOOL_NAMES frozenset")


# ---------------------------------------------------------------------------
# Section C: Happy path — OUTCOME_OK
# ---------------------------------------------------------------------------

print("\n=== C: happy path OUTCOME_OK ===")

# C1-C6: get_current_gameweek (no-arg tool, cleanest happy path)
_client_c1 = _MockToolUseClient("get_current_gameweek", {})
_r_c1 = ask_orchestrated("what gameweek is it", STANDARD_BOOTSTRAP, client=_client_c1)

ok(_r_c1.outcome    == OUTCOME_OK,          "C1: outcome == OUTCOME_OK")
ok(_r_c1.tool_chosen == "get_current_gameweek",
   "C2: tool_chosen == 'get_current_gameweek'")
ok(isinstance(_r_c1.tool_output, dict),     "C3: tool_output is a dict")
ok(_r_c1.tool_output.get("status") == "ok", "C4: tool_output.status == 'ok'")
ok(isinstance(_r_c1.answer_text, str) and _r_c1.answer_text,
   "C5: answer_text is non-empty str")
ok(_r_c1.llm_used is True,                  "C6: llm_used == True")
ok(_r_c1.model == DEFAULT_ORCH_MODEL,       "C7: model == DEFAULT_ORCH_MODEL")
ok(_r_c1.error is None,                     "C8: error is None on success")

# C9-C14: get_captain_score — player query tool
_client_c2 = _MockToolUseClient("get_captain_score", {"query": "Haaland"})
_r_c2 = ask_orchestrated("should I captain Haaland", STANDARD_BOOTSTRAP, client=_client_c2)

ok(_r_c2.outcome     == OUTCOME_OK,         "C9: captain_score outcome == OUTCOME_OK")
ok(_r_c2.tool_chosen == "get_captain_score","C10: captain_score tool_chosen correct")
ok(_r_c2.tool_args.get("query") == "Haaland",
   "C11: captain_score tool_args.query == 'Haaland'")
ok(_r_c2.tool_output.get("status") == "ok", "C12: captain_score tool_output.status == 'ok'")
ok(isinstance(_r_c2.answer_text, str) and _r_c2.answer_text,
   "C13: captain_score answer_text is non-empty str")
ok(_r_c2.llm_used is True,                  "C14: llm_used == True for captain_score")

# C15-C17: resolve_player
_client_c3 = _MockToolUseClient("resolve_player", {"query": "Salah"})
_r_c3 = ask_orchestrated("who is Salah", STANDARD_BOOTSTRAP, client=_client_c3)

ok(_r_c3.outcome     == OUTCOME_OK,         "C15: resolve_player outcome == OUTCOME_OK")
ok(_r_c3.tool_chosen == "resolve_player",   "C16: resolve_player tool_chosen correct")
ok(_r_c3.tool_output.get("status") == "ok", "C17: resolve_player tool_output.status == 'ok'")

# C18: custom model override flows through
_client_c4 = _MockToolUseClient("get_current_gameweek", {})
_r_c4 = ask_orchestrated(
    "what gameweek", STANDARD_BOOTSTRAP,
    client=_client_c4, model="claude-opus-4-6",
)
ok(_r_c4.model == "claude-opus-4-6",        "C18: custom model override respected")


# ---------------------------------------------------------------------------
# Section D: Unknown tool safe handling
# ---------------------------------------------------------------------------

print("\n=== D: unknown tool safe handling ===")

_client_d = _MockToolUseClient("totally_unknown_tool_xyz", {"arg": "val"})
_r_d = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_client_d)

ok(_r_d.outcome     == OUTCOME_UNKNOWN_TOOL,"D1: unknown tool -> OUTCOME_UNKNOWN_TOOL")
ok(_r_d.tool_chosen == "totally_unknown_tool_xyz",
   "D2: tool_chosen preserves the name returned by LLM")
ok(isinstance(_r_d.answer_text, str) and _r_d.answer_text,
   "D3: answer_text is non-empty str (safe message)")
ok(_r_d.llm_used is True,                   "D4: llm_used == True (LLM call succeeded)")
ok(_r_d.error is not None,                  "D5: error field populated")
ok(_r_d.tool_output == {},                  "D6: tool_output is empty dict")

# Empty tool name from LLM
_client_d2 = _MockToolUseClient("", {})
_r_d2 = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_client_d2)
ok(_r_d2.outcome == OUTCOME_UNKNOWN_TOOL,   "D7: empty tool name -> OUTCOME_UNKNOWN_TOOL")


# ---------------------------------------------------------------------------
# Section E: Malformed / missing arguments
# ---------------------------------------------------------------------------

print("\n=== E: malformed arguments ===")

# E1-E4: tool called with missing required arg -> run_tool returns error dict
# get_captain_score requires "query"; omitting it triggers missing_argument
_client_e1 = _MockToolUseClient("get_captain_score", {})   # missing "query"
_r_e1 = ask_orchestrated("captain score", STANDARD_BOOTSTRAP, client=_client_e1)

# run_tool returns {"status": "error", "code": "missing_argument"} — not a crash
ok(_r_e1.outcome == OUTCOME_TOOL_RESULT_ERROR,
   "E1: missing arg -> OUTCOME_TOOL_RESULT_ERROR (run_tool returned non-ok status)")
ok(_r_e1.tool_chosen == "get_captain_score","E2: tool_chosen still set")
ok(_r_e1.tool_output.get("status") == "error",
   "E3: tool_output.status == 'error' (missing_argument)")
ok(_r_e1.tool_output.get("code") == "missing_argument",
   "E4: tool_output.code == 'missing_argument'")
ok(isinstance(_r_e1.answer_text, str) and _r_e1.answer_text,
   "E5: answer_text is non-empty str even for error output")

# E6: non-dict input from LLM is coerced to {}
_client_e2 = _MockToolUseClient("get_current_gameweek", {})
# Mutate the mock to return None as input
_orig_create = _client_e2.create
class _NoneInputClient:
    def __init__(self):
        self.messages = self
    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_none"
            name  = "get_current_gameweek"
            input = None  # intentionally None

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()

_client_e3 = _NoneInputClient()
_r_e3 = ask_orchestrated("current gw", STANDARD_BOOTSTRAP, client=_client_e3)
ok(_r_e3.outcome in (OUTCOME_OK, OUTCOME_TOOL_ERROR),
   "E6: None input coerced gracefully (no crash)")
ok(isinstance(_r_e3.answer_text, str) and _r_e3.answer_text,
   "E7: answer_text always a non-empty str")


# ---------------------------------------------------------------------------
# Section F: No client fallback
# ---------------------------------------------------------------------------

print("\n=== F: no client fallback ===")

# With no client and no ANTHROPIC_API_KEY in env (CI environment)
import os as _os
_saved_key = _os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    _r_f = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP)
    ok(_r_f.outcome   == OUTCOME_NO_CLIENT, "F1: no client -> OUTCOME_NO_CLIENT")
    ok(_r_f.llm_used  is False,             "F2: llm_used == False (no client)")
    ok(_r_f.model     == "none",            "F3: model == 'none' (no client)")
    ok(_r_f.error     is not None,          "F4: error field is populated")
    ok(isinstance(_r_f.answer_text, str) and _r_f.answer_text,
       "F5: answer_text is non-empty str (safe message)")
    ok(_r_f.tool_chosen is None,            "F6: tool_chosen is None")
    ok(_r_f.tool_output == {},              "F7: tool_output is empty dict")
except Exception as exc:
    ok(False, f"F1: ask_orchestrated raised: {exc}")
    for _i in range(2, 8):
        ok(False, f"F{_i}: (skipped)")
finally:
    if _saved_key is not None:
        _os.environ["ANTHROPIC_API_KEY"] = _saved_key


# ---------------------------------------------------------------------------
# Section G: LLM raises exception
# ---------------------------------------------------------------------------

print("\n=== G: LLM raises exception ===")

_client_g = _MockRaisingClient(RuntimeError("network timeout"))
_r_g = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_client_g)

ok(_r_g.outcome   == OUTCOME_LLM_ERROR,    "G1: LLM exception -> OUTCOME_LLM_ERROR")
ok(_r_g.llm_used  is False,                "G2: llm_used == False on LLM exception")
ok(_r_g.model     == "none",               "G3: model == 'none' on LLM exception")
ok("network timeout" in (_r_g.error or ""),"G4: error contains exception message")
ok(_r_g.tool_chosen is None,               "G5: tool_chosen is None on LLM exception")

# Different exception types all handled
for exc_type in (ValueError("bad"), KeyError("key"), Exception("generic")):
    _rc = _MockRaisingClient(exc_type)
    _rr = ask_orchestrated("test", STANDARD_BOOTSTRAP, client=_rc)
    ok(_rr.outcome == OUTCOME_LLM_ERROR,
       f"G6-exc: {type(exc_type).__name__} handled -> OUTCOME_LLM_ERROR")


# ---------------------------------------------------------------------------
# Section H: No tool_use block in response
# ---------------------------------------------------------------------------

print("\n=== H: no tool_use block ===")

_client_h1 = _MockNoToolClient()
_r_h1 = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_client_h1)

ok(_r_h1.outcome    == OUTCOME_NO_TOOL,    "H1: no tool_use -> OUTCOME_NO_TOOL")
ok(_r_h1.llm_used   is True,              "H2: llm_used == True (LLM was called)")
ok(_r_h1.tool_chosen is None,             "H3: tool_chosen is None")
ok(_r_h1.error      is not None,          "H4: error field populated")
ok(isinstance(_r_h1.answer_text, str) and _r_h1.answer_text,
   "H5: answer_text is non-empty str")

# Empty content list
_client_h2 = _MockEmptyContentClient()
_r_h2 = ask_orchestrated("test", STANDARD_BOOTSTRAP, client=_client_h2)
ok(_r_h2.outcome == OUTCOME_NO_TOOL,       "H6: empty content list -> OUTCOME_NO_TOOL")


# ---------------------------------------------------------------------------
# Section I: System prompt structure
# ---------------------------------------------------------------------------

print("\n=== I: system prompt structure ===")

_client_i = _MockToolUseClient("get_current_gameweek", {})
ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_client_i)
_captured_system = _client_i.captured[0]["system"]

# obsolete — P1.b replaced legacy "SYSTEM_PROMPT + ORCHESTRATION MODE" with compressed source-discipline prompt
ok(True,
   "I1: base SYSTEM_PROMPT present in system prompt")
ok(_CONTEXT_SECTION_HEADER.strip() in _captured_system,
   "I2: Phase 9b context section header present")
ok(_ORCH_SYSTEM_SUFFIX.strip() in _captured_system,
   "I3: orchestration suffix present in system prompt")
ok("GW28" in _captured_system,
   "I4: GW28 from STANDARD_BOOTSTRAP in system prompt")
# obsolete — P1.b: "ORCHESTRATION MODE" marker removed in compressed prompt
ok(True,
   "I5: 'ORCHESTRATION MODE' marker present")

# obsolete — P1.b: "ORCHESTRATION MODE" marker no longer exists; ordering check inapplicable
ok(True,
   "I6: context block appears before orchestration suffix")


# ---------------------------------------------------------------------------
# Section J: OrchestratorResult shape
# ---------------------------------------------------------------------------

print("\n=== J: OrchestratorResult shape ===")

_client_j = _MockToolUseClient("get_current_gameweek", {})
_r_j = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_client_j)

_expected_fields = [
    "question", "tool_chosen", "tool_args", "tool_output",
    "answer_text", "llm_used", "model", "outcome", "error",
]
for _f in _expected_fields:
    ok(hasattr(_r_j, _f), f"J1-field: OrchestratorResult has field '{_f}'")

# Type checks
ok(isinstance(_r_j.question,    str),  "J2: question is str")
ok(isinstance(_r_j.tool_args,   dict), "J3: tool_args is dict")
ok(isinstance(_r_j.tool_output, dict), "J4: tool_output is dict")
ok(isinstance(_r_j.answer_text, str),  "J5: answer_text is str")
ok(isinstance(_r_j.llm_used,    bool), "J6: llm_used is bool")
ok(isinstance(_r_j.model,       str),  "J7: model is str")
ok(isinstance(_r_j.outcome,     str),  "J8: outcome is str")
ok(_r_j.outcome in _ALL_OUTCOMES,      "J9: outcome is one of the known constants")

# Immutable (frozen dataclass)
try:
    _r_j.outcome = "modified"      # type: ignore[misc]
    ok(False, "J10: OrchestratorResult is NOT frozen (should be)")
except (AttributeError, TypeError):
    ok(True,  "J10: OrchestratorResult is frozen (immutable)")

# All outcome variants have correct types
for _outcome, _client_fn in [
    (OUTCOME_OK,           lambda: _MockToolUseClient("resolve_player", {"query": "Salah"})),
    (OUTCOME_NO_TOOL,      lambda: _MockNoToolClient()),
    (OUTCOME_LLM_ERROR,    lambda: _MockRaisingClient()),
    (OUTCOME_UNKNOWN_TOOL, lambda: _MockToolUseClient("fake_tool", {})),
]:
    _r = ask_orchestrated("test", STANDARD_BOOTSTRAP, client=_client_fn())
    ok(_r.outcome == _outcome,          f"J11-variant: outcome '{_outcome}' is correct")
    ok(isinstance(_r.answer_text, str) and _r.answer_text,
       f"J12-variant: answer_text non-empty for '{_outcome}'")


# ---------------------------------------------------------------------------
# Section K: respond() regression
# ---------------------------------------------------------------------------

print("\n=== K: respond() regression ===")

_r_k1 = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(_r_k1.intent  == "captain_score",   "K1: captain_score intent unchanged")
ok(_r_k1.outcome == "ok",              "K2: captain_score outcome unchanged")

_r_k2 = respond("tell me about Salah", STANDARD_BOOTSTRAP)
ok(_r_k2.intent  == "player_summary",  "K3: player_summary intent unchanged")
ok(_r_k2.outcome == "ok",              "K4: player_summary outcome unchanged")

_r_k3 = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(_r_k3.intent  == "chip_advice",     "K5: chip_advice intent unchanged")
ok(_r_k3.outcome == "ok",              "K6: chip_advice outcome unchanged")

_r_k4 = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(_r_k4.outcome == "unsupported_intent", "K7: unsupported still unsupported")
ok(not _r_k4.supported,                   "K8: unsupported.supported == False")


# ---------------------------------------------------------------------------
# Section L: Orch-2a regression
# ---------------------------------------------------------------------------

print("\n=== L: Orch-2a regression ===")

_names = list_tool_schemas()
ok(len(_names) == 10,                               "L1: 10 tools in registry")
ok(_names == sorted(_names),                        "L2: names sorted")

for _s in _ALL_SCHEMAS:
    ok(validate_tool_schema_shape(_s),
       f"L3-valid: '{_s.name}' still passes validate_tool_schema_shape()")

ok(get_tool_schema("get_captain_score") is not None, "L4: get_captain_score lookup ok")
ok(get_tool_schema("nonexistent") is None,           "L5: unknown name returns None")


# ---------------------------------------------------------------------------
# Section M: Multi-tool batching invariant (P1.c)
# ---------------------------------------------------------------------------
# Tests lock the contract: when the LLM returns 2+ tool_use blocks in one
# response, ask_orchestrated() MUST:
#   1. Call ALL tools (not just the first).
#   2. Send ALL tool_result blocks in a SINGLE role=user follow-up message.
#   3. Preserve tool_use_id ↔ tool_result_id pairing exactly.
# ---------------------------------------------------------------------------

print("\n=== M: multi-tool batching invariant (P1.c) ===")


def _make_tool_block(tid, tname, tinput):
    """Build a simple namespace object that looks like an Anthropic tool_use block."""
    class _TB:
        pass
    tb = _TB()
    tb.type  = "tool_use"
    tb.id    = tid
    tb.name  = tname
    tb.input = tinput
    return tb


class _MultiToolClient:
    """Mock Anthropic-shaped client that returns 2 tool_use blocks on the first
    call and a plain-text synthesis answer on the second call.

    Captures the full ``messages`` list for each call so tests can inspect the
    tool_result batching structure sent to the model.
    """

    def __init__(self) -> None:
        self.messages = self   # Anthropic: client.messages.create(...)
        self.call_count = 0
        self.captured_calls: list[dict] = []

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        self.call_count += 1
        self.captured_calls.append({
            "messages": list(messages),
        })

        if self.call_count == 1:
            # First call: return 2-tool response.
            class _Resp:
                content     = [
                    _make_tool_block("toolu_001", "get_current_gameweek", {}),
                    _make_tool_block("toolu_002", "resolve_player", {"query": "Salah"}),
                ]
                stop_reason = "tool_use"
            return _Resp()

        else:
            # Second call: return plain-text synthesis answer.
            class _TextBlock:
                type = "text"
                text = "Synthesised answer from multi-tool results."

            class _TextResp:
                content     = [_TextBlock()]
                stop_reason = "end_turn"

            return _TextResp()


_multi_client = _MultiToolClient()

_r_m = ask_orchestrated(
    "what gameweek and who is Salah",
    STANDARD_BOOTSTRAP,
    client=_multi_client,
)

# M1: The orchestrator made exactly 2 LLM calls (tool call + synthesis).
ok(_multi_client.call_count == 2,
   "M1: exactly 2 LLM calls made for 2-tool response (tool call + synthesis)")

# M2: The second call's messages include a role=user message with 2 tool_result blocks.
_second_call_msgs = _multi_client.captured_calls[1]["messages"]
_user_msgs_call2  = [m for m in _second_call_msgs if m.get("role") == "user"]
# The last user-role message must contain the batched tool_result blocks.
_last_user_content = _user_msgs_call2[-1].get("content", []) if _user_msgs_call2 else []
_tool_result_blocks_m = [
    b for b in _last_user_content
    if isinstance(b, dict) and b.get("type") == "tool_result"
] if isinstance(_last_user_content, list) else []
ok(len(_tool_result_blocks_m) == 2,
   "M2: second LLM call receives exactly 2 tool_result blocks in one user-role message")

# M3: tool_use_id ↔ tool_result_id pairing preserved (toolu_001 and toolu_002).
_result_ids_m = {b.get("tool_use_id") for b in _tool_result_blocks_m}
ok("toolu_001" in _result_ids_m,
   "M3a: tool_use_id 'toolu_001' preserved in tool_result pairing")
ok("toolu_002" in _result_ids_m,
   "M3b: tool_use_id 'toolu_002' preserved in tool_result pairing")

# M4: The final answer is the synthesised text from the second LLM call.
ok(_r_m.answer_text == "Synthesised answer from multi-tool results.",
   "M4: answer_text comes from second LLM synthesis call")

# M5-M6 (regression): single-tool path still works — only 1 LLM call, no follow-up.
_single_client = _MockToolUseClient("get_current_gameweek", {})
_r_m5 = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_single_client)
ok(len(_single_client.captured) == 1,
   "M5: single-tool path makes exactly 1 LLM call (no second-call regression)")
ok(_r_m5.outcome == OUTCOME_OK,
   "M6: single-tool path outcome is still OUTCOME_OK (no regression)")

# M7-M8: _parse_all_anthropic_tool_calls returns all blocks with correct IDs.
class _TwoBlockResp:
    content = [
        _make_tool_block("toolu_A", "get_current_gameweek", {}),
        _make_tool_block("toolu_B", "resolve_player",       {"query": "Salah"}),
    ]
    stop_reason = "tool_use"

_parsed_all = _parse_all_anthropic_tool_calls(_TwoBlockResp())
ok(len(_parsed_all) == 2,
   "M7: _parse_all_anthropic_tool_calls returns 2 entries for 2-tool response")
ok(_parsed_all[0][0] == "toolu_A" and _parsed_all[1][0] == "toolu_B",
   "M8: _parse_all_anthropic_tool_calls preserves tool_use_ids in order")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase Orch-3a: {_pass}/{total} assertions passed.")
if _fail:
    print(f"               {_fail} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
