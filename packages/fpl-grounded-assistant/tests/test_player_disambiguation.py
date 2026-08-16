"""
Tests for the player-name disambiguation wizard fix.

Covers:
  * get_player_snapshot(): a trailing team-code token (e.g. "Johnson CHE")
    narrows an ambiguous name match to exactly one player, without
    changing behavior for queries that already resolve uniquely or that
    end in an unknown/non-team token.
  * harness.ask_v2(): the orchestrator branch's outcome now reflects
    get_player_snapshot's own status (ambiguous/not_found/etc.) instead of
    always reporting "ok"; player_suggestions is populated from the
    ambiguous candidates for this tool specifically; every other
    orch-only tool's outcome is unchanged (still hard-coded "ok"),
    confirming the fix is scoped correctly.
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

import pytest

import fpl_grounded_assistant  # noqa: E402,F401

from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot  # noqa: E402
from fpl_grounded_assistant.harness import ask_v2  # noqa: E402
from fpl_grounded_assistant.orchestrator import OrchestratorResult  # noqa: E402


@pytest.fixture(autouse=True)
def _orch_flags(monkeypatch: "pytest.MonkeyPatch"):
    """Enable the orchestrator branch and stub the evaluator client so
    ask_v2() reaches the orch branch under test without any real network
    call -- mirrors tests/test_fi7c_existing_intent_evidence.py's fixture."""
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# get_player_snapshot() — team-hint disambiguation
# ---------------------------------------------------------------------------

def test_bare_ambiguous_name_unchanged(bootstrap):
    """Regression pin for the bug report itself: 'Johnson' alone is still
    ambiguous, listing both candidates."""
    r = get_player_snapshot("Johnson", bootstrap=bootstrap)
    assert r["status"] == "ambiguous"
    assert {c["web_name"] for c in r["candidates"]} == {"Johnson"}
    assert len(r["candidates"]) == 2


def test_team_hint_resolves_to_the_right_player(bootstrap):
    r = get_player_snapshot("Johnson CHE", bootstrap=bootstrap)
    assert r["status"] == "ok"
    assert r["player"]["web_name"] == "Johnson"
    assert r["player"]["team_short"] == "CHE"
    assert r["player"]["position"] == "MID"


def test_team_hint_resolves_the_other_candidate(bootstrap):
    r = get_player_snapshot("Johnson MUN", bootstrap=bootstrap)
    assert r["status"] == "ok"
    assert r["player"]["team_short"] == "MUN"
    assert r["player"]["position"] == "DEF"


def test_unknown_team_token_does_not_swallow_a_real_candidate(bootstrap):
    """A trailing token that isn't a real team code must not be silently
    stripped -- the query behaves exactly as if the extra word were part
    of an (unmatched) name, not as a disambiguator."""
    r = get_player_snapshot("Johnson XYZ", bootstrap=bootstrap)
    assert r["status"] == "not_found"


def test_unrelated_unique_query_unaffected(bootstrap):
    """Ordinary single-match queries are byte-for-byte unchanged."""
    r = get_player_snapshot("Haaland", bootstrap=bootstrap)
    assert r["status"] == "ok"
    assert r["player"]["web_name"] == "Haaland"


def test_team_hint_alone_with_no_name_falls_through(bootstrap):
    """A query that's just a team code (nothing to strip it from) must not
    crash or misbehave -- degrades to not_found like any other query with
    no name match."""
    r = get_player_snapshot("CHE", bootstrap=bootstrap)
    assert r["status"] in ("not_found", "ambiguous")


# ---------------------------------------------------------------------------
# harness.ask_v2() — outcome derivation + player_suggestions (orch path)
# ---------------------------------------------------------------------------

def _orch_result(tool: str, tool_output: dict) -> OrchestratorResult:
    return OrchestratorResult(
        question="controlled",
        tool_chosen=tool,
        tool_args={},
        tool_output=tool_output,
        answer_text=f"controlled answer for {tool}",
        llm_used=True,
        model="controlled",
        outcome="ok",  # the ORCHESTRATION succeeded -- a tool call completed
    )


def test_ambiguous_player_snapshot_reports_ambiguous_outcome(monkeypatch, bootstrap):
    candidates = [
        {"id": 6, "web_name": "Johnson", "team_short": "CHE", "position": "MID"},
        {"id": 7, "web_name": "Johnson", "team_short": "MUN", "position": "DEF"},
    ]
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch_result(
            "get_player_snapshot",
            {"status": "ambiguous", "query": "johnson", "candidates": candidates,
             "message": "Multiple players match 'johnson'. Please specify."},
        ),
    )
    result = ask_v2("johnson", bootstrap, orch_client=object())
    assert result["outcome"] == "ambiguous"
    suggestions = result["player_suggestions"]
    assert suggestions is not None
    assert len(suggestions) == 2
    assert suggestions[0] == {"label": "Johnson (CHE)", "send_text": "Johnson CHE"}
    assert suggestions[1] == {"label": "Johnson (MUN)", "send_text": "Johnson MUN"}


def test_ok_player_snapshot_has_no_suggestions(monkeypatch, bootstrap):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch_result(
            "get_player_snapshot",
            {"status": "ok", "player": {"id": 1, "web_name": "Haaland"}},
        ),
    )
    result = ask_v2("haaland", bootstrap, orch_client=object())
    assert result["outcome"] == "ok"
    assert result.get("player_suggestions") is None


def test_other_orch_tool_outcome_unaffected(monkeypatch, bootstrap):
    """Scope guard: a different orch-only tool returning a non-ok status
    must NOT start reporting it -- only get_player_snapshot's branch was
    touched. Confirms the fix doesn't silently change behavior elsewhere."""
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch_result(
            "get_zonal_opportunity",
            {"status": "missing_context", "message": "no tactical store"},
        ),
    )
    result = ask_v2("zonal test", bootstrap, orch_client=object())
    assert result["outcome"] == "ok"
    assert result.get("player_suggestions") is None


# ---------------------------------------------------------------------------
# harness.ask_v2() — find_players multi-match also arms the pick wizard
# (PR #120 wired only get_player_snapshot; the LLM sometimes picks
# find_players for the identical ambiguous-name query — this closes that gap)
# ---------------------------------------------------------------------------

def test_find_players_multi_match_arms_pick_wizard(monkeypatch, bootstrap):
    """find_players is a pure name-lookup tool, so >1 match is an ambiguous
    disambiguation. It must arm the SAME wizard as get_player_snapshot's
    'ambiguous' status instead of falling through to a dead-end plain-text
    list. Asserts on the wire AskResponse the frontend actually consumes:
    the pick wizard arms on intent==player_snapshot + suggestions."""
    from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: PLC0415
    import fpl_server  # noqa: PLC0415
    matches = [
        {"id": 10, "web_name": "João Pedro", "team_short": "CHE", "position": "FWD"},
        {"id": 11, "web_name": "Costinha",   "team_short": "BHA", "position": "DEF"},
    ]
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch_result(
            "find_players",
            {"status": "ok", "query": "joao pedro", "match_count": 2, "matches": matches},
        ),
    )
    ar = to_ask_response(ask_v2("joao pedro", bootstrap, orch_client=object()),
                         fpl_server.AskRequest(question="joao pedro"))
    assert ar.intent == "player_snapshot"     # frontend arms the pick wizard on this
    assert ar.outcome == "ambiguous"
    assert ar.suggestions is not None
    assert len(ar.suggestions) == 2
    assert ar.suggestions[0] == {"label": "João Pedro (CHE)", "send_text": "João Pedro CHE"}
    assert ar.suggestions[1] == {"label": "Costinha (BHA)", "send_text": "Costinha BHA"}


def test_find_players_single_match_does_not_arm_wizard(monkeypatch, bootstrap):
    """A unique name lookup via find_players is NOT ambiguous — no chips, no
    forced player_snapshot intent, outcome stays ok. Guards against turning
    every find_players result into a wizard."""
    from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: PLC0415
    import fpl_server  # noqa: PLC0415
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch_result(
            "find_players",
            {"status": "ok", "query": "haaland", "match_count": 1,
             "matches": [{"id": 1, "web_name": "Haaland", "team_short": "MCI", "position": "FWD"}]},
        ),
    )
    # Use a non-name conversational request so PR 2's deterministic bare-name
    # interception does not pre-empt this legacy orchestrator-path scope guard.
    ar = to_ask_response(ask_v2("player search request", bootstrap, orch_client=object()),
                         fpl_server.AskRequest(question="player search request"))
    assert ar.suggestions is None
    assert ar.outcome == "ok"
    assert ar.intent != "player_snapshot"   # find_players' own (unsupported) intent, untouched
