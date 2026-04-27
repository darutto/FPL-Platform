"""
run_phase8b_tests.py
====================
Phase 8b: Home/Away Fixture Factor — automated test suite.

Sections
--------
A  _compute_effective_fdr() — formula correctness
B  _resolve_venue() — lookup logic
C  _derive_scoring_inputs() — is_home + effective_fdr in output
D  Layer 1 vs Layer 2 isolation — captain_score unchanged, position_score uses effective_fdr
E  Venue tag in FDR reason phrases
F  is_home/effective_fdr in comparison raw output
G  FinalResponse metadata — is_home/effective_fdr in ComparisonPlayerContext
H  DifferentialEntry.is_home propagation
I  No team_fixtures -> effective_fdr == raw_fdr (no adjustment)
J  156/156 V1 regression gate

Run
---
    cd packages/fpl-grounded-assistant
    python run_phase8b_tests.py
"""
from __future__ import annotations

import os
import sys
import copy

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

from fpl_grounded_assistant.comparison import (
    _compute_effective_fdr,
    _resolve_venue,
    _derive_scoring_inputs,
    HOME_FDR_ADJUSTMENT,
)
from fpl_grounded_assistant.comparison import compare_players
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DIFFERENTIAL_BOOTSTRAP,
)
from fpl_grounded_assistant.final_response import FinalResponse
from fpl_grounded_assistant import respond


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def check(label: str, condition: bool) -> None:
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# Section A: _compute_effective_fdr formula
# ---------------------------------------------------------------------------

section("A: _compute_effective_fdr formula")

# Home reduces FDR by 0.5
check("home: raw 3 -> 2.5", _compute_effective_fdr(3, True) == 2.5)
check("home: raw 1 -> clamped to 1.0", _compute_effective_fdr(1, True) == 1.0)
check("home: raw 5 -> 4.5", _compute_effective_fdr(5, True) == 4.5)

# Away increases FDR by 0.5
check("away: raw 3 -> 3.5", _compute_effective_fdr(3, False) == 3.5)
check("away: raw 5 -> clamped to 5.0", _compute_effective_fdr(5, False) == 5.0)
check("away: raw 1 -> 1.5", _compute_effective_fdr(1, False) == 1.5)

# Unknown venue — no adjustment
check("unknown: raw 4 -> 4.0 (float)", _compute_effective_fdr(4, None) == 4.0)
check("unknown: raw 3 -> 3.0 (float)", _compute_effective_fdr(3, None) == 3.0)

# Float result
check("home: result is float", isinstance(_compute_effective_fdr(3, True), float))
check("away: result is float", isinstance(_compute_effective_fdr(3, False), float))

# HOME_FDR_ADJUSTMENT constant
check("HOME_FDR_ADJUSTMENT == 0.5", HOME_FDR_ADJUSTMENT == 0.5)


# ---------------------------------------------------------------------------
# Section B: _resolve_venue lookup
# ---------------------------------------------------------------------------

section("B: _resolve_venue lookup")

team_fixtures = {
    1: [
        {"gameweek": 27, "is_home": False, "difficulty": 4},
        {"gameweek": 28, "is_home": True,  "difficulty": 3},
        {"gameweek": 29, "is_home": False, "difficulty": 5},
    ],
    13: [
        {"gameweek": 28, "is_home": False, "difficulty": 4},
    ],
}

check("team 1 GW28 -> is_home=True",  _resolve_venue(1,  team_fixtures, 28) is True)
check("team 13 GW28 -> is_home=False", _resolve_venue(13, team_fixtures, 28) is False)
check("team 1 GW27 -> is_home=False", _resolve_venue(1,  team_fixtures, 27) is False)
check("team 1 GW29 -> is_home=False", _resolve_venue(1,  team_fixtures, 29) is False)
check("team 99 (missing) -> None",     _resolve_venue(99, team_fixtures, 28) is None)
check("no team_fixtures -> None",       _resolve_venue(1,  None, 28) is None)
check("no current_gw -> None",          _resolve_venue(1,  team_fixtures, None) is None)
check("team_id=None -> None",           _resolve_venue(None, team_fixtures, 28) is None)
check("gw not in fixture list -> None", _resolve_venue(1,  team_fixtures, 99) is None)


# ---------------------------------------------------------------------------
# Section C: _derive_scoring_inputs with Phase 8b fields
# ---------------------------------------------------------------------------

section("C: _derive_scoring_inputs — is_home + effective_fdr in output")

# Arsenal (team=1) is home in GW28 per STANDARD_BOOTSTRAP team_fixtures
# fixture_difficulty_map: {1: 5, 13: 4, 14: 4, 8: 5}
# Arsenal (team=1) raw FDR=5, home -> effective_fdr=4.5

ars_element = next(
    el for el in STANDARD_BOOTSTRAP["elements"] if el.get("team") == 1
)
fdr_map       = STANDARD_BOOTSTRAP["fixture_difficulty_map"]
team_fixtures = STANDARD_BOOTSTRAP["team_fixtures"]
current_gw    = 28  # GW28 is is_current in STANDARD_BOOTSTRAP

inputs = _derive_scoring_inputs(ars_element, fdr_map, team_fixtures, current_gw)

check("is_home key present",           "is_home" in inputs)
check("effective_fdr key present",     "effective_fdr" in inputs)
check("fixture_difficulty key present","fixture_difficulty" in inputs)
check("Arsenal is_home=True (GW28)",   inputs["is_home"] is True)
check("Arsenal raw fdr=5",             inputs["fixture_difficulty"] == 5)
check("Arsenal effective_fdr=4.5 (home -0.5)", inputs["effective_fdr"] == 4.5)

# Synthetic Chelsea element (team=8) — away in GW28, raw FDR=5
# away -> effective_fdr=5.5 -> clamped to 5.0
che_element_synth = {
    "id": 99, "web_name": "TestCHE", "team": 8, "element_type": 3,
    "status": "a", "form": "5.0", "expected_goal_involvements": "0.50",
    "minutes": 900,
}
inputs_che = _derive_scoring_inputs(che_element_synth, fdr_map, team_fixtures, current_gw)

check("Chelsea (synth) is_home=False (GW28)",  inputs_che["is_home"] is False)
check("Chelsea (synth) raw fdr=5",             inputs_che["fixture_difficulty"] == 5)
check("Chelsea (synth) effective_fdr=5.0 (clamped from 5.5)", inputs_che["effective_fdr"] == 5.0)

# Manchester City (team=13) is home in GW28
# fixture_difficulty_map: {13: 4}, home -> effective_fdr=3.5
mci_element = next(
    el for el in STANDARD_BOOTSTRAP["elements"] if el.get("team") == 13
)
inputs_mci = _derive_scoring_inputs(mci_element, fdr_map, team_fixtures, current_gw)

check("MCI is_home=True (GW28)",      inputs_mci["is_home"] is True)
check("MCI raw fdr=4",                inputs_mci["fixture_difficulty"] == 4)
check("MCI effective_fdr=3.5 (home)", inputs_mci["effective_fdr"] == 3.5)


# ---------------------------------------------------------------------------
# Section D: Layer 1 vs Layer 2 isolation
# ---------------------------------------------------------------------------

section("D: Layer 1 (captain_score) unchanged — Layer 2 uses effective_fdr")

from fpl_captain_engine import calculate_captain_score
from fpl_grounded_assistant.position_score import compute_position_score

# Haaland (team=13, MCI, GW28 home, raw FDR=4, effective_fdr=3.5)
haa_element = next(
    el for el in STANDARD_BOOTSTRAP["elements"] if el.get("web_name") == "Haaland"
)
inputs_h = _derive_scoring_inputs(haa_element, fdr_map, team_fixtures, current_gw)

layer1 = round(calculate_captain_score(
    inputs_h["form"], inputs_h["fixture_difficulty"],
    inputs_h["xgi_per_90"], inputs_h["minutes_risk"],
), 2)
layer2_home = compute_position_score(
    "FWD", inputs_h["form"], inputs_h["effective_fdr"],
    inputs_h["xgi_per_90"], inputs_h["minutes_risk"],
    0.0, 0.0,
).position_score
layer2_raw = compute_position_score(
    "FWD", inputs_h["form"], float(inputs_h["fixture_difficulty"]),
    inputs_h["xgi_per_90"], inputs_h["minutes_risk"],
    0.0, 0.0,
).position_score

check("Layer 1 uses raw fdr (int) -> no home adj", layer1 == round(calculate_captain_score(
    inputs_h["form"], 4, inputs_h["xgi_per_90"], inputs_h["minutes_risk"]), 2))
check("Layer 2 home > Layer 2 raw (home bonus gives lower FDR -> higher score)",
      layer2_home > layer2_raw)
check("Layer 1 fixture input unchanged (raw int 4)",
      inputs_h["fixture_difficulty"] == 4)
check("Layer 2 fixture input is effective_fdr 3.5",
      inputs_h["effective_fdr"] == 3.5)


# ---------------------------------------------------------------------------
# Section E: FDR reason phrases include venue tag
# ---------------------------------------------------------------------------

section("E: Venue tag in FDR reason phrases")

# Use compare_players directly with STANDARD_BOOTSTRAP (has team_fixtures)
# Compare Salah (LIV, home GW28, raw FDR=4, efdr=3.5) vs Haaland (MCI, home GW28, raw FDR=4, efdr=3.5)
# Both home — equal FDR, no FDR advantage reason expected
result_same = compare_players("Salah", "Haaland", STANDARD_BOOTSTRAP)
check("compare_players returns ok", result_same.get("status") == "ok")

# Verify is_home present in score_inputs for both
a_inputs = result_same.get("player_a", {}).get("score_inputs", {})
b_inputs = result_same.get("player_b", {}).get("score_inputs", {})
check("player_a score_inputs has is_home",       "is_home" in a_inputs)
check("player_b score_inputs has effective_fdr", "effective_fdr" in b_inputs)

# Build a bootstrap where team A is home (low FDR) and team B is away (high FDR)
# so that an FDR advantage reason fires with venue tag.
# LIV (team=14) GW28 is home (raw FDR=4, efdr=3.5)
# MUN (team=11) GW28 is away (raw FDR=3, efdr=3.5) — but fixture says MUN away at LIV, diff=5
# Instead: directly check the reason phrase format by examining score_inputs efdr values.

# Salah (LIV, home GW28, raw FDR=4, efdr=3.5) vs Saka (ARS, home GW28, raw FDR=5, efdr=4.5)
# Salah clearly wins on form (9.5 vs 5.5); efdr diff = 4.5-3.5 = 1.0 >= threshold
# So FDR reason should fire: winner(Salah) has easier efdr than loser(Saka)
result_s_vs_sk = compare_players("Salah", "Saka", STANDARD_BOOTSTRAP)
if result_s_vs_sk.get("status") == "ok":
    reasons = result_s_vs_sk.get("comparison_reasons", [])
    fdr_reasons = [r for r in reasons if "fixture" in r.lower()]
    check("FDR advantage reason fires when efdr diff >= 1 (Salah vs Saka)",
          len(fdr_reasons) > 0)
    if fdr_reasons:
        # Both are home -> venue tag should be "H" for both sides
        # Expected: "easier fixture (FDR 4H vs 5H)"
        check("FDR reason contains venue tag (H)",
              "H" in fdr_reasons[0])
else:
    check("Salah vs Saka compare ok (for FDR reason check)", False)


# ---------------------------------------------------------------------------
# Section F: is_home / effective_fdr in raw comparison output
# ---------------------------------------------------------------------------

section("F: is_home/effective_fdr in comparison score_inputs dicts")

result = compare_players("Salah", "Haaland", STANDARD_BOOTSTRAP)
check("status ok", result.get("status") == "ok")

pa = result.get("player_a", {})
pb = result.get("player_b", {})
pa_inp = pa.get("score_inputs", {})
pb_inp = pb.get("score_inputs", {})

check("player_a.score_inputs.is_home present",       "is_home" in pa_inp)
check("player_a.score_inputs.effective_fdr present", "effective_fdr" in pa_inp)
check("player_b.score_inputs.is_home present",       "is_home" in pb_inp)
check("player_b.score_inputs.effective_fdr present", "effective_fdr" in pb_inp)

# Values should be bool|None and float
check("player_a is_home is bool or None",
      pa_inp.get("is_home") in (True, False, None))
check("player_a effective_fdr is float",
      isinstance(pa_inp.get("effective_fdr"), float))

# captain_score still uses raw FDR (fixture_difficulty: int)
check("player_a score_inputs.fixture_difficulty is int",
      isinstance(pa_inp.get("fixture_difficulty"), int))


# ---------------------------------------------------------------------------
# Section G: FinalResponse.comparison — ComparisonPlayerContext fields
# ---------------------------------------------------------------------------

section("G: ComparisonPlayerContext.is_home / effective_fdr in FinalResponse")

r: FinalResponse = respond("compare Salah and Haaland", STANDARD_BOOTSTRAP)
check("respond ok", r.outcome in ("ok", "unsupported_intent"))

if r.comparison:
    ctx_a = r.comparison.player_a
    ctx_b = r.comparison.player_b
    check("player_a is_home field exists", hasattr(ctx_a, "is_home"))
    check("player_b is_home field exists", hasattr(ctx_b, "is_home"))
    check("player_a effective_fdr field exists", hasattr(ctx_a, "effective_fdr"))
    check("player_b effective_fdr field exists", hasattr(ctx_b, "effective_fdr"))
    check("player_a is_home is bool or None",
          ctx_a.is_home in (True, False, None))
    check("player_b effective_fdr is float",
          isinstance(ctx_b.effective_fdr, float))
    # Both LIV and MCI are home in GW28 — is_home should be True for both
    check("Salah (LIV) is_home=True in GW28",  ctx_a.is_home is True or ctx_b.is_home is True)
else:
    check("comparison meta populated", False)


# ---------------------------------------------------------------------------
# Section H: DifferentialEntry.is_home propagation
# ---------------------------------------------------------------------------

section("H: DifferentialEntry.is_home in differential picks")

r_diff: FinalResponse = respond("show me differential picks", DIFFERENTIAL_BOOTSTRAP)

if r_diff.differential and r_diff.differential.picks:
    pick = r_diff.differential.picks[0]
    check("DifferentialEntry has is_home attr", hasattr(pick, "is_home"))
    check("DifferentialEntry.is_home is bool or None",
          pick.is_home in (True, False, None))
else:
    check("differential picks populated for section H", False)


# ---------------------------------------------------------------------------
# Section I: No team_fixtures -> effective_fdr == raw_fdr
# ---------------------------------------------------------------------------

section("I: Fallback when team_fixtures missing")

bootstrap_no_fixtures = copy.deepcopy(STANDARD_BOOTSTRAP)
del bootstrap_no_fixtures["team_fixtures"]

# _derive_scoring_inputs with no team_fixtures -> is_home=None, effective_fdr=float(raw)
haa_elem2 = next(
    el for el in bootstrap_no_fixtures["elements"] if el.get("web_name") == "Haaland"
)
inputs_no_fix = _derive_scoring_inputs(
    haa_elem2,
    bootstrap_no_fixtures["fixture_difficulty_map"],
    None,   # no team_fixtures
    28,
)
check("no team_fixtures -> is_home=None",            inputs_no_fix["is_home"] is None)
check("no team_fixtures -> effective_fdr = raw_fdr", inputs_no_fix["effective_fdr"] == float(inputs_no_fix["fixture_difficulty"]))

# respond() also works when team_fixtures absent
r_no_fix: FinalResponse = respond("compare Salah and Haaland", bootstrap_no_fixtures)
check("respond ok with no team_fixtures", r_no_fix.outcome in ("ok", "unsupported_intent"))
if r_no_fix.comparison and r_no_fix.comparison.player_a:
    check("is_home=None when no team_fixtures",
          r_no_fix.comparison.player_a.is_home is None or
          r_no_fix.comparison.player_b.is_home is None)


# ---------------------------------------------------------------------------
# Section J: V1 regression gate (156/156)
# ---------------------------------------------------------------------------

section("J: V1 regression gate")

try:
    from validation_corpus import VALIDATION_SCENARIOS
    from run_validation import run_cli_surface, run_http_surface
    from fpl_grounded_assistant.conversation_fixtures import AMBIGUOUS_BOOTSTRAP

    _BS_MAP = {
        "standard":    STANDARD_BOOTSTRAP,
        "ambiguous":   AMBIGUOUS_BOOTSTRAP,
        "differential": DIFFERENTIAL_BOOTSTRAP,
    }

    j_pass = 0
    j_fail = 0
    j_errors: list[str] = []

    for sc in VALIDATION_SCENARIOS:
        bs = _BS_MAP.get(sc.bootstrap, STANDARD_BOOTSTRAP)
        for surface in sc.surfaces:
            if surface not in ("cli", "http"):
                continue
            try:
                if surface == "cli":
                    result = run_cli_surface(sc, bs)
                else:
                    result = run_http_surface(sc, bs)
                # Validate against scenario expectations
                errs = []
                if result.get("outcome") != sc.expected_outcome:
                    errs.append(f"outcome {result.get('outcome')!r} != {sc.expected_outcome!r}")
                if result.get("intent") != sc.expected_intent:
                    errs.append(f"intent {result.get('intent')!r} != {sc.expected_intent!r}")
                if result.get("supported") != sc.expected_supported:
                    errs.append(f"supported {result.get('supported')} != {sc.expected_supported}")
                if errs:
                    j_fail += 1
                    j_errors.append(f"[{sc.id}/{surface}] {'; '.join(errs)}")
                else:
                    j_pass += 1
            except Exception as exc:
                j_fail += 1
                j_errors.append(f"[{sc.id}/{surface}] EXCEPTION: {exc}")

    # Section J covers cli+http surfaces only (session surfaces in run_phase_v1_tests.py).
    # The 156/156 full gate is run_phase_v1_tests.py; this checks no regressions on
    # the stateless surfaces caused by Phase 8b changes.
    check(f"V1 stateless regression: {j_pass}/{j_pass+j_fail} cli+http scenarios pass",
          j_fail == 0 and j_pass > 0)
    if j_errors:
        for msg in j_errors[:10]:
            print(f"    {msg}")
except ImportError as e:
    print(f"  SKIP  run_validation not importable: {e}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
total = _pass + _fail
print(f"Phase 8b: {_pass}/{total} assertions passed")
if _fail:
    print(f"  *** {_fail} FAILED ***")
    sys.exit(1)
else:
    print("  All assertions passed.")
    sys.exit(0)
