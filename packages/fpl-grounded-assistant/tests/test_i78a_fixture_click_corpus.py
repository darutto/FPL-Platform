"""i78-A: the fixture-click routing corpus and its read-out.

Two things are pinned here, neither of which makes a network call:

1. The corpus the measurement runs on is the generated contract file
   (field-notes/artifacts/i78a-canonical-phrases.json, produced by the fpl-ui
   jest test from ``teamOutlookQuestion`` / ``fixtureCellQuestion``), loaded
   with the labels the analyzer relies on -- and it stays OUT of ``CORPUS``,
   which the golden battery consumes verbatim as a paid run.
2. The analyzer's decision rule: 3/3 first-tool hits with no gameweek dump
   anywhere is a hit; anything less is a miss; a control whose majority lands
   in a touched tool it does not accept is a migration. Synthetic rows, so a
   read-out that silently stopped counting would fail here rather than print
   a clean matrix over a broken run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tool_routing_corpus as corpus  # noqa: E402
import analyze_i78a_fixture_click_routing as analyzer  # noqa: E402


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def test_contract_file_exists_and_is_generated_not_typed():
    data = corpus.load_i78a_canonical_phrases()
    assert data["source"] == "packages/fpl-ui/lib/fixture-chat-links.ts"
    assert data["generated_by"].endswith("fixture-chat-links-canonical.test.ts")
    assert "GENERATED" in data["note"]


def test_fixture_click_corpus_shape_and_labels():
    # 28 while the cell phrase was per axis; 20 since i93-b made the cell
    # tap one phrase asking both sides (4 teams x {2 team-row axes, cell,
    # DGW cell, future cell}).
    entries = corpus.i78a_fixture_click_corpus()
    assert len(entries) == 20
    assert len({e["id"] for e in entries}) == 20
    assert len({e["question"] for e in entries}) == 20
    kinds = {e["i78a"]["kind"] for e in entries}
    assert kinds == {"teamOutlookQuestion", "fixtureCellQuestion"}
    for e in entries:
        assert e["family"] == "fixture_click"
        assert e["control"] is True
        assert e["acceptable_tools"] == [corpus.I78A_EXPECTED_TOOL]
        assert e["forbidden_tools"] == [corpus.I78A_FORBIDDEN_TOOL]
        assert e["i78a"]["axis"] in ("attack", "defence", "both")
        # The phrase is what the UI would insert: it names the team.
        assert e["question"]
        if e["i78a"]["kind"] == "fixtureCellQuestion":
            assert e["i78a"]["axis"] == "both"          # i93-b
            assert f"J{e['i78a']['gameweek']}" in e["question"]
            assert ("doble jornada" in e["question"]) == bool(e["i78a"]["is_dgw"])


def test_fixture_click_family_is_not_in_the_golden_corpus():
    # scripts/golden_axes.py reuses CORPUS verbatim as a paid run; the i78-A
    # phrases are selected by their own driver instead.
    assert not any(q.get("family") == "fixture_click" for q in corpus.CORPUS)
    assert "fixture_click" not in corpus.FAMILIES


def test_controls_resolve_from_the_shared_corpus_in_declared_order():
    controls = corpus.i78a_controls()
    assert [c["id"] for c in controls] == list(corpus.I78A_CONTROL_IDS)
    # sh-c04 is the positive control for the narrowed get_fixtures_for_gw.
    sh_c04 = next(c for c in controls if c["id"] == "sh-c04")
    assert "get_fixtures_for_gw" in sh_c04["acceptable_tools"]


def test_missing_contract_file_names_the_regeneration_command(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        corpus.load_i78a_canonical_phrases(tmp_path / "nope.json")
    assert "I78A_WRITE_CANONICAL_PHRASES=1" in str(exc.value)


# ---------------------------------------------------------------------------
# Analyzer decision rule
# ---------------------------------------------------------------------------

def _row(qid: str, seq: list[str], *, family: str = "fixture_click",
         kind: str = "fixtureCellQuestion", cell: str | None = "current",
         acceptable: list[str] | None = None, forbidden: list[str] | None = None) -> dict:
    return {
        "question_id": qid, "family": family, "question": qid,
        "tool_sequence": seq, "tool_chosen": seq[0] if seq else None,
        "acceptable_tools": acceptable or ["get_fixture_outlook"],
        "forbidden_tools": forbidden or ["get_fixtures_for_gw"],
        "i78a": {"kind": kind, "cell_position": cell} if family == "fixture_click" else None,
        "cost_usd": 0.001, "exception": None, "provider": "p", "model": "m",
        "corpus_sha256": {"x": "y"},
    }


def test_three_of_three_with_no_dump_is_a_hit():
    rows = [_row("a", ["get_fixture_outlook"]) for _ in range(3)]
    s = analyzer.summarize(rows)
    assert s["by_kind"]["fixtureCellQuestion"] == (1, 1, 1)
    assert s["dump_rows"] == 0


def test_two_of_three_is_a_miss_even_though_i82_would_call_it_a_hit():
    rows = [_row("a", ["get_fixture_outlook"]), _row("a", ["get_fixture_outlook"]),
            _row("a", ["get_fixtures_for_gw"])]
    s = analyzer.summarize(rows)
    assert s["by_kind"]["fixtureCellQuestion"] == (0, 1, 0)
    assert s["dump_rows"] == 1


def test_dump_later_in_the_sequence_still_fails_the_phrase():
    rows = [_row("a", ["get_fixture_outlook"]), _row("a", ["get_fixture_outlook"]),
            _row("a", ["get_fixture_outlook", "get_fixtures_for_gw"])]
    s = analyzer.summarize(rows)
    hits, n, reached = s["by_kind"]["fixtureCellQuestion"]
    assert (hits, n) == (0, 1)
    assert reached == 1, "the expected tool WAS reached in every run -- reported separately"
    assert s["dump_rows"] == 1


def test_future_cells_are_reported_as_their_own_kind():
    rows = [_row("f", ["get_fixture_outlook"], cell="future") for _ in range(3)]
    s = analyzer.summarize(rows)
    assert s["by_kind"] == {"fixtureCellQuestion (future cell)": (1, 1, 1)}


def test_control_majority_into_a_touched_tool_is_a_migration():
    rows = [
        _row("tf-03", ["get_fixture_outlook"], family="team_fixtures", kind="", cell=None,
             acceptable=["get_team_schedule"], forbidden=[]),
        _row("tf-03", ["get_fixture_outlook"], family="team_fixtures", kind="", cell=None,
             acceptable=["get_team_schedule"], forbidden=[]),
        _row("tf-03", ["get_team_schedule"], family="team_fixtures", kind="", cell=None,
             acceptable=["get_team_schedule"], forbidden=[]),
    ]
    s = analyzer.summarize(rows)
    assert [m[0] for m in s["migrations_touched"]] == ["tf-03"]
    assert s["migrations_forbidden"] == []


def test_control_that_keeps_its_tool_is_not_a_migration():
    rows = [
        _row("sh-c04", ["get_fixtures_for_gw"], family="season_history", kind="", cell=None,
             acceptable=["get_fixtures_for_gw", "get_gameweek_context"],
             forbidden=["get_historical_gameweek_top_scorer"])
        for _ in range(3)
    ]
    s = analyzer.summarize(rows)
    assert s["migrations_touched"] == []
    assert s["migrations_forbidden"] == []
    assert s["control_table"][0][2] == 3  # 3 of 3 acceptable


def test_control_majority_into_an_i82_forbidden_tool_is_still_reported():
    rows = [
        _row("sh-c01", ["get_player_season_points"], family="season_history", kind="", cell=None,
             acceptable=["get_player_snapshot"], forbidden=["get_player_season_points"])
        for _ in range(2)
    ] + [
        _row("sh-c01", ["get_player_snapshot"], family="season_history", kind="", cell=None,
             acceptable=["get_player_snapshot"], forbidden=["get_player_season_points"])
    ]
    s = analyzer.summarize(rows)
    assert [m[0] for m in s["migrations_forbidden"]] == ["sh-c01"]
    assert s["migrations_touched"] == []
