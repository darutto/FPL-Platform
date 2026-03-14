#!/usr/bin/env python3
"""
run_phase1e_tests.py
=====================
Standalone validator for fpl_query_tools Phase 1e — query composition layer.

Run from the fpl-query-tools/ directory:
    python3 run_phase1e_tests.py

No pytest or network dependency. Adds sibling package dirs to sys.path
automatically.

Suites
------
A.  Import smoke                                    (3 assertions)
B.  resolve_player_query — id resolution            (4 assertions)
C.  resolve_player_query — web_name resolution      (3 assertions)
D.  resolve_player_query — exact name resolution    (4 assertions)
E.  resolve_player_query — alias resolution         (4 assertions)
F.  resolve_player_query — miss / None              (3 assertions)
G.  get_player_summary — fields + enrichment        (8 assertions)
H.  get_player_summary — miss / edge cases          (3 assertions)
I.  get_current_gameweek_from_bootstrap             (5 assertions)
J.  Public surface guard                            (3 assertions)
──────────────────────────────────────────────────────────────────
Total                                              (40 assertions)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — add this package + all owned sibling packages
# ---------------------------------------------------------------------------
_PKG_DIR = Path(__file__).parent
for _p in [
    _PKG_DIR,
    _PKG_DIR.parent / "fpl-data-core",
    _PKG_DIR.parent / "fpl-api-client",
    _PKG_DIR.parent / "fpl-player-registry",
]:
    sys.path.insert(0, str(_p))

from fpl_query_tools import (  # noqa: E402
    get_current_gameweek_from_bootstrap,
    get_player_summary,
    resolve_player_query,
)
from fpl_player_registry import PlayerRecord  # noqa: E402

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
    print(f"\n{'─' * 62}")
    print(f"  {title}")
    print(f"{'─' * 62}")


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

TEAMS = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
]

PLAYERS = [
    {"id": 1,  "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",   "team_id": 13, "element_type": 4,
     "status": "a", "now_cost": 145, "selected_by_percent": "52.3"},
    {"id": 2,  "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",     "team_id": 14, "element_type": 3,
     "status": "a", "now_cost": 135, "selected_by_percent": "64.1"},
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",      "team_id": 1,  "element_type": 3,
     "status": "d", "now_cost": 100, "selected_by_percent": "35.0"},
    {"id": 4,  "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne", "team_id": 13, "element_type": 3,
     "status": "i", "now_cost": 105, "selected_by_percent": "14.2"},
    {"id": 5,  "first_name": "Ben",     "second_name": "Clarke",
     "web_name": "Clarke",    "team_id": 1,  "element_type": 2,
     "status": "a", "now_cost": 45,  "selected_by_percent": "1.2"},
    {"id": 6,  "first_name": "Adam",    "second_name": "Johnson",
     "web_name": "Johnson",   "team_id": 8,  "element_type": 3,
     "status": "a", "now_cost": 50},
    {"id": 7,  "first_name": "Glen",    "second_name": "Johnson",
     "web_name": "Johnson",   "team_id": 11, "element_type": 2,
     "status": "a", "now_cost": 45},
    {"id": 8,  "first_name": "Test",    "second_name": "Player",
     "web_name": "TPlayer",   "team_id": 1,  "element_type": 1,
     "status": "u"},
]

BOOTSTRAP = {
    "elements": PLAYERS,
    "teams":    TEAMS,
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
}

P, T = PLAYERS, TEAMS   # short aliases for brevity


# ===========================================================================
# Suite A — Import smoke
# ===========================================================================

section("A. Import smoke")

import fpl_query_tools as _pkg  # noqa: E402

check(_pkg is not None, "A1  fpl_query_tools imports cleanly")
check(
    all(hasattr(_pkg, n) for n in (
        "resolve_player_query", "get_player_summary",
        "get_current_gameweek_from_bootstrap"
    )),
    "A2  all 3 public functions present",
)
check(all(callable(getattr(_pkg, n)) for n in _pkg.__all__), "A3  all exports are callable")


# ===========================================================================
# Suite B — resolve_player_query: id
# ===========================================================================

section("B. resolve_player_query — id resolution")

r = resolve_player_query(1, P, T)
check(r is not None and r.id == 1 and r.web_name == "Haaland",
      "B1  int id=1 → Haaland")

r = resolve_player_query("2", P, T)
check(r is not None and r.id == 2, "B2  string '2' → Salah (id 2)")

check(isinstance(resolve_player_query(3, P, T), PlayerRecord),
      "B3  returns PlayerRecord instance")

check(resolve_player_query(99, P, T) is None, "B4  absent id=99 → None")


# ===========================================================================
# Suite C — resolve_player_query: web_name
# ===========================================================================

section("C. resolve_player_query — web_name resolution")

r = resolve_player_query("Saka", P, T)
check(r is not None and r.id == 3, "C1  'Saka' (exact) → id 3")

check(
    resolve_player_query("saka", P, T) is not None and
    resolve_player_query("SAKA", P, T) is not None,
    "C2  web_name lookup is case-insensitive",
)

check(resolve_player_query("Johnson", P, T) is None,
      "C3  ambiguous 'Johnson' → None")


# ===========================================================================
# Suite D — resolve_player_query: exact name
# ===========================================================================

section("D. resolve_player_query — exact name resolution")

r = resolve_player_query("De Bruyne", P, T)
check(r is not None and r.id == 4, "D1  second_name 'De Bruyne' → id 4")

r = resolve_player_query("Erling", P, T)
check(r is not None and r.id == 1, "D2  first_name 'Erling' → id 1")

check(resolve_player_query("de bruyne", P, T) is not None,
      "D3  case-insensitive exact name")

r = resolve_player_query("Clarke", P, T)
check(r is not None and r.id == 5, "D4  plain second_name 'Clarke' → id 5")


# ===========================================================================
# Suite E — resolve_player_query: alias
# ===========================================================================

section("E. resolve_player_query — alias resolution")

r = resolve_player_query("KDB", P, T)
check(r is not None and r.id == 4, "E1  alias 'KDB' → De Bruyne (id 4)")

r = resolve_player_query("el Vikingo", P, T)
check(r is not None and r.id == 1, "E2  alias 'el Vikingo' → Haaland (id 1)")

r = resolve_player_query("Mo", P, T)
check(r is not None and r.id == 2, "E3  alias 'Mo' → Salah (id 2)")

check(resolve_player_query("el Fantasma", P, T) is None,
      "E4  unknown alias → None")


# ===========================================================================
# Suite F — resolve_player_query: miss
# ===========================================================================

section("F. resolve_player_query — miss / None")

check(resolve_player_query(999, P, T) is None,
      "F1  absent id → None")
check(resolve_player_query("xyzzy_no_such_player", P, T) is None,
      "F2  gibberish query → None")
check(resolve_player_query("Haaland", [], T) is None,
      "F3  empty player list → None")


# ===========================================================================
# Suite G — get_player_summary: fields + enrichment
# ===========================================================================

section("G. get_player_summary — fields + enrichment")

result = get_player_summary("Haaland", P, T)
check(isinstance(result, dict), "G1  hit returns dict")

required = {"id", "name", "web_name", "team", "team_short", "position",
            "cost_m", "status", "selected_by_percent", "query_resolved_via"}
check(required.issubset(result.keys()), "G2  all required keys present")

fwd = get_player_summary(1, P, T)
mid = get_player_summary(4, P, T)
check(fwd["position"] == "FWD" and mid["position"] == "MID",
      "G3  element_type→position label correct (FWD, MID)")

check(result["cost_m"] == 14.5, "G4  cost_m = now_cost/10 (145 → 14.5)")

check(
    get_player_summary("Haaland", P, T)["status"] == "Available" and
    get_player_summary("Saka",    P, T)["status"] == "Doubtful"   and
    get_player_summary("De Bruyne", P, T)["status"] == "Injured",
    "G5  status labels correct (Available, Doubtful, Injured)",
)

h = get_player_summary(1, P, T)
check(h["team"] == "Manchester City" and h["team_short"] == "MCI",
      "G6  team name enriched from teams list")

check(h["query_resolved_via"] == "id",
      "G7  query_resolved_via='id' for numeric query")

kdb_s = get_player_summary("KDB", P, T)
check(kdb_s is not None and kdb_s["query_resolved_via"] == "alias",
      "G8  query_resolved_via='alias' for KDB")


# ===========================================================================
# Suite H — get_player_summary: miss / edge cases
# ===========================================================================

section("H. get_player_summary — miss / edge cases")

check(get_player_summary(99, P, T) is None,
      "H1  absent player → None")

sparse_p = [{"id": 10, "first_name": "X", "second_name": "Y",
             "web_name": "XY", "team_id": 1, "element_type": 3, "status": "a"}]
sparse_t = [{"id": 1, "name": "Test FC", "short_name": "TST"}]
s = get_player_summary("XY", sparse_p, sparse_t)
check(s is not None and s["cost_m"] is None,
      "H2  missing now_cost → cost_m is None")

unknown_status_p = [{"id": 10, "first_name": "A", "second_name": "B",
                     "web_name": "AB", "team_id": 1,
                     "element_type": 2, "status": "z", "now_cost": 45}]
unknown_status_t = [{"id": 1, "name": "FC", "short_name": "FC"}]
us = get_player_summary("AB", unknown_status_p, unknown_status_t)
check(us is not None and us["status"] == "z",
      "H3  unknown status code passed through raw")


# ===========================================================================
# Suite I — get_current_gameweek_from_bootstrap
# ===========================================================================

section("I. get_current_gameweek_from_bootstrap")

check(get_current_gameweek_from_bootstrap(BOOTSTRAP) == 28,
      "I1  is_current GW28 returned")

bs_no_current = copy.deepcopy(BOOTSTRAP)
for ev in bs_no_current["events"]:
    ev["is_current"] = False
check(get_current_gameweek_from_bootstrap(bs_no_current) == 29,
      "I2  falls back to is_next (GW29)")

bs_neither = copy.deepcopy(BOOTSTRAP)
for ev in bs_neither["events"]:
    ev["is_current"] = False
    ev["is_next"] = False
check(get_current_gameweek_from_bootstrap(bs_neither) is None,
      "I3  no flags → None")

check(get_current_gameweek_from_bootstrap({}) is None,
      "I4  empty dict → None (no network call)")

check(get_current_gameweek_from_bootstrap({"teams": [], "elements": []}) is None,
      "I5  missing events key → None")


# ===========================================================================
# Suite J — Public surface guard
# ===========================================================================

section("J. Public surface guard")

check(
    set(_pkg.__all__) == {
        "resolve_player_query", "get_player_summary",
        "get_current_gameweek_from_bootstrap",
    },
    "J1  __all__ contains exactly the 3 Phase 1e exports",
    f"got {_pkg.__all__}",
)

check(
    not hasattr(_pkg, "_build_and_resolve") and
    not hasattr(_pkg, "_STATUS_LABELS") and
    not hasattr(_pkg, "build_registry"),
    "J2  internal helpers not leaked into package surface",
)

r1 = get_player_summary("Haaland", P, T)
r2 = get_player_summary("Haaland", P, T)
check(r1 == r2, "J3  identical inputs produce identical outputs (deterministic)")


# ===========================================================================
# Summary
# ===========================================================================

total = _passed + _failed
print(f"\n{'═' * 62}")
print(f"  Phase 1e standalone validator")
print(f"  {_passed}/{total} assertions passed", "✓ PASS" if _failed == 0 else "✗ FAIL")
if _failures:
    print(f"\n  Failures:")
    for f in _failures:
        print(f"    • {f}")
print(f"{'═' * 62}")

sys.exit(0 if _failed == 0 else 1)


