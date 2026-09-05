"""Regressions for the agentic-loop experiment's frozen-bootstrap capture.

Two defects made the completed experiment's fixture axis unusable:

1. ``_capture_bootstrap`` froze ``/api/bootstrap-static/`` only, which carries
   no fixtures -- so every FDR tool answered ``missing_context`` and every
   fixture claim in the artifact was ungrounded.
2. ``get_fixtures_for_gw`` silently fell back to a *live* API call whenever
   ``bootstrap["_gw_fixtures"]`` was absent, so the run was not frozen at all.

The capture-shape tests below are hermetic (``requests`` is stubbed). The rest
run against the real frozen artifact and skip if it is missing.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util as _ilu
import json
import socket
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PACKAGE_ROOT = _HERE.parent
_PACKAGES = _PACKAGE_ROOT.parent
_REPO_ROOT = _PACKAGES.parent

# The capture path imports fpl_pipeline (for _build_team_fixtures) and the
# network-isolation test drives the whole registry, whose tools reach across
# siblings pytest.ini does not list. Mirror the driver's _configure_imports.
for _pkg in sorted(_PACKAGES.iterdir()):
    if _pkg.is_dir() and str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

_MOD_PATH = _PACKAGE_ROOT / "scripts" / "run_agentic_loop_experiment.py"
_spec = _ilu.spec_from_file_location("run_agentic_loop_experiment", _MOD_PATH)
exp = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(exp)

FROZEN = _REPO_ROOT / "field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json"


# ---------------------------------------------------------------------------
# Hermetic capture-shape tests
# ---------------------------------------------------------------------------

_TEAMS = [
    {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": 4},
    {"id": 2, "name": "Chelsea", "short_name": "CHE", "strength": 4},
    {"id": 3, "name": "Everton", "short_name": "EVE", "strength": 3},
    {"id": 4, "name": "Fulham", "short_name": "FUL", "strength": 3},
]

_FIXTURES = [
    {"id": 1, "event": 1, "team_h": 1, "team_a": 2,
     "team_h_difficulty": 4, "team_a_difficulty": 5},
    {"id": 2, "event": 1, "team_h": 3, "team_a": 4,
     "team_h_difficulty": 3, "team_a_difficulty": 2},
    {"id": 3, "event": 2, "team_h": 2, "team_a": 3,
     "team_h_difficulty": 2, "team_a_difficulty": 4},
    # Unscheduled: must be dropped, not defaulted into some gameweek.
    {"id": 4, "event": None, "team_h": 1, "team_a": 4,
     "team_h_difficulty": 2, "team_a_difficulty": 4},
]

_BOOTSTRAP_STATIC = {
    "teams": _TEAMS,
    "elements": [],
    "events": [{"id": 1, "is_current": False, "is_next": True, "finished": False}],
}


class _FakeResponse:
    def __init__(self, url: str, payload: object) -> None:
        self.url = url
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def captured(tmp_path, monkeypatch):
    """Run ``_capture_bootstrap`` against stubbed FPL endpoints."""
    import requests

    from fpl_api_client.fpl_client import ALL_FIXTURES_URL, BOOTSTRAP_URL

    payloads = {BOOTSTRAP_URL: _BOOTSTRAP_STATIC, ALL_FIXTURES_URL: _FIXTURES}

    def _fake_get(url, **_kwargs):
        assert url in payloads, f"unexpected capture URL {url}"
        return _FakeResponse(url, payloads[url])

    monkeypatch.setattr(requests, "get", _fake_get)
    target = tmp_path / "frozen.json"
    exp._capture_bootstrap(target)
    return target


def test_group_fixtures_by_event_drops_unscheduled():
    batches = exp._group_fixtures_by_event(_FIXTURES)

    assert sorted(batches) == [1, 2]
    assert [f["id"] for f in batches[1]] == [1, 2]
    assert [f["id"] for f in batches[2]] == [3]
    # Fixture 4 (event: null) appears nowhere.
    assert 4 not in {f["id"] for gw in batches.values() for f in gw}


def test_capture_writes_team_fixtures_for_every_team(captured):
    frozen = json.loads(captured.read_text(encoding="utf-8"))

    assert frozen["team_fixtures"], "team_fixtures must be present and non-empty"
    # JSON stringifies the int team ids _build_team_fixtures produces.
    assert set(frozen["team_fixtures"]) == {"1", "2", "3", "4"}
    def schedule(team_id):
        return [
            {key: fixture[key] for key in ("gameweek", "opponent_team", "is_home", "difficulty")}
            for fixture in frozen["team_fixtures"][team_id]
        ]

    assert schedule("1") == [
        {"gameweek": 1, "opponent_team": 2, "is_home": True, "difficulty": 4},
    ]
    assert schedule("3") == [
        {"gameweek": 1, "opponent_team": 4, "is_home": True, "difficulty": 3},
        {"gameweek": 2, "opponent_team": 2, "is_home": False, "difficulty": 4},
    ]
    # Each fixture also carries the completion context the minutes denominator
    # reads. A per-GW batch is never a complete season, so the marker is false
    # here and participation degrades explicitly rather than dividing by a
    # partial schedule.
    for fixtures in frozen["team_fixtures"].values():
        for fixture in fixtures:
            assert set(fixture) == {
                "gameweek", "opponent_team", "is_home", "difficulty",
                "finished", "kickoff_time", "minutes",
                "official_fixture_context_complete",
            }
            assert fixture["official_fixture_context_complete"] is False


def test_capture_injects_string_keyed_gw_fixtures(captured):
    """``get_fixtures_for_gw`` looks up ``_gw_fixtures[str(gw)]`` -- int keys
    would miss and fall through to the live API."""
    frozen = json.loads(captured.read_text(encoding="utf-8"))

    assert set(frozen["_gw_fixtures"]) == {"1", "2"}
    assert all(isinstance(key, str) for key in frozen["_gw_fixtures"])
    assert [f["id"] for f in frozen["_gw_fixtures"]["1"]] == [1, 2]


def test_capture_metadata_describes_the_assembled_artifact(captured):
    from fpl_api_client.fpl_client import ALL_FIXTURES_URL, BOOTSTRAP_URL

    meta = json.loads(
        captured.with_suffix(captured.suffix + ".meta.json").read_text(encoding="utf-8")
    )

    # The experiment header pins this hash, so it must be the hash of the file
    # that actually ran -- not of either upstream response.
    assert meta["sha256"] == hashlib.sha256(captured.read_bytes()).hexdigest()
    assert meta["sources"] == [BOOTSTRAP_URL, ALL_FIXTURES_URL]
    assert set(meta["source_sha256"]) == {"bootstrap_static", "fixtures"}
    assert meta["captured_at"]
    assert meta["fixture_counts"] == {
        "fixtures_returned": 4,
        "fixtures_scheduled": 3,
        "fixtures_dropped_no_event": 1,
        "gameweeks_covered": 2,
        "teams_with_fixtures": 4,
    }


def test_load_bootstrap_restores_int_team_ids(captured):
    """Several consumers (``scoring_shared._resolve_venue``,
    ``differential_picks._has_current_gw_fixture``) index ``team_fixtures``
    with an int and degrade silently to "no fixture data" on a miss."""
    loaded = exp._load_bootstrap(captured)

    assert set(loaded["team_fixtures"]) == {1, 2, 3, 4}
    assert all(isinstance(key, int) for key in loaded["team_fixtures"])
    # _gw_fixtures stays string-keyed on purpose.
    assert all(isinstance(key, str) for key in loaded["_gw_fixtures"])


# ---------------------------------------------------------------------------
# Frozen-artifact tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def frozen_bootstrap():
    if not FROZEN.exists():
        pytest.skip(f"frozen bootstrap {FROZEN} not present")
    return exp._load_bootstrap(FROZEN)


@pytest.fixture(scope="module")
def run_tool_fn():
    # The registry is populated as an import side-effect of the package;
    # importing the runner alone yields only a handful of tools.
    import fpl_grounded_assistant  # noqa: F401

    from fpl_tool_runner import run_tool

    return run_tool


def test_frozen_bootstrap_covers_all_twenty_teams(frozen_bootstrap):
    team_fixtures = frozen_bootstrap["team_fixtures"]
    team_ids = {int(team["id"]) for team in frozen_bootstrap["teams"]}

    assert len(team_ids) == 20
    assert set(team_fixtures) == team_ids
    assert all(team_fixtures[team_id] for team_id in team_ids)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_fixture_outlook", {"axis": "attack", "horizon": 5}),
        ("get_team_fixture_calendar", {"horizon": 5, "top_n": 5}),
    ],
)
def test_fixture_tools_are_grounded(frozen_bootstrap, run_tool_fn, tool, args):
    """These answered ``missing_context`` against the fixture-less snapshot."""
    result = run_tool_fn(tool, args, frozen_bootstrap)

    assert result["status"] == "ok", result.get("message")


def test_rank_players_by_metric_still_ok(frozen_bootstrap, run_tool_fn):
    result = run_tool_fn(
        "rank_players_by_metric",
        {"metric": "points_per_game", "position": "MID",
         "min_price": 6.0, "max_price": 8.0, "top_n": 5},
        frozen_bootstrap,
    )

    assert result["status"] == "ok", result.get("message")
    assert result.get("ranking_basis")


def test_next_five_gameweeks_are_consecutive_and_well_formed(frozen_bootstrap, run_tool_fn):
    next_gw = run_tool_fn("get_current_gameweek", {}, frozen_bootstrap)["gameweek"]
    team_ids = {int(team["id"]) for team in frozen_bootstrap["teams"]}
    short_names = {team["short_name"]: int(team["id"]) for team in frozen_bootstrap["teams"]}
    team_id = short_names["MCI"]

    window = [
        fixture for fixture in frozen_bootstrap["team_fixtures"][team_id]
        if next_gw <= fixture["gameweek"] < next_gw + 5
    ]

    assert len(window) == 5
    assert sorted(f["gameweek"] for f in window) == list(range(next_gw, next_gw + 5))
    for fixture in window:
        assert 1 <= fixture["difficulty"] <= 5
        assert fixture["opponent_team"] in team_ids
        assert fixture["opponent_team"] != team_id
        assert isinstance(fixture["is_home"], bool)


# ---------------------------------------------------------------------------
# Network isolation -- the direct test of defect 2
# ---------------------------------------------------------------------------

#: Every tool the completed experiment actually reached for, plus the fixture
#: tools the re-freeze is meant to unblock.
_SCENARIO_TOOL_CALLS = [
    ("get_gameweek_context", {}),
    ("get_current_gameweek", {}),
    ("get_transfer_suggestion", {"position": "MID", "max_price": 8.0}),
    ("rank_players_by_metric", {"metric": "points_per_game", "position": "MID",
                                "min_price": 6.0, "max_price": 8.0, "top_n": 5}),
    ("get_player_snapshot", {"player_name": "Haaland"}),
    ("get_position_fixture_run", {"position_query": "MID", "horizon": 5}),
    ("get_fixtures_for_gw", {"gw_number": 1}),
    ("get_fixture_outlook", {"axis": "attack", "horizon": 5}),
    ("get_team_fixture_calendar", {"horizon": 5, "top_n": 5}),
]


class _NetworkAttempted(Exception):
    pass


@pytest.fixture()
def network_tripwire(monkeypatch):
    """Record *and* block every outbound connection attempt.

    Recording matters as much as blocking: ``get_fixtures_for_gw`` wraps its
    live call in a bare ``except Exception``, so a leak that only raised would
    be swallowed and the tool would still look fine.
    """
    attempts: list[str] = []

    def _boom(*args, **_kwargs):
        attempts.append(repr(args[:2]))
        raise _NetworkAttempted("outbound network attempted")

    monkeypatch.setattr(socket.socket, "connect", _boom, raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom, raising=False)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    return attempts


def test_no_tool_touches_the_network(frozen_bootstrap, run_tool_fn, network_tripwire):
    for tool, args in _SCENARIO_TOOL_CALLS:
        result = run_tool_fn(tool, args, frozen_bootstrap)
        assert result["status"] == "ok", f"{tool}: {result}"

    assert network_tripwire == [], f"tools attempted outbound calls: {network_tripwire}"


def test_tripwire_catches_the_pre_fix_leak(frozen_bootstrap, run_tool_fn, network_tripwire):
    """Negative control: without ``_gw_fixtures`` -- the pre-fix snapshot shape
    -- ``get_fixtures_for_gw`` reaches for the live API. If this stops tripping,
    the isolation test above has gone blind."""
    # import_module, not "import a.b as gfg": __init__ re-exports the tool
    # function under the module's own name and shadows it.
    gfg = importlib.import_module("fpl_grounded_assistant.get_fixtures_for_gw")

    gfg._fixture_cache.clear()
    unfrozen = dict(frozen_bootstrap)
    unfrozen.pop("_gw_fixtures")

    run_tool_fn("get_fixtures_for_gw", {"gw_number": 1}, unfrozen)

    assert network_tripwire, "expected the pre-fix shape to attempt a live call"
