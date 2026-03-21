"""
run_phase5p_tests.py
====================
Phase 5p: Structured Ranked Captain Candidate Metadata

Tests that verify:
  A  RankedCaptainEntry dataclass — fields, frozen, importable
  B  FinalResponse.captain_ranking populated for rank_candidates OK turns
  C  Correct entry count and rank ordering
  D  Per-entry field values (Salah #1, Haaland #2, Saka #3)
  E  Failed / not_found candidates excluded from captain_ranking
  F  captain_ranking is None for non-ranking turns
  G  run() debug JSON includes captain_ranking for ranking turns
  H  run_session() includes captain_ranking in turn dict
  I  HTTP AskResponse and SessionAskResponse have captain_ranking field
  J  HTTP serialisation — captain_ranking list shape and values
  K  Shape identity: CLI debug == HTTP == session for captain_ranking
  L  _serial_captain_ranking matches _captain_ranking_list
  M  Regression — captain, comparison, gameweek turns unchanged

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5p_tests.py
"""
from __future__ import annotations

import json
import os
import sys

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

_passed = 0
_failed = 0


def ok(label: str, expr: bool, detail: str = "") -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        msg = f"FAIL  {label}"
        if detail:
            msg += f"\n      {detail}"
        print(msg)


# ===========================================================================
# Imports
# ===========================================================================

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.final_response import (                           # noqa: E402
    RankedCaptainEntry, CaptainScoreMeta, ComparisonMeta, FinalResponse, respond,
)
from fpl_grounded_assistant.dispatcher import (                               # noqa: E402
    INTENT_RANK_CANDIDATES, INTENT_CAPTAIN_SCORE, OUTCOME_OK,
)
from fpl_cli import run, run_session, _serial_captain_ranking                 # noqa: E402
import fpl_server                                                              # noqa: E402
from fpl_server import AskResponse, SessionAskResponse, _captain_ranking_list # noqa: E402
from fastapi.testclient import TestClient                                      # noqa: E402

BS = STANDARD_BOOTSTRAP
_CANDIDATES_3 = [{"query": "Haaland"}, {"query": "Salah"}, {"query": "Saka"}]
_CANDIDATES_4 = [{"query": "Haaland"}, {"query": "Salah"}, {"query": "Saka"}, {"query": "De Bruyne"}]


# ===========================================================================
# Section A — RankedCaptainEntry dataclass
# ===========================================================================
print("\n--- A: RankedCaptainEntry dataclass ---")

_e = RankedCaptainEntry(
    rank=1, web_name="Salah", team_short="LIV",
    captain_score=60.58, tier="safe",
    role_bonus=5.0, set_piece_notes=("penalty_taker_1",),
)
ok("A1 RankedCaptainEntry importable",     True)
ok("A2 rank field",                        _e.rank == 1)
ok("A3 web_name field",                    _e.web_name == "Salah")
ok("A4 team_short field",                  _e.team_short == "LIV")
ok("A5 captain_score field",               _e.captain_score == 60.58)
ok("A6 tier field",                        _e.tier == "safe")
ok("A7 role_bonus field",                  _e.role_bonus == 5.0)
ok("A8 set_piece_notes is tuple",          isinstance(_e.set_piece_notes, tuple))
ok("A9 set_piece_notes value",             _e.set_piece_notes == ("penalty_taker_1",))

def _check_frozen(obj):
    try:
        obj.rank = 99  # type: ignore[misc]
        return False
    except Exception:
        return True

ok("A10 frozen — assignment raises",       _check_frozen(_e))


# ===========================================================================
# Section B — FinalResponse.captain_ranking populated for OK ranking turns
# ===========================================================================
print("\n--- B: FinalResponse.captain_ranking for rank_candidates OK ---")

_r = respond("top captains this week", BS, candidates_list=_CANDIDATES_3)
ok("B1 respond() returns FinalResponse",   isinstance(_r, FinalResponse))
ok("B2 intent == rank_candidates",         _r.intent == INTENT_RANK_CANDIDATES)
ok("B3 outcome == ok",                     _r.outcome == OUTCOME_OK)
ok("B4 captain_ranking is not None",       _r.captain_ranking is not None)
ok("B5 captain_ranking is a tuple",        isinstance(_r.captain_ranking, tuple))
ok("B6 all entries are RankedCaptainEntry",
   all(isinstance(e, RankedCaptainEntry) for e in (_r.captain_ranking or ())))


# ===========================================================================
# Section C — Entry count and rank ordering
# ===========================================================================
print("\n--- C: Entry count and rank ordering ---")

ok("C1 3 entries for 3 valid candidates",  len(_r.captain_ranking or ()) == 3)
_ranks = [e.rank for e in (_r.captain_ranking or ())]
ok("C2 ranks are [1, 2, 3]",              _ranks == [1, 2, 3],         str(_ranks))
_scores = [e.captain_score for e in (_r.captain_ranking or ())]
ok("C3 scores are descending",            _scores == sorted(_scores, reverse=True), str(_scores))

_r4 = respond("top captains this week", BS, candidates_list=_CANDIDATES_4)
ok("C4 4 candidates → 4 entries",         len(_r4.captain_ranking or ()) == 4)
ok("C5 rank 1 player is Salah",           (_r4.captain_ranking or (None,))[0].web_name == "Salah")


# ===========================================================================
# Section D — Per-entry field values
# ===========================================================================
print("\n--- D: Per-entry field values ---")

_ranking = _r.captain_ranking or ()
_r1 = _ranking[0] if len(_ranking) > 0 else None   # Salah
_r2 = _ranking[1] if len(_ranking) > 1 else None   # Haaland
_r3 = _ranking[2] if len(_ranking) > 2 else None   # Saka

ok("D1  rank-1 web_name == Salah",        _r1 is not None and _r1.web_name == "Salah")
ok("D2  rank-1 team_short == LIV",        _r1 is not None and _r1.team_short == "LIV")
ok("D3  rank-1 score ≈ 60.58",            _r1 is not None and abs(_r1.captain_score - 60.58) < 0.1)
ok("D4  rank-1 tier == safe",             _r1 is not None and _r1.tier == "safe")
ok("D5  rank-1 role_bonus == 5.0",        _r1 is not None and _r1.role_bonus == 5.0)
ok("D6  rank-1 set_piece_notes has pen",  _r1 is not None and "penalty_taker_1" in _r1.set_piece_notes)

ok("D7  rank-2 web_name == Haaland",      _r2 is not None and _r2.web_name == "Haaland")
ok("D8  rank-2 team_short == MCI",        _r2 is not None and _r2.team_short == "MCI")
ok("D9  rank-2 tier == upside",           _r2 is not None and _r2.tier == "upside")

ok("D10 rank-3 web_name == Saka",         _r3 is not None and _r3.web_name == "Saka")
ok("D11 rank-3 tier == differential",     _r3 is not None and _r3.tier == "differential")
ok("D12 rank-3 set_piece_notes has fk2",  _r3 is not None and "freekick_taker_2" in _r3.set_piece_notes)


# ===========================================================================
# Section E — Failed/not-found candidates excluded
# ===========================================================================
print("\n--- E: Failed candidates excluded from captain_ranking ---")

_mixed = [{"query": "Haaland"}, {"query": "xyznotaplayer999"}, {"query": "Salah"}]
_r_mixed = respond("top captains this week", BS, candidates_list=_mixed)
ok("E1 mixed candidates → ok outcome",    _r_mixed.outcome == OUTCOME_OK)
ok("E2 only 2 ok entries",                len(_r_mixed.captain_ranking or ()) == 2,
   str(len(_r_mixed.captain_ranking or ())))
_mixed_names = [e.web_name for e in (_r_mixed.captain_ranking or ())]
ok("E3 only valid players in ranking",    "Haaland" in _mixed_names and "Salah" in _mixed_names)
ok("E4 not_found player excluded",        "xyznotaplayer999" not in _mixed_names)


# ===========================================================================
# Section F — captain_ranking is None for non-ranking turns
# ===========================================================================
print("\n--- F: captain_ranking None for non-ranking turns ---")

_r_cap = respond("should I captain Salah", BS)
ok("F1 captain_score turn — captain_ranking None", _r_cap.captain_ranking is None)
ok("F2 captain_score turn — captain not None",     _r_cap.captain is not None)

_r_cmp = respond("Haaland vs Salah", BS)
ok("F3 comparison turn — captain_ranking None",    _r_cmp.captain_ranking is None)

_r_gw = respond("what is the current gameweek", BS)
ok("F4 gameweek turn — captain_ranking None",      _r_gw.captain_ranking is None)

_r_nf = respond("top captains this week", BS, candidates_list=[{"query": "xyznotaplayer999"}])
ok("F5 all-failed ranking — outcome ok, ranking tuple",  # partial ok: total=0, error_count=1
   _r_nf.captain_ranking is not None)
ok("F6 all-failed — empty tuple",
   _r_nf.captain_ranking is not None and len(_r_nf.captain_ranking) == 0,
   str(_r_nf.captain_ranking))

_r_miss = respond("top captains this week", BS)  # no candidates_list → missing_arguments
ok("F7 missing_arguments turn — captain_ranking None", _r_miss.captain_ranking is None)


# ===========================================================================
# Section G — run() debug JSON includes captain_ranking
# ===========================================================================
print("\n--- G: run() debug JSON includes captain_ranking ---")

_g_exit, _g_out = run(
    "top captains this week", BS, debug=True,
    candidates_list=_CANDIDATES_3,
)
ok("G1 exit code 0", _g_exit == 0, str(_g_exit))

_g_body: dict = {}
try:
    _g_body = json.loads(_g_out)
    ok("G2 output parses as JSON", True)
except json.JSONDecodeError as e:
    ok("G2 output parses as JSON", False, str(e))

ok("G3 captain_ranking key present",      "captain_ranking" in _g_body, str(list(_g_body.keys())))
ok("G4 captain_ranking is list",           isinstance(_g_body.get("captain_ranking"), list))
ok("G5 3 entries",                         len(_g_body.get("captain_ranking", [])) == 3)
ok("G6 final_text present",               "final_text" in _g_body)
ok("G7 intent == rank_candidates",         _g_body.get("intent") == "rank_candidates")

_g_first = _g_body.get("captain_ranking", [{}])[0]
ok("G8 first entry has rank key",          "rank" in _g_first)
ok("G9 first entry rank == 1",             _g_first.get("rank") == 1)
ok("G10 first entry web_name == Salah",    _g_first.get("web_name") == "Salah")
ok("G11 first entry tier == safe",         _g_first.get("tier") == "safe")
ok("G12 first entry has set_piece_notes",  isinstance(_g_first.get("set_piece_notes"), list))
ok("G13 first entry exactly 7 keys",
   set(_g_first.keys()) == {"rank", "web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"},
   str(set(_g_first.keys())))

# No captain_ranking for non-ranking turn
_, _g_out_cap = run("should I captain Salah", BS, debug=True)
_g_body_cap = json.loads(_g_out_cap)
ok("G14 captain_score debug — no captain_ranking",
   "captain_ranking" not in _g_body_cap, str(list(_g_body_cap.keys())))
ok("G15 captain_score debug — captain present",
   "captain" in _g_body_cap)


# ===========================================================================
# Section H — run_session() includes captain_ranking in turn dict
# ===========================================================================
print("\n--- H: run_session() captain_ranking in turn dict ---")

_h_turns = run_session(
    ["top captains this week"],
    BS,
    candidates_list=_CANDIDATES_3,
)
ok("H1 returns list",              isinstance(_h_turns, list))
ok("H2 one turn",                  len(_h_turns) == 1)
_h_t1 = _h_turns[0] if _h_turns else {}
ok("H3 turn has captain_ranking",  "captain_ranking" in _h_t1, str(list(_h_t1.keys())))
ok("H4 captain_ranking is list",    isinstance(_h_t1.get("captain_ranking"), list))
ok("H5 3 entries",                  len(_h_t1.get("captain_ranking", [])) == 3)
ok("H6 first entry web_name",       _h_t1.get("captain_ranking", [{}])[0].get("web_name") == "Salah")

# multi-turn: only ranking turn has captain_ranking
_h_multi = run_session(
    ["should I captain Salah", "top captains this week", "what is the current gameweek"],
    BS,
    candidates_list=_CANDIDATES_3,
)
ok("H7 3 turns",                    len(_h_multi) == 3)
ok("H8 captain turn — no captain_ranking",
   "captain_ranking" not in _h_multi[0] if len(_h_multi) > 0 else True,
   str(list(_h_multi[0].keys())) if _h_multi else "")
ok("H9 ranking turn — has captain_ranking",
   "captain_ranking" in _h_multi[1] if len(_h_multi) > 1 else False)
ok("H10 gameweek turn — no captain_ranking",
   "captain_ranking" not in _h_multi[2] if len(_h_multi) > 2 else True)


# ===========================================================================
# Section I — HTTP AskResponse and SessionAskResponse have captain_ranking
# ===========================================================================
print("\n--- I: HTTP response schemas ---")

_ask_fields = AskResponse.model_fields
ok("I1 AskResponse has captain_ranking field",         "captain_ranking" in _ask_fields)
ok("I2 AskResponse captain_ranking default None",      _ask_fields["captain_ranking"].default is None)

_sess_fields = SessionAskResponse.model_fields
ok("I3 SessionAskResponse has captain_ranking field",  "captain_ranking" in _sess_fields)
ok("I4 SessionAskResponse captain_ranking default None", _sess_fields["captain_ranking"].default is None)


# ===========================================================================
# Section J — HTTP serialisation via TestClient
# ===========================================================================
print("\n--- J: HTTP serialisation ---")

fpl_server._init_bootstrap(BS)
_j_client = TestClient(fpl_server.app, raise_server_exceptions=True)

_j_resp = _j_client.post("/ask", json={
    "question": "top captains this week",
    "candidates_list": [{"query": "Haaland"}, {"query": "Salah"}, {"query": "Saka"}],
})
ok("J1 HTTP 200",                           _j_resp.status_code == 200, str(_j_resp.status_code))
_j_body = _j_resp.json()
ok("J2 outcome == ok",                      _j_body.get("outcome") == "ok")
ok("J3 captain_ranking key present",        "captain_ranking" in _j_body, str(list(_j_body.keys())))
ok("J4 captain_ranking is list",            isinstance(_j_body.get("captain_ranking"), list))
ok("J5 3 entries",                          len(_j_body.get("captain_ranking", [])) == 3)
_j_first = _j_body.get("captain_ranking", [{}])[0]
ok("J6 first entry rank == 1",             _j_first.get("rank") == 1)
ok("J7 first entry web_name == Salah",     _j_first.get("web_name") == "Salah")
ok("J8 first entry tier == safe",          _j_first.get("tier") == "safe")
ok("J9 first entry role_bonus == 5.0",     _j_first.get("role_bonus") == 5.0)
ok("J10 first entry set_piece_notes list", isinstance(_j_first.get("set_piece_notes"), list))
ok("J11 first entry exactly 7 keys",
   set(_j_first.keys()) == {"rank", "web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"},
   str(set(_j_first.keys())))

# Non-ranking turn has captain_ranking as null
_j_cap_resp = _j_client.post("/ask", json={"question": "should I captain Salah"})
_j_cap_body = _j_cap_resp.json()
ok("J12 captain_score HTTP — captain_ranking is None",
   _j_cap_body.get("captain_ranking") is None)
ok("J13 captain_score HTTP — captain not None",
   _j_cap_body.get("captain") is not None)


# ===========================================================================
# Section K — Shape identity: CLI debug == HTTP == session
# ===========================================================================
print("\n--- K: Shape identity across CLI, HTTP, session ---")

_k_cli_list  = _g_body.get("captain_ranking", [])    # from Section G
_k_http_list = _j_body.get("captain_ranking", [])    # from Section J
_k_sess_list = _h_t1.get("captain_ranking", [])      # from Section H

ok("K1 CLI and HTTP list lengths equal",   len(_k_cli_list) == len(_k_http_list),
   f"CLI: {len(_k_cli_list)}, HTTP: {len(_k_http_list)}")
ok("K2 CLI and session list lengths equal", len(_k_cli_list) == len(_k_sess_list),
   f"CLI: {len(_k_cli_list)}, sess: {len(_k_sess_list)}")
ok("K3 CLI first entry == HTTP first entry",
   _k_cli_list[0] == _k_http_list[0] if _k_cli_list and _k_http_list else False,
   f"CLI: {_k_cli_list[0] if _k_cli_list else None}\nHTTP: {_k_http_list[0] if _k_http_list else None}")
ok("K4 CLI first entry == session first entry",
   _k_cli_list[0] == _k_sess_list[0] if _k_cli_list and _k_sess_list else False,
   f"CLI: {_k_cli_list[0] if _k_cli_list else None}\nSESS: {_k_sess_list[0] if _k_sess_list else None}")


# ===========================================================================
# Section L — _serial_captain_ranking matches _captain_ranking_list
# ===========================================================================
print("\n--- L: _serial_captain_ranking matches _captain_ranking_list ---")

if _r.captain_ranking is not None:
    _l_cli  = _serial_captain_ranking(_r.captain_ranking)
    _l_http = _captain_ranking_list(_r.captain_ranking)
    ok("L1 CLI and HTTP helpers produce equal output", _l_cli == _l_http,
       f"CLI: {_l_cli}\nHTTP: {_l_http}")
    ok("L2 both return lists",   isinstance(_l_cli, list) and isinstance(_l_http, list))
    ok("L3 3 entries each",      len(_l_cli) == 3 and len(_l_http) == 3)
    ok("L4 each entry has 7 keys",
       all(set(e.keys()) == {"rank", "web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"}
           for e in _l_cli))
else:
    ok("L1 CLI and HTTP helpers produce equal output", False, "captain_ranking was None")
    ok("L2 both return lists", False)
    ok("L3 3 entries each", False)
    ok("L4 each entry has 7 keys", False)


# ===========================================================================
# Section M — Regression
# ===========================================================================
print("\n--- M: Regression ---")

# captain_score turn unchanged
_m_cap = respond("should I captain Salah", BS)
ok("M1  captain_score — captain not None",     _m_cap.captain is not None)
ok("M2  captain_score — captain_ranking None", _m_cap.captain_ranking is None)
ok("M3  captain_score — comparison None",      _m_cap.comparison is None)
ok("M4  captain_score — captain.tier == safe", _m_cap.captain is not None and _m_cap.captain.tier == "safe")

# comparison turn unchanged
_m_cmp = respond("Haaland vs Salah", BS)
ok("M5  comparison — comparison not None",     _m_cmp.comparison is not None)
ok("M6  comparison — captain None",            _m_cmp.captain is None)
ok("M7  comparison — captain_ranking None",    _m_cmp.captain_ranking is None)
ok("M8  comparison is ComparisonMeta",         isinstance(_m_cmp.comparison, ComparisonMeta))

# Phase 5n tests still hold (81/81)
_m_haaland = respond("should I captain Haaland", BS)
ok("M9  Haaland CaptainScoreMeta intact",      _m_haaland.captain is not None)
ok("M10 Haaland captain_ranking None",         _m_haaland.captain_ranking is None)

# HTTP captain_ranking absent from previous response models (null, not missing key)
ok("M11 AskResponse captain_ranking default is None",
   AskResponse.model_fields["captain_ranking"].default is None)

# ranking turn has no captain field (not a single-player turn)
ok("M12 ranking turn — captain is None",       _r.captain is None)
ok("M13 ranking turn — captain_ranking not None", _r.captain_ranking is not None)


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*60}")
print(f"Phase 5p results: {_passed}/{_passed+_failed} PASS")
print(f"{'='*60}")
if _failed:
    sys.exit(1)
