#!/usr/bin/env python3
"""
run_phase1f_tests.py
=====================
Standalone validator for fpl_tool_contract Phase 1f — tool-contract layer.

Run from the fpl-tool-contract/ directory:
    python3 run_phase1f_tests.py

No pytest or network dependency.

Suites
------
A.  Import smoke                                            (3 assertions)
B.  tool_resolve_player — status "ok"                      (7 assertions)
C.  tool_resolve_player — status "ambiguous"               (4 assertions)
D.  tool_resolve_player — status "not_found"               (3 assertions)
E.  tool_get_player_summary — status "ok" + enrichment     (7 assertions)
F.  tool_get_player_summary — ambiguous / not_found        (3 assertions)
G.  tool_get_current_gameweek — ok / not_found / edge      (5 assertions)
H.  Structured output contract                             (4 assertions)
I.  Public surface guard                                    (3 assertions)
──────────────────────────────────────────────────────────────────────────
Total                                                      (39 assertions)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_PKG = Path(__file__).parent
for _p in [
    _PKG,
    _PKG.parent / "fpl-data-core",
    _PKG.parent / "fpl-api-client",
    _PKG.parent / "fpl-player-registry",
    _PKG.parent / "fpl-query-tools",
]:
    sys.path.insert(0, str(_p))

from fpl_tool_contract import (  # noqa: E402
    tool_get_current_gameweek,
    tool_get_player_summary,
    tool_resolve_player,
)

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0
_failures: list[str] = []


def ok(label: str) -> None:
    global _passed
    _passed += 1
    print(f"  ✓  {label}")


def fail(label: str, detail: str = "") -> None:
    global _failed
    _failed += 1
    _failures.append(f"{label}: {detail}")
    print(f"  ✗  {label}")
    if detail:
        print(f"       {detail}")


def check(condition: bool, label: str, detail: str = "") -> None:
    ok(label) if condition else fail(label, detail)


def section(title: str) -> None:
    print(f"\n{'─' * 66}")
    print(f"  {title}")
    print(f"{'─' * 66}")


# ---------------------------------------------------------------------------
# Fixture bootstrap (raw FPL-style elements with "team" key)
# ---------------------------------------------------------------------------

BOOTSTRAP = {
    "elements": [
        {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
         "web_name": "Haaland",   "team": 13, "team_code": 43, "element_type": 4,
         "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
         "form": "8.0", "expected_goals": "1.50", "expected_assists": "0.20",
         "expected_goal_involvements": "1.70"},
        {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
         "web_name": "Salah",     "team": 14, "team_code": 1,  "element_type": 3,
         "status": "a", "now_cost": 135, "selected_by_percent": "64.1",
         "form": "9.5", "expected_goals": "0.90", "expected_assists": "0.55",
         "expected_goal_involvements": "1.45"},
        {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
         "web_name": "Saka",      "team": 1,  "team_code": 3,  "element_type": 3,
         "status": "d", "now_cost": 100, "selected_by_percent": "35.0",
         "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
         "expected_goal_involvements": "0.85"},
        {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
         "web_name": "De Bruyne", "team": 13, "team_code": 43, "element_type": 3,
         "status": "i", "now_cost": 105, "selected_by_percent": "14.2",
         "form": "0.0", "expected_goals": "0.20", "expected_assists": "0.40",
         "expected_goal_involvements": "0.60"},
        # Duplicate web_name pair
        {"id": 6,  "first_name": "Adam",    "second_name": "Johnson",
         "web_name": "Johnson",   "team": 8,  "team_code": 8,  "element_type": 3,
         "status": "a", "now_cost": 50, "selected_by_percent": "0.5",
         "form": "2.0", "expected_goals": "0.10", "expected_assists": "0.05",
         "expected_goal_involvements": "0.15"},
        {"id": 7,  "first_name": "Glen",    "second_name": "Johnson",
         "web_name": "Johnson",   "team": 11, "team_code": 12, "element_type": 2,
         "status": "a", "now_cost": 45, "selected_by_percent": "0.3",
         "form": "1.5", "expected_goals": "0.05", "expected_assists": "0.02",
         "expected_goal_involvements": "0.07"},
    ],
    "teams": [
        {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
        {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
        {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
        {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
        {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
    ],
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
}

BS = BOOTSTRAP   # short alias


# ===========================================================================
# Suite A — Import smoke
# ===========================================================================

section("A. Import smoke")

import fpl_tool_contract as _pkg  # noqa: E402

check(_pkg is not None, "A1  fpl_tool_contract imports cleanly")
check(
    all(hasattr(_pkg, n) for n in (
        "tool_resolve_player", "tool_get_player_summary",
        "tool_get_current_gameweek"
    )),
    "A2  all 3 tool functions present",
)
check(all(callable(getattr(_pkg, n)) for n in _pkg.__all__), "A3  all exports callable")


# ===========================================================================
# Suite B — tool_resolve_player: "ok"
# ===========================================================================

section("B. tool_resolve_player — status 'ok'")

r = tool_resolve_player("Haaland", BS)
check(isinstance(r, dict), "B1  returns dict")
check(r.get("status") == "ok", "B2  status == 'ok'")

required_ok = {"status", "player_id", "web_name", "name",
               "team", "team_short", "position", "status_label",
               "resolved_via", "query"}
check(required_ok.issubset(r.keys()), "B3  all required ok-keys present",
      f"missing: {required_ok - r.keys()}")

check(r["resolved_via"] == "web_name" and r["player_id"] == 1,
      "B4  resolved_via='web_name', player_id=1 for 'Haaland'")

r_id = tool_resolve_player(2, BS)
check(r_id["resolved_via"] == "id" and r_id["player_id"] == 2,
      "B5  resolved_via='id' for numeric query 2")

r_alias = tool_resolve_player("KDB", BS)
check(r_alias["status"] == "ok" and r_alias["resolved_via"] == "alias"
      and r_alias["player_id"] == 4,
      "B6  alias 'KDB' → ok, resolved_via='alias', player_id=4")

r_el = tool_resolve_player("el Vikingo", BS)
check(r_el["query"] == "el Vikingo" and r_el["player_id"] == 1,
      "B7  original query preserved in output")


# ===========================================================================
# Suite C — tool_resolve_player: "ambiguous"
# ===========================================================================

section("C. tool_resolve_player — status 'ambiguous'")

r_amb = tool_resolve_player("Johnson", BS)
check(r_amb["status"] == "ambiguous",  "C1  'Johnson' → ambiguous")
check({"status", "query", "message"}.issubset(r_amb.keys()),
      "C2  ambiguous result has status+query+message")
check(len(r_amb["message"]) > 10, "C3  ambiguous message is non-trivial")
check(r_amb["query"] == "Johnson",     "C4  query field preserved")


# ===========================================================================
# Suite D — tool_resolve_player: "not_found"
# ===========================================================================

section("D. tool_resolve_player — status 'not_found'")

r_nf = tool_resolve_player("Zidane", BS)
check(r_nf["status"] == "not_found",  "D1  'Zidane' → not_found")
check({"status", "query", "message"}.issubset(r_nf.keys()),
      "D2  not_found result has status+query+message")
check(tool_resolve_player(99, BS)["status"] == "not_found",
      "D3  absent id 99 → not_found")


# ===========================================================================
# Suite E — tool_get_player_summary: "ok" + enrichment
# ===========================================================================

section("E. tool_get_player_summary — status 'ok' + enrichment")

s = tool_get_player_summary(1, BS)
check(s["status"] == "ok", "E1  status == 'ok'")

required_summary = {"status", "player_id", "web_name", "name",
                    "team", "team_short", "position", "cost_m",
                    "status_label", "selected_by_percent",
                    "resolved_via", "query"}
check(required_summary.issubset(s.keys()), "E2  all summary ok-keys present",
      f"missing: {required_summary - s.keys()}")

check(s["cost_m"] == 14.5,           "E3  cost_m = 145/10 = 14.5")
check(s["status_label"] == "Available", "E4  Haaland status_label = Available")
check(tool_get_player_summary("Saka", BS)["status_label"] == "Doubtful",
      "E5  Saka status_label = Doubtful")
check(s["position"] == "FWD",        "E6  Haaland position = FWD")
check(s["team"] == "Manchester City" and s["team_short"] == "MCI",
      "E7  team name and short enriched from teams list")


# ===========================================================================
# Suite F — tool_get_player_summary: ambiguous / not_found
# ===========================================================================

section("F. tool_get_player_summary — ambiguous / not_found")

check(tool_get_player_summary("Johnson", BS)["status"] == "ambiguous",
      "F1  'Johnson' → ambiguous in summary too")
check(tool_get_player_summary("Cantona", BS)["status"] == "not_found",
      "F2  'Cantona' → not_found")
f3 = tool_get_player_summary("Johnson", BS)
check("message" in f3 and len(f3["message"]) > 10,
      "F3  ambiguous summary has non-trivial message")


# ===========================================================================
# Suite G — tool_get_current_gameweek
# ===========================================================================

section("G. tool_get_current_gameweek — ok / not_found / edge")

gw = tool_get_current_gameweek(BS)
check(gw["status"] == "ok" and gw["gameweek"] == 28,
      "G1  is_current GW28 → ok, gameweek=28")

bs_nc = copy.deepcopy(BOOTSTRAP)
for ev in bs_nc["events"]:
    ev["is_current"] = False
gw2 = tool_get_current_gameweek(bs_nc)
check(gw2["status"] == "ok" and gw2["gameweek"] == 29,
      "G2  no is_current, is_next GW29 → ok, gameweek=29")

bs_none = {"events": [{"id": 1, "is_current": False, "is_next": False}]}
check(tool_get_current_gameweek(bs_none)["status"] == "not_found",
      "G3  no flags → not_found")

check(tool_get_current_gameweek({})["status"] == "not_found",
      "G4  empty dict → not_found (no network call)")

check(set(gw.keys()) == {"status", "gameweek"},
      "G5  ok result has exactly status+gameweek keys (clean contract)")


# ===========================================================================
# Suite H — Structured output contract
# ===========================================================================

section("H. Structured output contract")

_all_results = [
    tool_resolve_player("Haaland", BS),
    tool_resolve_player("Johnson", BS),
    tool_resolve_player("Zidane",  BS),
    tool_get_player_summary(1, BS),
    tool_get_current_gameweek(BS),
]
check(all("status" in r for r in _all_results),
      "H1  every result has a 'status' key")

_valid_statuses = {"ok", "ambiguous", "not_found"}
check(all(r["status"] in _valid_statuses for r in _all_results),
      "H2  all status values are from the defined vocabulary")

r1 = tool_get_player_summary("Haaland", BS)
r2 = tool_get_player_summary("Haaland", BS)
check(r1 == r2, "H3  identical inputs → identical outputs (deterministic)")

non_ok = [tool_resolve_player("Johnson", BS), tool_resolve_player("Zidane", BS)]
leak_free = all(
    "player_id" not in r and "position" not in r and "cost_m" not in r
    for r in non_ok
)
check(leak_free, "H4  player fields absent from non-ok results")


# ===========================================================================
# Suite I — Public surface guard
# ===========================================================================

section("I. Public surface guard")

check(
    set(_pkg.__all__) == {
        "tool_resolve_player", "tool_get_player_summary",
        "tool_get_current_gameweek",
    },
    "I1  __all__ contains exactly the 3 Phase 1f exports",
)
check(not hasattr(_pkg, "_resolve_with_status"),
      "I2  _resolve_with_status not leaked into surface")
check(len(_pkg.__all__) == 3,
      "I3  exactly 3 tools exported (no scope creep)")


# ===========================================================================
# Summary
# ===========================================================================

total = _passed + _failed
print(f"\n{'═' * 66}")
print(f"  Phase 1f standalone validator")
print(f"  {_passed}/{total} assertions passed", "✓ PASS" if _failed == 0 else "✗ FAIL")
if _failures:
    print(f"\n  Failures:")
    for f in _failures:
        print(f"    • {f}")
print(f"{'═' * 66}")

sys.exit(0 if _failed == 0 else 1)


