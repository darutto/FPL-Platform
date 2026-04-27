"""
run_phase_orch3b_tests.py
=========================
Phase Orch-3b: Provider-dispatch parity for ask_orchestrated().

Validates that:
- to_gemini() is present on ToolSchema and produces the correct wire shape.
- _build_tools() returns the correct format for each provider.
- _parse_anthropic_tool_call() extracts (name, args) from an Anthropic response.
- _parse_openai_tool_call() handles JSON-string arguments correctly.
- _parse_gemini_tool_call() handles dict-like args correctly.
- _parse_tool_call() dispatches to the right parser for each explicit provider.
- _parse_tool_call() auto-detects all three shapes when provider=None.
- ask_orchestrated() with provider="openai" succeeds end-to-end.
- ask_orchestrated() with provider="gemini" succeeds end-to-end.
- ask_orchestrated() with provider="anthropic" (explicit) succeeds end-to-end.
- OUTCOME_TOOL_RESULT_ERROR is returned when run_tool returns status != "ok".
- OUTCOME_OK only when run_tool returns status == "ok".
- Error field is None for OUTCOME_OK, non-None for OUTCOME_TOOL_RESULT_ERROR.
- All 7 outcome constants are present and unique.
- Provider constants (PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI) are str.
- Orch-3a regression: Anthropic default path still works without explicit provider.
- Orch-2a regression: ToolSchema still passes validate_tool_schema_shape.
- respond() regression: existing deterministic path is unchanged.

Sections
--------
A  Module and public surface       -- importability, new constants
B  to_gemini() format              -- Gemini function-declaration wire shape
C  _build_tools() format           -- per-provider tool list format
D  Parser unit tests               -- _parse_*_tool_call helpers
E  _parse_tool_call() dispatch     -- explicit and auto-detect modes
F  ask_orchestrated() OpenAI path  -- end-to-end with OpenAI mock
G  ask_orchestrated() Gemini path  -- end-to-end with Gemini mock
H  ask_orchestrated() Anthropic explicit -- end-to-end with explicit provider
I  OUTCOME_TOOL_RESULT_ERROR       -- tool ran, status != "ok"
J  Orch-3a regression              -- default Anthropic path unchanged
K  Orch-2a regression              -- registry + schema validation green
L  respond() regression            -- deterministic path unchanged

Run from packages/fpl-grounded-assistant::

    python run_phase_orch3b_tests.py
"""
from __future__ import annotations

import json
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
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    DEFAULT_ORCH_MODEL,
    _ORCH_SYSTEM_SUFFIX,
    _ALL_OUTCOMES,
    _ALL_PROVIDERS,
    _build_tools,
    _parse_anthropic_tool_call,
    _parse_openai_tool_call,
    _parse_gemini_tool_call,
    _parse_tool_call,
)
from fpl_grounded_assistant.tool_schema_registry import (
    ToolSchema,
    list_tool_schemas,
    get_tool_schema,
    validate_tool_schema_shape,
    TOOL_NAMES,
    _ALL_SCHEMAS,
)
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

class _AnthropicToolClient:
    """Anthropic-shaped tool_use response mock."""

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
            id    = "toolu_ant_001"
            name  = _name
            input = _input

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


class _OpenAIToolClient:
    """OpenAI function-calling response mock.

    Arguments are serialised as a JSON string (matching the real OpenAI SDK).
    """

    def __init__(self, tool_name: str, tool_args: dict) -> None:
        self._tool_name = tool_name
        self._tool_args = tool_args
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
        _args_str = json.dumps(self._tool_args)  # JSON string — key difference

        class _Function:
            name      = _name
            arguments = _args_str

        class _ToolCall:
            id       = "call_oai_001"
            type     = "function"
            function = _Function()

        class _Message:
            tool_calls = [_ToolCall()]

        class _Choice:
            message       = _Message()
            finish_reason = "tool_calls"

        class _Response:
            choices = [_Choice()]

        return _Response()


class _GeminiToolClient:
    """Gemini function-call response mock.

    Args are dict-like (mapping), not a JSON string.
    """

    def __init__(self, tool_name: str, tool_args: dict) -> None:
        self._tool_name = tool_name
        self._tool_args = tool_args
        self.messages = self
        self.captured: list[dict] = []

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        self.captured.append({
            "model":    model,
            "system":   system,
            "tools":    tools,
            "messages": messages,
        })
        _name = self._tool_name
        _args = dict(self._tool_args)

        class _FunctionCall:
            name = _name
            args = _args

        class _Part:
            function_call = _FunctionCall()

        class _Content:
            parts = [_Part()]

        class _Candidate:
            content = _Content()

        class _Response:
            candidates = [_Candidate()]

        return _Response()


class _NoToolClient:
    """Plain text response with no tool call."""

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


# ---------------------------------------------------------------------------
# Section A: Module and public surface
# ---------------------------------------------------------------------------

print("\n=== A: module and public surface ===")

ok(callable(ask_orchestrated),                  "A1: ask_orchestrated is callable")
ok(isinstance(OUTCOME_TOOL_RESULT_ERROR, str),  "A2: OUTCOME_TOOL_RESULT_ERROR is str")
ok(OUTCOME_TOOL_RESULT_ERROR in _ALL_OUTCOMES,  "A3: OUTCOME_TOOL_RESULT_ERROR in _ALL_OUTCOMES")
ok(len(_ALL_OUTCOMES) == 7,                     "A4: _ALL_OUTCOMES has 7 values")
ok(len(set(_ALL_OUTCOMES)) == 7,                "A5: all outcome constants unique")
ok(isinstance(PROVIDER_ANTHROPIC, str),         "A6: PROVIDER_ANTHROPIC is str")
ok(isinstance(PROVIDER_OPENAI, str),            "A7: PROVIDER_OPENAI is str")
ok(isinstance(PROVIDER_GEMINI, str),            "A8: PROVIDER_GEMINI is str")
ok(len(_ALL_PROVIDERS) == 3,                    "A9: _ALL_PROVIDERS has 3 values")
ok(PROVIDER_ANTHROPIC in _ALL_PROVIDERS,        "A10: PROVIDER_ANTHROPIC in _ALL_PROVIDERS")
ok(PROVIDER_OPENAI    in _ALL_PROVIDERS,        "A11: PROVIDER_OPENAI in _ALL_PROVIDERS")
ok(PROVIDER_GEMINI    in _ALL_PROVIDERS,        "A12: PROVIDER_GEMINI in _ALL_PROVIDERS")
ok(callable(_build_tools),                      "A13: _build_tools is callable")
ok(callable(_parse_anthropic_tool_call),        "A14: _parse_anthropic_tool_call is callable")
ok(callable(_parse_openai_tool_call),           "A15: _parse_openai_tool_call is callable")
ok(callable(_parse_gemini_tool_call),           "A16: _parse_gemini_tool_call is callable")
ok(callable(_parse_tool_call),                  "A17: _parse_tool_call is callable")

# All 7 outcomes are distinct strings
_all_out_list = [
    OUTCOME_OK, OUTCOME_NO_CLIENT, OUTCOME_LLM_ERROR, OUTCOME_NO_TOOL,
    OUTCOME_UNKNOWN_TOOL, OUTCOME_TOOL_ERROR, OUTCOME_TOOL_RESULT_ERROR,
]
ok(len(set(_all_out_list)) == 7,               "A18: all 7 outcome string values are distinct")


# ---------------------------------------------------------------------------
# Section B: to_gemini() format
# ---------------------------------------------------------------------------

print("\n=== B: to_gemini() format ===")

for s in _ALL_SCHEMAS:
    d = s.to_gemini()
    ok(d.get("name") == s.name,
       f"B1-name: '{s.name}' to_gemini() name correct")
    ok(isinstance(d.get("description"), str) and d["description"],
       f"B2-desc: '{s.name}' to_gemini() description is non-empty str")
    ok(d.get("parameters") is s.parameters,
       f"B3-params: '{s.name}' to_gemini() parameters is the schema's parameters dict")
    # No 'input_schema' or 'type'+'function' wrapper — Gemini uses 'parameters' directly
    ok("input_schema" not in d,
       f"B4-no-input-schema: '{s.name}' to_gemini() has no 'input_schema' key")
    ok("type" not in d,
       f"B5-no-type: '{s.name}' to_gemini() has no top-level 'type' key")

# to_gemini() keys: name, description, parameters
_sample = _ALL_SCHEMAS[0]
ok(set(_sample.to_gemini().keys()) == {"name", "description", "parameters"},
   "B6: to_gemini() has exactly 3 keys: name, description, parameters")


# ---------------------------------------------------------------------------
# Section C: _build_tools() format
# ---------------------------------------------------------------------------

print("\n=== C: _build_tools() format ===")

# Anthropic (default — None)
_tools_ant_none = _build_tools(None)
ok(isinstance(_tools_ant_none, list),           "C1: _build_tools(None) returns list")
ok(len(_tools_ant_none) == 10,                  "C2: _build_tools(None) has 10 entries")
ok("input_schema" in _tools_ant_none[0],        "C3: _build_tools(None) -> Anthropic format")
ok("type" not in _tools_ant_none[0],            "C4: _build_tools(None) no 'type' at top level")

# Anthropic (explicit)
_tools_ant_expl = _build_tools(PROVIDER_ANTHROPIC)
ok(len(_tools_ant_expl) == 10,                  "C5: _build_tools(ANTHROPIC) has 10 entries")
ok("input_schema" in _tools_ant_expl[0],        "C6: _build_tools(ANTHROPIC) -> Anthropic format")

# OpenAI
_tools_oai = _build_tools(PROVIDER_OPENAI)
ok(isinstance(_tools_oai, list),                "C7: _build_tools(OPENAI) returns list")
ok(len(_tools_oai) == 10,                       "C8: _build_tools(OPENAI) has 10 entries")
ok(_tools_oai[0].get("type") == "function",     "C9: _build_tools(OPENAI) entries have type=='function'")
ok("function" in _tools_oai[0],                 "C10: _build_tools(OPENAI) entries have 'function' key")

# Gemini
_tools_gem = _build_tools(PROVIDER_GEMINI)
ok(isinstance(_tools_gem, list),                "C11: _build_tools(GEMINI) returns list")
ok(len(_tools_gem) == 1,                        "C12: _build_tools(GEMINI) returns 1 wrapper dict")
_decls = _tools_gem[0].get("function_declarations", [])
ok(len(_decls) == 10,                           "C13: Gemini wrapper has 10 function_declarations")
ok(_decls[0].get("name") in TOOL_NAMES,         "C14: first Gemini declaration has valid tool name")
ok("parameters" in _decls[0],                   "C15: Gemini declaration has 'parameters' key")
ok("input_schema" not in _decls[0],             "C16: Gemini declaration has no 'input_schema'")


# ---------------------------------------------------------------------------
# Section D: Parser unit tests
# ---------------------------------------------------------------------------

print("\n=== D: parser unit tests ===")

# D1-D5: _parse_anthropic_tool_call
def _make_ant_response(tool_name: str, tool_input: dict) -> object:
    """Build an Anthropic-shaped response with a tool_use block."""
    class _Block:
        pass
    class _Resp:
        pass
    blk = object.__new__(_Block)
    blk.type  = "tool_use"
    blk.name  = tool_name
    blk.input = tool_input
    resp = object.__new__(_Resp)
    resp.content = [blk]
    return resp

def _make_ant_text_response() -> object:
    """Build an Anthropic-shaped response with no tool_use block."""
    class _TextBlk:
        pass
    class _Resp:
        pass
    blk = object.__new__(_TextBlk)
    blk.type = "text"
    blk.text = "I cannot help."
    resp = object.__new__(_Resp)
    resp.content = [blk]
    return resp

_ant_parsed = _parse_anthropic_tool_call(_make_ant_response("get_captain_score", {"query": "Haaland"}))
ok(_ant_parsed is not None,                     "D1: Anthropic parser returns non-None")
ok(_ant_parsed[0] == "get_captain_score",       "D2: Anthropic parser extracts tool name")
ok(_ant_parsed[1] == {"query": "Haaland"},      "D3: Anthropic parser extracts tool args")

class _AntNoToolResponse:
    class _TextBlock:
        type = "text"
        text = "hello"
    content = [_TextBlock()]

ok(_parse_anthropic_tool_call(_make_ant_text_response()) is None,
   "D4: Anthropic parser returns None when no tool_use block")
ok(_parse_anthropic_tool_call(object()) is None,
   "D5: Anthropic parser returns None for unexpected object")

# D6-D11: _parse_openai_tool_call (arguments is a JSON string)
def _make_oai_response(tool_name: str, arguments) -> object:
    """Build an OpenAI-shaped response object."""
    class _Fn:
        name      = tool_name
        args_val  = arguments
    class _TC:
        pass
    class _Msg:
        pass
    class _Ch:
        pass
    class _Resp:
        pass
    fn = _Fn()
    fn.name = tool_name
    fn.arguments = arguments
    tc = object.__new__(_TC)
    tc.__class__ = _TC
    tc.function = fn
    msg = object.__new__(_Msg)
    msg.tool_calls = [tc]
    ch = object.__new__(_Ch)
    ch.message = msg
    resp = object.__new__(_Resp)
    resp.choices = [ch]
    return resp

_oai_resp = _make_oai_response("resolve_player", json.dumps({"query": "Salah"}))
_oai_parsed = _parse_openai_tool_call(_oai_resp)
ok(_oai_parsed is not None,                     "D6: OpenAI parser returns non-None")
ok(_oai_parsed[0] == "resolve_player",          "D7: OpenAI parser extracts tool name")
ok(_oai_parsed[1] == {"query": "Salah"},        "D8: OpenAI parser deserialises JSON string args")

# OpenAI with dict args (not JSON string — also supported)
_oai_dict_resp = _make_oai_response("get_current_gameweek", {})
_oai_dict_parsed = _parse_openai_tool_call(_oai_dict_resp)
ok(_oai_dict_parsed is not None,                "D9: OpenAI parser handles dict args too")
ok(_oai_dict_parsed[1] == {},                   "D10: OpenAI dict args parsed to empty dict")

ok(_parse_openai_tool_call(object()) is None,   "D11: OpenAI parser returns None for unexpected object")

# D12-D17: _parse_gemini_tool_call
def _make_gemini_response(tool_name: str, args) -> object:
    """Build a Gemini-shaped response object."""
    class _FC:
        pass
    class _Part:
        pass
    class _Cont:
        pass
    class _Cand:
        pass
    class _Resp:
        pass
    fc = object.__new__(_FC)
    fc.name = tool_name
    fc.args = args
    part = object.__new__(_Part)
    part.function_call = fc
    cont = object.__new__(_Cont)
    cont.parts = [part]
    cand = object.__new__(_Cand)
    cand.content = cont
    resp = object.__new__(_Resp)
    resp.candidates = [cand]
    return resp

_gem_resp = _make_gemini_response("get_player_summary", {"query": "Salah"})
_gem_parsed = _parse_gemini_tool_call(_gem_resp)
ok(_gem_parsed is not None,                     "D12: Gemini parser returns non-None")
ok(_gem_parsed[0] == "get_player_summary",      "D13: Gemini parser extracts tool name")
ok(_gem_parsed[1] == {"query": "Salah"},        "D14: Gemini parser extracts args as dict")

# Gemini with None args -> empty dict
_gem_none_resp = _make_gemini_response("get_current_gameweek", None)
_gem_none_parsed = _parse_gemini_tool_call(_gem_none_resp)
ok(_gem_none_parsed is not None,                "D15: Gemini parser handles None args")
ok(_gem_none_parsed[1] == {},                   "D16: Gemini None args -> empty dict")

ok(_parse_gemini_tool_call(object()) is None,   "D17: Gemini parser returns None for unexpected object")


# ---------------------------------------------------------------------------
# Section E: _parse_tool_call() dispatch
# ---------------------------------------------------------------------------

print("\n=== E: _parse_tool_call() dispatch ===")

# Explicit Anthropic
_parsed_ant = _parse_tool_call(
    _make_ant_response("get_captain_score", {"query": "Haaland"}), PROVIDER_ANTHROPIC)
ok(_parsed_ant is not None,                     "E1: _parse_tool_call(ANT) returns non-None")
ok(_parsed_ant[0] == "get_captain_score",       "E2: _parse_tool_call(ANT) correct name")

# Explicit OpenAI
_parsed_oai = _parse_tool_call(
    _make_oai_response("resolve_player", json.dumps({"query": "Salah"})), PROVIDER_OPENAI)
ok(_parsed_oai is not None,                     "E3: _parse_tool_call(OAI) returns non-None")
ok(_parsed_oai[0] == "resolve_player",          "E4: _parse_tool_call(OAI) correct name")

# Explicit Gemini
_parsed_gem = _parse_tool_call(
    _make_gemini_response("get_player_summary", {"query": "Salah"}), PROVIDER_GEMINI)
ok(_parsed_gem is not None,                     "E5: _parse_tool_call(GEM) returns non-None")
ok(_parsed_gem[0] == "get_player_summary",      "E6: _parse_tool_call(GEM) correct name")

# Auto-detect: Anthropic response (tool_use block) with provider=None
_parsed_auto_ant = _parse_tool_call(
    _make_ant_response("get_captain_score", {"query": "Haaland"}), None)
ok(_parsed_auto_ant is not None,                "E7: auto-detect finds Anthropic tool_use block")
ok(_parsed_auto_ant[0] == "get_captain_score",  "E8: auto-detect Anthropic name correct")

# Auto-detect: OpenAI response with provider=None
_parsed_auto_oai = _parse_tool_call(
    _make_oai_response("resolve_player", json.dumps({"query": "Salah"})), None)
ok(_parsed_auto_oai is not None,                "E9: auto-detect finds OpenAI tool call")
ok(_parsed_auto_oai[0] == "resolve_player",     "E10: auto-detect OpenAI name correct")

# Auto-detect: Gemini response with provider=None
_parsed_auto_gem = _parse_tool_call(
    _make_gemini_response("get_player_summary", {"query": "Salah"}), None)
ok(_parsed_auto_gem is not None,                "E11: auto-detect finds Gemini function_call")
ok(_parsed_auto_gem[0] == "get_player_summary", "E12: auto-detect Gemini name correct")

# Auto-detect: no tool in response -> None
class _EmptyResponse:
    content    = []
    choices    = []
    candidates = []

ok(_parse_tool_call(_EmptyResponse(), None) is None,
   "E13: auto-detect returns None when no tool call found")


# ---------------------------------------------------------------------------
# Section F: ask_orchestrated() OpenAI path
# ---------------------------------------------------------------------------

print("\n=== F: ask_orchestrated() OpenAI path ===")

_cli_oai = _OpenAIToolClient("get_current_gameweek", {})
_r_f = ask_orchestrated(
    "what gameweek is it",
    STANDARD_BOOTSTRAP,
    client=_cli_oai,
    provider=PROVIDER_OPENAI,
)

ok(_r_f.outcome == OUTCOME_OK,                  "F1: OpenAI path -> OUTCOME_OK")
ok(_r_f.tool_chosen == "get_current_gameweek",  "F2: OpenAI path tool_chosen correct")
ok(isinstance(_r_f.tool_output, dict),          "F3: OpenAI path tool_output is dict")
ok(_r_f.tool_output.get("status") == "ok",      "F4: OpenAI path tool_output.status == 'ok'")
ok(isinstance(_r_f.answer_text, str) and _r_f.answer_text,
   "F5: OpenAI path answer_text is non-empty str")
ok(_r_f.llm_used is True,                       "F6: OpenAI path llm_used == True")
ok(_r_f.error is None,                          "F7: OpenAI path error is None")

# Tool list passed was in OpenAI format
ok(len(_cli_oai.captured) == 1,                 "F8: exactly 1 LLM call made (OpenAI)")
_oai_tools = _cli_oai.captured[0]["tools"]
ok(isinstance(_oai_tools, list),                "F9: OpenAI tools is a list")
ok(len(_oai_tools) == 10,                       "F10: OpenAI tools has 10 entries")
ok(_oai_tools[0].get("type") == "function",     "F11: OpenAI tools[0].type == 'function'")

# OpenAI path with captain score (has required arg)
_cli_oai2 = _OpenAIToolClient("get_captain_score", {"query": "Haaland"})
_r_f2 = ask_orchestrated(
    "should I captain Haaland",
    STANDARD_BOOTSTRAP,
    client=_cli_oai2,
    provider=PROVIDER_OPENAI,
)
ok(_r_f2.outcome == OUTCOME_OK,                 "F12: OpenAI captain_score -> OUTCOME_OK")
ok(_r_f2.tool_args.get("query") == "Haaland",  "F13: OpenAI tool_args.query preserved")
ok(_r_f2.tool_output.get("status") == "ok",    "F14: OpenAI captain_score output.status == 'ok'")


# ---------------------------------------------------------------------------
# Section G: ask_orchestrated() Gemini path
# ---------------------------------------------------------------------------

print("\n=== G: ask_orchestrated() Gemini path ===")

_cli_gem = _GeminiToolClient("get_current_gameweek", {})
_r_g = ask_orchestrated(
    "what gameweek is it",
    STANDARD_BOOTSTRAP,
    client=_cli_gem,
    provider=PROVIDER_GEMINI,
)

ok(_r_g.outcome == OUTCOME_OK,                  "G1: Gemini path -> OUTCOME_OK")
ok(_r_g.tool_chosen == "get_current_gameweek",  "G2: Gemini path tool_chosen correct")
ok(_r_g.tool_output.get("status") == "ok",      "G3: Gemini path tool_output.status == 'ok'")
ok(isinstance(_r_g.answer_text, str) and _r_g.answer_text,
   "G4: Gemini path answer_text is non-empty str")
ok(_r_g.llm_used is True,                       "G5: Gemini path llm_used == True")
ok(_r_g.error is None,                          "G6: Gemini path error is None")

# Tool list passed was in Gemini format (one wrapper dict)
ok(len(_cli_gem.captured) == 1,                 "G7: exactly 1 LLM call made (Gemini)")
_gem_tools = _cli_gem.captured[0]["tools"]
ok(isinstance(_gem_tools, list),                "G8: Gemini tools is a list")
ok(len(_gem_tools) == 1,                        "G9: Gemini tools has 1 wrapper entry")
ok("function_declarations" in _gem_tools[0],    "G10: Gemini tools has function_declarations")
ok(len(_gem_tools[0]["function_declarations"]) == 10,
   "G11: Gemini function_declarations has 10 entries")

# Gemini path with player query
_cli_gem2 = _GeminiToolClient("resolve_player", {"query": "Salah"})
_r_g2 = ask_orchestrated(
    "who is Salah",
    STANDARD_BOOTSTRAP,
    client=_cli_gem2,
    provider=PROVIDER_GEMINI,
)
ok(_r_g2.outcome == OUTCOME_OK,                 "G12: Gemini resolve_player -> OUTCOME_OK")
ok(_r_g2.tool_args.get("query") == "Salah",    "G13: Gemini tool_args.query preserved")
ok(_r_g2.tool_output.get("status") == "ok",    "G14: Gemini resolve_player output.status == 'ok'")


# ---------------------------------------------------------------------------
# Section H: ask_orchestrated() Anthropic explicit path
# ---------------------------------------------------------------------------

print("\n=== H: ask_orchestrated() Anthropic explicit path ===")

_cli_ant = _AnthropicToolClient("get_current_gameweek", {})
_r_h = ask_orchestrated(
    "what gameweek is it",
    STANDARD_BOOTSTRAP,
    client=_cli_ant,
    provider=PROVIDER_ANTHROPIC,
)

ok(_r_h.outcome == OUTCOME_OK,                  "H1: Anthropic explicit path -> OUTCOME_OK")
ok(_r_h.tool_chosen == "get_current_gameweek",  "H2: Anthropic explicit tool_chosen correct")
ok(_r_h.tool_output.get("status") == "ok",      "H3: Anthropic explicit output.status == 'ok'")
ok(_r_h.error is None,                          "H4: Anthropic explicit error is None")

# Tool list passed was in Anthropic format
_ant_tools = _cli_ant.captured[0]["tools"]
ok("input_schema" in _ant_tools[0],             "H5: Anthropic explicit tools in Anthropic format")
ok("type" not in _ant_tools[0],                 "H6: Anthropic explicit tools no 'type' at top level")


# ---------------------------------------------------------------------------
# Section I: OUTCOME_TOOL_RESULT_ERROR
# ---------------------------------------------------------------------------

print("\n=== I: OUTCOME_TOOL_RESULT_ERROR ===")

# Missing required arg -> run_tool returns status="error"
_cli_missing = _AnthropicToolClient("get_captain_score", {})  # missing "query"
_r_i1 = ask_orchestrated(
    "captain score",
    STANDARD_BOOTSTRAP,
    client=_cli_missing,
    provider=PROVIDER_ANTHROPIC,
)
ok(_r_i1.outcome == OUTCOME_TOOL_RESULT_ERROR,  "I1: missing arg -> OUTCOME_TOOL_RESULT_ERROR")
ok(_r_i1.tool_chosen == "get_captain_score",    "I2: tool_chosen still set on tool_result_error")
ok(_r_i1.tool_output.get("status") == "error",  "I3: tool_output.status == 'error'")
ok(_r_i1.tool_output.get("code") == "missing_argument",
   "I4: tool_output.code == 'missing_argument'")
ok(_r_i1.error is not None,                     "I5: error field populated on tool_result_error")
ok("error" in (_r_i1.error or ""),              "I6: error message references error status")
ok(isinstance(_r_i1.answer_text, str) and _r_i1.answer_text,
   "I7: answer_text non-empty even on tool_result_error")
ok(_r_i1.llm_used is True,                      "I8: llm_used == True on tool_result_error")

# Same via OpenAI path
_cli_missing_oai = _OpenAIToolClient("get_captain_score", {})
_r_i2 = ask_orchestrated(
    "captain score",
    STANDARD_BOOTSTRAP,
    client=_cli_missing_oai,
    provider=PROVIDER_OPENAI,
)
ok(_r_i2.outcome == OUTCOME_TOOL_RESULT_ERROR,  "I9: OpenAI missing arg -> OUTCOME_TOOL_RESULT_ERROR")

# Same via Gemini path
_cli_missing_gem = _GeminiToolClient("get_captain_score", {})
_r_i3 = ask_orchestrated(
    "captain score",
    STANDARD_BOOTSTRAP,
    client=_cli_missing_gem,
    provider=PROVIDER_GEMINI,
)
ok(_r_i3.outcome == OUTCOME_TOOL_RESULT_ERROR,  "I10: Gemini missing arg -> OUTCOME_TOOL_RESULT_ERROR")

# OUTCOME_OK only when status == "ok"
_cli_ok = _AnthropicToolClient("get_current_gameweek", {})
_r_i4 = ask_orchestrated("what gw", STANDARD_BOOTSTRAP, client=_cli_ok)
ok(_r_i4.outcome == OUTCOME_OK,                 "I11: status=='ok' -> OUTCOME_OK")
ok(_r_i4.error is None,                         "I12: error is None when OUTCOME_OK")

# OUTCOME_TOOL_RESULT_ERROR outcome is in _ALL_OUTCOMES
ok(OUTCOME_TOOL_RESULT_ERROR in _ALL_OUTCOMES,  "I13: OUTCOME_TOOL_RESULT_ERROR in _ALL_OUTCOMES")


# ---------------------------------------------------------------------------
# Section J: Orch-3a regression (default Anthropic path unchanged)
# ---------------------------------------------------------------------------

print("\n=== J: Orch-3a regression ===")

# Default provider=None should behave identically to explicit Anthropic
_cli_j1 = _AnthropicToolClient("get_current_gameweek", {})
_r_j1 = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP, client=_cli_j1)
ok(_r_j1.outcome == OUTCOME_OK,                 "J1: default (None) provider -> OUTCOME_OK")
ok(_r_j1.tool_chosen == "get_current_gameweek", "J2: default provider tool_chosen correct")

_cli_j2 = _AnthropicToolClient("get_captain_score", {"query": "Haaland"})
_r_j2 = ask_orchestrated("captain Haaland", STANDARD_BOOTSTRAP, client=_cli_j2)
ok(_r_j2.outcome == OUTCOME_OK,                 "J3: default captain_score -> OUTCOME_OK")
ok(_r_j2.tool_output.get("status") == "ok",    "J4: default captain_score status == 'ok'")

# Default tool list format is Anthropic
_cli_j3 = _AnthropicToolClient("get_current_gameweek", {})
ask_orchestrated("gw", STANDARD_BOOTSTRAP, client=_cli_j3)
_j3_tools = _cli_j3.captured[0]["tools"]
ok("input_schema" in _j3_tools[0],             "J5: default tool format is Anthropic (input_schema)")

# No-client fallback still works
_saved = os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    _r_j_no = ask_orchestrated("what gameweek", STANDARD_BOOTSTRAP)
    ok(_r_j_no.outcome == OUTCOME_NO_CLIENT,    "J6: no client -> OUTCOME_NO_CLIENT")
    ok(_r_j_no.llm_used is False,               "J7: llm_used == False (no client)")
except Exception as exc:
    ok(False, f"J6: ask_orchestrated raised: {exc}")
    ok(False, "J7: (skipped)")
finally:
    if _saved is not None:
        os.environ["ANTHROPIC_API_KEY"] = _saved

# Unknown tool still returns OUTCOME_UNKNOWN_TOOL
_cli_unk = _AnthropicToolClient("totally_unknown_tool", {})
_r_unk = ask_orchestrated("test", STANDARD_BOOTSTRAP, client=_cli_unk)
ok(_r_unk.outcome == OUTCOME_UNKNOWN_TOOL,      "J8: unknown tool -> OUTCOME_UNKNOWN_TOOL")

# No tool in response -> OUTCOME_NO_TOOL
_cli_notool = _NoToolClient()
_r_notool = ask_orchestrated("test", STANDARD_BOOTSTRAP, client=_cli_notool)
ok(_r_notool.outcome == OUTCOME_NO_TOOL,        "J9: no tool_use -> OUTCOME_NO_TOOL")


# ---------------------------------------------------------------------------
# Section K: Orch-2a regression
# ---------------------------------------------------------------------------

print("\n=== K: Orch-2a regression ===")

_names = list_tool_schemas()
ok(len(_names) == 10,                           "K1: 10 tools in registry")
ok(_names == sorted(_names),                    "K2: names sorted")

for _s in _ALL_SCHEMAS:
    ok(validate_tool_schema_shape(_s),
       f"K3-valid: '{_s.name}' still passes validate_tool_schema_shape()")

ok(get_tool_schema("get_captain_score") is not None,
   "K4: get_captain_score lookup ok")
ok(get_tool_schema("nonexistent") is None,      "K5: unknown name returns None")

# to_gemini() does not break validate_tool_schema_shape (shape validator ignores method)
for _s2 in _ALL_SCHEMAS:
    ok(validate_tool_schema_shape(_s2) is True,
       f"K6-gemini-compat: '{_s2.name}' validates after adding to_gemini()")


# ---------------------------------------------------------------------------
# Section L: respond() regression
# ---------------------------------------------------------------------------

print("\n=== L: respond() regression ===")

_r_l1 = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(_r_l1.intent  == "captain_score",            "L1: captain_score intent unchanged")
ok(_r_l1.outcome == "ok",                       "L2: captain_score outcome unchanged")

_r_l2 = respond("tell me about Salah", STANDARD_BOOTSTRAP)
ok(_r_l2.intent  == "player_summary",           "L3: player_summary intent unchanged")
ok(_r_l2.outcome == "ok",                       "L4: player_summary outcome unchanged")

_r_l3 = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(_r_l3.intent  == "chip_advice",              "L5: chip_advice intent unchanged")
ok(_r_l3.outcome == "ok",                       "L6: chip_advice outcome unchanged")

_r_l4 = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(_r_l4.outcome == "unsupported_intent",       "L7: unsupported still unsupported")
ok(not _r_l4.supported,                         "L8: unsupported.supported == False")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase Orch-3b: {_pass}/{total} assertions passed.")
if _fail:
    print(f"               {_fail} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
