"""Steering "juega de defensa?" towards get_position_changes (local test 2026-11-03). No provider calls.

"¿De Cuyper juega de defensa?" ran get_player_snapshot and answered with FPL's label only, so the observed gap
(FPL position vs the position played in the announced lineups) never showed. The audit log's tool_calls proved the
choice. These pin the phrasings that belong to the lineup tool, and a pointer from the snapshot that does not name a
tool that may not be offered (same flag-neutral rule as test_involvement_steering_descriptions.py).
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.tool_schema_registry import (
    GET_PLAYER_SNAPSHOT_SCHEMA,
    GET_POSITION_CHANGES_SCHEMA,
    get_offered_tool_schemas,
)

PHRASES = [
    "juega de defensa", "de que juega X", "en que posicion juega X", "es X realmente defensa",
    "does X actually play as a defender", "what position does X really play",
]


@pytest.mark.parametrize("phrase", PHRASES)
def test_position_changes_claims_the_where_does_he_actually_play_phrasings(phrase):
    assert phrase in GET_POSITION_CHANGES_SCHEMA.description


def test_position_changes_keeps_its_original_triggers():
    d = GET_POSITION_CHANGES_SCHEMA.description
    assert "'cambio de posicion de X'" in d and "'quien lo sustituye'" in d and "'where does X play when Y is out'" in d


def test_snapshot_says_its_position_is_only_fpls_label_and_points_away_without_naming_a_tool():
    d = GET_PLAYER_SNAPSHOT_SCHEMA.description
    assert "Its position is only FPL's label" in d
    assert "'juega de defensa'" in d and "'what position does X play'" in d
    assert "lineup-based position tool" in d
    # get_position_changes may not be offered (FOOTBALL_INTELLIGENCE_ENABLED off): never name it from here.
    assert "get_position_changes" not in d
    assert GET_POSITION_CHANGES_SCHEMA not in get_offered_tool_schemas(False)
    assert GET_POSITION_CHANGES_SCHEMA in get_offered_tool_schemas(True)
