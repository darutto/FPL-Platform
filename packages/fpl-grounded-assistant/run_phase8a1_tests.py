"""
Phase 8a1 Position-Aware Heuristic Evaluation tests
====================================================

Verifies that Phase 8a1 position_score layer is:
  1. Correct — compute_position_score() formula per position
  2. MID-zero-drift — MID position_score == captain_score
  3. Position-aware — GKP gets saves/CS credit, DEF gets CS credit
  4. Auditable — dc_score tracked at zero weight, components visible
  5. Overridable — weights_override produces different output
  6. Consistent — position_score exposed at comparison/transfer/differential
  7. Contract-complete — FinalResponse metadata fields present
  8. Cross-surface — CLI/HTTP/session parity
  9. Non-regressive — 156/156 V1 scenarios still pass

Sections
--------
A  compute_position_score() unit tests — formula correctness
B  MID position_score == captain_score (zero drift)
C  GKP/DEF position-specific scoring
D  DC component tracked at zero weight
E  weights_override injection
F  comparison/transfer/differential raw output fields
G  FinalResponse metadata fields
H  Cross-surface parity (CLI/HTTP/session)
I  Regression — V1 corpus 156/156
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB  = lambda name: os.path.join(_PKGS, name)
for _pkg in [
    _HERE,
    _SIB("fpl-api-client"),
    _SIB("fpl-data-core"),
    _SIB("fpl-player-registry"),
    _SIB("fpl-query-tools"),
    _SIB("fpl-tool-contract"),
    _SIB("fpl-tool-runner"),
    _SIB("fpl-captain-engine"),
    _SIB("fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

from fpl_captain_engine import calculate_captain_score
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.position_score import (
    compute_position_score,
    PositionWeights,
    POSITION_PROFILES,
    DEF_EXPERIMENTAL_PROFILES,
    PositionScoreResult,
)
from fpl_grounded_assistant.comparison import compare_players
from fpl_grounded_assistant.transfer_advisor import get_transfer_advice
from fpl_grounded_assistant.differential_picks import get_differential_picks
from fpl_grounded_assistant import respond

# ---------------------------------------------------------------------------
# Test runner helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_errors: list[str] = []


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        _errors.append(f"  FAIL: {label}")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# Bootstrap fixtures
# ---------------------------------------------------------------------------

_raya = next((e for e in STANDARD_BOOTSTRAP["elements"] if e.get("web_name") == "Raya"), None)
_salah = next((e for e in STANDARD_BOOTSTRAP["elements"] if e.get("web_name") == "Salah"), None)
_haaland = next((e for e in STANDARD_BOOTSTRAP["elements"] if e.get("web_name") == "Haaland"), None)

# Differential bootstrap — low-ownership player
DIFFERENTIAL_BOOTSTRAP: dict = {
    **STANDARD_BOOTSTRAP,
    "elements": STANDARD_BOOTSTRAP["elements"] + [
        {
            "id": 10, "first_name": "Cole", "second_name": "Palmer",
            "web_name": "Palmer", "team": 8, "team_code": 8, "element_type": 3,
            "status": "a", "now_cost": 60, "selected_by_percent": "3.5",
            "form": "7.0", "expected_goals": "0.40", "expected_assists": "0.50",
            "expected_goal_involvements": "0.90", "minutes": 1800,
            "penalties_order": 1, "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None,
        },
    ],
}


# ---------------------------------------------------------------------------
# Section A: compute_position_score() formula correctness
# ---------------------------------------------------------------------------

section("A: compute_position_score() formula correctness")

# A1-A3: GKP basic scoring
gkp_result = compute_position_score(
    position="GKP", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.0, minutes_risk=10.0,
    saves_per_90=2.8, clean_sheets_per_90=0.27,
)
ok(isinstance(gkp_result, PositionScoreResult), "A1: returns PositionScoreResult")
ok(gkp_result.position_profile == "GKP", "A2: profile label is GKP")
ok(0 <= gkp_result.position_score <= 100, "A3: position_score in [0, 100]")

# A4-A7: Component normalisation
ok(abs(gkp_result.components["form_score"] - 50.0) < 0.01,
   "A4: form_score = clamp(5.0/10*100) = 50.0")
ok(abs(gkp_result.components["fixture_score"] - 60.0) < 0.01,
   "A5: fixture_score = clamp((6-3)*20) = 60.0")
ok(abs(gkp_result.components["xgi_score"] - 0.0) < 0.01,
   "A6: xgi_score = 0 for GKP (xgi=0)")
ok(abs(gkp_result.components["minutes_score"] - 90.0) < 0.01,
   "A7: minutes_score = clamp(100-10) = 90.0")

# A8-A9: GKP-specific components
ok(abs(gkp_result.components["saves_score"] - 70.0) < 0.01,
   "A8: saves_score = clamp(2.8/4.0*100) = 70.0")
ok(abs(gkp_result.components["cs_score"] - 54.0) < 0.01,
   "A9: cs_score = clamp(0.27/0.5*100) = 54.0")

# A10: Weighted sum verification
# Uses 2026-03-28 calibrated GKP weights: form=0.40, saves=0.15 (was 0.30/0.25)
expected_gkp = (
    50.0 * 0.40   # form  (calibrated: 0.30 -> 0.40)
    + 60.0 * 0.20  # fixture
    + 0.0 * 0.00   # xgi
    + 90.0 * 0.10  # minutes
    + 70.0 * 0.15  # saves  (calibrated: 0.25 -> 0.15)
    + 54.0 * 0.15  # cs
    + 0.0 * 0.00   # dc
)
ok(abs(gkp_result.position_score - round(expected_gkp, 2)) < 0.01,
   f"A10: GKP position_score == weighted sum ({gkp_result.position_score} vs {round(expected_gkp, 2)})")

# A11: All 7 components present
ok(len(gkp_result.components) == 7, "A11: components dict has exactly 7 entries")

# A12: Weights match profile
ok(gkp_result.weights == POSITION_PROFILES["GKP"].as_dict(),
   "A12: weights dict matches GKP profile")

# A13: Weighted dict sums to position_score (before clamping)
weighted_sum = sum(gkp_result.weighted.values())
ok(abs(weighted_sum - gkp_result.position_score) < 0.01,
   "A13: weighted values sum to position_score")

# A14: Unknown position falls back to MID
unk_result = compute_position_score(
    position="UNK", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.5, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.0,
)
ok(unk_result.position_profile == "MID", "A14: unknown position falls back to MID profile")

# A15: Clamping at upper bound
extreme = compute_position_score(
    position="MID", form=15.0, fixture_difficulty=1,
    xgi_per_90=5.0, minutes_risk=-10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.0,
)
ok(extreme.position_score <= 100.0, "A15: position_score clamped at 100")


# ---------------------------------------------------------------------------
# Section B: MID position_score == captain_score (zero drift)
# ---------------------------------------------------------------------------

section("B: MID position_score == captain_score (zero drift)")

# Use Salah's actual stats from bootstrap
if _salah is not None:
    from fpl_grounded_assistant.transfer_advisor import _derive_scoring_inputs

    fdr_map = STANDARD_BOOTSTRAP.get("fixture_difficulty_map", {})
    salah_inputs = _derive_scoring_inputs(_salah, fdr_map)
    canonical_salah = round(float(calculate_captain_score(
        salah_inputs["form"], salah_inputs["fixture_difficulty"],
        salah_inputs["xgi_per_90"], salah_inputs["minutes_risk"],
    )), 2)

    mid_result = compute_position_score(
        position="MID",
        form=salah_inputs["form"],
        fixture_difficulty=salah_inputs["fixture_difficulty"],
        xgi_per_90=salah_inputs["xgi_per_90"],
        minutes_risk=salah_inputs["minutes_risk"],
        saves_per_90=0.0,
        clean_sheets_per_90=0.0,
    )
    ok(abs(mid_result.position_score - canonical_salah) < 0.01,
       f"B1: MID position_score ({mid_result.position_score}) == captain_score ({canonical_salah})")
    ok(mid_result.position_profile == "MID", "B2: profile label is MID")
    ok(mid_result.weights["saves"] == 0.0, "B3: MID saves weight is 0")
    ok(mid_result.weights["clean_sheet"] == 0.0, "B4: MID clean_sheet weight is 0")
    ok(mid_result.weights["dc"] == 0.0, "B5: MID dc weight is 0")

    # FWD should also match canonical (same weights as MID)
    fwd_result = compute_position_score(
        position="FWD",
        form=salah_inputs["form"],
        fixture_difficulty=salah_inputs["fixture_difficulty"],
        xgi_per_90=salah_inputs["xgi_per_90"],
        minutes_risk=salah_inputs["minutes_risk"],
        saves_per_90=0.0,
        clean_sheets_per_90=0.0,
    )
    ok(abs(fwd_result.position_score - canonical_salah) < 0.01,
       f"B6: FWD position_score ({fwd_result.position_score}) == captain_score ({canonical_salah}) — FWD=MID bridge")
else:
    for i in range(1, 7):
        ok(False, f"B{i}: SKIP — Salah not in STANDARD_BOOTSTRAP")


# ---------------------------------------------------------------------------
# Section C: GKP/DEF position-specific scoring
# ---------------------------------------------------------------------------

section("C: GKP/DEF position-specific scoring")

# GKP benefits from saves and clean sheets
gkp_with_saves = compute_position_score(
    position="GKP", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.0, minutes_risk=10.0,
    saves_per_90=3.0, clean_sheets_per_90=0.3,
)
gkp_no_saves = compute_position_score(
    position="GKP", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.0, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.0,
)
ok(gkp_with_saves.position_score > gkp_no_saves.position_score,
   "C1: GKP with saves scores higher than GKP without saves")

# Saves component contributes 15% of GKP score (calibrated 2026-03-28)
ok(gkp_with_saves.weighted["saves"] > 0,
   "C2: GKP saves weighted contribution > 0")

# DEF benefits from clean sheets
def_with_cs = compute_position_score(
    position="DEF", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.1, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.4,
)
def_no_cs = compute_position_score(
    position="DEF", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.1, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.0,
)
ok(def_with_cs.position_score > def_no_cs.position_score,
   "C3: DEF with clean sheets scores higher than DEF without")
ok(def_with_cs.weighted["clean_sheet"] > 0,
   "C4: DEF clean_sheet weighted contribution > 0")

# DEF xgi weight is reduced (0.15 vs MID 0.20)
ok(POSITION_PROFILES["DEF"].xgi < POSITION_PROFILES["MID"].xgi,
   "C5: DEF xgi weight < MID xgi weight")

# GKP xgi weight is zero
ok(POSITION_PROFILES["GKP"].xgi == 0.0,
   "C6: GKP xgi weight is zero")


# ---------------------------------------------------------------------------
# Section D: DC component tracked at zero weight
# ---------------------------------------------------------------------------

section("D: DC component tracked at zero weight")

dc_result = compute_position_score(
    position="DEF", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.1, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.3,
    dc_per_90=8.0,
)

ok("dc_score" in dc_result.components, "D1: dc_score present in components")
ok(dc_result.components["dc_score"] > 0, "D2: dc_score > 0 when dc_per_90 > 0")
# Expected: clamp(8.0/12.0*100) = 66.67
ok(abs(dc_result.components["dc_score"] - 66.6667) < 0.01,
   "D3: dc_score normalisation correct (8.0/12.0*100 = 66.67)")
ok(dc_result.weighted["dc"] == 0.0, "D4: dc weighted contribution is 0 (zero weight)")
ok(dc_result.weights["dc"] == 0.0, "D5: dc weight is 0 in default DEF profile")

# Same score with or without DC (zero weight)
dc_zero = compute_position_score(
    position="DEF", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.1, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.3,
    dc_per_90=0.0,
)
ok(dc_result.position_score == dc_zero.position_score,
   "D6: position_score unchanged by dc_per_90 at zero weight")


# ---------------------------------------------------------------------------
# Section E: weights_override injection
# ---------------------------------------------------------------------------

section("E: weights_override injection")

# Use experimental DEF profile with DC weight
exp_profile = DEF_EXPERIMENTAL_PROFILES["dc_included"]
ok(exp_profile.dc == 0.10, "E1: experimental DEF profile has dc=0.10")

exp_result = compute_position_score(
    position="DEF", form=5.0, fixture_difficulty=3,
    xgi_per_90=0.1, minutes_risk=10.0,
    saves_per_90=0.0, clean_sheets_per_90=0.3,
    dc_per_90=8.0,
    weights_override=exp_profile,
)
ok(exp_result.position_profile == "custom", "E2: weights_override sets profile to 'custom'")
ok(exp_result.weights["dc"] == 0.10, "E3: overridden weights include dc=0.10")
ok(exp_result.weighted["dc"] > 0, "E4: dc contributes to score with override")
ok(exp_result.position_score != dc_result.position_score,
   "E5: experimental profile produces different score than default")

# Custom weights must sum to 1.0
try:
    bad = PositionWeights(form=0.5, fixture=0.5, xgi=0.0, minutes=0.0,
                          saves=0.0, clean_sheet=0.0, dc=0.1)
    ok(False, "E6: PositionWeights should reject weights that don't sum to 1.0")
except ValueError:
    ok(True, "E6: PositionWeights rejects weights not summing to 1.0")


# ---------------------------------------------------------------------------
# Section F: comparison/transfer/differential raw output fields
# ---------------------------------------------------------------------------

section("F: comparison/transfer/differential raw output — position_score fields")

if _raya is not None:
    # Comparison
    cmp = compare_players("Raya", "Salah", STANDARD_BOOTSTRAP)
    ok(cmp["status"] == "ok", "F1: Raya vs Salah comparison ok")
    pa = cmp["player_a"]
    pb = cmp["player_b"]
    ok("position_score" in pa, "F2: player_a has position_score")
    ok("position_score" in pb, "F3: player_b has position_score")
    ok("captain_score" in pa, "F4: player_a retains captain_score (Layer 1)")
    ok("captain_score" in pb, "F5: player_b retains captain_score")
    ok("adjusted_captain_score" not in pa, "F6: player_a no longer has adjusted_captain_score")
    ok("position_bias" not in pa.get("score_inputs", {}),
       "F7: score_inputs no longer has position_bias")
    ok("position_profile" in pa.get("score_inputs", {}),
       "F8: score_inputs has position_profile")
    ok("components" in pa.get("score_inputs", {}),
       "F9: score_inputs has components dict")

    # Transfer
    xfer = get_transfer_advice("Saka", "Salah", STANDARD_BOOTSTRAP)
    ok(xfer["status"] == "ok", "F10: transfer advice ok")
    ok("position_score" in xfer["player_out"], "F11: transfer player_out has position_score")
    ok("position_score" in xfer["player_in"], "F12: transfer player_in has position_score")

    # score_delta uses position_score
    delta = round(xfer["player_in"]["position_score"]
                  - xfer["player_out"]["position_score"], 2)
    ok(abs(xfer["score_delta"] - delta) < 0.01,
       "F13: score_delta matches position_score difference")

    # Differential
    diff = get_differential_picks(DIFFERENTIAL_BOOTSTRAP)
    ok(diff["status"] == "ok", "F14: differential picks ok")
    if diff["picks"]:
        p0 = diff["picks"][0]
        ok("position_score" in p0, "F15: differential pick has position_score")
        ok("captain_score" in p0, "F16: differential pick retains captain_score")
        ok("adjusted_captain_score" not in p0, "F17: no adjusted_captain_score in picks")
    else:
        ok(False, "F15-F17: no picks returned")
else:
    for i in range(1, 18):
        ok(False, f"F{i}: SKIP — Raya not in STANDARD_BOOTSTRAP")


# ---------------------------------------------------------------------------
# Section G: FinalResponse metadata fields
# ---------------------------------------------------------------------------

section("G: FinalResponse metadata fields")

if _raya is not None:
    # Comparison metadata
    r_cmp = respond("compare Raya and Salah", STANDARD_BOOTSTRAP)
    ok(r_cmp.comparison is not None, "G1: comparison metadata populated")
    if r_cmp.comparison and r_cmp.comparison.player_a:
        ctx_a = r_cmp.comparison.player_a
        ok(hasattr(ctx_a, "position_score"), "G2: ComparisonPlayerContext has position_score")
        ok(hasattr(ctx_a, "captain_score"), "G3: ComparisonPlayerContext retains captain_score")
        ok(not hasattr(ctx_a, "adjusted_captain_score"),
           "G4: ComparisonPlayerContext no longer has adjusted_captain_score")
        ok(not hasattr(ctx_a, "position_bias"),
           "G5: ComparisonPlayerContext no longer has position_bias")

        # GKP: position_score differs from captain_score
        gkp_ctx = ctx_a if ctx_a.position == "GKP" else r_cmp.comparison.player_b
        if gkp_ctx and gkp_ctx.position == "GKP":
            ok(gkp_ctx.position_score != gkp_ctx.captain_score,
               "G6: GKP position_score differs from captain_score")
        else:
            ok(False, "G6: GKP context not found")

        # MID: weight profile is identical to canonical formula.
        # Phase 8b: position_score may differ from captain_score when venue is known
        # (Layer 2 uses effective_fdr; Layer 1 uses raw FDR). For a home MID player,
        # position_score >= captain_score (effective_fdr < raw_fdr => higher fixture_score).
        mid_ctx = r_cmp.comparison.player_b if ctx_a.position == "GKP" else ctx_a
        if mid_ctx and mid_ctx.position == "MID":
            if mid_ctx.is_home is None:
                ok(abs(mid_ctx.position_score - mid_ctx.captain_score) < 0.01,
                   "G7: MID position_score == captain_score (no venue data)")
            else:
                # Phase 8b: small expected divergence from home/away FDR adj
                ok(isinstance(mid_ctx.position_score, float),
                   "G7: MID position_score is float (Phase 8b: may differ from captain_score due to effective_fdr)")
        else:
            ok(False, "G7: MID context not found")
    else:
        for i in range(2, 8):
            ok(False, f"G{i}: comparison player context missing")

    # Differential metadata
    r_diff = respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
    ok(r_diff.differential is not None, "G8: differential metadata populated")
    if r_diff.differential and r_diff.differential.picks:
        dp = r_diff.differential.picks[0]
        ok(hasattr(dp, "position_score"), "G9: DifferentialEntry has position_score")
        ok(hasattr(dp, "captain_score"), "G10: DifferentialEntry retains captain_score")
        ok(not hasattr(dp, "adjusted_captain_score"),
           "G11: DifferentialEntry no longer has adjusted_captain_score")
    else:
        for i in range(9, 12):
            ok(False, f"G{i}: differential picks missing")
else:
    for i in range(1, 12):
        ok(False, f"G{i}: SKIP — Raya not in STANDARD_BOOTSTRAP")


# ---------------------------------------------------------------------------
# Section H: Cross-surface parity (CLI/HTTP/session)
# ---------------------------------------------------------------------------

section("H: Cross-surface parity — position_score on CLI/HTTP/session")

# CLI surface
try:
    cli_r = respond("compare Salah and Haaland", STANDARD_BOOTSTRAP)
    ok(cli_r.outcome == "ok", "H1: CLI comparison outcome ok")
    ok(cli_r.comparison is not None, "H2: CLI comparison metadata present")
    if cli_r.comparison and cli_r.comparison.player_a:
        ok(hasattr(cli_r.comparison.player_a, "position_score"),
           "H3: CLI player_a has position_score")
        ok(not hasattr(cli_r.comparison.player_a, "adjusted_captain_score"),
           "H4: CLI player_a no adjusted_captain_score")
    else:
        ok(False, "H3-H4: CLI comparison player_a missing")
except Exception as exc:
    ok(False, f"H1-H4: CLI surface failed with {exc}")

# HTTP surface
try:
    import fpl_server
    from fastapi.testclient import TestClient as _TC

    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    _http = _TC(fpl_server.app)

    resp = _http.post("/ask", json={"question": "compare Salah and Haaland"})
    ok(resp.status_code == 200, "H5: HTTP /ask returns 200")
    body = resp.json()
    comp = body.get("comparison", {})
    if comp:
        pa_h = comp.get("player_a", {})
        ok("position_score" in pa_h, "H6: HTTP player_a has position_score")
        ok("adjusted_captain_score" not in pa_h,
           "H7: HTTP player_a no adjusted_captain_score")
        ok("position_bias" not in pa_h,
           "H8: HTTP player_a no position_bias")
    else:
        ok(False, "H6-H8: HTTP comparison missing")
except Exception as exc:
    ok(False, f"H5-H8: HTTP surface failed with {exc}")

# Session surface
try:
    import fpl_server as _fs
    from fastapi.testclient import TestClient as _TC2

    _fs._init_bootstrap(STANDARD_BOOTSTRAP)
    _fs._clear_sessions()
    _sc = _TC2(_fs.app)

    r_s = _sc.post("/session")
    ok(r_s.status_code == 200, "H9: POST /session returns 200")
    sid = r_s.json()["session_id"]

    r_sa = _sc.post(f"/session/{sid}/ask",
                     json={"question": "compare Salah and Haaland"})
    ok(r_sa.status_code == 200, "H10: session /ask returns 200")
    body_s = r_sa.json()
    comp_s = body_s.get("comparison", {})
    if comp_s:
        pa_s = comp_s.get("player_a", {})
        ok("position_score" in pa_s,
           "H11: session player_a has position_score")
        ok("adjusted_captain_score" not in pa_s,
           "H12: session player_a no adjusted_captain_score")
    else:
        ok(False, "H11-H12: session comparison missing")
except Exception as exc:
    ok(False, f"H9-H12: session surface failed with {exc}")


# ---------------------------------------------------------------------------
# Section I: Regression — V1 corpus 156/156
# ---------------------------------------------------------------------------

section("I: Regression — Phase V1 corpus 156/156")

try:
    from run_validation import run_all_scenarios
    v1_results = run_all_scenarios()
    passed = sum(1 for r in v1_results if r.get("pass") is True)
    total = len(v1_results)
    ok(passed == total,
       f"I1: All V1 corpus scenarios pass ({passed}/{total})")
except Exception as exc:
    ok(False, f"I1: V1 corpus runner raised {exc}")


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
total_assertions = _pass + _fail
print(f"Phase 8a1 results: {_pass}/{total_assertions} PASS")
if _errors:
    for e in _errors:
        print(e)
print("=" * 60)

if _fail:
    sys.exit(1)
