"""
fpl_grounded_assistant.conversation_state
==========================================
Phase 4e: minimal multi-turn conversation state.
Phase 4f: extended with bounded history + LLM-assisted resolver integration.

Provides a lightweight, in-memory state layer on top of the stateless
``respond()`` function.  State is explicit, bounded, and restricted to
player-context tracking for pronoun/reference resolution in follow-up
questions.

Design principles
-----------------
- **Optional** — ``respond()`` is unchanged; stateless callers are unaffected.
- **Short-lived** — callers control lifetime by constructing a new
  ``ConversationSession`` per conversation and discarding it afterwards.
- **Narrow** — only the most recently successfully resolved player query
  and a bounded history (≤ 3 turns) are tracked.  No long-term memory.
- **Inspectable** — ``ConversationState`` is a plain dataclass; no hidden
  or encoded state.

Follow-up patterns supported
-----------------------------
Phase 4e: English pronoun substitution via regex.
Phase 4f: LLM-assisted reference resolution for Spanish/ellipsis follow-ups.

When ``resolver_client`` is provided to ``ConversationSession.respond()``,
the LLM resolver handles patterns the Phase 4e regex cannot:

- ``"¿Y él?"``           → resolves to last player via Spanish pronoun
- ``"¿Y como capitán?"`` → captain_score intent + last player via ellipsis
- ``"¿Y Salah?"``        → explicit player + intent from context
- ``"And Salah?"``       → explicit player + intent from context

When no client is available, Phase 4e regex fallback handles English pronouns::

    him  his  he  her  hers  she  them  their  they
    the player  this player  that player

Intentionally deferred
-----------------------
- Long-term memory or session persistence
- Multi-player context tracking ("him or Salah")
- Comparison intents
- Trailing-clause pronoun handling (e.g. "who is better, him or Salah?")

Public API
----------
::

    from fpl_grounded_assistant import (
        ConversationSession,   # primary interface
        ConversationState,     # inspectable state object
        resolve_pronouns,      # pure substitution helper (Phase 4e)
    )

    session = ConversationSession()
    r1 = session.respond("should I captain Haaland", bootstrap)

    # Phase 4e — English pronoun fallback (no client needed)
    r2 = session.respond("should I captain him?", bootstrap)

    # Phase 4f — LLM resolver for Spanish/ellipsis (optional)
    r3 = session.respond("¿Y como capitán?", bootstrap, resolver_client=client)

    session.clear()  # reset for next conversation
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .dispatcher import (
    OUTCOME_OK,
    INTENT_CAPTAIN_SCORE,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
)
from .router import route
from .final_response import respond as _respond, FinalResponse


# ---------------------------------------------------------------------------
# Pronoun / reference patterns
# ---------------------------------------------------------------------------
# Ordered longest-first so multi-word references are tried before single words.
# All are lowercase; matching is case-insensitive.
_PRONOUNS: tuple[str, ...] = (
    "the player",
    "this player",
    "that player",
    "their",
    "them",
    "they",
    "hers",
    "his",
    "him",
    "her",
    "she",
    "he",
)


# ---------------------------------------------------------------------------
# ConversationState
# ---------------------------------------------------------------------------

@dataclass
class ConversationState:
    """Minimal in-memory state for a single conversation session.

    Attributes
    ----------
    last_player_query:
        The player name / query string most recently resolved with outcome=ok
        and a player-related intent.  ``None`` until such a turn completes.
    turn_count:
        Total number of turns processed in this session (includes turns that
        did not update ``last_player_query``).
    history:
        Bounded list of recent ``(question_text, intent)`` pairs.  At most
        3 entries — oldest entry is dropped when the limit is reached.  Used
        by the Phase 4f LLM reference resolver as conversation context.

    Mutated only by ``update_from_response()`` and ``clear()``.
    """

    last_player_query: str | None = field(default=None)
    turn_count: int = field(default=0)
    history: list[tuple[str, str]] = field(default_factory=list)

    def update_from_response(
        self,
        response: FinalResponse,
        resolved_query: str | None,
        question_text: str | None = None,
    ) -> None:
        """Update state after a completed turn.

        Stores *resolved_query* as the new ``last_player_query`` only when:

        - *resolved_query* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent`` is one of: captain_score, player_summary,
          player_resolve

        Always increments ``turn_count`` regardless of whether the player
        context is updated.

        Appends ``(question_text, response.intent)`` to ``history`` when
        *question_text* is provided.  History is bounded to 3 entries.

        Parameters
        ----------
        response:
            The ``FinalResponse`` returned by ``respond()``.
        resolved_query:
            The player query extracted by the router for this turn (after
            reference resolution), or ``None`` if no player was targeted.
        question_text:
            The canonical question text that was sent to the backend.
            Used to populate ``history`` for the Phase 4f LLM resolver.
        """
        self.turn_count += 1
        if (
            resolved_query
            and response.outcome == OUTCOME_OK
            and response.intent in (
                INTENT_CAPTAIN_SCORE,
                INTENT_PLAYER_SUMMARY,
                INTENT_PLAYER_RESOLVE,
            )
        ):
            self.last_player_query = resolved_query

        if question_text:
            if len(self.history) >= 3:
                self.history.pop(0)
            self.history.append((question_text, response.intent))

    def clear(self) -> None:
        """Reset all state.  Call when starting a new conversation."""
        self.last_player_query = None
        self.turn_count = 0
        self.history.clear()


# ---------------------------------------------------------------------------
# Pronoun resolver — pure function, no side effects
# ---------------------------------------------------------------------------

def resolve_pronouns(question: str, state: ConversationState) -> str:
    """Substitute the first pronoun / player reference with the last player.

    Returns *question* unchanged if:

    - ``state.last_player_query`` is ``None``
    - no recognised pronoun or reference is present in *question*

    Substitution is case-insensitive.  Single-word pronouns use ``\\b``
    word-boundary anchors to prevent false matches (e.g. "him" will not
    match inside "Birmingham").  Multi-word references ("the player" etc.)
    are matched as plain substrings.

    Only the **first** matching pronoun per question is substituted.

    Parameters
    ----------
    question:
        Raw question string from the caller.
    state:
        The current ``ConversationState``.

    Returns
    -------
    str
        Question with the first pronoun replaced by ``state.last_player_query``,
        or the original *question* if no substitution was made.

    Examples
    --------
    >>> s = ConversationState()
    >>> s.last_player_query = "Haaland"
    >>> resolve_pronouns("should I captain him?", s)
    'should I captain Haaland?'
    >>> resolve_pronouns("tell me about Haaland", s)
    'tell me about Haaland'
    """
    if not state.last_player_query:
        return question

    player = state.last_player_query

    for pronoun in _PRONOUNS:
        if " " in pronoun:
            pattern = re.escape(pronoun)
        else:
            pattern = rf"\b{re.escape(pronoun)}\b"

        if re.search(pattern, question, flags=re.IGNORECASE):
            return re.sub(pattern, player, question, count=1, flags=re.IGNORECASE)

    return question


# ---------------------------------------------------------------------------
# ConversationSession
# ---------------------------------------------------------------------------

class ConversationSession:
    """Stateful wrapper around ``respond()`` for multi-turn conversations.

    Maintains a ``ConversationState`` across calls and resolves pronoun
    follow-up references before passing each question to the stateless
    ``respond()``.

    The underlying ``respond()`` function is unchanged and always used
    internally — all ``FinalResponse`` invariants are preserved.

    Parameters
    ----------
    state:
        Optional pre-built ``ConversationState``.  Defaults to a fresh
        empty state.

    Usage::

        session = ConversationSession()
        r1 = session.respond("should I captain Haaland", bootstrap)
        r2 = session.respond("should I captain him?", bootstrap)
        session.clear()  # reset for a new conversation
    """

    def __init__(self, state: ConversationState | None = None) -> None:
        self.state: ConversationState = (
            state if state is not None else ConversationState()
        )

    def respond(
        self,
        question: str,
        bootstrap: dict[str, Any],
        **kwargs: Any,
    ) -> FinalResponse:
        """Resolve follow-up references, call ``respond()``, update state.

        Steps:

        1. Attempt LLM-assisted reference resolution (Phase 4f) when
           ``resolver_client`` is present in *kwargs*; fall back to Phase 4e
           deterministic pronoun substitution otherwise.
        2. Route the resolved/rewritten question to extract ``player_query``.
        3. Call the stateless ``respond()`` with the rewritten question.
        4. Update ``state`` based on the response outcome and intent.

        Parameters
        ----------
        question:
            Raw user question (any language).  Reference resolution runs
            before the question reaches the deterministic backend.
        bootstrap:
            FPL bootstrap dict (same as the stateless ``respond()``).
        resolver_client:
            Optional Anthropic client for Phase 4f LLM reference resolution.
            Consumed here — not forwarded to the stateless ``respond()``.
            When absent (or ``None``), Phase 4e deterministic fallback is used.
        **kwargs:
            All other kwargs are forwarded to the stateless ``respond()``
            unchanged (e.g. ``include_debug=True``, ``client=...``).

        Returns
        -------
        FinalResponse
            Identical in shape and invariants to the stateless ``respond()``.
            ``FinalResponse.intent`` reflects the rewritten question.
        """
        # Lazy import — avoids circular import between conversation_state ↔ reference_resolver
        from .reference_resolver import resolve_reference  # noqa: PLC0415

        # Consume resolver_client from kwargs so it is not forwarded to _respond()
        resolver_client = kwargs.pop("resolver_client", None)

        resolution = resolve_reference(
            question,
            self.state,
            client=resolver_client,
            history=self.state.history if self.state.history else None,
        )
        rewritten = resolution.rewritten_question

        # Extract player_query for state tracking — route() is lightweight
        route_result = route(rewritten)
        player_query: str | None = None
        if route_result is not None:
            player_query = route_result.tool_args.get("query") or None

        response = _respond(rewritten, bootstrap, **kwargs)
        self.state.update_from_response(response, player_query, question_text=rewritten)
        return response

    @property
    def last_player_query(self) -> str | None:
        """Convenience accessor for ``state.last_player_query``."""
        return self.state.last_player_query

    @property
    def turn_count(self) -> int:
        """Convenience accessor for ``state.turn_count``."""
        return self.state.turn_count

    def clear(self) -> None:
        """Reset conversation state.  Call when starting a new conversation."""
        self.state.clear()
