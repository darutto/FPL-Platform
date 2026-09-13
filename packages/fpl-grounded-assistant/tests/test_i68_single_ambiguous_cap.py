"""i68 -- one cap on ambiguous candidates, owned by the player registry.

``fpl_player_registry.MAX_AMBIGUOUS_CANDIDATES`` is the number. PR #214 (i67)
moved ``get_player_season_points`` and ``player_form`` onto it;
``get_player_history`` and ``get_player_snapshot`` kept a private
``_MAX_AMBIGUOUS_CANDIDATES = 5`` each, with docstrings saying "up to 5". Two
copies of a number is how two disambiguation paths end up offering a different
count for the same tie -- the exact drift i67 found in the candidate *shape*.

Two checks, deliberately at two levels:

*   **Source:** the numeric literal is written exactly once across the
    registry and the four tools. A reintroduced local copy fails this test by
    file name.
*   **Behaviour:** each of the four tools, handed more tied players than the
    cap, returns exactly the registry's number -- read from the registry at
    test time, never hard-coded here. Change the literal in ``resolution.py``
    and all four follow; a tool with its own copy does not.

Why the behaviour check is not a runtime monkeypatch of the registry value:
every tool binds the name at import time (``from fpl_player_registry import
MAX_AMBIGUOUS_CANDIDATES``, the pattern #214 chose) and ``candidate_dicts``
binds it as a default argument, so patching the registry attribute after
import reaches none of them. That is not a defect -- it is what a single
literal looks like in Python -- but it means the mutation that proves
single-ness is "edit the literal, re-run", which the source-level test pins.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import fpl_player_registry  # noqa: E402
from fpl_player_registry import MAX_AMBIGUOUS_CANDIDATES, resolution  # noqa: E402

# The package re-exports the tool FUNCTIONS under the module names, so a
# ``from fpl_grounded_assistant import get_player_snapshot`` yields the
# function; the modules are what the source and attribute checks need.
history_mod = importlib.import_module("fpl_grounded_assistant.get_player_history")
season_mod = importlib.import_module("fpl_grounded_assistant.get_player_season_points")
snapshot_mod = importlib.import_module("fpl_grounded_assistant.get_player_snapshot")
form_mod = importlib.import_module("fpl_grounded_assistant.player_form")


# ---------------------------------------------------------------------------
# Source: the literal exists once
# ---------------------------------------------------------------------------

_TOOL_MODULES = (history_mod, snapshot_mod, season_mod, form_mod)

#: An assignment of a NUMERIC literal to a name ending in MAX_AMBIGUOUS_CANDIDATES.
#: An alias (``_MAX = MAX_AMBIGUOUS_CANDIDATES``) is not a second number and is
#: deliberately not matched.
_LITERAL_DEFINITION = re.compile(
    r"^\s*_?MAX_AMBIGUOUS_CANDIDATES\s*(?::\s*int)?\s*=\s*\d+\s*(?:#.*)?$",
    re.MULTILINE,
)


def _literal_definitions(module) -> list[str]:
    source = Path(module.__file__).read_text(encoding="utf-8")
    return _LITERAL_DEFINITION.findall(source)


def test_the_registry_defines_the_number_once():
    assert len(_literal_definitions(resolution)) == 1


@pytest.mark.parametrize("module", _TOOL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_no_tool_keeps_its_own_copy_of_the_number(module):
    copies = _literal_definitions(module)
    assert copies == [], (
        f"{module.__name__} defines its own ambiguous-candidate cap: {copies}. "
        f"Import MAX_AMBIGUOUS_CANDIDATES from fpl_player_registry instead."
    )


def test_the_package_reexports_the_same_object_the_tools_import():
    assert fpl_player_registry.MAX_AMBIGUOUS_CANDIDATES == resolution.MAX_AMBIGUOUS_CANDIDATES
    assert history_mod.MAX_AMBIGUOUS_CANDIDATES == resolution.MAX_AMBIGUOUS_CANDIDATES
    assert snapshot_mod.MAX_AMBIGUOUS_CANDIDATES == resolution.MAX_AMBIGUOUS_CANDIDATES
    assert season_mod.MAX_AMBIGUOUS_CANDIDATES == resolution.MAX_AMBIGUOUS_CANDIDATES


# ---------------------------------------------------------------------------
# Behaviour: each tool caps at the registry's number
# ---------------------------------------------------------------------------

_TEAMS = [
    {"id": 1, "name": "Arsenal", "short_name": "ARS", "code": 3},
    {"id": 2, "name": "Aston Villa", "short_name": "AVL", "code": 7},
]
_ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP"},
    {"id": 2, "singular_name_short": "DEF"},
    {"id": 3, "singular_name_short": "MID"},
    {"id": 4, "singular_name_short": "FWD"},
]


def _tied_bootstrap(n: int) -> dict:
    """``n`` players who all resolve at rank 0 for the query "Silva"."""
    elements = [
        {"id": 100 + i, "first_name": "A", "second_name": f"Silva{i}",
         "web_name": "Silva", "team": 1 + (i % 2), "team_code": 3,
         "element_type": 3, "status": "a", "now_cost": 50,
         "selected_by_percent": "1.0", "form": "1.0", "total_points": 10 - i,
         "expected_goals": "0.1", "expected_assists": "0.1",
         "expected_goal_involvements": "0.2"}
        for i in range(n)
    ]
    return {"elements": elements, "teams": _TEAMS, "element_types": _ELEMENT_TYPES,
            "events": [{"id": 5, "is_current": True, "is_next": False, "finished": False}]}


def _via_snapshot(n: int) -> list:
    out = snapshot_mod.get_player_snapshot("Silva", bootstrap=_tied_bootstrap(n))
    assert out["status"] == "ambiguous"
    return out["candidates"]


def _via_history(n: int) -> list:
    out = history_mod.get_player_history("Silva", bootstrap=_tied_bootstrap(n))
    assert out["status"] == "ambiguous"
    return out["candidates"]


def _via_season_points(n: int) -> list:
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame([
        {"player_id": 100 + i, "web_name": "Silva", "first_name": "A",
         "second_name": f"Silva{i}", "element_type": 3, "team_id": 1 + (i % 2),
         "total_points": 10 - i}
        for i in range(n)
    ])
    out = season_mod._resolve_player_in_season("Silva", frame, {1: "ARS", 2: "AVL"})
    assert out["status"] == "ambiguous"
    return out["candidates"]


def _via_player_form(n: int) -> list:
    status, element, meta = form_mod._resolve_player("Silva", _tied_bootstrap(n))
    assert status == "ambiguous" and element is None
    return meta["candidates"]


_TOOLS = {
    "get_player_history": _via_history,
    "get_player_snapshot": _via_snapshot,
    "get_player_season_points": _via_season_points,
    "player_form": _via_player_form,
}


@pytest.mark.parametrize("tool", sorted(_TOOLS), ids=sorted(_TOOLS))
def test_more_ties_than_the_cap_returns_exactly_the_registrys_number(tool):
    candidates = _TOOLS[tool](MAX_AMBIGUOUS_CANDIDATES + 3)
    assert len(candidates) == MAX_AMBIGUOUS_CANDIDATES


@pytest.mark.parametrize("tool", sorted(_TOOLS), ids=sorted(_TOOLS))
def test_fewer_ties_than_the_cap_returns_them_all(tool):
    """The number is a cap, not a fixed count -- so the test above cannot be
    passed by a tool that always returns MAX_AMBIGUOUS_CANDIDATES rows."""
    candidates = _TOOLS[tool](MAX_AMBIGUOUS_CANDIDATES - 1)
    assert len(candidates) == MAX_AMBIGUOUS_CANDIDATES - 1
