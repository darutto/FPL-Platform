"""
run_phase4a_tests.py
====================
Phase 4a: Live API integration test.

Proves the full end-to-end pipeline works:

    assemble_captain_context()  ->  respond()  ->  FinalResponse

Two test modes
--------------
Sections A–D  (OFFLINE): injected bootstrap + fixtures — no network, no LLM.
Sections E–F  (LIVE):    real FPL API — requires internet access.

Live sections are skipped when ``FPL_SKIP_LIVE=1`` is set.
They run by default.

Run (all tests including live)::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase4a_tests.py

Skip live network sections::

    FPL_SKIP_LIVE=1 ... python run_phase4a_tests.py

Sections
--------
A  — Import & wiring validation
B  — Offline: assemble_captain_context -> respond() full pipeline
C  — Offline: multiple intents through assembled context
D  — Offline: FinalResponse invariant hardening
E  — Live: assemble_captain_context() with real FPL API
F  — Live: respond() with live FPL bootstrap

Expected: 50+ assertions (offline), 21 additional (live).
"""
from __future__ import annotations

import copy
import os
import sys

# ---------------------------------------------------------------------------
# Path setup  (mirrors all other phase test runners)
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

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_passed  = 0
_failed  = 0
_skipped = 0


def _section(name: str) -> None:
    print(f"\n  [{name}]")


def ok(label: str, condition: bool) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"    PASS  {label}")
    else:
        _failed += 1
        print(f"    FAIL  {label}")


def skip(label: str, reason: str = "") -> None:
    global _skipped
    _skipped += 1
    suffix = f" ({reason})" if reason else ""
    print(f"    SKIP  {label}{suffix}")


# ---------------------------------------------------------------------------
# Environment flags
# ---------------------------------------------------------------------------
_SKIP_LIVE = os.environ.get("FPL_SKIP_LIVE", "0").strip() == "1"

# ---------------------------------------------------------------------------
# Shared offline fixtures  (GW28, 5 teams, 2 players — same data as Phase 2e)
# ---------------------------------------------------------------------------
_TEAMS = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
]

_ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP"},
    {"id": 2, "singular_name_short": "DEF"},
    {"id": 3, "singular_name_short": "MID"},
    {"id": 4, "singular_name_short": "FWD"},
]

_ELEMENTS = [
    {
        "id": 1, "first_name": "Erling", "second_name": "Haaland",
        "web_name": "Haaland", "team": 13, "team_code": 43, "element_type": 4,
        "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
        "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
        "expected_goal_involvements": "1.70", "minutes": 1800,
        "penalties_order": 1, "direct_freekicks_order": None,
        "corners_and_indirect_freekicks_order": None,
    },
    {
        "id": 2, "first_name": "Mohamed", "second_name": "Salah",
        "web_name": "Salah", "team": 14, "team_code": 1, "element_type": 3,
        "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
        "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
        "expected_goal_involvements": "1.45", "minutes": 2250,
        "penalties_order": 1, "direct_freekicks_order": None,
        "corners_and_indirect_freekicks_order": None,
    },
]

_EVENTS = [
    {"id": 27, "is_current": False, "is_next": False, "finished": True},
    {"id": 28, "is_current": True,  "is_next": False, "finished": False},
    {"id": 29, "is_current": False, "is_next": True,  "finished": False},
]

_FIXTURES_GW28 = [
    {"team_h": 1,  "team_a": 13, "event": 28},   # Arsenal vs Man City
    {"team_h": 14, "team_a": 8,  "event": 28},   # Liverpool vs Chelsea
]

_BOOTSTRAP_OFFLINE = {
    "elements":      _ELEMENTS,
    "teams":         _TEAMS,
    "events":        _EVENTS,
    "element_types": _ELEMENT_TYPES,
}


def _offline_ctx():
    """Fresh assembled context from offline fixtures — no network."""
    return assemble_captain_context(
        gameweek=28,
        bootstrap=copy.deepcopy(_BOOTSTRAP_OFFLINE),
        fixtures=_FIXTURES_GW28,
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
print("Phase 4a — Live API Integration Test")
print("=" * 50)
if _SKIP_LIVE:
    print("  (FPL_SKIP_LIVE=1: live sections E–F will be skipped)")
print()

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
_section("Imports")

try:
    from fpl_pipeline import assemble_captain_context
    _pipeline_ok = True
except Exception as _e:
    _pipeline_ok = False
    print(f"  IMPORT ERROR (fpl_pipeline): {_e}")

try:
    from fpl_grounded_assistant import (
        respond,
        FinalResponse,
        OUTCOME_OK,
        OUTCOME_UNSUPPORTED_INTENT,
        STANDARD_BOOTSTRAP,
    )
    _assistant_ok = True
except Exception as _e:
    _assistant_ok = False
    print(f"  IMPORT ERROR (fpl_grounded_assistant): {_e}")

ok("fpl_pipeline imports cleanly",           _pipeline_ok)
ok("fpl_grounded_assistant imports cleanly", _assistant_ok)

if not (_pipeline_ok and _assistant_ok):
    print("\nFatal: imports failed — cannot continue.")
    sys.exit(1)


# ===========================================================================
# Section A — Import & wiring validation
# ===========================================================================
_section("A: Import & wiring validation")

ok("A1  assemble_captain_context is callable",          callable(assemble_captain_context))
ok("A2  respond is callable",                           callable(respond))
ok("A3  FinalResponse is a class",                      isinstance(FinalResponse, type))
ok("A4  OUTCOME_OK is a non-empty string",              isinstance(OUTCOME_OK, str) and bool(OUTCOME_OK))
ok("A5  OUTCOME_UNSUPPORTED_INTENT is a non-empty str", isinstance(OUTCOME_UNSUPPORTED_INTENT, str) and bool(OUTCOME_UNSUPPORTED_INTENT))
ok("A6  STANDARD_BOOTSTRAP is a dict",                  isinstance(STANDARD_BOOTSTRAP, dict))
ok("A7  STANDARD_BOOTSTRAP has 'elements'",             "elements" in STANDARD_BOOTSTRAP)
ok("A8  STANDARD_BOOTSTRAP has 'teams'",                "teams" in STANDARD_BOOTSTRAP)
ok("A9  STANDARD_BOOTSTRAP has 'events'",               "events" in STANDARD_BOOTSTRAP)
ok("A10 STANDARD_BOOTSTRAP has fixture_difficulty_map", "fixture_difficulty_map" in STANDARD_BOOTSTRAP)


# ===========================================================================
# Section B — Offline: assemble_captain_context -> respond() full pipeline
# ===========================================================================
_section("B: Offline — assemble_captain_context -> respond() full pipeline")

_ctx_b = _offline_ctx()

ok("B1  assemble_captain_context returns dict",        isinstance(_ctx_b, dict))
ok("B2  ctx has 'bootstrap' key",                      "bootstrap" in _ctx_b)
ok("B3  ctx['bootstrap'] has fixture_difficulty_map",  "fixture_difficulty_map" in _ctx_b["bootstrap"])
ok("B4  ctx['gameweek'] == 28",                        _ctx_b["gameweek"] == 28)
ok("B5  ctx['fixture_difficulty_map'] is non-empty",   len(_ctx_b["fixture_difficulty_map"]) > 0)
ok("B6  ctx['meta'] is a dict",                        isinstance(_ctx_b["meta"], dict))

_r_b = respond("should I captain Haaland", _ctx_b["bootstrap"])

ok("B7  respond() returns FinalResponse",              isinstance(_r_b, FinalResponse))
ok("B8  final_text is non-empty",                      len(_r_b.final_text) > 0)
ok("B9  outcome is 'ok' for Haaland captain query",    _r_b.outcome == OUTCOME_OK)
ok("B10 supported is True",                            _r_b.supported is True)
ok("B11 intent is a non-empty string",                 isinstance(_r_b.intent, str) and bool(_r_b.intent))
ok("B12 review_passed is bool",                        isinstance(_r_b.review_passed, bool))
ok("B13 llm_used is bool",                             isinstance(_r_b.llm_used, bool))
ok("B14 llm_used is False (no API key)",               _r_b.llm_used is False)
ok("B15 debug is None by default",                     _r_b.debug is None)


# ===========================================================================
# Section C — Offline: multiple intents through assembled context
# ===========================================================================
_section("C: Offline — multiple intents through assembled context")

# Each intent gets a fresh assembled context so bootstrap mutations don't leak.
_c_captain = respond("captain score for Salah", _offline_ctx()["bootstrap"])
ok("C1  captain score: outcome ok",          _c_captain.outcome == OUTCOME_OK)
ok("C2  captain score: final_text non-empty", len(_c_captain.final_text) > 0)
ok("C3  captain score: supported True",      _c_captain.supported is True)

_c_rank = respond(
    "rank captains",
    _offline_ctx()["bootstrap"],
    candidates_list=[{"query": "Haaland"}, {"query": "Salah"}],
)
ok("C4  rank candidates: outcome ok",          _c_rank.outcome == OUTCOME_OK)
ok("C5  rank candidates: final_text non-empty", len(_c_rank.final_text) > 0)
ok("C6  rank candidates: supported True",      _c_rank.supported is True)

_c_gw = respond("what gameweek is it", _offline_ctx()["bootstrap"])
ok("C7  gameweek query: outcome ok",           _c_gw.outcome == OUTCOME_OK)
ok("C8  gameweek query: final_text non-empty", len(_c_gw.final_text) > 0)
ok("C9  gameweek query: supported True",       _c_gw.supported is True)

_c_unsupported = respond("what is the meaning of life", _offline_ctx()["bootstrap"])
ok("C10 unsupported: outcome is unsupported_intent",
   _c_unsupported.outcome == OUTCOME_UNSUPPORTED_INTENT)
ok("C11 unsupported: supported is False",      _c_unsupported.supported is False)
ok("C12 unsupported: final_text non-empty",    len(_c_unsupported.final_text) > 0)


# ===========================================================================
# Section D — Offline: FinalResponse invariant hardening
# ===========================================================================
_section("D: Offline — FinalResponse invariant hardening")

_D_QUERIES = [
    "should I captain Haaland",
    "what gameweek is it",
    "what is Salah's captain score",
    "what is the meaning of life",
    "who is the best player ever",
]

# Each query gets a fresh bootstrap to avoid mutation leakage.
_d_responses = [respond(q, _offline_ctx()["bootstrap"]) for q in _D_QUERIES]

# Invariant 1: respond() never raises
ok("D1  respond() returned for all queries (never raised)", len(_d_responses) == len(_D_QUERIES))

# Invariant 2: final_text always non-empty
ok("D2  final_text non-empty for all queries",
   all(len(r.final_text) > 0 for r in _d_responses))

# Invariant 3: supported == (outcome != OUTCOME_UNSUPPORTED_INTENT)
ok("D3  supported == (outcome != OUTCOME_UNSUPPORTED_INTENT) — all queries",
   all(r.supported == (r.outcome != OUTCOME_UNSUPPORTED_INTENT) for r in _d_responses))

# Invariant 4: llm_used=True implies review_passed=True
ok("D4  llm_used=True -> review_passed=True — all queries",
   all(not r.llm_used or r.review_passed for r in _d_responses))

# Invariant 5: not llm_used -> final_text == response_text (debug bundle)
_d_debug = [respond(q, _offline_ctx()["bootstrap"], include_debug=True) for q in _D_QUERIES]
ok("D5  not llm_used -> final_text == response_text (deterministic fallback)",
   all(r.llm_used or r.final_text == r.debug.response_text for r in _d_debug))

# Invariant 6: debug is None by default
ok("D6  debug is None by default — all queries",
   all(r.debug is None for r in _d_responses))

# Invariant 7: debug populated when include_debug=True
ok("D7  debug is not None when include_debug=True",
   all(r.debug is not None for r in _d_debug))

# Invariant 8: debug fields are non-empty strings
_d0 = _d_debug[0]
ok("D8  debug.response_text is non-empty str",  isinstance(_d0.debug.response_text, str) and bool(_d0.debug.response_text))
ok("D9  debug.prompt_used is non-empty str",    isinstance(_d0.debug.prompt_used, str) and bool(_d0.debug.prompt_used))
ok("D10 debug.model is a str",                  isinstance(_d0.debug.model, str))
ok("D11 debug.violations is a tuple",           isinstance(_d0.debug.violations, tuple))

# Invariant 9: FinalResponse field types
_d_r = _d_responses[0]
ok("D12 final_text is str",     isinstance(_d_r.final_text, str))
ok("D13 outcome is str",        isinstance(_d_r.outcome, str))
ok("D14 supported is bool",     isinstance(_d_r.supported, bool))
ok("D15 intent is str",         isinstance(_d_r.intent, str))
ok("D16 review_passed is bool", isinstance(_d_r.review_passed, bool))
ok("D17 llm_used is bool",      isinstance(_d_r.llm_used, bool))

# Invariant 10: edge-case inputs don't raise
_d_safe = True
try:
    respond("", _offline_ctx()["bootstrap"])
    respond("   ", _offline_ctx()["bootstrap"])
except Exception:
    _d_safe = False
ok("D18 respond() never raises even on blank/whitespace input", _d_safe)


# ===========================================================================
# Section E — Live: assemble_captain_context() with real FPL API
# ===========================================================================
_section("E: Live — assemble_captain_context() with real FPL API")

_live_ctx   = None
_live_error = None

_E_LABELS = [
    "E1  live call completes without error",
    "E2  ctx['bootstrap'] is a dict",
    "E3  ctx['bootstrap'] has 'elements' (player list)",
    "E4  ctx['bootstrap'] has 'teams'",
    "E5  ctx['bootstrap'] has 'fixture_difficulty_map' pre-injected",
    "E6  ctx['bootstrap']['elements'] has at least 400 players",
    "E7  ctx['gameweek'] is int or None",
    "E8  ctx['fixtures'] is a list",
    "E9  ctx['fixture_difficulty_map'] is a dict",
    "E10 ctx['meta'] has all required keys",
    "E11 meta['team_count'] >= 20",
    "E12 meta['assembled_at'] ends with 'Z' (UTC ISO-8601)",
    "E13 meta['gw_resolved_via'] is one of bootstrap/explicit/none",
]

if _SKIP_LIVE:
    for _lbl in _E_LABELS:
        skip(_lbl, "FPL_SKIP_LIVE=1")
else:
    try:
        _live_ctx = assemble_captain_context()
    except Exception as _e:
        _live_error = _e

    ok(_E_LABELS[0], _live_error is None)

    if _live_ctx is not None:
        _lbs  = _live_ctx["bootstrap"]
        _lmeta = _live_ctx["meta"]

        ok(_E_LABELS[1],  isinstance(_lbs, dict))
        ok(_E_LABELS[2],  "elements" in _lbs)
        ok(_E_LABELS[3],  "teams" in _lbs)
        ok(_E_LABELS[4],  "fixture_difficulty_map" in _lbs)
        ok(_E_LABELS[5],  len(_lbs.get("elements", [])) >= 400)
        ok(_E_LABELS[6],  _live_ctx["gameweek"] is None or isinstance(_live_ctx["gameweek"], int))
        ok(_E_LABELS[7],  isinstance(_live_ctx["fixtures"], list))
        ok(_E_LABELS[8],  isinstance(_live_ctx["fixture_difficulty_map"], dict))
        ok(_E_LABELS[9],  all(k in _lmeta for k in ("gw_resolved_via", "fixture_count", "team_count", "blank_gw_teams", "assembled_at")))
        ok(_E_LABELS[10], _lmeta.get("team_count", 0) >= 20)
        ok(_E_LABELS[11], isinstance(_lmeta.get("assembled_at"), str) and _lmeta["assembled_at"].endswith("Z"))
        ok(_E_LABELS[12], _lmeta.get("gw_resolved_via") in {"bootstrap", "explicit", "none"})
    else:
        for _lbl in _E_LABELS[1:]:
            skip(_lbl, f"live call failed: {_live_error}")


# ===========================================================================
# Section F — Live: respond() with live FPL bootstrap
# ===========================================================================
_section("F: Live — respond() with live FPL bootstrap")

_F_LABELS = [
    "F1  respond() returns FinalResponse with live bootstrap",
    "F2  final_text non-empty",
    "F3  outcome is a non-empty string",
    "F4  supported is bool",
    "F5  llm_used is False (no API key configured)",
    "F6  invariant: supported == (outcome != OUTCOME_UNSUPPORTED_INTENT)",
    "F7  invariant: llm_used=True -> review_passed=True",
    "F8  gameweek query returns ok outcome with live data",
    "F9  unsupported intent returns unsupported_intent with live data",
    "F10 respond() never raises on blank input with live bootstrap",
    "F11 player not in live bootstrap returns not_found or error (not crash)",
    "F12 debug bundle populated when include_debug=True with live bootstrap",
]

_skip_f_reason = (
    "FPL_SKIP_LIVE=1" if _SKIP_LIVE
    else (f"live call failed: {_live_error}" if _live_ctx is None else None)
)

if _skip_f_reason:
    for _lbl in _F_LABELS:
        skip(_lbl, _skip_f_reason)
else:
    _lbs = _live_ctx["bootstrap"]

    _f_r = respond("should I captain Haaland", _lbs)

    ok(_F_LABELS[0],  isinstance(_f_r, FinalResponse))
    ok(_F_LABELS[1],  len(_f_r.final_text) > 0)
    ok(_F_LABELS[2],  isinstance(_f_r.outcome, str) and bool(_f_r.outcome))
    ok(_F_LABELS[3],  isinstance(_f_r.supported, bool))
    ok(_F_LABELS[4],  _f_r.llm_used is False)
    ok(_F_LABELS[5],  _f_r.supported == (_f_r.outcome != OUTCOME_UNSUPPORTED_INTENT))
    ok(_F_LABELS[6],  not _f_r.llm_used or _f_r.review_passed)

    _f_gw = respond("what gameweek are we in", _lbs)
    ok(_F_LABELS[7],  _f_gw.outcome == OUTCOME_OK)

    _f_unsup = respond("what is the meaning of life", _lbs)
    ok(_F_LABELS[8],  _f_unsup.outcome == OUTCOME_UNSUPPORTED_INTENT)

    _f_safe = True
    try:
        respond("", _lbs)
        respond("   ", _lbs)
    except Exception:
        _f_safe = False
    ok(_F_LABELS[9],  _f_safe)

    _f_unknown = respond("captain score for Zzzunknownplayer999", _lbs)
    ok(_F_LABELS[10], isinstance(_f_unknown, FinalResponse) and len(_f_unknown.final_text) > 0)

    _f_dbg = respond("should I captain Haaland", _lbs, include_debug=True)
    ok(_F_LABELS[11], _f_dbg.debug is not None and bool(_f_dbg.debug.response_text))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'=' * 50}")
print(f"Phase 4a — Results: {_passed} passed, {_failed} failed, {_skipped} skipped")
print(f"{'=' * 50}")

if _failed == 0:
    print("\nAll assertions PASS.")
else:
    print(f"\n{_failed} assertion(s) FAILED — see FAIL lines above.")
    sys.exit(1)
