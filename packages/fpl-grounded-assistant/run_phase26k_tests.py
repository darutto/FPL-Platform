"""
run_phase26k_tests.py
=====================
Phase 2.6k: Transfer-suggestion not_found renderer branch.

Before this slice, unresolved team queries fell through to the generic
"Error (error): ..." fallback. This slice adds a dedicated branch that
produces a friendly, transfer-specific message instead.

New renderer behavior for status="not_found"
---------------------------------------------
  Input:  {"status": "not_found", "team_query": "Spurs", "message": "..."}
  Output: "No club matching 'Spurs' was found in the current fixture data.
           Check the spelling or try a common abbreviation (...)."

All other transfer-suggestion statuses (ok, empty, missing_context) are
unchanged.

Deliverable scope
-----------------
  renderer.py  — one new branch added to _render_get_transfer_suggestion
  run_phase26k_tests.py — this file

No handler, router, metadata, schema, or corpus changes.

Regression
----------
run_validation:       80/80
run_phase26j_tests:   68/68    (run independently)
run_phase26i_tests:   87/87    (run independently)
run_phase26h_tests:   110/110  (run independently)
run_phase26e4_tests:  110/110  (run independently)
run_phase26f_tests:   67/67    (run independently)
run_phase26d4_tests:  35/35    (run independently)
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

from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.conversation_fixtures import DIFFERENTIAL_BOOTSTRAP
from fpl_grounded_assistant.final_response import respond

_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _pass.append(label)
        print("  PASS  " + label)
    else:
        _fail.append(label)
        msg = "  FAIL  " + label
        if detail:
            msg += " (" + detail + ")"
        print(msg)


# ---------------------------------------------------------------------------
# A — Renderer unit: not_found branch
# ---------------------------------------------------------------------------

print("\n=== A: not_found renderer branch ===")

_nf1 = render("get_transfer_suggestion", {
    "status":     "not_found",
    "team_query": "Spurs",
    "message":    "No team found matching 'Spurs'.",
})
_check("A1 not_found is str",            isinstance(_nf1, str))
_check("A2 not_found non-empty",         bool(_nf1))
_check("A3 not_found not generic error", not _nf1.startswith("Error ("))
_check("A4 not_found mentions Spurs",    "Spurs" in _nf1 or "spurs" in _nf1.lower())
_check("A5 not_found mentions club/team", "club" in _nf1.lower() or "team" in _nf1.lower())
_check("A6 not_found has guidance",
       "spelling" in _nf1.lower() or "abbreviation" in _nf1.lower()
       or "try" in _nf1.lower())

# Different unresolved team
_nf2 = render("get_transfer_suggestion", {
    "status":     "not_found",
    "team_query": "Athletico Madrid",
    "message":    "No team found matching 'Athletico Madrid'.",
})
_check("A7 not_found echoes query",      "Athletico Madrid" in _nf2)
_check("A8 not_found still not generic", not _nf2.startswith("Error ("))

# team_query absent — graceful fallback
_nf3 = render("get_transfer_suggestion", {
    "status":  "not_found",
    "message": "No team found.",
})
_check("A9 not_found no team_query safe", isinstance(_nf3, str) and bool(_nf3))
_check("A10 not_found no team_query not error", not _nf3.startswith("Error ("))


# ---------------------------------------------------------------------------
# B — Renderer unit: other statuses unchanged
# ---------------------------------------------------------------------------

print("\n=== B: Other statuses unchanged ===")

_ok_out = render("get_transfer_suggestion", {
    "status":         "ok",
    "position":       "MID",
    "position_label": "midfielders",
    "team_short":     None,
    "team_name":      None,
    "max_price":      None,
    "horizon":        5,
    "top_n":          1,
    "picks": [{
        "rank": 1, "web_name": "Salah", "team_short": "LIV", "position": "MID",
        "now_cost": 135, "now_cost_m": 13.5, "form": 9.5,
        "avg_fdr": 2.8, "difficulty_label": "easy",
        "composite_score": 3.39, "ownership": 64.1,
    }],
})
_check("B1 ok status renders Salah",     "Salah" in _ok_out)
_check("B2 ok not_found unchanged",      "No club matching" not in _ok_out)

_empty_out = render("get_transfer_suggestion", {
    "status":    "empty",
    "position":  "MID",
    "team_short": None,
    "team_name":  None,
    "max_price": 5.0,
    "horizon":   5,
    "top_n":     5,
    "message":   "No available midfielders under £5.0m found.",
})
_check("B3 empty renders message",       "No available midfielders" in _empty_out)
_check("B4 empty not generic error",     not _empty_out.startswith("Error ("))

_mc_out = render("get_transfer_suggestion", {
    "status":  "missing_context",
    "message": "Player data not available.",
})
_check("B5 missing_context renders",     "Player data" in _mc_out or bool(_mc_out))


# ---------------------------------------------------------------------------
# C — End-to-end: respond() for unresolved team
# ---------------------------------------------------------------------------

print("\n=== C: End-to-end not_found ===")

# Spurs not in DIFFERENTIAL_BOOTSTRAP
_fr_spurs = respond("best Spurs players to buy", DIFFERENTIAL_BOOTSTRAP)
_check("C1 intent=transfer_suggestion",  _fr_spurs.intent == "transfer_suggestion")
_check("C2 outcome=not_found",           _fr_spurs.outcome == "not_found")
_check("C3 transfer_suggestion=None",    _fr_spurs.transfer_suggestion is None)
_ft_spurs = _fr_spurs.final_text
_check("C4 final_text non-empty",        bool(_ft_spurs))
_check("C5 not generic Error()",         not _ft_spurs.startswith("Error ("))
_check("C6 mentions Spurs",              "Spurs" in _ft_spurs or "spurs" in _ft_spurs.lower())
_check("C7 transfer-specific message",
       "club" in _ft_spurs.lower() or "team" in _ft_spurs.lower()
       or "found" in _ft_spurs.lower())

# Another real PL club not in DIFFERENTIAL_BOOTSTRAP (Brighton is a known alias)
_fr_bha = respond("best Brighton players to buy", DIFFERENTIAL_BOOTSTRAP)
_check("C8 Brighton outcome=not_found",  _fr_bha.outcome == "not_found")
_ft_bha = _fr_bha.final_text
_check("C9 Brighton not Error()",        not _ft_bha.startswith("Error ("))
_check("C10 Brighton echoes query",      "Brighton" in _ft_bha or "brighton" in _ft_bha.lower())


# ---------------------------------------------------------------------------
# D — Successful routes still render correctly
# ---------------------------------------------------------------------------

print("\n=== D: Successful routes unchanged ===")

_fr_ok = respond("best Liverpool players to buy", DIFFERENTIAL_BOOTSTRAP)
_check("D1 ok intent ok",               _fr_ok.intent == "transfer_suggestion")
_check("D2 ok outcome ok",              _fr_ok.outcome == "ok")
_ft_ok = _fr_ok.final_text
_check("D3 ok renders Salah",           "Salah" in _ft_ok)
_check("D4 ok no not_found text",       "No club matching" not in _ft_ok)

_fr_pos = respond("best midfielders to buy", DIFFERENTIAL_BOOTSTRAP)
_check("D5 position-only ok",           _fr_pos.intent == "transfer_suggestion")
_ft_pos = _fr_pos.final_text
_check("D6 position-only renders",      "midfielders" in _ft_pos)


# ---------------------------------------------------------------------------
# E — Regression (validation corpus)
# ---------------------------------------------------------------------------

print("\n=== E: Regression ===")

from run_validation import run_all_scenarios

results = run_all_scenarios()
total  = len(results)
passed = sum(1 for r in results if r.get("pass"))
_check("E1 validation corpus " + str(passed) + "/" + str(total) + " PASS",
       passed == total,
       str(total - passed) + " scenario(s) failed")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("Phase 2.6k: %d/%d assertions passed." % (len(_pass), len(_pass) + len(_fail)))
if _fail:
    print("               %d assertion(s) FAILED." % len(_fail))
    for f in _fail:
        print("  - " + f)
else:
    print("               All assertions passed.")
