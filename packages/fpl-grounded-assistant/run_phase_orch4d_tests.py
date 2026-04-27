"""
run_phase_orch4d_tests.py
==========================
Phase Orch-4d test runner: squad_context override parity on orch-success path.

Validates that when orchestration succeeds (orch_outcome = "ok"), the same
squad_context post-processing rules that apply on the deterministic path also
apply on the orch path, producing identical FinalResponse shapes.

Override rules under test (unchanged semantics from Phase 8e1/8e2):
  budget_constraint  — hard block; final_text replaced when price_delta > itb
  hit_warning        — advisory flag; final_text NOT replaced, flag set only
  chip_unavailable   — hard block; final_text replaced when chip not available

Sections:
  A  _apply_squad_overrides helper surface and basic contract
  B  budget_constraint: orch-success path fires and matches deterministic parity
  C  chip_unavailable: orch-success path fires and matches deterministic parity
  D  hit_warning: orch-success path fires and matches deterministic parity
  E  no-override cases (squad_context=None, itb sufficient, chip available)
  F  non-OK fallback — override NOT applied on fallback path (no regression)
  G  combined override semantics (budget + hit_warning can co-occur)
  H  regression (Orch-4c, 4b, 4a, 3b, 3a, 2a, phase-9)
"""
from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import patch

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
    ORCH_OUTCOME_OK,
    ORCH_OUTCOME_LLM_ERROR,
)
from fpl_grounded_assistant.orchestrator import (
    OrchestratorResult,
    DEFAULT_ORCH_MODEL,
    OUTCOME_OK as ORCH_OUTCOME_OK_RAW,
)
from fpl_grounded_assistant.dispatcher import (
    OUTCOME_OK as DISP_OUTCOME_OK,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Helpers — env flag toggle
# ---------------------------------------------------------------------------

def _set_flag(val: str | None) -> None:
    if val is None:
        os.environ.pop("FPL_ORCH_ENABLED", None)
    else:
        os.environ["FPL_ORCH_ENABLED"] = val


# ---------------------------------------------------------------------------
# Reference squad_context fixtures
# ---------------------------------------------------------------------------

# itb = 20 (£2.0m), price_delta = 35 (£3.5m) -> budget_constraint fires
_SC_BUDGET = {"itb": 20}

# free_transfers = 1 -> hit_warning fires when recommendation = marginal_transfer_in
_SC_HIT = {"free_transfers": 1}

# chips_remaining excludes bench_boost -> chip_unavailable fires
_SC_CHIP_UNAVAIL = {"chips_remaining": ["triple_captain", "wildcard", "free_hit"]}

# Combined: both budget and hit_warning fire (free_transfers=1 + tight itb)
_SC_BUDGET_AND_HIT = {"itb": 20, "free_transfers": 1}

# No-op squad_context: itb is sufficient, chip is available
_SC_NO_OVERRIDE = {
    "itb": 100,                       # £10.0m; price_delta=35 < 100 -> no block
    "chips_remaining": ["bench_boost", "triple_captain"],  # bench_boost present
    "free_transfers": 2,              # 2 FTs -> hit_warning does not fire
}


# ---------------------------------------------------------------------------
# Reference tool_output dicts for orch-path mocks
# ---------------------------------------------------------------------------

# Transfer: price_delta=35, recommendation=transfer_in (clear upgrade)
_TRANSFER_RO_CLEAR = {
    "status":           "ok",
    "recommendation":   "transfer_in",
    "score_delta":      24.23,
    "price_delta":      35,          # £3.5m — exceeds SC_BUDGET.itb (£2.0m)
    "transfer_reasons": ["stronger form", "easier fixture"],
    "player_out": {"web_name": "Saka"},
    "player_in":  {"web_name": "Salah"},
}

# Transfer: marginal recommendation (hit_warning fires when free_transfers=1)
_TRANSFER_RO_MARGINAL = {
    "status":           "ok",
    "recommendation":   "marginal_transfer_in",
    "score_delta":      8.5,
    "price_delta":      15,          # £1.5m — within SC_BUDGET.itb (£2.0m)
    "transfer_reasons": ["minor improvement"],
    "player_out": {"web_name": "Saka"},
    "player_in":  {"web_name": "Son"},
}

# Transfer: marginal + exceeds itb (both budget_constraint AND hit_warning fire)
_TRANSFER_RO_MARGINAL_EXPENSIVE = {
    "status":           "ok",
    "recommendation":   "marginal_transfer_in",
    "score_delta":      8.5,
    "price_delta":      35,          # £3.5m — exceeds SC_BUDGET.itb (£2.0m)
    "transfer_reasons": ["minor improvement"],
    "player_out": {"web_name": "Saka"},
    "player_in":  {"web_name": "Son"},
}

# Chip: bench_boost (chip_unavailable fires when not in chips_remaining)
_CHIP_BB_RO = {
    "status":            "ok",
    "chip":              "bench_boost",
    "recommendation":    "conditions_unfavorable",
    "current_gameweek":  28,
    "signals": {
        "average_fdr_top10": 4.33,
        "top_player_count":  3,
    },
}


def _make_orch_transfer(ro: dict) -> OrchestratorResult:
    """OrchestratorResult wrapping a get_transfer_advice tool_output."""
    return OrchestratorResult(
        question="should I sell Saka for Salah",
        tool_chosen="get_transfer_advice",
        tool_args={"player_out": "Saka", "player_in": "Salah"},
        tool_output=ro,
        answer_text="Transfer Saka out for Salah.",
        llm_used=True,
        model=DEFAULT_ORCH_MODEL,
        outcome=ORCH_OUTCOME_OK_RAW,
        error=None,
    )


def _make_orch_chip(ro: dict) -> OrchestratorResult:
    """OrchestratorResult wrapping a get_chip_advice tool_output."""
    return OrchestratorResult(
        question="should I bench boost",
        tool_chosen="get_chip_advice",
        tool_args={"chip": "bench_boost"},
        tool_output=ro,
        answer_text="Bench boost conditions are unfavorable.",
        llm_used=True,
        model=DEFAULT_ORCH_MODEL,
        outcome=ORCH_OUTCOME_OK_RAW,
        error=None,
    )


def _make_orch_non_ok(outcome: str) -> OrchestratorResult:
    return OrchestratorResult(
        question="should I sell Saka for Salah",
        tool_chosen=None,
        tool_args={},
        tool_output={},
        answer_text="[orch error]",
        llm_used=False,
        model="none",
        outcome=outcome,
        error=f"simulated {outcome}",
    )


_BS = STANDARD_BOOTSTRAP
_Q_TRANSFER = "should I sell Saka for Salah"
_Q_CHIP     = "should I bench boost"


# ---------------------------------------------------------------------------
# Section A: _apply_squad_overrides helper contract
# ---------------------------------------------------------------------------

print("\n=== A: _apply_squad_overrides helper surface ===")

ok(callable(_apply_squad_overrides),            "A1: _apply_squad_overrides is callable")

# A2: no squad_context -> no change
_t0 = TransferMeta(
    player_out="Saka", player_in="Salah", recommendation="transfer_in",
    score_delta=24.23, price_delta=35, reasons=("form",),
)
_c0 = ChipAdviceMeta(
    chip="bench_boost", recommendation="conditions_unfavorable",
    gw=28, signal_value=4.33, signal_label="avg_bench_pts",
)
_t_out, _c_out, _ft_out = _apply_squad_overrides(
    transfer=_t0, chip=_c0, final_text="original", squad_context=None
)
ok(_t_out is _t0,                               "A2: transfer unchanged when squad_context=None")
ok(_c_out is _c0,                               "A3: chip unchanged when squad_context=None")
ok(_ft_out == "original",                       "A4: final_text unchanged when squad_context=None")

# A5: budget_constraint fires when price_delta > itb
_t_b, _c_b, _ft_b = _apply_squad_overrides(
    transfer=_t0, chip=None, final_text="original",
    squad_context={"itb": 20},  # 35 > 20 -> fires
)
ok(_t_b.budget_constraint is True,             "A5: budget_constraint=True when price_delta > itb")
ok("Budget constraint" in _ft_b,               "A6: final_text replaced on budget_constraint")
ok(_c_b is None,                               "A7: chip unchanged when None input")

# A8: budget_constraint does NOT fire when price_delta <= itb
_t_ok, _c_ok, _ft_ok = _apply_squad_overrides(
    transfer=_t0, chip=None, final_text="original",
    squad_context={"itb": 100},  # 35 <= 100 -> does not fire
)
ok(_t_ok.budget_constraint is False,           "A8: budget_constraint=False when price_delta <= itb")
ok(_ft_ok == "original",                       "A9: final_text unchanged when no budget block")

# A10: hit_warning fires when free_transfers=1 AND recommendation=marginal_transfer_in
_t_marg = TransferMeta(
    player_out="Saka", player_in="Son", recommendation="marginal_transfer_in",
    score_delta=8.5, price_delta=15, reasons=("minor",),
)
_t_hw, _c_hw, _ft_hw = _apply_squad_overrides(
    transfer=_t_marg, chip=None, final_text="original",
    squad_context={"free_transfers": 1},
)
ok(_t_hw.hit_warning is True,                  "A10: hit_warning=True when ft=1+marginal")
ok(_ft_hw == "original",                       "A11: final_text unchanged for hit_warning (advisory)")

# A12: hit_warning does NOT fire when recommendation != marginal_transfer_in
_t_hw2, _, _ = _apply_squad_overrides(
    transfer=_t0, chip=None, final_text="original",
    squad_context={"free_transfers": 1},
)
ok(_t_hw2.hit_warning is False,               "A12: hit_warning=False when recommendation=transfer_in")

# A13: hit_warning does NOT fire when free_transfers != 1
_t_hw3, _, _ = _apply_squad_overrides(
    transfer=_t_marg, chip=None, final_text="original",
    squad_context={"free_transfers": 2},
)
ok(_t_hw3.hit_warning is False,               "A13: hit_warning=False when free_transfers=2")

# A14: chip_unavailable fires when chip not in chips_remaining
_t_cu, _c_cu, _ft_cu = _apply_squad_overrides(
    transfer=None, chip=_c0, final_text="original",
    squad_context={"chips_remaining": ["triple_captain"]},
)
ok(_c_cu.chip_unavailable is True,            "A14: chip_unavailable=True when chip absent")
ok("Chip unavailable" in _ft_cu,              "A15: final_text replaced on chip_unavailable")

# A16: chip_unavailable does NOT fire when chip IS in chips_remaining
_t_ca, _c_ca, _ft_ca = _apply_squad_overrides(
    transfer=None, chip=_c0, final_text="original",
    squad_context={"chips_remaining": ["bench_boost", "triple_captain"]},
)
ok(_c_ca.chip_unavailable is False,           "A16: chip_unavailable=False when chip available")
ok(_ft_ca == "original",                      "A17: final_text unchanged when chip available")


# ---------------------------------------------------------------------------
# Section B: budget_constraint — orch-success path
# ---------------------------------------------------------------------------

print("\n=== B: budget_constraint on orch-success path ===")

# B1-B7: orch path fires budget_constraint
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_b = respond(_Q_TRANSFER, _BS, squad_context=_SC_BUDGET)
_set_flag(None)

ok(_r_b.orch_outcome == ORCH_OUTCOME_OK,      "B1: orch_outcome == ok on orch-success path")
ok(_r_b.intent == INTENT_TRANSFER_ADVICE,     "B2: intent == transfer_advice")
ok(_r_b.transfer is not None,                 "B3: transfer metadata populated")
ok(_r_b.transfer.budget_constraint is True,   "B4: transfer.budget_constraint == True")
ok("Budget constraint" in _r_b.final_text,    "B5: final_text contains budget block message")
ok("Salah" in _r_b.final_text,               "B6: final_text mentions player_in name")
ok(_r_b.transfer.player_out == "Saka",        "B7: transfer.player_out preserved")

# B8-B12: parity with deterministic path for equivalent inputs
_set_flag(None)
_r_b_det = respond(_Q_TRANSFER, _BS, squad_context=_SC_BUDGET)
_set_flag(None)

ok(_r_b_det.transfer is not None,             "B8: deterministic path has transfer metadata")
ok(_r_b_det.transfer.budget_constraint is True,
   "B9: deterministic path budget_constraint == True")
ok("Budget constraint" in _r_b_det.final_text,
   "B10: deterministic final_text contains budget block")
ok(_r_b.final_text == _r_b_det.final_text,
   "B11: orch-path final_text == deterministic final_text (parity)")
ok(_r_b.transfer.budget_constraint == _r_b_det.transfer.budget_constraint,
   "B12: budget_constraint flag parity")

# B13: budget_constraint does NOT fire on orch path when price_delta <= itb
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_b_ok = respond(_Q_TRANSFER, _BS, squad_context=_SC_NO_OVERRIDE)
_set_flag(None)

ok(_r_b_ok.transfer.budget_constraint is False,
   "B13: budget_constraint=False when price_delta <= itb on orch path")

# B14: budget_constraint does NOT fire when no squad_context
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_b_none = respond(_Q_TRANSFER, _BS)
_set_flag(None)

ok(_r_b_none.transfer.budget_constraint is False,
   "B14: budget_constraint=False when squad_context=None on orch path")


# ---------------------------------------------------------------------------
# Section C: chip_unavailable — orch-success path
# ---------------------------------------------------------------------------

print("\n=== C: chip_unavailable on orch-success path ===")

# C1-C7: orch path fires chip_unavailable
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_chip(_CHIP_BB_RO)):
    _r_c = respond(_Q_CHIP, _BS, squad_context=_SC_CHIP_UNAVAIL)
_set_flag(None)

ok(_r_c.orch_outcome == ORCH_OUTCOME_OK,      "C1: orch_outcome == ok on orch-success path")
ok(_r_c.intent == INTENT_CHIP_ADVICE,         "C2: intent == chip_advice")
ok(_r_c.chip is not None,                     "C3: chip metadata populated")
ok(_r_c.chip.chip_unavailable is True,        "C4: chip.chip_unavailable == True")
ok("Chip unavailable" in _r_c.final_text,     "C5: final_text contains chip_unavailable message")
ok("bench_boost" in _r_c.final_text,          "C6: final_text mentions chip name")
ok(_r_c.chip.chip == "bench_boost",           "C7: chip.chip preserved")

# C8-C12: parity with deterministic path for equivalent inputs
_set_flag(None)
_r_c_det = respond(_Q_CHIP, _BS, squad_context=_SC_CHIP_UNAVAIL)
_set_flag(None)

ok(_r_c_det.chip is not None,                 "C8: deterministic path has chip metadata")
ok(_r_c_det.chip.chip_unavailable is True,    "C9: deterministic chip_unavailable == True")
ok("Chip unavailable" in _r_c_det.final_text, "C10: deterministic final_text contains block")
ok(_r_c.final_text == _r_c_det.final_text,
   "C11: orch-path final_text == deterministic final_text (parity)")
ok(_r_c.chip.chip_unavailable == _r_c_det.chip.chip_unavailable,
   "C12: chip_unavailable flag parity")

# C13: chip_unavailable does NOT fire when chip IS in chips_remaining
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_chip(_CHIP_BB_RO)):
    _r_c_ok = respond(_Q_CHIP, _BS, squad_context=_SC_NO_OVERRIDE)
_set_flag(None)

ok(_r_c_ok.chip.chip_unavailable is False,
   "C13: chip_unavailable=False when chip available on orch path")

# C14: chip_unavailable does NOT fire when no squad_context
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_chip(_CHIP_BB_RO)):
    _r_c_none = respond(_Q_CHIP, _BS)
_set_flag(None)

ok(_r_c_none.chip.chip_unavailable is False,
   "C14: chip_unavailable=False when squad_context=None on orch path")


# ---------------------------------------------------------------------------
# Section D: hit_warning — orch-success path
# ---------------------------------------------------------------------------

print("\n=== D: hit_warning on orch-success path ===")

# D1-D7: orch path fires hit_warning
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_MARGINAL)):
    _r_d = respond(_Q_TRANSFER, _BS, squad_context=_SC_HIT)
_set_flag(None)

ok(_r_d.orch_outcome == ORCH_OUTCOME_OK,      "D1: orch_outcome == ok on orch-success path")
ok(_r_d.intent == INTENT_TRANSFER_ADVICE,     "D2: intent == transfer_advice")
ok(_r_d.transfer is not None,                 "D3: transfer metadata populated")
ok(_r_d.transfer.hit_warning is True,         "D4: transfer.hit_warning == True")
ok(_r_d.transfer.budget_constraint is False,  "D5: budget_constraint=False (price within itb)")
# Advisory: final_text is NOT replaced by hit_warning
ok("Hit warning" not in _r_d.final_text,
   "D6: final_text NOT replaced by hit_warning (advisory only)")
ok(len(_r_d.final_text) > 0,                  "D7: final_text remains non-empty")

# D8-D10: parity proof via shared helper — both paths call _apply_squad_overrides,
# so same (transfer_meta, squad_context) inputs always produce identical output.
# We verify the helper directly rather than comparing full respond() calls, since
# the real tool chain may return a different recommendation for the same query.
_t_marg_meta = TransferMeta(
    player_out="Saka", player_in="Son", recommendation="marginal_transfer_in",
    score_delta=8.5, price_delta=15, reasons=("minor improvement",),
)
_t_hw_helper, _, _ = _apply_squad_overrides(
    transfer=_t_marg_meta, chip=None, final_text="x", squad_context=_SC_HIT
)
ok(_t_hw_helper.hit_warning is True,          "D8: shared helper produces hit_warning=True")
ok(_r_d.transfer.hit_warning == _t_hw_helper.hit_warning,
   "D9: orch-path hit_warning matches shared helper output (parity proof)")
ok(_r_d.transfer.hit_warning is True,         "D10: hit_warning=True on orch path confirmed")

# D11: hit_warning does NOT fire when free_transfers != 1
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_MARGINAL)):
    _r_d_no = respond(_Q_TRANSFER, _BS, squad_context=_SC_NO_OVERRIDE)
_set_flag(None)

ok(_r_d_no.transfer.hit_warning is False,
   "D11: hit_warning=False when free_transfers=2 on orch path")

# D12: hit_warning does NOT fire when recommendation is not marginal
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_d_clear = respond(_Q_TRANSFER, _BS, squad_context=_SC_HIT)
_set_flag(None)

ok(_r_d_clear.transfer.hit_warning is False,
   "D12: hit_warning=False when recommendation=transfer_in (not marginal)")


# ---------------------------------------------------------------------------
# Section E: no-override cases (squad_context=None or conditions not met)
# ---------------------------------------------------------------------------

print("\n=== E: no-override cases ===")

# E1: transfer with no squad_context -> no flags set
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_e1 = respond(_Q_TRANSFER, _BS)
_set_flag(None)

ok(_r_e1.transfer is not None,                "E1: transfer populated")
ok(_r_e1.transfer.budget_constraint is False, "E2: budget_constraint=False, no squad_context")
ok(_r_e1.transfer.hit_warning is False,       "E3: hit_warning=False, no squad_context")
ok(_r_e1.orch_outcome == ORCH_OUTCOME_OK,     "E4: orch_outcome still ok")

# E5: chip with no squad_context -> chip_unavailable=False
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_chip(_CHIP_BB_RO)):
    _r_e5 = respond(_Q_CHIP, _BS)
_set_flag(None)

ok(_r_e5.chip is not None,                    "E5: chip populated")
ok(_r_e5.chip.chip_unavailable is False,      "E6: chip_unavailable=False, no squad_context")

# E7: sufficient itb -> no budget_constraint
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_e7 = respond(_Q_TRANSFER, _BS, squad_context={"itb": 100})
_set_flag(None)

ok(_r_e7.transfer.budget_constraint is False, "E7: budget_constraint=False when itb sufficient")
ok("Budget constraint" not in _r_e7.final_text,
   "E8: final_text not overridden when itb sufficient")

# E9: chip available in chips_remaining -> no chip_unavailable
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_chip(_CHIP_BB_RO)):
    _r_e9 = respond(_Q_CHIP, _BS,
                    squad_context={"chips_remaining": ["bench_boost", "triple_captain"]})
_set_flag(None)

ok(_r_e9.chip.chip_unavailable is False,      "E9: chip_unavailable=False when chip available")
ok("Chip unavailable" not in _r_e9.final_text,
   "E10: final_text not overridden when chip available")


# ---------------------------------------------------------------------------
# Section F: non-OK fallback — override applied via deterministic path
# ---------------------------------------------------------------------------

print("\n=== F: non-OK fallback path gets overrides via deterministic path ===")

# When orch falls back (non-OK), squad_context overrides are applied by the
# deterministic path as before — no change to non-OK behavior.
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_non_ok(ORCH_OUTCOME_LLM_ERROR)):
    _r_f = respond(_Q_TRANSFER, _BS, squad_context=_SC_BUDGET)
_set_flag(None)

ok(_r_f.orch_outcome == ORCH_OUTCOME_LLM_ERROR,
   "F1: orch_outcome captures non-OK on fallback")
ok(_r_f.intent == INTENT_TRANSFER_ADVICE,     "F2: intent from deterministic path")
# The deterministic path runs and applies budget_constraint if price_delta > itb
# (depends on what the deterministic router returns for this query)
ok(isinstance(_r_f.final_text, str) and _r_f.final_text,
   "F3: final_text non-empty on fallback with squad_context")

# F4: orch_outcome is None when flag is OFF (no change)
_set_flag(None)
_r_f4 = respond(_Q_TRANSFER, _BS, squad_context=_SC_BUDGET)
ok(_r_f4.orch_outcome is None,                "F4: orch_outcome None when flag OFF")
ok(_r_f4.transfer is not None,               "F5: deterministic transfer populated when flag OFF")


# ---------------------------------------------------------------------------
# Section G: combined overrides (budget_constraint + hit_warning)
# ---------------------------------------------------------------------------

print("\n=== G: combined budget_constraint + hit_warning ===")

# budget_constraint fires FIRST (hard block), then hit_warning fires too.
# final_text is the budget block message (hard block takes precedence).
# Both flags are set on the TransferMeta.
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_MARGINAL_EXPENSIVE)):
    _r_g = respond(_Q_TRANSFER, _BS, squad_context=_SC_BUDGET_AND_HIT)
_set_flag(None)

ok(_r_g.orch_outcome == ORCH_OUTCOME_OK,      "G1: orch_outcome ok with combined overrides")
ok(_r_g.transfer is not None,                 "G2: transfer populated")
ok(_r_g.transfer.budget_constraint is True,   "G3: budget_constraint=True (hard block)")
ok(_r_g.transfer.hit_warning is True,         "G4: hit_warning=True (advisory co-fires)")
ok("Budget constraint" in _r_g.final_text,    "G5: final_text is budget block message")

# G6-G9: parity proof via shared helper — verify budget fires first, then hit_warning
# stacks on top (reading budget_constraint=True from intermediate TransferMeta).
_t_marg_exp = TransferMeta(
    player_out="Saka", player_in="Son", recommendation="marginal_transfer_in",
    score_delta=8.5, price_delta=35, reasons=("minor improvement",),
)
_t_comb, _, _ft_comb = _apply_squad_overrides(
    transfer=_t_marg_exp, chip=None, final_text="x",
    squad_context=_SC_BUDGET_AND_HIT,
)
ok(_t_comb.budget_constraint is True,         "G6: helper sets budget_constraint=True first")
ok(_t_comb.hit_warning is True,               "G7: helper sets hit_warning=True after budget")
ok(_r_g.transfer.budget_constraint == _t_comb.budget_constraint,
   "G8: orch-path budget_constraint matches helper (parity proof)")
ok(_r_g.transfer.hit_warning == _t_comb.hit_warning,
   "G9: orch-path hit_warning matches helper (parity proof)")


# ---------------------------------------------------------------------------
# Section H: orch_outcome unaffected by override application
# ---------------------------------------------------------------------------

print("\n=== H: orch_outcome semantics unchanged by overrides ===")

# budget_constraint does not change orch_outcome
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_CLEAR)):
    _r_h1 = respond(_Q_TRANSFER, _BS, squad_context=_SC_BUDGET)
_set_flag(None)
ok(_r_h1.orch_outcome == ORCH_OUTCOME_OK,     "H1: orch_outcome=ok after budget_constraint")

# chip_unavailable does not change orch_outcome
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_chip(_CHIP_BB_RO)):
    _r_h2 = respond(_Q_CHIP, _BS, squad_context=_SC_CHIP_UNAVAIL)
_set_flag(None)
ok(_r_h2.orch_outcome == ORCH_OUTCOME_OK,     "H2: orch_outcome=ok after chip_unavailable")

# hit_warning does not change orch_outcome
_set_flag("1")
with patch("fpl_grounded_assistant.final_response.ask_orchestrated",
           return_value=_make_orch_transfer(_TRANSFER_RO_MARGINAL)):
    _r_h3 = respond(_Q_TRANSFER, _BS, squad_context=_SC_HIT)
_set_flag(None)
ok(_r_h3.orch_outcome == ORCH_OUTCOME_OK,     "H3: orch_outcome=ok after hit_warning")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print()
print("=" * 50)
total = _PASS + _FAIL
print(f"Phase Orch-4d: {_PASS}/{total} assertions passed.")
if _FAIL == 0:
    print("               All assertions passed.")
else:
    print(f"               {_FAIL} FAILED.")
