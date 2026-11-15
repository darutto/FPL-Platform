"""Steering towards get_player_involvement for touches / passes / key passes (local test 2026-11-03). No provider calls.

"Compara los toques y pases clave de Cole Palmer y Saka" ran get_player_snapshot twice. Locally the cause was the FI
flag (get_player_involvement was not offered at all); these pin the flag-neutral wording that keeps the two general
tools from claiming those metrics, whichever tool set the turn gets.
"""
from __future__ import annotations

import re

from fpl_grounded_assistant.tool_schema_registry import (
    COMPARE_PLAYERS_SCHEMA,
    GET_PLAYER_INVOLVEMENT_SCHEMA,
    GET_PLAYER_SNAPSHOT_SCHEMA,
    GET_POSITION_CHANGES_SCHEMA,
    get_offered_tool_schemas,
)

def test_snapshot_says_it_has_no_involvement_metrics():
    d = GET_PLAYER_SNAPSHOT_SCHEMA.description
    assert "It has no touches, passes, pass accuracy, key passes or backward passes." in d


def test_compare_players_says_its_comparison_is_the_captain_score_only():
    d = COMPARE_PLAYERS_SCHEMA.description
    assert "(position-aware captain score only; not touches or passes)" in d


def test_general_tools_never_name_a_tool_that_may_not_be_offered():
    # With FOOTBALL_INTELLIGENCE_ENABLED off, get_player_involvement is not in the tool list: pointing at it from an
    # always-offered description would send the model to a tool it cannot call.
    for schema in (GET_PLAYER_SNAPSHOT_SCHEMA, COMPARE_PLAYERS_SCHEMA):
        assert "get_player_involvement" not in schema.description
    assert GET_PLAYER_INVOLVEMENT_SCHEMA not in get_offered_tool_schemas(False)
    assert GET_PLAYER_INVOLVEMENT_SCHEMA in get_offered_tool_schemas(True)


def test_involvement_keeps_the_one_call_compare_instruction():
    d = GET_PLAYER_INVOLVEMENT_SCHEMA.description
    assert "To COMPARE TWO PLAYERS" in d and "ONE call with player=X and compare_player=Y" in d and "never two calls" in d
    assert all(m in d.lower() for m in ("touches", "key passes", "pass accuracy", "backward"))
    assert "compara Palmer y Saka" in GET_PLAYER_INVOLVEMENT_SCHEMA.parameters["properties"]["compare_player"]["description"]


def test_position_changes_english_calls_the_player_he():
    # Product decision 2026-11-07: English prose refers to a player as he/his/him, never they/their. The model
    # copies this wording into its answers.
    d = GET_POSITION_CHANGES_SCHEMA.description
    assert "his club's recent matches" in d and "his own earlier starts" in d and "most of his starts" in d
    # Quoted example phrases ('cuando no jugo Y', 'because of the move') are the user's or forbidden wording, not
    # ours. An apostrophe right after a letter (club's, Y's) is not a quote. "them"/"they" stay allowed for plural
    # things (the per-90 figures, the match counts); "their" only ever meant the player here.
    own_words = re.sub(r"(?<![A-Za-z])'.*?'(?![A-Za-z])", "", d)
    assert re.search(r"\b(he|his|him)\b", own_words)
    assert not re.search(r"\b(their|theirs|themselves)\b", own_words)
