"""
run_phase_orch4d_tests.py
==========================
Phase Orch-4d test runner: _apply_squad_overrides helper contract.

Override rules under test (unchanged semantics from Phase 8e1/8e2):
  budget_constraint  — hard block; final_text replaced when price_delta > itb
  hit_warning        — advisory flag; final_text NOT replaced, flag set only
  chip_unavailable   — hard block; final_text replaced when chip not available

Sections:
  A  _apply_squad_overrides helper surface and basic contract

Retired (2026-07-12): sections B-H — all "orch-success path" parity coverage
(does _apply_squad_overrides fire identically whether respond() got its
answer via orchestration or the deterministic router). Commit 118d43e
("G2.a delete rollout-isolation surface", 2026-05-18) removed the
orchestration gate from respond() entirely — there is no orch-success path
left to compare against, so those sections all patched
final_response.ask_orchestrated (which no longer exists) to simulate one.
Section A calls _apply_squad_overrides directly and needs no orchestrator
mocking at all, so it's untouched and still validates the live helper.
Note: this overlaps substantially with run_phase_orch4e_tests.py's Section F,
which exercises the same helper through the same scenarios (budget, hit
warning, chip unavailable, combined, no-op) — worth consolidating later,
not done here since both currently pass and touch the same live code, not
dead code.
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
    TransferMeta,
    ChipAdviceMeta,
    _apply_squad_overrides,
)


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
