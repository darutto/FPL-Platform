"""
Phase 5n tests — Structured Captain Score Metadata.

Tests across sections:
  A  CaptainScoreMeta dataclass — fields, types, frozen
  B  FinalResponse.captain populated for captain_score OK turns
  C  FinalResponse.captain None for non-captain-score turns
  D  All four test players — correct web_name, team_short, score, tier,
     role_bonus, set_piece_notes values
  E  CLI _serial_captain() — correct keys and values
  F  CLI run() debug JSON includes captain key
  G  HTTP AskResponse and SessionAskResponse schemas include captain field
  H  HTTP serialisation — captain dict has correct keys and values
  I  Regression — FinalResponse.comparison unchanged for comparison turns

Run with:
    cd packages/fpl-grounded-assistant
    python run_phase5n_tests.py
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
from fpl_grounded_assistant.final_response import (
    CaptainScoreMeta, ComparisonMeta, FinalResponse, respond,
)
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE, INTENT_RANK_CANDIDATES, INTENT_PLAYER_SUMMARY,
    INTENT_COMPARE_PLAYERS, OUTCOME_OK,
)
from fpl_cli import run, _serial_captain
from fpl_server import AskResponse, SessionAskResponse, _captain_meta_dict

BS = STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# A: CaptainScoreMeta dataclass
# ---------------------------------------------------------------------------
print("\n--- A: CaptainScoreMeta dataclass ---")

_m = CaptainScoreMeta(
    web_name="Salah", team_short="LIV",
    captain_score=60.58, tier="safe",
    role_bonus=5.0, set_piece_notes=("penalty_taker_1",),
)
ok("A1 CaptainScoreMeta is importable",    True)  # import above succeeded
ok("A2 web_name field",                    _m.web_name == "Salah")
ok("A3 team_short field",                  _m.team_short == "LIV")
ok("A4 captain_score field",               _m.captain_score == 60.58)
ok("A5 tier field",                        _m.tier == "safe")
ok("A6 role_bonus field",                  _m.role_bonus == 5.0)
ok("A7 set_piece_notes is tuple",          isinstance(_m.set_piece_notes, tuple))
ok("A8 set_piece_notes value",             _m.set_piece_notes == ("penalty_taker_1",))
def _check_frozen(obj):
    try:
        obj.tier = "avoid"  # type: ignore[misc]
        return False
    except Exception:
        return True

ok("A9 frozen — assignment raises",        _check_frozen(_m))


# ---------------------------------------------------------------------------
# B: FinalResponse.captain populated for captain_score OK turns
# ---------------------------------------------------------------------------
print("\n--- B: FinalResponse.captain for captain_score OK ---")

_r_haaland = respond("Should I captain Haaland?", BS)
ok("B1 respond() returns FinalResponse",   isinstance(_r_haaland, FinalResponse))
ok("B2 intent == captain_score",           _r_haaland.intent == INTENT_CAPTAIN_SCORE)
ok("B3 outcome == ok",                     _r_haaland.outcome == OUTCOME_OK)
ok("B4 captain is not None",               _r_haaland.captain is not None)
ok("B5 captain is CaptainScoreMeta",       isinstance(_r_haaland.captain, CaptainScoreMeta))

_c_h = _r_haaland.captain
ok("B6 Haaland web_name",                  _c_h.web_name == "Haaland")
ok("B7 Haaland team_short == MCI",         _c_h.team_short == "MCI")
ok("B8 Haaland captain_score > 0",         _c_h.captain_score > 0)
ok("B9 Haaland tier non-empty",            bool(_c_h.tier))
ok("B10 Haaland role_bonus >= 0",          _c_h.role_bonus >= 0.0)
ok("B11 Haaland set_piece_notes is tuple", isinstance(_c_h.set_piece_notes, tuple))


# ---------------------------------------------------------------------------
# C: FinalResponse.captain is None for non-captain-score turns
# ---------------------------------------------------------------------------
print("\n--- C: FinalResponse.captain None for other intents ---")

_r_gw = respond("What gameweek is it?", BS)
ok("C1 gameweek — captain is None",        _r_gw.captain is None)

_r_sum = respond("Give me a summary for Salah", BS)
ok("C2 player summary — captain is None",  _r_sum.captain is None)

_r_rank = respond("Top captains this week: Haaland, Salah", BS)
ok("C3 rank candidates — captain is None", _r_rank.captain is None)

_r_cmp = respond("Haaland vs Salah", BS)
ok("C4 comparison — captain is None",      _r_cmp.captain is None)
ok("C5 comparison — comparison not None",  _r_cmp.comparison is not None)


# ---------------------------------------------------------------------------
# D: All four test players — verify field values
# ---------------------------------------------------------------------------
print("\n--- D: All four test players ---")

_r_salah = respond("Should I captain Salah?", BS)
_c_s = _r_salah.captain
ok("D1 Salah captain is CaptainScoreMeta", isinstance(_c_s, CaptainScoreMeta))
ok("D2 Salah web_name",                    _c_s.web_name == "Salah")
ok("D3 Salah team_short == LIV",           _c_s.team_short == "LIV")
ok("D4 Salah score ≈ 60.58",               abs(_c_s.captain_score - 60.58) < 0.1)
ok("D5 Salah tier == safe",                _c_s.tier == "safe")
ok("D6 Salah role_bonus > 0",              _c_s.role_bonus > 0)          # penalty taker
ok("D7 Salah set_piece_notes non-empty",   len(_c_s.set_piece_notes) > 0)

_r_saka = respond("Captain score for Saka", BS)
_c_sk = _r_saka.captain
ok("D8 Saka captain is CaptainScoreMeta",  isinstance(_c_sk, CaptainScoreMeta))
ok("D9 Saka tier == differential",         _c_sk.tier == "differential")
ok("D10 Saka score ≈ 36.35",              abs(_c_sk.captain_score - 36.35) < 0.5)

_r_db = respond("Should I captain De Bruyne?", BS)
_c_db = _r_db.captain
ok("D11 De Bruyne captain is CaptainScoreMeta", isinstance(_c_db, CaptainScoreMeta))
ok("D12 De Bruyne tier == avoid",          _c_db.tier == "avoid")
ok("D13 De Bruyne score ≈ 14.0",          abs(_c_db.captain_score - 14.0) < 0.5)

_r_h2 = respond("Should I captain Haaland?", BS)
_c_h2 = _r_h2.captain
ok("D14 Haaland tier == upside",           _c_h2.tier == "upside")
ok("D15 Haaland score ≈ 54.85",           abs(_c_h2.captain_score - 54.85) < 0.5)


# ---------------------------------------------------------------------------
# E: CLI _serial_captain() helper
# ---------------------------------------------------------------------------
print("\n--- E: CLI _serial_captain() ---")

_ser = _serial_captain(_c_s)
ok("E1 returns dict",                      isinstance(_ser, dict))
ok("E2 has web_name key",                  "web_name" in _ser)
ok("E3 has team_short key",               "team_short" in _ser)
ok("E4 has captain_score key",             "captain_score" in _ser)
ok("E5 has tier key",                      "tier" in _ser)
ok("E6 has role_bonus key",               "role_bonus" in _ser)
ok("E7 has set_piece_notes key",           "set_piece_notes" in _ser)
ok("E8 set_piece_notes is list",           isinstance(_ser["set_piece_notes"], list))
ok("E9 web_name correct",                  _ser["web_name"] == "Salah")
ok("E10 tier correct",                     _ser["tier"] == "safe")
ok("E11 no extra keys",                    set(_ser.keys()) == {
    "web_name", "team_short", "captain_score", "tier", "role_bonus", "set_piece_notes"
})


# ---------------------------------------------------------------------------
# F: CLI run() debug JSON includes captain key
# ---------------------------------------------------------------------------
print("\n--- F: CLI run() debug JSON ---")

import json as _json

_exit_code, _out = run("Should I captain Salah?", BS, debug=True)
_payload = _json.loads(_out)
ok("F1 exit code 0",                       _exit_code == 0)
ok("F2 captain key present",               "captain" in _payload)
ok("F3 captain.web_name == Salah",         _payload["captain"]["web_name"] == "Salah")
ok("F4 captain.tier == safe",              _payload["captain"]["tier"] == "safe")
ok("F5 captain.set_piece_notes is list",   isinstance(_payload["captain"]["set_piece_notes"], list))

_exit_gw, _out_gw = run("What gameweek is it?", BS, debug=True)
_payload_gw = _json.loads(_out_gw)
ok("F6 gameweek debug — no captain key",   "captain" not in _payload_gw)

_exit_cmp, _out_cmp = run("Haaland vs Salah", BS, debug=True)
_payload_cmp = _json.loads(_out_cmp)
ok("F7 comparison debug — no captain key", "captain" not in _payload_cmp)
ok("F8 comparison debug — comparison key present", "comparison" in _payload_cmp)


# ---------------------------------------------------------------------------
# G: HTTP AskResponse and SessionAskResponse have captain field
# ---------------------------------------------------------------------------
print("\n--- G: HTTP response schemas ---")

_ask_fields = AskResponse.model_fields
ok("G1 AskResponse has captain field",          "captain" in _ask_fields)
ok("G2 AskResponse captain default None",       _ask_fields["captain"].default is None)

_sess_fields = SessionAskResponse.model_fields
ok("G3 SessionAskResponse has captain field",   "captain" in _sess_fields)
ok("G4 SessionAskResponse captain default None", _sess_fields["captain"].default is None)


# ---------------------------------------------------------------------------
# H: HTTP serialisation — _captain_meta_dict
# ---------------------------------------------------------------------------
print("\n--- H: HTTP _captain_meta_dict serialisation ---")

_http_dict = _captain_meta_dict(_c_s)
ok("H1 returns dict",                      isinstance(_http_dict, dict))
ok("H2 web_name key",                      _http_dict.get("web_name") == "Salah")
ok("H3 team_short key",                    _http_dict.get("team_short") == "LIV")
ok("H4 captain_score key",                 "captain_score" in _http_dict)
ok("H5 tier key",                          _http_dict.get("tier") == "safe")
ok("H6 role_bonus key",                    "role_bonus" in _http_dict)
ok("H7 set_piece_notes is list",           isinstance(_http_dict.get("set_piece_notes"), list))
ok("H8 matches _serial_captain output",    _http_dict == _ser)


# ---------------------------------------------------------------------------
# I: Regression — comparison and other fields unchanged
# ---------------------------------------------------------------------------
print("\n--- I: Regression ---")

# captain_score turn does not pollute comparison
ok("I1 captain turn — comparison is None",      _r_salah.comparison is None)

# comparison turn still populates comparison, not captain
ok("I2 comparison turn — comparison not None",  _r_cmp.comparison is not None)
ok("I3 comparison turn — captain is None",      _r_cmp.captain is None)
ok("I4 comparison ComparisonMeta intact",       isinstance(_r_cmp.comparison, ComparisonMeta))

# comparison serial unchanged
_cmp_serial = _json.loads(_out_cmp)
ok("I5 comparison serial has winner",           "winner" in _cmp_serial["comparison"])
ok("I6 comparison serial has margin",           "margin" in _cmp_serial["comparison"])
ok("I7 comparison serial has player_a",         "player_a" in _cmp_serial["comparison"])
ok("I8 comparison serial has player_b",         "player_b" in _cmp_serial["comparison"])

# FinalResponse.captain field doesn't exist on comparison response
ok("I9 FinalResponse has captain attr",         hasattr(_r_cmp, "captain"))
ok("I10 rank candidates — captain is None",     _r_rank.captain is None)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print(f"Phase 5n results: {PASS}/{PASS+FAIL} PASS")
print(f"{'='*60}")
if FAIL:
    sys.exit(1)
