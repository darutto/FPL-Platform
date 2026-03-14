"""
run_phase2j_tests.py
====================
Standalone validator for Phase 2j: deterministic explanation templates.

Tests the new ``explainer.py`` module and the updated renderer integration
without requiring pytest or live FPL API data.

Run:
    python run_phase2j_tests.py
    # Expected: all sections PASS, final count reported.

Sections
--------
A  Threshold constants exist and have correct types/values
B  _ROLE_REASON map structure
C  _COMPACT_EXCLUDED set structure
D  explain_captain — non-ok inputs return empty list (safety)
E  explain_captain — all signals in neutral range → empty list
F  explain_captain — form signal: FORM_HIGH boundary
G  explain_captain — form signal: FORM_LOW boundary
H  explain_captain — fixture signal: FDR_EASY boundary
I  explain_captain — fixture signal: FDR_HARD boundary
J  explain_captain — xGI signal: XGI_HIGH boundary
K  explain_captain — xGI signal: XGI_LOW boundary
L  explain_captain — minutes risk: zero → Secure minutes
M  explain_captain — minutes risk: RISK_ROTATION boundary
N  explain_captain — minutes risk: RISK_HIGH boundary
O  explain_captain — role signals: penalty_taker_1
P  explain_captain — role signals: penalty_taker_2
Q  explain_captain — role signals: freekick_taker_1 + freekick_taker_2
R  explain_captain — role signals: combined pen + FK
S  explain_captain — tier = differential → tier summary reason
T  explain_captain — tier = low_confidence → tier summary reason
U  explain_captain — tier = safe/upside/avoid → no tier summary reason
V  explain_captain — reason ordering: role first, then form, fixture, xGI, risk
W  explain_captain — full profile: strong safe captain with penalty
X  explain_captain — full profile: avoid candidate (high risk + weak inputs)
Y  explain_captain — full profile: differential (low ownership scenario)
Z  explain_captain_compact — excludes _COMPACT_EXCLUDED reasons
AA explain_captain_compact — cap enforced (max_reasons=2 default)
AB explain_captain_compact — custom max_reasons parameter
AC explain_captain_compact — non-ok input returns empty list
AD explain_captain_compact — neutral range → empty list (no reasons)
AE renderer — _render_get_captain_score appends Why clause when reasons exist
AF renderer — _render_get_captain_score Why clause absent when no reasons
AG renderer — _render_get_captain_score reasons include role + form + fixture
AH renderer — _render_get_captain_score avoid tier: Why clause still present
AI renderer — _render_get_captain_score low_confidence: Why includes tier reason
AJ renderer — _render_get_captain_score non-ok branches unchanged (no Why)
AK renderer — _render_rank_captain_candidates compact reasons per entry
AL renderer — _render_rank_captain_candidates Penalty taker NOT in compact
AM renderer — _render_rank_captain_candidates no reasons when neutral profile
AN renderer — _render_rank_captain_candidates avoid entry has compact reasons
AO renderer — non-ok entry lines unchanged (no reason clause)
AP Phase 2i regression — tier brackets, set-piece suffix still present
AQ Phase 2a/2b regression — all pre-existing output fields intact
AR raw_output not mutated by explain_captain() or renderer calls
AS interface report — sample outputs for human review
"""
from __future__ import annotations

import copy
import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-captain-engine"))
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-tool-contract"))
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-player-registry"))
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-query-tools"))
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-api-client"))
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-data-core"))
sys.path.insert(0, os.path.join(_HERE, "..", "fpl-tool-runner"))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from fpl_grounded_assistant.explainer import (
    FORM_HIGH, FORM_LOW, FDR_EASY, FDR_HARD, XGI_HIGH, XGI_LOW,
    RISK_ROTATION, RISK_HIGH, _ROLE_REASON, _COMPACT_EXCLUDED,
    explain_captain, explain_captain_compact,
)
from fpl_grounded_assistant.renderer import (
    _render_get_captain_score, _render_rank_captain_candidates,
)

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_pass_count = 0
_fail_count = 0


def ok(condition: bool, label: str) -> None:
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
    else:
        _fail_count += 1
        print(f"  FAIL: {label}")


def _section(name: str) -> None:
    print(f"\n--- Section {name} ---")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _inputs(
    form: float = 5.0,
    fdr: int = 3,
    xgi: float = 0.30,
    risk: float = 0.0,
) -> dict:
    return {
        "form": form,
        "fixture_difficulty": fdr,
        "xgi_per_90": xgi,
        "minutes_risk": risk,
    }


def _role(notes: list[str] | None = None, threat: bool = False) -> dict:
    notes = notes or []
    return {
        "set_piece_notes": notes,
        "set_piece_threat": threat or bool(notes),
        "role_bonus": 0.0,
    }


def _out(
    tier: str = "upside",
    inputs: dict | None = None,
    role_notes: list[str] | None = None,
    web_name: str = "Player",
    name: str = "Player FC",
    team_short: str = "TST",
    position: str = "MID",
    score: float = 45.0,
) -> dict:
    return {
        "status": "ok",
        "web_name": web_name,
        "name": name,
        "team": "Test FC",
        "team_short": team_short,
        "position": position,
        "captain_score": score,
        "tier": tier,
        "role_signals": _role(role_notes),
        "score_inputs": inputs if inputs is not None else _inputs(),
    }


def _rank_entry(
    rank: int,
    web_name: str,
    team_short: str,
    tier: str,
    score: float,
    inputs: dict | None = None,
    role_notes: list[str] | None = None,
) -> dict:
    return {
        "status": "ok",
        "rank": rank,
        "index": rank - 1,
        "player_id": rank * 10,
        "web_name": web_name,
        "name": web_name,
        "team": web_name + " FC",
        "team_short": team_short,
        "position": "MID",
        "captain_score": score,
        "tier": tier,
        "role_signals": _role(role_notes),
        "score_inputs": inputs if inputs is not None else _inputs(),
        "derived_fields": [],
        "query": web_name,
    }


def _rank_ok(entries: list[dict], errors: int = 0) -> dict:
    return {
        "status": "ok",
        "ranked_candidates": entries,
        "total": len(entries),
        "error_count": errors,
    }


# ---------------------------------------------------------------------------
# Section A — threshold constants
# ---------------------------------------------------------------------------
_section("A — threshold constants")
ok(isinstance(FORM_HIGH, float),      "A1 FORM_HIGH is float")
ok(isinstance(FORM_LOW, float),       "A2 FORM_LOW is float")
ok(isinstance(FDR_EASY, int),         "A3 FDR_EASY is int")
ok(isinstance(FDR_HARD, int),         "A4 FDR_HARD is int")
ok(isinstance(XGI_HIGH, float),       "A5 XGI_HIGH is float")
ok(isinstance(XGI_LOW, float),        "A6 XGI_LOW is float")
ok(isinstance(RISK_ROTATION, float),  "A7 RISK_ROTATION is float")
ok(isinstance(RISK_HIGH, float),      "A8 RISK_HIGH is float")
ok(FORM_HIGH == 7.0,     "A9  FORM_HIGH=7.0")
ok(FORM_LOW == 3.0,      "A10 FORM_LOW=3.0")
ok(FDR_EASY == 2,        "A11 FDR_EASY=2")
ok(FDR_HARD == 4,        "A12 FDR_HARD=4")
ok(XGI_HIGH == 0.50,     "A13 XGI_HIGH=0.50")
ok(XGI_LOW == 0.15,      "A14 XGI_LOW=0.15")
ok(RISK_ROTATION == 30.0,"A15 RISK_ROTATION=30.0")
ok(RISK_HIGH == 50.0,    "A16 RISK_HIGH=50.0")
# Ordering sanity checks
ok(FORM_LOW < FORM_HIGH,              "A17 FORM_LOW < FORM_HIGH")
ok(FDR_EASY < FDR_HARD,               "A18 FDR_EASY < FDR_HARD")
ok(XGI_LOW < XGI_HIGH,                "A19 XGI_LOW < XGI_HIGH")
ok(RISK_ROTATION < RISK_HIGH,         "A20 RISK_ROTATION < RISK_HIGH")

# ---------------------------------------------------------------------------
# Section B — _ROLE_REASON map
# ---------------------------------------------------------------------------
_section("B — _ROLE_REASON map")
for key in ("penalty_taker_1", "penalty_taker_2", "freekick_taker_1", "freekick_taker_2"):
    ok(key in _ROLE_REASON, f"B: _ROLE_REASON has key '{key}'")
ok(_ROLE_REASON["penalty_taker_1"]  == "Penalty taker",        "B5 pen1 label")
ok(_ROLE_REASON["penalty_taker_2"]  == "2nd penalty taker",    "B6 pen2 label")
ok(_ROLE_REASON["freekick_taker_1"] == "Free-kick taker",      "B7 fk1 label")
ok(_ROLE_REASON["freekick_taker_2"] == "2nd free-kick taker",  "B8 fk2 label")

# ---------------------------------------------------------------------------
# Section C — _COMPACT_EXCLUDED set
# ---------------------------------------------------------------------------
_section("C — _COMPACT_EXCLUDED set")
ok(isinstance(_COMPACT_EXCLUDED, frozenset),  "C1 _COMPACT_EXCLUDED is frozenset")
ok("Penalty taker"                 in _COMPACT_EXCLUDED, "C2 pen1 excluded")
ok("2nd penalty taker"             in _COMPACT_EXCLUDED, "C3 pen2 excluded")
ok("Free-kick taker"               in _COMPACT_EXCLUDED, "C4 fk1 excluded")
ok("2nd free-kick taker"           in _COMPACT_EXCLUDED, "C5 fk2 excluded")
ok("High-upside differential profile" in _COMPACT_EXCLUDED, "C6 differential summary excluded")
ok("Low-confidence captaincy profile" in _COMPACT_EXCLUDED, "C7 low_confidence summary excluded")
ok("Strong recent form"            not in _COMPACT_EXCLUDED, "C8 form reason NOT excluded")
ok("Favorable fixture"             not in _COMPACT_EXCLUDED, "C9 fixture reason NOT excluded")
ok("Secure minutes"                not in _COMPACT_EXCLUDED, "C10 minutes reason NOT excluded")

# ---------------------------------------------------------------------------
# Section D — non-ok inputs return empty list (safety)
# ---------------------------------------------------------------------------
_section("D — non-ok inputs return empty list")
for non_ok in (
    {"status": "ambiguous"},
    {"status": "not_found"},
    {"status": "error", "code": "missing_argument"},
    {},
    {"status": None},
):
    ok(explain_captain(non_ok) == [], f"D: non-ok {non_ok.get('status', '(no status)')} → []")

# ---------------------------------------------------------------------------
# Section E — all neutral inputs → empty list
# ---------------------------------------------------------------------------
_section("E — all neutral inputs → empty (no reasons)")
neutral = _out(tier="upside", inputs=_inputs(form=5.0, fdr=3, xgi=0.30, risk=0.0))
# risk=0.0 → "Secure minutes" — make risk neutral too
neutral_risk_out = _out(tier="upside", inputs=_inputs(form=5.0, fdr=3, xgi=0.30, risk=10.0))
reasons_e = explain_captain(neutral_risk_out)
ok("Strong recent form" not in reasons_e, "E1 neutral form → no form reason")
ok("Favorable fixture"  not in reasons_e, "E2 neutral FDR → no fixture reason")
ok("High attacking involvement" not in reasons_e, "E3 neutral xGI → no xGI reason")
ok("Secure minutes"     not in reasons_e, "E4 non-zero risk → no secure minutes")
ok("Rotation risk lowers confidence" not in reasons_e, "E5 low risk → no rotation reason")
ok("High-upside differential profile" not in reasons_e, "E6 upside tier → no tier summary")

# ---------------------------------------------------------------------------
# Section F — form: FORM_HIGH boundary
# ---------------------------------------------------------------------------
_section("F — form FORM_HIGH boundary")
out_form_high     = _out(inputs=_inputs(form=FORM_HIGH, fdr=3, xgi=0.30, risk=10.0))
out_form_just_low = _out(inputs=_inputs(form=FORM_HIGH - 0.01, fdr=3, xgi=0.30, risk=10.0))

ok("Strong recent form" in explain_captain(out_form_high),        "F1 form >= FORM_HIGH → reason")
ok("Strong recent form" not in explain_captain(out_form_just_low),"F2 form < FORM_HIGH → no reason")

# ---------------------------------------------------------------------------
# Section G — form: FORM_LOW boundary
# ---------------------------------------------------------------------------
_section("G — form FORM_LOW boundary")
out_form_low      = _out(inputs=_inputs(form=FORM_LOW - 0.01, fdr=3, xgi=0.30, risk=10.0))
out_form_at_low   = _out(inputs=_inputs(form=FORM_LOW, fdr=3, xgi=0.30, risk=10.0))  # exactly 3.0 → NOT < 3.0

ok("Weak recent form" in explain_captain(out_form_low),          "G1 form < FORM_LOW → reason")
ok("Weak recent form" not in explain_captain(out_form_at_low),   "G2 form == FORM_LOW → no reason (< not <=)")

# ---------------------------------------------------------------------------
# Section H — fixture: FDR_EASY boundary
# ---------------------------------------------------------------------------
_section("H — fixture FDR_EASY boundary")
out_fdr_easy  = _out(inputs=_inputs(form=5.0, fdr=FDR_EASY,     xgi=0.30, risk=10.0))
out_fdr_three = _out(inputs=_inputs(form=5.0, fdr=FDR_EASY + 1, xgi=0.30, risk=10.0))

ok("Favorable fixture" in explain_captain(out_fdr_easy),         "H1 fdr <= FDR_EASY → reason")
ok("Favorable fixture" not in explain_captain(out_fdr_three),    "H2 fdr = FDR_EASY+1 → no reason")

# FDR_EASY - 1 also qualifies
out_fdr_one = _out(inputs=_inputs(form=5.0, fdr=1, xgi=0.30, risk=10.0))
ok("Favorable fixture" in explain_captain(out_fdr_one),          "H3 fdr=1 → reason")

# ---------------------------------------------------------------------------
# Section I — fixture: FDR_HARD boundary
# ---------------------------------------------------------------------------
_section("I — fixture FDR_HARD boundary")
out_fdr_hard      = _out(inputs=_inputs(form=5.0, fdr=FDR_HARD,     xgi=0.30, risk=10.0))
out_fdr_just_easy = _out(inputs=_inputs(form=5.0, fdr=FDR_HARD - 1, xgi=0.30, risk=10.0))
out_fdr_five      = _out(inputs=_inputs(form=5.0, fdr=5,             xgi=0.30, risk=10.0))

ok("Tough fixture" in explain_captain(out_fdr_hard),             "I1 fdr >= FDR_HARD → reason")
ok("Tough fixture" not in explain_captain(out_fdr_just_easy),    "I2 fdr = FDR_HARD-1 → no reason")
ok("Tough fixture" in explain_captain(out_fdr_five),             "I3 fdr=5 → reason")

# ---------------------------------------------------------------------------
# Section J — xGI: XGI_HIGH boundary
# ---------------------------------------------------------------------------
_section("J — xGI XGI_HIGH boundary")
out_xgi_high  = _out(inputs=_inputs(form=5.0, fdr=3, xgi=XGI_HIGH,      risk=10.0))
out_xgi_below = _out(inputs=_inputs(form=5.0, fdr=3, xgi=XGI_HIGH-0.01, risk=10.0))

ok("High attacking involvement" in explain_captain(out_xgi_high),     "J1 xgi >= XGI_HIGH → reason")
ok("High attacking involvement" not in explain_captain(out_xgi_below), "J2 xgi < XGI_HIGH → no reason")

# ---------------------------------------------------------------------------
# Section K — xGI: XGI_LOW boundary
# ---------------------------------------------------------------------------
_section("K — xGI XGI_LOW boundary")
out_xgi_low   = _out(inputs=_inputs(form=5.0, fdr=3, xgi=XGI_LOW-0.01, risk=10.0))
out_xgi_at    = _out(inputs=_inputs(form=5.0, fdr=3, xgi=XGI_LOW,      risk=10.0))

ok("Weak attacking process" in explain_captain(out_xgi_low),    "K1 xgi < XGI_LOW → reason")
ok("Weak attacking process" not in explain_captain(out_xgi_at), "K2 xgi == XGI_LOW → no reason (< not <=)")

# ---------------------------------------------------------------------------
# Section L — minutes risk: zero → Secure minutes
# ---------------------------------------------------------------------------
_section("L — minutes risk=0 → Secure minutes")
out_secure     = _out(inputs=_inputs(risk=0.0))
out_nonzero    = _out(inputs=_inputs(risk=5.0))

ok("Secure minutes" in explain_captain(out_secure),     "L1 risk=0.0 → Secure minutes")
ok("Secure minutes" not in explain_captain(out_nonzero),"L2 risk=5.0 → no Secure minutes")

# ---------------------------------------------------------------------------
# Section M — minutes risk: RISK_ROTATION boundary
# ---------------------------------------------------------------------------
_section("M — minutes risk RISK_ROTATION boundary")
out_rotation      = _out(inputs=_inputs(risk=RISK_ROTATION))
out_just_below    = _out(inputs=_inputs(risk=RISK_ROTATION - 0.01))
out_in_range      = _out(inputs=_inputs(risk=40.0))

ok("Rotation risk lowers confidence" in explain_captain(out_rotation),   "M1 risk >= RISK_ROTATION and < RISK_HIGH → reason")
ok("Rotation risk lowers confidence" not in explain_captain(out_just_below),"M2 risk < RISK_ROTATION → no reason")
ok("Rotation risk lowers confidence" in explain_captain(out_in_range),   "M3 risk in [30,50) → reason")

# RISK_HIGH boundary: at RISK_HIGH, should be Significant minutes risk, not Rotation
out_at_risk_high  = _out(inputs=_inputs(risk=RISK_HIGH))
ok("Rotation risk lowers confidence" not in explain_captain(out_at_risk_high), "M4 risk >= RISK_HIGH → no rotation reason")
ok("Significant minutes risk" in explain_captain(out_at_risk_high),            "M5 risk >= RISK_HIGH → significant risk reason")

# ---------------------------------------------------------------------------
# Section N — minutes risk: RISK_HIGH boundary
# ---------------------------------------------------------------------------
_section("N — minutes risk RISK_HIGH boundary")
out_high_risk     = _out(inputs=_inputs(risk=100.0))
out_mid_risk      = _out(inputs=_inputs(risk=RISK_HIGH - 0.01))

ok("Significant minutes risk" in explain_captain(out_high_risk),       "N1 risk=100 → significant risk")
ok("Significant minutes risk" not in explain_captain(out_mid_risk),    "N2 risk < RISK_HIGH → no significant risk")

# ---------------------------------------------------------------------------
# Section O — role signals: penalty_taker_1
# ---------------------------------------------------------------------------
_section("O — role: penalty_taker_1")
out_pen1 = _out(role_notes=["penalty_taker_1"])
reasons_o = explain_captain(out_pen1)
ok("Penalty taker" in reasons_o,           "O1 penalty_taker_1 → 'Penalty taker'")
ok("2nd penalty taker" not in reasons_o,   "O2 no pen2 reason")
ok("Free-kick taker" not in reasons_o,     "O3 no FK reason")

# ---------------------------------------------------------------------------
# Section P — role signals: penalty_taker_2
# ---------------------------------------------------------------------------
_section("P — role: penalty_taker_2")
out_pen2 = _out(role_notes=["penalty_taker_2"])
reasons_p = explain_captain(out_pen2)
ok("2nd penalty taker" in reasons_p,   "P1 penalty_taker_2 → '2nd penalty taker'")
ok("Penalty taker" not in reasons_p,   "P2 no pen1 reason")

# ---------------------------------------------------------------------------
# Section Q — role signals: freekick takers
# ---------------------------------------------------------------------------
_section("Q — role: freekick takers")
out_fk1 = _out(role_notes=["freekick_taker_1"])
out_fk2 = _out(role_notes=["freekick_taker_2"])
ok("Free-kick taker"     in explain_captain(out_fk1), "Q1 fk1 → 'Free-kick taker'")
ok("2nd free-kick taker" in explain_captain(out_fk2), "Q2 fk2 → '2nd free-kick taker'")

# ---------------------------------------------------------------------------
# Section R — role signals: combined pen + FK
# ---------------------------------------------------------------------------
_section("R — role: combined pen1 + fk1")
out_combo = _out(role_notes=["penalty_taker_1", "freekick_taker_1"])
reasons_r = explain_captain(out_combo)
ok("Penalty taker"   in reasons_r, "R1 pen1 in combo")
ok("Free-kick taker" in reasons_r, "R2 fk1 in combo")

# ---------------------------------------------------------------------------
# Section S — tier = differential → tier summary reason
# ---------------------------------------------------------------------------
_section("S — tier=differential → tier summary")
out_diff = _out(tier="differential")
reasons_s = explain_captain(out_diff)
ok("High-upside differential profile" in reasons_s, "S1 differential tier → summary reason")
ok("Low-confidence captaincy profile" not in reasons_s, "S2 no low_conf reason for differential")

# ---------------------------------------------------------------------------
# Section T — tier = low_confidence → tier summary reason
# ---------------------------------------------------------------------------
_section("T — tier=low_confidence → tier summary")
out_lc = _out(tier="low_confidence")
reasons_t = explain_captain(out_lc)
ok("Low-confidence captaincy profile" in reasons_t, "T1 low_confidence tier → summary reason")
ok("High-upside differential profile" not in reasons_t, "T2 no differential reason for low_conf")

# ---------------------------------------------------------------------------
# Section U — safe/upside/avoid → no tier summary reason
# ---------------------------------------------------------------------------
_section("U — safe/upside/avoid → no tier summary reason")
for tier_u in ("safe", "upside", "avoid"):
    out_u = _out(tier=tier_u)
    reasons_u = explain_captain(out_u)
    ok("High-upside differential profile" not in reasons_u, f"U: no diff summary for tier={tier_u}")
    ok("Low-confidence captaincy profile" not in reasons_u,  f"U: no lc summary for tier={tier_u}")

# ---------------------------------------------------------------------------
# Section V — reason ordering: role first
# ---------------------------------------------------------------------------
_section("V — reason ordering: role before form/fixture/xGI/risk")
out_v = _out(
    tier="safe",
    inputs=_inputs(form=FORM_HIGH, fdr=FDR_EASY, xgi=XGI_HIGH, risk=0.0),
    role_notes=["penalty_taker_1"],
)
reasons_v = explain_captain(out_v)
ok(len(reasons_v) >= 5, "V1 all 5 signal types contribute at least 5 reasons")
pen_idx    = reasons_v.index("Penalty taker")
form_idx   = reasons_v.index("Strong recent form")
fix_idx    = reasons_v.index("Favorable fixture")
xgi_idx    = reasons_v.index("High attacking involvement")
risk_idx   = reasons_v.index("Secure minutes")
ok(pen_idx  < form_idx,  "V2 role before form")
ok(form_idx < fix_idx,   "V3 form before fixture")
ok(fix_idx  < xgi_idx,   "V4 fixture before xGI")
ok(xgi_idx  < risk_idx,  "V5 xGI before risk")

# ---------------------------------------------------------------------------
# Section W — full profile: strong safe captain with penalty
# ---------------------------------------------------------------------------
_section("W — full profile: safe + penalty + strong inputs")
out_w = _out(
    tier="safe", score=59.85,
    web_name="Haaland", name="Erling Haaland", team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
    role_notes=["penalty_taker_1"],
)
reasons_w = explain_captain(out_w)
ok("Penalty taker"           in reasons_w, "W1 pen reason")
ok("Strong recent form"      in reasons_w, "W2 form reason")
ok("Favorable fixture"       in reasons_w, "W3 fixture reason")
ok("High attacking involvement" in reasons_w, "W4 xGI reason")
ok("Secure minutes"          in reasons_w, "W5 minutes reason")
ok("Weak recent form"        not in reasons_w, "W6 no weak form")
ok("Tough fixture"           not in reasons_w, "W7 no tough fixture")

# ---------------------------------------------------------------------------
# Section X — full profile: avoid candidate
# ---------------------------------------------------------------------------
_section("X — full profile: avoid candidate (high risk + weak inputs)")
out_x = _out(
    tier="avoid", score=12.0,
    inputs=_inputs(form=2.5, fdr=2, xgi=0.10, risk=100.0),
)
reasons_x = explain_captain(out_x)
ok("Weak recent form"          in reasons_x, "X1 weak form reason")
ok("Favorable fixture"         in reasons_x, "X2 favorable fixture (still noted)")
ok("Weak attacking process"    in reasons_x, "X3 weak xGI reason")
ok("Significant minutes risk"  in reasons_x, "X4 high risk reason")
ok("Strong recent form"        not in reasons_x, "X5 no strong form")
ok("Secure minutes"            not in reasons_x, "X6 no secure minutes")

# ---------------------------------------------------------------------------
# Section Y — full profile: differential
# ---------------------------------------------------------------------------
_section("Y — full profile: differential")
out_y = _out(
    tier="differential", score=39.0,
    inputs=_inputs(form=7.5, fdr=2, xgi=0.25, risk=0.0),
)
reasons_y = explain_captain(out_y)
ok("Strong recent form"             in reasons_y, "Y1 form reason")
ok("Favorable fixture"              in reasons_y, "Y2 fixture reason")
ok("High-upside differential profile" in reasons_y, "Y3 differential tier reason")
ok("Secure minutes"                 in reasons_y, "Y4 secure minutes")

# ---------------------------------------------------------------------------
# Section Z — explain_captain_compact excludes _COMPACT_EXCLUDED
# ---------------------------------------------------------------------------
_section("Z — explain_captain_compact excludes role + tier-summary reasons")
out_z = _out(
    tier="differential", score=42.0,
    inputs=_inputs(form=8.0, fdr=2, xgi=0.60, risk=0.0),
    role_notes=["penalty_taker_1"],
)
full_z    = explain_captain(out_z)
compact_z = explain_captain_compact(out_z)

ok("Penalty taker"                   in full_z,         "Z1 Penalty taker in full reasons")
ok("Penalty taker"                   not in compact_z,  "Z2 Penalty taker excluded from compact")
ok("High-upside differential profile" in full_z,        "Z3 tier summary in full reasons")
ok("High-upside differential profile" not in compact_z, "Z4 tier summary excluded from compact")
ok("Strong recent form"              in compact_z,       "Z5 form reason NOT excluded from compact")
ok("Favorable fixture"               in compact_z or "High attacking involvement" in compact_z,
   "Z6 fixture or xGI reason appears in compact")

# ---------------------------------------------------------------------------
# Section AA — compact cap enforced
# ---------------------------------------------------------------------------
_section("AA — compact cap enforced (max_reasons=2)")
out_aa = _out(
    tier="upside",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.60, risk=0.0),
)
compact_aa = explain_captain_compact(out_aa)
ok(len(compact_aa) <= 2,  "AA1 compact capped at 2 reasons by default")
compact_aa3 = explain_captain_compact(out_aa, max_reasons=3)
ok(len(compact_aa3) <= 3, "AA2 custom max_reasons=3 respected")

# Edge case: max_reasons=0
compact_aa0 = explain_captain_compact(out_aa, max_reasons=0)
ok(len(compact_aa0) == 0, "AA3 max_reasons=0 → empty list")

# ---------------------------------------------------------------------------
# Section AB — custom max_reasons parameter
# ---------------------------------------------------------------------------
_section("AB — custom max_reasons parameter")
out_ab = _out(
    tier="safe",
    inputs=_inputs(form=8.5, fdr=1, xgi=0.60, risk=0.0),
)
ok(len(explain_captain_compact(out_ab, max_reasons=1)) <= 1, "AB1 max_reasons=1")
ok(len(explain_captain_compact(out_ab, max_reasons=4)) <= 4, "AB2 max_reasons=4")

# ---------------------------------------------------------------------------
# Section AC — compact: non-ok → empty
# ---------------------------------------------------------------------------
_section("AC — compact: non-ok → empty")
ok(explain_captain_compact({"status": "ambiguous"}) == [], "AC1 ambiguous → []")
ok(explain_captain_compact({"status": "not_found"}) == [], "AC2 not_found → []")
ok(explain_captain_compact({}) == [],                      "AC3 empty dict → []")

# ---------------------------------------------------------------------------
# Section AD — compact: neutral range → empty (no reasons to compact)
# ---------------------------------------------------------------------------
_section("AD — compact: neutral range → empty")
out_ad = _out(tier="upside", inputs=_inputs(form=5.0, fdr=3, xgi=0.30, risk=10.0))
compact_ad = explain_captain_compact(out_ad)
ok(compact_ad == [], "AD1 neutral profile → empty compact list")

# ---------------------------------------------------------------------------
# Section AE — renderer appends Why clause when reasons exist
# ---------------------------------------------------------------------------
_section("AE — renderer: Why clause present when reasons exist")
out_ae = _out(
    tier="safe", score=59.85,
    web_name="Haaland", name="Erling Haaland", team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
)
result_ae = _render_get_captain_score(out_ae)
ok(" Why:" in result_ae,              "AE1 Why clause present")
ok("Strong recent form" in result_ae, "AE2 form reason in Why clause")
ok("Favorable fixture"  in result_ae, "AE3 fixture reason in Why clause")

# ---------------------------------------------------------------------------
# Section AF — renderer: Why clause absent when no reasons
# ---------------------------------------------------------------------------
_section("AF — renderer: Why clause absent for neutral profile")
out_af = _out(
    tier="upside", score=40.0,
    web_name="Player", name="Player Name", team_short="TST", position="MID",
    inputs=_inputs(form=5.0, fdr=3, xgi=0.25, risk=15.0),
)
result_af = _render_get_captain_score(out_af)
ok(" Why:" not in result_af, "AF1 no Why clause for all-neutral profile")

# ---------------------------------------------------------------------------
# Section AG — renderer: reasons include role + form + fixture
# ---------------------------------------------------------------------------
_section("AG — renderer: reasons include role + form + fixture in Why clause")
out_ag = _out(
    tier="safe", score=62.85,
    web_name="Haaland", name="Erling Haaland", team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
    role_notes=["penalty_taker_1"],
)
result_ag = _render_get_captain_score(out_ag)
ok("Penalty taker" in result_ag,        "AG1 penalty taker in Why clause (single-player shows role)")
ok("Strong recent form" in result_ag,   "AG2 form reason present")
ok("Favorable fixture"  in result_ag,   "AG3 fixture reason present")
ok("Secure minutes"     in result_ag,   "AG4 minutes reason present")
# Separator: semicolons used for Why clause
ok("Why:" in result_ag and ";" in result_ag.split("Why:")[1], "AG5 semicolons separate reasons")

# ---------------------------------------------------------------------------
# Section AH — renderer: avoid tier still has Why clause
# ---------------------------------------------------------------------------
_section("AH — renderer: avoid tier — Why clause still appended")
out_ah = _out(
    tier="avoid", score=10.0,
    web_name="Martial", name="Anthony Martial", team_short="MAN", position="FWD",
    inputs=_inputs(form=2.5, fdr=2, xgi=0.08, risk=100.0),
)
result_ah = _render_get_captain_score(out_ah)
ok("Avoid" in result_ah,              "AH1 Avoid tier label present")
ok("Not recommended" in result_ah,    "AH2 avoid note present")
ok("Why:" in result_ah,               "AH3 Why clause still appended for avoid")
ok("Weak recent form" in result_ah,   "AH4 weak form in Why")
ok("Significant minutes risk" in result_ah, "AH5 high risk in Why")

# ---------------------------------------------------------------------------
# Section AI — renderer: low_confidence — Why includes tier reason
# ---------------------------------------------------------------------------
_section("AI — renderer: low_confidence — Why includes tier summary")
out_ai = _out(
    tier="low_confidence", score=28.0,
    web_name="Bench", name="Bench Player", team_short="XXX", position="MID",
    inputs=_inputs(form=4.0, fdr=3, xgi=0.20, risk=20.0),
)
result_ai = _render_get_captain_score(out_ai)
ok("Low confidence" in result_ai,                    "AI1 tier label present")
ok("caution" in result_ai.lower(),                   "AI2 caution note from Phase 2i")
ok("Why:" in result_ai,                              "AI3 Why clause present")
ok("Low-confidence captaincy profile" in result_ai,  "AI4 tier summary in Why clause")

# ---------------------------------------------------------------------------
# Section AJ — renderer: non-ok branches produce no Why
# ---------------------------------------------------------------------------
_section("AJ — renderer: non-ok branches unchanged (no Why clause)")
for non_ok in (
    {"status": "ambiguous", "query": "X"},
    {"status": "not_found", "query": "Y"},
    {"status": "error", "code": "missing_argument", "message": "needs form"},
):
    r = _render_get_captain_score(non_ok)
    ok("Why:" not in r, f"AJ: no Why clause for status={non_ok.get('status')}")

# ---------------------------------------------------------------------------
# Section AK — renderer ranked: compact reasons per entry
# ---------------------------------------------------------------------------
_section("AK — renderer ranked: compact reasons per entry line")
entries_ak = [
    _rank_entry(1, "Haaland", "MCI", "safe",  59.85, inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0)),
    _rank_entry(2, "Salah",   "LIV", "upside", 47.20, inputs=_inputs(form=7.2, fdr=2, xgi=0.55, risk=0.0)),
]
result_ak = _render_rank_captain_candidates(_rank_ok(entries_ak))
haaland_line = [l for l in result_ak.split("\n") if "Haaland" in l][0]
salah_line   = [l for l in result_ak.split("\n") if "Salah" in l][0]
ok("(" in haaland_line,               "AK1 compact reasons in parens for Haaland")
ok("Strong recent form" in haaland_line, "AK2 form reason on Haaland line")
ok("Favorable fixture"  in haaland_line, "AK3 fixture reason on Haaland line")
ok("(" in salah_line,                 "AK4 compact reasons in parens for Salah")
ok("Strong recent form" in salah_line, "AK5 form reason on Salah line")

# ---------------------------------------------------------------------------
# Section AL — ranked: Penalty taker NOT in compact reasons
# ---------------------------------------------------------------------------
_section("AL — ranked: Penalty taker excluded from compact (already shown as · pen)")
entries_al = [
    _rank_entry(1, "Haaland", "MCI", "safe", 59.85,
                inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
                role_notes=["penalty_taker_1"]),
]
result_al = _render_rank_captain_candidates(_rank_ok(entries_al))
haaland_line_al = [l for l in result_al.split("\n") if "Haaland" in l][0]
ok("· pen" in haaland_line_al,             "AL1 set-piece suffix still present")
ok("Penalty taker" not in haaland_line_al, "AL2 Penalty taker NOT in compact reasons (already in · pen)")
ok("Strong recent form" in haaland_line_al,"AL3 form reason still in compact")

# ---------------------------------------------------------------------------
# Section AM — ranked: no reasons when neutral profile
# ---------------------------------------------------------------------------
_section("AM — ranked: no reasons when neutral profile")
entries_am = [
    _rank_entry(1, "Neutral", "NTL", "upside", 40.0, inputs=_inputs(form=5.0, fdr=3, xgi=0.25, risk=15.0)),
]
result_am = _render_rank_captain_candidates(_rank_ok(entries_am))
neutral_line = [l for l in result_am.split("\n") if "Neutral" in l][0]
ok("(" not in neutral_line, "AM1 no reasons clause when all inputs are neutral")

# ---------------------------------------------------------------------------
# Section AN — ranked: avoid entry has compact reasons
# ---------------------------------------------------------------------------
_section("AN — ranked: avoid entry gets compact reasons")
entries_an = [
    _rank_entry(1, "Haaland", "MCI", "safe",  59.85, inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0)),
    _rank_entry(2, "Martial", "MAN", "avoid",  8.00, inputs=_inputs(form=2.0, fdr=4, xgi=0.08, risk=100.0)),
]
result_an = _render_rank_captain_candidates(_rank_ok(entries_an))
martial_line = [l for l in result_an.split("\n") if "Martial" in l][0]
ok("[avoid]" in martial_line,             "AN1 avoid tier bracket on Martial line")
ok("(" in martial_line,                   "AN2 compact reasons present for avoid entry")
ok("Weak recent form" in martial_line or "Significant minutes risk" in martial_line or
   "Tough fixture" in martial_line, "AN3 at least one avoid-related reason on Martial line")

# ---------------------------------------------------------------------------
# Section AO — non-ok entry lines unchanged
# ---------------------------------------------------------------------------
_section("AO — non-ok entry lines in ranked list unchanged")
ok_entry_ao = _rank_entry(1, "Haaland", "MCI", "safe", 59.85)
non_ok_ao = {"status": "not_found", "query": "Ghost", "message": "not found", "index": 1}
mixed_ao = {"status": "ok", "ranked_candidates": [ok_entry_ao, non_ok_ao],
            "total": 1, "error_count": 1}
result_ao = _render_rank_captain_candidates(mixed_ao)
ok("Ghost" not in result_ao,                  "AO1 non-ok player not shown in list")
ok("candidate(s) could not be resolved" in result_ao, "AO2 error count note present")
ok("Why:" not in result_ao,                   "AO3 no Why clause in ranked output")

# ---------------------------------------------------------------------------
# Section AP — Phase 2i regression: tier brackets + set-piece suffix intact
# ---------------------------------------------------------------------------
_section("AP — Phase 2i regression: tier brackets + set-piece suffix intact")
out_ap = _out(
    tier="safe", score=59.85,
    web_name="Haaland", name="Erling Haaland", team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
    role_notes=["penalty_taker_1"],
)
result_ap = _render_get_captain_score(out_ap)
ok("Tier: Safe pick" in result_ap,           "AP1 tier label intact (Phase 2i)")
ok("Set-piece: penalty taker." in result_ap, "AP2 set-piece clause intact (Phase 2i)")

entries_ap = [
    _rank_entry(1, "Haaland", "MCI", "safe", 59.85,
                inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
                role_notes=["penalty_taker_1"]),
    _rank_entry(2, "Salah", "LIV", "upside", 47.20),
]
result_ap2 = _render_rank_captain_candidates(_rank_ok(entries_ap))
ok("[safe]" in result_ap2,   "AP3 tier bracket intact (Phase 2i)")
ok("[upside]" in result_ap2, "AP4 upside bracket intact (Phase 2i)")
ok("· pen" in result_ap2,    "AP5 set-piece suffix intact (Phase 2i)")

# ---------------------------------------------------------------------------
# Section AQ — Phase 2a/2b regression: all pre-existing output fields intact
# ---------------------------------------------------------------------------
_section("AQ — Phase 2a/2b regression: pre-existing renderer fields intact")
out_aq = _out(
    tier="safe", score=59.85,
    web_name="Haaland", name="Erling Haaland", team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
)
result_aq = _render_get_captain_score(out_aq)
ok("Haaland" in result_aq,     "AQ1 player name (Phase 2a)")
ok("MCI" in result_aq,         "AQ2 team_short (Phase 2a)")
ok("FWD" in result_aq,         "AQ3 position (Phase 2a)")
ok("59.85/100" in result_aq,   "AQ4 score (Phase 2a)")
ok("form 8.5" in result_aq,    "AQ5 form input (Phase 2a)")
ok("FDR 2" in result_aq,       "AQ6 FDR input (Phase 2a)")
ok("xGI/90 0.82" in result_aq, "AQ7 xGI input (Phase 2a)")
ok("min-risk 0.0" in result_aq,"AQ8 min-risk (Phase 2a)")
ok("Inputs:" in result_aq,     "AQ9 Inputs: prefix (Phase 2a)")

entries_aq = [_rank_entry(1, "Salah", "LIV", "upside", 48.0)]
result_aq2 = _render_rank_captain_candidates(_rank_ok(entries_aq))
ok("Captain rankings" in result_aq2,  "AQ10 rank header (Phase 2b)")
ok("1 player scored" in result_aq2,   "AQ11 total count (Phase 2b)")
ok("Salah" in result_aq2,             "AQ12 player name (Phase 2b)")

# ---------------------------------------------------------------------------
# Section AR — raw_output not mutated
# ---------------------------------------------------------------------------
_section("AR — raw_output not mutated by explain_captain() or renderer")
original_ar = _out(
    tier="safe", score=59.85, web_name="Haaland", name="Erling Haaland",
    team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
    role_notes=["penalty_taker_1"],
)
snapshot_ar = copy.deepcopy(original_ar)
_ = explain_captain(original_ar)
ok(original_ar == snapshot_ar, "AR1 explain_captain does not mutate raw_output")
_ = _render_get_captain_score(original_ar)
ok(original_ar == snapshot_ar, "AR2 renderer does not mutate raw_output")

# ---------------------------------------------------------------------------
# Section AS — interface report
# ---------------------------------------------------------------------------
_section("AS — interface report")
print()
print("  Phase 2j threshold constants:")
print(f"    FORM_HIGH={FORM_HIGH}, FORM_LOW={FORM_LOW}")
print(f"    FDR_EASY={FDR_EASY}, FDR_HARD={FDR_HARD}")
print(f"    XGI_HIGH={XGI_HIGH}, XGI_LOW={XGI_LOW}")
print(f"    RISK_ROTATION={RISK_ROTATION}, RISK_HIGH={RISK_HIGH}")
print()
print("  Sample single-player (safe + penalty + strong profile):")
sample_safe = _out(
    tier="safe", score=59.85, web_name="Haaland", name="Erling Haaland",
    team_short="MCI", position="FWD",
    inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
    role_notes=["penalty_taker_1"],
)
print("    " + _render_get_captain_score(sample_safe))
print()
print("  Sample single-player (avoid, high risk, weak profile):")
sample_avoid = _out(
    tier="avoid", score=10.0, web_name="Martial", name="Anthony Martial",
    team_short="MAN", position="FWD",
    inputs=_inputs(form=2.5, fdr=2, xgi=0.08, risk=100.0),
)
print("    " + _render_get_captain_score(sample_avoid))
print()
print("  Sample single-player (differential):")
sample_diff = _out(
    tier="differential", score=39.0, web_name="Mbeumo", name="Bryan Mbeumo",
    team_short="BRE", position="FWD",
    inputs=_inputs(form=7.5, fdr=2, xgi=0.25, risk=0.0),
)
print("    " + _render_get_captain_score(sample_diff))
print()
print("  Sample ranked output:")
entries_as = [
    _rank_entry(1, "Haaland", "MCI", "safe",  59.85,
                inputs=_inputs(form=8.5, fdr=2, xgi=0.82, risk=0.0),
                role_notes=["penalty_taker_1"]),
    _rank_entry(2, "Salah",   "LIV", "upside", 47.20,
                inputs=_inputs(form=7.2, fdr=2, xgi=0.55, risk=0.0)),
    _rank_entry(3, "Mbeumo",  "BRE", "differential", 39.0,
                inputs=_inputs(form=7.5, fdr=2, xgi=0.25, risk=0.0)),
    _rank_entry(4, "Martial", "MAN", "avoid",   8.00,
                inputs=_inputs(form=2.0, fdr=4, xgi=0.08, risk=100.0)),
]
for line in _render_rank_captain_candidates(_rank_ok(entries_as)).split("\n"):
    print("    " + line)
ok(True, "AS1 interface report generated")

# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------
total = _pass_count + _fail_count
print()
print(f"{'=' * 60}")
print(f"Phase 2j explainer tests: {_pass_count}/{total} PASS", end="")
if _fail_count:
    print(f"  ({_fail_count} FAIL)")
    sys.exit(1)
else:
    print()
    print("ALL ASSERTIONS PASS")


