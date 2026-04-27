# -*- coding: utf-8 -*-
"""
run_blank_gw_differential_tests.py
=====================================
Blank-GW differential filter: get_differential_picks must not surface
players whose team has no current-GW fixture.

Sections
--------
A  _has_current_gw_fixture helper — unit-level correctness
B  Blank-GW exclusion — blank player excluded; active player retained
C  No-data fallback — filter skipped when team_fixtures is None
D  All-blank fallback — status="empty" when filtering leaves no candidates
E  Normal differential still ranks correctly after filter introduced
F  CLI/HTTP/session parity — respond() paths produce consistent results
G  Regression: 44/44 V1 validation corpus still passes

Run from packages/fpl-grounded-assistant::

    python run_blank_gw_differential_tests.py
"""
from __future__ import annotations

import copy
import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

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

from fpl_grounded_assistant.differential_picks import (
    _has_current_gw_fixture,
    get_differential_picks,
)
from fpl_grounded_assistant.conversation_fixtures import (
    DIFFERENTIAL_BOOTSTRAP,
    DIFFERENTIAL_BGW_BOOTSTRAP,
)
from fpl_grounded_assistant import respond

# ---------------------------------------------------------------------------
# Test runner helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    label = label.replace("\u2192", "->")  # ASCII-safe for Windows cp1252
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Section A: _has_current_gw_fixture helper
# ---------------------------------------------------------------------------

print("\n=== Section A: _has_current_gw_fixture helper ===")

# Team has fixture in current GW
_tf_a = {1: [{"gameweek": 28, "is_home": True}]}
ok(_has_current_gw_fixture(1, _tf_a, 28) is True,
   "team with GW28 fixture -> True")

# Team has fixtures but none in current GW (blank)
_tf_b = {1: [{"gameweek": 29, "is_home": True}]}
ok(_has_current_gw_fixture(1, _tf_b, 28) is False,
   "team with no GW28 fixture (blank) -> False")

# team_fixtures is None -> cannot determine
ok(_has_current_gw_fixture(1, None, 28) is None,
   "team_fixtures=None -> None (filter skipped)")

# current_gw is None -> cannot determine
ok(_has_current_gw_fixture(1, {1: [{"gameweek": 28}]}, None) is None,
   "current_gw=None -> None (filter skipped)")

# Team not in team_fixtures -> cannot determine
ok(_has_current_gw_fixture(99, {1: [{"gameweek": 28}]}, 28) is None,
   "team not in team_fixtures -> None (filter skipped)")

# Empty fixtures list for team -> False (no fixture this GW, but data is present)
ok(_has_current_gw_fixture(1, {1: []}, 28) is False,
   "empty fixtures list for team -> False (blank)")

# ---------------------------------------------------------------------------
# Section B: Blank-GW exclusion
# ---------------------------------------------------------------------------

print("\n=== Section B: Blank-GW exclusion ===")

# DIFFERENTIAL_BGW_BOOTSTRAP: Chelsea (team 8) has no GW28 fixture.
# Palmer (CHE) should be excluded; Mbeumo (MUN) should remain.
bgw_result = get_differential_picks(DIFFERENTIAL_BGW_BOOTSTRAP)

ok(bgw_result["status"] == "ok",
   "BGW bootstrap: status=ok (Mbeumo still qualifies)")

_bgw_names = [p["web_name"] for p in bgw_result["picks"]]
ok("Palmer" not in _bgw_names,
   "Palmer (CHE, blank GW28) excluded from picks")
ok("Mbeumo" in _bgw_names,
   "Mbeumo (MUN, has GW28 fixture) included in picks")

# Verify Palmer's team (8) is genuinely blank in the fixture
ok(
    _has_current_gw_fixture(8, DIFFERENTIAL_BGW_BOOTSTRAP["team_fixtures"], 28) is False,
    "Chelsea (team 8) has no GW28 fixture in BGW bootstrap",
)

# Verify Mbeumo's team (11) is NOT blank
ok(
    _has_current_gw_fixture(11, DIFFERENTIAL_BGW_BOOTSTRAP["team_fixtures"], 28) is True,
    "Man Utd (team 11) has GW28 fixture in BGW bootstrap",
)

# ---------------------------------------------------------------------------
# Section C: No-data fallback (team_fixtures=None)
# ---------------------------------------------------------------------------

print("\n=== Section C: No-data fallback (team_fixtures=None) ===")

_no_tf = copy.deepcopy(DIFFERENTIAL_BOOTSTRAP)
del _no_tf["team_fixtures"]

no_tf_result = get_differential_picks(_no_tf)
ok(no_tf_result["status"] == "ok",
   "No team_fixtures: result still ok (no filtering applied)")

_no_tf_names = [p["web_name"] for p in no_tf_result["picks"]]
ok("Palmer" in _no_tf_names,
   "No team_fixtures: Palmer not filtered (data unavailable -> safe default)")
ok("Mbeumo" in _no_tf_names,
   "No team_fixtures: Mbeumo not filtered (data unavailable -> safe default)")

# ---------------------------------------------------------------------------
# Section D: All-blank fallback -> status="empty"
# ---------------------------------------------------------------------------

print("\n=== Section D: All-blank fallback -> status=empty ===")

# Build a bootstrap where every team's GW28 fixture is removed, but all
# low-ownership available players remain in elements.
_all_blank = copy.deepcopy(DIFFERENTIAL_BOOTSTRAP)
# Strip GW28 from all teams
_all_blank["team_fixtures"] = {
    team_id: [f for f in fixtures if f["gameweek"] != 28]
    for team_id, fixtures in _all_blank["team_fixtures"].items()
}

all_blank_result = get_differential_picks(_all_blank)
ok(all_blank_result["status"] == "empty",
   "All-blank: status=empty when filtering leaves no candidates")
ok("message" in all_blank_result,
   "All-blank: empty result includes message")

# ---------------------------------------------------------------------------
# Section E: Normal differential still ranks correctly
# ---------------------------------------------------------------------------

print("\n=== Section E: Normal differential ranking unchanged ===")

# DIFFERENTIAL_BOOTSTRAP: all teams have GW28 fixtures.
# Both Palmer (CHE) and Mbeumo (MUN) should appear.
normal_result = get_differential_picks(DIFFERENTIAL_BOOTSTRAP)
ok(normal_result["status"] == "ok",
   "Normal bootstrap: status=ok")
_normal_names = [p["web_name"] for p in normal_result["picks"]]
ok("Palmer" in _normal_names,
   "Normal bootstrap: Palmer in picks (CHE has GW28 fixture)")
ok("Mbeumo" in _normal_names,
   "Normal bootstrap: Mbeumo in picks (MUN has GW28 fixture)")

# Both players present; rank order driven by position_score.
# Mbeumo (FWD, FDR=2) outranks Palmer (MID, FDR=5) on fixture component — this is expected.
ok(len(normal_result["picks"]) >= 2,
   "Normal bootstrap: at least 2 picks returned")

# ---------------------------------------------------------------------------
# Section F: CLI and HTTP surface parity
# ---------------------------------------------------------------------------

print("\n=== Section F: respond() surface parity ===")

# respond() is the single shared pipeline; CLI/HTTP/session serialization
# is downstream. Verifying respond() is sufficient to confirm parity.
bgw_resp = respond(
    "good differentials this week",
    bootstrap=DIFFERENTIAL_BGW_BOOTSTRAP,
)
ok(bgw_resp.intent == "differential_picks",
   "BGW respond(): intent=differential_picks")
ok(bgw_resp.differential is not None,
   "BGW respond(): differential metadata present")

if bgw_resp.differential:
    _resp_picks = bgw_resp.differential.picks or []
    _resp_names = [p.web_name for p in _resp_picks]
    ok("Palmer" not in _resp_names,
       "BGW respond(): Palmer excluded from FinalResponse picks")
    ok("Mbeumo" in _resp_names,
       "BGW respond(): Mbeumo in FinalResponse picks")

# Normal bootstrap via respond() — no blank players -> both present
normal_resp = respond(
    "good differentials this week",
    bootstrap=DIFFERENTIAL_BOOTSTRAP,
)
ok(normal_resp.intent == "differential_picks",
   "Normal respond(): intent=differential_picks")
if normal_resp.differential:
    _norm_names = [p.web_name for p in (normal_resp.differential.picks or [])]
    ok("Palmer" in _norm_names,
       "Normal respond(): Palmer in FinalResponse (CHE has fixture)")
    ok("Mbeumo" in _norm_names,
       "Normal respond(): Mbeumo in FinalResponse (MUN has fixture)")

# ---------------------------------------------------------------------------
# Section G: Regression — V1 validation corpus
# ---------------------------------------------------------------------------

print("\n=== Section G: V1 regression gate ===")

import subprocess
proc = subprocess.run(
    [sys.executable, "run_validation.py", "--no-artifacts"],
    capture_output=True,
    text=True,
    cwd=_HERE,
)
_val_out = proc.stdout + proc.stderr
_val_pass = "44/44 scenarios PASS" in _val_out
ok(_val_pass, "V1 regression: 44/44 PASS")
if not _val_pass:
    print("    Validation output:")
    for line in _val_out.splitlines()[-10:]:
        print(f"    {line}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
total = _pass + _fail
print(f"Results: {_pass}/{total} PASS")
if _fail:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
