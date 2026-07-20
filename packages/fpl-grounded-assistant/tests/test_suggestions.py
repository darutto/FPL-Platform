"""
Tests for the Guided Comparison flow — additive ``suggestions`` payload.

Covers:
  * ranker ordering (transfers_in DESC), limit, deterministic tie-break
  * ranker tolerance of malformed / missing bootstrap data (never raises)
  * build_suggestions present on compare needs_clarification, None on OK
    outcomes and on non-compare intents
  * suggestions_to_list / build_suggestion_dicts serialization shape
  * real /ask wiring: ask_v2("/comparar") -> needs_clarification carries
    player_suggestions; to_ask_response maps them onto AskResponse.suggestions
  * OK compare (both players supplied) carries NO suggestions
  * serialization parity across the /ask (adapter, list[dict]) and
    /session (tuple[Suggestion] -> serializer) paths
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pytest

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
from fpl_grounded_assistant.suggestions import (  # noqa: E402
    Suggestion,
    top_transfer_names,
    build_suggestions,
    suggestions_to_list,
    build_suggestion_dicts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bootstrap_with_transfers() -> dict:
    """Bootstrap whose elements carry distinct transfers_in_event volumes."""
    return {
        "elements": [
            {"id": 1, "web_name": "Saka",    "transfers_in_event": 500},
            {"id": 2, "web_name": "Palmer",  "transfers_in_event": 900},
            {"id": 3, "web_name": "Haaland", "transfers_in_event": 300},
            {"id": 4, "web_name": "Salah",   "transfers_in_event": 700},
            {"id": 5, "web_name": "Isak",    "transfers_in_event": 100},
            {"id": 6, "web_name": "Watkins", "transfers_in_event": 800},
            {"id": 7, "web_name": "Foden",   "transfers_in_event": 200},
        ],
        "teams": [],
    }


# ---------------------------------------------------------------------------
# Ranker
# ---------------------------------------------------------------------------

def test_ranker_orders_by_transfers_in_descending():
    out = top_transfer_names(_bootstrap_with_transfers(), limit=6)
    labels = [d["label"] for d in out]
    assert labels == ["Palmer", "Watkins", "Salah", "Saka", "Haaland", "Foden"]


def test_ranker_label_equals_send_text_and_is_web_name():
    out = top_transfer_names(_bootstrap_with_transfers(), limit=3)
    for d in out:
        assert set(d.keys()) == {"label", "send_text"}
        assert d["label"] == d["send_text"]
    assert out[0]["label"] == "Palmer"


def test_ranker_respects_limit():
    assert len(top_transfer_names(_bootstrap_with_transfers(), limit=2)) == 2
    assert len(top_transfer_names(_bootstrap_with_transfers(), limit=100)) == 7


def test_ranker_deterministic_tie_break_by_id_ascending():
    bs = {"elements": [
        {"id": 9, "web_name": "Nine",  "transfers_in_event": 100},
        {"id": 2, "web_name": "Two",   "transfers_in_event": 100},
        {"id": 5, "web_name": "Five",  "transfers_in_event": 100},
    ]}
    labels = [d["label"] for d in top_transfer_names(bs, limit=3)]
    # Equal volume -> ascending id -> Two(2), Five(5), Nine(9)
    assert labels == ["Two", "Five", "Nine"]


def test_ranker_tolerates_malformed_data():
    bs = {"elements": [
        {"id": 1, "web_name": "Ok",   "transfers_in_event": 50},
        {"id": 2, "web_name": "",     "transfers_in_event": 999},   # empty name skipped
        {"id": 3, "transfers_in_event": 999},                       # no name skipped
        {"id": 4, "web_name": "Bad",  "transfers_in_event": "oops"},  # bad volume -> 0
        "garbage",                                                  # non-dict skipped
        None,                                                        # None skipped
        {"id": 6, "web_name": "Top",  "transfers_in_event": 1000},
    ]}
    labels = [d["label"] for d in top_transfer_names(bs, limit=10)]
    assert labels == ["Top", "Ok", "Bad"]


@pytest.mark.parametrize("bad", [None, {}, {"elements": None}, {"elements": "x"}, 42])
def test_ranker_never_raises_on_bad_bootstrap(bad):
    assert top_transfer_names(bad) == []


def test_ranker_non_positive_limit_returns_empty():
    assert top_transfer_names(_bootstrap_with_transfers(), limit=0) == []
    assert top_transfer_names(_bootstrap_with_transfers(), limit=-3) == []


def test_ranker_direction_out():
    bs = {"elements": [
        {"id": 1, "web_name": "A", "transfers_out_event": 10, "transfers_in_event": 0},
        {"id": 2, "web_name": "B", "transfers_out_event": 30, "transfers_in_event": 0},
        {"id": 3, "web_name": "C", "transfers_out_event": 20, "transfers_in_event": 0},
    ]}
    labels = [d["label"] for d in top_transfer_names(bs, direction="out")]
    assert labels == ["B", "C", "A"]


# ---------------------------------------------------------------------------
# build_suggestions — intent/outcome gating
# ---------------------------------------------------------------------------

def test_build_suggestions_present_on_compare_needs_clarification():
    sugs = build_suggestions("compare_players", "needs_clarification",
                             _bootstrap_with_transfers())
    assert sugs is not None
    assert all(isinstance(s, Suggestion) for s in sugs)
    assert sugs[0].label == "Palmer"
    assert len(sugs) == 6  # default limit


def test_build_suggestions_none_on_ok_outcome():
    assert build_suggestions("compare_players", "ok",
                             _bootstrap_with_transfers()) is None


def test_build_suggestions_none_on_other_intent():
    for intent in ("captain_score", "transfer_advice", "player_form", None):
        assert build_suggestions(intent, "needs_clarification",
                                 _bootstrap_with_transfers()) is None


def test_build_suggestions_none_when_no_players():
    assert build_suggestions("compare_players", "needs_clarification",
                             {"elements": []}) is None
    assert build_suggestions("compare_players", "needs_clarification", None) is None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def test_suggestions_to_list_shape():
    sugs = (Suggestion("Saka", "Saka"), Suggestion("Palmer", "Palmer"))
    assert suggestions_to_list(sugs) == [
        {"label": "Saka", "send_text": "Saka"},
        {"label": "Palmer", "send_text": "Palmer"},
    ]


def test_suggestions_to_list_none_and_empty():
    assert suggestions_to_list(None) is None
    assert suggestions_to_list(()) is None


def test_build_suggestion_dicts_matches_tuple_serialization():
    bs = _bootstrap_with_transfers()
    dicts = build_suggestion_dicts("compare_players", "needs_clarification", bs)
    tup = build_suggestions("compare_players", "needs_clarification", bs)
    assert dicts == suggestions_to_list(tup)
    assert dicts[0] == {"label": "Palmer", "send_text": "Palmer"}


# ---------------------------------------------------------------------------
# Real /ask wiring — ask_v2 + harness_adapter.to_ask_response
# ---------------------------------------------------------------------------

def _ask_request(question: str):
    from fpl_server import AskRequest  # noqa: PLC0415
    return AskRequest(question=question)


def test_ask_v2_bare_comparar_carries_player_suggestions():
    from fpl_grounded_assistant.harness import ask_v2  # noqa: PLC0415
    d = ask_v2("/comparar", _bootstrap_with_transfers())
    assert d["outcome"] == "needs_clarification"
    assert d["prompt_name"] == "comparar"
    ps = d["player_suggestions"]
    assert ps and ps[0] == {"label": "Palmer", "send_text": "Palmer"}


def test_ask_v2_partial_comparar_still_carries_suggestions():
    from fpl_grounded_assistant.harness import ask_v2  # noqa: PLC0415
    d = ask_v2("/comparar Saka", _bootstrap_with_transfers())
    assert d["outcome"] == "needs_clarification"
    assert d["player_suggestions"]


def test_ask_v2_non_compare_clarification_has_no_suggestions():
    from fpl_grounded_assistant.harness import ask_v2  # noqa: PLC0415
    d = ask_v2("/capitan", _bootstrap_with_transfers())  # missing 'player'
    assert d["outcome"] == "needs_clarification"
    assert d.get("player_suggestions") is None


def test_to_ask_response_maps_suggestions_onto_askresponse():
    from fpl_grounded_assistant.harness import ask_v2  # noqa: PLC0415
    from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: PLC0415
    d = ask_v2("/comparar", _bootstrap_with_transfers())
    resp = to_ask_response(d, _ask_request("/comparar"))
    assert resp.clarification_asked is True
    assert resp.suggestions is not None
    assert resp.suggestions[0] == {"label": "Palmer", "send_text": "Palmer"}


def test_to_ask_response_ok_turn_suggestions_none():
    """A deterministic OK turn (a @resource) carries no player suggestions."""
    from fpl_grounded_assistant.harness import ask_v2  # noqa: PLC0415
    from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: PLC0415
    d = ask_v2("@top_form", _bootstrap_with_transfers())
    assert d["outcome"] == "ok"
    assert d.get("player_suggestions") is None
    resp = to_ask_response(d, _ask_request("@top_form"))
    assert resp.suggestions is None


# ---------------------------------------------------------------------------
# Contract wiring: FinalResponse field default + session serializer parity
# ---------------------------------------------------------------------------

def test_final_response_suggestions_defaults_none():
    from fpl_grounded_assistant.final_response import FinalResponse  # noqa: PLC0415
    fr = FinalResponse(final_text="", outcome="ok", supported=True, intent="x",
                       review_passed=True, llm_used=False, debug=None)
    assert fr.suggestions is None


def test_session_and_ask_paths_produce_identical_wire_shape():
    """Adapter (list[dict]) and session serializer (tuple->list) must agree."""
    from fpl_server import _suggestions_meta_list  # noqa: PLC0415
    bs = _bootstrap_with_transfers()
    # /ask path shape
    ask_shape = build_suggestion_dicts("compare_players", "needs_clarification", bs)
    # /session path shape: FinalResponse holds a tuple[Suggestion]; serializer -> list[dict]
    tup = build_suggestions("compare_players", "needs_clarification", bs)
    session_shape = _suggestions_meta_list(tup)
    assert ask_shape == session_shape
    assert session_shape[0] == {"label": "Palmer", "send_text": "Palmer"}
