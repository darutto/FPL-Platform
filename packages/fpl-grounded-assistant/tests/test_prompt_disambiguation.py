"""
Tests for the prompt-turn disambiguation wizard.

Regression context: `/comparar Palmer vs Saka` where "Palmer" matched two
players dead-ended on an English "Multiple players share the name…" sentence
with nothing to tap. Four layers each dropped the signal independently:

  1. fpl_tool_contract._resolve_with_status resolved the tied candidates and
     then threw them away, so no tool could offer chips.
  2. compare_players / get_transfer_advice / get_player_fixture_run re-projected
     the failed side without the candidates.
  3. harness.ask_v2's prompt branches overwrote the tool's status — expansion
     hard-coded "ok", dispatch collapsed everything non-ok to "error".
  4. The UI armed its pick-one wizard on intent == "player_snapshot" only.

These tests pin layers 1-3; the UI side is covered by
fpl-ui/__tests__/prompt-rewrite-wizard.test.tsx.
"""
from __future__ import annotations

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401

from fpl_grounded_assistant.comparison import compare_players  # noqa: E402
from fpl_grounded_assistant.harness import ask_v2  # noqa: E402
from fpl_grounded_assistant.prompt_disambiguation import (  # noqa: E402
    prompt_disambiguation_suggestions,
    rebuild_with_choice,
)
from fpl_grounded_assistant.suggestions import KIND_PROMPT_REWRITE  # noqa: E402
from fpl_grounded_assistant.transfer_advisor import get_transfer_advice  # noqa: E402
from fpl_tool_contract import tool_resolve_player  # noqa: E402


# ---------------------------------------------------------------------------
# Layer 1 — the resolver carries its tied candidates out
# ---------------------------------------------------------------------------

def test_resolve_player_ambiguous_carries_candidates(bootstrap):
    r = tool_resolve_player("Johnson", bootstrap)
    assert r["status"] == "ambiguous"
    assert {c["id"] for c in r["candidates"]} == {6, 7}
    # The full name is what a rewrite substitutes in, so it must be present
    # and must actually differ between the tied players.
    assert {c["name"] for c in r["candidates"]} == {"Adam Johnson", "Glen Johnson"}
    assert {c["team_short"] for c in r["candidates"]} == {"CHE", "MUN"}


def test_resolve_player_ok_and_not_found_carry_no_candidates(bootstrap):
    assert tool_resolve_player("Saka", bootstrap)["status"] == "ok"
    assert "candidates" not in tool_resolve_player("Saka", bootstrap)
    assert "candidates" not in tool_resolve_player("Nobody", bootstrap)


# ---------------------------------------------------------------------------
# Layer 2 — two-sided tools forward the failing side's candidates
# ---------------------------------------------------------------------------

def test_compare_players_forwards_candidates_for_either_side(bootstrap):
    left = compare_players("Johnson", "Saka", bootstrap)
    assert left["status"] == "ambiguous"
    assert left["error_player"] == "Johnson"
    assert {c["id"] for c in left["candidates"]} == {6, 7}

    right = compare_players("Saka", "Johnson", bootstrap)
    assert right["error_player"] == "Johnson"
    assert {c["id"] for c in right["candidates"]} == {6, 7}


def test_compare_players_not_found_has_no_candidates(bootstrap):
    r = compare_players("Nobody", "Saka", bootstrap)
    assert r["status"] == "not_found"
    assert "candidates" not in r


def test_transfer_advice_forwards_candidates(bootstrap):
    r = get_transfer_advice("Johnson", "Saka", bootstrap)
    assert r["status"] == "ambiguous"
    assert {c["id"] for c in r["candidates"]} == {6, 7}


# ---------------------------------------------------------------------------
# rebuild_with_choice — the rewrite itself
# ---------------------------------------------------------------------------

def test_rebuild_replaces_only_the_ambiguous_slot():
    assert rebuild_with_choice(
        "/comparar Johnson vs Saka", "comparar", "Johnson", "Adam Johnson",
    ) == "/comparar Adam Johnson vs Saka"
    assert rebuild_with_choice(
        "/comparar Saka vs Johnson", "comparar", "Johnson", "Adam Johnson",
    ) == "/comparar Saka vs Adam Johnson"


def test_rebuild_preserves_the_users_own_connector():
    """"y"/"por" must survive — re-rendering from parsed args would not."""
    assert rebuild_with_choice(
        "/comparar Saka y Johnson", "comparar", "Johnson", "Adam Johnson",
    ) == "/comparar Saka y Adam Johnson"
    assert rebuild_with_choice(
        "/transferencia Johnson por Saka", "transferencia", "Johnson", "Glen Johnson",
    ) == "/transferencia Glen Johnson por Saka"


def test_rebuild_handles_single_argument_prompts():
    assert rebuild_with_choice(
        "/capitan Johnson", "capitan", "Johnson", "Adam Johnson",
    ) == "/capitan Adam Johnson"


def test_rebuild_refuses_unsafe_inputs():
    """Every case here would produce a command that runs the wrong query."""
    # Named-flag form — the positional split does not apply.
    assert rebuild_with_choice(
        "/comparar a=Johnson b=Saka", "comparar", "Johnson", "Adam Johnson",
    ) is None
    # Not this prompt's slash form.
    assert rebuild_with_choice(
        "compare Johnson vs Saka", "comparar", "Johnson", "Adam Johnson",
    ) is None
    # Ambiguous query matches neither slot.
    assert rebuild_with_choice(
        "/comparar Salah vs Saka", "comparar", "Johnson", "Adam Johnson",
    ) is None
    # Nothing to substitute.
    assert rebuild_with_choice(
        "/comparar Johnson vs Saka", "comparar", "Johnson", "   ",
    ) is None


def test_rebuild_is_case_and_accent_insensitive_on_the_slot():
    assert rebuild_with_choice(
        "/comparar johnson vs Saka", "comparar", "Johnson", "Adam Johnson",
    ) == "/comparar Adam Johnson vs Saka"


# ---------------------------------------------------------------------------
# prompt_disambiguation_suggestions — chip construction
# ---------------------------------------------------------------------------

def test_no_chips_for_non_ambiguous_or_candidate_free_output():
    assert prompt_disambiguation_suggestions("/comparar A vs B", "comparar", {"status": "ok"}) is None
    assert prompt_disambiguation_suggestions("/comparar A vs B", "comparar", None) is None
    assert prompt_disambiguation_suggestions(
        "/comparar A vs B", "comparar",
        {"status": "ambiguous", "error_player": "A"},  # no candidates key
    ) is None
    assert prompt_disambiguation_suggestions(
        "/comparar A vs B", None, {"status": "ambiguous"},
    ) is None


def test_identical_names_fall_back_to_the_stable_id():
    """Two players sharing a full name would re-ambiguate on the re-send —
    the chip would loop the user back to the same message. The id cannot."""
    raw = {
        "status": "ambiguous",
        "error_player": "Johnson",
        "candidates": [
            {"id": 6, "name": "Adam Johnson", "web_name": "Johnson", "team_short": "CHE"},
            {"id": 7, "name": "Adam Johnson", "web_name": "Johnson", "team_short": "CHE"},
        ],
    }
    chips = prompt_disambiguation_suggestions("/comparar Johnson vs Saka", "comparar", raw)
    assert [c.send_text for c in chips] == [
        "/comparar 6 vs Saka",
        "/comparar 7 vs Saka",
    ]
    # ...and the labels must differ, or the user cannot tell the chips apart.
    assert len({c.label for c in chips}) == 2


# ---------------------------------------------------------------------------
# Layer 3 — ask_v2 reports the real outcome and attaches the chips
# ---------------------------------------------------------------------------

def test_expansion_prompt_reports_ambiguous_and_offers_chips(bootstrap):
    r = ask_v2("/comparar Johnson vs Saka", bootstrap)
    assert r["selected_tool"] == "compare_players"
    # Was hard-coded "ok" before the fix — the whole reason nothing downstream
    # could tell this turn apart from a successful comparison.
    assert r["outcome"] == "ambiguous"

    chips = r["player_suggestions"]
    assert [c["send_text"] for c in chips] == [
        "/comparar Adam Johnson vs Saka",
        "/comparar Glen Johnson vs Saka",
    ]
    assert all(c["kind"] == KIND_PROMPT_REWRITE for c in chips)
    assert {c["player_id"] for c in chips} == {6, 7}
    assert {c["label"] for c in chips} == {"Adam Johnson (CHE)", "Glen Johnson (MUN)"}


def test_dispatch_prompt_reports_ambiguous_and_offers_chips(bootstrap):
    """/calendarios is MODE_DISPATCH — a separate branch from /comparar's."""
    r = ask_v2("/calendarios Johnson", bootstrap)
    assert r["outcome"] == "ambiguous"
    assert [c["send_text"] for c in r["player_suggestions"]] == [
        "/calendarios Adam Johnson",
        "/calendarios Glen Johnson",
    ]


def test_tapping_a_chip_resolves_the_turn(bootstrap):
    """End-to-end: the chip's send_text must actually run the comparison the
    user asked for — both players, not a single-player lookup."""
    chip = ask_v2("/comparar Johnson vs Saka", bootstrap)["player_suggestions"][0]
    r = ask_v2(chip["send_text"], bootstrap)
    assert r["outcome"] == "ok"
    assert r["selected_tool"] == "compare_players"
    assert r["raw_output"]["query_a"] == "Adam Johnson"
    assert r["raw_output"]["query_b"] == "Saka"


def test_unambiguous_prompt_turn_is_unchanged(bootstrap):
    """The happy path must not grow chips or change its outcome."""
    r = ask_v2("/comparar Salah vs Saka", bootstrap)
    assert r["outcome"] == "ok"
    assert r.get("player_suggestions") is None
