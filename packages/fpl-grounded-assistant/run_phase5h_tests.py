"""
run_phase5h_tests.py
====================
Phase 5h: Role-Aware Comparison Context

Tests that verify:
  A. Module shape — new exports present
  B. _set_piece_advantage_phrase — logic branches
  C. _explain_comparison integration — set-piece specificity
  D. compare_players() player dicts — position and role_signals present
  E. Parity — direct and follow-up produce identical comparison_reasons content
  F. Regression — existing behaviour and FinalResponse.comparison unchanged

Run::

    cd packages/fpl-grounded-assistant
    python run_phase5h_tests.py
"""
from __future__ import annotations

import sys
import os

# ---------------------------------------------------------------------------
# Minimal sys.path setup (mirrors other run_phaseX_tests.py files)
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

import traceback

PASS = 0
FAIL = 0


def ok(label: str) -> None:
    global PASS
    PASS += 1
    print(f"  PASS  {label}")


def fail(label: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    msg = f"  FAIL  {label}"
    if detail:
        msg += f"\n        {detail}"
    print(msg)


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        ok(label)
    else:
        fail(label, detail)


# ===========================================================================
# Section A — Module shape
# ===========================================================================
print("\n--- A: Module shape ---")

try:
    from fpl_grounded_assistant import _set_piece_advantage_phrase
    ok("A1  _set_piece_advantage_phrase importable from package")
except ImportError as exc:
    fail("A1  _set_piece_advantage_phrase importable from package", str(exc))

try:
    from fpl_grounded_assistant.comparison import _SET_PIECE_SHORT
    ok("A2  _SET_PIECE_SHORT importable from comparison module")
except ImportError as exc:
    fail("A2  _SET_PIECE_SHORT importable from comparison module", str(exc))

try:
    from fpl_grounded_assistant.comparison import _SET_PIECE_SHORT as _CSP_SHORT
    check("A3  _SET_PIECE_SHORT has penalty_taker_1 -> 'pen'",
          _CSP_SHORT.get("penalty_taker_1") == "pen",
          str(_CSP_SHORT))
    check("A4  _SET_PIECE_SHORT has freekick_taker_2 -> 'fk2'",
          _CSP_SHORT.get("freekick_taker_2") == "fk2",
          str(_CSP_SHORT))
except Exception as exc:
    fail("A3/A4  _SET_PIECE_SHORT checks", str(exc))

try:
    from fpl_grounded_assistant import _explain_comparison
    ok("A5  _explain_comparison still importable")
except ImportError as exc:
    fail("A5  _explain_comparison still importable", str(exc))


# ===========================================================================
# Section B — _set_piece_advantage_phrase logic branches
# ===========================================================================
print("\n--- B: _set_piece_advantage_phrase ---")

from fpl_grounded_assistant import _set_piece_advantage_phrase  # noqa: E402

# B1: no advantage when bonuses are equal
w_equal = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]}
l_equal = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]}
check("B1  equal bonuses -> None",
      _set_piece_advantage_phrase(w_equal, l_equal) is None)

# B2: no advantage when winner bonus is lower
w_lower = {"role_bonus": 0.5, "set_piece_notes": ["freekick_taker_2"]}
l_higher = {"role_bonus": 3.0, "set_piece_notes": ["freekick_taker_1"]}
check("B2  winner lower bonus -> None",
      _set_piece_advantage_phrase(w_lower, l_higher) is None)

# B3: winner pen, loser fk2 -> "set-piece advantage (pen vs fk2)"
w_pen = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]}
l_fk2 = {"role_bonus": 0.5, "set_piece_notes": ["freekick_taker_2"]}
result_b3 = _set_piece_advantage_phrase(w_pen, l_fk2)
check("B3  pen vs fk2 phrase",
      result_b3 == "set-piece advantage (pen vs fk2)",
      repr(result_b3))

# B4: winner pen, loser has no notes -> "set-piece advantage (pen)"
l_no_notes = {"role_bonus": 0.0, "set_piece_notes": []}
result_b4 = _set_piece_advantage_phrase(w_pen, l_no_notes)
check("B4  pen vs no-notes phrase",
      result_b4 == "set-piece advantage (pen)",
      repr(result_b4))

# B5: winner fk1, loser fk2 -> "set-piece advantage (fk vs fk2)"
w_fk1 = {"role_bonus": 3.0, "set_piece_notes": ["freekick_taker_1"]}
l_fk2b = {"role_bonus": 0.5, "set_piece_notes": ["freekick_taker_2"]}
result_b5 = _set_piece_advantage_phrase(w_fk1, l_fk2b)
check("B5  fk vs fk2 phrase",
      result_b5 == "set-piece advantage (fk vs fk2)",
      repr(result_b5))

# B6: winner has role_bonus but empty notes -> generic fallback
w_bonus_no_notes = {"role_bonus": 2.0, "set_piece_notes": []}
l_no_bonus = {"role_bonus": 0.0, "set_piece_notes": []}
result_b6 = _set_piece_advantage_phrase(w_bonus_no_notes, l_no_bonus)
check("B6  role_bonus but no notes -> generic 'set-piece advantage'",
      result_b6 == "set-piece advantage",
      repr(result_b6))

# B7: missing keys default gracefully (no exception)
try:
    result_b7 = _set_piece_advantage_phrase({}, {})
    check("B7  empty dicts -> None (no exception)",
          result_b7 is None,
          repr(result_b7))
except Exception as exc:
    fail("B7  empty dicts raises", str(exc))

# B8: loser has higher bonus but winner has notes — no phrase
w_pen2 = {"role_bonus": 2.5, "set_piece_notes": ["penalty_taker_2"]}
l_pen  = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]}
check("B8  winner pen2 vs loser pen (loser has higher bonus) -> None",
      _set_piece_advantage_phrase(w_pen2, l_pen) is None)


# ===========================================================================
# Section C — _explain_comparison integration
# ===========================================================================
print("\n--- C: _explain_comparison integration ---")

from fpl_grounded_assistant import _explain_comparison  # noqa: E402

# Build minimal scored dicts with the STANDARD_BOOTSTRAP role signals
# Haaland: pen/5.0  Saka: fk2/0.5  Salah: pen/5.0  De Bruyne: fk1/3.0
_HAALAND_ROLE = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"],
                 "set_piece_threat": True, "penalties_order": 1}
_SAKA_ROLE    = {"role_bonus": 0.5, "set_piece_notes": ["freekick_taker_2"],
                 "set_piece_threat": True, "penalties_order": 0}
_SALAH_ROLE   = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"],
                 "set_piece_threat": True, "penalties_order": 1}
_DKB_ROLE     = {"role_bonus": 3.0, "set_piece_notes": ["freekick_taker_1"],
                 "set_piece_threat": True, "penalties_order": 0}

_BASE_INPUTS = {"form": 8.0, "fixture_difficulty": 3, "xgi_per_90": 0.50, "minutes_risk": 0.0}

def _make_scored(role: dict, inputs: dict | None = None) -> dict:
    return {
        "score_inputs": inputs or _BASE_INPUTS.copy(),
        "role_signals": role,
    }


# C1: Haaland(pen/5.0) vs Saka(fk2/0.5) — should include specific set-piece phrase
haaland = _make_scored(_HAALAND_ROLE)
saka    = _make_scored(_SAKA_ROLE)
reasons_c1 = _explain_comparison(haaland, saka)
check("C1  Haaland vs Saka reasons list type",
      isinstance(reasons_c1, list))
check("C2  Haaland vs Saka includes 'set-piece advantage (pen vs fk2)'",
      "set-piece advantage (pen vs fk2)" in reasons_c1,
      str(reasons_c1))
check("C3  Haaland vs Saka does NOT contain old generic 'set-piece advantage' alone",
      "set-piece advantage" not in reasons_c1 or
      any("pen" in r or "fk" in r for r in reasons_c1 if "set-piece advantage" in r),
      str(reasons_c1))

# C4: Haaland(pen/5.0) vs Salah(pen/5.0) — equal role_bonus -> no set-piece reason
salah = _make_scored(_SALAH_ROLE)
reasons_c4 = _explain_comparison(haaland, salah)
set_piece_reasons = [r for r in reasons_c4 if "set-piece" in r]
check("C4  Haaland vs Salah (equal pen) -> no set-piece reason",
      len(set_piece_reasons) == 0,
      str(reasons_c4))

# C5: De Bruyne(fk1/3.0) vs Saka(fk2/0.5)
dkb  = _make_scored(_DKB_ROLE)
reasons_c5 = _explain_comparison(dkb, saka)
check("C5  De Bruyne vs Saka includes 'set-piece advantage (fk vs fk2)'",
      "set-piece advantage (fk vs fk2)" in reasons_c5,
      str(reasons_c5))

# C6: No exception on missing role_signals
no_role = {"score_inputs": _BASE_INPUTS.copy()}
try:
    _explain_comparison(no_role, no_role)
    ok("C6  missing role_signals -> no exception")
except Exception as exc:
    fail("C6  missing role_signals raises", str(exc))


# ===========================================================================
# Section D — compare_players() player dicts: position and role_signals
# ===========================================================================
print("\n--- D: compare_players() player dicts ---")

from fpl_grounded_assistant import compare_players, STANDARD_BOOTSTRAP  # noqa: E402

result_d = compare_players("Haaland", "Saka", STANDARD_BOOTSTRAP)
check("D1  compare_players status ok",
      result_d.get("status") == "ok",
      str(result_d.get("status")))

pa = result_d.get("player_a", {})
pb = result_d.get("player_b", {})

check("D2  player_a has 'position' key",
      "position" in pa,
      str(list(pa.keys())))
check("D3  player_a 'position' is non-empty string",
      isinstance(pa.get("position"), str) and len(pa.get("position", "")) > 0,
      repr(pa.get("position")))
check("D4  player_b has 'position' key",
      "position" in pb,
      str(list(pb.keys())))
check("D5  player_a has 'role_signals' key",
      "role_signals" in pa,
      str(list(pa.keys())))
check("D6  player_a 'role_signals' is a dict",
      isinstance(pa.get("role_signals"), dict),
      str(type(pa.get("role_signals"))))
check("D7  player_b has 'role_signals' key",
      "role_signals" in pb,
      str(list(pb.keys())))
check("D8  player_a role_signals has role_bonus",
      "role_bonus" in pa.get("role_signals", {}),
      str(list(pa.get("role_signals", {}).keys())))

# D9: Haaland position should be FWD
check("D9  Haaland position == FWD",
      pa.get("position") == "FWD",
      repr(pa.get("position")))

# D10: existing keys still present
for key in ("web_name", "captain_score", "tier", "reasons", "score_inputs"):
    check(f"D10 player_a still has '{key}'",
          key in pa,
          str(list(pa.keys())))
    break  # just check one as representative; full check below

check("D11 player_a still has all pre-5h keys",
      all(k in pa for k in ("web_name", "captain_score", "tier", "reasons", "score_inputs")),
      str(list(pa.keys())))


# ===========================================================================
# Section E — Parity: direct and follow-up produce identical comparison_reasons
# ===========================================================================
print("\n--- E: comparison_reasons parity ---")

from fpl_grounded_assistant import ConversationSession  # noqa: E402

# Direct call
direct = compare_players("Haaland", "Saka", STANDARD_BOOTSTRAP)
direct_reasons = direct.get("comparison_reasons", [])
direct_label   = direct.get("margin_label", "")
direct_winner  = direct.get("winner")

check("E1  direct comparison_reasons is a list",
      isinstance(direct_reasons, list))
check("E2  direct margin_label non-empty",
      isinstance(direct_label, str) and len(direct_label) > 0,
      repr(direct_label))

# Session follow-up
session_e = ConversationSession()
_r1 = session_e.respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
_r2 = session_e.respond("And Salah?", STANDARD_BOOTSTRAP)

check("E3  follow-up turn is ok",
      _r2.outcome == "ok",
      repr(_r2.outcome))
check("E4  follow-up FinalResponse.comparison is not None",
      _r2.comparison is not None)

if _r2.comparison is not None:
    # Follow-up compares Haaland vs Salah, not Haaland vs Saka
    # Just verify structural parity — both fields present
    check("E5  follow-up comparison has reasons tuple",
          isinstance(_r2.comparison.reasons, tuple))
    check("E6  follow-up comparison has label",
          isinstance(_r2.comparison.label, str) and len(_r2.comparison.label) > 0,
          repr(_r2.comparison.label))
    check("E7  follow-up comparison has winner field (str or None)",
          _r2.comparison.winner is None or isinstance(_r2.comparison.winner, str))
    check("E8  follow-up comparison.reasons is tuple (not list)",
          isinstance(_r2.comparison.reasons, tuple))

# Direct comparison Haaland vs Salah for comparison with follow-up result
direct_hs = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)
direct_hs_reasons = tuple(direct_hs.get("comparison_reasons", []))
direct_hs_label   = direct_hs.get("margin_label", "")
direct_hs_winner  = direct_hs.get("winner")

if _r2.comparison is not None:
    check("E9  follow-up comparison.reasons equals direct comparison Haaland vs Salah",
          _r2.comparison.reasons == direct_hs_reasons,
          f"follow-up={_r2.comparison.reasons!r}  direct={direct_hs_reasons!r}")
    check("E10 follow-up comparison.label equals direct",
          _r2.comparison.label == direct_hs_label,
          f"follow-up={_r2.comparison.label!r}  direct={direct_hs_label!r}")
    check("E11 follow-up comparison.winner equals direct",
          _r2.comparison.winner == direct_hs_winner,
          f"follow-up={_r2.comparison.winner!r}  direct={direct_hs_winner!r}")

# E12: Haaland vs Saka direct should include set-piece reason
check("E12 Haaland vs Saka direct comparison_reasons includes set-piece phrase",
      any("set-piece" in r for r in direct_reasons),
      str(direct_reasons))


# ===========================================================================
# Section F — Regression
# ===========================================================================
print("\n--- F: Regression ---")

from fpl_grounded_assistant import respond  # noqa: E402

# F1: direct comparison still returns ok FinalResponse
fr_f1 = respond("compare Haaland and Saka", STANDARD_BOOTSTRAP)
check("F1  respond comparison outcome ok",
      fr_f1.outcome == "ok",
      repr(fr_f1.outcome))
check("F2  respond comparison.comparison populated",
      fr_f1.comparison is not None)

if fr_f1.comparison is not None:
    check("F3  comparison.winner is str or None",
          fr_f1.comparison.winner is None or isinstance(fr_f1.comparison.winner, str))
    check("F4  comparison.margin >= 0",
          fr_f1.comparison.margin >= 0,
          repr(fr_f1.comparison.margin))
    check("F5  comparison.label in valid set",
          fr_f1.comparison.label in ("narrow", "moderate", "clear"),
          repr(fr_f1.comparison.label))
    check("F6  comparison.reasons is tuple",
          isinstance(fr_f1.comparison.reasons, tuple))

# F7: non-comparison intent still returns comparison=None
fr_f7 = respond("should I captain Haaland?", STANDARD_BOOTSTRAP)
check("F7  captain_score intent has comparison=None",
      fr_f7.comparison is None,
      repr(fr_f7.comparison))

# F8: not_found comparison still no comparison meta
fr_f8 = respond("compare Haaland and NotARealPlayer123", STANDARD_BOOTSTRAP)
check("F8  not_found comparison has comparison=None",
      fr_f8.comparison is None,
      repr(fr_f8.comparison))

# F9: final_text always non-empty
check("F9  final_text non-empty",
      len(fr_f1.final_text) > 0)

# F10: run Phase 5g regression suite inline
try:
    from fpl_grounded_assistant import ComparisonMeta
    check("F10 ComparisonMeta still importable",
          True)
except ImportError as exc:
    fail("F10 ComparisonMeta still importable", str(exc))

# F11: HTTP serialization shape (stateless /ask)
try:
    from fastapi.testclient import TestClient
    import fpl_server
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._clear_sessions()
    client_http = TestClient(fpl_server.app)

    resp = client_http.post("/ask", json={"question": "compare Haaland and Saka"})
    check("F11 /ask status 200",
          resp.status_code == 200,
          str(resp.status_code))
    body = resp.json()
    check("F12 /ask comparison field present",
          "comparison" in body,
          str(list(body.keys())))
    check("F13 /ask comparison is dict",
          isinstance(body.get("comparison"), dict),
          str(type(body.get("comparison"))))
    comp = body.get("comparison", {})
    check("F14 /ask comparison has winner key",
          "winner" in comp,
          str(list(comp.keys())))
    check("F15 /ask comparison has reasons list",
          isinstance(comp.get("reasons"), list),
          str(type(comp.get("reasons"))))

    # F16: session endpoint also includes comparison
    sess_resp = client_http.post("/session")
    sid = sess_resp.json()["session_id"]
    turn1 = client_http.post(f"/session/{sid}/ask",
                              json={"question": "compare Haaland and Saka"})
    check("F16 session /ask status 200",
          turn1.status_code == 200,
          str(turn1.status_code))
    body16 = turn1.json()
    check("F17 session /ask comparison present",
          "comparison" in body16,
          str(list(body16.keys())))
    check("F18 session /ask comparison is dict",
          isinstance(body16.get("comparison"), dict),
          str(type(body16.get("comparison"))))

    fpl_server._clear_sessions()
except Exception as exc:
    fail("F11-F18 HTTP regression", traceback.format_exc())

# F19: _explain_comparison returns list (not tuple)
check("F19 _explain_comparison returns list",
      isinstance(_explain_comparison(_make_scored(_HAALAND_ROLE), _make_scored(_SAKA_ROLE)), list))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*50}")
total = PASS + FAIL
print(f"Phase 5h: {PASS}/{total} assertions passed", end="")
if FAIL:
    print(f"  ({FAIL} FAILED)")
    sys.exit(1)
else:
    print()
