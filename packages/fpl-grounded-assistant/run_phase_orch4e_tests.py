"""
run_phase_orch4e_tests.py
==========================
Phase Orch-4e test runner: contract doc / fixture parity and orch_outcome audit
semantics codified as executable evidence.

Deliverables validated:
  1. FINAL_RESPONSE_CONTRACT.md — orch_outcome field present in table, all 6 non-OK
     outcome strings listed, semantics section present, override order section present,
     multi-intent deferred note present.
  2. http_contract_fixtures.json — orch_outcome field documented in _meta, orch_outcome
     present in at least one ask fixture and one session fixture, orch-specific fixtures
     present.
  3. Runtime invariants — orch_outcome=None when no client (orch OFF), always present as
     field on FinalResponse, unaffected by squad_context overrides.
  4. Override ordering proof — budget fires before hit_warning; chip fires independently;
     combined budget+hit fires both flags; all via _apply_squad_overrides (same helper
     called by both paths).
  5. Deferred multi-intent explicit assertion — sub-calls (_multi_intent_depth>=1) always
     have orch_outcome=None.
  6. Regression — prior orch phases (4a/4b/4c/4d) invariants remain intact.

Sections:
  A  Contract doc content — FINAL_RESPONSE_CONTRACT.md key sections present
  B  Fixture schema — http_contract_fixtures.json orch_outcome coverage
  C  Runtime: orch_outcome field always present on FinalResponse
  D  Runtime: orch_outcome=None when no client (orch not attempted)
  F  Override ordering proof via _apply_squad_overrides
  G  Deferred: sub-calls (depth>=1) always have orch_outcome=None
  I  Regression stack (4a/4b/4c/4d invariants)

Retired (2026-07-12): sections E and H, and the depth=0 assertion in G,
exercised the pre-G2.a orchestration gate inside respond() (patching
`final_response.ask_orchestrated` to inject a mocked OrchestratorResult).
Commit 118d43e ("G2.a delete rollout-isolation surface") removed that gate —
respond() is deterministic-only now, and `ask_orchestrated` no longer exists
as an attribute of final_response — so those sections tested a code path that
no longer exists. `_orch_result_to_final_response` (the function they
indirectly exercised via the gate) is still live, but its only direct callers
are run_phase_orch4a_tests.py and run_phase_orch4b_tests.py — this file never
called it directly. Section labels (A-D, F, G, I) are kept as-is rather than
renumbered, to preserve continuity with FINAL_RESPONSE_CONTRACT.md/git history
references to specific letters.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from dataclasses import fields as dc_fields

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

os.environ.pop("FPL_ORCH_ENABLED", None)
os.environ.pop("FPL_ORCH_PROVIDER", None)

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(cond: bool, label: str, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  [{detail}]"
        print(msg)


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.final_response import (
    FinalResponse,
    TransferMeta,
    ChipAdviceMeta,
    respond,
    _apply_squad_overrides,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_flag(val: str | None) -> None:
    if val is None:
        os.environ.pop("FPL_ORCH_ENABLED", None)
    else:
        os.environ["FPL_ORCH_ENABLED"] = val


_BS = STANDARD_BOOTSTRAP
_CAPTAIN_Q = "should I captain Haaland"
_TRANSFER_Q = "should I sell Saka for Salah"


# ---------------------------------------------------------------------------
# File paths for doc/fixture checks
# ---------------------------------------------------------------------------

_CONTRACT_PATH = os.path.join(_HERE, "FINAL_RESPONSE_CONTRACT.md")
_FIXTURE_PATH  = os.path.join(_HERE, "http_contract_fixtures.json")

with open(_CONTRACT_PATH, encoding="utf-8") as _f:
    _CONTRACT_TEXT = _f.read()

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    _FIXTURES = json.load(_f)


# ===========================================================================
# Section A — Contract doc content: FINAL_RESPONSE_CONTRACT.md key sections
# ===========================================================================

print("\n--- A: Contract doc content ---")

ok(
    "orch_outcome" in _CONTRACT_TEXT,
    "A1 orch_outcome mentioned in contract doc",
)

ok(
    "Orch-4c" in _CONTRACT_TEXT,
    "A2 Orch-4c phase label present in doc",
)

ok(
    "## `orch_outcome`" in _CONTRACT_TEXT,
    "A3 orch_outcome has its own top-level section",
)

ok(
    "Orchestration Audit Field" in _CONTRACT_TEXT,
    "A4 orch_outcome section title includes 'Orchestration Audit Field'",
)

# All 6 non-OK outcome strings listed in the doc
for _outcome_str in ["no_client", "llm_error", "no_tool", "unknown_tool", "tool_error", "tool_result_error"]:
    ok(
        f'`"{_outcome_str}"'  in _CONTRACT_TEXT or f"'{_outcome_str}'" in _CONTRACT_TEXT or f'"{_outcome_str}"' in _CONTRACT_TEXT,
        f"A5.{_outcome_str}  non-OK outcome '{_outcome_str}' documented in contract",
    )

ok(
    "independence" in _CONTRACT_TEXT.lower() or "Independent" in _CONTRACT_TEXT,
    "A6 orch_outcome independence from outcome documented",
)

ok(
    "Override application order" in _CONTRACT_TEXT or "override application order" in _CONTRACT_TEXT.lower(),
    "A7 override application order section present",
)

ok(
    "budget_constraint" in _CONTRACT_TEXT and "hit_warning" in _CONTRACT_TEXT and "chip_unavailable" in _CONTRACT_TEXT,
    "A8 all three override types mentioned in contract",
)

ok(
    "Hard block" in _CONTRACT_TEXT or "hard block" in _CONTRACT_TEXT.lower(),
    "A9 hard-block vs advisory classification documented",
)

ok(
    "Advisory" in _CONTRACT_TEXT or "advisory" in _CONTRACT_TEXT,
    "A10 advisory classification documented",
)

ok(
    "_apply_squad_overrides" in _CONTRACT_TEXT,
    "A11 _apply_squad_overrides helper referenced in contract",
)

ok(
    "multi-intent" in _CONTRACT_TEXT.lower() or "multi_intent" in _CONTRACT_TEXT,
    "A12 multi-intent orch behavior mentioned in contract",
)

ok(
    "_multi_intent_depth" in _CONTRACT_TEXT,
    "A13 _multi_intent_depth bypass mechanism documented",
)

ok(
    "Deferred" in _CONTRACT_TEXT and "sub_responses" in _CONTRACT_TEXT,
    "A14 deferred note for per-sub-response orch_outcome present",
)

ok(
    "CLI" in _CONTRACT_TEXT and "Surface serialization" in _CONTRACT_TEXT,
    "A15 surface serialization section documents CLI/HTTP orch_outcome behavior",
)

# orch_outcome row in the stable fields table
ok(
    "| `orch_outcome`" in _CONTRACT_TEXT,
    "A16 orch_outcome present as a row in the stable fields table",
)

ok(
    "str\\|None" in _CONTRACT_TEXT and "orch_outcome" in _CONTRACT_TEXT,
    "A17 orch_outcome type str|None documented in table",
)


# ===========================================================================
# Section B — Fixture schema: http_contract_fixtures.json orch_outcome coverage
# ===========================================================================

print("\n--- B: Fixture schema coverage ---")

ok(
    "orch_outcome_contract" in _FIXTURES.get("_meta", {}),
    "B1 orch_outcome_contract section present in _meta",
)

_orch_contract = _FIXTURES["_meta"].get("orch_outcome_contract", {})

ok(
    _orch_contract.get("always_present_in_json") is True,
    "B2 always_present_in_json=true documented in orch_outcome_contract",
)

ok(
    "independence_invariant" in _orch_contract,
    "B3 independence_invariant documented in orch_outcome_contract",
)

ok(
    "override_invariant" in _orch_contract,
    "B4 override_invariant documented in orch_outcome_contract",
)

# All 6 non-OK strings in the orch_outcome_contract values
_orch_values = _orch_contract.get("values", {})
for _v in ["no_client", "llm_error", "no_tool", "unknown_tool", "tool_error", "tool_result_error"]:
    ok(
        _v in _orch_values,
        f"B5.{_v}  non-OK value '{_v}' documented in orch_outcome_contract.values",
    )

ok(
    "orch_outcome" in _FIXTURES["_meta"].get("response_stable_fields", {}).get("POST /ask", []),
    "B6 orch_outcome in response_stable_fields for POST /ask",
)

ok(
    "orch_outcome" in _FIXTURES["_meta"].get("response_stable_fields", {}).get("POST /session/{session_id}/ask", []),
    "B7 orch_outcome in response_stable_fields for POST /session/{session_id}/ask",
)

# At least one ask fixture has an orch_outcome field
_ask_fixtures = _FIXTURES.get("ask_fixtures", [])
_ask_with_orch = [f for f in _ask_fixtures if "orch_outcome" in f.get("expected", {}).get("body", {})]
ok(
    len(_ask_with_orch) >= 1,
    f"B8 at least 1 ask fixture documents orch_outcome field (found {len(_ask_with_orch)})",
)

# At least one session fixture has orch_outcome documented
_sess_fixtures = _FIXTURES.get("session_ask_fixtures", [])
_sess_with_orch = [f for f in _sess_fixtures if "orch_outcome" in f.get("expected", {}).get("body", {})]
ok(
    len(_sess_with_orch) >= 1,
    f"B9 at least 1 session fixture documents orch_outcome field (found {len(_sess_with_orch)})",
)

# Orch-specific fixtures present
_orch_fixture_ids = {f["id"] for f in _ask_fixtures}
ok(
    "ask_orch_outcome_always_present" in _orch_fixture_ids,
    "B10 ask_orch_outcome_always_present fixture present",
)

ok(
    "ask_orch_outcome_independence" in _orch_fixture_ids,
    "B11 ask_orch_outcome_independence fixture present",
)

ok(
    "ask_orch_outcome_with_budget_constraint" in _orch_fixture_ids,
    "B12 ask_orch_outcome_with_budget_constraint fixture present",
)


# ===========================================================================
# Section C — Runtime: orch_outcome field always present on FinalResponse
# ===========================================================================

print("\n--- C: Runtime orch_outcome field always present ---")

# FinalResponse must have orch_outcome as a dataclass field
_fr_field_names = {f.name for f in dc_fields(FinalResponse)}
ok(
    "orch_outcome" in _fr_field_names,
    "C1 orch_outcome is a declared field on FinalResponse dataclass",
)

# Default is None
_dummy = FinalResponse(
    final_text="test",
    outcome="ok",
    supported=True,
    intent="captain_score",
    review_passed=True,
    llm_used=False,
    debug=None,
)
ok(
    _dummy.orch_outcome is None,
    "C2 orch_outcome defaults to None on FinalResponse",
)

# respond() with no orch client always returns orch_outcome=None
_set_flag(None)
_r = respond(_CAPTAIN_Q, _BS)
ok(
    hasattr(_r, "orch_outcome"),
    "C3 respond() result has orch_outcome attribute",
)
ok(
    _r.orch_outcome is None,
    "C4 orch_outcome=None when no API client (orch not attempted)",
    detail=f"got {_r.orch_outcome!r}",
)


# ===========================================================================
# Section D — Runtime: orch_outcome=None when no client
# ===========================================================================

print("\n--- D: orch_outcome=None for all intent routes when no client ---")

_ROUTE_QUERIES = [
    ("captain_score",     "should I captain Haaland"),
    ("transfer_advice",   "should I sell Saka for Salah"),
    ("chip_advice",       "should I use bench boost this week"),
    ("compare_players",   "Haaland vs Salah"),
    ("player_fixture_run","Salah fixtures"),
    ("differential_picks","good differentials"),
    ("unsupported",       "Is Haaland fit to play?"),
]

_set_flag(None)
for _intent, _q in _ROUTE_QUERIES:
    _r2 = respond(_q, _BS)
    ok(
        _r2.orch_outcome is None,
        f"D1.{_intent}  orch_outcome=None for '{_intent}' route with no client",
        detail=f"got {_r2.orch_outcome!r}",
    )


# ===========================================================================
# Section F — Override ordering proof via _apply_squad_overrides
# ===========================================================================

print("\n--- F: Override ordering proof via _apply_squad_overrides ---")

# F1: budget fires (step 1); hit_warning also fires when marginal + expensive (step 2)
_transfer_marginal_expensive = TransferMeta(
    player_out="Saka",
    player_in="Son",
    recommendation="marginal_transfer_in",
    score_delta=8.5,
    price_delta=35,    # exceeds itb=20
    reasons=("minor improvement",),
    budget_constraint=False,
    hit_warning=False,
)
_sc_budget_and_hit = {"itb": 20, "free_transfers": 1}
_t1, _c1, _ft1 = _apply_squad_overrides(
    transfer=_transfer_marginal_expensive,
    chip=None,
    final_text="original text",
    squad_context=_sc_budget_and_hit,
)
ok(
    _t1.budget_constraint is True,
    "F1 budget_constraint fires first (step 1) on marginal+expensive transfer",
)
ok(
    _t1.hit_warning is True,
    "F2 hit_warning fires second (step 2) — reads recommendation after budget step (recommendation unchanged)",
)
ok(
    "Budget constraint" in _ft1,
    "F3 final_text is the budget message (hard block; hit_warning is advisory only)",
)

# F4: budget fires alone on clear transfer (recommendation=transfer_in → hit_warning does not fire)
_transfer_clear = TransferMeta(
    player_out="Saka",
    player_in="Salah",
    recommendation="transfer_in",
    score_delta=24.23,
    price_delta=35,
    reasons=("stronger form",),
    budget_constraint=False,
    hit_warning=False,
)
_t2, _c2, _ft2 = _apply_squad_overrides(
    transfer=_transfer_clear,
    chip=None,
    final_text="original",
    squad_context={"itb": 20, "free_transfers": 1},
)
ok(
    _t2.budget_constraint is True,
    "F4 budget_constraint fires on clear transfer when price_delta > itb",
)
ok(
    _t2.hit_warning is False,
    "F5 hit_warning does NOT fire on clear transfer (recommendation='transfer_in')",
)

# F6: hit_warning alone fires (affordable marginal transfer + 1 free transfer)
_transfer_marginal_cheap = TransferMeta(
    player_out="Saka",
    player_in="Son",
    recommendation="marginal_transfer_in",
    score_delta=8.5,
    price_delta=15,
    reasons=("minor improvement",),
    budget_constraint=False,
    hit_warning=False,
)
_t3, _c3, _ft3 = _apply_squad_overrides(
    transfer=_transfer_marginal_cheap,
    chip=None,
    final_text="original",
    squad_context={"itb": 100, "free_transfers": 1},
)
ok(
    _t3.budget_constraint is False,
    "F6 budget_constraint does NOT fire when price_delta <= itb",
)
ok(
    _t3.hit_warning is True,
    "F7 hit_warning fires on marginal+affordable transfer with free_transfers=1",
)
ok(
    _ft3 == "original",
    "F8 hit_warning is advisory — final_text is NOT overridden",
    detail=f"got {_ft3!r}",
)

# F9: chip_unavailable fires (step 3), independent of transfer overrides
_chip_bb = ChipAdviceMeta(
    chip="bench_boost",
    recommendation="conditions_favorable",
    gw=29,
    signal_value=72.5,
    signal_label="top captain score",
    chip_unavailable=False,
)
_t4, _c4, _ft4 = _apply_squad_overrides(
    transfer=None,
    chip=_chip_bb,
    final_text="chip original",
    squad_context={"chips_remaining": ["triple_captain", "wildcard"]},
)
ok(
    _c4.chip_unavailable is True,
    "F9 chip_unavailable fires when chip not in chips_remaining (step 3)",
)
ok(
    "Chip unavailable" in _ft4,
    "F10 chip_unavailable overrides final_text (hard block)",
)

# F11: order proof — budget and chip can co-fire in same turn
_t5, _c5, _ft5 = _apply_squad_overrides(
    transfer=_transfer_clear,
    chip=_chip_bb,
    final_text="original",
    squad_context={"itb": 20, "chips_remaining": ["wildcard"]},
)
ok(
    _t5.budget_constraint is True and _c5.chip_unavailable is True,
    "F11 budget_constraint and chip_unavailable can both fire in same turn",
)

# F12: no overrides when squad_context=None
_t6, _c6, _ft6 = _apply_squad_overrides(
    transfer=_transfer_clear,
    chip=_chip_bb,
    final_text="original",
    squad_context=None,
)
ok(
    _t6.budget_constraint is False and _c6.chip_unavailable is False,
    "F12 no overrides when squad_context=None",
)
ok(
    _ft6 == "original",
    "F13 final_text unchanged when squad_context=None",
)


# ===========================================================================
# Section G — Deferred: sub-calls (depth=1) always have orch_outcome=None
# ===========================================================================

print("\n--- G: Deferred multi-intent sub-call orch_outcome=None ---")

_set_flag("1")
_r_depth1 = respond(_CAPTAIN_Q, _BS, _multi_intent_depth=1)
ok(
    _r_depth1.orch_outcome is None,
    "G1 orch_outcome=None when _multi_intent_depth=1 (sub-call bypasses orch gate)",
    detail=f"got {_r_depth1.orch_outcome!r}",
)

_r_depth2 = respond(_CAPTAIN_Q, _BS, _multi_intent_depth=2)
ok(
    _r_depth2.orch_outcome is None,
    "G2 orch_outcome=None when _multi_intent_depth=2 (any depth > 0 bypasses)",
    detail=f"got {_r_depth2.orch_outcome!r}",
)

_set_flag(None)


# ===========================================================================
# Section I — Regression stack (Orch-4a/4b/4c/4d invariants)
# ===========================================================================

print("\n--- I: Regression stack ---")

_set_flag(None)

# Orch-4a: respond() never raises
try:
    _r_i1 = respond(_CAPTAIN_Q, _BS)
    ok(True, "I1 respond() does not raise (Orch-4a invariant)")
except Exception as _e:
    ok(False, "I1 respond() does not raise", detail=str(_e))

# Orch-4b: success-path metadata (captain) populated on OK turn
ok(
    _r_i1.captain is not None,
    "I2 captain metadata populated on captain_score OK turn (Orch-4b invariant)",
)

# Orch-4b: final_text non-empty on all routes
for _intent, _q in _ROUTE_QUERIES:
    _r_i2 = respond(_q, _BS)
    ok(
        len(_r_i2.final_text) > 0,
        f"I3.{_intent}  final_text non-empty (Orch-4b invariant)",
    )

# Orch-4c: orch_outcome is an attribute on every FinalResponse
_r_i3 = respond("good differentials", _BS)
ok(
    hasattr(_r_i3, "orch_outcome"),
    "I4 orch_outcome attribute present on FinalResponse (Orch-4c invariant)",
)

# Orch-4d: _apply_squad_overrides is importable and callable
try:
    _t_i, _c_i, _ft_i = _apply_squad_overrides(
        transfer=None, chip=None, final_text="test", squad_context=None
    )
    ok(True, "I5 _apply_squad_overrides importable and callable (Orch-4d invariant)")
    ok(_t_i is None and _c_i is None and _ft_i == "test", "I6 _apply_squad_overrides returns (None, None, unchanged) when no overrides")
except Exception as _e:
    ok(False, "I5 _apply_squad_overrides importable and callable", detail=str(_e))
    ok(False, "I6 _apply_squad_overrides returns expected no-op result")

# Orch-4d: squad_context budget_constraint fires on deterministic path
_r_i4 = respond(_TRANSFER_Q, _BS, squad_context={"itb": 5})
ok(
    _r_i4.transfer is not None and _r_i4.transfer.budget_constraint is True,
    "I7 budget_constraint fires on deterministic path (Orch-4d invariant)",
)

# Orch-4d: chip_unavailable fires on deterministic path
_CHIP_Q = "should I use bench boost this week"
_r_i5 = respond(_CHIP_Q, _BS, squad_context={"chips_remaining": ["wildcard"]})
ok(
    _r_i5.chip is not None and _r_i5.chip.chip_unavailable is True,
    "I8 chip_unavailable fires on deterministic path (Orch-4d invariant)",
)

# Stability: FINAL_RESPONSE_CONTRACT.md file is readable and non-empty
ok(
    len(_CONTRACT_TEXT) > 1000,
    "I9 FINAL_RESPONSE_CONTRACT.md is readable and non-trivially long",
    detail=f"length={len(_CONTRACT_TEXT)}",
)

# Stability: http_contract_fixtures.json is valid JSON with expected top-level keys
ok(
    all(k in _FIXTURES for k in ["_meta", "ask_fixtures", "session_ask_fixtures", "http_status_contract"]),
    "I10 http_contract_fixtures.json has all expected top-level keys",
)


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'='*60}")
print(f"Orch-4e: {_PASS} passed, {_FAIL} failed")
print(f"{'='*60}\n")

if _FAIL > 0:
    sys.exit(1)
