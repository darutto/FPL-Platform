"""
run_phase9a_tests.py
=====================
Phase 9a: Orchestrator context builder.

Sections
--------
A  build_orchestration_context_dict  — structural correctness on STANDARD_BOOTSTRAP
B  build_orchestration_context_dict  — DGW/BGW bootstraps
C  build_orchestration_context       — string output shape and grounding invariants
D  Degraded inputs                   — missing fields produce output, not errors
E  Regression                        — chip_advisor and existing backend unaffected

Run from packages/fpl-grounded-assistant::

    python run_phase9a_tests.py
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

from fpl_grounded_assistant.context_builder import (
    build_orchestration_context,
    build_orchestration_context_dict,
)
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DGW_BOOTSTRAP,
    BGW_BOOTSTRAP,
)

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
# Section A: dict output — STANDARD_BOOTSTRAP structural correctness
# ---------------------------------------------------------------------------

print("\n=== A: build_orchestration_context_dict — STANDARD_BOOTSTRAP ===")

ctx = build_orchestration_context_dict(STANDARD_BOOTSTRAP)

# A1-A3: top-level keys present
ok("gameweek"         in ctx, "A1: 'gameweek' key present")
ok("gw_type"          in ctx, "A2: 'gw_type' key present")
ok("players"          in ctx, "A3: 'players' key present")
ok("chip_signals"     in ctx, "A4: 'chip_signals' key present")
ok("fixture_schedule" in ctx, "A5: 'fixture_schedule' key present")

# A6-A8: gameweek section
gw = ctx["gameweek"]
ok(gw["current_gw"] == 28,                         "A6: current_gw == 28")
ok(gw["next_gw"] == 29,                             "A7: next_gw == 29")
ok("mid-season" in (gw["season_phase"] or ""),      "A8: season_phase contains 'mid-season'")

# A9-A11: gw_type section — STANDARD_BOOTSTRAP is normal
gwt = ctx["gw_type"]
ok(gwt["gw_type"] == "normal",    "A9: gw_type == 'normal'")
ok(gwt["dgw_count"] == 0,         "A10: dgw_count == 0")
ok(gwt["bgw_count"] == 0,         "A11: bgw_count == 0")

# A12-A16: players section
pl = ctx["players"]
ok("top_candidates" in pl,                          "A12: top_candidates key present")
ok("all_players" in pl,                             "A13: all_players key present")
ok(len(pl["top_candidates"]) >= 1,                  "A14: at least 1 top candidate")
# All candidates are MID/FWD
ok(all(p["position"] in ("MID", "FWD") for p in pl["top_candidates"]),
   "A15: all top candidates are MID or FWD")
# Candidates sorted by form desc
forms = [float(p["form"]) for p in pl["top_candidates"]]
ok(forms == sorted(forms, reverse=True),            "A16: top_candidates sorted by form desc")

# A17-A18: player data quality
first = pl["top_candidates"][0]
ok("web_name"   in first, "A17: candidate has web_name")
ok("team_short" in first, "A18: candidate has team_short")
ok("form"       in first, "A19: candidate has form")
ok("ownership"  in first, "A20: candidate has ownership")

# A21-A22: chip signals present
cs = ctx["chip_signals"]
ok("triple_captain" in cs, "A21: triple_captain signal present")
ok("bench_boost"    in cs, "A22: bench_boost signal present")
ok("wildcard"       in cs, "A23: wildcard signal present")
ok("free_hit"       in cs, "A24: free_hit signal present")

# A25-A27: chip signal shapes
if cs.get("triple_captain"):
    ok("recommendation" in cs["triple_captain"], "A25: TC has recommendation")
    ok("top_score"      in cs["triple_captain"], "A26: TC has top_score")
    ok("top_player"     in cs["triple_captain"], "A27: TC has top_player")
else:
    print("  SKIP  A25-A27: TC signal None")

# A28-A29: fixture schedule populated
fs = ctx["fixture_schedule"]
ok(isinstance(fs, dict),    "A28: fixture_schedule is a dict")
ok(len(fs) > 0,             "A29: fixture_schedule has entries")

# A30: schedule horizon covers 3 GWs
sample_team = next(iter(fs.values()), [])
ok(len(sample_team) == 3,   "A30: schedule has 3 GW entries per team")

# ---------------------------------------------------------------------------
# Section B: dict output — DGW / BGW bootstraps
# ---------------------------------------------------------------------------

print("\n=== B: build_orchestration_context_dict — DGW/BGW ===")

ctx_dgw = build_orchestration_context_dict(DGW_BOOTSTRAP)
ctx_bgw = build_orchestration_context_dict(BGW_BOOTSTRAP)

ok(ctx_dgw["gw_type"]["gw_type"] == "double", "B1: DGW_BOOTSTRAP gw_type == 'double'")
ok(ctx_dgw["gw_type"]["dgw_count"] >= 1,      "B2: DGW dgw_count >= 1")
ok(ctx_bgw["gw_type"]["gw_type"] == "blank",  "B3: BGW_BOOTSTRAP gw_type == 'blank'")
ok(ctx_bgw["gw_type"]["bgw_count"] >= 1,      "B4: BGW bgw_count >= 1")

# Chip signal follows GW type
if ctx_dgw["chip_signals"].get("free_hit"):
    ok("favorable" in (ctx_dgw["chip_signals"]["free_hit"]["recommendation"] or ""),
       "B5: DGW free_hit recommendation contains 'favorable'")
else:
    print("  SKIP  B5: DGW chip_signals.free_hit None")

# ---------------------------------------------------------------------------
# Section C: string output — shape and grounding invariants
# ---------------------------------------------------------------------------

print("\n=== C: build_orchestration_context — string output ===")

text = build_orchestration_context(STANDARD_BOOTSTRAP)

ok(isinstance(text, str),                  "C1: returns a string")
ok(len(text) > 100,                        "C2: non-trivial length (>100 chars)")
ok("=== FPL Data Context ===" in text,     "C3: contains header")
ok("[GAMEWEEK]" in text,                   "C4: GAMEWEEK section present")
ok("[GAMEWEEK TYPE]" in text,              "C5: GAMEWEEK TYPE section present")
ok("[PLAYERS]" in text,                    "C6: PLAYERS section present")
ok("[CHIP SIGNALS]" in text,              "C7: CHIP SIGNALS section present")
ok("[FIXTURE SCHEDULE" in text,            "C8: FIXTURE SCHEDULE section present")

# Grounding: real player names from STANDARD_BOOTSTRAP appear
ok("Haaland" in text,   "C9: player 'Haaland' appears in context")
ok("Salah"   in text,   "C10: player 'Salah' appears in context")
ok("GW28"    in text,   "C11: 'GW28' appears in context")

# Grounding: no hallucinated GW0
ok("GW0" not in text,   "C12: 'GW0' never appears in context")

# Teams from bootstrap appear in fixture schedule
ok("LIV" in text or "Liverpool" in text, "C13: Liverpool team present in context")
ok("MCI" in text or "Man City"  in text, "C14: Man City team present in context")

# DGW text for DGW bootstrap
text_dgw = build_orchestration_context(DGW_BOOTSTRAP)
ok("DOUBLE GAMEWEEK" in text_dgw, "C15: DGW bootstrap mentions 'DOUBLE GAMEWEEK'")

text_bgw = build_orchestration_context(BGW_BOOTSTRAP)
ok("BLANK GAMEWEEK" in text_bgw,  "C16: BGW bootstrap mentions 'BLANK GAMEWEEK'")

# ---------------------------------------------------------------------------
# Section D: degraded inputs — no fixture_difficulty_map, no team_fixtures, no events
# ---------------------------------------------------------------------------

print("\n=== D: degraded inputs — missing fields ===")

bare_bootstrap: dict = {
    "elements": STANDARD_BOOTSTRAP["elements"],
    "teams":    STANDARD_BOOTSTRAP["teams"],
    "events":   STANDARD_BOOTSTRAP["events"],
    # no fixture_difficulty_map, no team_fixtures
}

try:
    d_ctx = build_orchestration_context_dict(bare_bootstrap)
    ok(True, "D1: dict build does not raise with missing fixture fields")
    ok("players" in d_ctx, "D2: players section still populated")
except Exception as exc:
    ok(False, f"D1: raised {exc}")
    ok(False, "D2: (skipped)")

try:
    d_text = build_orchestration_context(bare_bootstrap)
    ok(isinstance(d_text, str) and len(d_text) > 50, "D3: string build does not raise with missing fixture fields")
    ok("Haaland" in d_text, "D4: player names still appear in degraded output")
except Exception as exc:
    ok(False, f"D3: raised {exc}")
    ok(False, "D4: (skipped)")

# Completely empty bootstrap
try:
    e_text = build_orchestration_context({})
    ok(isinstance(e_text, str), "D5: empty bootstrap returns a string (no crash)")
except Exception as exc:
    ok(False, f"D5: empty bootstrap raised {exc}")

# No events (GW unknown)
no_gw_bs = {**STANDARD_BOOTSTRAP, "events": []}
try:
    ng_text = build_orchestration_context(no_gw_bs)
    ok(isinstance(ng_text, str),  "D6: no-events bootstrap returns a string")
    ok("GW0" not in ng_text,      "D7: no 'GW0' with missing GW events")
    ok("unknown" in ng_text,      "D8: 'unknown' appears when GW not found")
except Exception as exc:
    ok(False, f"D6: raised {exc}")

# ---------------------------------------------------------------------------
# Section E: regression — chip_advisor and existing backend unaffected
# ---------------------------------------------------------------------------

print("\n=== E: regression — chip_advisor / existing backend ===")

try:
    from fpl_grounded_assistant.chip_advisor import get_chip_advice
    raw = get_chip_advice("bench_boost", STANDARD_BOOTSTRAP)
    ok(raw["status"] == "ok",             "E1: chip_advisor bench_boost still ok")
    ok("average_fdr_top10" in raw["signals"], "E2: BB signals unaffected")
except Exception as exc:
    ok(False, f"E1: chip_advisor raised {exc}")
    ok(False, "E2: (skipped)")

try:
    from fpl_grounded_assistant import respond
    r = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
    ok(r.intent == "captain_score",  "E3: captain_score intent unaffected")
    ok(r.outcome == "ok",            "E4: captain_score outcome == ok")
except Exception as exc:
    ok(False, f"E3: respond() raised {exc}")
    ok(False, "E4: (skipped)")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase 9a: {_pass}/{total} assertions passed.")
if _fail:
    print(f"          {_fail} FAILED.")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
