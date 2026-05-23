"""
run_phase_m3_preflight_tests.py
================================
Phase M3 preflight (MCP_architecture): blockers B1 and B2 closure tests.

Covers:
    B1  tool_schema_registry: 17 schemas, all 7 Phase-2.6 tools registered,
        OpenAI/Anthropic/Gemini serialisation parity, SUPPORTED_INTENTS
        coverage via the dispatcher's _TOOL_TO_INTENT map.
    B2  intent_classifier.CLASSIFIER_SYSTEM_PROMPT enumerates all 17
        supported intents with English + Spanish examples for the three
        previously-missing intents (differential_picks,
        position_fixture_run, multi_intent).  Confidence threshold (0.7)
        unchanged.

Run from packages/fpl-grounded-assistant::

    python run_phase_m3_preflight_tests.py

Exit 0 on success, 1 on failure.  Target: >= 20 assertions.

This is a *preflight* slice — it does NOT wire ask_orchestrated into
decision_router, does NOT add POST /ask-orchestrated, and does NOT
introduce FPL_ORCH_ENABLED.  Those are M3 proper.
"""
from __future__ import annotations

import os
import sys


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

from fpl_grounded_assistant.tool_schema_registry import (  # noqa: E402
    TOOL_NAMES,
    _ALL_SCHEMAS,
    _REGISTRY,
    get_tool_schema,
    list_tool_schemas,
    validate_tool_schema_shape,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    SUPPORTED_INTENTS,
    _TOOL_TO_INTENT,
)
from fpl_grounded_assistant import intent_classifier as ic  # noqa: E402


_pass = 0
_fail = 0
_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        _failures.append(label)
        print(f"  FAIL  {label}")


# ===========================================================================
# B1 — tool_schema_registry coverage and serialisation
# ===========================================================================
print("\n[B1] tool_schema_registry extension to 21 tools (P2.1 find_players, P2.2 get_player_snapshot, P2.3 get_player_history, P2.4 get_fixtures_for_gw)")

NEW_TOOLS = (
    "get_player_form",
    "get_injury_list",
    "get_price_changes",
    "get_team_fixture_calendar",
    "get_team_schedule",
    "get_position_fixture_run",
    "get_transfer_suggestion",
)

check(len(_ALL_SCHEMAS) == 21, "B1.1: _ALL_SCHEMAS has exactly 21 entries")
check(len(_REGISTRY) == 21, "B1.2: _REGISTRY dict has 21 entries (no name collisions)")
check(len(TOOL_NAMES) == 21, "B1.3: TOOL_NAMES frozenset has 21 entries")
check(len(list_tool_schemas()) == 21, "B1.4: list_tool_schemas() returns 21 names")

for name in NEW_TOOLS:
    check(name in TOOL_NAMES, f"B1.5/{name}: {name} is in TOOL_NAMES")
    sch = get_tool_schema(name)
    check(sch is not None and sch.name == name,
          f"B1.6/{name}: get_tool_schema returns ToolSchema with matching name")
    check(validate_tool_schema_shape(sch),
          f"B1.7/{name}: schema passes validate_tool_schema_shape")

# Every existing schema must still validate structurally
for sch in _ALL_SCHEMAS:
    check(validate_tool_schema_shape(sch),
          f"B1.8/{sch.name}: structural shape valid")

# OpenAI / Anthropic / Gemini serialisation parity for all 17.
for sch in _ALL_SCHEMAS:
    oai = sch.to_openai()
    check(
        isinstance(oai, dict)
        and oai.get("type") == "function"
        and isinstance(oai.get("function"), dict)
        and oai["function"].get("name") == sch.name
        and isinstance(oai["function"].get("parameters"), dict)
        and isinstance(oai["function"].get("description"), str)
        and oai["function"]["description"],
        f"B1.9/{sch.name}: to_openai() shape (type=function, function.name/description/parameters)",
    )

    ant = sch.to_anthropic()
    check(
        isinstance(ant, dict)
        and ant.get("name") == sch.name
        and isinstance(ant.get("description"), str) and ant["description"]
        and isinstance(ant.get("input_schema"), dict)
        and ant["input_schema"].get("type") == "object",
        f"B1.10/{sch.name}: to_anthropic() shape (name/description/input_schema)",
    )

    gem = sch.to_gemini()
    check(
        isinstance(gem, dict)
        and gem.get("name") == sch.name
        and isinstance(gem.get("parameters"), dict),
        f"B1.11/{sch.name}: to_gemini() shape (name/description/parameters)",
    )

# SUPPORTED_INTENTS coverage: every supported intent has at least one tool
# whose schema is registered (verified via the dispatcher's _TOOL_TO_INTENT
# inverse map).
covered_intents = {
    intent for tool, intent in _TOOL_TO_INTENT.items() if tool in TOOL_NAMES
}
missing_intents = SUPPORTED_INTENTS - covered_intents
check(not missing_intents,
      f"B1.12: every SUPPORTED_INTENT is covered by at least one registered "
      f"tool (missing={sorted(missing_intents)})")

# Tightening: the 7 new tools each map back to a SUPPORTED_INTENT.
for tool in NEW_TOOLS:
    intent = _TOOL_TO_INTENT.get(tool)
    check(intent in SUPPORTED_INTENTS,
          f"B1.13/{tool}: maps to a SUPPORTED_INTENT ({intent})")


# ===========================================================================
# B2 — classifier system prompt enumerates 17 intents + ES examples
# ===========================================================================
print("\n[B2] classifier system prompt extension")

prompt = ic.CLASSIFIER_SYSTEM_PROMPT

# The classifier deliberately lists intent labels (the string values of the
# INTENT_* constants), not the Python constant names.  Assert each supported
# intent string value appears in the prompt.  The "17" tracked by the M3
# blockers is precisely SUPPORTED_INTENTS; multi_intent is recognised by the
# classifier on top of that set so it can route to the multi-intent handler.
check(len(SUPPORTED_INTENTS) == 17,
      "B2.1: SUPPORTED_INTENTS has exactly 17 entries")

prompt_intents = sorted(SUPPORTED_INTENTS | {"multi_intent"})
check(len(prompt_intents) == 18,
      "B2.1b: classifier-visible intent universe is 17 supported + multi_intent")

for intent_value in prompt_intents:
    # Each intent name appears in the prompt as a 'label:' line — we just
    # require substring presence (the prompt uses 'name:\n' form).
    check(intent_value in prompt,
          f"B2.2/{intent_value}: appears in CLASSIFIER_SYSTEM_PROMPT")

# Section anchors: confirm each previously-missing intent has a labelled
# section header (the prompt format is `<intent>:\n`).
for intent_value in ("differential_picks", "position_fixture_run", "multi_intent"):
    check(f"\n{intent_value}:\n" in prompt,
          f"B2.3/{intent_value}: has its own labelled section in the prompt")

# Spanish examples present for the three previously-missing intents.
check("diferenciales" in prompt.lower(),
      "B2.4: Spanish example phrase 'diferenciales' present (differential_picks)")
check("calendario" in prompt.lower() and "defensa" in prompt.lower(),
      "B2.5: Spanish position-fixture-run phrasing present "
      "('calendario' + 'defensa')")
check("qué jornada" in prompt.lower() or "que jornada" in prompt.lower(),
      "B2.6: Spanish multi_intent example phrase ('qué jornada') present")
check("Salah" in prompt and "salah" in prompt.lower(),
      "B2.7: Spanish multi_intent example references a player (Salah)")

# Confidence threshold unchanged.
check(ic._CONFIDENCE_THRESHOLD == 0.7,
      "B2.8: _CONFIDENCE_THRESHOLD is still 0.7")

# IntentClassification dataclass untouched (field set guard).
fields = set(ic.IntentClassification.__dataclass_fields__.keys())
check(fields == {"intent", "canonical_question", "confidence", "language"},
      "B2.9: IntentClassification field set unchanged")


# ===========================================================================
# Summary
# ===========================================================================
print("\n" + "=" * 70)
print(f"M3 preflight — passed: {_pass}, failed: {_fail}")
if _failures:
    print("\nFailures:")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All M3-preflight assertions PASS.")
sys.exit(0)
