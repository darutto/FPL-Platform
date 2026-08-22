"""``get_team_schedule`` must report ambiguity, not deny the team exists.

Before this fix, ``_resolve_team`` collapsed "zero matches" and "two matches"
into the same ``None``, so ``{"team_query": "man"}`` answered ``not_found``
with "No team found matching 'man'." — a true thing reported as false, while
``get_team_snapshot`` answered ``ambiguous`` for the same query. The product
contradicted itself depending on which tool the model happened to pick.

``_resolve_team_result`` now returns the outcome; ``_resolve_team`` is a thin
wrapper over it that still collapses ambiguous→``None`` for its four other
callers, whose behaviour must be byte-identical. Those callers are pinned
here through their own public surfaces, not by reading the wrapper.

Everything runs against the real frozen bootstrap artifact so no fixture can
invent a shape production never emits.
"""
from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PACKAGE_ROOT = _HERE.parent
_PACKAGES = _PACKAGE_ROOT.parent
_REPO_ROOT = _PACKAGES.parent

# The tool registry reaches across siblings pytest.ini does not list.
for _pkg in sorted(_PACKAGES.iterdir()):
    if _pkg.is_dir() and str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

from fpl_grounded_assistant.fixture_context import build_fixture_context
from fpl_grounded_assistant.renderer import render as render_tool_output
from fpl_grounded_assistant.team_fixture_calendar import (
    _resolve_team,
    _resolve_team_result,
    get_team_schedule,
)
from fpl_grounded_assistant.zonal_weakness_tool import _to_store_team

FROZEN = _REPO_ROOT / "field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json"

_EXP_PATH = _PACKAGE_ROOT / "scripts" / "run_agentic_loop_experiment.py"


def _load_experiment_module():
    spec = _ilu.spec_from_file_location("run_agentic_loop_experiment", _EXP_PATH)
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def frozen_bootstrap():
    """The real captured artifact — never a hand-built stand-in."""
    if not FROZEN.exists():
        pytest.skip(f"frozen bootstrap {FROZEN} not present")
    return _load_experiment_module()._load_bootstrap(FROZEN)


@pytest.fixture(scope="module")
def run_tool_fn():
    # The registry is populated as an import side-effect of the package.
    import fpl_grounded_assistant  # noqa: F401

    from fpl_tool_runner import run_tool

    return run_tool


# ---------------------------------------------------------------------------
# The defect itself, end to end through the runner
# ---------------------------------------------------------------------------

def test_ambiguous_team_query_is_not_reported_as_not_found(frozen_bootstrap, run_tool_fn):
    """"man" matches Man City AND Man Utd. Both exist; neither is 'not found'."""
    result = run_tool_fn(
        "get_team_schedule", {"team_query": "man", "horizon": 5}, frozen_bootstrap
    )

    assert result["status"] == "ambiguous", result
    assert result["team_query"] == "man"
    shorts = {c["short_name"] for c in result["candidates"]}
    assert {"MCI", "MUN"} <= shorts, shorts
    assert "No team found" not in result["message"]


def test_ambiguous_candidates_carry_short_name_and_name(frozen_bootstrap, run_tool_fn):
    result = run_tool_fn(
        "get_team_schedule", {"team_query": "man", "horizon": 5}, frozen_bootstrap
    )

    assert result["candidates"], "ambiguous with no candidates is useless to the caller"
    for candidate in result["candidates"]:
        assert set(candidate) == {"short_name", "name"}
        assert candidate["short_name"] and candidate["name"]


def test_schedule_and_snapshot_no_longer_contradict_each_other(frozen_bootstrap, run_tool_fn):
    """The whole point: two tools, same query, same verdict about existence."""
    schedule = run_tool_fn(
        "get_team_schedule", {"team_query": "man", "horizon": 5}, frozen_bootstrap
    )
    snapshot = run_tool_fn(
        "get_team_snapshot", {"team_name": "man"}, frozen_bootstrap
    )

    assert schedule["status"] == snapshot["status"] == "ambiguous"
    assert {c["short_name"] for c in schedule["candidates"]} == {
        c["short_name"] for c in snapshot["candidates"]
    }


def test_multi_word_ambiguity_lists_every_match(frozen_bootstrap, run_tool_fn):
    """"city" hits three clubs — the candidate list must not be truncated to two."""
    result = run_tool_fn(
        "get_team_schedule", {"team_query": "city", "horizon": 5}, frozen_bootstrap
    )

    assert result["status"] == "ambiguous", result
    shorts = {c["short_name"] for c in result["candidates"]}
    expected = {
        team["short_name"]
        for team in frozen_bootstrap["teams"]
        if "city" in team["name"].lower()
    }
    assert shorts == expected
    assert len(expected) >= 3, "frozen artifact no longer has a 3-way 'city' collision"


# ---------------------------------------------------------------------------
# Everything that resolved before must still resolve to the same team
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("query", "expected_short"),
    [
        ("Arsenal", "ARS"),           # exact name
        ("ARS", "ARS"),               # exact short_name
        ("liverpool", "LIV"),         # exact name, lowercased
        ("Spurs", "TOT"),             # exact short-name-adjacent
        ("Man Utd", "MUN"),           # exact name
        ("utd", "MUN"),               # alias map
        ("nott'm forest", "NFO"),     # alias map, punctuation
        ("aston villa fc", "AVL"),    # alias map, formal name
        ("newcastle", "NEW"),         # alias map
        ("villa", "AVL"),             # unique substring
        ("manchester city", "MCI"),   # alias map, disambiguating full name
    ],
)
def test_resolvable_queries_still_resolve_to_the_same_team(
    frozen_bootstrap, run_tool_fn, query, expected_short
):
    result = run_tool_fn(
        "get_team_schedule", {"team_query": query, "horizon": 5}, frozen_bootstrap
    )

    assert result["status"] == "ok", result
    assert result["team_short"] == expected_short


@pytest.mark.parametrize("query", ["zzz", "", "not a football club"])
def test_genuine_miss_is_still_not_found(frozen_bootstrap, run_tool_fn, query):
    result = run_tool_fn(
        "get_team_schedule", {"team_query": query, "horizon": 5}, frozen_bootstrap
    )

    assert result["status"] == "not_found", result
    assert "candidates" not in result


def test_alias_pointing_at_a_relegated_club_is_not_found(frozen_bootstrap):
    """"wolverhampton" is in the alias map but WOL is not in this season's
    bootstrap. That must stay ``not_found``, not become ``ambiguous``."""
    assert "WOL" not in {t["short_name"] for t in frozen_bootstrap["teams"]}

    assert _resolve_team_result("wolverhampton", frozen_bootstrap) == {"status": "not_found"}


# ---------------------------------------------------------------------------
# The wrapper contract the other five call sites depend on
# ---------------------------------------------------------------------------

def test_wrapper_collapses_ambiguous_and_not_found_to_none(frozen_bootstrap):
    assert _resolve_team("man", frozen_bootstrap) is None
    assert _resolve_team("zzz", frozen_bootstrap) is None


def test_wrapper_returns_the_bootstrap_dict_itself_on_ok(frozen_bootstrap):
    """Callers index ``team["id"]`` / ``team["short_name"]`` — the wrapper must
    hand back the bootstrap team dict, not a candidate summary."""
    team = _resolve_team("Arsenal", frozen_bootstrap)

    assert team is not None
    assert team is _resolve_team_result("Arsenal", frozen_bootstrap)["team_data"]
    assert team in frozen_bootstrap["teams"]
    assert int(team["id"]) and team["short_name"] == "ARS"


# ---------------------------------------------------------------------------
# The four other callers — pinned through their own surfaces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["man", "city", "zzz", "wolverhampton"])
def test_fixture_outlook_tool_unchanged_on_unresolvable_queries(
    frozen_bootstrap, run_tool_fn, query
):
    result = run_tool_fn(
        "get_fixture_outlook",
        {"team_query": query, "axis": "attack", "horizon": 5},
        frozen_bootstrap,
    )

    assert result["status"] == "not_found", result
    assert result["message"] == f"No team found matching '{query}'."


@pytest.mark.parametrize(("query", "expected_short"), [("Arsenal", "ARS"), ("villa", "AVL")])
def test_fixture_outlook_tool_unchanged_on_resolvable_queries(
    frozen_bootstrap, run_tool_fn, query, expected_short
):
    result = run_tool_fn(
        "get_fixture_outlook",
        {"team_query": query, "axis": "attack", "horizon": 5},
        frozen_bootstrap,
    )

    assert result["status"] == "ok", result
    assert result["team_short"] == expected_short


@pytest.mark.parametrize("query", ["man", "city", "zzz"])
def test_transfer_suggestion_unchanged_on_unresolvable_queries(
    frozen_bootstrap, run_tool_fn, query
):
    result = run_tool_fn(
        "get_transfer_suggestion",
        {"team_query": query, "position_query": "MID"},
        frozen_bootstrap,
    )

    assert result["status"] == "not_found", result


def test_transfer_suggestion_unchanged_on_resolvable_query(frozen_bootstrap, run_tool_fn):
    result = run_tool_fn(
        "get_transfer_suggestion",
        {"team_query": "Arsenal", "position_query": "MID"},
        frozen_bootstrap,
    )

    assert result["status"] == "ok", result
    assert result["team_short"] == "ARS"


@pytest.mark.parametrize("query", ["man", "city", "zzz"])
def test_build_fixture_context_still_returns_none_on_unresolvable(frozen_bootstrap, query):
    assert build_fixture_context(
        frozen_bootstrap, team_query=query, position="MID", horizon=5
    ) is None


def test_build_fixture_context_unchanged_on_resolvable(frozen_bootstrap):
    context = build_fixture_context(
        frozen_bootstrap, team_query="Arsenal", position="MID", horizon=5
    )

    assert context is not None
    assert context["team_short"] == "ARS"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("man", "man"),                    # unresolved → raw query passes through
        ("city", "city"),
        ("zzz", "zzz"),
        ("Arsenal", "Arsenal"),            # resolved → Understat name
        ("utd", "Manchester United"),
        ("spurs", "Tottenham"),
    ],
)
def test_zonal_store_team_bridge_unchanged(frozen_bootstrap, query, expected):
    """The zonal tools themselves answer ``missing_context`` without a tactical
    store, so pin the resolver-consuming helper directly — it is the caller,
    not the wrapper under test."""
    assert _to_store_team(query, frozen_bootstrap) == expected


# ---------------------------------------------------------------------------
# The new status must render, not fall through to the error branch
# ---------------------------------------------------------------------------

def test_ambiguous_schedule_renders_as_a_clarifying_question(frozen_bootstrap, run_tool_fn):
    result = run_tool_fn(
        "get_team_schedule", {"team_query": "man", "horizon": 5}, frozen_bootstrap
    )
    text = render_tool_output("get_team_schedule", result)

    assert "Error" not in text, text
    assert "MCI" in text and "MUN" in text
