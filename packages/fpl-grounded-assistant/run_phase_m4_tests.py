"""
run_phase_m4_tests.py
======================
Phase M4 (MCP_architecture): Spanish Hardening tests.

Covers:
    A  Alias migration: tables exported from intent_aliases.py
    B  §7.1 Spanish transfer prefix/connector fixes
    C  §7.2 Spanish player-fixture-run prefix fixes
    D  §7.3 "calendario de X" disambiguation (team vs player)
    E  §7.6 Spanish differential-picks keywords
    F  §7.5 Spanish gameweek keywords
    G  Prompt-prefixed inputs route deterministically
    H  D-suite guard (M3 contract: phrase must remain unroutable)

Run from packages/fpl-grounded-assistant::

    python run_phase_m4_tests.py

Target: >=30 assertions.  Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations

import os
import sys

# Windows consoles default to cp1252 which crashes on Unicode glyphs (e.g. the
# `→` used in test labels). Reconfigure stdout/stderr to utf-8 with replacement
# so the runner prints cleanly on every platform. No-op on Linux/macOS.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

from fpl_grounded_assistant import ask  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.router import route  # noqa: E402
from fpl_grounded_assistant.intent_aliases import (  # noqa: E402
    TRANSFER_SPANISH_PREFIXES,
    TRANSFER_SPANISH_CONNECTORS,
    FIXTURE_RUN_SPANISH_PREFIXES,
    FIXTURE_RUN_SPANISH_SUFFIXES,
    DIFFERENTIAL_SPANISH_KEYWORDS,
    GAMEWEEK_SPANISH_KEYWORDS,
    CALENDARIO_DE_PREFIX,
)

BOOTSTRAP = STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Test plumbing
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        _failures.append(label)
        print(f"  FAIL  {label}")


def tool(question: str) -> str | None:
    """Return the tool_name routed for *question*, or None."""
    r = route(question)
    return r.tool_name if r else None


# ===========================================================================
# A — Alias migration: tables exported from intent_aliases.py
# ===========================================================================
print("\n[A] alias migration — intent_aliases.py exports")

# A1: TRANSFER_SPANISH_PREFIXES is non-empty and contains expected entries
check(len(TRANSFER_SPANISH_PREFIXES) > 0,           "A1: TRANSFER_SPANISH_PREFIXES non-empty")
check("vendo" in TRANSFER_SPANISH_PREFIXES,         "A2: 'vendo' in TRANSFER_SPANISH_PREFIXES")
check("saco a" in TRANSFER_SPANISH_PREFIXES,        "A3: 'saco a' in TRANSFER_SPANISH_PREFIXES")
check("cambio" in TRANSFER_SPANISH_PREFIXES,        "A4: 'cambio' in TRANSFER_SPANISH_PREFIXES")
check("véndele" in TRANSFER_SPANISH_PREFIXES,       "A5: 'véndele' in TRANSFER_SPANISH_PREFIXES")

# A2: TRANSFER_SPANISH_CONNECTORS
check(" por " in TRANSFER_SPANISH_CONNECTORS,       "A6: ' por ' in TRANSFER_SPANISH_CONNECTORS")
check(" por el " in TRANSFER_SPANISH_CONNECTORS,    "A7: ' por el ' in TRANSFER_SPANISH_CONNECTORS")

# A3: FIXTURE_RUN_SPANISH_PREFIXES
check(len(FIXTURE_RUN_SPANISH_PREFIXES) > 0,            "A8: FIXTURE_RUN_SPANISH_PREFIXES non-empty")
check("proximos partidos de" in FIXTURE_RUN_SPANISH_PREFIXES, "A9: 'proximos partidos de' in FIXTURE_RUN_SPANISH_PREFIXES")
check("siguientes partidos de" in FIXTURE_RUN_SPANISH_PREFIXES, "A10: 'siguientes partidos de' in FIXTURE_RUN_SPANISH_PREFIXES")

# A4: DIFFERENTIAL_SPANISH_KEYWORDS
check("diferenciales" in DIFFERENTIAL_SPANISH_KEYWORDS,         "A11: 'diferenciales' in DIFFERENTIAL_SPANISH_KEYWORDS")
check("diferenciales esta semana" in DIFFERENTIAL_SPANISH_KEYWORDS, "A12: 'diferenciales esta semana' in DIFFERENTIAL_SPANISH_KEYWORDS")

# A5: GAMEWEEK_SPANISH_KEYWORDS
check("jornada actual" in GAMEWEEK_SPANISH_KEYWORDS,             "A13: 'jornada actual' in GAMEWEEK_SPANISH_KEYWORDS")
check("que jornada es" in GAMEWEEK_SPANISH_KEYWORDS,             "A14: 'que jornada es' in GAMEWEEK_SPANISH_KEYWORDS")

# A6: CALENDARIO_DE_PREFIX sentinel
check(CALENDARIO_DE_PREFIX == "calendario de ",                  "A15: CALENDARIO_DE_PREFIX == 'calendario de '")


# ===========================================================================
# B — §7.1 Spanish transfer advice fixes
# ===========================================================================
print("\n[B] §7.1 Spanish transfer prefix/connector fixes")

check(tool("vendele Salah por Haaland") == "get_transfer_advice",
      "B1: 'vendele Salah por Haaland' → get_transfer_advice")
check(tool("véndele Salah por Haaland") == "get_transfer_advice",
      "B2: 'véndele Salah por Haaland' (accent) → get_transfer_advice")
check(tool("vendo Saka por Haaland") == "get_transfer_advice",
      "B3: 'vendo Saka por Haaland' → get_transfer_advice")
check(tool("cambio Saka por Salah") == "get_transfer_advice",
      "B4: 'cambio Saka por Salah' → get_transfer_advice")
check(tool("saco a Saka por Salah") == "get_transfer_advice",
      "B5: 'saco a Saka por Salah' → get_transfer_advice")
check(tool("doy de baja a Saka por Haaland") == "get_transfer_advice",
      "B6: 'doy de baja a Saka por Haaland' → get_transfer_advice")

# B regression: English transfer still routes
check(tool("should I sell Saka for Haaland") == "get_transfer_advice",
      "B7 regression: 'should I sell Saka for Haaland' → get_transfer_advice")
check(tool("sell Haaland for Salah") == "get_transfer_advice",
      "B8 regression: 'sell Haaland for Salah' → get_transfer_advice")
check(tool("swap Saka for Haaland") == "get_transfer_advice",
      "B9 regression: 'swap Saka for Haaland' → get_transfer_advice")

# B anti-regression: 'cambios de precio' not swallowed by 'cambio' prefix
check(tool("cambios de precio esta semana") == "get_price_changes",
      "B10 anti-regression: 'cambios de precio esta semana' → get_price_changes (not transfer)")


# ===========================================================================
# C — §7.2 Spanish player fixture-run fixes
# ===========================================================================
print("\n[C] §7.2 Spanish player fixture-run fixes")

check(tool("proximos partidos de Saka") == "get_player_fixture_run",
      "C1: 'proximos partidos de Saka' → get_player_fixture_run")
check(tool("próximos partidos de Saka") == "get_player_fixture_run",
      "C2: 'próximos partidos de Saka' (accent) → get_player_fixture_run")
check(tool("siguientes partidos de Salah") == "get_player_fixture_run",
      "C3: 'siguientes partidos de Salah' → get_player_fixture_run")
check(tool("partidos de Haaland") == "get_player_fixture_run",
      "C4: 'partidos de Haaland' → get_player_fixture_run")

# C regression: English fixture-run still routes
check(tool("fixtures for Haaland") == "get_player_fixture_run",
      "C5 regression: 'fixtures for Haaland' → get_player_fixture_run")
check(tool("Salah fixtures") == "get_player_fixture_run",
      "C6 regression: 'Salah fixtures' → get_player_fixture_run")
check(tool("Haaland next 5 games") == "get_player_fixture_run",
      "C7 regression: 'Haaland next 5 games' → get_player_fixture_run")


# ===========================================================================
# D — §7.3 "calendario de X" disambiguation
# ===========================================================================
print("\n[D] §7.3 'calendario de X' disambiguation (team vs player)")

# D1: known team → team_schedule
check(tool("calendario de Arsenal") == "get_team_schedule",
      "D1: 'calendario de Arsenal' → get_team_schedule")
check(tool("calendario de Liverpool") == "get_team_schedule",
      "D2: 'calendario de Liverpool' → get_team_schedule")
check(tool("calendario de Manchester City") == "get_team_schedule",
      "D3: 'calendario de Manchester City' → get_team_schedule")
check(tool("calendario de Chelsea") == "get_team_schedule",
      "D4: 'calendario de Chelsea' → get_team_schedule")

# D2: plan example with "del" — team_schedule
check(tool("calendario de los proximos 5 del City") == "get_team_schedule",
      "D5: 'calendario de los proximos 5 del City' → get_team_schedule")

# D3: non-team player → player_fixture_run
check(tool("calendario de Haaland") == "get_player_fixture_run",
      "D6: 'calendario de Haaland' → get_player_fixture_run")
check(tool("calendario de Salah") == "get_player_fixture_run",
      "D7: 'calendario de Salah' → get_player_fixture_run")

# D4 regression: old "calendario del" contraction still routes to team_schedule
check(tool("calendario del Arsenal") == "get_team_schedule",
      "D8 regression: 'calendario del Arsenal' → get_team_schedule")
check(tool("proximos partidos del Liverpool") == "get_team_schedule",
      "D9 regression: 'proximos partidos del Liverpool' → get_team_schedule")

# D5: route() returns correct tool_args for disambiguation
_d_team = route("calendario de Arsenal")
check(_d_team is not None and _d_team.tool_args.get("team_query") == "Arsenal",
      "D10: 'calendario de Arsenal' → team_query='Arsenal'")

_d_player = route("calendario de Haaland")
check(_d_player is not None and _d_player.tool_args.get("query") == "Haaland",
      "D11: 'calendario de Haaland' → query='Haaland'")


# ===========================================================================
# E — §7.6 Spanish differential-picks keywords
# ===========================================================================
print("\n[E] §7.6 Spanish differential keywords")

check(tool("diferenciales") == "get_differential_picks",
      "E1: 'diferenciales' → get_differential_picks")
check(tool("diferenciales esta semana") == "get_differential_picks",
      "E2: 'diferenciales esta semana' → get_differential_picks")
check(tool("diferenciales para esta jornada") == "get_differential_picks",
      "E3: 'diferenciales para esta jornada' → get_differential_picks")

# E regression: English still routes
check(tool("differentials this week") == "get_differential_picks",
      "E4 regression: 'differentials this week' → get_differential_picks")
check(tool("differential picks") == "get_differential_picks",
      "E5 regression: 'differential picks' → get_differential_picks")
check(tool("low ownership picks") == "get_differential_picks",
      "E6 regression: 'low ownership picks' → get_differential_picks")


# ===========================================================================
# F — §7.5 Spanish gameweek keywords
# ===========================================================================
print("\n[F] §7.5 Spanish gameweek keywords")

check(tool("que jornada es") == "get_current_gameweek",
      "F1: 'que jornada es' → get_current_gameweek")
check(tool("jornada actual") == "get_current_gameweek",
      "F2: 'jornada actual' → get_current_gameweek")
check(tool("en que jornada estamos") == "get_current_gameweek",
      "F3: 'en que jornada estamos' → get_current_gameweek")
check(tool("jornada en curso") == "get_current_gameweek",
      "F4: 'jornada en curso' → get_current_gameweek")

# F regression: English still routes
check(tool("current gameweek") == "get_current_gameweek",
      "F5 regression: 'current gameweek' → get_current_gameweek")
check(tool("what gameweek") == "get_current_gameweek",
      "F6 regression: 'what gameweek' → get_current_gameweek")


# ===========================================================================
# G — Prompt-prefixed inputs route deterministically
# ===========================================================================
print("\n[G] Prompt-prefixed inputs route deterministically (via ask())")

# ask() returns a dict with 'selected_tool' as the tool name key.
# These tests verify that canonical prompt expansions reach route() without
# the orchestrator fallback (selected_tool is not None = route hit).

_r_cap = ask("should I captain Haaland", BOOTSTRAP)
check(_r_cap.get("selected_tool") == "get_captain_score",
      "G1: 'should I captain Haaland' → get_captain_score (deterministic)")
check(_r_cap.get("raw_output", {}).get("status") == "ok",
      "G2: captain_score raw_output.status='ok'")

_r_cmp = ask("compare Salah and Haaland", BOOTSTRAP)
check(_r_cmp.get("selected_tool") == "compare_players",
      "G3: 'compare Salah and Haaland' → compare_players (deterministic)")

_r_tfr = ask("should I sell Saka for Haaland", BOOTSTRAP)
check(_r_tfr.get("selected_tool") == "get_transfer_advice",
      "G4: 'should I sell Saka for Haaland' → get_transfer_advice (deterministic)")

_r_chip = ask("should I use bench boost this week", BOOTSTRAP)
check(_r_chip.get("selected_tool") == "get_chip_advice",
      "G5: 'should I use bench boost this week' → get_chip_advice (deterministic)")

# Spanish slash-command equivalents that now route deterministically:
_r_vend = ask("vendele Saka por Haaland", BOOTSTRAP)
check(_r_vend.get("selected_tool") == "get_transfer_advice",
      "G6: Spanish 'vendele Saka por Haaland' → get_transfer_advice (deterministic)")

_r_cal = ask("proximos partidos de Saka", BOOTSTRAP)
check(_r_cal.get("selected_tool") == "get_player_fixture_run",
      "G7: Spanish 'proximos partidos de Saka' → get_player_fixture_run (deterministic)")

_r_dif = ask("diferenciales esta semana", BOOTSTRAP)
check(_r_dif.get("selected_tool") == "get_differential_picks",
      "G8: Spanish 'diferenciales esta semana' → get_differential_picks (deterministic)")


# ===========================================================================
# H — D-suite guard (M3 hand-off contract)
# ===========================================================================
print("\n[H] D-suite guard: M3 unroutable phrase must remain unrouted")

_D_QUESTION = (
    "darme un consejo holistico sobre mi banco esta semana segun el calendario"
)

# H1: route() returns None — phrase not absorbed by deterministic router
_d_route = route(_D_QUESTION)
check(_d_route is None,
      "H1: D-suite phrase unroutable by route() after M4 changes")

# H2: ask() returns unsupported (no classifier stub, no orchestrator)
_d_resp = ask(_D_QUESTION, BOOTSTRAP)
check(_d_resp.get("selected_tool") is None,
      "H2: ask() on D-suite phrase returns no selected_tool")

# H3: related vocabulary separately routes correctly (they don't absorb D-suite)
check(tool("calendario de Arsenal") == "get_team_schedule",
      "H3: 'calendario de Arsenal' routes correctly (not absorbed with D-suite)")
check(tool("calendario de Haaland") == "get_player_fixture_run",
      "H4: 'calendario de Haaland' routes correctly (separate from D-suite)")


# ===========================================================================
# Results
# ===========================================================================
print(f"\n{'='*70}")
total = _pass + _fail
print(f"Phase M4 results: {_pass} PASS, {_fail} FAIL  (total {total})")
print(f"{'='*70}")

if _failures:
    print("\nFailed assertions:")
    for f in _failures:
        print(f"  FAIL  {f}")
    sys.exit(1)
else:
    print("All M4 assertions PASS.")
    sys.exit(0)
