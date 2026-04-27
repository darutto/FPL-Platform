"""
run_phase9c_tests.py
=====================
Phase 9c: Session-turn context freshness verification.

Validates that build_system_prompt() is called once per turn in a
ConversationSession, that each call uses the bootstrap passed for THAT
turn (not a stale reference from a prior turn), and that deterministic
routing precedence and all FinalResponse invariants are preserved.

No production code changes are required for this slice.  Freshness
evidence is captured by injecting a _CapturingClient whose
messages.create() records the ``system`` argument on every call.
This is the same mock-client pattern established in run_phase3a_tests.py
(sections J/K) — fully deterministic, no API keys needed.

Sections
--------
A  _CapturingClient infrastructure  -- verify mock captures correctly
B  Single-turn context presence     -- system prompt contains context block
C  Per-turn freshness               -- context reflects each turn's bootstrap
D  Invocation count                 -- N turns => N captures
E  Context fingerprint accuracy     -- GW in prompt matches bootstrap GW
F  Fallback in multi-turn           -- session survives context_builder raise
G  Deterministic routing precedence -- outcomes unchanged with capturing client
H  FinalResponse contract shape     -- no field drift
I  Phase 9b regression              -- build_system_prompt / context injection
J  Phase 9a regression              -- build_orchestration_context

Run from packages/fpl-grounded-assistant::

    python run_phase9c_tests.py
"""
from __future__ import annotations

import copy
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

from fpl_grounded_assistant.conversation_state import ConversationSession
from fpl_grounded_assistant.llm_layer import (
    SYSTEM_PROMPT,
    build_system_prompt,
    _CONTEXT_SECTION_HEADER,
    _CONTEXT_SECTION_FOOTER,
)
from fpl_grounded_assistant.context_builder import build_orchestration_context
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
# Capturing mock client
#
# Follows the _MockClientOK pattern from run_phase3a_tests.py (Section J).
# Every messages.create() call records the ``system`` argument and returns
# a minimal valid response so ask_llm() registers llm_called=True.
# ---------------------------------------------------------------------------

class _CapturingClient:
    """Mock Anthropic-compatible client that records per-call system prompts.

    Passes all FinalResponse invariant checks because:
    * messages.create() succeeds (no exception)
    * content[0].text is a non-empty string
    * llm_called=True is set in LLMResponse
    * Review layer runs normally on the captured text
    """

    def __init__(self, reply: str = "Haaland is a good captain this week.") -> None:
        self._reply = reply
        self.captured: list[dict] = []   # [{system, messages, model}, ...]
        self.messages = self             # client.messages.create(...) -> self.create(...)

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list,
        **_kwargs,
    ):
        self.captured.append({
            "system":   system,
            "messages": messages,
            "model":    model,
        })

        class _Content:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Message:
            def __init__(self, text: str) -> None:
                self.content = [_Content(text)]

        return _Message(self._reply)

    # Convenience
    @property
    def system_prompts(self) -> list[str]:
        """Return the ordered list of system prompts from all captured calls."""
        return [c["system"] for c in self.captured]

    @property
    def call_count(self) -> int:
        return len(self.captured)


# ---------------------------------------------------------------------------
# Bootstrap variants for cross-turn freshness testing
#
# GW28_BOOTSTRAP  — GW28 is_current (identical to STANDARD_BOOTSTRAP)
# GW29_BOOTSTRAP  — GW29 is_current; GW30 is_next; GW28 finished
# These differ only in the events block so the GW fingerprint is unambiguous.
# ---------------------------------------------------------------------------

GW28_BOOTSTRAP: dict = STANDARD_BOOTSTRAP  # alias for clarity

GW29_BOOTSTRAP: dict = copy.deepcopy(STANDARD_BOOTSTRAP)
GW29_BOOTSTRAP["events"] = [
    {"id": 27, "is_current": False, "is_next": False, "finished": True},
    {"id": 28, "is_current": False, "is_next": False, "finished": True},
    {"id": 29, "is_current": True,  "is_next": False, "finished": False},
    {"id": 30, "is_current": False, "is_next": True,  "finished": False},
]


# ---------------------------------------------------------------------------
# Section A: _CapturingClient infrastructure
# ---------------------------------------------------------------------------

print("\n=== A: _CapturingClient infrastructure ===")

_client_a = _CapturingClient(reply="Test response.")

# A1: ask_llm with capturing client sets llm_called=True
from fpl_grounded_assistant.llm_layer import ask_llm
lr = ask_llm("should I captain Haaland", GW28_BOOTSTRAP, client=_client_a)
ok(lr.llm_called is True,         "A1: llm_called=True with capturing client")
ok(lr.model != "none",            "A2: model is set (not 'none') with capturing client")
ok(_client_a.call_count == 1,     "A3: exactly 1 call recorded after 1 ask_llm()")

# A4-A6: system prompt was captured
ok(len(_client_a.system_prompts) == 1,              "A4: 1 system prompt captured")
captured_sys = _client_a.system_prompts[0]
ok(isinstance(captured_sys, str),                   "A5: captured system prompt is str")
ok(len(captured_sys) > len(SYSTEM_PROMPT),          "A6: captured prompt includes context (longer than base)")

# A7: llm_text is the mock reply (capturing client reply flows through)
ok(lr.llm_text == "Test response.", "A7: llm_text == mock client reply")

# ---------------------------------------------------------------------------
# Section B: Single-turn context presence in captured system prompt
# ---------------------------------------------------------------------------

print("\n=== B: Single-turn context presence ===")

ok(SYSTEM_PROMPT in captured_sys,                          "B1: base SYSTEM_PROMPT in captured prompt")
ok(_CONTEXT_SECTION_HEADER.strip() in captured_sys,        "B2: context header present")
ok(_CONTEXT_SECTION_FOOTER.strip() in captured_sys,        "B3: context footer present")
ok("GW28" in captured_sys,                                 "B4: GW28 in captured system prompt")
ok("Haaland" in captured_sys,                              "B5: 'Haaland' in captured system prompt")
ok("Salah"   in captured_sys,                              "B6: 'Salah' in captured system prompt")
ok("Do NOT fabricate" in captured_sys,                     "B7: safety rule still present")
ok("Do NOT contradict" in captured_sys,                    "B8: grounding rule still present")

# ---------------------------------------------------------------------------
# Section C: Per-turn freshness — different bootstraps produce different context
# ---------------------------------------------------------------------------

print("\n=== C: Per-turn freshness (different bootstrap per turn) ===")

# Pre-compute expected fingerprints
ctx28 = build_orchestration_context(GW28_BOOTSTRAP)
ctx29 = build_orchestration_context(GW29_BOOTSTRAP)

ok("GW28" in ctx28,  "C1: GW28 bootstrap context contains 'GW28'")
ok("GW29" in ctx29,  "C2: GW29 bootstrap context contains 'GW29'")
ok("GW28" not in ctx29 or "Current Gameweek : GW29" in ctx29,
   "C3: GW29 context shows GW29 as current (not GW28)")

# Run two asks with different bootstraps and capture system prompts
_client_c = _CapturingClient()

ask_llm("should I captain Haaland", GW28_BOOTSTRAP, client=_client_c)
ask_llm("should I captain Salah",   GW29_BOOTSTRAP, client=_client_c)

ok(_client_c.call_count == 2,       "C4: 2 calls recorded for 2 ask_llm() calls")

sys28 = _client_c.system_prompts[0]
sys29 = _client_c.system_prompts[1]

ok("GW28" in sys28,                 "C5: turn-1 system prompt contains 'GW28'")
ok("GW29" in sys29,                 "C6: turn-2 system prompt contains 'GW29'")
ok(sys28 != sys29,                  "C7: system prompts differ across turns (not stale)")

# Verify GW28 did NOT bleed into turn-2 prompt
ok("Current Gameweek : GW28" not in sys29,
   "C8: turn-2 system prompt does not show GW28 as current (no stale cache)")
ok("Current Gameweek : GW29" in sys29,
   "C9: turn-2 system prompt shows GW29 as current (correct)")

# ---------------------------------------------------------------------------
# Section D: Invocation count — N turns => exactly N captures
# ---------------------------------------------------------------------------

print("\n=== D: Invocation count ===")

_client_d = _CapturingClient()

N_TURNS = 4
for i in range(N_TURNS):
    bs = GW28_BOOTSTRAP if i % 2 == 0 else GW29_BOOTSTRAP
    ask_llm("should I captain Haaland", bs, client=_client_d)

ok(_client_d.call_count == N_TURNS,
   f"D1: exactly {N_TURNS} captures for {N_TURNS} ask_llm() calls")

# Each capture has a system prompt
ok(all(isinstance(s, str) and len(s) > 0 for s in _client_d.system_prompts),
   "D2: every captured system prompt is a non-empty string")

# Even/odd turns have alternating GWs
even_gws = [sp for i, sp in enumerate(_client_d.system_prompts) if i % 2 == 0]
odd_gws  = [sp for i, sp in enumerate(_client_d.system_prompts) if i % 2 == 1]
ok(all("GW28" in sp for sp in even_gws), "D3: even turns (GW28 bootstrap) contain 'GW28'")
ok(all("GW29" in sp for sp in odd_gws),  "D4: odd turns (GW29 bootstrap) contain 'GW29'")

# ---------------------------------------------------------------------------
# Section E: True multi-turn session path via ConversationSession
# ---------------------------------------------------------------------------

print("\n=== E: Multi-turn ConversationSession freshness ===")

session = ConversationSession()
_client_e = _CapturingClient()

# Turn 1: GW28 bootstrap
r1 = session.respond("should I captain Haaland", GW28_BOOTSTRAP, client=_client_e)
# Turn 2: GW29 bootstrap (simulating a server bootstrap refresh between sessions)
r2 = session.respond("should I captain Salah",   GW29_BOOTSTRAP, client=_client_e)

ok(session.turn_count == 2,        "E1: session.turn_count == 2 after 2 turns")
ok(_client_e.call_count == 2,      "E2: 2 client calls for 2 session turns")

e_sys1 = _client_e.system_prompts[0]
e_sys2 = _client_e.system_prompts[1]

ok("GW28" in e_sys1,               "E3: session turn-1 system prompt contains GW28")
ok("GW29" in e_sys2,               "E4: session turn-2 system prompt contains GW29")
ok(e_sys1 != e_sys2,               "E5: session system prompts differ between turns (fresh per turn)")
ok("Current Gameweek : GW29" in e_sys2,
   "E6: session turn-2 prompt shows GW29 as current gameweek")

# Deterministic intents/outcomes still correct
ok(r1.intent  == "captain_score",  "E7: session turn-1 intent = captain_score")
ok(r1.outcome == "ok",             "E8: session turn-1 outcome = ok")
ok(r2.intent  == "captain_score",  "E9: session turn-2 intent = captain_score")
ok(r2.outcome == "ok",             "E10: session turn-2 outcome = ok")

# llm_used=True for both turns (capturing client returns a valid reply)
ok(r1.llm_used is True,            "E11: session turn-1 llm_used=True (client captured)")
ok(r2.llm_used is True,            "E12: session turn-2 llm_used=True (client captured)")

# ---------------------------------------------------------------------------
# Section F: Fallback in multi-turn when context_builder raises
# ---------------------------------------------------------------------------

print("\n=== F: Fallback in multi-turn when context_builder raises ===")

import fpl_grounded_assistant.context_builder as _cb_module

_orig_build = _cb_module.build_orchestration_context


def _raising_build(bootstrap):
    raise RuntimeError("simulated context builder failure in session")


session_f = ConversationSession()
_client_f = _CapturingClient()

# Patch context builder to raise
_cb_module.build_orchestration_context = _raising_build

try:
    rf1 = session_f.respond("should I captain Haaland", GW28_BOOTSTRAP, client=_client_f)
    rf2 = session_f.respond("tell me about Salah",       GW28_BOOTSTRAP, client=_client_f)
    ok(True, "F1: session survives context_builder raise (no exception)")
    ok(session_f.turn_count == 2,     "F2: turn_count == 2 despite context failure")
    ok(rf1.intent  == "captain_score","F3: turn-1 intent still captain_score")
    ok(rf1.outcome == "ok",           "F4: turn-1 outcome still ok")
    ok(rf2.intent  == "player_summary","F5: turn-2 intent still player_summary")
    ok(rf2.outcome == "ok",           "F6: turn-2 outcome still ok")

    # With context builder raising, build_system_prompt returns base SYSTEM_PROMPT
    # Both captures should equal SYSTEM_PROMPT exactly
    ok(all(sp == SYSTEM_PROMPT for sp in _client_f.system_prompts),
       "F7: fallback system prompt == base SYSTEM_PROMPT when context_builder raises")
    ok(_CONTEXT_SECTION_HEADER.strip() not in _client_f.system_prompts[0],
       "F8: no context section header in fallback prompt")
except Exception as exc:
    ok(False, f"F1: session raised: {exc}")
    for label in ["F2", "F3", "F4", "F5", "F6", "F7", "F8"]:
        ok(False, f"{label}: (skipped — exception in F1)")
finally:
    _cb_module.build_orchestration_context = _orig_build

# Confirm restore: next turn gets context again
session_g_verify = ConversationSession()
_client_g_verify = _CapturingClient()
respond("should I captain Haaland", GW28_BOOTSTRAP, client=_client_g_verify)
ok(_CONTEXT_SECTION_HEADER.strip() in _client_g_verify.system_prompts[0],
   "F9: context injection restored after monkey-patch teardown")

# ---------------------------------------------------------------------------
# Section G: Deterministic routing precedence with capturing client
# ---------------------------------------------------------------------------

print("\n=== G: Deterministic routing precedence ===")

# The capturing client does not affect routing — deterministic backend runs
# before any LLM call, regardless of which client is provided.

_client_g = _CapturingClient()

rg_captain = respond("should I captain Haaland",       GW28_BOOTSTRAP, client=_client_g)
rg_summary = respond("tell me about Salah",             GW28_BOOTSTRAP, client=_client_g)
rg_chip    = respond("should I bench boost this week",  GW28_BOOTSTRAP, client=_client_g)
rg_unsup   = respond("who will win the league",         GW28_BOOTSTRAP, client=_client_g)

ok(rg_captain.intent  == "captain_score",       "G1: captain_score intent unchanged")
ok(rg_captain.outcome == "ok",                  "G2: captain_score outcome unchanged")
ok(rg_captain.captain is not None,              "G3: captain metadata populated (deterministic)")
ok(rg_summary.intent  == "player_summary",      "G4: player_summary intent unchanged")
ok(rg_summary.outcome == "ok",                  "G5: player_summary outcome unchanged")
ok(rg_chip.intent     == "chip_advice",         "G6: chip_advice intent unchanged")
ok(rg_chip.outcome    == "ok",                  "G7: chip_advice outcome unchanged")
ok(rg_unsup.outcome   == "unsupported_intent",  "G8: unsupported still unsupported_intent")
ok(not rg_unsup.supported,                      "G9: unsupported.supported == False")

# LLM only called for supported intents (unsupported returns before API call)
# Note: with no client set for rg_unsup path above, llm_used=False is expected
ok(_client_g.call_count >= 3,    "G10: at least 3 API calls (supported intents)")

# ---------------------------------------------------------------------------
# Section H: FinalResponse contract shape
# ---------------------------------------------------------------------------

print("\n=== H: FinalResponse contract shape ===")

_REQUIRED_FIELDS = [
    "final_text", "outcome", "supported", "intent",
    "review_passed", "llm_used", "debug",
    "comparison", "captain", "captain_ranking",
    "sub_responses", "transfer", "chip",
    "fixture_run", "differential",
]

_client_h = _CapturingClient()
rh = respond("should I captain Haaland", GW28_BOOTSTRAP, client=_client_h)
for fname in _REQUIRED_FIELDS:
    ok(hasattr(rh, fname), f"H: FinalResponse has field '{fname}'")

ok(isinstance(rh.final_text, str) and len(rh.final_text) > 0,
   "H-extra: final_text is non-empty string")

# ---------------------------------------------------------------------------
# Section I: Phase 9b regression
# ---------------------------------------------------------------------------

print("\n=== I: Phase 9b regression ===")

from fpl_grounded_assistant.llm_layer import (
    _MAX_CONTEXT_CHARS,
    _CONTEXT_TRUNCATION_MARKER,
)

prompt = build_system_prompt(GW28_BOOTSTRAP)
ok(SYSTEM_PROMPT in prompt,                          "I1: base SYSTEM_PROMPT present")
ok(len(prompt) > len(SYSTEM_PROMPT),                 "I2: prompt longer than base")
ok(_CONTEXT_SECTION_HEADER.strip() in prompt,        "I3: context header present")
ok(_CONTEXT_SECTION_FOOTER.strip() in prompt,        "I4: context footer present")
ok("GW28" in prompt,                                 "I5: GW28 in prompt")
ok("Do NOT fabricate" in prompt,                     "I6: safety rule present")

# Truncation still works
fat_bs = copy.deepcopy(STANDARD_BOOTSTRAP)
base_el = fat_bs["elements"][0].copy()
for i in range(500):
    el = base_el.copy()
    el["id"] = 2000 + i
    el["web_name"] = f"FatPlayer{i:04d}"
    fat_bs["elements"].append(el)
fat_prompt = build_system_prompt(fat_bs)
ctx_fat = build_orchestration_context(fat_bs)
if len(ctx_fat) > _MAX_CONTEXT_CHARS:
    ok(_CONTEXT_TRUNCATION_MARKER.strip() in fat_prompt,
       "I7: truncation marker present for oversized bootstrap")
else:
    ok(isinstance(fat_prompt, str), "I7: oversized bootstrap still returns string")

# Fallback still works
import fpl_grounded_assistant.context_builder as _cb2
_orig2 = _cb2.build_orchestration_context
_cb2.build_orchestration_context = lambda bs: (_ for _ in ()).throw(RuntimeError("fail"))
try:
    fb_prompt = build_system_prompt(GW28_BOOTSTRAP)
    ok(fb_prompt == SYSTEM_PROMPT, "I8: fallback == SYSTEM_PROMPT on exception")
except Exception:
    ok(False, "I8: build_system_prompt raised on exception (should not)")
finally:
    _cb2.build_orchestration_context = _orig2

# ---------------------------------------------------------------------------
# Section J: Phase 9a regression
# ---------------------------------------------------------------------------

print("\n=== J: Phase 9a regression ===")

from fpl_grounded_assistant.context_builder import (
    build_orchestration_context,
    build_orchestration_context_dict,
)
from fpl_grounded_assistant.conversation_fixtures import DGW_BOOTSTRAP, BGW_BOOTSTRAP

ctx_dict = build_orchestration_context_dict(STANDARD_BOOTSTRAP)
ok(ctx_dict["gameweek"]["current_gw"] == 28,          "J1: current_gw == 28")
ok(ctx_dict["gw_type"]["gw_type"] == "normal",         "J2: gw_type == normal")
ok(len(ctx_dict["players"]["top_candidates"]) >= 1,    "J3: top_candidates populated")

ctx_text = build_orchestration_context(STANDARD_BOOTSTRAP)
ok("=== FPL Data Context ===" in ctx_text,             "J4: header present")
ok("GW28" in ctx_text,                                 "J5: GW28 in text")
ok("Haaland" in ctx_text,                              "J6: Haaland in text")
ok("GW0" not in ctx_text,                              "J7: no GW0 leak")

ok("DOUBLE GAMEWEEK" in build_orchestration_context(DGW_BOOTSTRAP), "J8: DGW text")
ok("BLANK GAMEWEEK"  in build_orchestration_context(BGW_BOOTSTRAP), "J9: BGW text")

try:
    build_orchestration_context({})
    ok(True, "J10: empty bootstrap no crash")
except Exception as exc:
    ok(False, f"J10: empty bootstrap raised {exc}")

# GW29 bootstrap dict check (new for 9c)
ctx29_dict = build_orchestration_context_dict(GW29_BOOTSTRAP)
ok(ctx29_dict["gameweek"]["current_gw"] == 29, "J11: GW29 bootstrap -> current_gw == 29")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase 9c: {_pass}/{total} assertions passed.")
if _fail:
    print(f"          {_fail} FAILED.")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
