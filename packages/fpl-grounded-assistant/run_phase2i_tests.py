"""
run_phase2i_tests.py
====================
Standalone validator for Phase 2i: renderer tier + role-signal surfacing.

Tests the updated renderer without requiring pytest or live FPL API data.
All assertions use fabricated raw_output dicts that mirror the structure
produced by fpl_tool_contract.tools after Phase 2g/2h.

Run:
    python run_phase2i_tests.py
    # Expected: all sections PASS, final count reported.

Sections
--------
A  _TIER_LABEL / _TIER_SHORT / _SET_PIECE_LABEL / _SET_PIECE_SHORT dicts
B  _tier_display() helper
C  _tier_short() helper
D  _set_piece_clause() helper
E  _set_piece_suffix() helper
F  _render_get_captain_score — ok, safe tier, no set-piece
G  _render_get_captain_score — ok, safe tier, penalty taker (pen_1)
H  _render_get_captain_score — ok, safe tier, freekick taker (fk_1)
I  _render_get_captain_score — ok, safe tier, combined pen+fk
J  _render_get_captain_score — ok, upside tier
K  _render_get_captain_score — ok, differential tier
L  _render_get_captain_score — ok, avoid tier, high minutes risk
M  _render_get_captain_score — ok, avoid tier, low score (risk < 50)
N  _render_get_captain_score — ok, low_confidence tier
O  _render_get_captain_score — ok, player with same web_name and name
P  _render_get_captain_score — ambiguous (unchanged from Phase 2a)
Q  _render_get_captain_score — not_found (unchanged)
R  _render_get_captain_score — error / missing_argument (unchanged)
S  _render_rank_captain_candidates — ok, all tiers represented, no set-piece
T  _render_rank_captain_candidates — ok, with set-piece suffixes
U  _render_rank_captain_candidates — avoid in ranked list, labelled correctly
V  _render_rank_captain_candidates — partial failures (non-ok entries)
W  _render_rank_captain_candidates — 0 ok entries, errors only
X  _render_rank_captain_candidates — top-10 cap and overflow text
Y  _render_rank_captain_candidates — error status (empty candidates)
Z  render() dispatch — tier surfaced for both tool names
AA raw_output not mutated by render() call
AB regression — existing Phase 2a/2b output fields still present
AC interface report
"""
from __future__ import annotations

import sys
import os

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
from fpl_grounded_assistant.renderer import (
    _TIER_LABEL,
    _TIER_SHORT,
    _SET_PIECE_LABEL,
    _SET_PIECE_SHORT,
    _tier_display,
    _tier_short,
    _set_piece_clause,
    _set_piece_suffix,
    _render_get_captain_score,
    _render_rank_captain_candidates,
    render,
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
# Fixtures — fabricated raw_output dicts
# ---------------------------------------------------------------------------

def _captain_output(
    score: float = 54.85,
    tier: str = "safe",
    risk: float = 0.0,
    set_piece_threat: bool = False,
    set_piece_notes: list[str] | None = None,
    role_bonus: float = 0.0,
    web_name: str = "Haaland",
    name: str = "Erling Haaland",
    team_short: str = "MCI",
    position: str = "FWD",
) -> dict:
    return {
        "status": "ok",
        "player_id": 355,
        "web_name": web_name,
        "name": name,
        "team": "Manchester City",
        "team_short": team_short,
        "position": position,
        "captain_score": score,
        "tier": tier,
        "role_signals": {
            "penalties_order": 1 if "penalty_taker_1" in (set_piece_notes or []) else None,
            "direct_freekicks_order": 1 if "freekick_taker_1" in (set_piece_notes or []) else None,
            "corners_and_indirect_freekicks_order": None,
            "set_piece_notes": set_piece_notes or [],
            "set_piece_threat": set_piece_threat,
            "role_bonus": role_bonus,
        },
        "score_inputs": {
            "form": 8.5,
            "fixture_difficulty": 2,
            "xgi_per_90": 0.82,
            "minutes_risk": risk,
        },
        "derived_fields": ["form", "fixture_difficulty", "minutes_risk", "xgi_per_90"],
        "query": "Haaland",
    }


def _rank_entry(
    rank: int,
    web_name: str,
    team_short: str,
    position: str,
    score: float,
    tier: str,
    set_piece_threat: bool = False,
    set_piece_notes: list[str] | None = None,
    role_bonus: float = 0.0,
) -> dict:
    return {
        "status": "ok",
        "index": rank - 1,
        "rank": rank,
        "player_id": rank * 10,
        "web_name": web_name,
        "name": web_name,
        "team": web_name + " FC",
        "team_short": team_short,
        "position": position,
        "captain_score": score,
        "tier": tier,
        "role_signals": {
            "set_piece_notes": set_piece_notes or [],
            "set_piece_threat": set_piece_threat,
            "role_bonus": role_bonus,
        },
        "score_inputs": {"form": 7.0, "fixture_difficulty": 2, "xgi_per_90": 0.5, "minutes_risk": 0.0},
        "derived_fields": [],
        "query": web_name,
    }


def _rank_ok_output(entries: list[dict], errors: int = 0) -> dict:
    return {
        "status": "ok",
        "ranked_candidates": entries,
        "total": len(entries),
        "error_count": errors,
    }


# ---------------------------------------------------------------------------
# Section A — display dict structure
# ---------------------------------------------------------------------------
_section("A — _TIER_LABEL / _TIER_SHORT / _SET_PIECE_LABEL / _SET_PIECE_SHORT")
for tier in ("safe", "upside", "differential", "avoid", "low_confidence"):
    ok(tier in _TIER_LABEL, f"_TIER_LABEL has key '{tier}'")
    ok(tier in _TIER_SHORT, f"_TIER_SHORT has key '{tier}'")
ok(_TIER_LABEL["safe"] == "Safe pick",           "_TIER_LABEL safe='Safe pick'")
ok(_TIER_LABEL["upside"] == "Upside pick",       "_TIER_LABEL upside='Upside pick'")
ok(_TIER_LABEL["differential"] == "Differential","_TIER_LABEL differential='Differential'")
ok(_TIER_LABEL["avoid"] == "Avoid",              "_TIER_LABEL avoid='Avoid'")
ok(_TIER_LABEL["low_confidence"] == "Low confidence", "_TIER_LABEL low_confidence='Low confidence'")
ok(_TIER_SHORT["safe"] == "safe",                "_TIER_SHORT safe='safe'")
ok(_TIER_SHORT["differential"] == "diff",        "_TIER_SHORT differential='diff'")
ok(_TIER_SHORT["low_confidence"] == "?",         "_TIER_SHORT low_confidence='?'")
for note in ("penalty_taker_1", "penalty_taker_2", "freekick_taker_1", "freekick_taker_2"):
    ok(note in _SET_PIECE_LABEL, f"_SET_PIECE_LABEL has key '{note}'")
    ok(note in _SET_PIECE_SHORT, f"_SET_PIECE_SHORT has key '{note}'")
ok(_SET_PIECE_LABEL["penalty_taker_1"] == "penalty taker",    "SET_PIECE_LABEL pen1='penalty taker'")
ok(_SET_PIECE_LABEL["penalty_taker_2"] == "2nd penalty taker","SET_PIECE_LABEL pen2='2nd penalty taker'")
ok(_SET_PIECE_LABEL["freekick_taker_1"] == "free-kick taker", "SET_PIECE_LABEL fk1='free-kick taker'")
ok(_SET_PIECE_SHORT["penalty_taker_1"] == "pen",              "SET_PIECE_SHORT pen1='pen'")
ok(_SET_PIECE_SHORT["freekick_taker_1"] == "FK",              "SET_PIECE_SHORT fk1='FK'")

# ---------------------------------------------------------------------------
# Section B — _tier_display()
# ---------------------------------------------------------------------------
_section("B — _tier_display()")
ok(_tier_display("safe") == "Safe pick",          "_tier_display safe")
ok(_tier_display("upside") == "Upside pick",      "_tier_display upside")
ok(_tier_display("differential") == "Differential","_tier_display differential")
ok(_tier_display("avoid") == "Avoid",             "_tier_display avoid")
ok(_tier_display("low_confidence") == "Low confidence","_tier_display low_confidence")
ok(_tier_display("unknown_tier") == "unknown_tier","_tier_display unknown passthrough")

# ---------------------------------------------------------------------------
# Section C — _tier_short()
# ---------------------------------------------------------------------------
_section("C — _tier_short()")
ok(_tier_short("safe") == "safe",                "_tier_short safe")
ok(_tier_short("upside") == "upside",            "_tier_short upside")
ok(_tier_short("differential") == "diff",        "_tier_short differential")
ok(_tier_short("avoid") == "avoid",              "_tier_short avoid")
ok(_tier_short("low_confidence") == "?",         "_tier_short low_confidence")
ok(_tier_short("xyz") == "xyz",                  "_tier_short unknown passthrough")

# ---------------------------------------------------------------------------
# Section D — _set_piece_clause()
# ---------------------------------------------------------------------------
_section("D — _set_piece_clause()")
no_role = {"set_piece_threat": False, "set_piece_notes": []}
pen1    = {"set_piece_threat": True,  "set_piece_notes": ["penalty_taker_1"]}
pen2    = {"set_piece_threat": True,  "set_piece_notes": ["penalty_taker_2"]}
fk1     = {"set_piece_threat": True,  "set_piece_notes": ["freekick_taker_1"]}
fk2     = {"set_piece_threat": True,  "set_piece_notes": ["freekick_taker_2"]}
combo   = {"set_piece_threat": True,  "set_piece_notes": ["penalty_taker_1", "freekick_taker_1"]}
corners = {"set_piece_threat": False, "set_piece_notes": []}  # corners never produce a bonus

ok(_set_piece_clause(no_role) == "",                                "clause no role = empty")
ok(_set_piece_clause(pen1) == " Set-piece: penalty taker.",         "clause pen1")
ok(_set_piece_clause(pen2) == " Set-piece: 2nd penalty taker.",     "clause pen2")
ok(_set_piece_clause(fk1) == " Set-piece: free-kick taker.",        "clause fk1")
ok(_set_piece_clause(fk2) == " Set-piece: 2nd free-kick taker.",    "clause fk2")
ok(_set_piece_clause(combo) == " Set-piece: penalty taker, free-kick taker.", "clause combo")
ok(_set_piece_clause(corners) == "",                                "clause corners = empty")
# No double-period guarantee
for sig in (pen1, pen2, fk1, fk2, combo):
    clause = _set_piece_clause(sig)
    ok(".." not in clause, f"no double-period in clause for {sig['set_piece_notes']}")
# Starts with space, ends with period
ok(_set_piece_clause(pen1).startswith(" "),   "clause starts with space")
ok(_set_piece_clause(pen1).endswith("."),     "clause ends with period")

# ---------------------------------------------------------------------------
# Section E — _set_piece_suffix()
# ---------------------------------------------------------------------------
_section("E — _set_piece_suffix()")
ok(_set_piece_suffix(no_role) == "",           "suffix no role = empty")
ok(_set_piece_suffix(pen1) == " · pen",        "suffix pen1")
ok(_set_piece_suffix(pen2) == " · 2nd pen",    "suffix pen2")
ok(_set_piece_suffix(fk1) == " · FK",          "suffix fk1")
ok(_set_piece_suffix(fk2) == " · 2nd FK",      "suffix fk2")
ok(_set_piece_suffix(combo) == " · pen, FK",   "suffix combo")
ok(_set_piece_suffix(corners) == "",           "suffix corners = empty")
ok(_set_piece_suffix(pen1).startswith(" · "), "suffix starts with ' · '")

# ---------------------------------------------------------------------------
# Section F — single player, safe tier, no set-piece
# ---------------------------------------------------------------------------
_section("F — _render_get_captain_score ok safe, no set-piece")
out = _captain_output(score=54.85, tier="safe", risk=0.0)
result = _render_get_captain_score(out)
ok("Haaland" in result,        "F1 player name present")
ok("MCI" in result,            "F2 team_short present")
ok("FWD" in result,            "F3 position present")
ok("54.85/100" in result,      "F4 score present")
ok("Safe pick" in result,      "F5 tier label present")
ok("Tier:" in result,          "F6 Tier label prefix present")
ok("Inputs:" in result,        "F7 Inputs prefix present")
ok("form 8.5" in result,       "F8 form input present")
ok("FDR 2" in result,          "F9 FDR input present")
ok("xGI/90 0.82" in result,    "F10 xGI/90 input present")
ok("min-risk 0.0" in result,   "F11 min-risk input present")
ok("Set-piece" not in result,  "F12 no set-piece clause when no role")
ok(".." not in result,         "F13 no double period")
ok("Not recommended" not in result, "F14 no avoid note for safe tier")
ok("caution" not in result,    "F15 no caution note for safe tier")

# ---------------------------------------------------------------------------
# Section G — safe tier, penalty taker (pen_1)
# ---------------------------------------------------------------------------
_section("G — _render_get_captain_score ok safe, penalty_taker_1")
out_g = _captain_output(
    score=59.85, tier="safe", risk=0.0,
    set_piece_threat=True, set_piece_notes=["penalty_taker_1"], role_bonus=5.0,
)
result_g = _render_get_captain_score(out_g)
ok("Safe pick" in result_g,                   "G1 tier label")
ok("Set-piece: penalty taker." in result_g,   "G2 set-piece clause")
ok(".." not in result_g,                      "G3 no double period")
ok("Not recommended" not in result_g,         "G4 no avoid note")
ok(result_g.endswith("penalty taker."),       "G5 ends with set-piece clause")

# ---------------------------------------------------------------------------
# Section H — safe tier, freekick taker (fk_1)
# ---------------------------------------------------------------------------
_section("H — _render_get_captain_score ok safe, freekick_taker_1")
out_h = _captain_output(
    score=57.85, tier="safe", risk=0.0,
    set_piece_threat=True, set_piece_notes=["freekick_taker_1"], role_bonus=3.0,
)
result_h = _render_get_captain_score(out_h)
ok("Safe pick" in result_h,                    "H1 tier label")
ok("Set-piece: free-kick taker." in result_h,  "H2 set-piece clause")
ok(".." not in result_h,                       "H3 no double period")

# ---------------------------------------------------------------------------
# Section I — safe tier, combined pen_1 + fk_1
# ---------------------------------------------------------------------------
_section("I — _render_get_captain_score ok safe, pen+fk combo")
out_i = _captain_output(
    score=62.85, tier="safe", risk=0.0,
    set_piece_threat=True,
    set_piece_notes=["penalty_taker_1", "freekick_taker_1"],
    role_bonus=8.0,
)
result_i = _render_get_captain_score(out_i)
ok("Safe pick" in result_i,                                        "I1 tier label")
ok("penalty taker, free-kick taker" in result_i,                   "I2 combo clause")
ok("Set-piece: penalty taker, free-kick taker." in result_i,       "I3 full clause")
ok(".." not in result_i,                                           "I4 no double period")

# ---------------------------------------------------------------------------
# Section J — upside tier
# ---------------------------------------------------------------------------
_section("J — _render_get_captain_score ok upside")
out_j = _captain_output(score=44.00, tier="upside", risk=5.0)
result_j = _render_get_captain_score(out_j)
ok("Upside pick" in result_j,          "J1 tier label")
ok("44.0/100" in result_j,             "J2 score")
ok("Not recommended" not in result_j,  "J3 no avoid note")
ok("Set-piece" not in result_j,        "J4 no set-piece (none provided)")

# ---------------------------------------------------------------------------
# Section K — differential tier
# ---------------------------------------------------------------------------
_section("K — _render_get_captain_score ok differential")
out_k = _captain_output(score=39.00, tier="differential", risk=0.0)
result_k = _render_get_captain_score(out_k)
ok("Differential" in result_k,        "K1 tier label")
ok("Not recommended" not in result_k, "K2 no avoid note")

# ---------------------------------------------------------------------------
# Section L — avoid tier, high minutes risk
# ---------------------------------------------------------------------------
_section("L — _render_get_captain_score ok avoid (high risk)")
out_l = _captain_output(score=25.00, tier="avoid", risk=100.0)
result_l = _render_get_captain_score(out_l)
ok("Avoid" in result_l,               "L1 tier label")
ok("Not recommended" in result_l,     "L2 avoid note present")
ok("high minutes risk" in result_l.lower() or "minutes risk" in result_l.lower(),
   "L3 reason mentioned")
ok("min-risk 100.0" in result_l,      "L4 risk value visible")
ok("Set-piece" not in result_l,       "L5 no set-piece clause")

# ---------------------------------------------------------------------------
# Section M — avoid tier, low score (risk < 50)
# ---------------------------------------------------------------------------
_section("M — _render_get_captain_score ok avoid (low score)")
out_m = _captain_output(score=10.00, tier="avoid", risk=0.0)
result_m = _render_get_captain_score(out_m)
ok("Avoid" in result_m,                   "M1 tier label")
ok("Not recommended" in result_m,         "M2 avoid note present")
ok("threshold" in result_m.lower() or "score" in result_m.lower(), "M3 reason mentioned")

# ---------------------------------------------------------------------------
# Section N — low_confidence tier
# ---------------------------------------------------------------------------
_section("N — _render_get_captain_score ok low_confidence")
out_n = _captain_output(score=30.00, tier="low_confidence", risk=10.0)
result_n = _render_get_captain_score(out_n)
ok("Low confidence" in result_n,       "N1 tier label")
ok("caution" in result_n.lower(),      "N2 caution note present")
ok("Set-piece" not in result_n,        "N3 no set-piece clause")

# ---------------------------------------------------------------------------
# Section O — player where web_name == name (no parentheses)
# ---------------------------------------------------------------------------
_section("O — single player, same web_name and name")
out_o = _captain_output(web_name="Salah", name="Salah", team_short="LIV", tier="safe")
result_o = _render_get_captain_score(out_o)
ok("Salah (Salah)" not in result_o, "O1 no duplicate name parentheses")
ok("Salah" in result_o,             "O2 name appears")
ok("LIV" in result_o,               "O3 team present")

# ---------------------------------------------------------------------------
# Section P — ambiguous (non-ok, unchanged)
# ---------------------------------------------------------------------------
_section("P — ambiguous (unchanged)")
out_p = {"status": "ambiguous", "query": "Johnson"}
result_p = _render_get_captain_score(out_p)
ok("Multiple players" in result_p,        "P1 multiple players message")
ok("Johnson" in result_p,                 "P2 query name in message")
ok("Safe pick" not in result_p,           "P3 no tier in ambiguous response")
ok("Set-piece" not in result_p,           "P4 no set-piece in ambiguous response")
ok("disambiguate" in result_p.lower(),    "P5 disambiguation guidance present")

# ---------------------------------------------------------------------------
# Section Q — not_found (unchanged)
# ---------------------------------------------------------------------------
_section("Q — not_found (unchanged)")
out_q = {"status": "not_found", "query": "Neymar Jr"}
result_q = _render_get_captain_score(out_q)
ok("No player found" in result_q,         "Q1 not found message")
ok("Neymar Jr" in result_q,               "Q2 query name in message")
ok("Safe pick" not in result_q,           "Q3 no tier in not_found response")
ok("Set-piece" not in result_q,           "Q4 no set-piece in not_found response")

# ---------------------------------------------------------------------------
# Section R — error / missing_argument (unchanged)
# ---------------------------------------------------------------------------
_section("R — error/missing_argument (unchanged)")
out_r_miss = {"status": "error", "code": "missing_argument", "message": "needs form"}
result_r1 = _render_get_captain_score(out_r_miss)
ok("Captain scoring requires" in result_r1, "R1 missing_argument message")
ok("Safe pick" not in result_r1,            "R2 no tier in error response")

out_r_gen = {"status": "error", "code": "internal", "message": "oops"}
result_r2 = _render_get_captain_score(out_r_gen)
ok("Error (internal)" in result_r2,         "R3 generic error message")

# ---------------------------------------------------------------------------
# Section S — ranked ok, mixed tiers, no set-piece
# ---------------------------------------------------------------------------
_section("S — rank candidates ok, mixed tiers, no set-piece")
entries_s = [
    _rank_entry(1, "Haaland", "MCI", "FWD", 59.85, "safe"),
    _rank_entry(2, "Salah",   "LIV", "MID", 47.20, "upside"),
    _rank_entry(3, "Palmer",  "CHE", "MID", 39.00, "differential"),
    _rank_entry(4, "Martial", "MAN", "FWD", 12.00, "avoid"),
]
result_s = _render_rank_captain_candidates(_rank_ok_output(entries_s))
ok("Captain rankings" in result_s,    "S1 header present")
ok("4 players scored" in result_s,    "S2 total count in header")
ok("[safe]" in result_s,              "S3 safe tier label")
ok("[upside]" in result_s,            "S4 upside tier label")
ok("[diff]" in result_s,              "S5 differential tier label (short)")
ok("[avoid]" in result_s,             "S6 avoid tier label")
ok("59.85/100" in result_s,           "S7 score for rank 1")
ok("· " not in result_s,             "S8 no set-piece suffix when no set-piece roles")

# ---------------------------------------------------------------------------
# Section T — ranked ok, with set-piece suffixes
# ---------------------------------------------------------------------------
_section("T — rank candidates ok, set-piece suffixes")
entries_t = [
    _rank_entry(1, "Haaland", "MCI", "FWD", 59.85, "safe",
                set_piece_threat=True, set_piece_notes=["penalty_taker_1"], role_bonus=5.0),
    _rank_entry(2, "Palmer",  "CHE", "MID", 42.00, "upside",
                set_piece_threat=True, set_piece_notes=["freekick_taker_1"], role_bonus=3.0),
    _rank_entry(3, "Salah",   "LIV", "MID", 47.20, "safe"),
]
result_t = _render_rank_captain_candidates(_rank_ok_output(entries_t))
ok("· pen" in result_t,             "T1 penalty taker suffix for Haaland")
ok("· FK" in result_t,              "T2 FK suffix for Palmer")
ok("[safe]" in result_t,            "T3 safe tier brackets")
ok("[upside]" in result_t,          "T4 upside tier brackets")
# Salah has no set-piece role — verify no suffix on that line
salah_line = [l for l in result_t.split("\n") if "Salah" in l]
ok(len(salah_line) == 1,            "T5 exactly one Salah line")
ok("· " not in salah_line[0],       "T6 no set-piece suffix on Salah line")

# ---------------------------------------------------------------------------
# Section U — avoid in ranked list labelled correctly
# ---------------------------------------------------------------------------
_section("U — avoid candidate in ranked list")
entries_u = [
    _rank_entry(1, "Haaland", "MCI", "FWD", 59.85, "safe"),
    _rank_entry(2, "Martial", "MAN", "FWD", 5.00,  "avoid"),
]
result_u = _render_rank_captain_candidates(_rank_ok_output(entries_u))
ok("[avoid]" in result_u,              "U1 avoid tier labelled in ranking")
ok("5.0/100" in result_u,             "U2 avoid candidate score shown")
martial_line = [l for l in result_u.split("\n") if "Martial" in l][0]
ok("[avoid]" in martial_line,          "U3 avoid bracket on Martial line")
ok("Not recommended" not in result_u,  "U4 no hedging prose in ranked list (single-player only)")

# ---------------------------------------------------------------------------
# Section V — partial failures (non-ok entries)
# ---------------------------------------------------------------------------
_section("V — rank candidates partial failures")
ok_entry = _rank_entry(1, "Haaland", "MCI", "FWD", 59.85, "safe")
non_ok_entry = {
    "status": "not_found",
    "query": "Fake Player",
    "message": "No player found matching 'Fake Player'.",
    "index": 1,
}
mixed_output = {
    "status": "ok",
    "ranked_candidates": [ok_entry, non_ok_entry],
    "total": 1,
    "error_count": 1,
}
result_v = _render_rank_captain_candidates(mixed_output)
ok("Captain rankings" in result_v,           "V1 header present")
ok("1 player scored" in result_v,            "V2 total = 1")
ok("1 candidate(s) could not be resolved" in result_v, "V3 error count note")
ok("Haaland" in result_v,                    "V4 ok candidate shown")
ok("Fake Player" not in result_v,            "V5 failed candidate not shown in list")

# ---------------------------------------------------------------------------
# Section W — zero ok entries, errors only
# ---------------------------------------------------------------------------
_section("W — zero ok entries")
empty_out = {
    "status": "ok",
    "ranked_candidates": [
        {"status": "not_found", "query": "Nobody", "message": "not found", "index": 0},
    ],
    "total": 0,
    "error_count": 1,
}
result_w = _render_rank_captain_candidates(empty_out)
ok("No captain candidates could be ranked" in result_w, "W1 no-candidates message")
ok("1 candidate(s) failed" in result_w,                 "W2 error count in message")

# ---------------------------------------------------------------------------
# Section X — top-10 cap and overflow text
# ---------------------------------------------------------------------------
_section("X — top-10 cap + overflow")
entries_x = [
    _rank_entry(i, f"Player{i}", "XXX", "MID", float(100 - i), "upside")
    for i in range(1, 14)
]
result_x = _render_rank_captain_candidates(_rank_ok_output(entries_x))
lines_x = [l for l in result_x.split("\n") if l.strip().startswith(tuple("123456789"))]
ok(len(lines_x) == 10,                 "X1 exactly 10 player lines rendered")
ok("... and 3 more" in result_x,       "X2 overflow text present")

# ---------------------------------------------------------------------------
# Section Y — error status (empty candidates list)
# ---------------------------------------------------------------------------
_section("Y — error status (empty candidates)")
error_out = {
    "status": "error",
    "code": "missing_argument",
    "message": "candidates list is empty — at least one candidate is required.",
}
result_y = _render_rank_captain_candidates(error_out)
ok("Captain ranking requires" in result_y, "Y1 error message for empty list")
ok("[safe]" not in result_y,              "Y2 no tier brackets in error response")

# ---------------------------------------------------------------------------
# Section Z — render() dispatch
# ---------------------------------------------------------------------------
_section("Z — render() dispatch")
out_z = _captain_output(score=54.85, tier="safe")
r_z1 = render("get_captain_score", out_z)
ok("Safe pick" in r_z1,              "Z1 get_captain_score dispatch surfaces tier")

entries_z = [_rank_entry(1, "Salah", "LIV", "MID", 48.0, "upside")]
out_z2 = _rank_ok_output(entries_z)
r_z2 = render("rank_captain_candidates", out_z2)
ok("[upside]" in r_z2,              "Z2 rank_captain_candidates dispatch surfaces tier")

# Unknown tool still falls through safely
r_z3 = render("unknown_tool_xyz", {"code": "unknown_tool", "message": "no renderer"})
ok("Error" in r_z3,                 "Z3 unknown tool fallback is safe")

# ---------------------------------------------------------------------------
# Section AA — raw_output not mutated by render()
# ---------------------------------------------------------------------------
_section("AA — raw_output immutability")
import copy
original = _captain_output(score=54.85, tier="safe", set_piece_threat=True, set_piece_notes=["penalty_taker_1"])
snapshot = copy.deepcopy(original)
_ = render("get_captain_score", original)
ok(original == snapshot, "AA1 raw_output not mutated by render()")

original_rank = _rank_ok_output([_rank_entry(1, "Salah", "LIV", "MID", 48.0, "upside")])
snapshot_rank = copy.deepcopy(original_rank)
_ = render("rank_captain_candidates", original_rank)
ok(original_rank == snapshot_rank, "AA2 rank raw_output not mutated by render()")

# ---------------------------------------------------------------------------
# Section AB — regression, existing fields still present
# ---------------------------------------------------------------------------
_section("AB — regression, existing Phase 2a/2b output fields present")
out_ab = _captain_output(score=54.85, tier="safe")
result_ab = _render_get_captain_score(out_ab)
ok("Haaland" in result_ab,     "AB1 player name present (Phase 2a)")
ok("MCI" in result_ab,         "AB2 team_short present (Phase 2a)")
ok("FWD" in result_ab,         "AB3 position present (Phase 2a)")
ok("54.85/100" in result_ab,   "AB4 score present (Phase 2a)")
ok("form 8.5" in result_ab,    "AB5 form input present (Phase 2a)")
ok("FDR 2" in result_ab,       "AB6 FDR input present (Phase 2a)")
ok("xGI/90 0.82" in result_ab, "AB7 xGI/90 input present (Phase 2a)")
ok("min-risk 0.0" in result_ab,"AB8 min-risk input present (Phase 2a)")

entries_ab = [_rank_entry(1, "Salah", "LIV", "MID", 48.0, "upside")]
result_ab2 = _render_rank_captain_candidates(_rank_ok_output(entries_ab))
ok("Captain rankings" in result_ab2,  "AB9 rank header present (Phase 2b)")
ok("1 player scored" in result_ab2,   "AB10 total count present (Phase 2b)")
ok("Salah" in result_ab2,             "AB11 player name present (Phase 2b)")
ok("48.0/100" in result_ab2,          "AB12 score present (Phase 2b)")
ok("LIV" in result_ab2,               "AB13 team_short present (Phase 2b)")

# ---------------------------------------------------------------------------
# Section AC — interface report
# ---------------------------------------------------------------------------
_section("AC — interface report")
print()
print("  _TIER_LABEL keys: " + ", ".join(sorted(_TIER_LABEL)))
print("  _SET_PIECE_LABEL keys: " + ", ".join(sorted(_SET_PIECE_LABEL)))
print()
print("  Sample single-player safe+pen output:")
sample = _captain_output(
    score=59.85, tier="safe", risk=0.0,
    set_piece_threat=True, set_piece_notes=["penalty_taker_1"], role_bonus=5.0,
)
print("    " + _render_get_captain_score(sample))
print()
print("  Sample avoid output:")
sample_avoid = _captain_output(score=10.00, tier="avoid", risk=100.0)
print("    " + _render_get_captain_score(sample_avoid))
print()
print("  Sample ranked output (3 players):")
entries_sample = [
    _rank_entry(1, "Haaland", "MCI", "FWD", 59.85, "safe",
                set_piece_threat=True, set_piece_notes=["penalty_taker_1"]),
    _rank_entry(2, "Salah", "LIV", "MID", 47.20, "upside"),
    _rank_entry(3, "Martial", "MAN", "FWD", 12.00, "avoid"),
]
for line in _render_rank_captain_candidates(_rank_ok_output(entries_sample)).split("\n"):
    print("    " + line)
ok(True, "AC1 interface report generated")

# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------
total = _pass_count + _fail_count
print()
print(f"{'=' * 60}")
print(f"Phase 2i renderer tests: {_pass_count}/{total} PASS", end="")
if _fail_count:
    print(f"  ({_fail_count} FAIL)")
    sys.exit(1)
else:
    print()
    print("ALL ASSERTIONS PASS")


