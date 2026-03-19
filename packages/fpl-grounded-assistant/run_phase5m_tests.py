"""
Phase 5m tests — Captain Tier Framing Consistency.

Tests 81 assertions across sections:
  A  fpl_captain_engine exports — classify_captain_tier, derive_role_signals
  B  tool_get_captain_score enriched output — tier, role_signals, real inputs
  C  tool_rank_captain_candidates enriched output — tier, role_signals per candidate
  D  Captain score renderer — framing for each tier (Haaland/Salah/Saka/De Bruyne)
  E  Rank renderer — multi-candidate formatted output
  F  Tier vocabulary consistency — same player gets same tier from both tools
  G  respond() pipeline — captain score answer_text no longer an error message
  H  Regression — comparison and session-inspect behavior unchanged

Run with:
    cd packages/fpl-grounded-assistant
    PYTHONPATH=../../packages/fpl-captain-engine/fpl_captain_engine:../../packages/fpl-captain-engine:../../packages/fpl-tool-runner:../../packages/fpl-tool-contract:../../packages/fpl-query-tools:../../packages/fpl-player-registry:../../packages/fpl-api-client:../../packages/fpl-pipeline:. python run_phase5m_tests.py
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# sys.path bootstrap — must come before any fpl_* imports
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

PASS = 0
FAIL = 0

def ok(label: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL  {label}")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant import render, respond
from fpl_grounded_assistant.renderer import (
    _TIER_LABEL, _TIER_SHORT, _tier_display, _tier_short,
    _render_get_captain_score, _render_rank_captain_candidates,
)
from fpl_tool_contract import tool_get_captain_score, tool_rank_captain_candidates
from fpl_tool_runner import run_tool

# ---------------------------------------------------------------------------
# Shared test bootstrap
# ---------------------------------------------------------------------------

BS = STANDARD_BOOTSTRAP
# Expected real-data scoring inputs (derived from STANDARD_BOOTSTRAP)
#   Haaland: form=8.0, FDR=4, xgi=1.70/(1800/90)=0.085, risk=0.0 → score=54.85 → upside
#   Salah:   form=9.5, FDR=4, xgi=1.45/(2250/90)=0.058, risk=0.0 → score=60.58 → safe
#   Saka:    form=5.5, FDR=5, xgi=0.85/(900/90)=0.085,  risk=25.0 → score=36.35 → differential
#   DeBruyne:form=0.0, FDR=4, xgi=0.60/(270/90)=0.2,    risk=100.0→ score=14.0  → avoid

print("=" * 60)
print("Phase 5m — Captain Tier Framing Consistency")
print("=" * 60)


# ===========================================================================
# Section A: fpl_captain_engine exports
# ===========================================================================
print("\n--- A: fpl_captain_engine exports ---")

from fpl_captain_engine import (
    classify_captain_tier,
    derive_role_signals,
    TIER_SAFE, TIER_UPSIDE, TIER_DIFFERENTIAL, TIER_AVOID, TIER_LOW_CONFIDENCE,
    ALL_TIERS,
)

ok("A1  classify_captain_tier callable",      callable(classify_captain_tier))
ok("A2  derive_role_signals callable",        callable(derive_role_signals))
ok("A3  TIER_SAFE == 'safe'",                 TIER_SAFE == "safe")
ok("A4  TIER_UPSIDE == 'upside'",             TIER_UPSIDE == "upside")
ok("A5  TIER_DIFFERENTIAL == 'differential'", TIER_DIFFERENTIAL == "differential")
ok("A6  TIER_AVOID == 'avoid'",               TIER_AVOID == "avoid")
ok("A7  TIER_LOW_CONFIDENCE == 'low_confidence'", TIER_LOW_CONFIDENCE == "low_confidence")
ok("A8  ALL_TIERS has 5 entries",             len(ALL_TIERS) == 5)

# Spot-check classify_captain_tier
ok("A9  Salah-like → safe",        classify_captain_tier(60.58, 0.0, 0.058) == "safe")
ok("A10 Haaland-like → upside",    classify_captain_tier(54.85, 0.0, 0.085) == "upside")
ok("A11 Saka-like → differential", classify_captain_tier(36.35, 25.0, 0.085) == "differential")
ok("A12 injured → avoid",          classify_captain_tier(14.0, 100.0, 0.20) == "avoid")
ok("A13 catch-all → low_confidence", classify_captain_tier(25.0, 40.0, 0.05) == "low_confidence")


# ===========================================================================
# Section B: tool_get_captain_score enriched output
# ===========================================================================
print("\n--- B: tool_get_captain_score enriched output ---")

_h = tool_get_captain_score("Haaland", BS)  # no candidate_inputs → auto-derive
ok("B1  Haaland status ok",              _h["status"] == "ok")
ok("B2  Haaland tier present",           "tier" in _h)
ok("B3  Haaland tier == 'upside'",       _h["tier"] == "upside")
ok("B4  Haaland role_signals present",   "role_signals" in _h)
ok("B5  Haaland pen note present",       "penalty_taker_1" in _h["role_signals"].get("set_piece_notes", []))
ok("B6  Haaland role_bonus == 5.0",      _h["role_signals"].get("role_bonus") == 5.0)
ok("B7  Haaland score_inputs form=8.0",  _h["score_inputs"]["form"] == 8.0)
ok("B8  Haaland score ≈ 54.85",          abs(_h["captain_score"] - 54.85) < 0.01)

_s = tool_get_captain_score("Salah", BS)
ok("B9  Salah tier == 'safe'",           _s["tier"] == "safe")
ok("B10 Salah score ≈ 60.58",            abs(_s["captain_score"] - 60.58) < 0.01)
ok("B11 Salah role_signals has pen",     "penalty_taker_1" in _s["role_signals"].get("set_piece_notes", []))

_sk = tool_get_captain_score("Saka", BS)
ok("B12 Saka tier == 'differential'",    _sk["tier"] == "differential")
ok("B13 Saka score ≈ 36.35",             abs(_sk["captain_score"] - 36.35) < 0.01)
ok("B14 Saka fk2 role note",             "freekick_taker_2" in _sk["role_signals"].get("set_piece_notes", []))
ok("B15 Saka minutes_risk ≈ 25.0",       abs(_sk["score_inputs"]["minutes_risk"] - 25.0) < 0.01)

_db = tool_get_captain_score("De Bruyne", BS)
ok("B16 DeBruyne tier == 'avoid'",       _db["tier"] == "avoid")
ok("B17 DeBruyne score ≈ 14.0",          abs(_db["captain_score"] - 14.0) < 0.01)
ok("B18 DeBruyne minutes_risk == 100.0", _db["score_inputs"]["minutes_risk"] == 100.0)

# Explicit override still respected
_hx = tool_get_captain_score("Haaland", BS, {"form": 0.0, "fixture_difficulty": 5, "xgi_per_90": 0.0, "minutes_risk": 100.0})
ok("B19 explicit override respected (score < 10)", _hx["captain_score"] < 10.0)
ok("B20 explicit override → avoid tier",           _hx["tier"] == "avoid")

# not_found still works
_nf = tool_get_captain_score("xyznotaplayer999", BS)
ok("B21 not_found status",               _nf["status"] == "not_found")


# ===========================================================================
# Section C: tool_rank_captain_candidates enriched output
# ===========================================================================
print("\n--- C: tool_rank_captain_candidates enriched output ---")

# Without explicit inputs → auto-derive from bootstrap elements
_rank = tool_rank_captain_candidates([{"query": "Haaland"}, {"query": "Salah"}], BS)
ok("C1  rank status ok",                 _rank["status"] == "ok")
ok("C2  rank total == 2",                _rank["total"] == 2)

_c1 = _rank["ranked_candidates"][0]  # higher score first
_c2 = _rank["ranked_candidates"][1]

# Salah (60.58) ranks above Haaland (54.85)
ok("C3  rank1 web_name == Salah",        _c1["web_name"] == "Salah")
ok("C4  rank1 tier == 'safe'",           _c1["tier"] == "safe")
ok("C5  rank1 role_signals present",     "role_signals" in _c1)
ok("C6  rank2 web_name == Haaland",      _c2["web_name"] == "Haaland")
ok("C7  rank2 tier == 'upside'",         _c2["tier"] == "upside")

# All 4 players
_rank4 = tool_rank_captain_candidates(
    [{"query": "Haaland"}, {"query": "Salah"}, {"query": "Saka"}, {"query": "De Bruyne"}],
    BS,
)
ok("C8  rank4 total == 4",               _rank4["total"] == 4)
_tiers = {c["web_name"]: c["tier"] for c in _rank4["ranked_candidates"] if c.get("status") == "ok"}
ok("C9  Salah tier safe in rank4",       _tiers.get("Salah") == "safe")
ok("C10 Haaland tier upside in rank4",   _tiers.get("Haaland") == "upside")
ok("C11 Saka tier differential in rank4",_tiers.get("Saka") == "differential")
ok("C12 DeBruyne tier avoid in rank4",   _tiers.get("De Bruyne") == "avoid")


# ===========================================================================
# Section D: Captain score renderer
# ===========================================================================
print("\n--- D: Captain score renderer ---")

_r_h = _render_get_captain_score(_h)
ok("D1  Haaland render is str",          isinstance(_r_h, str))
ok("D2  Haaland render starts with name",_r_h.startswith("Haaland"))
ok("D3  Haaland render has 'Upside'",    "Upside" in _r_h)
ok("D4  Haaland render has score",       "54.85" in _r_h)

_r_s = _render_get_captain_score(_s)
ok("D5  Salah render has 'Safe'",        "Safe" in _r_s)
ok("D6  Salah render has score",         "60.58" in _r_s)

_r_sk = _render_get_captain_score(_sk)
ok("D7  Saka render has 'Differential'", "Differential" in _r_sk)

_r_db = _render_get_captain_score(_db)
ok("D8  DeBruyne render has 'Avoid'",    "Avoid" in _r_db)

# not_found and ambiguous paths
ok("D9  not_found path renders gracefully", "not found" in _render_get_captain_score(_nf).lower() or
                                             "No player found" in _render_get_captain_score(_nf))

# Tier vocabulary — all 5 tiers covered
ok("D10 TIER_LABEL has 'upside'",        "upside" in _TIER_LABEL)
ok("D11 TIER_LABEL has 'avoid'",         "avoid" in _TIER_LABEL)
ok("D12 TIER_SHORT has 'upside' → 'up'", _TIER_SHORT.get("upside") == "up")
ok("D13 TIER_SHORT has 'avoid'",         "avoid" in _TIER_SHORT)
ok("D14 TIER_LABEL not has 'balanced'",  "balanced" not in _TIER_LABEL)


# ===========================================================================
# Section E: Rank renderer
# ===========================================================================
print("\n--- E: Rank renderer ---")

_r_rank4 = _render_rank_captain_candidates(_rank4)
ok("E1  rank render is str",             isinstance(_r_rank4, str))
ok("E2  rank render has Salah",          "Salah" in _r_rank4)
ok("E3  rank render has Haaland",        "Haaland" in _r_rank4)
ok("E4  rank render has tier 'safe'",    "[safe]" in _r_rank4)
ok("E5  rank render has tier 'up'",      "[up]" in _r_rank4)
ok("E6  rank render has tier 'diff'",    "[diff]" in _r_rank4)
ok("E7  rank render has tier 'avoid'",   "[avoid]" in _r_rank4)
ok("E8  rank render has '1.'",           "1." in _r_rank4)

# Empty ok candidates path
_rank_empty = {"status": "ok", "ranked_candidates": [], "total": 0, "error_count": 0}
ok("E9  empty rank renders gracefully",  "No captain candidates" in _render_rank_captain_candidates(_rank_empty))


# ===========================================================================
# Section F: Tier vocabulary consistency
# ===========================================================================
print("\n--- F: Tier vocabulary consistency ---")

# Same player should get identical tier from both get_captain_score and rank tool
_r1 = tool_get_captain_score("Haaland", BS)
_r2_list = tool_rank_captain_candidates([{"query": "Haaland"}], BS)
_r2_haaland = next((c for c in _r2_list["ranked_candidates"] if c.get("web_name") == "Haaland"), {})

ok("F1  Haaland tier consistent across tools",   _r1["tier"] == _r2_haaland.get("tier"))
ok("F2  Haaland score consistent across tools",  abs(_r1["captain_score"] - _r2_haaland.get("captain_score", 0)) < 0.01)
ok("F3  Haaland role_bonus consistent",           _r1["role_signals"]["role_bonus"] == _r2_haaland.get("role_signals", {}).get("role_bonus"))

_s1 = tool_get_captain_score("Salah", BS)
_s2_list = tool_rank_captain_candidates([{"query": "Salah"}], BS)
_s2_salah = next((c for c in _s2_list["ranked_candidates"] if c.get("web_name") == "Salah"), {})

ok("F4  Salah tier consistent across tools",     _s1["tier"] == _s2_salah.get("tier"))
ok("F5  Salah score consistent across tools",    abs(_s1["captain_score"] - _s2_salah.get("captain_score", 0)) < 0.01)

# Tier consistency with comparison tool
from fpl_grounded_assistant.comparison import compare_players

_comp = compare_players("Haaland", "Salah", BS)
ok("F6  comp status ok",                         _comp["status"] == "ok")
ok("F7  Haaland tier matches comparison player_a tier",
   _r1["tier"] == _comp["player_a"]["tier"])
ok("F8  Salah tier matches comparison player_b tier",
   _s1["tier"] == _comp["player_b"]["tier"])
ok("F9  Haaland score matches comparison player_a score",
   abs(_r1["captain_score"] - _comp["player_a"]["captain_score"]) < 0.01)


# ===========================================================================
# Section G: respond() pipeline — captain answers no longer error text
# ===========================================================================
print("\n--- G: respond() pipeline ---")

# respond() returns FinalResponse; when LLM not available, final_text = response_text
# which is the deterministic renderer output — should no longer be an error message.

_fr_h = respond("should I captain Haaland", BS)
ok("G1  respond outcome ok",              _fr_h.outcome == "ok")
ok("G2  respond intent captain_score",    _fr_h.intent == "captain_score")
ok("G3  respond final_text not empty",    bool(_fr_h.final_text))
ok("G4  respond final_text not 'Error'",  not _fr_h.final_text.startswith("Error"))
ok("G5  respond final_text has Haaland",  "Haaland" in _fr_h.final_text)

_fr_s = respond("captain score for Salah", BS)
ok("G6  Salah respond outcome ok",        _fr_s.outcome == "ok")
ok("G7  Salah final_text not error",      not _fr_s.final_text.startswith("Error"))

# run_tool() path
_rt = run_tool("get_captain_score", {"query": "Haaland"}, BS)
ok("G8  run_tool tier present",           "tier" in _rt)
ok("G9  run_tool role_signals present",   "role_signals" in _rt)
ok("G10 run_tool tier == 'upside'",       _rt["tier"] == "upside")

# render() dispatches to new renderer
_rend = render("get_captain_score", _rt)
ok("G11 render captain_score not error",  not _rend.startswith("Error"))
ok("G12 render captain_score has name",   "Haaland" in _rend)

_rend_rank = render("rank_captain_candidates", _rank4)
ok("G13 render rank not error",           not _rend_rank.startswith("Error"))
ok("G14 render rank has Salah",           "Salah" in _rend_rank)


# ===========================================================================
# Section H: Regression — comparison and session-inspect unchanged
# ===========================================================================
print("\n--- H: Regression ---")

# Comparison output still has winner/margin/label/reasons
ok("H1  comparison winner present",       "winner" in _comp)
ok("H2  comparison margin_label present", "margin_label" in _comp)
ok("H3  comparison recommendation str",   isinstance(_comp.get("recommendation"), str))

_fr_comp = respond("Haaland vs Salah", BS)
ok("H4  comparison respond outcome ok",   _fr_comp.outcome == "ok")
ok("H5  comparison respond has comparison meta", _fr_comp.comparison is not None)
ok("H6  comparison meta winner is str",   isinstance(_fr_comp.comparison.winner, str))

# Session inspect unchanged
from fpl_grounded_assistant import ConversationSession
_sess = ConversationSession()
_sess_r = _sess.respond("should I captain Haaland", BS)
ok("H7  session respond outcome ok",      _sess_r.outcome == "ok")
ok("H8  session final_text not error",    not _sess_r.final_text.startswith("Error"))
ok("H9  session final_text has Haaland",  "Haaland" in _sess_r.final_text)

# Session state updated for captain turn
_sess_r2 = _sess.respond("Haaland vs Salah", BS)
ok("H10 session comparison turn ok",      _sess_r2.outcome == "ok")
ok("H11 session has last_comparison",     _sess.state.last_comparison is not None)

# Other tools still work
_fr_gw = respond("what gameweek is it", BS)
ok("H12 gameweek respond ok",             _fr_gw.outcome == "ok")

_fr_sum = respond("summary for Salah", BS)
ok("H13 summary respond ok",              _fr_sum.outcome == "ok")
ok("H14 summary not error text",          not _fr_sum.final_text.startswith("Error"))

# Unsupported still safe
_fr_unsup = respond("what should I eat for breakfast", BS)
ok("H15 unsupported outcome",             _fr_unsup.outcome == "unsupported_intent")
ok("H16 unsupported supported=False",     _fr_unsup.supported is False)


# ===========================================================================
# Results
# ===========================================================================
print()
print("=" * 60)
TOTAL = PASS + FAIL
print(f"Phase 5m results: {PASS}/{TOTAL} PASS")
print("=" * 60)

if FAIL > 0:
    sys.exit(1)
