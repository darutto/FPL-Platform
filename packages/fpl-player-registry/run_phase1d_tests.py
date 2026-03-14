#!/usr/bin/env python3
"""
run_phase1d_tests.py
=====================
Standalone validator for fpl_player_registry Phase 1d — bootstrap core.

Run from the fpl-player-registry/ directory:
    python3 run_phase1d_tests.py

No pytest or network dependency — stdlib + local package only.

Suites
------
A.  Import smoke                          (3 assertions)
B.  build_registry determinism            (5 assertions)
C.  lookup_by_id                          (4 assertions)
D.  lookup_by_web_name — exact            (5 assertions)
E.  lookup_by_exact_name                  (6 assertions)
F.  lookup_by_alias / nickname            (8 assertions)
G.  Duplicate web_name handling           (4 assertions)
H.  Missing-player / None returns         (4 assertions)
I.  Stable IDs and team linkage           (5 assertions)
J.  Public surface guard                  (3 assertions)
──────────────────────────────────────────────────────────
Total                                    (47 assertions)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fpl_player_registry import (
    PlayerRecord,
    PlayerRegistry,
    build_registry,
    KNOWN_NICKNAMES,
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
    print(f"\n{'─' * 58}")
    print(f"  {title}")
    print(f"{'─' * 58}")


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

TEAMS: list[dict] = [
    {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    {"id": 8,  "name": "Chelsea",         "short_name": "CHE", "code": 8,  "strength": 4},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
    {"id": 5,  "name": "Everton",         "short_name": "EVE", "code": 11, "strength": 2},
]

PLAYERS: list[dict] = [
    {"id": 1, "first_name": "Erling",  "second_name": "Haaland",
     "web_name": "Haaland",       "team_id": 13, "element_type": 4, "status": "a",
     "now_cost": 145, "selected_by_percent": "52.3"},
    {"id": 2, "first_name": "Mohamed", "second_name": "Salah",
     "web_name": "Salah",         "team_id": 14, "element_type": 3, "status": "a",
     "now_cost": 135, "selected_by_percent": "64.1"},
    {"id": 3, "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka",          "team_id": 1,  "element_type": 3, "status": "d",
     "now_cost": 100, "selected_by_percent": "35.0"},
    {"id": 4, "first_name": "Kevin",   "second_name": "De Bruyne",
     "web_name": "De Bruyne",     "team_id": 13, "element_type": 3, "status": "i",
     "now_cost": 105, "selected_by_percent": "14.2"},
    {"id": 5, "first_name": "Ben",     "second_name": "Clarke",
     "web_name": "Clarke",        "team_id": 1,  "element_type": 2, "status": "a",
     "now_cost": 45,  "selected_by_percent": "1.2"},
    # Duplicate web_name pair
    {"id": 6, "first_name": "Adam",   "second_name": "Johnson",
     "web_name": "Johnson",       "team_id": 8,  "element_type": 3, "status": "a"},
    {"id": 7, "first_name": "Glen",   "second_name": "Johnson",
     "web_name": "Johnson",       "team_id": 11, "element_type": 2, "status": "a"},
    # Minimal fields
    {"id": 8, "first_name": "Test",   "second_name": "Player",
     "web_name": "TPlayer",       "team_id": 5,  "element_type": 1, "status": "u"},
]

REG: PlayerRegistry = build_registry(PLAYERS, TEAMS)


# ===========================================================================
# Suite A — Import smoke
# ===========================================================================

section("A. Import smoke")

check(isinstance(KNOWN_NICKNAMES, dict) and len(KNOWN_NICKNAMES) >= 10,
      "A1  KNOWN_NICKNAMES is a non-empty dict with ≥ 10 entries")

import fpl_player_registry as _pkg
check(
    all(hasattr(_pkg, n) for n in ("PlayerRecord", "PlayerRegistry", "build_registry", "KNOWN_NICKNAMES")),
    "A2  all 4 exports present in package",
)
check(not hasattr(_pkg, "SeasonIdMapper"), "A3  SeasonIdMapper NOT in Phase 1d surface")


# ===========================================================================
# Suite B — build_registry determinism
# ===========================================================================

section("B. build_registry determinism")

check(isinstance(REG, PlayerRegistry), "B1  build_registry returns PlayerRegistry instance")
check(len(REG) == len(PLAYERS),        "B2  len(registry) == len(PLAYERS)",
      f"got {len(REG)}")

r2 = build_registry(PLAYERS, TEAMS)
check(len(r2) == len(REG), "B3  building twice gives same len (deterministic)")

check(isinstance(REG.all_players(), list) and len(REG.all_players()) == len(PLAYERS),
      "B4  all_players() returns full list")

empty_reg = build_registry([], [])
check(len(empty_reg) == 0 and empty_reg.all_players() == [],
      "B5  empty bootstrap → empty registry")


# ===========================================================================
# Suite C — lookup_by_id
# ===========================================================================

section("C. lookup_by_id")

rec = REG.lookup_by_id(1)
check(rec is not None and rec.id == 1 and rec.web_name == "Haaland",
      "C1  id=1 → Haaland")

check(isinstance(REG.lookup_by_id(2), PlayerRecord),
      "C2  lookup_by_id returns PlayerRecord instance")

check(REG.lookup_by_id(99) is None, "C3  id=99 (absent) → None")

all_ok = all(REG.lookup_by_id(p["id"]) is not None for p in PLAYERS)
check(all_ok, "C4  all fixture player ids resolvable")


# ===========================================================================
# Suite D — lookup_by_web_name
# ===========================================================================

section("D. lookup_by_web_name — exact")

r = REG.lookup_by_web_name("Haaland")
check(r is not None and r.id == 1, "D1  'Haaland' (exact) → id 1")

check(
    REG.lookup_by_web_name("haaland") is not None and
    REG.lookup_by_web_name("HAALAND") is not None,
    "D2  case-insensitive lookup",
)

check(REG.lookup_by_web_name("NotAPlayer") is None, "D3  absent web_name → None")

check(REG.lookup_by_web_name("Johnson") is None,
      "D4  ambiguous web_name 'Johnson' → None")

check(REG.lookup_by_web_name("Salah") is not None and REG.lookup_by_web_name("Salah").id == 2,
      "D5  unique 'Salah' → id 2")


# ===========================================================================
# Suite E — lookup_by_exact_name
# ===========================================================================

section("E. lookup_by_exact_name")

r = REG.lookup_by_exact_name("Saka")
check(r is not None and r.id == 3, "E1  web_name 'Saka' → id 3")

r = REG.lookup_by_exact_name("De Bruyne")
check(r is not None and r.id == 4, "E2  second_name 'De Bruyne' → id 4")

r = REG.lookup_by_exact_name("Erling")
check(r is not None and r.id == 1, "E3  first_name 'Erling' → id 1")

r = REG.lookup_by_exact_name("de bruyne")
check(r is not None and r.id == 4, "E4  case-insensitive second_name")

check(REG.lookup_by_exact_name("Platini") is None, "E5  absent name → None")

# web_name priority over first_name
_prio_reg = build_registry(
    [
        {"id": 10, "first_name": "Alpha", "second_name": "Smith",
         "web_name": "Beta", "team_id": 1, "element_type": 3, "status": "a"},
        {"id": 11, "first_name": "Beta",  "second_name": "Jones",
         "web_name": "Jones", "team_id": 1, "element_type": 3, "status": "a"},
    ],
    [{"id": 1, "name": "Test FC", "short_name": "TST"}],
)
r = _prio_reg.lookup_by_exact_name("Beta")
check(r is not None and r.id == 10, "E6  web_name takes priority over first_name")


# ===========================================================================
# Suite F — lookup_by_alias / nickname
# ===========================================================================

section("F. lookup_by_alias / nickname")

r = REG.lookup_by_alias("KDB")
check(r is not None and r.id == 4, "F1  alias 'KDB' → De Bruyne (id 4)")

r = REG.lookup_by_alias("el Vikingo")
check(r is not None and r.id == 1, "F2  alias 'el Vikingo' → Haaland (id 1)")

r = REG.lookup_by_alias("kdb")
check(r is not None and r.id == 4, "F3  case-insensitive alias")

r = REG.lookup_by_alias("Mo")
check(r is not None and r.id == 2, "F4  alias 'Mo' → Salah (id 2)")

_taa_reg = build_registry(
    [{"id": 20, "first_name": "Trent", "second_name": "Alexander-Arnold",
      "web_name": "Alexander-Arnold", "team_id": 14, "element_type": 2, "status": "a"}],
    [{"id": 14, "name": "Liverpool", "short_name": "LIV"}],
)
check(_taa_reg.lookup_by_alias("TAA") is not None,  "F5  alias 'TAA' → Alexander-Arnold")
check(_taa_reg.lookup_by_alias("Trent") is not None, "F6  alias 'Trent' → Alexander-Arnold")

check(REG.lookup_by_alias("Zizou") is None, "F7  unknown alias → None")

_no_salah = build_registry(
    [{"id": 1, "first_name": "Erling", "second_name": "Haaland",
      "web_name": "Haaland", "team_id": 13, "element_type": 4, "status": "a"}],
    [{"id": 13, "name": "Man City", "short_name": "MCI"}],
)
check(_no_salah.lookup_by_alias("Mo") is None, "F8  alias for absent player → None")


# ===========================================================================
# Suite G — Duplicate web_name handling
# ===========================================================================

section("G. Duplicate web_name handling")

check("johnson" in REG.ambiguous_web_names, "G1  'johnson' recorded in ambiguous_web_names")
check(REG.lookup_by_web_name("Johnson") is None, "G2  ambiguous 'Johnson' lookup → None")

adam = REG.lookup_by_id(6)
glen = REG.lookup_by_id(7)
check(
    adam is not None and glen is not None and adam.web_name == "Johnson" and glen.web_name == "Johnson" and adam.id != glen.id,
    "G3  both 'Johnson' players resolvable by id",
)
check(
    "haaland" not in REG.ambiguous_web_names and "salah" not in REG.ambiguous_web_names,
    "G4  unique players not flagged as ambiguous",
)


# ===========================================================================
# Suite H — Missing-player / None returns
# ===========================================================================

section("H. Missing-player / None returns")

check(REG.lookup_by_id(99) is None,              "H1  absent id → None")
check(REG.lookup_by_web_name("Cantona") is None, "H2  absent web_name → None")
check(REG.lookup_by_exact_name("Platini") is None, "H3  absent exact name → None")
check(REG.lookup_by_alias("el Fantasma") is None, "H4  absent alias → None")


# ===========================================================================
# Suite I — Stable IDs and team linkage
# ===========================================================================

section("I. Stable IDs and team linkage")

all_ids_ok = all(REG.lookup_by_id(p["id"]).id == p["id"] for p in PLAYERS)
check(all_ids_ok, "I1  all record ids match bootstrap ids")

haaland = REG.lookup_by_id(1)
check(
    haaland.team_id == 13 and haaland.team_name == "Manchester City" and haaland.team_short_name == "MCI",
    "I2  Haaland team linkage correct (id=13, MCI, Manchester City)",
)

check(isinstance(REG.get_team(13), dict) and REG.get_team(13)["name"] == "Manchester City",
      "I3  get_team(13) returns correct raw dict")

check(REG.get_team(999) is None, "I4  get_team for absent team → None")

# Frozen record — mutation should raise
haaland = REG.lookup_by_id(1)
mutation_raised = False
try:
    object.__setattr__(haaland, "web_name", "Mutated")  # bypass frozen
except (AttributeError, TypeError):
    mutation_raised = True
# dataclass frozen=True raises FrozenInstanceError (subclass of AttributeError)
frozen_ok = isinstance(haaland, PlayerRecord)  # at minimum, record exists and is typed
# Direct test: attempting normal assignment
try:
    haaland.web_name = "Mutated"  # type: ignore[misc]
    mutation_raised = False
except (AttributeError, TypeError):
    mutation_raised = True
check(mutation_raised, "I5  PlayerRecord is immutable (frozen dataclass)")


# ===========================================================================
# Suite J — Public surface guard
# ===========================================================================

section("J. Public surface guard")

check(
    set(_pkg.__all__) == {"PlayerRecord", "PlayerRegistry", "build_registry", "KNOWN_NICKNAMES"},
    "J1  __all__ contains exactly the 4 Phase 1d exports",
    f"got {_pkg.__all__}",
)
check(not hasattr(_pkg, "SeasonIdMapper"),   "J2  SeasonIdMapper not in surface")
check(callable(build_registry),              "J3  build_registry is callable")


# ===========================================================================
# Summary
# ===========================================================================

total = _passed + _failed
print(f"\n{'═' * 58}")
print(f"  Phase 1d standalone validator")
print(f"  {_passed}/{total} assertions passed", "✓ PASS" if _failed == 0 else "✗ FAIL")
if _failures:
    print(f"\n  Failures:")
    for f in _failures:
        print(f"    • {f}")
print(f"{'═' * 58}")

sys.exit(0 if _failed == 0 else 1)


