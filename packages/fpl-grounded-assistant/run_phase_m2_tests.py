"""
run_phase_m2_tests.py
======================
Phase M2 (MCP_architecture): Guided Prompt Registry tests.

Covers:
    A  PromptSpec registry surface (list_prompts, resolve_prompt, aliases)
    B  Argument parsing — connectors, key=value flags, positional fallback
    C  Validation — missing required arg -> needs_clarification + field name
    D  Validation rule violations (a==b, out==in, range, enum)
    E  Expansion-mode canonical text + intent re-entry through route()
    F  Dispatch-mode direct tool invocation with typed args

Run from packages/fpl-grounded-assistant::

    python run_phase_m2_tests.py

Total assertions: >= 35.  Exit 0 on success, 1 on failure.
"""
from __future__ import annotations

import copy
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

from fpl_grounded_assistant import ask_v2  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.decision_router import decide  # noqa: E402
from fpl_grounded_assistant.prompt_registry import (  # noqa: E402
    list_prompts,
    list_prompt_specs,
    resolve_prompt,
    get_prompt_spec,
    validate_and_parse,
    build_expansion,
    MODE_EXPANSION,
    MODE_DISPATCH,
)
from fpl_grounded_assistant.intent_aliases import (  # noqa: E402
    resolve_prompt as alias_resolve_prompt,
    list_prompt_names,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    INTENT_CAPTAIN_SCORE,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
    INTENT_CHIP_ADVICE,
    INTENT_RANK_CANDIDATES,
)

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


def _build_bootstrap() -> dict:
    bs = copy.deepcopy(STANDARD_BOOTSTRAP)
    for el in bs["elements"]:
        el.setdefault("total_points", 100)
    return bs


BOOTSTRAP = _build_bootstrap()


# ===========================================================================
# A — registry surface
# ===========================================================================
print("\n[A] prompt_registry surface")

names = list_prompts()
expected = {"capitan", "comparar", "transferencia", "calendarios",
            "diferenciales", "chips", "clasificacion"}
check(set(names) == expected, "A1: list_prompts returns the seven canonical names")
check(len(list_prompt_specs()) == 7, "A2: list_prompt_specs has seven specs")
check(resolve_prompt("/CAPITAN") == "capitan", "A3: '/CAPITAN' (uppercase) resolves to capitan")
check(resolve_prompt("captain") == "capitan", "A4: English alias 'captain' resolves to capitan")
check(resolve_prompt("compare") == "comparar", "A5: alias 'compare' -> comparar")
check(resolve_prompt("rank") == "clasificacion", "A6: alias 'rank' -> clasificacion")
check(resolve_prompt("unknown_zzz") is None, "A7: unknown prompt resolves to None")
check(alias_resolve_prompt("/capitan") == "capitan",
      "A8: intent_aliases.resolve_prompt re-export works")
check(set(list_prompt_names()) == expected,
      "A9: intent_aliases.list_prompt_names returns the seven names")


# ===========================================================================
# B — argument parsing
# ===========================================================================
print("\n[B] argument parsing")

spec_compare = get_prompt_spec("comparar")
r = validate_and_parse(spec_compare, "Saka and Palmer")
check(r["ok"] and r["args"]["a"] == "Saka" and r["args"]["b"] == "Palmer",
      "B1: '/comparar Saka and Palmer' positional+connector parses")

r = validate_and_parse(spec_compare, "Saka vs Palmer")
check(r["ok"] and r["args"]["a"] == "Saka" and r["args"]["b"] == "Palmer",
      "B2: '/comparar Saka vs Palmer' positional+connector parses")

r = validate_and_parse(spec_compare, "a=Saka b=Palmer")
check(r["ok"] and r["args"]["a"] == "Saka" and r["args"]["b"] == "Palmer",
      "B3: '/comparar a=Saka b=Palmer' named-form parses")

spec_xfer = get_prompt_spec("transferencia")
r = validate_and_parse(spec_xfer, "Saka por Palmer")
check(r["ok"] and r["args"]["out"] == "Saka" and r["args"]["in"] == "Palmer",
      "B4: '/transferencia Saka por Palmer' parses (Spanish connector)")

r = validate_and_parse(spec_xfer, "salida=Saka entrada=Palmer")
check(r["ok"] and r["args"]["out"] == "Saka" and r["args"]["in"] == "Palmer",
      "B5: Spanish-aliased flag keys (salida/entrada) parse")

spec_cal = get_prompt_spec("calendarios")
r = validate_and_parse(spec_cal, "Haaland horizon=5")
check(r["ok"] and r["args"]["player"] == "Haaland" and r["args"]["horizon"] == 5,
      "B6: '/calendarios Haaland horizon=5' parses with int horizon")

r = validate_and_parse(spec_cal, "Haaland")
check(r["ok"] and r["args"]["player"] == "Haaland" and r["args"]["horizon"] == 5,
      "B7: '/calendarios Haaland' uses default horizon=5")

spec_diff = get_prompt_spec("diferenciales")
r = validate_and_parse(spec_diff, "threshold=10 top_n=8")
check(r["ok"] and r["args"]["threshold"] == 10.0 and r["args"]["top_n"] == 8,
      "B8: '/diferenciales threshold=10 top_n=8' parses with typed floats/ints")

r = validate_and_parse(spec_diff, "")
check(r["ok"] and r["args"]["threshold"] == 15.0 and r["args"]["top_n"] == 5,
      "B9: '/diferenciales' (no args) uses defaults")

spec_chips = get_prompt_spec("chips")
r = validate_and_parse(spec_chips, "tc")
check(r["ok"] and r["args"]["chip"] == "tc",
      "B10: '/chips tc' parses enum value")

spec_clasif = get_prompt_spec("clasificacion")
r = validate_and_parse(spec_clasif, "n=3")
check(r["ok"] and r["args"]["n"] == 3, "B11: '/clasificacion n=3' parses")
r = validate_and_parse(spec_clasif, "")
check(r["ok"] and r["args"]["n"] == 5, "B12: '/clasificacion' uses default n=5")


# ===========================================================================
# C — missing required args -> needs_clarification with field name
# ===========================================================================
print("\n[C] needs_clarification on missing required args")

d = decide("/capitan", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["player"],
      "C1: '/capitan' (no player) -> needs_clarification, missing player")

d = decide("/comparar Saka", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and "b" in d["missing_fields"],
      "C2: '/comparar Saka' -> needs_clarification for missing b")

d = decide("/transferencia", BOOTSTRAP)
check(d["outcome"] == "needs_clarification"
      and set(d["missing_fields"]) == {"out", "in"},
      "C3: '/transferencia' -> needs_clarification for both out and in")

d = decide("/calendarios", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["player"],
      "C4: '/calendarios' -> needs_clarification, missing player")

d = decide("/chips", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["chip"],
      "C5: '/chips' -> needs_clarification, missing chip")


# ===========================================================================
# D — validation-rule violations
# ===========================================================================
print("\n[D] validation rules")

d = decide("/comparar a=Saka b=Saka", BOOTSTRAP)
check(d["outcome"] == "needs_clarification"
      and any("different" in e.lower() for e in d.get("errors", [])),
      "D1: '/comparar a=Saka b=Saka' -> needs_clarification (a==b)")

d = decide("/transferencia out=Salah in=Salah", BOOTSTRAP)
check(d["outcome"] == "needs_clarification"
      and any("different" in e.lower() for e in d.get("errors", [])),
      "D2: '/transferencia out=Salah in=Salah' -> needs_clarification (out==in)")

d = decide("/calendarios Haaland horizon=11", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["horizon"],
      "D3: '/calendarios Haaland horizon=11' -> needs_clarification (range)")

d = decide("/calendarios Haaland horizon=0", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["horizon"],
      "D4: '/calendarios Haaland horizon=0' -> needs_clarification (below min)")

d = decide("/chips chip=foo", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["chip"],
      "D5: '/chips chip=foo' -> needs_clarification (enum miss)")

d = decide("/diferenciales top_n=99", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and "top_n" in d["missing_fields"],
      "D6: '/diferenciales top_n=99' -> needs_clarification (top_n > 20)")

d = decide("/calendarios Haaland horizon=abc", BOOTSTRAP)
check(d["outcome"] == "needs_clarification" and d["missing_fields"] == ["horizon"],
      "D7: '/calendarios Haaland horizon=abc' -> needs_clarification (type error)")


# ===========================================================================
# E — expansion-mode prompts: canonical text + intent re-entry
# ===========================================================================
print("\n[E] expansion-mode prompts")

# E1: /capitan -> expansion produces canonical text
spec = get_prompt_spec("capitan")
check(spec.mode == MODE_EXPANSION, "E1: /capitan is expansion-mode")
text = build_expansion(spec, {"player": "Haaland"})
check(text == "should I captain Haaland", "E2: /capitan canonical text exact match")

# E3: re-entering route() via ask_v2 reaches INTENT_CAPTAIN_SCORE
r = ask_v2("/capitan Haaland", BOOTSTRAP)
check(r.get("selected_tool") == "get_captain_score",
      "E3: '/capitan Haaland' re-enters route() and hits get_captain_score")
check(r.get("workflow_intent") == INTENT_CAPTAIN_SCORE,
      "E4: ask_v2 carries workflow_intent=INTENT_CAPTAIN_SCORE")
check(r.get("canonical_text") == "should I captain Haaland",
      "E5: routing_trace carries canonical text")

# E6: /comparar
r = ask_v2("/comparar Saka and Palmer", BOOTSTRAP)
check(r.get("selected_tool") == "compare_players",
      "E6: '/comparar Saka and Palmer' reaches compare_players tool")
check(r.get("workflow_intent") == INTENT_COMPARE_PLAYERS,
      "E7: workflow_intent=INTENT_COMPARE_PLAYERS")

# E8: /transferencia
r = ask_v2("/transferencia Saka por Palmer", BOOTSTRAP)
check(r.get("selected_tool") == "get_transfer_advice",
      "E8: '/transferencia Saka por Palmer' reaches get_transfer_advice")
check(r.get("workflow_intent") == INTENT_TRANSFER_ADVICE,
      "E9: workflow_intent=INTENT_TRANSFER_ADVICE")

# E10: /chips
r = ask_v2("/chips tc", BOOTSTRAP)
check(r.get("selected_tool") == "get_chip_advice",
      "E10: '/chips tc' reaches get_chip_advice")
check(r.get("workflow_intent") == INTENT_CHIP_ADVICE,
      "E11: workflow_intent=INTENT_CHIP_ADVICE")

# E12: /clasificacion -> rank_captain_candidates (with auto-populated candidates)
r = ask_v2("/clasificacion", BOOTSTRAP)
check(r.get("selected_tool") == "rank_captain_candidates",
      "E12: '/clasificacion' reaches rank_captain_candidates")
check(r.get("workflow_intent") == INTENT_RANK_CANDIDATES,
      "E13: workflow_intent=INTENT_RANK_CANDIDATES")
check(r.get("canonical_text") == "top captains this week",
      "E14: /clasificacion canonical text exact match")


# ===========================================================================
# F — dispatch-mode prompts hit run_tool with typed args
# ===========================================================================
print("\n[F] dispatch-mode prompts")

spec = get_prompt_spec("calendarios")
check(spec.mode == MODE_DISPATCH, "F1: /calendarios is dispatch-mode")

# F2: /calendarios Haaland horizon=3 -> dispatch
r = ask_v2("/calendarios Haaland horizon=3", BOOTSTRAP)
check(r.get("selected_tool") == "get_player_fixture_run",
      "F2: '/calendarios Haaland horizon=3' dispatches get_player_fixture_run")
check(r.get("tool_input", {}).get("horizon") == 3,
      "F3: dispatched tool_input carries horizon=3")
check(r.get("tool_input", {}).get("query") == "Haaland",
      "F4: dispatched tool_input carries query=Haaland")
check(r.get("workflow_intent") == INTENT_PLAYER_FIXTURE_RUN,
      "F5: workflow_intent=INTENT_PLAYER_FIXTURE_RUN")
check(r.get("kind") == "prompt", "F6: result.kind == 'prompt'")

# F7: /diferenciales -> dispatch
spec = get_prompt_spec("diferenciales")
check(spec.mode == MODE_DISPATCH, "F7: /diferenciales is dispatch-mode")
r = ask_v2("/diferenciales threshold=10 top_n=8", BOOTSTRAP)
check(r.get("selected_tool") == "get_differential_picks",
      "F8: '/diferenciales threshold=10 top_n=8' dispatches get_differential_picks")
check(r.get("tool_input", {}).get("ownership_threshold") == 10.0,
      "F9: dispatched tool_input carries ownership_threshold=10.0")
check(r.get("tool_input", {}).get("top_n") == 8,
      "F10: dispatched tool_input carries top_n=8")
check(r.get("workflow_intent") == INTENT_DIFFERENTIAL_PICKS,
      "F11: workflow_intent=INTENT_DIFFERENTIAL_PICKS")
# Verify the raw output reflects the typed args
raw = r.get("raw_output") or {}
if raw.get("status") == "ok":
    meta = raw.get("ownership_threshold")
    check(meta == 10.0, "F12: raw_output.ownership_threshold == 10.0 (typed arg honored)")


# ===========================================================================
# Summary
# ===========================================================================
total = _pass + _fail
print(f"\n{'='*60}")
print(f"Phase M2 tests: {_pass}/{total} PASS  ({_fail} FAIL)")
if _failures:
    print("\nFailures:")
    for f in _failures:
        print(f"  - {f}")
sys.exit(0 if _fail == 0 else 1)
