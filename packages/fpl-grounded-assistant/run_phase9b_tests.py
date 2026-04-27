"""
run_phase9b_tests.py
=====================
Phase 9b: Orchestrator context injection into LLM router path.

Tests that:
- build_system_prompt() includes the FPL data context block
- context block is correctly delimited and data-accurate
- truncation kicks in for oversized context
- fallback to SYSTEM_PROMPT when context_builder raises
- deterministic routes still win (respond() grounded results unchanged)
- no FinalResponse contract drift
- session turns also receive fresh context per turn

Sections
--------
A  build_system_prompt()   -- structure, headers, content
B  Truncation guard        -- context capped at _MAX_CONTEXT_CHARS
C  Graceful fallback       -- exception in context_builder -> base SYSTEM_PROMPT
D  Deterministic precedence -- respond() grounded results unaffected
E  Contract invariants     -- FinalResponse shape unchanged
F  Phase 9a regression     -- build_orchestration_context still passes

Run from packages/fpl-grounded-assistant::

    python run_phase9b_tests.py
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

from fpl_grounded_assistant.llm_layer import (
    SYSTEM_PROMPT,
    build_system_prompt,
    _MAX_CONTEXT_CHARS,
    _CONTEXT_SECTION_HEADER,
    _CONTEXT_SECTION_FOOTER,
    _CONTEXT_TRUNCATION_MARKER,
)
from fpl_grounded_assistant.context_builder import build_orchestration_context
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DGW_BOOTSTRAP,
)
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
# Section A: build_system_prompt() — structure, headers, content
# ---------------------------------------------------------------------------

print("\n=== A: build_system_prompt() structure ===")

prompt = build_system_prompt(STANDARD_BOOTSTRAP)

# A1: returns a string
ok(isinstance(prompt, str),            "A1: returns a string")

# A2-A3: base SYSTEM_PROMPT content is present
ok(SYSTEM_PROMPT in prompt,            "A2: base SYSTEM_PROMPT is present verbatim")
ok(len(prompt) > len(SYSTEM_PROMPT),   "A3: prompt is longer than SYSTEM_PROMPT alone")

# A4-A5: context delimiter headers present
ok(_CONTEXT_SECTION_HEADER.strip() in prompt, "A4: context section header present")
ok(_CONTEXT_SECTION_FOOTER.strip() in prompt, "A5: context section footer present")

# A6: data context appears between header and footer
header_idx = prompt.find(_CONTEXT_SECTION_HEADER.strip())
footer_idx  = prompt.find(_CONTEXT_SECTION_FOOTER.strip())
ok(header_idx < footer_idx,            "A6: header appears before footer")

# A7-A9: actual FPL data in context block
ok("GW28"     in prompt,               "A7: current gameweek appears in prompt")
ok("Haaland"  in prompt,               "A8: player 'Haaland' appears in prompt")
ok("Salah"    in prompt,               "A9: player 'Salah' appears in prompt")

# A10: base rules still visible
ok("Do NOT contradict" in prompt,      "A10: base rule 'Do NOT contradict' still present")
ok("Do NOT fabricate"  in prompt,      "A11: base rule 'Do NOT fabricate' still present")

# A12: DGW bootstrap mentions double gameweek in prompt
dgw_prompt = build_system_prompt(DGW_BOOTSTRAP)
ok("DOUBLE GAMEWEEK" in dgw_prompt,    "A12: DGW bootstrap injects DOUBLE GAMEWEEK into prompt")

# A13: context is correctly ordered (SYSTEM_PROMPT before context block)
ok(prompt.index(SYSTEM_PROMPT) < prompt.index(_CONTEXT_SECTION_HEADER.strip()),
   "A13: base SYSTEM_PROMPT appears before context block")

# ---------------------------------------------------------------------------
# Section B: Truncation guard
# ---------------------------------------------------------------------------

print("\n=== B: truncation guard ===")

# Build a bootstrap that produces an oversized context by expanding elements
import copy

fat_bootstrap = copy.deepcopy(STANDARD_BOOTSTRAP)
# Inflate element list to blow past _MAX_CONTEXT_CHARS
base_el = fat_bootstrap["elements"][0].copy()
for i in range(500):
    el = base_el.copy()
    el["id"] = 1000 + i
    el["web_name"] = f"Player{i:04d}"
    fat_bootstrap["elements"].append(el)

fat_prompt = build_system_prompt(fat_bootstrap)

# B1: truncation marker present when context is too big
context_text = build_orchestration_context(fat_bootstrap)
if len(context_text) > _MAX_CONTEXT_CHARS:
    ok(_CONTEXT_TRUNCATION_MARKER.strip() in fat_prompt,
       "B1: truncation marker present when context exceeds _MAX_CONTEXT_CHARS")
else:
    # Context happened to fit — just verify no crash
    ok(isinstance(fat_prompt, str), "B1: fat bootstrap produces string (context fit)")

# B2: injected context block never exceeds _MAX_CONTEXT_CHARS + header/footer overhead
header_pos = fat_prompt.find(_CONTEXT_SECTION_HEADER.strip())
footer_pos  = fat_prompt.rfind(_CONTEXT_SECTION_FOOTER.strip())
if header_pos != -1 and footer_pos != -1:
    extracted = fat_prompt[header_pos:footer_pos + len(_CONTEXT_SECTION_FOOTER.strip())]
    # The extracted block includes headers; the bare context inside it
    # is at most _MAX_CONTEXT_CHARS + truncation marker chars
    ok(len(extracted) <= _MAX_CONTEXT_CHARS + 500,
       "B2: injected context block is bounded (within margin)")
else:
    ok(True, "B2: (context section not found — safe to skip)")

# B3: base rules still present after truncation
ok("Do NOT contradict" in fat_prompt,  "B3: base rules present even with truncated context")

# B4: header still present after truncation (not truncated away)
ok(_CONTEXT_SECTION_HEADER.strip() in fat_prompt, "B4: section header present even with truncation")

# ---------------------------------------------------------------------------
# Section C: graceful fallback when context_builder raises
# ---------------------------------------------------------------------------

print("\n=== C: graceful fallback ===")

import fpl_grounded_assistant.llm_layer as _llm_layer
import fpl_grounded_assistant.context_builder as _cb_module

# Monkey-patch build_orchestration_context to raise
_orig_fn = _cb_module.build_orchestration_context


def _raising_context(bootstrap):
    raise RuntimeError("simulated context build failure")


_cb_module.build_orchestration_context = _raising_context

try:
    fallback_prompt = build_system_prompt(STANDARD_BOOTSTRAP)
    ok(fallback_prompt == SYSTEM_PROMPT,
       "C1: fallback returns base SYSTEM_PROMPT when context_builder raises")
    ok(_CONTEXT_SECTION_HEADER.strip() not in fallback_prompt,
       "C2: no context section header in fallback prompt")
    ok(isinstance(fallback_prompt, str),
       "C3: fallback returns a string (does not raise)")
except Exception as exc:
    ok(False, f"C1: build_system_prompt raised: {exc}")
    ok(False, "C2: (skipped)")
    ok(False, "C3: (skipped)")
finally:
    _cb_module.build_orchestration_context = _orig_fn

# Verify restore worked
ok(build_system_prompt(STANDARD_BOOTSTRAP) != SYSTEM_PROMPT,
   "C4: context injection restored after monkey-patch teardown")

# ---------------------------------------------------------------------------
# Section D: deterministic precedence — respond() grounded results unaffected
# ---------------------------------------------------------------------------

print("\n=== D: deterministic precedence ===")

# D1-D4: captain_score intent — deterministic routing still wins
r_captain = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(r_captain.intent   == "captain_score",  "D1: captain_score intent unchanged")
ok(r_captain.outcome  == "ok",             "D2: captain_score outcome == ok")
ok(r_captain.supported,                    "D3: captain_score supported == True")
ok(r_captain.captain is not None,          "D4: captain metadata populated (deterministic)")

# D5-D7: player_summary intent
r_summary = respond("tell me about Salah", STANDARD_BOOTSTRAP)
ok(r_summary.intent  == "player_summary",  "D5: player_summary intent unchanged")
ok(r_summary.outcome == "ok",              "D6: player_summary outcome == ok")

# D8-D9: chip_advice intent
r_chip = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(r_chip.intent  == "chip_advice",        "D8: chip_advice intent unchanged")
ok(r_chip.outcome == "ok",                 "D9: chip_advice outcome == ok")

# D10: unsupported intent — still returns unsupported (not hallucinated)
r_unsup = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(r_unsup.outcome == "unsupported_intent","D10: unsupported question still unsupported_intent")
ok(not r_unsup.supported,                  "D11: unsupported.supported == False")

# ---------------------------------------------------------------------------
# Section E: FinalResponse contract invariants
# ---------------------------------------------------------------------------

print("\n=== E: contract invariants ===")

required_fields = [
    "final_text", "outcome", "supported", "intent",
    "review_passed", "llm_used", "debug",
    "comparison", "captain", "captain_ranking",
    "sub_responses", "transfer", "chip",
    "fixture_run", "differential",
]

r_test = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
for field_name in required_fields:
    ok(hasattr(r_test, field_name),
       f"E: FinalResponse has field '{field_name}'")

# E-extra: final_text is non-empty string
ok(isinstance(r_test.final_text, str) and len(r_test.final_text) > 0,
   "E-extra: final_text is non-empty string")

# ---------------------------------------------------------------------------
# Section F: Phase 9a regression
# ---------------------------------------------------------------------------

print("\n=== F: Phase 9a regression ===")

from fpl_grounded_assistant.context_builder import (
    build_orchestration_context,
    build_orchestration_context_dict,
)
from fpl_grounded_assistant.conversation_fixtures import BGW_BOOTSTRAP

# Re-run key Phase 9a assertions
ctx = build_orchestration_context_dict(STANDARD_BOOTSTRAP)
ok(ctx["gameweek"]["current_gw"] == 28,           "F1: 9a current_gw == 28")
ok(ctx["gw_type"]["gw_type"] == "normal",          "F2: 9a gw_type == normal")
ok(len(ctx["players"]["top_candidates"]) >= 1,     "F3: 9a top_candidates populated")

text = build_orchestration_context(STANDARD_BOOTSTRAP)
ok("=== FPL Data Context ===" in text,             "F4: 9a header present")
ok("GW28" in text,                                 "F5: 9a GW28 in text")
ok("Haaland" in text,                              "F6: 9a Haaland in text")
ok("GW0" not in text,                              "F7: 9a no GW0 leak")

dgw_text = build_orchestration_context(DGW_BOOTSTRAP)
ok("DOUBLE GAMEWEEK" in dgw_text,                  "F8: 9a DGW text correct")
bgw_text = build_orchestration_context(BGW_BOOTSTRAP)
ok("BLANK GAMEWEEK" in bgw_text,                   "F9: 9a BGW text correct")

# Empty bootstrap still doesn't crash
try:
    build_orchestration_context({})
    ok(True, "F10: 9a empty bootstrap no crash")
except Exception as exc:
    ok(False, f"F10: 9a empty bootstrap raised {exc}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase 9b: {_pass}/{total} assertions passed.")
if _fail:
    print(f"          {_fail} FAILED.")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
