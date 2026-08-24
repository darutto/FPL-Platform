"""Structural integrity checks for the tool-routing measurement corpus.

These are cheap, offline sanity checks (no LLM calls) on the corpus data
itself: every referenced tool name is real, ids are unique, the pinned case
is present verbatim, and the control/ambiguous labelling is internally
consistent. They exist so a future edit to the corpus can't silently
introduce a typo'd tool name or an inconsistent control flag that would
quietly corrupt a paid measurement run.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tool_routing_corpus import CORPUS, FAMILIES, ZONAL_TOOLS, get_pinned_question  # noqa: E402

from fpl_grounded_assistant.tool_schema_registry import get_offered_tool_names  # noqa: E402


def _valid_tool_names() -> frozenset[str]:
    return get_offered_tool_names(False)


def test_corpus_is_nonempty():
    assert len(CORPUS) > 0


def test_ids_are_unique():
    ids = [entry["id"] for entry in CORPUS]
    assert len(ids) == len(set(ids)), "duplicate question ids in corpus"


def test_every_family_is_declared_and_populated():
    families_in_corpus = {entry["family"] for entry in CORPUS}
    assert families_in_corpus == set(FAMILIES)
    for family in FAMILIES:
        count = sum(1 for e in CORPUS if e["family"] == family)
        assert count > 0, f"family {family!r} has no questions"


def test_acceptable_tools_are_real_registered_tools():
    valid = _valid_tool_names()
    for entry in CORPUS:
        for tool in entry["acceptable_tools"]:
            assert tool in valid, f"{entry['id']}: {tool!r} is not a registered tool"


def test_acceptable_tools_never_includes_zonal_tools():
    for entry in CORPUS:
        overlap = set(entry["acceptable_tools"]) & ZONAL_TOOLS
        assert not overlap, f"{entry['id']} accepts a zonal tool {overlap} -- excluded by design"


def test_acceptable_tools_nonempty_and_deduplicated():
    for entry in CORPUS:
        tools = entry["acceptable_tools"]
        assert len(tools) >= 1, f"{entry['id']} has an empty acceptable set"
        assert len(tools) == len(set(tools)), f"{entry['id']} has duplicate tools in its acceptable set"


def test_control_flag_matches_single_tool_acceptable_set():
    for entry in CORPUS:
        is_single = len(entry["acceptable_tools"]) == 1
        assert entry["control"] == is_single, (
            f"{entry['id']}: control={entry['control']} but acceptable_tools has "
            f"{len(entry['acceptable_tools'])} entries"
        )


def test_exactly_one_pinned_question():
    pinned = [e for e in CORPUS if e.get("pinned")]
    assert len(pinned) == 1


def test_pinned_question_matches_task_brief_verbatim():
    pinned = get_pinned_question()
    assert pinned["question"] == (
        "evalúa mi equipo y qué tan buena idea es el bench boost en la fecha 2"
    )
    assert pinned["family"] == "chip_vs_gameweek"
    assert "get_chip_advice" in pinned["acceptable_tools"]
    # The documented wrong pick must never be listed as acceptable anywhere
    # in this bucket -- that would silently launder the known failure away.
    assert "get_gameweek_context" not in pinned["acceptable_tools"]


def test_chip_vs_gameweek_bucket_never_accepts_the_known_wrong_tool():
    for entry in CORPUS:
        if entry["family"] == "chip_vs_gameweek":
            assert "get_gameweek_context" not in entry["acceptable_tools"], (
                f"{entry['id']} accepts get_gameweek_context -- that is the documented "
                "wrong pick this bucket exists to catch, not a defensible alternative"
            )


def test_every_entry_has_a_note():
    for entry in CORPUS:
        assert entry.get("note"), f"{entry['id']} is missing its justification note"
