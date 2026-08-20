"""Tests for class-2 composition scenario grading.

Verification points:
3. Grader passes a hand-built CORRECT payload.
4. Grader fails each of the five hand-built BROKEN payloads for the RIGHT reason.
5. Composition check works (synthetic single-tool trace fails; two-tool trace passes).
"""
import json
import re
from pathlib import Path

import pytest

from fpl_grounded_assistant.experiment_measurement import (
    CLASS2_REQUIREMENTS,
    validate_player_pick_payload,
    check_composition,
)


# Load frozen bootstrap
BOOTSTRAP_PATH = Path(__file__).parent.parent.parent.parent / "field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json"
BOOTSTRAP = None


@pytest.fixture(scope="module", autouse=True)
def setup_bootstrap():
    """Load bootstrap exactly as the driver does (no reshaping)."""
    global BOOTSTRAP
    if BOOTSTRAP_PATH.exists():
        with open(BOOTSTRAP_PATH, encoding="utf-8") as f:
            BOOTSTRAP = json.load(f)


def _get_player(position: int, min_price: float, max_price: float, bootstrap=None, exclude_ids=None):
    """Find a player matching position and price range, optionally excluding specific IDs."""
    if bootstrap is None:
        bootstrap = BOOTSTRAP
    if exclude_ids is None:
        exclude_ids = set()
    for player in bootstrap.get("elements", []):
        if (
            int(player.get("element_type", 0) or 0) == position
            and player.get("status") == "a"
            and int(player.get("minutes", 0) or 0) > 0
            and min_price <= player.get("now_cost", 0) / 10.0 <= max_price
            and int(player.get("id")) not in exclude_ids
        ):
            return player
    return None


def _get_team_fixtures(team_id: int, bootstrap=None):
    """Get fixtures for a team from bootstrap.

    team_fixtures comes from json.load(), so its keys are STRINGS. Look up
    tolerantly (same pattern the grader uses) rather than assuming int keys —
    an int-only lookup silently returns [] and produces empty fixture evidence.
    """
    if bootstrap is None:
        bootstrap = BOOTSTRAP
    team_fixtures = bootstrap.get("team_fixtures", {})
    return team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []


HORIZON_GWS = [1, 2, 3, 4, 5]


def _build_correct_payload_q10(bootstrap=None):
    """Build a correct Q10 payload for testing."""
    if bootstrap is None:
        bootstrap = BOOTSTRAP

    # Find two DISTINCT players in the correct position and price range.
    # _get_player is deterministic (returns the first match), so the second
    # call must exclude the first — re-calling it unchanged in a loop never
    # terminates.
    p1 = _get_player(3, 6.0, 8.0, bootstrap)  # MID
    p2 = _get_player(3, 6.0, 8.0, bootstrap, exclude_ids={int(p1["id"])} if p1 else None)

    if not p1 or not p2:
        pytest.skip("Not enough eligible MIDs in bootstrap")
    assert int(p1["id"]) != int(p2["id"]), "recommendation and runner_up must be distinct"

    # Get fixtures for the primary recommendation.
    # team_fixtures entries are pre-built by fpl_pipeline.context._build_team_fixtures
    # with keys: gameweek, opponent_team, is_home, difficulty. opponent_team is
    # already resolved — there is no team_h/team_a branch to compute here.
    team_id = int(p1["team"])
    fixtures = _get_team_fixtures(team_id, bootstrap)
    by_gw = {f.get("gameweek"): f for f in fixtures}
    fixture_evidence = []
    for gw in HORIZON_GWS:
        fixture = by_gw.get(gw)
        if fixture is None:
            continue
        fixture_evidence.append({
            "team": team_id,
            "gameweek": fixture.get("gameweek"),
            "opponent_team": fixture.get("opponent_team"),
            "is_home": fixture.get("is_home"),
            "difficulty": fixture.get("difficulty"),
        })

    return {
        "question_class": "player_pick_price_range",
        "position": "MID",
        "price_range": [6.0, 8.0],
        "horizon_gws": list(HORIZON_GWS),
        "metric_used": "points_per_game",
        "ranking_basis": "prior_season_carryover",
        "candidates_considered": [int(p1["id"]), int(p2["id"])],
        "recommendation": {
            "id": int(p1["id"]),
            "quoted_price": p1.get("now_cost", 0) / 10.0,
        },
        "runner_up": {
            "id": int(p2["id"]),
            "quoted_price": p2.get("now_cost", 0) / 10.0,
        },
        "fixture_evidence": fixture_evidence,
    }


def test_grader_correct_q10(setup_bootstrap):
    """Verify grader passes a correct Q10 payload."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)

    # Guard: an empty-evidence payload must never be able to satisfy this test.
    # The int-key lookup bug produced exactly that, and it went unnoticed.
    assert len(payload["fixture_evidence"]) == 5, (
        f"expected 5 fixture_evidence entries, got {len(payload['fixture_evidence'])} "
        "— check the team_fixtures key type and field names"
    )
    assert all(e["opponent_team"] is not None for e in payload["fixture_evidence"])
    assert all(e["difficulty"] is not None for e in payload["fixture_evidence"])

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)

    assert result["status"] == "valid", f"Expected valid, got errors: {result['errors']}"
    assert result["valid"] is True
    assert not result["errors"]


def test_grader_wrong_position(setup_bootstrap):
    """Verify grader fails when recommendation has wrong position."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Find a player with wrong position
    for player in BOOTSTRAP.get("elements", []):
        if (
            int(player.get("element_type", 0) or 0) == 2  # DEF, not MID
            and player.get("status") == "a"
            and int(player.get("minutes", 0) or 0) > 0
            and 6.0 <= player.get("now_cost", 0) / 10.0 <= 8.0
        ):
            payload["recommendation"]["id"] = int(player["id"])
            break

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("wrong_position" in err for err in result["errors"])


def test_grader_price_out_of_range(setup_bootstrap):
    """Verify grader fails when recommendation is outside price range."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Find a MID outside the range
    for player in BOOTSTRAP.get("elements", []):
        if (
            int(player.get("element_type", 0) or 0) == 3  # MID
            and player.get("status") == "a"
            and int(player.get("minutes", 0) or 0) > 0
            and (player.get("now_cost", 0) / 10.0 < 6.0 or player.get("now_cost", 0) / 10.0 > 8.0)
        ):
            payload["recommendation"]["id"] = int(player["id"])
            payload["recommendation"]["quoted_price"] = player.get("now_cost", 0) / 10.0
            break

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("price_out_of_range" in err for err in result["errors"])


def test_grader_quoted_price_mismatch(setup_bootstrap):
    """Verify grader fails when quoted_price doesn't match bootstrap."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Tamper with the quoted price
    payload["recommendation"]["quoted_price"] = 9.99  # Wrong

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("quoted_price_mismatch" in err for err in result["errors"])


def test_grader_bad_horizon(setup_bootstrap):
    """Verify grader fails with wrong horizon GWs."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Tamper with horizon (only 4 GWs instead of 5)
    payload["horizon_gws"] = [1, 2, 3, 4]

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("horizon_mismatch" in err for err in result["errors"])


def test_grader_fixture_difficulty_mismatch(setup_bootstrap):
    """Verify grader fails when fixture_evidence has wrong difficulty."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Tamper with the difficulty of the first fixture
    if payload["fixture_evidence"]:
        payload["fixture_evidence"][0]["difficulty"] = 999  # Wrong

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("difficulty_mismatch" in err for err in result["errors"])


def test_grader_fixture_opponent_mismatch(setup_bootstrap):
    """Verify grader fails when fixture_evidence has wrong opponent_team."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Tamper with the opponent_team of the first fixture
    if payload["fixture_evidence"]:
        payload["fixture_evidence"][0]["opponent_team"] = 999  # Wrong

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("opponent_mismatch" in err for err in result["errors"])


def test_grader_fixture_venue_mismatch(setup_bootstrap):
    """Verify grader fails when fixture_evidence has wrong is_home."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Tamper with the is_home of the first fixture
    if payload["fixture_evidence"]:
        original_is_home = payload["fixture_evidence"][0]["is_home"]
        payload["fixture_evidence"][0]["is_home"] = not original_is_home  # Wrong

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("venue_mismatch" in err for err in result["errors"])


def test_grader_duplicate_candidates(setup_bootstrap):
    """Verify grader fails with duplicate candidates."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    # Duplicate a candidate
    payload["candidates_considered"] = [
        payload["candidates_considered"][0],
        payload["candidates_considered"][0],
    ]

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("duplicate_candidates" in err for err in result["errors"])


def test_grader_missing_ranking_basis(setup_bootstrap):
    """Verify grader fails when ranking_basis is missing."""
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    payload = _build_correct_payload_q10(BOOTSTRAP)
    del payload["ranking_basis"]

    result = validate_player_pick_payload("Q10", payload, BOOTSTRAP)
    assert result["status"] == "invalid"
    assert any("ranking_basis_missing" in err for err in result["errors"])


def test_get_player_honours_exclude_ids(setup_bootstrap):
    """Regression: the invariant the old retry-loop wrongly assumed.

    _get_player is deterministic — it returns the FIRST match. Calling it again
    with the same arguments can only return the same player, so a
    `while p2 == p1: p2 = _get_player(...)` loop never terminates. Distinctness
    must come from exclusion, and this pins that it actually works.
    """
    if BOOTSTRAP is None:
        pytest.skip("Bootstrap not available")

    p1 = _get_player(3, 6.0, 8.0, BOOTSTRAP)
    assert p1 is not None

    # Same call, no exclusion -> same player. This is why the loop hung.
    assert int(_get_player(3, 6.0, 8.0, BOOTSTRAP)["id"]) == int(p1["id"])

    # With exclusion -> a different player.
    p2 = _get_player(3, 6.0, 8.0, BOOTSTRAP, exclude_ids={int(p1["id"])})
    assert p2 is not None
    assert int(p2["id"]) != int(p1["id"])

    # Excluding both yields a third, never one of the excluded.
    p3 = _get_player(3, 6.0, 8.0, BOOTSTRAP, exclude_ids={int(p1["id"]), int(p2["id"])})
    if p3 is not None:
        assert int(p3["id"]) not in {int(p1["id"]), int(p2["id"])}


def test_no_unbounded_search_loops_in_this_module():
    """Structural guard: this file must contain no `while` loop.

    A hanging test reports nothing at all — it is indistinguishable from a suite
    that was never run, which is the failure mode that let the broken grader look
    green. Every search here is a bounded `for` over a finite collection or plain
    list indexing; keep it that way. If a `while` ever becomes genuinely
    necessary, give it an explicit iteration cap and update this guard.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    offenders = [
        (lineno, line.strip())
        for lineno, line in enumerate(source.splitlines(), start=1)
        if re.match(r"^\s*while\b", line)
    ]
    assert not offenders, f"unbounded search loop(s) found: {offenders}"


def test_composition_ranking_only_fails():
    """Verify composition check fails on ranking-only trace."""
    ranking_only = [
        {
            "name": "rank_players_by_metric",
            "args": {"metric": "points_per_game", "position": "MID", "min_price": 6.0, "max_price": 8.0},
            "status": "ok",
        }
    ]

    result = check_composition(ranking_only)
    assert result["status"] == "invalid"
    assert not result["valid"]
    assert any("fixture_grounding_missing" in err for err in result["errors"])


def test_composition_ranking_without_price_fails():
    """Verify composition check fails if ranking lacks price bounds."""
    bare_ranking = [
        {
            "name": "rank_players_by_metric",
            "args": {"metric": "points_per_game", "position": "MID"},  # No min_price/max_price
            "status": "ok",
        },
        {
            "name": "get_fixture_outlook",
            "args": {"axis": "attack", "horizon": 5},
            "status": "ok",
        },
    ]

    result = check_composition(bare_ranking)
    assert result["status"] == "invalid"
    assert not result["valid"]
    assert any("ranking_missing_or_unpriced" in err for err in result["errors"])


def test_composition_priced_ranking_plus_fixture_passes():
    """Verify composition check passes on priced-ranking + fixture-grounding trace."""
    two_tool_trace = [
        {
            "name": "rank_players_by_metric",
            "args": {"metric": "points_per_game", "position": "MID", "min_price": 6.0, "max_price": 8.0},
            "status": "ok",
        },
        {
            "name": "get_fixture_outlook",
            "args": {"axis": "attack", "horizon": 5},
            "status": "ok",
        },
    ]

    result = check_composition(two_tool_trace)
    assert result["status"] == "valid", f"Expected valid, got errors: {result['errors']}"
    assert result["valid"] is True
    assert not result["errors"]


def test_composition_fixture_calendar_alternative_passes():
    """Verify composition check passes with get_team_fixture_calendar instead of get_fixture_outlook."""
    two_tool_alt = [
        {
            "name": "rank_players_by_metric",
            "args": {"metric": "points_per_game", "position": "MID", "min_price": 6.0, "max_price": 8.0},
            "status": "ok",
        },
        {
            "name": "get_team_fixture_calendar",
            "args": {"horizon": 5},
            "status": "ok",
        },
    ]

    result = check_composition(two_tool_alt)
    assert result["status"] == "valid"
    assert result["valid"] is True
    assert not result["errors"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
