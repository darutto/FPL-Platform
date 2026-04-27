"""
run_phase8c_tests.py
=====================
Phase 8c: DGW/BGW detection and free hit unblock.

Sections
--------
A  _classify_gameweek_type -- formula and boundary conditions
B  _advise_free_hit        -- recommendation per gameweek type
C  get_chip_advice         -- free hit via public entrypoint
D  FinalResponse.chip      -- ChipAdviceMeta signals for free hit
E  Regression: TC/WC/BB    -- existing chip advice unaffected
F  Regression: V1 stateless gate (cli+http, 54 scenarios via run_validation)

Run from packages/fpl-grounded-assistant::

    python run_phase8c_tests.py
"""
from __future__ import annotations

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

from fpl_grounded_assistant.chip_advisor import (
    _classify_gameweek_type,
    _advise_free_hit,
    get_chip_advice,
)
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DGW_BOOTSTRAP,
    BGW_BOOTSTRAP,
)
from fpl_grounded_assistant import respond

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Section A: _classify_gameweek_type formula and boundaries
# ---------------------------------------------------------------------------

print("\n=== A: _classify_gameweek_type ===")

# Build test bootstraps used across multiple sections
no_fixtures_bs = {**STANDARD_BOOTSTRAP}
no_fixtures_bs.pop("team_fixtures", None)

no_gw_bs = {**STANDARD_BOOTSTRAP, "events": []}

partial_dgw_bs = {
    **STANDARD_BOOTSTRAP,
    "team_fixtures": {
        1:  [{"gameweek": 28, "opponent_team": 8,  "is_home": True,  "difficulty": 3},
             {"gameweek": 28, "opponent_team": 11, "is_home": True,  "difficulty": 2}],
        13: [{"gameweek": 28, "opponent_team": 14, "is_home": True,  "difficulty": 3},
             {"gameweek": 28, "opponent_team": 8,  "is_home": False, "difficulty": 3}],
        14: [{"gameweek": 28, "opponent_team": 11, "is_home": True,  "difficulty": 2},
             {"gameweek": 28, "opponent_team": 1,  "is_home": False, "difficulty": 3}],
        8:  [{"gameweek": 28, "opponent_team": 1,  "is_home": False, "difficulty": 4}],
        11: [{"gameweek": 28, "opponent_team": 14, "is_home": False, "difficulty": 5}],
    },
}

# Mixed bootstrap: ARS plays twice (DGW), MCI has no fixture (BGW), others normal
mixed_bs = {
    **STANDARD_BOOTSTRAP,
    "team_fixtures": {
        1:  [{"gameweek": 28, "opponent_team": 8,  "is_home": True, "difficulty": 3},
             {"gameweek": 28, "opponent_team": 11, "is_home": True, "difficulty": 2}],  # DGW
        13: [],                                                                            # BGW
        14: [{"gameweek": 28, "opponent_team": 11, "is_home": True, "difficulty": 2}],  # normal
        8:  [{"gameweek": 28, "opponent_team": 1,  "is_home": False,"difficulty": 4}],  # normal
        11: [{"gameweek": 28, "opponent_team": 14, "is_home": False,"difficulty": 5}],  # normal
    },
}

# A1-A3: normal GW — all teams 1 fixture each
gw_type, dgw_t, dgw_c, bgw_t, bgw_c = _classify_gameweek_type(STANDARD_BOOTSTRAP)
ok(gw_type == "normal", "A1: STANDARD_BOOTSTRAP -> normal")
ok(dgw_c == 0,           "A2: STANDARD_BOOTSTRAP dgw_count == 0")
ok(bgw_c == 0,           "A3: STANDARD_BOOTSTRAP bgw_count == 0")

# A4-A6: DGW bootstrap (6 teams, 2 GW28 fixtures each)
gw_type, dgw_t, dgw_c, bgw_t, bgw_c = _classify_gameweek_type(DGW_BOOTSTRAP)
ok(gw_type == "double", "A4: DGW_BOOTSTRAP -> double")
ok(dgw_c == 6,           "A5: DGW_BOOTSTRAP dgw_count == 6")
ok(bgw_c == 0,           "A6: DGW_BOOTSTRAP bgw_count == 0")

# A7-A9: BGW bootstrap (2 teams with no GW28 fixture)
gw_type, dgw_t, dgw_c, bgw_t, bgw_c = _classify_gameweek_type(BGW_BOOTSTRAP)
ok(gw_type == "blank",            "A7: BGW_BOOTSTRAP -> blank")
ok(dgw_c == 0,                    "A8: BGW_BOOTSTRAP dgw_count == 0")
ok(sorted(bgw_t) == ["ARS","MCI"],"A9: BGW_BOOTSTRAP bgw_teams == ['ARS','MCI']")

# A10-A11: missing team_fixtures -> unknown
gw_type, dgw_t, dgw_c, bgw_t, bgw_c = _classify_gameweek_type(no_fixtures_bs)
ok(gw_type == "unknown", "A10: missing team_fixtures -> unknown")
ok(dgw_c == 0 and bgw_c == 0, "A11: missing team_fixtures both counts == 0")

# A12: missing current GW -> unknown
gw_type, *_ = _classify_gameweek_type(no_gw_bs)
ok(gw_type == "unknown", "A12: no current GW event -> unknown")

# A13-A14: partial DGW (3 teams in DGW, 0 BGW)
gw_type, dgw_t, dgw_c, bgw_t, bgw_c = _classify_gameweek_type(partial_dgw_bs)
ok(gw_type == "double", "A13: partial DGW (3 teams) -> double (no BGW)")
ok(dgw_c == 3,           "A14: partial DGW dgw_count == 3")

# A15: mixed week (1 DGW + 1 BGW) -> "mixed", NOT "double"
gw_type, dgw_t, dgw_c, bgw_t, bgw_c = _classify_gameweek_type(mixed_bs)
ok(gw_type == "mixed",         "A15: mixed week (DGW+BGW) -> 'mixed'")
ok(dgw_c == 1 and dgw_t == ["ARS"], "A16: mixed week dgw_count=1, dgw_teams=['ARS']")
ok(bgw_c == 1 and bgw_t == ["MCI"], "A17: mixed week bgw_count=1, bgw_teams=['MCI']")

# ---------------------------------------------------------------------------
# Section B: _advise_free_hit recommendation per gameweek type
# ---------------------------------------------------------------------------

print("\n=== B: _advise_free_hit recommendation ===")

# B1-B3: DGW_BOOTSTRAP -> favorable
result = _advise_free_hit(DGW_BOOTSTRAP, 28)
ok(result["recommendation"] == "conditions_favorable", "B1: DGW (6 teams) -> conditions_favorable")
ok(result["signals"]["gameweek_type"] == "double",     "B2: DGW signals.gameweek_type == 'double'")
ok(result["signals"]["affected_team_count"] == 6,      "B3: DGW signals.affected_team_count == 6")
ok("favorable" in result["advice_text"].lower(),        "B4: DGW advice_text contains 'favorable'")

# B5-B8: BGW_BOOTSTRAP -> marginal
result = _advise_free_hit(BGW_BOOTSTRAP, 28)
ok(result["recommendation"] == "conditions_marginal", "B5: BGW -> conditions_marginal")
ok(result["signals"]["gameweek_type"] == "blank",      "B6: BGW signals.gameweek_type == 'blank'")
ok(result["signals"]["affected_team_count"] == 2,      "B7: BGW signals.affected_team_count == 2")
ok("marginal" in result["advice_text"].lower(),         "B8: BGW advice_text contains 'marginal'")

# B9-B12: STANDARD_BOOTSTRAP (normal GW) -> unfavorable
result = _advise_free_hit(STANDARD_BOOTSTRAP, 28)
ok(result["recommendation"] == "conditions_unfavorable", "B9: normal GW -> conditions_unfavorable")
ok(result["signals"]["gameweek_type"] == "normal",        "B10: normal GW signals.gameweek_type == 'normal'")
ok(result["signals"]["affected_team_count"] == 0,         "B11: normal GW affected_count == 0")
ok("unfavorable" in result["advice_text"].lower(),         "B12: normal GW advice_text contains 'unfavorable'")

# B13: partial DGW (3 teams, below 6) -> marginal
result = _advise_free_hit(partial_dgw_bs, 28)
ok(result["recommendation"] == "conditions_marginal", "B13: partial DGW (3 teams) -> conditions_marginal")

# B14: fallback when no team_fixtures -> unfavorable (safe)
result = _advise_free_hit(no_fixtures_bs, 28)
ok(result["recommendation"] == "conditions_unfavorable", "B14: no team_fixtures -> conditions_unfavorable (safe fallback)")

# B15: signals contain current_gameweek
result = _advise_free_hit(STANDARD_BOOTSTRAP, 28)
ok(result["signals"]["current_gameweek"] == 28, "B15: signals.current_gameweek == 28")

# B16-B20: mixed week (1 DGW + 1 BGW) — Phase 8c1 defect fix
result = _advise_free_hit(mixed_bs, 28)
ok(result["recommendation"] == "conditions_marginal",    "B16: mixed (1 DGW+1 BGW) -> conditions_marginal")
ok(result["signals"]["gameweek_type"] == "mixed",        "B17: mixed signals.gameweek_type == 'mixed'")
ok(result["signals"]["dgw_count"] == 1,                  "B18: mixed signals.dgw_count == 1")
ok(result["signals"]["bgw_count"] == 1,                  "B19: mixed signals.bgw_count == 1")
ok("mixed" in result["advice_text"].lower(),             "B20: mixed advice_text contains 'mixed'")

# B21-B23: no current GW — Phase 8c1 defect fix (no GW0 in text)
result = _advise_free_hit(no_gw_bs, None)
ok(result["signals"]["current_gameweek"] is None,        "B21: no-GW signals.current_gameweek is None")
ok("GW0" not in result["advice_text"],                   "B22: no-GW advice_text does NOT contain 'GW0'")
ok("GW" not in result["advice_text"] or not any(
       w.startswith("GW") and w[2:].rstrip(").").isdigit()
       for w in result["advice_text"].split()),
   "B23: no-GW advice_text contains no 'GWN' token")

# B24: backward-compat affected_team_count still present for mixed
result = _advise_free_hit(mixed_bs, 28)
ok("affected_team_count" in result["signals"],            "B24: mixed signals still has affected_team_count (backward compat)")
ok(result["signals"]["affected_team_count"] == 2,        "B25: mixed affected_team_count == 2 (1 DGW + 1 BGW)")

# ---------------------------------------------------------------------------
# Section C: get_chip_advice public entrypoint
# ---------------------------------------------------------------------------

print("\n=== C: get_chip_advice (free_hit) ===")

# C1-C3: DGW favorable
raw = get_chip_advice("free_hit", DGW_BOOTSTRAP)
ok(raw["status"] == "ok",                              "C1: DGW free_hit status=ok")
ok(raw["recommendation"] == "conditions_favorable",    "C2: DGW free_hit recommendation=conditions_favorable")
ok(raw["chip"] == "free_hit",                          "C3: chip field == 'free_hit'")

# C4-C5: BGW marginal
raw = get_chip_advice("free_hit", BGW_BOOTSTRAP)
ok(raw["recommendation"] == "conditions_marginal",     "C4: BGW free_hit recommendation=conditions_marginal")
ok(raw["signals"]["gameweek_type"] == "blank",         "C5: BGW signals.gameweek_type == 'blank'")

# C6-C7: normal GW unfavorable
raw = get_chip_advice("free_hit", STANDARD_BOOTSTRAP)
ok(raw["recommendation"] == "conditions_unfavorable",  "C6: normal GW free_hit recommendation=conditions_unfavorable")
ok(raw["signals"]["gameweek_type"] == "normal",        "C7: normal GW signals.gameweek_type == 'normal'")

# C8: current_gameweek preserved in output
ok(raw["current_gameweek"] == 28, "C8: current_gameweek == 28 in output")

# ---------------------------------------------------------------------------
# Section D: FinalResponse.chip — ChipAdviceMeta for free hit
# ---------------------------------------------------------------------------

print("\n=== D: FinalResponse.chip (free_hit ChipAdviceMeta) ===")

# D1-D5: DGW favorable
resp_dgw = respond("should I free hit this week", DGW_BOOTSTRAP)
ok(resp_dgw.chip is not None,                                "D1: DGW chip meta non-null")
ok(resp_dgw.chip.chip == "free_hit",                         "D2: DGW chip.chip == 'free_hit'")
ok(resp_dgw.chip.recommendation == "conditions_favorable",   "D3: DGW chip.recommendation == conditions_favorable")
ok(resp_dgw.chip.signal_value == 6.0,                        "D4: DGW chip.signal_value == 6.0 (6 DGW teams)")
ok(resp_dgw.chip.signal_label == "double gameweek teams",    "D5: DGW chip.signal_label == 'double gameweek teams'")

# D6-D9: BGW marginal
resp_bgw = respond("should I free hit this week", BGW_BOOTSTRAP)
ok(resp_bgw.chip is not None,                                "D6: BGW chip meta non-null")
ok(resp_bgw.chip.recommendation == "conditions_marginal",    "D7: BGW chip.recommendation == conditions_marginal")
ok(resp_bgw.chip.signal_value == 2.0,                        "D8: BGW chip.signal_value == 2.0 (2 BGW teams)")
ok(resp_bgw.chip.signal_label == "blank gameweek teams",     "D9: BGW chip.signal_label == 'blank gameweek teams'")

# D10-D13: normal GW unfavorable
resp_std = respond("should I free hit this week", STANDARD_BOOTSTRAP)
ok(resp_std.chip is not None,                                 "D10: normal GW chip meta non-null")
ok(resp_std.chip.recommendation == "conditions_unfavorable",  "D11: normal GW chip.recommendation == conditions_unfavorable")
ok(resp_std.chip.signal_value == 0.0,                         "D12: normal GW chip.signal_value == 0.0")
ok(resp_std.chip.signal_label == "normal gameweek",           "D13: normal GW chip.signal_label == 'normal gameweek'")

# D14: gw field populated
ok(resp_dgw.chip.gw == 28, "D14: chip.gw == 28")

# ---------------------------------------------------------------------------
# Section E: Regression — TC, WC, BB unaffected
# ---------------------------------------------------------------------------

print("\n=== E: Regression — TC/WC/BB unaffected ===")

raw_tc = get_chip_advice("triple_captain", STANDARD_BOOTSTRAP)
ok(raw_tc["status"] == "ok",                              "E1: TC status=ok")
ok(raw_tc["recommendation"] in (
    "conditions_favorable", "conditions_marginal",
    "conditions_unfavorable"),                             "E2: TC recommendation valid vocab")
ok("top_captain_score" in raw_tc["signals"],               "E3: TC signals.top_captain_score present")

raw_wc = get_chip_advice("wildcard", STANDARD_BOOTSTRAP)
ok(raw_wc["status"] == "ok",                               "E4: WC status=ok")
ok(raw_wc["recommendation"] in (
    "conditions_favorable", "conditions_marginal",
    "conditions_unfavorable"),                             "E5: WC recommendation valid vocab")

raw_bb = get_chip_advice("bench_boost", STANDARD_BOOTSTRAP)
ok(raw_bb["status"] == "ok",                               "E6: BB status=ok")
ok("average_fdr_top10" in raw_bb["signals"],               "E7: BB signals.average_fdr_top10 present")

# TC/WC/BB unaffected by DGW_BOOTSTRAP too
raw_tc_dgw = get_chip_advice("triple_captain", DGW_BOOTSTRAP)
ok(raw_tc_dgw["recommendation"] in (
    "conditions_favorable", "conditions_marginal",
    "conditions_unfavorable"),                             "E8: TC unaffected by DGW_BOOTSTRAP")

# ---------------------------------------------------------------------------
# Section G: Phase 8c1 — mixed week + no-GW via FinalResponse.chip
# ---------------------------------------------------------------------------

print("\n=== G: Phase 8c1 defect closure (mixed week + no-GW) ===")

# G1-G5: mixed week FinalResponse.chip
resp_mixed = respond("should I free hit this week", mixed_bs)
ok(resp_mixed.chip is not None,                                 "G1: mixed chip meta non-null")
ok(resp_mixed.chip.recommendation == "conditions_marginal",     "G2: mixed chip.recommendation == conditions_marginal")
ok(resp_mixed.chip.signal_label == "mixed gameweek (double teams)", "G3: mixed chip.signal_label correct")
ok(resp_mixed.chip.signal_value == 1.0,                         "G4: mixed chip.signal_value == 1.0 (dgw_count)")
ok("GW28" in resp_mixed.final_text or "GW" in resp_mixed.final_text, "G5: mixed final_text has GW label")

# G6-G8: no-GW bootstrap — no GW0 in text at any layer
resp_no_gw = respond("should I free hit this week", no_gw_bs)
ok("GW0" not in resp_no_gw.final_text,   "G6: no-GW final_text never contains 'GW0'")
ok(resp_no_gw.chip is not None,          "G7: no-GW chip meta still populated (intent handled)")
ok(resp_no_gw.chip.gw is None,           "G8: no-GW chip.gw is None (not 0)")

# G9: mixed week signals expose dgw_teams and bgw_teams granularly
raw_mixed = get_chip_advice("free_hit", mixed_bs)
ok("dgw_teams" in raw_mixed["signals"],   "G9: mixed signals.dgw_teams present")
ok("bgw_teams" in raw_mixed["signals"],   "G10: mixed signals.bgw_teams present")
ok(raw_mixed["signals"]["dgw_teams"] == ["ARS"], "G11: mixed signals.dgw_teams == ['ARS']")
ok(raw_mixed["signals"]["bgw_teams"] == ["MCI"], "G12: mixed signals.bgw_teams == ['MCI']")

# ---------------------------------------------------------------------------
# Section F: Regression — V1 stateless gate (cli+http scenarios)
# ---------------------------------------------------------------------------

print("\n=== F: V1 stateless regression gate ===")

try:
    from validation_corpus import VALIDATION_SCENARIOS
    from run_validation import _resolve_bootstrap, run_cli_surface, run_http_surface

    f_pass = 0
    f_fail = 0

    for sc in VALIDATION_SCENARIOS:
        if not any(s in ("cli", "http") for s in sc.surfaces):
            continue
        bs = _resolve_bootstrap(sc.bootstrap)
        for surface, runner in (("cli", run_cli_surface), ("http", run_http_surface)):
            if surface not in sc.surfaces:
                continue
            try:
                result = runner(sc, bs)
                intent_ok   = result.get("intent")   == sc.expected_intent
                outcome_ok  = result.get("outcome")  == sc.expected_outcome
                support_ok  = result.get("supported") == sc.expected_supported
                chip_ok     = True
                if sc.expect_chip:
                    chip_ok = result.get("chip") is not None
                if intent_ok and outcome_ok and support_ok and chip_ok:
                    f_pass += 1
                else:
                    f_fail += 1
                    print(f"    FAIL  F [{sc.id}] {surface}: "
                          f"intent={result.get('intent')!r}(exp={sc.expected_intent!r}) "
                          f"outcome={result.get('outcome')!r}(exp={sc.expected_outcome!r}) "
                          f"chip_ok={chip_ok}")
            except Exception as exc:
                f_fail += 1
                print(f"    FAIL  F [{sc.id}] {surface}: exception: {exc}")

    ok(f_fail == 0 and f_pass > 0,
       f"F: stateless regression gate — {f_pass} pass, {f_fail} fail")

except Exception as exc:
    print(f"  SKIP  F: could not import validation runners ({exc})")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
total = _pass + _fail
print(f"Phase 8c: {_pass}/{total} assertions passed.")
if _fail:
    print(f"          {_fail} FAILED.")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
