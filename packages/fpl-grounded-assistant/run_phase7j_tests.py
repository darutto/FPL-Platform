"""
run_phase7j_tests.py
====================
Phase 7j: Validation Corpus V2 test suite.

Verifies that:
- New expect_* fields exist on ValidationScenario
- Updated scenarios correctly assert structured metadata
- New scenarios (30 transfer_followup_det, 31 differential_picks_structured) exist
- DIFFERENTIAL_BOOTSTRAP is available and correct
- CLI serial helper _serial_differential() works correctly
- Validation runner extracts all new fields from all surfaces
- _check_scenario_result() validates the new expect_* flags
- _check_cross_surface_parity() includes structured field presence checks
- Full validation run passes 31/31 scenarios

Sections
--------
A  ValidationScenario dataclass has all new expect_* fields
B  Corpus updated scenarios have correct expect_* flags
C  New scenario #30 transfer_followup_det metadata
D  New scenario #31 differential_picks_structured metadata
E  DIFFERENTIAL_BOOTSTRAP structure and content
F  _serial_differential() correctness
G  Validation runner surface result includes new fields
H  _check_scenario_result() passes for valid structured results
I  _check_scenario_result() catches missing/bad structured fields
J  _check_cross_surface_parity() catches presence mismatches
K  Full validation run -- all 31 scenarios PASS
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


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from validation_corpus import (
    VALIDATION_SCENARIOS, SCENARIO_BY_ID, ValidationScenario,
)
from run_validation import (
    run_cli_surface, run_http_surface,
    run_session_cli_surface, run_session_http_surface,
    _check_scenario_result, _check_cross_surface_parity,
    run_all_scenarios,
)
from fpl_grounded_assistant import STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP
from fpl_grounded_assistant.conversation_fixtures import DIFFERENTIAL_BOOTSTRAP
from fpl_cli import _serial_differential
from fpl_grounded_assistant import (
    DifferentialEntry, DifferentialPicksMeta,
    get_differential_picks,
)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(label: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = "") -> None:
    global _FAIL
    _FAIL += 1
    msg = f"  [FAIL] {label}"
    if detail:
        msg += f": {detail}"
    print(msg)


def chk(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        ok(label)
    else:
        fail(label, detail)


# ---------------------------------------------------------------------------
# Section A: ValidationScenario has all new expect_* fields
# ---------------------------------------------------------------------------

print("\n-- A: ValidationScenario new expect_* fields --")

chk(hasattr(ValidationScenario, "__dataclass_fields__"),
    "ValidationScenario is a dataclass")

fields = ValidationScenario.__dataclass_fields__
chk("expect_transfer" in fields,
    "expect_transfer field exists")
chk("expect_chip" in fields,
    "expect_chip field exists")
chk("expect_fixture_run" in fields,
    "expect_fixture_run field exists")
chk("expect_differential" in fields,
    "expect_differential field exists")

# Default values are False
dummy = ValidationScenario(
    id="test", family="test", description="test", question="test",
    bootstrap="standard", surfaces=("cli",),
    expected_intent="unsupported", expected_outcome="unsupported_intent",
    expected_supported=False,
)
chk(dummy.expect_transfer is False,
    "expect_transfer defaults to False")
chk(dummy.expect_chip is False,
    "expect_chip defaults to False")
chk(dummy.expect_fixture_run is False,
    "expect_fixture_run defaults to False")
chk(dummy.expect_differential is False,
    "expect_differential defaults to False")

# Can be set to True
s_with_transfer = ValidationScenario(
    id="t", family="f", description="d", question="q",
    bootstrap="standard", surfaces=("cli",),
    expected_intent="transfer_advice", expected_outcome="ok",
    expected_supported=True, expect_transfer=True,
)
chk(s_with_transfer.expect_transfer is True,
    "expect_transfer can be set to True")


# ---------------------------------------------------------------------------
# Section B: Updated scenarios have correct expect_* flags
# ---------------------------------------------------------------------------

print("\n-- B: Updated scenarios have correct expect_* flags --")

# Scenario 17: transfer_advice_direct should now have expect_transfer=True
s17 = SCENARIO_BY_ID["transfer_advice_direct"]
chk(s17.expect_transfer is True,
    "#17 transfer_advice_direct has expect_transfer=True")
chk("player_out='Saka'" in s17.notes or "player_out" in s17.notes,
    "#17 notes mention player_out")
chk("No structured metadata field yet" not in s17.notes,
    "#17 notes updated (no 'deferred' language)")

# Scenario 25: chip_advice_triple_captain_structured should have expect_chip=True
s25 = SCENARIO_BY_ID["chip_advice_triple_captain_structured"]
chk(s25.expect_chip is True,
    "#25 chip_advice_triple_captain_structured has expect_chip=True")

# Scenario 26: fixture_run_direct should have expect_fixture_run=True
s26 = SCENARIO_BY_ID["fixture_run_direct"]
chk(s26.expect_fixture_run is True,
    "#26 fixture_run_direct has expect_fixture_run=True")

# Scenarios without expect_* should still default to False
s1 = SCENARIO_BY_ID["direct_captain_score"]
chk(s1.expect_transfer is False,
    "#1 direct_captain_score has expect_transfer=False")
chk(s1.expect_chip is False,
    "#1 direct_captain_score has expect_chip=False")
chk(s1.expect_fixture_run is False,
    "#1 direct_captain_score has expect_fixture_run=False")
chk(s1.expect_differential is False,
    "#1 direct_captain_score has expect_differential=False")


# ---------------------------------------------------------------------------
# Section C: New scenario #30 — transfer_followup_det
# ---------------------------------------------------------------------------

print("\n-- C: Scenario #30 transfer_followup_det --")

chk("transfer_followup_det" in SCENARIO_BY_ID,
    "scenario transfer_followup_det exists in corpus")

s30 = SCENARIO_BY_ID["transfer_followup_det"]
chk(s30.family == "transfer_followup",
    "s30 family == 'transfer_followup'")
chk(s30.question == "what about Haaland instead",
    "s30 question == 'what about Haaland instead'")
chk(s30.bootstrap == "standard",
    "s30 bootstrap == 'standard'")
chk(set(s30.surfaces) == {"session_cli", "session_http"},
    "s30 surfaces == {session_cli, session_http}")
chk(s30.expected_intent == "transfer_advice",
    "s30 expected_intent == 'transfer_advice'")
chk(s30.expected_outcome == "ok",
    "s30 expected_outcome == 'ok'")
chk(s30.expected_supported is True,
    "s30 expected_supported == True")
chk(len(s30.session_prior_turns) == 1,
    "s30 has one prior turn")
chk(s30.session_prior_turns[0] == "should I sell Saka for Salah",
    "s30 prior turn is 'should I sell Saka for Salah'")
chk(s30.expect_transfer is True,
    "s30 expect_transfer == True")
chk(s30.expected_resolver_source == "transfer_followup",
    "s30 expected_resolver_source == 'transfer_followup'")
chk("Haaland" in s30.notes,
    "s30 notes mention Haaland")


# ---------------------------------------------------------------------------
# Section D: New scenario #31 — differential_picks_structured
# ---------------------------------------------------------------------------

print("\n-- D: Scenario #31 differential_picks_structured --")

chk("differential_picks_structured" in SCENARIO_BY_ID,
    "scenario differential_picks_structured exists in corpus")

s31 = SCENARIO_BY_ID["differential_picks_structured"]
chk(s31.family == "differential_picks",
    "s31 family == 'differential_picks'")
chk(s31.question == "good differentials",
    "s31 question == 'good differentials'")
chk(s31.bootstrap == "differential",
    "s31 bootstrap == 'differential'")
chk(set(s31.surfaces) == {"cli", "http"},
    "s31 surfaces == {cli, http}")
chk(s31.expected_intent == "differential_picks",
    "s31 expected_intent == 'differential_picks'")
chk(s31.expected_outcome == "ok",
    "s31 expected_outcome == 'ok'")
chk(s31.expected_supported is True,
    "s31 expected_supported == True")
chk(s31.expect_differential is True,
    "s31 expect_differential == True")
chk("Palmer" in s31.notes,
    "s31 notes mention Palmer")
chk("Mbeumo" in s31.notes,
    "s31 notes mention Mbeumo")


# ---------------------------------------------------------------------------
# Section E: DIFFERENTIAL_BOOTSTRAP structure
# ---------------------------------------------------------------------------

print("\n-- E: DIFFERENTIAL_BOOTSTRAP structure --")

chk(isinstance(DIFFERENTIAL_BOOTSTRAP, dict),
    "DIFFERENTIAL_BOOTSTRAP is a dict")
chk("elements" in DIFFERENTIAL_BOOTSTRAP,
    "DIFFERENTIAL_BOOTSTRAP has elements")
chk("fixture_difficulty_map" in DIFFERENTIAL_BOOTSTRAP,
    "DIFFERENTIAL_BOOTSTRAP has fixture_difficulty_map")
chk(11 in DIFFERENTIAL_BOOTSTRAP["fixture_difficulty_map"],
    "DIFFERENTIAL_BOOTSTRAP fixture_difficulty_map includes team 11 (MUN)")
chk(DIFFERENTIAL_BOOTSTRAP["fixture_difficulty_map"][11] == 2,
    "DIFFERENTIAL_BOOTSTRAP team 11 difficulty == 2")

diff_elements = DIFFERENTIAL_BOOTSTRAP["elements"]
chk(len(diff_elements) > len(STANDARD_BOOTSTRAP["elements"]),
    "DIFFERENTIAL_BOOTSTRAP has more elements than STANDARD_BOOTSTRAP")

# Find Palmer and Mbeumo
palmer = next((e for e in diff_elements if e.get("web_name") == "Palmer"), None)
mbeumo = next((e for e in diff_elements if e.get("web_name") == "Mbeumo"), None)

chk(palmer is not None, "Palmer exists in DIFFERENTIAL_BOOTSTRAP")
chk(mbeumo is not None, "Mbeumo exists in DIFFERENTIAL_BOOTSTRAP")

if palmer:
    chk(palmer.get("status") == "a", "Palmer status == 'a'")
    chk(float(palmer.get("selected_by_percent", "100")) < 15.0,
        "Palmer ownership < 15%")
    chk(palmer.get("team") == 8,
        "Palmer plays for team 8 (Chelsea)")

if mbeumo:
    chk(mbeumo.get("status") == "a", "Mbeumo status == 'a'")
    chk(float(mbeumo.get("selected_by_percent", "100")) < 15.0,
        "Mbeumo ownership < 15%")
    chk(mbeumo.get("team") == 11,
        "Mbeumo plays for team 11 (Man Utd)")

# team_fixtures carries through from STANDARD_BOOTSTRAP
chk("team_fixtures" in DIFFERENTIAL_BOOTSTRAP,
    "DIFFERENTIAL_BOOTSTRAP inherits team_fixtures")
chk(8 in DIFFERENTIAL_BOOTSTRAP["team_fixtures"],
    "team_fixtures includes team 8 (Chelsea) for Palmer")
chk(11 in DIFFERENTIAL_BOOTSTRAP["team_fixtures"],
    "team_fixtures includes team 11 (MUN) for Mbeumo")


# ---------------------------------------------------------------------------
# Section F: _serial_differential() correctness
# ---------------------------------------------------------------------------

print("\n-- F: _serial_differential() correctness --")

# Create a real DifferentialPicksMeta using get_differential_picks
diff_result = get_differential_picks(DIFFERENTIAL_BOOTSTRAP)
chk(diff_result.get("status") == "ok",
    "get_differential_picks returns ok on DIFFERENTIAL_BOOTSTRAP")

picks_raw = diff_result.get("picks", [])
chk(len(picks_raw) >= 1, "at least one pick returned")

# Build a DifferentialPicksMeta for serial testing
picks_frozen = tuple(
    DifferentialEntry(
        rank=int(p["rank"]),
        web_name=p["web_name"],
        team_short=p["team_short"],
        position=p["position"],
        captain_score=float(p["captain_score"]),
        ownership=float(p["ownership"]),
        now_cost=int(p["now_cost"]),
    )
    for p in picks_raw
)
meta = DifferentialPicksMeta(
    ownership_threshold=float(diff_result["ownership_threshold"]),
    top_n=int(diff_result["top_n"]),
    picks=picks_frozen,
)

serial = _serial_differential(meta)

chk("ownership_threshold" in serial, "_serial_differential has ownership_threshold")
chk("top_n" in serial, "_serial_differential has top_n")
chk("picks" in serial, "_serial_differential has picks")
chk(serial["ownership_threshold"] == 15.0,
    "_serial_differential ownership_threshold == 15.0")
chk(isinstance(serial["picks"], list),
    "_serial_differential picks is a list")
if serial["picks"]:
    p0 = serial["picks"][0]
    chk("rank" in p0, "_serial_differential picks[0] has rank")
    chk("web_name" in p0, "_serial_differential picks[0] has web_name")
    chk("team_short" in p0, "_serial_differential picks[0] has team_short")
    chk("position" in p0, "_serial_differential picks[0] has position")
    chk("captain_score" in p0, "_serial_differential picks[0] has captain_score")
    chk("ownership" in p0, "_serial_differential picks[0] has ownership")
    chk("now_cost" in p0, "_serial_differential picks[0] has now_cost")
    chk(p0["rank"] == 1, "_serial_differential picks[0].rank == 1")


# ---------------------------------------------------------------------------
# Section G: Validation runner extracts new fields from surfaces
# ---------------------------------------------------------------------------

print("\n-- G: Surface runners extract new fields --")

# Use transfer_advice_direct (scenario #17) on CLI to check transfer extraction
s17 = SCENARIO_BY_ID["transfer_advice_direct"]
cli_result = run_cli_surface(s17, STANDARD_BOOTSTRAP)
chk("transfer" in cli_result,
    "run_cli_surface result contains 'transfer' key")
chk("chip" in cli_result,
    "run_cli_surface result contains 'chip' key")
chk("fixture_run" in cli_result,
    "run_cli_surface result contains 'fixture_run' key")
chk("differential" in cli_result,
    "run_cli_surface result contains 'differential' key")
chk(cli_result.get("transfer") is not None,
    "transfer_advice_direct CLI transfer is non-None")

# Use chip_advice_triple_captain_structured (scenario #25) on HTTP to check chip extraction
import fpl_server
from fastapi.testclient import TestClient

fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
http_client = TestClient(fpl_server.app, raise_server_exceptions=True)
s25_http = SCENARIO_BY_ID["chip_advice_triple_captain_structured"]
http_result = run_http_surface(s25_http, STANDARD_BOOTSTRAP)
chk("chip" in http_result,
    "run_http_surface result contains 'chip' key")
chk(http_result.get("chip") is not None,
    "chip_advice HTTP chip is non-None")

# Use fixture_run_direct (scenario #26) on CLI to check fixture_run extraction
s26 = SCENARIO_BY_ID["fixture_run_direct"]
fr_result = run_cli_surface(s26, STANDARD_BOOTSTRAP)
chk("fixture_run" in fr_result,
    "run_cli_surface result contains 'fixture_run' key")
chk(fr_result.get("fixture_run") is not None,
    "fixture_run_direct CLI fixture_run is non-None")

# Use differential_picks_structured (scenario #31) on CLI to check differential extraction
s31 = SCENARIO_BY_ID["differential_picks_structured"]
diff_sr = run_cli_surface(s31, DIFFERENTIAL_BOOTSTRAP)
chk("differential" in diff_sr,
    "run_cli_surface result contains 'differential' key")
chk(diff_sr.get("differential") is not None,
    "differential_picks_structured CLI differential is non-None")


# ---------------------------------------------------------------------------
# Section H: _check_scenario_result() passes for valid structured results
# ---------------------------------------------------------------------------

print("\n-- H: _check_scenario_result() passes for valid results --")

# Build a mock surface result for a transfer scenario
valid_transfer_sr = {
    "intent":  "transfer_advice",
    "outcome": "ok",
    "supported": True,
    "transfer": {
        "player_out": "Saka",
        "player_in": "Salah",
        "recommendation": "transfer_in",
        "score_delta": 10.0,
        "price_delta": 35,
        "reasons": ["better form"],
    },
    "chip": None,
    "fixture_run": None,
    "differential": None,
    "captain": None,
    "comparison": None,
    "captain_ranking": None,
}
s_transfer = ValidationScenario(
    id="test_transfer", family="transfer", description="d", question="q",
    bootstrap="standard", surfaces=("cli",),
    expected_intent="transfer_advice", expected_outcome="ok",
    expected_supported=True, expect_transfer=True,
)
h_failures = _check_scenario_result(s_transfer, "cli", valid_transfer_sr)
chk(len(h_failures) == 0,
    "_check_scenario_result passes for valid transfer result",
    str(h_failures))

# Valid chip result
valid_chip_sr = {
    "intent": "chip_advice",
    "outcome": "ok",
    "supported": True,
    "chip": {
        "chip": "triple_captain",
        "recommendation": "conditions_marginal",
        "gw": 28,
        "signal_value": 60.5,
        "signal_label": "top captain score",
    },
    "transfer": None, "fixture_run": None, "differential": None,
    "captain": None, "comparison": None, "captain_ranking": None,
}
s_chip = ValidationScenario(
    id="test_chip", family="chip", description="d", question="q",
    bootstrap="standard", surfaces=("cli",),
    expected_intent="chip_advice", expected_outcome="ok",
    expected_supported=True, expect_chip=True,
)
h_chip_failures = _check_scenario_result(s_chip, "cli", valid_chip_sr)
chk(len(h_chip_failures) == 0,
    "_check_scenario_result passes for valid chip result",
    str(h_chip_failures))

# Valid fixture_run result
valid_fr_sr = {
    "intent": "player_fixture_run",
    "outcome": "ok",
    "supported": True,
    "fixture_run": {
        "web_name": "Salah", "team_short": "LIV", "position": "MID",
        "horizon": 5, "current_gameweek": 28,
        "fixtures": [{"gameweek": 28, "opponent_short": "MUN", "is_home": True, "difficulty": 2}],
    },
    "transfer": None, "chip": None, "differential": None,
    "captain": None, "comparison": None, "captain_ranking": None,
}
s_fr = ValidationScenario(
    id="test_fr", family="player_fixture_run", description="d", question="q",
    bootstrap="standard", surfaces=("cli",),
    expected_intent="player_fixture_run", expected_outcome="ok",
    expected_supported=True, expect_fixture_run=True,
)
h_fr_failures = _check_scenario_result(s_fr, "cli", valid_fr_sr)
chk(len(h_fr_failures) == 0,
    "_check_scenario_result passes for valid fixture_run result",
    str(h_fr_failures))

# Valid differential result
valid_diff_sr = {
    "intent": "differential_picks",
    "outcome": "ok",
    "supported": True,
    "differential": {
        "ownership_threshold": 15.0,
        "top_n": 5,
        "picks": [{"rank": 1, "web_name": "Palmer", "team_short": "CHE",
                   "position": "MID", "captain_score": 45.0,
                   "ownership": 3.5, "now_cost": 60}],
    },
    "transfer": None, "chip": None, "fixture_run": None,
    "captain": None, "comparison": None, "captain_ranking": None,
}
s_diff = ValidationScenario(
    id="test_diff", family="differential_picks", description="d", question="q",
    bootstrap="differential", surfaces=("cli",),
    expected_intent="differential_picks", expected_outcome="ok",
    expected_supported=True, expect_differential=True,
)
h_diff_failures = _check_scenario_result(s_diff, "cli", valid_diff_sr)
chk(len(h_diff_failures) == 0,
    "_check_scenario_result passes for valid differential result",
    str(h_diff_failures))


# ---------------------------------------------------------------------------
# Section I: _check_scenario_result() catches missing/bad structured fields
# ---------------------------------------------------------------------------

print("\n-- I: _check_scenario_result() catches failures --")

# Missing transfer when expect_transfer=True
missing_transfer_sr = {
    "intent": "transfer_advice", "outcome": "ok", "supported": True,
    "transfer": None, "chip": None, "fixture_run": None, "differential": None,
    "captain": None, "comparison": None, "captain_ranking": None,
}
i_fails = _check_scenario_result(s_transfer, "cli", missing_transfer_sr)
chk(any("transfer" in f for f in i_fails),
    "catches missing transfer when expect_transfer=True",
    str(i_fails))

# Bad recommendation in transfer
bad_rec_sr = dict(valid_transfer_sr)
bad_rec_sr["transfer"] = dict(valid_transfer_sr["transfer"])
bad_rec_sr["transfer"]["recommendation"] = "bad_value"
i_rec_fails = _check_scenario_result(s_transfer, "cli", bad_rec_sr)
chk(any("recommendation" in f for f in i_rec_fails),
    "catches invalid transfer recommendation",
    str(i_rec_fails))

# Missing chip when expect_chip=True
missing_chip_sr = {
    "intent": "chip_advice", "outcome": "ok", "supported": True,
    "chip": None, "transfer": None, "fixture_run": None, "differential": None,
    "captain": None, "comparison": None, "captain_ranking": None,
}
i_chip_fails = _check_scenario_result(s_chip, "cli", missing_chip_sr)
chk(any("chip" in f for f in i_chip_fails),
    "catches missing chip when expect_chip=True",
    str(i_chip_fails))

# Missing differential when expect_differential=True
missing_diff_sr = {
    "intent": "differential_picks", "outcome": "ok", "supported": True,
    "differential": None, "transfer": None, "chip": None, "fixture_run": None,
    "captain": None, "comparison": None, "captain_ranking": None,
}
i_diff_fails = _check_scenario_result(s_diff, "cli", missing_diff_sr)
chk(any("differential" in f for f in i_diff_fails),
    "catches missing differential when expect_differential=True",
    str(i_diff_fails))

# Unexpected transfer on non-transfer intent
unexpected_transfer_sr = {
    "intent": "captain_score", "outcome": "ok", "supported": True,
    "transfer": {"player_out": "X", "player_in": "Y", "recommendation": "transfer_in",
                 "score_delta": 1.0, "price_delta": 0, "reasons": []},
    "chip": None, "fixture_run": None, "differential": None,
    "captain": {"tier": "safe", "web_name": "Salah", "team_short": "LIV",
                "captain_score": 60.0, "role_bonus": 5.0, "set_piece_notes": []},
    "comparison": None, "captain_ranking": None,
}
s_capt_only = ValidationScenario(
    id="capt_only", family="captain", description="d", question="q",
    bootstrap="standard", surfaces=("cli",),
    expected_intent="captain_score", expected_outcome="ok",
    expected_supported=True, expect_captain=True,
)
unexpected_fails = _check_scenario_result(s_capt_only, "cli", unexpected_transfer_sr)
chk(any("transfer" in f for f in unexpected_fails),
    "catches unexpected transfer on non-transfer turn",
    str(unexpected_fails))


# ---------------------------------------------------------------------------
# Section J: _check_cross_surface_parity() catches presence mismatches
# ---------------------------------------------------------------------------

print("\n-- J: _check_cross_surface_parity() catches presence mismatches --")

# Two surfaces agree on transfer (both non-null)
agree_results = {
    "cli":  {"intent": "transfer_advice", "outcome": "ok", "supported": True,
             "transfer": {"player_out": "X"}, "chip": None, "fixture_run": None,
             "differential": None, "captain": None, "comparison": None,
             "captain_ranking": None},
    "http": {"intent": "transfer_advice", "outcome": "ok", "supported": True,
             "transfer": {"player_out": "X"}, "chip": None, "fixture_run": None,
             "differential": None, "captain": None, "comparison": None,
             "captain_ranking": None},
}
j_agree = _check_cross_surface_parity(agree_results)
chk(len(j_agree) == 0,
    "no parity failures when both surfaces agree on transfer presence")

# Mismatch: cli has transfer, http does not
mismatch_results = {
    "cli":  {"intent": "transfer_advice", "outcome": "ok", "supported": True,
             "transfer": {"player_out": "X"}, "chip": None, "fixture_run": None,
             "differential": None, "captain": None, "comparison": None,
             "captain_ranking": None},
    "http": {"intent": "transfer_advice", "outcome": "ok", "supported": True,
             "transfer": None, "chip": None, "fixture_run": None,
             "differential": None, "captain": None, "comparison": None,
             "captain_ranking": None},
}
j_mismatch = _check_cross_surface_parity(mismatch_results)
chk(any("transfer" in f for f in j_mismatch),
    "catches transfer presence mismatch between cli and http",
    str(j_mismatch))

# Mismatch: cli has differential, http does not
diff_mismatch = {
    "cli":  {"intent": "differential_picks", "outcome": "ok", "supported": True,
             "differential": {"ownership_threshold": 15.0, "top_n": 5, "picks": []},
             "transfer": None, "chip": None, "fixture_run": None,
             "captain": None, "comparison": None, "captain_ranking": None},
    "http": {"intent": "differential_picks", "outcome": "ok", "supported": True,
             "differential": None,
             "transfer": None, "chip": None, "fixture_run": None,
             "captain": None, "comparison": None, "captain_ranking": None},
}
j_diff_mismatch = _check_cross_surface_parity(diff_mismatch)
chk(any("differential" in f for f in j_diff_mismatch),
    "catches differential presence mismatch between cli and http",
    str(j_diff_mismatch))

# Single surface — no parity check
single = {"cli": {"intent": "ok", "outcome": "ok", "supported": True,
                  "transfer": None, "chip": None, "fixture_run": None,
                  "differential": None, "captain": None, "comparison": None,
                  "captain_ranking": None}}
j_single = _check_cross_surface_parity(single)
chk(len(j_single) == 0,
    "no parity failures for single surface")


# ---------------------------------------------------------------------------
# Section K: Full validation run -- all 31 scenarios PASS
# ---------------------------------------------------------------------------

print("\n-- K: Full validation run --")

results = run_all_scenarios()

total = len(results)
passed = sum(1 for r in results if r["pass"])
failed = total - passed

chk(total == 31,
    f"corpus has 31 scenarios (got {total})")
chk(failed == 0,
    f"all 31 scenarios pass ({failed} failed)")

if failed > 0:
    for r in results:
        if not r["pass"]:
            print(f"    FAILED: {r['id']}")
            for f_msg in r["failures"]:
                print(f"      {f_msg}")

# Spot-check specific scenarios
s17_result = next((r for r in results if r["id"] == "transfer_advice_direct"), None)
if s17_result:
    chk(s17_result["pass"],
        "#17 transfer_advice_direct passes")
    # Check that transfer metadata is present on both surfaces
    cli_sr = s17_result["surface_results"].get("cli", {})
    http_sr = s17_result["surface_results"].get("http", {})
    chk(cli_sr.get("transfer") is not None,
        "#17 transfer_advice_direct CLI has transfer metadata")
    chk(http_sr.get("transfer") is not None,
        "#17 transfer_advice_direct HTTP has transfer metadata")

s30_result = next((r for r in results if r["id"] == "transfer_followup_det"), None)
if s30_result:
    chk(s30_result["pass"],
        "#30 transfer_followup_det passes")
    sess_cli_sr = s30_result["surface_results"].get("session_cli", {})
    chk(sess_cli_sr.get("resolver_source") == "transfer_followup",
        "#30 session_cli resolver_source == 'transfer_followup'")

s31_result = next((r for r in results if r["id"] == "differential_picks_structured"), None)
if s31_result:
    chk(s31_result["pass"],
        "#31 differential_picks_structured passes")
    cli_sr31 = s31_result["surface_results"].get("cli", {})
    chk(cli_sr31.get("differential") is not None,
        "#31 CLI differential is non-None")
    chk(cli_sr31.get("intent") == "differential_picks",
        "#31 CLI intent == 'differential_picks'")
    chk(cli_sr31.get("outcome") == "ok",
        "#31 CLI outcome == 'ok'")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
print(f"Phase 7j tests: {_PASS} passed, {_FAIL} failed")
print(f"{'='*60}")

if __name__ == "__main__" or True:
    sys.exit(0 if _FAIL == 0 else 1)
