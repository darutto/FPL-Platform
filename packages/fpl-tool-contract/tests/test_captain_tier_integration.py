"""Captain-tier integration coverage for the captain-score tools.

Ported from `fpl-grounded-assistant/run_phase2g_tests.py` sections F-O (Phase
2g), a standalone runner in no CI list that had been dead at import since the
bare-`python` collision (PR #68). These assertions live here rather than in
fpl-captain-engine because they exercise `tool_get_captain_score` /
`tool_rank_captain_candidates`, which belong to this package -- captain-engine
is a leaf and its tests must not import fpl_tool_contract.

Two of the runner's assertions (N1/N2, "tool contract shape unchanged") were
failing and are corrected here rather than ported verbatim. They pinned an
exact key set that had drifted in both directions:
  - `role_signals` was added to ok responses in Phase 5m and never added to the
    expectation
  - `derived_fields` was expected but is not produced anywhere in this package
The key sets below reflect the contract the code actually implements.
"""

from __future__ import annotations

import pytest

from fpl_captain_engine import ALL_TIERS
from fpl_tool_contract.tools import (
    tool_get_captain_score,
    tool_rank_captain_candidates,
)


_SCORE_OK_KEYS = {
    "status", "player_id", "web_name", "name", "team", "team_short",
    "position", "captain_score", "tier", "role_signals", "score_inputs",
    "time_context", "query",
}

_RANK_ENTRY_OK_KEYS = (_SCORE_OK_KEYS - {"time_context"}) | {"index", "rank"}

# Scores produced by the shared conftest bootstrap. Pinned so a change to the
# scoring formula or its inputs surfaces here rather than silently.
_EXPECTED = {
    "Salah":     (66.0, "safe"),
    "Haaland":   (60.0, "safe"),
    "Saka":      (47.0, "differential"),
    "De Bruyne": (18.0, "avoid"),
}


# ---------------------------------------------------------------------------
# tool_get_captain_score
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_ok_response_carries_a_valid_tier(name, bootstrap):
    result = tool_get_captain_score(name, bootstrap)
    assert result["status"] == "ok"
    assert "tier" in result
    assert isinstance(result["tier"], str)
    assert result["tier"] in ALL_TIERS


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_score_and_tier_values(name, bootstrap):
    expected_score, expected_tier = _EXPECTED[name]
    result = tool_get_captain_score(name, bootstrap)
    assert result["captain_score"] == expected_score
    assert result["tier"] == expected_tier


def test_ok_response_key_set(bootstrap):
    assert set(tool_get_captain_score("Salah", bootstrap)) == _SCORE_OK_KEYS


def test_score_inputs_shape(bootstrap):
    result = tool_get_captain_score("Salah", bootstrap)
    assert set(result["score_inputs"]) == {
        "form", "fixture_difficulty", "xgi_per_90", "minutes_risk",
    }


def test_tier_immediately_follows_captain_score(bootstrap):
    """Field order is part of the rendered contract -- tier reads as a
    qualifier on the score it follows."""
    keys = list(tool_get_captain_score("Salah", bootstrap))
    assert keys.index("tier") == keys.index("captain_score") + 1


def test_injured_player_is_avoid_but_still_resolves(bootstrap):
    """`avoid` is a recommendation label, not an error: De Bruyne resolves
    fine, he is simply a bad captain pick."""
    result = tool_get_captain_score("De Bruyne", bootstrap)
    assert result["status"] == "ok"
    assert result["tier"] == "avoid"


def test_not_found_response_has_no_tier(bootstrap):
    result = tool_get_captain_score("NonExistentPlayerXYZ9999", bootstrap)
    assert result["status"] == "not_found"
    assert "tier" not in result


# ---------------------------------------------------------------------------
# tool_rank_captain_candidates
# ---------------------------------------------------------------------------

@pytest.fixture()
def ranked(bootstrap):
    return tool_rank_captain_candidates(
        [{"query": name} for name in ["Salah", "Haaland", "Saka", "De Bruyne"]],
        bootstrap,
    )


def test_rank_result_shape(ranked):
    assert set(ranked) >= {"status", "ranked_candidates", "total", "error_count"}
    assert ranked["status"] == "ok"
    assert ranked["total"] == 4
    assert ranked["error_count"] == 0
    assert isinstance(ranked["ranked_candidates"], list)
    assert len(ranked["ranked_candidates"]) == 4


def test_rank_entry_key_set(ranked):
    assert set(ranked["ranked_candidates"][0]) == _RANK_ENTRY_OK_KEYS


def test_every_ok_entry_has_a_valid_tier(ranked):
    for entry in ranked["ranked_candidates"]:
        assert entry["tier"] in ALL_TIERS


def test_rank_entry_tier_values(ranked):
    by_name = {e["web_name"]: e for e in ranked["ranked_candidates"]}
    for name, (expected_score, expected_tier) in _EXPECTED.items():
        assert by_name[name]["captain_score"] == expected_score
        assert by_name[name]["tier"] == expected_tier


def test_tier_does_not_affect_rank_ordering(ranked):
    """Ordering is by captain_score descending; tier is a label applied after,
    so an `avoid` player still appears in the ranking at its scored position."""
    scores = [e["captain_score"] for e in ranked["ranked_candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert ranked["ranked_candidates"][0]["rank"] == 1

    by_name = {e["web_name"]: e for e in ranked["ranked_candidates"]}
    assert by_name["De Bruyne"]["tier"] == "avoid"
    assert by_name["De Bruyne"] in ranked["ranked_candidates"]


def test_tier_absent_from_non_ok_entries(bootstrap):
    result = tool_rank_captain_candidates(
        [{"query": "Salah"}, {"query": "NonExistentPlayerXYZ9999"}],
        bootstrap,
    )
    ok_entries = [e for e in result["ranked_candidates"] if e["status"] == "ok"]
    non_ok = [e for e in result["ranked_candidates"] if e["status"] != "ok"]

    assert len(ok_entries) == 1
    assert len(non_ok) == 1
    assert non_ok[0]["status"] == "not_found"
    assert "tier" not in non_ok[0]
    assert all("tier" in e for e in ok_entries)
