"""
run_phase26c_tests.py
=====================
Phase 2.6c: Chip routing phrasing expansion.

Stories covered
---------------
1b.1  Wildcard timing phrasing (antes o despues, cuando usar, deberia usar)
1b.2  Bench boost conditional phrasing (tiene sentido, activar, vale la pena)
1b.3  Spent-chip sequencing phrasing (ya use, ya gaste and accented variants)

Contract invariants verified
-----------------------------
- All target prompts route to get_chip_advice (not None/unsupported)
- Correct chip keyword extracted per prompt
- False-positive guard: non-chip questions with advisory phrases do NOT route
- Existing English chip routing unchanged (regression)
- Classifier prompt contains Spanish chip examples for all three phrase families

Regression
----------
- run_validation: all 54 scenarios must PASS
- run_phase26b_tests: all 76 assertions must PASS
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


# ---------------------------------------------------------------------------
# Test runner helpers
# ---------------------------------------------------------------------------

_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


from fpl_grounded_assistant.router import route  # noqa: E402


# ---------------------------------------------------------------------------
# A — Story 1b.1: Wildcard timing phrasing
# ---------------------------------------------------------------------------

print("\n=== A: Story 1b.1 — wildcard timing phrasing ===")

_timing_cases = [
    ("deberia usar el wildcard antes o despues de la doble jornada",  "wildcard", "A1"),
    ("debería usar el wildcard antes o después de la doble jornada",  "wildcard", "A2"),
    ("cuando deberia usar el wildcard",                                "wildcard", "A3"),
    ("cuándo debería usar el wildcard",                                "wildcard", "A4"),
    ("deberia usar el wildcard esta semana",                           "wildcard", "A5"),
    ("debería usar mi wildcard ahora",                                 "wildcard", "A6"),
    ("wildcard antes o despues de la doble jornada",                   "wildcard", "A7"),
]

for q, chip, label in _timing_cases:
    r = route(q)
    _check(f"{label} '{q[:55]}' routes to chip_advice",
           r is not None and r.tool_name == "get_chip_advice",
           f"got {r.tool_name if r else 'None'}")
    if r is not None and r.tool_name == "get_chip_advice":
        _check(f"{label}c chip='{chip}'",
               r.tool_args.get("chip") == chip,
               f"got chip={r.tool_args.get('chip')}")


# ---------------------------------------------------------------------------
# B — Story 1b.2: Bench boost conditional phrasing
# ---------------------------------------------------------------------------

print("\n=== B: Story 1b.2 — bench boost conditional phrasing ===")

_conditional_cases = [
    ("tiene sentido activar el bench boost con 10 jugadores disponibles", "bench_boost", "B1"),
    ("tiene sentido usar el bench boost esta semana",                      "bench_boost", "B2"),
    ("vale la pena activar el bench boost ahora",                          "bench_boost", "B3"),
    ("vale la pena usar el bench boost ahora o guardarlo",                 "bench_boost", "B4"),
    ("activar el bench boost esta semana",                                 "bench_boost", "B5"),
    ("conviene activar el wildcard ahora",                                 "wildcard",    "B6"),
    ("conviene usar el wildcard esta jornada",                             "wildcard",    "B7"),
]

for q, chip, label in _conditional_cases:
    r = route(q)
    _check(f"{label} '{q[:55]}' routes to chip_advice",
           r is not None and r.tool_name == "get_chip_advice",
           f"got {r.tool_name if r else 'None'}")
    if r is not None and r.tool_name == "get_chip_advice":
        _check(f"{label}c chip='{chip}'",
               r.tool_args.get("chip") == chip,
               f"got chip={r.tool_args.get('chip')}")


# ---------------------------------------------------------------------------
# C — Story 1b.3: Spent-chip sequencing phrasing
# ---------------------------------------------------------------------------

print("\n=== C: Story 1b.3 — spent-chip sequencing phrasing ===")

_spent_cases = [
    ("ya use el wildcard, que chip me queda mas rentable para el final", "wildcard",    "C1"),
    ("ya usé el wildcard, qué chip me queda más rentable",               "wildcard",    "C2"),
    ("ya gaste el wildcard esta temporada",                               "wildcard",    "C3"),
    # bench boost appears before wildcard in _CHIP_KEYWORDS scan → bench_boost extracted
    # (user is asking when to use bench boost, so this is semantically correct)
    ("ya gasté el wildcard, cuando uso el bench boost",                   "bench_boost", "C4"),
    ("ya lo use, el bench boost merece la pena ahora",                    "bench_boost", "C5"),
    ("ya lo usé, conviene activar el bench boost",                        "bench_boost", "C6"),
]

for q, chip, label in _spent_cases:
    r = route(q)
    _check(f"{label} '{q[:55]}' routes to chip_advice",
           r is not None and r.tool_name == "get_chip_advice",
           f"got {r.tool_name if r else 'None'}")
    if r is not None and r.tool_name == "get_chip_advice":
        _check(f"{label}c chip='{chip}'",
               r.tool_args.get("chip") == chip,
               f"got chip={r.tool_args.get('chip')}")


# ---------------------------------------------------------------------------
# D — False-positive guard: advisory phrases without chip keywords do NOT route
# ---------------------------------------------------------------------------

print("\n=== D: False-positive guard ===")

_no_route_cases = [
    ("tiene sentido capitar a Salah esta semana", "D1"),
    ("vale la pena fichar a Palmer ahora",         "D2"),
    ("ya use a todos mis defensas",                "D3"),
    ("antes o despues del partido",                "D4"),
    ("deberia usar a Haaland de titular",          "D5"),
    ("activar mi equipo esta semana",              "D6"),
]

for q, label in _no_route_cases:
    r = route(q)
    is_chip = r is not None and r.tool_name == "get_chip_advice"
    _check(f"{label} '{q}' does NOT route to chip_advice",
           not is_chip,
           f"unexpectedly routed to chip_advice with chip={r.tool_args.get('chip') if r else None}")


# ---------------------------------------------------------------------------
# E — Regression: existing English chip routing unchanged
# ---------------------------------------------------------------------------

print("\n=== E: Regression — English chip routing ===")

_english_cases = [
    ("should I use triple captain this week",   "triple_captain", "E1"),
    ("should I wildcard this week",             "wildcard",       "E2"),
    ("should I free hit this week",             "free_hit",       "E3"),
    ("is this a good week for bench boost",     "bench_boost",    "E4"),
    ("should I activate triple captain",        "triple_captain", "E5"),
    ("worth using bench boost this gameweek",   "bench_boost",    "E6"),
    ("when to use wildcard",                    "wildcard",       "E7"),
]

for q, chip, label in _english_cases:
    r = route(q)
    _check(f"{label} '{q}' routes to chip_advice",
           r is not None and r.tool_name == "get_chip_advice",
           f"got {r.tool_name if r else 'None'}")
    if r is not None and r.tool_name == "get_chip_advice":
        _check(f"{label}c chip='{chip}'",
               r.tool_args.get("chip") == chip,
               f"got chip={r.tool_args.get('chip')}")


# ---------------------------------------------------------------------------
# F — Classifier prompt contains Spanish chip examples
# ---------------------------------------------------------------------------

print("\n=== F: Classifier prompt Spanish chip examples ===")

import inspect  # noqa: E402
from fpl_grounded_assistant import intent_classifier as _cls_mod  # noqa: E402

prompt = _cls_mod.CLASSIFIER_SYSTEM_PROMPT
_check("F1 timing example in prompt (antes o despues)",
       "antes o después" in prompt or "antes o despues" in prompt)
_check("F2 conditional example in prompt (tiene sentido activar)",
       "tiene sentido activar" in prompt)
_check("F3 spent-chip example in prompt (ya usé el wildcard)",
       "ya usé el wildcard" in prompt or "ya use el wildcard" in prompt)
_check("F4 chip_advice section is present",
       "chip_advice:" in prompt)


# ---------------------------------------------------------------------------
# G — End-to-end: corpus scenarios 52-54 pass via respond()
# ---------------------------------------------------------------------------

print("\n=== G: End-to-end corpus scenarios (respond()) ===")

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.final_response import respond  # noqa: E402

_e2e_cases = [
    ("debería usar el wildcard antes o después de la doble jornada",
     "chip_advice", "wildcard", "G1"),
    ("tiene sentido activar el bench boost con 10 jugadores disponibles",
     "chip_advice", "bench_boost", "G2"),
    ("ya use el wildcard, que chip me queda mas rentable para el final",
     "chip_advice", "wildcard", "G3"),
]

for q, exp_intent, exp_chip, label in _e2e_cases:
    fr = respond(q, STANDARD_BOOTSTRAP)
    _check(f"{label} intent=chip_advice",
           fr.intent == exp_intent,
           f"got intent={fr.intent}")
    _check(f"{label} outcome=ok",
           fr.outcome == "ok",
           f"got outcome={fr.outcome}")
    _check(f"{label} chip meta non-null",
           fr.chip is not None,
           "chip metadata is None")
    if fr.chip is not None:
        _check(f"{label} chip.chip='{exp_chip}'",
               fr.chip.chip == exp_chip,
               f"got chip.chip={fr.chip.chip}")


# ---------------------------------------------------------------------------
# H — Regression: validation corpus 54/54
# ---------------------------------------------------------------------------

print("\n=== H: Regression — validation corpus ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total  = len(results)
passed = sum(1 for r in results if r.get("pass"))
_check(f"H1 validation corpus {passed}/{total} PASS",
       passed == total,
       f"{total - passed} scenario(s) failed")


# ---------------------------------------------------------------------------
# I — Regression: Phase 2.6b assertions still green
# ---------------------------------------------------------------------------

print("\n=== I: Regression — Phase 2.6b ===")

import importlib.util  # noqa: E402

_b_spec = importlib.util.spec_from_file_location(
    "run_phase26b", os.path.join(_HERE, "run_phase26b_tests.py")
)
# Run the 2.6b suite as a subprocess to avoid sharing state
import subprocess  # noqa: E402
result = subprocess.run(
    [sys.executable, os.path.join(_HERE, "run_phase26b_tests.py")],
    capture_output=True, text=True, cwd=_HERE,
)
last_line = [l for l in result.stdout.splitlines() if "Phase 2.6b:" in l]
if last_line:
    summary = last_line[-1].strip()
    passed_b = "76/76" in summary or "All assertions passed" in summary
    _check(f"I1 phase26b regression: {summary}", passed_b, result.stderr[-200:] if result.stderr else "")
else:
    _check("I1 phase26b regression", False, "could not parse output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6c: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"            {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("            All assertions passed.")
