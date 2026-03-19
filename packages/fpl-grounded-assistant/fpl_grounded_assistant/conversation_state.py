"""
fpl_grounded_assistant.conversation_state
==========================================
Phase 4e: minimal multi-turn conversation state.
Phase 4f: extended with bounded history + LLM-assisted resolver integration.
Phase 5c: comparison follow-up support.

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
Phase 5c: deterministic comparison follow-up via ``resolve_comparison_followup()``.
Phase 5f: LLM-assisted comparison follow-up for Spanish and elliptical patterns.

When ``resolver_client`` is provided to ``ConversationSession.respond()``,
the LLM resolver handles patterns the Phase 4e regex cannot:

- ``"¿Y él?"``           → resolves to last player via Spanish pronoun
- ``"¿Y como capitán?"`` → captain_score intent + last player via ellipsis
- ``"¿Y Salah?"``        → explicit player + intent from context

Phase 5c deterministic comparison follow-ups (no client needed)::

    "And Salah?"               → compare {last_a} and Salah
    "What about Palmer?"       → compare {last_a} and Palmer
    "How about Palmer?"        → compare {last_a} and Palmer
    "What about X instead?"    → compare {last_a} and X
    "Compare him to Salah"     → compare {last_a} and Salah  (pronoun → last_a)

Phase 5f LLM comparison follow-ups (``resolver_client`` required)::

    "¿Y Salah?"                → compare {last_a} and Salah  (Spanish)
    "¿Y Saka?"                 → compare {last_a} and Saka   (Spanish)
    "vs Saka"                  → compare {last_a} and Saka   (bare vs)
    "Or Saka?"                 → compare {last_a} and Saka   (or-prefix)

When no client is available, Phase 4e regex fallback handles English pronouns::

    him  his  he  her  hers  she  them  their  they
    the player  this player  that player

Intentionally deferred
-----------------------
- Long-term memory or session persistence
- Multi-player context tracking ("him or Salah")
- Follow-up targeting player B specifically (always anchors to player A)
- Trailing-clause pronoun handling (e.g. "who is better, him or Salah?")

Public API
----------
::

    from fpl_grounded_assistant import (
        ConversationSession,          # primary interface
        ConversationState,            # inspectable state object
        resolve_pronouns,             # pure substitution helper (Phase 4e)
        resolve_comparison_followup,  # comparison follow-up rewriter (Phase 5c)
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
    INTENT_COMPARE_PLAYERS,   # Phase 5c
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
# Comparison follow-up patterns  (Phase 5c)
# ---------------------------------------------------------------------------
# Prefixes that introduce a new second-player follow-up after a comparison.
_COMP_FOLLOWUP_PREFIXES: tuple[str, ...] = (
    "what about ",
    "how about ",
    "and ",
)

# Trailing suffixes to strip from follow-up remainder.
_COMP_INSTEAD_SUFFIXES: tuple[str, ...] = (
    " instead",
)

# Matches "compare <pronoun> to/vs/against/and <player>".
_COMP_PRONOUN_RE = re.compile(
    r"^compare\s+(?:him|her|them|the\s+player|this\s+player)\s+"
    r"(?:to|vs\.?|against|and)\s+(.+)$",
    re.IGNORECASE,
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
    last_comparison:
        The ``(query_a, query_b)`` pair from the most recently completed
        successful comparison turn.  ``None`` until such a turn completes.
        Cleared when any successful non-comparison turn completes (Phase 5c).

    Mutated only by ``update_from_response()`` and ``clear()``.
    """

    last_player_query: str | None = field(default=None)
    turn_count: int = field(default=0)
    history: list[tuple[str, str]] = field(default_factory=list)
    last_comparison: tuple[str, str] | None = field(default=None)   # Phase 5c

    def update_from_response(
        self,
        response: FinalResponse,
        resolved_query: str | None,
        question_text: str | None = None,
        comparison_queries: tuple[str, str] | None = None,   # Phase 5c
    ) -> None:
        """Update state after a completed turn.

        Stores *resolved_query* as the new ``last_player_query`` only when:

        - *resolved_query* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent`` is one of: captain_score, player_summary,
          player_resolve

        Sets ``last_comparison`` to *comparison_queries* when:

        - *comparison_queries* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent == INTENT_COMPARE_PLAYERS``

        Clears ``last_comparison`` after any successful non-comparison turn.

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
        comparison_queries:
            The ``(query_a, query_b)`` extracted from the route result when
            the intent is ``compare_players``.  Used to update
            ``last_comparison`` (Phase 5c).
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

        # Phase 5c: comparison context tracking
        if (
            comparison_queries
            and response.outcome == OUTCOME_OK
            and response.intent == INTENT_COMPARE_PLAYERS
        ):
            self.last_comparison = comparison_queries
        elif response.outcome == OUTCOME_OK and response.intent != INTENT_COMPARE_PLAYERS:
            # Any other successful turn clears comparison context
            self.last_comparison = None

        if question_text:
            if len(self.history) >= 3:
                self.history.pop(0)
            self.history.append((question_text, response.intent))

    def clear(self) -> None:
        """Reset all state.  Call when starting a new conversation."""
        self.last_player_query = None
        self.turn_count = 0
        self.history.clear()
        self.last_comparison = None   # Phase 5c


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
# Comparison follow-up resolver  (Phase 5c)
# ---------------------------------------------------------------------------

def resolve_comparison_followup(question: str, state: ConversationState) -> str | None:
    """Detect a comparison follow-up and return the rewritten canonical question.

    Requires ``state.last_comparison`` to be set from a prior successful
    comparison turn.  Returns ``None`` when no follow-up pattern matches or
    when ``state.last_comparison`` is not set.

    Supported patterns (when ``state.last_comparison == (A, B)``):

    * ``"And Salah?"``              → ``"compare A and Salah"``
    * ``"What about Palmer?"``      → ``"compare A and Palmer"``
    * ``"How about Palmer?"``       → ``"compare A and Palmer"``
    * ``"What about X instead?"``   → ``"compare A and X"``
    * ``"Compare him to Salah"``    → ``"compare A and Salah"`` (pronoun → A)

    Parameters
    ----------
    question:
        Raw user question.
    state:
        Current ``ConversationState``.

    Returns
    -------
    str | None
        Canonical comparison question if a follow-up pattern matched, else ``None``.

    Notes
    -----
    Always anchors to player A (``last_comparison[0]``).  Replacing player B
    specifically, multi-player comparisons, and LLM-assisted follow-ups are
    intentionally deferred.
    """
    if not state.last_comparison:
        return None

    last_a, _ = state.last_comparison
    q_stripped = question.strip().rstrip("?!.")
    q_norm = q_stripped.lower()

    # Pattern: "and <player>" / "what about <player>" / "how about <player>"
    for prefix in _COMP_FOLLOWUP_PREFIXES:
        if q_norm.startswith(prefix):
            remainder_orig = q_stripped[len(prefix):].strip().rstrip("?!.,")
            remainder_norm = remainder_orig.lower()
            for suffix in _COMP_INSTEAD_SUFFIXES:
                if remainder_norm.endswith(suffix):
                    remainder_orig = remainder_orig[: len(remainder_orig) - len(suffix)].strip()
                    break
            if remainder_orig:
                return f"compare {last_a} and {remainder_orig}"

    # Pattern: "compare <pronoun> to/vs/against/and <player>"
    m = _COMP_PRONOUN_RE.match(q_stripped)
    if m:
        new_player = m.group(1).strip().rstrip("?!.,")
        if new_player:
            return f"compare {last_a} and {new_player}"

    return None


# ---------------------------------------------------------------------------
# Resolver debug helper (Phase 4g)
# ---------------------------------------------------------------------------

def _make_resolver_debug(resolution, original_question: str, rewritten_question: str):
    """Build a ResolverDebug from a ReferenceResolution.

    Lazy-imports ResolverDebug to avoid circular imports.

    Resolver source mapping (Phase 5k: comparison-specific values preserved):
    - "comparison_followup"     -> "comparison_followup"      (Phase 5c det. comparison rewrite)
    - "comparison_followup_llm" -> "comparison_followup_llm"  (Phase 5f LLM comparison rewrite)
    - "deterministic"           -> "fallback_regex"            (Phase 4e pronoun regex)
    - "none" (confidence 0.0)   -> "none"                     (no resolver ran)
    - any LLM source            -> "llm"                      (Phase 4f LLM resolution)
    """
    from .final_response import ResolverDebug  # noqa: PLC0415

    src = resolution.reference_source
    if src == "comparison_followup":               # Phase 5c: deterministic comparison follow-up
        resolver_source = "comparison_followup"
        resolver_confidence = None
    elif src == "comparison_followup_llm":         # Phase 5f: LLM comparison follow-up
        resolver_source = "comparison_followup_llm"
        resolver_confidence = float(resolution.confidence)
    elif src == "deterministic":                   # Phase 4e: pronoun regex fallback
        resolver_source = "fallback_regex"
        resolver_confidence = None
    elif src == "none" and resolution.confidence == 0.0:
        resolver_source = "none"
        resolver_confidence = None
    else:
        # LLM path: reference_source is "pronoun", "ellipsis", "explicit", or "none" with confidence > 0
        resolver_source = "llm"
        resolver_confidence = resolution.confidence

    return ResolverDebug(
        resolver_used=(resolver_source != "none"),
        resolver_source=resolver_source,
        resolver_confidence=resolver_confidence,
        rewritten_question=rewritten_question,
        fallback_reason=resolution.fallback_reason,
    )


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
        from .reference_resolver import (  # noqa: PLC0415
            resolve_reference,
            resolve_comparison_followup_llm,
            ReferenceResolution,
            _CONFIDENCE_THRESHOLD,
        )

        # Consume resolver_client from kwargs so it is not forwarded to _respond()
        resolver_client = kwargs.pop("resolver_client", None)

        # Read include_debug before resolution so we can build resolver debug bundle
        include_debug = kwargs.get("include_debug", False)

        # Phase 5c: deterministic comparison follow-up (highest priority, no client needed)
        comp_rewritten = resolve_comparison_followup(question, self.state)
        if comp_rewritten is not None:
            rewritten = comp_rewritten
            resolution = ReferenceResolution(
                resolved_query=None,
                intent_guess=INTENT_COMPARE_PLAYERS,
                reference_source="comparison_followup",
                confidence=1.0,
                language="en",
                rewritten_question=comp_rewritten,
                fallback_reason=None,
            )
        else:
            # Phase 5f: LLM comparison follow-up (Spanish/ellipsis, requires client)
            llm_comp: ReferenceResolution | None = None
            if self.state.last_comparison and resolver_client is not None:
                llm_comp = resolve_comparison_followup_llm(
                    question, self.state, client=resolver_client
                )

            if llm_comp is not None and llm_comp.confidence >= _CONFIDENCE_THRESHOLD:
                rewritten = llm_comp.rewritten_question
                resolution = llm_comp
            else:
                # Phase 4f: general reference resolver (single-player / pronoun / Spanish)
                resolution = resolve_reference(
                    question,
                    self.state,
                    client=resolver_client,
                    history=self.state.history if self.state.history else None,
                )
                rewritten = resolution.rewritten_question

        # Build resolver debug bundle when debug is requested
        _resolver_debug = None
        if include_debug:
            _resolver_debug = _make_resolver_debug(resolution, question, rewritten)

        # Extract player_query and comparison_queries for state tracking
        route_result = route(rewritten)
        player_query: str | None = None
        comparison_queries: tuple[str, str] | None = None
        if route_result is not None:
            player_query = route_result.tool_args.get("query") or None
            if route_result.tool_name == "compare_players":
                qa = route_result.tool_args.get("query_a", "")
                qb = route_result.tool_args.get("query_b", "")
                if qa and qb:
                    comparison_queries = (qa, qb)

        response = _respond(rewritten, bootstrap, **kwargs, _resolver_debug=_resolver_debug)
        self.state.update_from_response(
            response, player_query, question_text=rewritten,
            comparison_queries=comparison_queries,
        )
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
