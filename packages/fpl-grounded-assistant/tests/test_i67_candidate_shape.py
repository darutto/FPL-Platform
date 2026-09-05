"""i67 — an ambiguous answer must carry chips the user can actually tap.

The defect was never in the chip builder. ``suggestions.py`` formats
``f"{web_name} ({team_short})"`` correctly; it was handed a candidate with no
``team_short`` and printed exactly what it was given: **"Salah ()"**. So every
assertion here bites at the CALLER — the tool that builds the candidate — and
the end-to-end label is checked through the real builder, never re-implemented.

A test over the formatter alone would pass with the bug fully intact. That is
the whole point of this file.

Two sites, both verified against main on 2026-09-05:

*   ``get_player_season_points`` sent the numeric ``team_id`` where the chip
    reads ``team_short`` -> "Salah ()", and a ``send_text`` of just "Salah",
    which re-triggers the same ambiguity the chip was offering to resolve.
*   ``player_form`` returned the ambiguous status BARE, with no candidates at
    all, so no chip could be built and the conversation dead-ended.

A third site (``football_intelligence_runtime``) has the same bare-return shape
and is deliberately NOT fixed here — it is recorded on the card instead. Two
sites verified beat three half-done.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from fpl_grounded_assistant.suggestions import player_disambiguation_suggestions
from fpl_player_registry import (
    MAX_AMBIGUOUS_CANDIDATES,
    candidate_dict,
    candidate_dicts,
)


def _labels(candidates):
    """The chips a real caller would show, through the real builder."""
    suggestions = player_disambiguation_suggestions(candidates)
    return [s.label for s in (suggestions or ())]


# ---------------------------------------------------------------------------
# The shape itself
# ---------------------------------------------------------------------------

def test_the_constructor_produces_a_label_the_user_can_read():
    chips = _labels([
        candidate_dict(player_id=1, web_name="Salah", team_short="LIV", position="MID"),
        candidate_dict(player_id=2, web_name="Salah", team_short="BOU", position="FWD"),
    ])
    assert chips == ["Salah (LIV)", "Salah (BOU)"]


def test_a_team_id_where_team_short_belongs_is_the_visible_failure():
    """Pinning the defect itself: this is what the old caller produced."""
    assert _labels([{"id": 1, "web_name": "Salah", "team_id": 14}]) == ["Salah ()"]


def test_an_empty_label_also_breaks_the_send_text():
    """Worse than cosmetic: the chip loops.

    With no team code the chip sends back the bare name, which resolves to the
    same tie it was offering to break -- an infinite polite loop.
    """
    bad = player_disambiguation_suggestions([{"id": 1, "web_name": "Salah", "team_id": 14}])
    good = player_disambiguation_suggestions([
        candidate_dict(player_id=1, web_name="Salah", team_short="LIV")
    ])
    assert bad[0].send_text == "Salah"          # re-triggers the ambiguity
    assert good[0].send_text == "Salah LIV"     # resolves it


def test_one_cap_for_every_ambiguity_path():
    class _Rec:
        def __init__(self, i):
            self.id, self.web_name, self.team_short_name = i, f"P{i}", "LIV"
            self.element_type, self.first_name, self.second_name = 3, "A", f"B{i}"

    class _Match:
        def __init__(self, i):
            self.record, self.rank, self.total_points = _Rec(i), 0, 0

    built = candidate_dicts([_Match(i) for i in range(20)])
    assert len(built) == MAX_AMBIGUOUS_CANDIDATES


# ---------------------------------------------------------------------------
# Caller 1: get_player_season_points (parquet path)
# ---------------------------------------------------------------------------

@pytest.fixture
def season_frame():
    pd = pytest.importorskip("pandas")
    return pd.DataFrame([
        {"player_id": 1, "web_name": "Salah", "first_name": "Mohamed",
         "second_name": "Salah", "element_type": 3, "team_id": 14, "total_points": 200},
        {"player_id": 2, "web_name": "Salah", "first_name": "Amine",
         "second_name": "Salah", "element_type": 4, "team_id": 3, "total_points": 12},
    ])


def test_season_points_sends_the_club_code_not_its_number(season_frame):
    from fpl_grounded_assistant.get_player_season_points import _resolve_player_in_season

    resolved = _resolve_player_in_season("Salah", season_frame, {14: "LIV", 3: "BOU"})

    assert resolved["status"] == "ambiguous"
    assert _labels(resolved["candidates"]) == ["Salah (LIV)", "Salah (BOU)"]
    # The regression, stated as data rather than as a rendered string.
    assert all("team_id" not in c for c in resolved["candidates"])
    assert [c["team_short"] for c in resolved["candidates"]] == ["LIV", "BOU"]


def test_season_points_without_a_team_map_degrades_visibly(season_frame):
    """No club codes available -> empty codes, not a crash and not a number.

    The tool is still wrong-looking here, which is correct: it is better for a
    missing map to look missing than for an id to masquerade as a club.
    """
    from fpl_grounded_assistant.get_player_season_points import _resolve_player_in_season

    resolved = _resolve_player_in_season("Salah", season_frame, None)
    assert [c["team_short"] for c in resolved["candidates"]] == ["", ""]


# ---------------------------------------------------------------------------
# Caller 2: player_form (bare ambiguous return)
# ---------------------------------------------------------------------------

def test_player_form_carries_its_tied_players(monkeypatch):
    """The conversation must not dead-end on "aclara a quién te refieres" when
    the tied players were already computed one frame down the stack."""
    import fpl_grounded_assistant.player_form as pf

    elements = [
        {"id": 1, "web_name": "Salah", "first_name": "Mohamed",
         "second_name": "Salah", "element_type": 3, "team": 14},
        {"id": 2, "web_name": "Salah", "first_name": "Amine",
         "second_name": "Salah", "element_type": 4, "team": 3},
    ]
    teams = [{"id": 14, "short_name": "LIV"}, {"id": 3, "short_name": "BOU"}]
    bootstrap = {"elements": elements, "teams": teams}

    monkeypatch.setattr("fpl_api_client.fpl_client.get_players", lambda b: elements)
    monkeypatch.setattr("fpl_api_client.fpl_client.get_teams", lambda b: teams)

    status, element, meta = pf._resolve_player("Salah", bootstrap)
    assert status == "ambiguous"
    assert element is None
    assert _labels(meta["candidates"]) == ["Salah (LIV)", "Salah (BOU)"]


def test_player_form_tool_result_carries_them_too(monkeypatch):
    """The fix has to survive the tool boundary: the chips are built from what
    the tool RETURNS, not from what its private resolver knew."""
    import fpl_grounded_assistant.player_form as pf

    monkeypatch.setattr(
        pf, "_resolve_player",
        lambda query, bootstrap: (
            "ambiguous", None,
            {"candidates": [
                candidate_dict(player_id=1, web_name="Salah", team_short="LIV"),
                candidate_dict(player_id=2, web_name="Salah", team_short="BOU"),
            ]},
        ),
    )
    out = pf.get_player_form("Salah", {"elements": [], "teams": []})
    assert out["status"] == "ambiguous"
    assert _labels(out["candidates"]) == ["Salah (LIV)", "Salah (BOU)"]


def test_not_found_still_offers_nothing(monkeypatch):
    """No candidates key when there is nothing to choose between -- an empty
    chip row is its own kind of lie."""
    import fpl_grounded_assistant.player_form as pf

    monkeypatch.setattr(pf, "_resolve_player", lambda q, b: ("not_found", None, {}))
    out = pf.get_player_form("Nobody", {"elements": [], "teams": []})
    assert out["status"] == "not_found"
    assert "candidates" not in out


# ---------------------------------------------------------------------------
# The shape has one owner
# ---------------------------------------------------------------------------

def test_the_tool_contract_delegates_instead_of_keeping_a_copy():
    """fpl-tool-contract used to build the dict itself. Its shape was right,
    but a second copy is how copies drift -- and one of them did."""
    from fpl_tool_contract import tools

    source = Path(tools.__file__).read_text(encoding="utf-8")
    assert "candidate_dicts(matches" in source
    assert '"team_short":  match.record.team_short_name' not in source
