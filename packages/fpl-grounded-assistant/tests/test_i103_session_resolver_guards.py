"""
i103 -- the session resolver does not rewrite what it cannot resolve.

Measured cause (i100, field-notes/artifacts/i100-session-route-parity-2026-09-18.jsonl):
on a FIRST turn with an empty session, the Phase 4f LLM reference resolver
rewrote 30/90 calendar phrases to ``tell me about <team>`` (2 of them
``tell me about null``), every one of them with ``resolver_source="llm"``,
and the rewritten question then chose ``get_team_snapshot`` where /ask chose
``get_fixture_outlook``.  Three independent guards, each pinned here on its
own so removing one kills only its tests:

(a) ``ConversationSession.respond`` does not call ``resolve_reference`` when
    ``ConversationState.has_resolvable_context()`` is False -- the question
    reaches ``ask_v2`` verbatim, as it does on /ask.  With context present
    (a last player) the resolver IS still called: follow-ups stay alive.
(b) ``resolve_reference_llm`` normalises ``"null"``/``"none"``/blank to
    ``None`` at the parse edge, and validates a real ``resolved_query``
    against ``bootstrap["elements"]`` (shared registry matcher) BEFORE any
    player template is built.  A team name never becomes
    ``tell me about <team>``; ``fallback_reason="resolved_query_not_a_player"``.
(c) the resolver model is ``FPL_RESOLVER_MODEL`` read at call time, else
    ``DEFAULT_MODEL``; changing the env after import is honoured.

Every assertion reads what was produced (the question that reached ask_v2,
the ``rewritten_question`` on the resolution, the ``model`` kwarg the client
received) -- never the variable that requested it.
"""
from __future__ import annotations

import json
import os as _os
import sys as _sys
from unittest.mock import patch

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
from fpl_grounded_assistant import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.conversation_state import (  # noqa: E402
    ConversationSession,
    ConversationState,
)
from fpl_grounded_assistant import reference_resolver as rr  # noqa: E402
from fpl_grounded_assistant.reference_resolver import (  # noqa: E402
    ReferenceResolution,
    resolve_reference,
    resolve_reference_llm,
    resolver_model,
)

# One of the 20 canonical calendar phrases the /fixtures UI sends (i78-A);
# the kind that the resolver rewrote to "tell me about Newcastle" in prod.
_CALENDAR_PHRASE = "¿Cómo pinta el calendario ofensivo del Newcastle en las próximas jornadas?"


# ---------------------------------------------------------------------------
# Mocks -- Anthropic-shaped client, as run_phase4f_tests.py uses
# ---------------------------------------------------------------------------

class _Content:
    def __init__(self, text: str) -> None:
        self.text = text


class _Message:
    def __init__(self, text: str) -> None:
        self.content = [_Content(text)]


class _Messages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Message(self._text)


class _Client:
    """Returns a preset resolver JSON and records every ``create`` kwargs."""

    def __init__(self, text: str) -> None:
        self.messages = _Messages(text)


def _resolver_json(resolved_query, intent_guess=None, confidence=0.9) -> str:
    return json.dumps({
        "resolved_query": resolved_query,
        "intent_guess": intent_guess,
        "reference_source": "explicit",
        "confidence": confidence,
        "language": "es",
    })


def _fake_ask_v2_factory(seen: list[str]):
    def _fake_ask_v2(question, bootstrap, *args, **kwargs):
        seen.append(question)
        return {
            "selected_tool": "get_fixture_outlook",
            "tool_input": {"team_query": "Newcastle"},
            "raw_output": {"status": "ok"},
            "answer_text": "ok",
            "outcome": "ok",
            "kind": "text",
            "routing_trace": {
                "branch": "orchestrator",
                "orchestrator_called": True,
                "orchestrator_outcome": "ok",
                "grounded": True,
            },
            "tokens": {"total": 1},
        }
    return _fake_ask_v2


@pytest.fixture(autouse=True)
def _orch_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.delenv("FPL_RESOLVER_MODEL", raising=False)
    monkeypatch.delenv("FPL_RESOLVER_PROVIDER", raising=False)


# ---------------------------------------------------------------------------
# has_resolvable_context -- the predicate guard (a) reads
# ---------------------------------------------------------------------------

def test_fresh_state_has_no_resolvable_context():
    assert ConversationState().has_resolvable_context() is False


@pytest.mark.parametrize("field, value", [
    ("last_player_query", "Haaland"),
    ("last_comparison", ("Haaland", "Salah")),
    ("last_transfer", ("Salah", "Saka")),
    ("last_fixture_run_player", "Saka"),
    ("last_differential", True),
    ("history", [("tell me about Saka", "player_summary")]),
])
def test_any_anchor_makes_context_resolvable(field, value):
    state = ConversationState(**{field: value})
    assert state.has_resolvable_context() is True


def test_clear_resets_context_to_unresolvable():
    state = ConversationState(last_player_query="Haaland", history=[("q", "i")])
    state.clear()
    assert state.has_resolvable_context() is False


# ---------------------------------------------------------------------------
# Guard (a): empty session -> resolver not invoked, question verbatim
# ---------------------------------------------------------------------------

def test_empty_session_first_turn_does_not_call_resolver_and_forwards_verbatim():
    session = ConversationSession(state=ConversationState())
    seen: list[str] = []
    with patch(
        "fpl_grounded_assistant.reference_resolver.resolve_reference"
    ) as spy, patch(
        "fpl_grounded_assistant.harness.ask_v2", side_effect=_fake_ask_v2_factory(seen)
    ):
        result = session.respond(
            _CALENDAR_PHRASE, STANDARD_BOOTSTRAP, resolver_client=None, include_debug=True,
        )

    spy.assert_not_called()
    # Read from what reached ask_v2, not from the question we sent.
    assert seen == [_CALENDAR_PHRASE]
    # And from what the session reported about its own resolver step.
    dbg = result.debug.resolver
    assert dbg is not None
    assert dbg.resolver_used is False
    assert dbg.resolver_source == "none"
    assert dbg.rewritten_question == _CALENDAR_PHRASE
    assert dbg.fallback_reason == "no_resolvable_context"


def test_session_with_last_player_still_calls_resolver():
    """The follow-up path must stay alive: '¿y su forma?' after a player turn."""
    session = ConversationSession(state=ConversationState(last_player_query="Haaland"))
    seen: list[str] = []
    fake = ReferenceResolution(
        resolved_query="Haaland", intent_guess="player_summary", reference_source="pronoun",
        confidence=0.9, language="es", rewritten_question="tell me about Haaland",
    )
    with patch(
        "fpl_grounded_assistant.reference_resolver.resolve_reference", return_value=fake,
    ) as spy, patch(
        "fpl_grounded_assistant.harness.ask_v2", side_effect=_fake_ask_v2_factory(seen)
    ):
        result = session.respond(
            "¿y su forma?", STANDARD_BOOTSTRAP, resolver_client=None, include_debug=True,
        )

    spy.assert_called_once()
    _, kwargs = spy.call_args
    # The bootstrap travels to the resolver so guard (b) can validate against it.
    assert kwargs.get("bootstrap") is STANDARD_BOOTSTRAP
    # The canonical player question is a deterministic-ladder hit, so it need
    # not reach the mocked ask_v2; read the rewrite off the session's own report.
    assert result.debug.resolver.rewritten_question == "tell me about Haaland"
    assert result.debug.resolver.resolver_source == "llm"


def test_session_with_history_only_still_calls_resolver():
    """History alone is context (the resolver prompt carries recent_history)."""
    state = ConversationState(history=[("what is the current gameweek", "current_gameweek")])
    session = ConversationSession(state=state)
    seen: list[str] = []
    fake = ReferenceResolution(
        resolved_query=None, intent_guess=None, reference_source="none",
        confidence=0.0, language="es", rewritten_question="¿y la siguiente?",
    )
    with patch(
        "fpl_grounded_assistant.reference_resolver.resolve_reference", return_value=fake,
    ) as spy, patch(
        "fpl_grounded_assistant.harness.ask_v2", side_effect=_fake_ask_v2_factory(seen)
    ):
        session.respond("¿y la siguiente?", STANDARD_BOOTSTRAP, resolver_client=None)
    spy.assert_called_once()


# ---------------------------------------------------------------------------
# Guard (b): "null" normalised; team names never become a player template
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["null", "NULL", "none", "", "   ", None])
def test_null_spellings_never_build_a_template(raw):
    client = _Client(_resolver_json(raw, intent_guess=None, confidence=0.9))
    res = resolve_reference_llm(
        _CALENDAR_PHRASE, ConversationState(), client=client, bootstrap=STANDARD_BOOTSTRAP,
    )
    assert res is not None
    assert res.resolved_query is None
    assert res.rewritten_question == _CALENDAR_PHRASE
    assert "tell me about" not in res.rewritten_question
    # "null" means "no player", not "a non-player": normalised at the edge,
    # so the element validation never sees it and no reason is recorded.
    assert res.fallback_reason is None


def test_null_is_normalised_even_without_bootstrap():
    """The edge normalisation does not depend on data being present."""
    client = _Client(_resolver_json("null"))
    res = resolve_reference_llm(_CALENDAR_PHRASE, ConversationState(), client=client)
    assert res is not None
    assert res.resolved_query is None
    assert res.rewritten_question == _CALENDAR_PHRASE


@pytest.mark.parametrize("team_name", ["Newcastle", "Liverpool", "Man City", "Spurs", "Arsenal"])
def test_team_name_leaves_question_intact_with_reason(team_name):
    client = _Client(_resolver_json(team_name, intent_guess=None, confidence=0.9))
    res = resolve_reference(
        _CALENDAR_PHRASE, ConversationState(), client=client, bootstrap=STANDARD_BOOTSTRAP,
    )
    assert res.rewritten_question == _CALENDAR_PHRASE
    assert res.resolved_query is None
    assert res.fallback_reason == "resolved_query_not_a_player"
    # Confidence was high, so the LLM path "won" -- with the question intact.
    assert res.confidence == 0.9


def test_real_player_still_builds_the_template():
    """Salah IS an element of STANDARD_BOOTSTRAP -> template as before i103."""
    client = _Client(_resolver_json("Salah", intent_guess=None, confidence=0.9))
    res = resolve_reference(
        "¿Y Salah?", ConversationState(), client=client, bootstrap=STANDARD_BOOTSTRAP,
    )
    assert res.rewritten_question == "tell me about Salah"
    assert res.resolved_query == "Salah"
    assert res.fallback_reason is None


def test_real_player_with_intent_uses_intent_template():
    client = _Client(_resolver_json("Haaland", intent_guess="captain_score", confidence=0.9))
    res = resolve_reference(
        "¿Y él como capitán?", ConversationState(last_player_query="Haaland"),
        client=client, bootstrap=STANDARD_BOOTSTRAP,
    )
    assert res.rewritten_question == "should I captain Haaland"


def test_no_player_intents_still_rewrite_without_a_player():
    """current_gameweek / rank_candidates need no {player}; a team name in
    resolved_query must not block them (it is simply dropped)."""
    client = _Client(_resolver_json("Newcastle", intent_guess="current_gameweek", confidence=0.9))
    res = resolve_reference(
        "¿en qué jornada estamos?", ConversationState(), client=client, bootstrap=STANDARD_BOOTSTRAP,
    )
    assert res.rewritten_question == "what is the current gameweek"
    assert res.fallback_reason == "resolved_query_not_a_player"


def test_without_bootstrap_validation_is_skipped_pre_i103_behaviour():
    """Callers that have no data keep the old contract -- documented, not hidden."""
    client = _Client(_resolver_json("Newcastle", intent_guess=None, confidence=0.9))
    res = resolve_reference(_CALENDAR_PHRASE, ConversationState(), client=client)
    assert res.rewritten_question == "tell me about Newcastle"
    assert res.fallback_reason is None


def test_validation_uses_the_shared_registry_matcher():
    """Guard (b) must go through fpl_player_registry.resolve_player_candidates
    (PR #14 / #142-145), not a private matcher."""
    with patch.object(rr, "resolve_player_candidates", wraps=rr.resolve_player_candidates) as spy:
        client = _Client(_resolver_json("Newcastle", intent_guess=None, confidence=0.9))
        resolve_reference(
            _CALENDAR_PHRASE, ConversationState(), client=client, bootstrap=STANDARD_BOOTSTRAP,
        )
    spy.assert_called_once()
    args, kwargs = spy.call_args
    assert args[0] == "Newcastle"
    assert args[1] is STANDARD_BOOTSTRAP["elements"]
    assert kwargs == {"allow_prefix": True, "allow_substring": False}


def test_end_to_end_session_with_context_blocks_team_rewrite():
    """Through ConversationSession: a session WITH context (so guard (a) does
    not fire) whose LLM names a team must still forward the question intact.
    This is the case guard (a) cannot cover and guard (b) exists for."""
    session = ConversationSession(state=ConversationState(last_player_query="Haaland"))
    seen: list[str] = []
    client = _Client(_resolver_json("Newcastle", intent_guess=None, confidence=0.9))
    with patch("fpl_grounded_assistant.harness.ask_v2", side_effect=_fake_ask_v2_factory(seen)):
        result = session.respond(
            _CALENDAR_PHRASE, STANDARD_BOOTSTRAP, resolver_client=client, include_debug=True,
        )
    assert seen == [_CALENDAR_PHRASE]
    assert result.debug.resolver.fallback_reason == "resolved_query_not_a_player"


# ---------------------------------------------------------------------------
# Guard (c): model read from FPL_RESOLVER_MODEL at call time
# ---------------------------------------------------------------------------

def test_resolver_model_default_when_env_absent(monkeypatch):
    monkeypatch.delenv("FPL_RESOLVER_MODEL", raising=False)
    assert resolver_model() == rr.DEFAULT_RESOLVER_MODEL


def test_resolver_model_env_wins(monkeypatch):
    monkeypatch.setenv("FPL_RESOLVER_MODEL", "gemini-2.5-flash-lite")
    assert resolver_model() == "gemini-2.5-flash-lite"


def test_resolver_model_blank_env_falls_back(monkeypatch):
    monkeypatch.setenv("FPL_RESOLVER_MODEL", "   ")
    assert resolver_model() == rr.DEFAULT_RESOLVER_MODEL


def test_client_receives_env_model_set_after_import(monkeypatch):
    """The module was imported long before this env change; the call must
    still honour it -- i.e. the read happens per call, not at import."""
    monkeypatch.setenv("FPL_RESOLVER_MODEL", "resolver-model-from-env")
    client = _Client(_resolver_json("Haaland", intent_guess="player_summary", confidence=0.9))
    resolve_reference_llm("¿y él?", ConversationState(last_player_query="Haaland"), client=client)
    assert [c["model"] for c in client.messages.calls] == ["resolver-model-from-env"]


def test_client_receives_default_model_when_env_absent(monkeypatch):
    monkeypatch.delenv("FPL_RESOLVER_MODEL", raising=False)
    client = _Client(_resolver_json("Haaland", intent_guess="player_summary", confidence=0.9))
    resolve_reference_llm("¿y él?", ConversationState(last_player_query="Haaland"), client=client)
    assert [c["model"] for c in client.messages.calls] == [rr.DEFAULT_RESOLVER_MODEL]


def test_explicit_model_kwarg_still_wins(monkeypatch):
    monkeypatch.setenv("FPL_RESOLVER_MODEL", "resolver-model-from-env")
    client = _Client(_resolver_json("Haaland", intent_guess="player_summary", confidence=0.9))
    resolve_reference_llm(
        "¿y él?", ConversationState(last_player_query="Haaland"), client=client, model="explicit-model",
    )
    assert [c["model"] for c in client.messages.calls] == ["explicit-model"]


def test_comparison_resolver_reads_env_model_too(monkeypatch):
    """Same knob for the Phase 5f comparison resolver (same deprecated default)."""
    monkeypatch.setenv("FPL_RESOLVER_MODEL", "resolver-model-from-env")
    client = _Client(json.dumps({
        "is_comparison_followup": True, "new_player": "Saka", "confidence": 0.9, "language": "es",
    }))
    rr.resolve_comparison_followup_llm(
        "¿y Saka?", ConversationState(last_comparison=("Haaland", "Salah")), client=client,
    )
    assert [c["model"] for c in client.messages.calls] == ["resolver-model-from-env"]


# ---------------------------------------------------------------------------
# Default pair: openai / gpt-5.6-luna (Leo 2026-09-23), provider and model
# resolved together so a GPT id is never sent to Gemini.
# ---------------------------------------------------------------------------

def test_default_pair_is_openai_luna(monkeypatch):
    monkeypatch.delenv("FPL_RESOLVER_MODEL", raising=False)
    monkeypatch.delenv("FPL_RESOLVER_PROVIDER", raising=False)
    assert rr.resolver_provider() == "openai"
    assert resolver_model() == "gpt-5.6-luna"


def test_default_ignores_the_presentation_default_provider(monkeypatch):
    """llm_layer's DEFAULT_PROVIDER (gemini in prod) is the presentation
    layer's knob; the resolver no longer inherits it."""
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")
    monkeypatch.delenv("FPL_RESOLVER_PROVIDER", raising=False)
    assert rr.resolver_provider() == "openai"
    assert resolver_model() == "gpt-5.6-luna"


def test_provider_override_brings_its_own_default_model(monkeypatch):
    monkeypatch.setenv("FPL_RESOLVER_PROVIDER", " Gemini ")
    monkeypatch.delenv("FPL_RESOLVER_MODEL", raising=False)
    assert rr.resolver_provider() == "gemini"
    assert resolver_model() != "gpt-5.6-luna"
    assert resolver_model().startswith("gemini")


def test_model_override_wins_over_the_provider_default(monkeypatch):
    monkeypatch.setenv("FPL_RESOLVER_PROVIDER", "gemini")
    monkeypatch.setenv("FPL_RESOLVER_MODEL", "gemini-3.5-flash")
    assert resolver_model() == "gemini-3.5-flash"


@pytest.mark.parametrize("fn_name", ["resolve_reference_llm", "resolve_comparison_followup_llm"])
def test_both_resolvers_ask_get_provider_for_the_resolver_provider(monkeypatch, fn_name):
    """Read off the call get_provider actually received, not off the helper."""
    monkeypatch.setenv("FPL_RESOLVER_PROVIDER", "openai")
    seen: list[str] = []

    def fake_get_provider(name, client=None):
        seen.append(name)
        raise rr.ProviderNotAvailableError("stop here")

    monkeypatch.setattr(rr, "get_provider", fake_get_provider)
    state = ConversationState(last_player_query="Haaland", last_comparison=("Haaland", "Salah"))
    assert getattr(rr, fn_name)("¿y él?", state) is None
    assert seen == ["openai"]
