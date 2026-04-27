"""
run_phase_orch2a_tests.py
=========================
Phase Orch-2a: Tool schema registry scaffold.

Validates that:
- All 10 grounded tools are registered with complete schemas.
- Schema names are unique and stable.
- Every schema passes structural validation (validate_tool_schema_shape).
- Required arg lists match what the router/tool-contract backend expects.
- Registry lookup works correctly for known and unknown names.
- to_openai() and to_anthropic() produce well-formed serialisations.
- No runtime regression in respond() for representative intents.
- Phase 9c, 9b, and 9a invariants remain green (spot-checked).

Sections
--------
A  list_tool_schemas()         -- completeness, sort stability, count
B  Name uniqueness and format  -- snake_case, no collisions
C  validate_tool_schema_shape  -- all registered schemas pass
D  Required args               -- match router/tool-contract expectations
E  get_tool_schema()           -- known and unknown lookup
F  to_openai() format          -- OpenAI function-calling wire shape
G  to_anthropic() format       -- Anthropic tool_use wire shape
H  Chip enum values            -- get_chip_advice chip enum completeness
I  No-arg tools                -- get_current_gameweek and get_differential_picks
J  respond() regression        -- representative intents unaffected

Run from packages/fpl-grounded-assistant::

    python run_phase_orch2a_tests.py
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

from fpl_grounded_assistant.tool_schema_registry import (
    ToolSchema,
    list_tool_schemas,
    get_tool_schema,
    validate_tool_schema_shape,
    TOOL_NAMES,
    _REGISTRY,            # white-box: verify internal consistency
    _ALL_SCHEMAS,
)
from fpl_grounded_assistant.dispatcher import _TOOL_TO_INTENT, SUPPORTED_INTENTS
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


# Expected set of tool names (mirrors dispatcher._TOOL_TO_INTENT keys)
_EXPECTED_TOOL_NAMES: frozenset[str] = frozenset(_TOOL_TO_INTENT.keys())

# Expected required args per tool (derived from router.py)
_EXPECTED_REQUIRED: dict[str, set[str]] = {
    "get_current_gameweek":    set(),
    "get_player_summary":      {"query"},
    "resolve_player":          {"query"},
    "get_captain_score":       {"query"},
    "rank_captain_candidates": {"candidates"},
    "compare_players":         {"query_a", "query_b"},
    "get_transfer_advice":     {"query_out", "query_in"},
    "get_chip_advice":         {"chip"},
    "get_player_fixture_run":  {"query"},
    "get_differential_picks":  set(),
}

# Chip enum values that the router recognises (canonical chip names)
_EXPECTED_CHIP_ENUM: set[str] = {
    "triple_captain", "wildcard", "bench_boost", "free_hit",
}


# ---------------------------------------------------------------------------
# Section A: list_tool_schemas() — completeness, sort, count
# ---------------------------------------------------------------------------

print("\n=== A: list_tool_schemas() ===")

names = list_tool_schemas()

ok(isinstance(names, list),         "A1: list_tool_schemas() returns a list")
ok(len(names) == 10,                "A2: exactly 10 tools registered")
ok(names == sorted(names),          "A3: names are sorted alphabetically")
ok(len(set(names)) == len(names),   "A4: no duplicate names in list")

# Every expected tool is present
for tool_name in sorted(_EXPECTED_TOOL_NAMES):
    ok(tool_name in names,
       f"A5-presence: '{tool_name}' in list_tool_schemas()")

# TOOL_NAMES frozenset matches the list
ok(set(names) == set(TOOL_NAMES),   "A6: TOOL_NAMES frozenset matches list")


# ---------------------------------------------------------------------------
# Section B: Name uniqueness and snake_case format
# ---------------------------------------------------------------------------

print("\n=== B: name uniqueness and format ===")

ok(len(_REGISTRY) == 10, "B1: registry dict has 10 entries")

# All names are snake_case (no spaces, no hyphens, non-empty)
for s in _ALL_SCHEMAS:
    ok(
        isinstance(s.name, str) and s.name
        and " " not in s.name and "-" not in s.name,
        f"B2-format: '{s.name}' is snake_case",
    )

# Names in registry match name field on each schema
for s in _ALL_SCHEMAS:
    ok(
        _REGISTRY.get(s.name) is s,
        f"B3-keyed: registry['{s.name}'] is the correct ToolSchema object",
    )


# ---------------------------------------------------------------------------
# Section C: validate_tool_schema_shape — all registered schemas pass
# ---------------------------------------------------------------------------

print("\n=== C: validate_tool_schema_shape() ===")

for s in _ALL_SCHEMAS:
    ok(
        validate_tool_schema_shape(s) is True,
        f"C1-valid: '{s.name}' passes validate_tool_schema_shape()",
    )

# Failing inputs
ok(validate_tool_schema_shape(None)  is False, "C2: None fails validation")
ok(validate_tool_schema_shape({})    is False, "C3: plain dict fails validation")
ok(validate_tool_schema_shape("str") is False, "C4: string fails validation")
ok(validate_tool_schema_shape(42)    is False, "C5: int fails validation")

# Malformed ToolSchema-like objects
_bad_no_name = ToolSchema(name="", description="ok", parameters={"type": "object", "properties": {}, "required": []})
ok(validate_tool_schema_shape(_bad_no_name) is False, "C6: empty name fails")

_bad_space = ToolSchema(name="bad name", description="ok", parameters={"type": "object", "properties": {}, "required": []})
ok(validate_tool_schema_shape(_bad_space) is False, "C7: name with space fails")

_bad_hyphen = ToolSchema(name="bad-name", description="ok", parameters={"type": "object", "properties": {}, "required": []})
ok(validate_tool_schema_shape(_bad_hyphen) is False, "C8: name with hyphen fails")

_bad_desc = ToolSchema(name="tool_name", description="", parameters={"type": "object", "properties": {}, "required": []})
ok(validate_tool_schema_shape(_bad_desc) is False, "C9: empty description fails")

_bad_type = ToolSchema(name="tool_name", description="ok", parameters={"type": "array", "properties": {}, "required": []})
ok(validate_tool_schema_shape(_bad_type) is False, "C10: type != object fails")

_bad_props = ToolSchema(name="tool_name", description="ok", parameters={"type": "object", "properties": None, "required": []})
ok(validate_tool_schema_shape(_bad_props) is False, "C11: properties=None fails")

_bad_req = ToolSchema(name="tool_name", description="ok", parameters={"type": "object", "properties": {}, "required": None})
ok(validate_tool_schema_shape(_bad_req) is False, "C12: required=None fails")


# ---------------------------------------------------------------------------
# Section D: Required args match backend expectations
# ---------------------------------------------------------------------------

print("\n=== D: required args match backend expectations ===")

for tool_name, expected_req in sorted(_EXPECTED_REQUIRED.items()):
    schema = get_tool_schema(tool_name)
    if schema is None:
        ok(False, f"D-schema-present: '{tool_name}' is registered")
        continue

    actual_req = set(schema.parameters.get("required", []))
    ok(
        actual_req == expected_req,
        f"D-required: '{tool_name}' required={sorted(actual_req)} "
        f"(expected {sorted(expected_req)})",
    )

# Parameters that are listed as required must appear in properties
for s in _ALL_SCHEMAS:
    props = s.parameters.get("properties", {})
    required = s.parameters.get("required", [])
    for req_arg in required:
        ok(
            req_arg in props,
            f"D-props: '{s.name}' required arg '{req_arg}' appears in properties",
        )


# ---------------------------------------------------------------------------
# Section E: get_tool_schema() lookup
# ---------------------------------------------------------------------------

print("\n=== E: get_tool_schema() lookup ===")

# Known names return correct ToolSchema
for tool_name in _EXPECTED_TOOL_NAMES:
    result = get_tool_schema(tool_name)
    ok(isinstance(result, ToolSchema),   f"E1-type: get_tool_schema('{tool_name}') returns ToolSchema")
    ok(result is not None and result.name == tool_name,
       f"E2-name: get_tool_schema('{tool_name}').name == '{tool_name}'")

# Unknown names return None
ok(get_tool_schema("nonexistent")       is None, "E3: unknown name returns None")
ok(get_tool_schema("")                  is None, "E4: empty string returns None")
ok(get_tool_schema("GET_CAPTAIN_SCORE") is None, "E5: wrong-case name returns None")

# Return is the same object across calls (identity preserved)
s1 = get_tool_schema("get_captain_score")
s2 = get_tool_schema("get_captain_score")
ok(s1 is s2, "E6: repeated lookups return the same object")


# ---------------------------------------------------------------------------
# Section F: to_openai() wire format
# ---------------------------------------------------------------------------

print("\n=== F: to_openai() format ===")

for s in _ALL_SCHEMAS:
    d = s.to_openai()
    ok(d.get("type") == "function",                             f"F1-type: '{s.name}' to_openai() type == 'function'")
    ok(isinstance(d.get("function"), dict),                     f"F2-func: '{s.name}' to_openai() has 'function' dict")
    ok(d["function"].get("name") == s.name,                    f"F3-name: '{s.name}' to_openai() function.name correct")
    ok(isinstance(d["function"].get("description"), str),      f"F4-desc: '{s.name}' to_openai() description is str")
    ok(isinstance(d["function"].get("parameters"), dict),      f"F5-params: '{s.name}' to_openai() parameters is dict")


# ---------------------------------------------------------------------------
# Section G: to_anthropic() wire format
# ---------------------------------------------------------------------------

print("\n=== G: to_anthropic() format ===")

for s in _ALL_SCHEMAS:
    d = s.to_anthropic()
    ok(d.get("name") == s.name,                                f"G1-name: '{s.name}' to_anthropic() name correct")
    ok(isinstance(d.get("description"), str),                  f"G2-desc: '{s.name}' to_anthropic() description is str")
    ok(d.get("input_schema") is s.parameters,                  f"G3-schema: '{s.name}' to_anthropic() input_schema is parameters dict")
    # No 'type' key at top level — Anthropic uses 'input_schema' not 'type'+'function'
    ok("type" not in d,                                        f"G4-nokey: '{s.name}' to_anthropic() has no 'type' key")


# ---------------------------------------------------------------------------
# Section H: Chip enum values
# ---------------------------------------------------------------------------

print("\n=== H: chip enum values ===")

chip_schema = get_tool_schema("get_chip_advice")
ok(chip_schema is not None,                                    "H1: get_chip_advice schema exists")
chip_prop = chip_schema.parameters["properties"].get("chip", {}) if chip_schema else {}
chip_enum = set(chip_prop.get("enum", []))
ok(chip_enum == _EXPECTED_CHIP_ENUM,
   f"H2: chip enum == {sorted(_EXPECTED_CHIP_ENUM)} (got {sorted(chip_enum)})")
ok(chip_prop.get("type") == "string",                         "H3: chip property type == 'string'")

# Each chip value is in the router's _CHIP_KEYWORDS canonical names
from fpl_grounded_assistant.router import _CHIP_KEYWORDS
_router_chip_canonicals = {canonical for _, canonical in _CHIP_KEYWORDS}
for chip_val in _EXPECTED_CHIP_ENUM:
    ok(chip_val in _router_chip_canonicals,
       f"H4-router: chip enum value '{chip_val}' is a router canonical")


# ---------------------------------------------------------------------------
# Section I: No-arg tools
# ---------------------------------------------------------------------------

print("\n=== I: no-arg tools ===")

for no_arg_tool in ("get_current_gameweek", "get_differential_picks"):
    s = get_tool_schema(no_arg_tool)
    ok(s is not None,                                          f"I1-exists: '{no_arg_tool}' registered")
    ok(s is not None and s.parameters.get("required") == [],  f"I2-required: '{no_arg_tool}' required == []")
    ok(s is not None and s.parameters.get("properties") == {},f"I3-props: '{no_arg_tool}' properties == {{}}")
    ok(s is not None and s.parameters.get("additionalProperties") is False,
       f"I4-addlprops: '{no_arg_tool}' additionalProperties == False")


# ---------------------------------------------------------------------------
# Section J: respond() regression — representative intents
# ---------------------------------------------------------------------------

print("\n=== J: respond() regression ===")

# J1-J2: captain_score
r_cap = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(r_cap.intent  == "captain_score", "J1: captain_score intent unchanged")
ok(r_cap.outcome == "ok",            "J2: captain_score outcome == ok")

# J3-J4: player_summary
r_sum = respond("tell me about Salah", STANDARD_BOOTSTRAP)
ok(r_sum.intent  == "player_summary", "J3: player_summary intent unchanged")
ok(r_sum.outcome == "ok",             "J4: player_summary outcome == ok")

# J5-J6: chip_advice
r_chip = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(r_chip.intent  == "chip_advice", "J5: chip_advice intent unchanged")
ok(r_chip.outcome == "ok",          "J6: chip_advice outcome == ok")

# J7-J8: differential_picks (STANDARD_BOOTSTRAP lacks position score data
# so outcome may be 'error', but routing and supported flag are correct)
r_diff = respond("good differentials", STANDARD_BOOTSTRAP)
ok(r_diff.intent   == "differential_picks", "J7: differential_picks intent unchanged")
ok(r_diff.supported is True,                "J8: differential_picks is supported (routing works)")

# J9-J10: unsupported still unsupported
r_unsup = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(r_unsup.outcome == "unsupported_intent", "J9: unsupported still unsupported")
ok(not r_unsup.supported,                   "J10: unsupported.supported == False")

# J11: registry import did not change SUPPORTED_INTENTS
ok(len(SUPPORTED_INTENTS) == 10,
   f"J11: SUPPORTED_INTENTS still has 10 entries (got {len(SUPPORTED_INTENTS)})")

# J12: registry size matches dispatcher tool count
ok(len(_REGISTRY) == len(_TOOL_TO_INTENT),
   f"J12: registry size ({len(_REGISTRY)}) == _TOOL_TO_INTENT size ({len(_TOOL_TO_INTENT)})")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase Orch-2a: {_pass}/{total} assertions passed.")
if _fail:
    print(f"               {_fail} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
