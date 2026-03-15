"""
fpl_grounded_assistant.conversation_state
==========================================
Phase 4e: minimal multi-turn conversation state.

Provides a lightweight, in-memory state layer on top of the stateless
``respond()`` function.  State is explicit, bounded, and restricted to
player-context tracking for pronoun resolution in follow-up questions.

Design principles
-----------------
- **Optional** — ``respond()`` is unchanged; stateless callers are unaffected.
- **Short-lived** — callers control lifetime by constructing a new
  ``ConversationSession`` per conversation and discarding it afterwards.
- **Narrow** — only the most recently successfully resolved player query
  is tracked.  No history, no summarisation, no long-term memory.
- **Inspectable** — ``ConversationState`` is a plain dataclass; no hidden
  or encoded state.

Follow-up patterns supported
-----------------------------
Pronoun substitution enables follow-up questions that reference the most
recently resolved player.  The substituted question is then passed to the
existing deterministic router unchanged — no new routing rules are added.

Supported pronouns / references (matched with word-boundary awareness)::

    him  his  he  her  hers  she  them  their  they
    the player  this player  that player

Examples::

    # Turn 1 — resolves Haaland, stores last_player_query = "Haaland"
    r1 = session.respond("should I captain Haaland", bootstrap)

    # Turn 2 — pronoun resolved before routing
    r2 = session.respond("should I captain him?", bootstrap)
    # effective question: "should I captain Haaland?"

    # Turn 3 — summary follow-up
    r3 = session.respond("tell me about him", bootstrap)
    # effective question: "tell me about Haaland"

Intentionally deferred
-----------------------
- Long-term memory or session persistence
- Multi-player context tracking
- Comparison intents or new routing rules
- LLM-based reference resolution
- Trailing-clause pronoun handling (e.g. "who is better, him or Salah?")

Public API
----------
::

    from fpl_grounded_assistant import (
        ConversationSession,   # primary interface
        ConversationState,     # inspectable state object
        resolve_pronouns,      # pure substitution helper
    )

    session = ConversationSession()
    r1 = session.respond("should I captain Haaland", bootstrap)
    r2 = session.respond("should I captain him?", bootstrap)
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

    Mutated only by ``update_from_response()`` and ``clear()``.
    """

    last_player_query: str | None = field(default=None)
    turn_count: int = field(default=0)

    def update_from_response(
        self,
        response: FinalResponse,
        resolved_query: str | None,
    ) -> None:
        """Update state after a completed turn.

        Stores *resolved_query* as the new ``last_player_query`` only when:

        - *resolved_query* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent`` is one of: captain_score, player_summary,
          player_resolve

        Always increments ``turn_count`` regardless of whether the player
        context is updated.

        Parameters
        ----------
        response:
            The ``FinalResponse`` returned by ``respond()``.
        resolved_query:
            The player query extracted by the router for this turn (after
            pronoun substitution), or ``None`` if no player was targeted.
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

    def clear(self) -> None:
        """Reset all state.  Call when starting a new conversation."""
        self.last_player_query = None
        self.turn_count = 0


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

        1. Substitute pronouns in *question* using ``state.last_player_query``.
        2. Route the resolved question to extract ``player_query`` (if any).
        3. Call the stateless ``respond()`` with the resolved question.
        4. Update ``state`` based on the response outcome and intent.

        Parameters
        ----------
        question:
            Raw user question.  Pronouns are substituted before routing.
        bootstrap:
            FPL bootstrap dict (same as the stateless ``respond()``).
        **kwargs:
            Forwarded to the stateless ``respond()`` unchanged
            (e.g. ``include_debug=True``, ``client=...``).

        Returns
        -------
        FinalResponse
            Identical in shape and invariants to the stateless ``respond()``.
            ``FinalResponse.intent`` reflects the resolved (post-substitution)
            question.
        """
        resolved = resolve_pronouns(question, self.state)

        # Extract player_query for state tracking — route() is lightweight
        route_result = route(resolved)
        player_query: str | None = None
        if route_result is not None:
            player_query = route_result.tool_args.get("query") or None

        response = _respond(resolved, bootstrap, **kwargs)
        self.state.update_from_response(response, player_query)
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
