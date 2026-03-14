#!/usr/bin/env python3
"""
run_phase1c_tests.py
=====================
Standalone validator for fpl_api_client Phase 1c — bootstrap-only surface.

Run from the fpl-api-client/ directory:
    python3 run_phase1c_tests.py

Requires only stdlib + requests (already available in the VM).
No pytest dependency — uses plain assert for portability.

Suites:
    A.  Import smoke                  (2 assertions)
    B.  fetch_json happy path         (3 assertions)
    C.  fetch_json retry/error        (4 assertions)
    D.  get_bootstrap                 (3 assertions)
    E.  get_players                   (6 assertions)
    F.  get_teams                     (5 assertions)
    G.  get_current_gameweek          (6 assertions)
    H.  Public surface guard          (2 assertions)
    ─────────────────────────────────────────────────
    Total                            (31 assertions)
"""
from __future__ import annotations

import copy
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make fpl_api_client importable from this directory
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

import requests  # noqa: E402  (must come after sys.path manipulation)
from fpl_api_client.fpl_client import (  # noqa: E402
    BOOTSTRAP_URL,
    _DEFAULT_TIMEOUT,
    _RETRY_ATTEMPTS,
    _RETRY_BACKOFF,
    fetch_json,
    get_bootstrap,
    get_current_gameweek,
    get_players,
    get_teams,
)

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_PATCH_TARGET = "fpl_api_client.fpl_client.requests.get"

_passed = 0
_failed = 0
_failures: list[str] = []


def ok(label: str) -> None:
    global _passed
    _passed += 1
    print(f"  ✓  {label}")


def fail(label: str, detail: str) -> None:
    global _failed
    _failed += 1
    _failures.append(f"{label}: {detail}")
    print(f"  ✗  {label}")
    print(f"       {detail}")


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        ok(label)
    else:
        fail(label, detail or "assertion failed")


def section(title: str) -> None:
    print(f"\n{'─' * 58}")
    print(f"  {title}")
    print(f"{'─' * 58}")


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

MINIMAL_BOOTSTRAP: dict = {
    "elements": [
        {
            "id": 1, "first_name": "Erling", "second_name": "Haaland",
            "web_name": "Haaland", "team": 13, "team_code": 43,
            "element_type": 4, "status": "a", "now_cost": 145,
            "selected_by_percent": "52.3", "form": "8.0",
            "expected_goals": "1.50", "expected_assists": "0.20",
            "expected_goal_involvements": "1.70",
        },
        {
            "id": 2, "first_name": "Mohamed", "second_name": "Salah",
            "web_name": "Salah", "team": 14, "team_code": 1,
            "element_type": 3, "status": "a", "now_cost": 135,
            "selected_by_percent": "64.1", "form": "9.5",
            "expected_goals": "0.90", "expected_assists": "0.55",
            "expected_goal_involvements": "1.45",
        },
        {
            "id": 3, "first_name": "Bukayo", "second_name": "Saka",
            "web_name": "Saka", "team": 1, "team_code": 3,
            "element_type": 3, "status": "d", "now_cost": 100,
            "selected_by_percent": "35.0", "form": "5.5",
            "expected_goals": "0.45", "expected_assists": "0.40",
            "expected_goal_involvements": "0.85",
        },
    ],
    "teams": [
        {"id": 1,  "name": "Arsenal",        "short_name": "ARS", "code": 3,  "strength": 4},
        {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
        {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
    ],
    "events": [
        {"id": 27, "is_current": False, "is_next": False, "finished": True},
        {"id": 28, "is_current": True,  "is_next": False, "finished": False},
        {"id": 29, "is_current": False, "is_next": True,  "finished": False},
    ],
    "element_types": [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ],
}


def _make_ok_response(payload: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = copy.deepcopy(payload)
    m.raise_for_status.return_value = None
    return m


def _make_err_response(status: int = 503) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.side_effect = requests.HTTPError(f"Mock {status}")
    return m


def _make_conn_err() -> MagicMock:
    m = MagicMock()
    m.raise_for_status.side_effect = requests.ConnectionError("Mock timeout")
    return m


# ===========================================================================
# Suite A — Import smoke
# ===========================================================================

section("A. Import smoke")

try:
    import fpl_api_client
    check(
        hasattr(fpl_api_client, "get_bootstrap"),
        "A1  fpl_api_client exposes get_bootstrap",
    )
    check(
        set(fpl_api_client.__all__) == {"get_bootstrap", "get_players", "get_teams", "get_current_gameweek"},
        "A2  __all__ contains exactly the 4 bootstrap functions",
        f"got {fpl_api_client.__all__}",
    )
except Exception as exc:
    fail("A1-A2  import failed", str(exc))

# ===========================================================================
# Suite B — fetch_json happy path
# ===========================================================================

section("B. fetch_json happy path")

with patch(_PATCH_TARGET, return_value=_make_ok_response({"ok": True})):
    result = fetch_json("https://example.com/api/")
check(result == {"ok": True}, "B1  fetch_json returns parsed JSON")

with patch(_PATCH_TARGET, return_value=_make_ok_response({})) as mg:
    fetch_json("https://example.com/api/")
check(
    mg.call_args[0][0] == "https://example.com/api/",
    "B2  fetch_json passes correct url to requests.get",
)
check(
    mg.call_args[1].get("timeout") == _DEFAULT_TIMEOUT,
    "B3  fetch_json passes default timeout",
    f"got timeout={mg.call_args[1].get('timeout')}",
)

# ===========================================================================
# Suite C — fetch_json retry / error
# ===========================================================================

section("C. fetch_json retry / error")

# C1 — succeeds on 2nd attempt
with patch(_PATCH_TARGET, side_effect=[_make_conn_err(), _make_ok_response({"data": 42})]):
    with patch("fpl_api_client.fpl_client.time.sleep"):
        retry_result = fetch_json("https://example.com/api/")
check(retry_result == {"data": 42}, "C1  fetch_json retries and succeeds on 2nd attempt")

# C2 — raises after all retries
raised = False
with patch(_PATCH_TARGET, side_effect=[_make_err_response() for _ in range(_RETRY_ATTEMPTS)]):
    with patch("fpl_api_client.fpl_client.time.sleep"):
        try:
            fetch_json("https://example.com/api/")
        except requests.HTTPError:
            raised = True
check(raised, "C2  fetch_json raises HTTPError after all retries exhausted")

# C3 — sleeps between retries
with patch(_PATCH_TARGET, side_effect=[_make_conn_err(), _make_ok_response({})]):
    with patch("fpl_api_client.fpl_client.time.sleep") as mock_sleep:
        fetch_json("https://example.com/api/")
check(
    mock_sleep.call_count == 1 and mock_sleep.call_args[0][0] == _RETRY_BACKOFF * 1,
    "C3  fetch_json sleeps _RETRY_BACKOFF * attempt between retries",
    f"sleep calls={mock_sleep.call_count}, arg={mock_sleep.call_args}",
)

# C4 — no sleep on success
with patch(_PATCH_TARGET, return_value=_make_ok_response({})):
    with patch("fpl_api_client.fpl_client.time.sleep") as mock_sleep:
        fetch_json("https://example.com/api/")
check(mock_sleep.call_count == 0, "C4  no sleep when first attempt succeeds")

# ===========================================================================
# Suite D — get_bootstrap
# ===========================================================================

section("D. get_bootstrap")

with patch(_PATCH_TARGET, return_value=_make_ok_response(MINIMAL_BOOTSTRAP)) as mg:
    bs = get_bootstrap()
check(mg.call_args[0][0] == BOOTSTRAP_URL, "D1  get_bootstrap fetches BOOTSTRAP_URL")
check(isinstance(bs, dict), "D2  get_bootstrap returns dict")
check(
    "elements" in bs and "teams" in bs and "events" in bs,
    "D3  bootstrap dict contains elements, teams, events",
)

# ===========================================================================
# Suite E — get_players
# ===========================================================================

section("E. get_players")

bs = copy.deepcopy(MINIMAL_BOOTSTRAP)
players = get_players(bs)

check(isinstance(players, list), "E1  get_players returns a list")
check(len(players) == 3, "E2  player count matches elements count", f"got {len(players)}")

required_keys = {
    "id", "first_name", "second_name", "web_name",
    "team_id", "team_code", "element_type", "status",
    "now_cost", "selected_by_percent", "form",
    "expected_goals", "expected_assists", "expected_goal_involvements",
}
all_have_keys = all(required_keys.issubset(p.keys()) for p in players)
check(all_have_keys, "E3  all required keys present in every player dict")

haaland = next(p for p in players if p["id"] == 1)
check(haaland["team_id"] == 13, "E4  team field mapped to team_id correctly")

# E5 — calls get_bootstrap when None
with patch(_PATCH_TARGET, return_value=_make_ok_response(MINIMAL_BOOTSTRAP)):
    players_none = get_players(None)
check(len(players_none) == 3, "E5  get_players calls get_bootstrap when arg is None")

# E6 — optional fields None when absent
sparse = {"elements": [{
    "id": 99, "first_name": "X", "second_name": "Y", "web_name": "XY",
    "team": 1, "element_type": 3, "status": "a",
}]}
sparse_players = get_players(sparse)
p = sparse_players[0]
check(
    p["team_code"] is None and p["now_cost"] is None and p["form"] is None,
    "E6  optional fields are None when absent from element",
)

# ===========================================================================
# Suite F — get_teams
# ===========================================================================

section("F. get_teams")

bs = copy.deepcopy(MINIMAL_BOOTSTRAP)
teams = get_teams(bs)

check(isinstance(teams, list), "F1  get_teams returns a list")
check(len(teams) == 3, "F2  team count matches bootstrap teams", f"got {len(teams)}")

req_team_keys = {"id", "name", "short_name", "code", "strength"}
all_teams_ok = all(req_team_keys.issubset(t.keys()) for t in teams)
check(all_teams_ok, "F3  all required keys present in every team dict")

man_city = next(t for t in teams if t["id"] == 13)
check(
    man_city["name"] == "Manchester City" and man_city["short_name"] == "MCI" and man_city["strength"] == 5,
    "F4  team values (name, short_name, strength) correct for Man City",
)

with patch(_PATCH_TARGET, return_value=_make_ok_response(MINIMAL_BOOTSTRAP)):
    teams_none = get_teams(None)
check(len(teams_none) == 3, "F5  get_teams calls get_bootstrap when arg is None")

# ===========================================================================
# Suite G — get_current_gameweek
# ===========================================================================

section("G. get_current_gameweek")

bs = copy.deepcopy(MINIMAL_BOOTSTRAP)
check(get_current_gameweek(bs) == 28, "G1  returns is_current event id (GW 28)")

bs_no_current = copy.deepcopy(MINIMAL_BOOTSTRAP)
for ev in bs_no_current["events"]:
    ev["is_current"] = False
check(get_current_gameweek(bs_no_current) == 29, "G2  falls back to is_next when no is_current")

bs_neither = copy.deepcopy(MINIMAL_BOOTSTRAP)
for ev in bs_neither["events"]:
    ev["is_current"] = False
    ev["is_next"] = False
check(get_current_gameweek(bs_neither) is None, "G3  returns None when neither flag set")

check(get_current_gameweek({"events": []}) is None, "G4  returns None for empty events list")
check(get_current_gameweek({}) is None, "G5  returns None for missing events key")

with patch(_PATCH_TARGET, return_value=_make_ok_response(MINIMAL_BOOTSTRAP)):
    gw_none = get_current_gameweek(None)
check(gw_none == 28, "G6  calls get_bootstrap when arg is None")

# ===========================================================================
# Suite H — Public surface guard
# ===========================================================================

section("H. Public surface guard")

import fpl_api_client as _pkg  # noqa: E402

check(
    all(callable(getattr(_pkg, name)) for name in _pkg.__all__),
    "H1  every name in __all__ is callable",
)
check(
    not hasattr(_pkg, "FootballDataClient") and not hasattr(_pkg, "get_fixtures"),
    "H2  out-of-scope items (FootballDataClient, get_fixtures) not in public surface",
)

# ===========================================================================
# Summary
# ===========================================================================

total = _passed + _failed
print(f"\n{'═' * 58}")
print(f"  Phase 1c standalone validator")
print(f"  {_passed}/{total} assertions passed", "✓ PASS" if _failed == 0 else "✗ FAIL")
if _failures:
    print(f"\n  Failures:")
    for f in _failures:
        print(f"    • {f}")
print(f"{'═' * 58}")

sys.exit(0 if _failed == 0 else 1)


