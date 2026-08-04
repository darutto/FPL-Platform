"""
Regression: the per-module current-gameweek resolvers must delegate to the
canonical ``fpl_api_client.get_current_gameweek`` (``is_current → is_next →
None``), not re-implement an ``is_current``-only loop.

Background: six grounded-assistant modules each carried a private resolver that
checked ``is_current`` only. Pre-season / between-GW (the GW1-before-kickoff
state) no event is ``is_current`` — GW1 is ``is_next`` — so those copies returned
``None`` and downstream GW selection / venue adjustment silently no-op'd. This is
the same season-launch bug fixed for comparison/differential/transfer in #38.

Each resolver body is now a thin delegation whose only dependency is a local
``from fpl_api_client import get_current_gameweek``. We extract that function from
source and exec it in a clean namespace, giving real behavioural coverage for all
six without importing their heavy module graphs (fpl_tool_runner / captain engine
/ package ``__init__``), matching the standalone-load convention in this suite.
"""
from __future__ import annotations

import ast
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.join(os.path.dirname(_HERE), "fpl_grounded_assistant")

# (module file, resolver function name) — the six consolidated in PR A.
_RESOLVERS = [
    ("context_builder.py", "_get_current_gw"),
    ("chip_advisor.py", "_get_current_gameweek"),
    ("fixture_outlook.py", "_get_current_gameweek"),
    ("player_fixture_run.py", "_get_current_gameweek"),
    ("team_fixture_calendar.py", "_get_current_gameweek"),
    ("transfer_suggestion.py", "_get_current_gameweek"),
]


def _extract_resolver(filename: str, func_name: str):
    """Return the resolver function, exec'd standalone from its source segment."""
    path = os.path.join(_PKG, filename)
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            segment = ast.get_source_segment(src, node)
            assert segment is not None
            namespace: dict = {}
            # The def line annotates ``dict[str, Any]``; provide Any (no
            # ``from __future__`` in this synthetic namespace).
            exec("from typing import Any\n" + segment, namespace)
            return namespace[func_name]
    raise AssertionError(f"{func_name} not found in {filename}")


@pytest.fixture(params=_RESOLVERS, ids=[m for m, _ in _RESOLVERS])
def resolver(request):
    return _extract_resolver(*request.param)


def test_is_next_fallback_pre_season(resolver):
    """No is_current event, GW1 is is_next → returns 1 (not None). The fix."""
    bootstrap = {
        "events": [
            {"id": 1, "is_current": False, "is_next": True},
            {"id": 2, "is_current": False, "is_next": False},
        ]
    }
    assert resolver(bootstrap) == 1


def test_is_current_wins_over_next(resolver):
    """Both present on different events → is_current takes precedence."""
    bootstrap = {
        "events": [
            {"id": 5, "is_current": True, "is_next": False},
            {"id": 6, "is_current": False, "is_next": True},
        ]
    }
    assert resolver(bootstrap) == 5


def test_none_when_season_not_started_or_over(resolver):
    """No is_current and no is_next → None (season over / not started)."""
    bootstrap = {
        "events": [
            {"id": 1, "is_current": False, "is_next": False},
        ]
    }
    assert resolver(bootstrap) is None


def test_uses_supplied_bootstrap_no_live_api(resolver, monkeypatch):
    """The supplied bootstrap is used — the wrapper never triggers a live fetch.

    Canonical ``get_current_gameweek`` only calls ``get_bootstrap()`` when its
    argument is ``None``. Passing an explicit bootstrap must avoid any network
    call; we prove it by making ``get_bootstrap`` raise.
    """
    import fpl_api_client.fpl_client as fc

    def _boom(*_a, **_k):
        raise AssertionError("live API fetch attempted — bootstrap not passed through")

    monkeypatch.setattr(fc, "get_bootstrap", _boom)

    bootstrap = {"events": [{"id": 3, "is_current": True, "is_next": False}]}
    assert resolver(bootstrap) == 3


def test_canonical_contract_directly():
    """Pin the canonical resolver the six now delegate to."""
    from fpl_api_client import get_current_gameweek

    assert get_current_gameweek(
        {"events": [{"id": 7, "is_current": False, "is_next": True}]}
    ) == 7
    assert get_current_gameweek(
        {"events": [{"id": 8, "is_current": True}, {"id": 9, "is_next": True}]}
    ) == 8
    assert get_current_gameweek({"events": []}) is None
