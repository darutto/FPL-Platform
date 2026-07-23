"""
Regression tests for the ConversationSession.respond() comparison-followup
gate (conversation_state.py).

Bug: resolve_comparison_followup_llm() (Phase 5f — handles Spanish/elliptical
comparison follow-ups like "y con Semenyo?") was gated behind
`resolver_client is not None`, but the live /session/{id}/ask HTTP endpoint
(fpl_server.py::session_ask) never passes a resolver_client. This made the
entire LLM comparison-followup path permanently dead in production: any
compare-follow-up phrased outside the narrow English deterministic patterns
("And X?", "What about X?") fell through unresolved and was answered as an
unrelated brand-new question by the LLM orchestrator.

resolve_comparison_followup_llm() already handles client=None correctly on
its own — it calls get_provider(_PROVIDER, client=None), which constructs a
fresh provider from env credentials and degrades to None (via
ProviderNotAvailableError) if none are configured. The only bug was the
redundant, overly-strict outer gate; these tests lock in its removal.
"""
from __future__ import annotations

import os as _os
import sys as _sys
from unittest.mock import patch

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
from fpl_grounded_assistant.reference_resolver import ReferenceResolution  # noqa: E402


def _session_with_last_comparison(player_a: str, player_b: str) -> ConversationSession:
    state = ConversationState(last_comparison=(player_a, player_b))
    return ConversationSession(state=state)


def test_comparison_followup_llm_attempted_even_when_resolver_client_is_none():
    """The core regression: resolver_client=None (the production reality —
    fpl_server.py never passes one) must NOT prevent the attempt. Before the
    fix, this whole branch was skipped by the `resolver_client is not None`
    guard; now only `state.last_comparison` gates it."""
    session = _session_with_last_comparison("Haaland", "Salah")

    with patch(
        "fpl_grounded_assistant.reference_resolver.resolve_comparison_followup_llm"
    ) as mock_resolver:
        mock_resolver.return_value = None  # simulate "no client available" -> graceful no-op
        session.respond("y con Semenyo?", STANDARD_BOOTSTRAP, resolver_client=None)

    # The key assertion: it was CALLED at all (with resolver_client=None passed
    # straight through) — this is exactly what the removed guard used to block.
    mock_resolver.assert_called_once()
    _, kwargs = mock_resolver.call_args
    assert kwargs.get("client") is None


def test_comparison_followup_llm_not_attempted_without_last_comparison():
    """The meaningful gate (no prior comparison to extend) must still hold —
    this fix only removes the client check, not the last_comparison check."""
    session = ConversationSession(state=ConversationState())  # no last_comparison

    with patch(
        "fpl_grounded_assistant.reference_resolver.resolve_comparison_followup_llm"
    ) as mock_resolver:
        session.respond("y con Semenyo?", STANDARD_BOOTSTRAP, resolver_client=None)

    mock_resolver.assert_not_called()


def test_successful_llm_resolution_rewrites_to_canonical_compare_question():
    """When the (mocked) LLM resolver succeeds, the question is rewritten to
    anchor on player A and swap in the new player — proving the redraw path
    a successful resolution would trigger."""
    session = _session_with_last_comparison("Haaland", "Salah")

    fake_resolution = ReferenceResolution(
        resolved_query="Semenyo",
        intent_guess=None,
        reference_source="comparison_followup_llm",
        confidence=0.9,
        language="es",
        rewritten_question="compare Haaland and Semenyo",
    )

    with patch(
        "fpl_grounded_assistant.reference_resolver.resolve_comparison_followup_llm",
        return_value=fake_resolution,
    ):
        result = session.respond("y con Semenyo?", STANDARD_BOOTSTRAP, resolver_client=None)

    # The rewritten question must have been what actually got dispatched —
    # observable via the intent, since a successful compare_players turn sets it.
    assert result.intent == "compare_players"
