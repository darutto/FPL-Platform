"""
run_phase26e2_tests.py
======================
Phase 2.6e.2: Explicit DGW/BGW labeling on team fixture calendar entries.

New fields per team entry (additive, backward-compatible)
----------------------------------------------------------
has_dgw        bool   — True when team has >=2 fixtures in any GW in the horizon
has_bgw        bool   — True when team blanks in a GW other teams play
dgw_gameweeks  list   — sorted GW numbers where team has a double fixture
bgw_gameweeks  list   — sorted GW numbers where team has a blank (others play)

Labeling rules
--------------
A GW is "active" if >=1 team has a fixture in it.
DGW for team: >=2 fixtures in one GW inside horizon.
BGW for team: 0 fixtures in an active GW inside horizon.
If ALL teams are blank in a GW (no data beyond a cut-off), that GW is NOT a BGW.

Test bootstraps
---------------
DGW_BOOTSTRAP  — all 6 teams have 2 GW28 fixtures -> DGW:28 for every team
BGW_BOOTSTRAP  — ARS+MCI blank GW28 while LIV/CHE/MUN play -> BGW:28 for ARS+MCI
STANDARD_BOOTSTRAP — clean 1-fixture-per-GW schedule -> no DGW/BGW anywhere

Expected DGW_BOOTSTRAP rankings (horizon=2, GW28-29)
------------------------------------------------------
All teams have 2 GW28 + 1 GW29 = 3 fixtures each.
Difficulties vary; ranking by avg_fdr unchanged from Phase 2.6e.1 formula.

Expected BGW_BOOTSTRAP results (horizon=2, GW28-29)
-----------------------------------------------------
ARS: GW28 blank (BGW) + GW29 home vs MUN FDR3 -> fixture_count=1, avg=3.0, bgw:28
MCI: GW28 blank (BGW) + GW29 away vs LIV FDR4 -> fixture_count=1, avg=4.0, bgw:28
LIV: GW28 home vs MUN FDR2 + GW29 home vs MCI FDR3 -> fixture_count=2, avg=2.5
CHE: GW28 home vs LIV FDR3 + GW29 home vs MUN FDR2 -> fixture_count=2, avg=2.5
MUN: GW28 away vs LIV FDR5 + GW29 away vs ARS FDR4 -> fixture_count=2, avg=4.5

Regression
----------
run_phase26e1_tests:  119/119
run_validation:       65/65
run_phase26d4_tests:  35/35
"""
from __future__ import annotations

import os
import sys
import subprocess

_PGROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

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


_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


from fpl_grounded_assistant.team_fixture_calendar import (  # noqa: E402
    get_team_fixture_calendar,
    _get_active_gws,
    _classify_team_gws,
)
from fpl_grounded_assistant.final_response import respond   # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import (  # noqa: E402
    STANDARD_BOOTSTRAP, DGW_BOOTSTRAP, BGW_BOOTSTRAP,
)


# ---------------------------------------------------------------------------
# A — New fields are present and zero on clean schedule (STANDARD_BOOTSTRAP)
# ---------------------------------------------------------------------------

print("\n=== A: Fields present on clean schedule (no DGW/BGW) ===")

result_std = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="easiest", horizon=5)
teams_std  = result_std.get("teams", [])

for t in teams_std:
    short = t.get("team_short", "?")
    _check(f"A1 {short}: has_dgw field present", "has_dgw" in t)
    _check(f"A2 {short}: has_bgw field present", "has_bgw" in t)
    _check(f"A3 {short}: dgw_gameweeks field present", "dgw_gameweeks" in t)
    _check(f"A4 {short}: bgw_gameweeks field present", "bgw_gameweeks" in t)
    _check(f"A5 {short}: has_dgw=False (no doubles)", t.get("has_dgw") is False,
           f"got {t.get('has_dgw')}")
    _check(f"A6 {short}: has_bgw=False (no blanks)", t.get("has_bgw") is False,
           f"got {t.get('has_bgw')}")
    _check(f"A7 {short}: dgw_gameweeks=[]", t.get("dgw_gameweeks") == [],
           f"got {t.get('dgw_gameweeks')}")
    _check(f"A8 {short}: bgw_gameweeks=[]", t.get("bgw_gameweeks") == [],
           f"got {t.get('bgw_gameweeks')}")


# ---------------------------------------------------------------------------
# B — _get_active_gws helper
# ---------------------------------------------------------------------------

print("\n=== B: _get_active_gws helper ===")

# STANDARD_BOOTSTRAP, horizon 5 from GW28 -> active GWs = {28,29,30,31,32}
active_std = _get_active_gws(STANDARD_BOOTSTRAP["team_fixtures"], 28, 5)
_check("B1 active GWs for STANDARD_BOOTSTRAP horizon=5",
       active_std == frozenset({28, 29, 30, 31, 32}),
       f"got {sorted(active_std)}")

# BGW_BOOTSTRAP, horizon=2 -> GW28 and GW29 are active (LIV/CHE/MUN play GW28)
active_bgw = _get_active_gws(BGW_BOOTSTRAP["team_fixtures"], 28, 2)
_check("B2 active GWs for BGW_BOOTSTRAP horizon=2 includes GW28",
       28 in active_bgw, f"got {sorted(active_bgw)}")
_check("B3 active GWs for BGW_BOOTSTRAP horizon=2 includes GW29",
       29 in active_bgw, f"got {sorted(active_bgw)}")

# DGW_BOOTSTRAP, horizon=1 (only GW28) -> {28}
active_dgw1 = _get_active_gws(DGW_BOOTSTRAP["team_fixtures"], 28, 1)
_check("B4 active GWs for DGW_BOOTSTRAP horizon=1 = {28}",
       active_dgw1 == frozenset({28}),
       f"got {sorted(active_dgw1)}")


# ---------------------------------------------------------------------------
# C — _classify_team_gws helper: DGW detection
# ---------------------------------------------------------------------------

print("\n=== C: _classify_team_gws — DGW detection ===")

# DGW_BOOTSTRAP: ARS (team 1) has 2 GW28 fixtures
active_dgw2 = _get_active_gws(DGW_BOOTSTRAP["team_fixtures"], 28, 2)
dgw_ars, bgw_ars = _classify_team_gws(1, DGW_BOOTSTRAP["team_fixtures"], 28, 2, active_dgw2)
_check("C1 ARS dgw_gameweeks=[28] in DGW_BOOTSTRAP",
       dgw_ars == [28], f"got {dgw_ars}")
_check("C2 ARS bgw_gameweeks=[] in DGW_BOOTSTRAP",
       bgw_ars == [], f"got {bgw_ars}")

# DGW_BOOTSTRAP: all teams have 2 GW28 fixtures
for team_id, short in [(1,"ARS"),(13,"MCI"),(14,"LIV"),(8,"CHE"),(11,"MUN"),(17,"TOT")]:
    dg, bg = _classify_team_gws(team_id, DGW_BOOTSTRAP["team_fixtures"], 28, 1, active_dgw1)
    _check(f"C3 {short}: dgw=[28] when horizon=1", dg == [28], f"got {dg}")
    _check(f"C4 {short}: bgw=[]  when horizon=1", bg == [],   f"got {bg}")


# ---------------------------------------------------------------------------
# D — _classify_team_gws helper: BGW detection
# ---------------------------------------------------------------------------

print("\n=== D: _classify_team_gws — BGW detection ===")

active_bgw2 = _get_active_gws(BGW_BOOTSTRAP["team_fixtures"], 28, 2)

# ARS (team 1): no GW28 fixture -> BGW:28; has GW29 -> no blank there
dg_ars_b, bg_ars_b = _classify_team_gws(1, BGW_BOOTSTRAP["team_fixtures"], 28, 2, active_bgw2)
_check("D1 ARS: bgw_gameweeks=[28] in BGW_BOOTSTRAP",
       bg_ars_b == [28], f"got {bg_ars_b}")
_check("D2 ARS: dgw_gameweeks=[] in BGW_BOOTSTRAP",
       dg_ars_b == [], f"got {dg_ars_b}")

# MCI (team 13): same as ARS
dg_mci_b, bg_mci_b = _classify_team_gws(13, BGW_BOOTSTRAP["team_fixtures"], 28, 2, active_bgw2)
_check("D3 MCI: bgw_gameweeks=[28]", bg_mci_b == [28], f"got {bg_mci_b}")

# LIV (team 14): plays GW28 -> no BGW in GW28; plays GW29 -> no BGW in GW29
dg_liv_b, bg_liv_b = _classify_team_gws(14, BGW_BOOTSTRAP["team_fixtures"], 28, 2, active_bgw2)
_check("D4 LIV: bgw_gameweeks=[] (plays both GWs)", bg_liv_b == [], f"got {bg_liv_b}")
_check("D5 LIV: dgw_gameweeks=[] (no doubles)",     dg_liv_b == [], f"got {dg_liv_b}")


# ---------------------------------------------------------------------------
# E — Handler output: DGW_BOOTSTRAP labels correct
# ---------------------------------------------------------------------------

print("\n=== E: Handler — DGW_BOOTSTRAP labels ===")

result_dgw = get_team_fixture_calendar(DGW_BOOTSTRAP, mode="easiest", horizon=2)
_check("E1 status=ok", result_dgw.get("status") == "ok",
       f"got {result_dgw.get('status')!r}")

teams_dgw = result_dgw.get("teams", [])
for t in teams_dgw:
    short = t.get("team_short", "?")
    _check(f"E2 {short}: has_dgw=True",
           t.get("has_dgw") is True, f"got {t.get('has_dgw')}")
    _check(f"E3 {short}: dgw_gameweeks=[28]",
           t.get("dgw_gameweeks") == [28], f"got {t.get('dgw_gameweeks')}")
    _check(f"E4 {short}: has_bgw=False",
           t.get("has_bgw") is False, f"got {t.get('has_bgw')}")
    _check(f"E5 {short}: bgw_gameweeks=[]",
           t.get("bgw_gameweeks") == [], f"got {t.get('bgw_gameweeks')}")


# ---------------------------------------------------------------------------
# F — Handler output: BGW_BOOTSTRAP labels correct (horizon=2)
# ---------------------------------------------------------------------------

print("\n=== F: Handler — BGW_BOOTSTRAP labels ===")

result_bgw = get_team_fixture_calendar(BGW_BOOTSTRAP, mode="easiest", horizon=2, top_n=5)
teams_bgw  = result_bgw.get("teams", [])
_check("F1 status=ok", result_bgw.get("status") == "ok")
_check("F2 5 teams returned", len(teams_bgw) == 5, f"got {len(teams_bgw)}")

teams_by_short = {t["team_short"]: t for t in teams_bgw}

# ARS: no GW28 fixture; GW29 fixture exists
ars = teams_by_short.get("ARS", {})
_check("F3 ARS: has_bgw=True",           ars.get("has_bgw") is True,    f"got {ars.get('has_bgw')}")
_check("F4 ARS: bgw_gameweeks=[28]",     ars.get("bgw_gameweeks") == [28], f"got {ars.get('bgw_gameweeks')}")
_check("F5 ARS: has_dgw=False",          ars.get("has_dgw") is False,   f"got {ars.get('has_dgw')}")
_check("F6 ARS: fixture_count=1",        ars.get("fixture_count") == 1, f"got {ars.get('fixture_count')}")

# MCI: same as ARS
mci = teams_by_short.get("MCI", {})
_check("F7 MCI: has_bgw=True",           mci.get("has_bgw") is True)
_check("F8 MCI: bgw_gameweeks=[28]",     mci.get("bgw_gameweeks") == [28])

# LIV: plays GW28 and GW29, no blanks
liv = teams_by_short.get("LIV", {})
_check("F9 LIV: has_bgw=False",          liv.get("has_bgw") is False,   f"got {liv.get('has_bgw')}")
_check("F10 LIV: bgw_gameweeks=[]",      liv.get("bgw_gameweeks") == [], f"got {liv.get('bgw_gameweeks')}")
_check("F11 LIV: fixture_count=2",       liv.get("fixture_count") == 2, f"got {liv.get('fixture_count')}")

# CHE and MUN also play GW28, no blank
for short in ("CHE", "MUN"):
    t = teams_by_short.get(short, {})
    _check(f"F12 {short}: has_bgw=False", t.get("has_bgw") is False)


# ---------------------------------------------------------------------------
# G — Ranking formula unchanged by labels (scores same as Phase 2.6e.1)
# ---------------------------------------------------------------------------

print("\n=== G: Ranking formula unchanged ===")

# STANDARD_BOOTSTRAP: same results as Phase 2.6e.1
result_clean = get_team_fixture_calendar(STANDARD_BOOTSTRAP, mode="easiest", horizon=5)
t_clean = result_clean.get("teams", [])
_check("G1 LIV still ranks #1 (avg 2.8)", t_clean[0]["team_short"] == "LIV",
       f"got {t_clean[0]['team_short']}")
_check("G2 MUN still ranks #5 (avg 4.2)", t_clean[4]["team_short"] == "MUN",
       f"got {t_clean[4]['team_short']}")
_check("G3 avg_fdr values unchanged",
       t_clean[0]["avg_fdr"] == 2.80 and t_clean[4]["avg_fdr"] == 4.20)


# ---------------------------------------------------------------------------
# H — Metadata propagates through respond() / FinalResponse
# ---------------------------------------------------------------------------

print("\n=== H: Metadata propagates through respond() ===")

fr_dgw = respond("mejor calendario", DGW_BOOTSTRAP)
_check("H1 intent=team_fixture_calendar", fr_dgw.intent == "team_fixture_calendar")
_check("H2 team_calendar meta non-None", fr_dgw.team_calendar is not None)
if fr_dgw.team_calendar:
    first = fr_dgw.team_calendar.teams[0]
    _check("H3 meta.teams[0].has_dgw=True", first.has_dgw is True,
           f"got {first.has_dgw}")
    _check("H4 meta.teams[0].dgw_gameweeks contains 28",
           28 in first.dgw_gameweeks, f"got {first.dgw_gameweeks}")
    _check("H5 meta.teams[0].bgw_gameweeks=() (empty tuple)",
           first.bgw_gameweeks == (), f"got {first.bgw_gameweeks}")

fr_bgw = respond("mejor calendario", BGW_BOOTSTRAP)
_check("H6 BGW intent=team_fixture_calendar", fr_bgw.intent == "team_fixture_calendar")
if fr_bgw.team_calendar:
    teams_by_short_meta = {t.team_short: t for t in fr_bgw.team_calendar.teams}
    ars_meta = teams_by_short_meta.get("ARS")
    if ars_meta:
        _check("H7 ARS meta.has_bgw=True", ars_meta.has_bgw is True)
        _check("H8 ARS meta.bgw_gameweeks=(28,)",
               ars_meta.bgw_gameweeks == (28,), f"got {ars_meta.bgw_gameweeks}")


# ---------------------------------------------------------------------------
# I — Renderer includes DGW/BGW label in final_text
# ---------------------------------------------------------------------------

print("\n=== I: Renderer shows DGW/BGW labels ===")

_check("I1 DGW scenario final_text contains 'DGW'",
       "DGW" in fr_dgw.final_text,
       f"first 300 chars: {fr_dgw.final_text[:300]}")
_check("I2 BGW scenario final_text contains 'BGW'",
       "BGW" in fr_bgw.final_text,
       f"first 300 chars: {fr_bgw.final_text[:300]}")
_check("I3 clean scenario final_text contains no DGW/BGW",
       "DGW" not in fr_clean_text and "BGW" not in fr_clean_text
       if (fr_clean_text := respond("mejor calendario", STANDARD_BOOTSTRAP).final_text)
       else True)


# ---------------------------------------------------------------------------
# J — Regression suites
# ---------------------------------------------------------------------------

print("\n=== J: Regression ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"J1 validation corpus {passed}/{total} PASS", passed == total,
       f"{total - passed} scenario(s) failed")

for suite, label, pattern in [
    ("run_phase26e1_tests.py", "J2 phase26e1", "119/119"),
    ("run_phase26d4_tests.py", "J3 phase26d4", "35/35"),
]:
    proc = subprocess.run(
        [sys.executable, os.path.join(_HERE, suite)],
        capture_output=True, text=True, cwd=_HERE,
        timeout=120, creationflags=_PGROUP,
    )
    count_line = [l for l in proc.stdout.splitlines() if pattern in l]
    if count_line:
        _check(f"{label}: {count_line[-1].strip()}", pattern in count_line[-1])
    else:
        _check(label, False, f"'{pattern}' not found in output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6e.2: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"               {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("               All assertions passed.")
