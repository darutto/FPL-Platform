"""
Phase 8a Parity and Contract Hardening tests
=============================================

Verifies that Phase 8a position-aware scoring is:
  1. Correct — bias values match formula for GKP / DEF / MID / FWD
  2. Consistent — adjusted_captain_score and position_bias are exposed at
     every surface (comparison, transfer, differential) across CLI, HTTP,
     and session
  3. Auditable — canonical captain_score preserved alongside adjusted score
  4. Non-regressive — all 156 Phase V1 scenarios still pass

Sections
--------
A  compute_position_bias() unit tests — formula correctness (28 assertions)
B  compare_players() raw output — adjusted fields present (16 assertions)
C  FinalResponse.comparison fields — ComparisonPlayerContext 8a fields (12 assertions)
D  FinalResponse.differential fields — DifferentialEntry.adjusted (8 assertions)
E  Transfer advice — adjusted delta and score_inputs (8 assertions)
F  Cross-surface parity — CLI / HTTP / session comparison (12 assertions)
G  GKP vs MID comparison end-to-end (10 assertions)
H  Regression — V1 corpus 156/156 still PASS (1 assertion)
"""
from __future__ import annotations

import copy
import importlib.util
import os
import sys

# ---------------------------------------------------------------------------
# Path setup (same pattern as other phase test runners)
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

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.position_bias import compute_position_bias
from fpl_grounded_assistant.comparison import compare_players
from fpl_grounded_assistant.transfer_advisor import get_transfer_advice
from fpl_grounded_assistant.differential_picks import get_differential_picks
from fpl_grounded_assistant import respond, FinalResponse
from fpl_grounded_assistant.final_response import (
    ComparisonPlayerContext,
    DifferentialEntry,
)

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

# STANDARD_BOOTSTRAP already has Raya (id=5, GKP, team=1/ARS) added in Phase 8a
# Verify Raya is present before running GKP tests
_raya = next((e for e in STANDARD_BOOTSTRAP["elements"] if e.get("web_name") == "Raya"), None)
_salah = next((e for e in STANDARD_BOOTSTRAP["elements"] if e.get("web_name") == "Salah"), None)
_haaland = next((e for e in STANDARD_BOOTSTRAP["elements"] if e.get("web_name") == "Haaland"), None)

# Differential bootstrap — low-ownership available players for differential test
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
# Section A: compute_position_bias() unit tests
# ---------------------------------------------------------------------------

section("A: compute_position_bias() formula correctness")

# A1: GKP with saves_per_90=2.8, cs_per_90=0.27, xgi=0.0
gkp_el = {"saves_per_90": 2.8, "clean_sheets_per_90": 0.27, "defensive_contribution_per_90": 0.0}
bias_gkp, inp_gkp = compute_position_bias("GKP", gkp_el, xgi_per_90=0.0)
ok(bias_gkp > 0, "A1: GKP bias is positive")
ok(bias_gkp > 10, "A2: GKP bias > 10 for decent GKP (saves 2.8, cs 0.27)")
ok(inp_gkp["saves_score"] > 0, "A3: GKP saves_score > 0")
ok(inp_gkp["cs_score"] > 0, "A4: GKP cs_score > 0")
ok(inp_gkp["xgi_drag"] == 0.0, "A5: GKP xgi_drag == 0 (no xGI)")
ok(inp_gkp["dc_per_90"] == 0.0, "A6: GKP dc_per_90 == 0.0 (always zero)")

# Expected: saves_score = clamp(2.8/4.0*100, 0, 100) = 70.0
# cs_score  = clamp(0.27/0.5*100, 0, 100) = 54.0
# bias = 70.0*0.15 + 54.0*0.10 - 0 = 10.5 + 5.4 = 15.9
ok(abs(inp_gkp["saves_score"] - 70.0) < 0.01, "A7: GKP saves_score == 70.0")
ok(abs(inp_gkp["cs_score"] - 54.0) < 0.01, "A8: GKP cs_score == 54.0")
ok(abs(bias_gkp - 15.9) < 0.01, "A9: GKP bias == 15.9")

# A10: DEF with low xGI (defensive DEF)
def_el_def = {"saves_per_90": 0.0, "clean_sheets_per_90": 0.27, "defensive_contribution_per_90": 8.0}
bias_def_def, inp_def_def = compute_position_bias("DEF", def_el_def, xgi_per_90=0.05)
ok(bias_def_def > 0, "A10: DEF (defensive) bias is positive")
ok(inp_def_def["xgi_drag"] < 1.0, "A11: DEF (defensive) xgi_drag is small")

# A12: DEF with high xGI (attacking fullback)
bias_def_atk, inp_def_atk = compute_position_bias("DEF", def_el_def, xgi_per_90=0.30)
ok(bias_def_atk < bias_def_def, "A12: Attacking DEF bias < Defensive DEF bias (xgi_drag offset)")
ok(inp_def_atk["xgi_drag"] > inp_def_def["xgi_drag"], "A13: Attacking DEF has higher xgi_drag")

# A14: MID bias is ALWAYS exactly 0
bias_mid, inp_mid = compute_position_bias("MID", gkp_el, xgi_per_90=0.5)
ok(bias_mid == 0.0, "A14: MID bias == 0.0 (exactly)")
ok(inp_mid["xgi_score"] > 0, "A15: MID xgi_score derived correctly even though bias=0")

# A16: FWD small positive bias
bias_fwd, inp_fwd = compute_position_bias("FWD", {}, xgi_per_90=0.4)
ok(bias_fwd > 0, "A16: FWD bias is positive")
ok(bias_fwd < 5.0, "A17: FWD bias is small (< 5.0) — not a dominant correction")
# Expected: xgi_score = clamp(0.4*50, 0, 100) = 20.0; bias = 20.0 * 0.05 = 1.0
ok(abs(bias_fwd - 1.0) < 0.01, "A18: FWD bias == 1.0 for xgi=0.4")

# A19: GKP with no per-90 fields in element → graceful fallback
empty_gkp = {}
bias_empty, _ = compute_position_bias("GKP", empty_gkp, xgi_per_90=0.0)
ok(bias_empty == 0.0, "A19: GKP with no per-90 fields → bias == 0 (safe fallback)")

# A20: Unknown position → treated as MID (zero bias)
bias_unk, _ = compute_position_bias("UNK", gkp_el, xgi_per_90=0.3)
ok(bias_unk == 0.0, "A20: Unknown position → bias == 0")

# A21: Saves normalisation ceiling — saves_per_90 >= 4.0 → saves_score = 100
bias_top_gkp, inp_top = compute_position_bias("GKP", {"saves_per_90": 5.0, "clean_sheets_per_90": 0.5}, xgi_per_90=0.0)
ok(inp_top["saves_score"] == 100.0, "A21: saves_per_90 >= 4.0 → saves_score clamped to 100")
ok(inp_top["cs_score"] == 100.0, "A22: cs_per_90 >= 0.5 → cs_score clamped to 100")

# A23: adjusted_captain_score never goes below 0 (clamping — tested in integration)
# Tested via a GKP with very low canonical score — but clamp happens in caller.
# Here: confirm bias inputs are all non-negative for a normal GKP
ok(all(v >= 0 for v in inp_gkp.values()), "A23: All GKP bias inputs >= 0")


# ---------------------------------------------------------------------------
# Section B: compare_players() raw output
# ---------------------------------------------------------------------------

section("B: compare_players() raw output — adjusted fields present")

if _raya is None:
    print("  SKIP B: Raya not in STANDARD_BOOTSTRAP")
else:
    result_gkp_mid = compare_players("Raya", "Salah", STANDARD_BOOTSTRAP)
    ok(result_gkp_mid["status"] == "ok", "B1: Raya vs Salah comparison status == ok")

    pa = result_gkp_mid["player_a"]  # Raya (GKP)
    pb = result_gkp_mid["player_b"]  # Salah (MID)

    ok("captain_score" in pa, "B2: player_a has canonical captain_score")
    ok("adjusted_captain_score" in pa, "B3: player_a has adjusted_captain_score (Phase 8a)")
    ok("captain_score" in pb, "B4: player_b has canonical captain_score")
    ok("adjusted_captain_score" in pb, "B5: player_b has adjusted_captain_score")

    ok("score_inputs" in pa, "B6: player_a has score_inputs")
    ok("position_bias" in pa["score_inputs"], "B7: score_inputs has position_bias (Phase 8a)")
    ok("saves_per_90" in pa["score_inputs"], "B8: score_inputs has saves_per_90")
    ok("clean_sheets_per_90" in pa["score_inputs"], "B9: score_inputs has clean_sheets_per_90")
    ok("dc_per_90" in pa["score_inputs"], "B10: score_inputs has dc_per_90")

    # GKP: adjusted > canonical (positive bias from saves + CS)
    ok(pa["adjusted_captain_score"] > pa["captain_score"],
       "B11: GKP adjusted_captain_score > canonical captain_score")
    # MID: adjusted == canonical (zero bias)
    ok(pb["adjusted_captain_score"] == pb["captain_score"],
       "B12: MID adjusted_captain_score == canonical captain_score (zero bias)")

    # Bias value in score_inputs matches position_bias for GKP
    ok(pa["score_inputs"]["position_bias"] > 0, "B13: GKP position_bias > 0 in score_inputs")
    ok(pb["score_inputs"]["position_bias"] == 0.0, "B14: MID position_bias == 0 in score_inputs")

    # MID vs FWD — Haaland FWD gets small positive bias
    result_mid_fwd = compare_players("Salah", "Haaland", STANDARD_BOOTSTRAP)
    ok(result_mid_fwd["status"] == "ok", "B15: Salah vs Haaland comparison status == ok")
    fwd_side = result_mid_fwd["player_b"]  # Haaland FWD
    ok(fwd_side["adjusted_captain_score"] >= fwd_side["captain_score"],
       "B16: FWD adjusted_captain_score >= canonical (small positive or zero)")


# ---------------------------------------------------------------------------
# Section C: FinalResponse.comparison — ComparisonPlayerContext 8a fields
# ---------------------------------------------------------------------------

section("C: FinalResponse.comparison — ComparisonPlayerContext Phase 8a fields")

if _raya is not None:
    r_cmp = respond("compare Raya and Salah", STANDARD_BOOTSTRAP)
    ok(r_cmp.comparison is not None, "C1: comparison is populated for compare turn")

    if r_cmp.comparison is not None:
        pa_ctx = r_cmp.comparison.player_a
        pb_ctx = r_cmp.comparison.player_b

        ok(pa_ctx is not None, "C2: player_a context is populated")
        ok(pb_ctx is not None, "C3: player_b context is populated")

        if pa_ctx is not None and pb_ctx is not None:
            # Both contexts have the new Phase 8a fields
            ok(hasattr(pa_ctx, "adjusted_captain_score"), "C4: player_a has adjusted_captain_score attr")
            ok(hasattr(pa_ctx, "position_bias"), "C5: player_a has position_bias attr")
            ok(hasattr(pb_ctx, "adjusted_captain_score"), "C6: player_b has adjusted_captain_score attr")
            ok(hasattr(pb_ctx, "position_bias"), "C7: player_b has position_bias attr")

            # GKP player_a (Raya) has positive bias
            raya_ctx = pa_ctx if pa_ctx.position == "GKP" else pb_ctx
            mid_ctx  = pb_ctx if pa_ctx.position == "GKP" else pa_ctx

            ok(raya_ctx.position == "GKP", "C8: GKP player resolved correctly")
            ok(raya_ctx.adjusted_captain_score > raya_ctx.captain_score,
               "C9: GKP adjusted_captain_score > canonical in ComparisonPlayerContext")
            ok(raya_ctx.position_bias > 0, "C10: GKP position_bias > 0 in ComparisonPlayerContext")
            ok(mid_ctx.adjusted_captain_score == mid_ctx.captain_score,
               "C11: MID adjusted == canonical in ComparisonPlayerContext")
            ok(mid_ctx.position_bias == 0.0, "C12: MID position_bias == 0.0 in ComparisonPlayerContext")


# ---------------------------------------------------------------------------
# Section D: FinalResponse.differential — DifferentialEntry adjusted field
# ---------------------------------------------------------------------------

section("D: FinalResponse.differential — DifferentialEntry Phase 8a field")

r_diff = respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
ok(r_diff.differential is not None, "D1: differential is populated for differential turn")

if r_diff.differential is not None:
    ok(len(r_diff.differential.picks) > 0, "D2: differential picks list is non-empty")
    pick0 = r_diff.differential.picks[0]

    ok(hasattr(pick0, "adjusted_captain_score"), "D3: DifferentialEntry has adjusted_captain_score attr")
    ok(hasattr(pick0, "captain_score"), "D4: DifferentialEntry has canonical captain_score attr")
    ok(isinstance(pick0.adjusted_captain_score, float), "D5: adjusted_captain_score is float")
    ok(pick0.adjusted_captain_score >= 0.0, "D6: adjusted_captain_score is non-negative")

    # MID pick (Palmer in DIFFERENTIAL_BOOTSTRAP) → adjusted == canonical
    if pick0.position == "MID":
        ok(pick0.adjusted_captain_score == pick0.captain_score,
           "D7: MID differential pick adjusted == canonical")
    else:
        ok(True, "D7: skip — first pick is not MID (position: %s)" % pick0.position)

    # Ranking is by adjusted score (all picks ordered by adjusted)
    if len(r_diff.differential.picks) > 1:
        ok(r_diff.differential.picks[0].adjusted_captain_score
           >= r_diff.differential.picks[1].adjusted_captain_score,
           "D8: picks are ordered by adjusted_captain_score descending")
    else:
        ok(True, "D8: skip — only one pick")


# ---------------------------------------------------------------------------
# Section E: Transfer advice — adjusted delta and score_inputs
# ---------------------------------------------------------------------------

section("E: get_transfer_advice() — adjusted_captain_score and score_inputs")

r_xfer = get_transfer_advice("Saka", "Salah", STANDARD_BOOTSTRAP)
ok(r_xfer["status"] == "ok", "E1: transfer advice status == ok")

if r_xfer["status"] == "ok":
    ok("adjusted_captain_score" in r_xfer["player_out"], "E2: player_out has adjusted_captain_score")
    ok("adjusted_captain_score" in r_xfer["player_in"], "E3: player_in has adjusted_captain_score")
    ok("position_bias" in r_xfer["player_out"]["score_inputs"], "E4: player_out score_inputs has position_bias")
    ok("position_bias" in r_xfer["player_in"]["score_inputs"], "E5: player_in score_inputs has position_bias")
    ok("captain_score" in r_xfer["player_out"], "E6: player_out retains canonical captain_score")
    ok("captain_score" in r_xfer["player_in"], "E7: player_in retains canonical captain_score")
    # score_delta is based on adjusted scores (may differ from canonical delta)
    delta_adj = round(r_xfer["player_in"]["adjusted_captain_score"]
                      - r_xfer["player_out"]["adjusted_captain_score"], 2)
    ok(abs(r_xfer["score_delta"] - delta_adj) < 0.01,
       "E8: score_delta matches adjusted_captain_score difference")


# ---------------------------------------------------------------------------
# Section F: Cross-surface parity — CLI / HTTP / session
# ---------------------------------------------------------------------------

section("F: Cross-surface parity — comparison score fields on CLI / HTTP / session")

# CLI surface — respond() is the canonical CLI-surface entry point
try:
    cli_result = respond("compare Salah and Haaland", STANDARD_BOOTSTRAP)
    ok(cli_result.outcome == "ok", "F1: CLI respond() comparison outcome == ok")
    ok(cli_result.comparison is not None, "F2: CLI respond() comparison metadata present")
    if cli_result.comparison and cli_result.comparison.player_a:
        ok(hasattr(cli_result.comparison.player_a, "adjusted_captain_score"),
           "F3: CLI comparison.player_a has adjusted_captain_score")
    else:
        ok(False, "F3: CLI comparison.player_a is None — unexpected")

    # Canonical score preserved alongside adjusted
    pa_cli = cli_result.comparison.player_a if cli_result.comparison else None
    ok(pa_cli is not None and hasattr(pa_cli, "captain_score"),
       "F4: CLI comparison.player_a retains canonical captain_score")
    ok(pa_cli is not None and hasattr(pa_cli, "position_bias"),
       "F5: CLI comparison.player_a has position_bias")

except Exception as exc:
    ok(False, f"F1-F5: CLI surface failed with {exc}")

# HTTP surface
try:
    import fpl_server
    from fastapi.testclient import TestClient as _TC

    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    _http_client = _TC(fpl_server.app)

    resp = _http_client.post("/ask", json={"question": "compare Salah and Haaland"})
    ok(resp.status_code == 200, "F6: HTTP /ask comparison returns 200")
    body = resp.json()
    ok(body.get("outcome") == "ok", "F7: HTTP /ask comparison outcome == ok")

    comp = body.get("comparison")
    ok(comp is not None, "F8: HTTP /ask response has comparison field")
    if comp:
        pa_http = comp.get("player_a", {})
        ok("adjusted_captain_score" in pa_http, "F9: HTTP comparison.player_a has adjusted_captain_score")
        ok("position_bias" in pa_http, "F10: HTTP comparison.player_a has position_bias")
    else:
        ok(False, "F9: HTTP comparison is None")
        ok(False, "F10: HTTP comparison is None")

except Exception as exc:
    ok(False, f"F6-F10: HTTP surface failed with {exc}")
    _http_client = None  # type: ignore[assignment]

# Session surface
try:
    import fpl_server as _fs
    from fastapi.testclient import TestClient as _TC2

    _fs._init_bootstrap(STANDARD_BOOTSTRAP)
    _fs._clear_sessions()
    _sess_client = _TC2(_fs.app)

    resp_s = _sess_client.post("/session")
    ok(resp_s.status_code == 200, "F11: POST /session returns 200")
    sid = resp_s.json()["session_id"]

    resp_sa = _sess_client.post(f"/session/{sid}/ask",
                                json={"question": "compare Salah and Haaland"})
    ok(resp_sa.status_code == 200, "F12: Session /ask comparison returns 200")
    body_sa = resp_sa.json()
    comp_sa = body_sa.get("comparison")
    ok(comp_sa is not None and "player_a" in comp_sa,
       "F13: Session response has comparison.player_a (adjusted_captain_score accessible)")

except Exception as exc:
    ok(False, f"F11-F13: Session surface failed with {exc}")


# ---------------------------------------------------------------------------
# Section G: GKP vs MID end-to-end
# ---------------------------------------------------------------------------

section("G: GKP vs MID comparison end-to-end (Raya vs Salah)")

if _raya is not None:
    r_gkp = respond("compare Raya and Salah", STANDARD_BOOTSTRAP)
    ok(r_gkp.outcome == "ok", "G1: GKP vs MID comparison outcome == ok")
    ok(r_gkp.comparison is not None, "G2: comparison metadata populated for GKP vs MID")
    ok(r_gkp.final_text, "G3: final_text is non-empty")

    if r_gkp.comparison:
        # Identify GKP context
        pa_g = r_gkp.comparison.player_a
        pb_g = r_gkp.comparison.player_b
        gkp_g = pa_g if (pa_g and pa_g.position == "GKP") else pb_g
        mid_g = pb_g if (pa_g and pa_g.position == "GKP") else pa_g

        ok(gkp_g is not None and gkp_g.position == "GKP", "G4: GKP side resolved")
        ok(mid_g is not None and mid_g.position == "MID", "G5: MID side resolved")

        if gkp_g and mid_g:
            ok(gkp_g.adjusted_captain_score > gkp_g.captain_score,
               "G6: GKP adjusted > canonical in final response")
            ok(mid_g.adjusted_captain_score == mid_g.captain_score,
               "G7: MID adjusted == canonical in final response")
            # margin reflects adjusted scores
            expected_margin = round(
                abs(gkp_g.adjusted_captain_score - mid_g.adjusted_captain_score), 2
            )
            ok(abs(r_gkp.comparison.margin - expected_margin) < 0.05,
               "G8: ComparisonMeta.margin matches adjusted score difference")
            ok(r_gkp.comparison.winner is not None or r_gkp.comparison.margin == 0,
               "G9: winner or tied result")
            ok(r_gkp.comparison.label in ("narrow", "moderate", "clear"),
               "G10: margin_label is one of the three valid values")


# ---------------------------------------------------------------------------
# Section H: Regression — V1 corpus
# ---------------------------------------------------------------------------

section("H: Regression — Phase V1 corpus 156/156")

try:
    from run_validation import run_all_scenarios
    v1_results = run_all_scenarios()
    passed = sum(1 for r in v1_results if r.get("pass") is True)
    total  = len(v1_results)
    ok(passed == total,
       f"H1: All V1 corpus scenarios pass ({passed}/{total})")
except Exception as exc:
    ok(False, f"H1: V1 corpus runner raised {exc}")


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
total_assertions = _pass + _fail
print(f"Phase 8a results: {_pass}/{total_assertions} PASS")
if _errors:
    for e in _errors:
        print(e)
print("=" * 60)

if _fail:
    sys.exit(1)
