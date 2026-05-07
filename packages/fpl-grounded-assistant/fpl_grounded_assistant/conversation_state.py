"""
fpl_grounded_assistant.conversation_state
==========================================
Phase 4e: minimal multi-turn conversation state.
Phase 4f: extended with bounded history + LLM-assisted resolver integration.
Phase 5c: comparison follow-up support.
Phase 5l: last_resolver_source tracking for session inspect audit snapshot.
Phase 7f: transfer follow-up support.
Phase 8d-i: fixture run follow-up support.
Phase 8d-ii: differential follow-up support.
Phase 2.7c: player form follow-up support.

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
Phase 2.7c: deterministic player form follow-up via ``resolve_player_form_followup()``.

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

Phase 7f deterministic transfer follow-ups (no client needed)::

    "What about Palmer instead?"  → sell {last_out} for Palmer
    "How about Palmer instead?"   → sell {last_out} for Palmer
    "What about Palmer?"          → sell {last_out} for Palmer
    "How about Palmer?"           → sell {last_out} for Palmer
    "Palmer instead?"             → sell {last_out} for Palmer  (bare name)

Phase 8d-i deterministic fixture run follow-ups (no client needed)::

    "What about Salah?"    → Salah fixtures
    "How about Salah?"     → Salah fixtures
    "Salah?"               → Salah fixtures  (bare name, ≤ 3 words, no interrogative start)

Phase 8d-ii deterministic differential follow-ups (no client needed)::

    "What about Mbeumo?"   → should I captain Mbeumo?
    "How about Palmer?"    → should I captain Palmer?
    "Mbeumo?"              → should I captain Mbeumo?  (bare name, ≤ 3 words)

Phase 2.7c deterministic player form follow-ups (no client needed)::

    "y en los ultimos 5 partidos?"      → historial de {last_player} en los últimos 5 partidos
    "en los últimos 3 partidos?"        → historial de {last_player} en los últimos 3 partidos
    "últimos partidos?"                 → historial de {last_player}
    "recent form?"                      → historial de {last_player}
    "last 5 games?"                     → historial de {last_player}
    "y su forma?"                       → historial de {last_player}
    "forma reciente?"                   → historial de {last_player}

Phase 8d-ii deterministic differential follow-ups (no client needed)::

    "What about Mbeumo?"   → should I captain Mbeumo?
    "How about Palmer?"    → should I captain Palmer?
    "Mbeumo?"              → should I captain Mbeumo?  (bare name, ≤ 3 words)

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
        ConversationSession,             # primary interface
        ConversationState,               # inspectable state object
        resolve_pronouns,                # pure substitution helper (Phase 4e)
        resolve_comparison_followup,     # comparison follow-up rewriter (Phase 5c)
        resolve_transfer_followup,       # transfer follow-up rewriter (Phase 7f)
        resolve_fixture_run_followup,    # fixture run follow-up rewriter (Phase 8d-i)
        resolve_player_form_followup,    # player form follow-up rewriter (Phase 2.7c)
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
    INTENT_COMPARE_PLAYERS,        # Phase 5c
    INTENT_TRANSFER_ADVICE,        # Phase 7f
    INTENT_PLAYER_FIXTURE_RUN,     # Phase 8d-i
    INTENT_DIFFERENTIAL_PICKS,     # Phase 8d-ii
    INTENT_PLAYER_FORM,            # Phase 2.7c
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

# ---------------------------------------------------------------------------
# Transfer follow-up patterns  (Phase 7f)
# ---------------------------------------------------------------------------
# Prefixes that introduce a new player_in after a transfer turn.
_TRANSFER_FOLLOWUP_PREFIXES: tuple[str, ...] = (
    "what about ",
    "how about ",
)

# Trailing suffixes to strip from the follow-up remainder.
_TRANSFER_INSTEAD_SUFFIXES: tuple[str, ...] = (
    " instead",
)


# ---------------------------------------------------------------------------
# Fixture run follow-up patterns  (Phase 8d-i)
# ---------------------------------------------------------------------------
# Prefixes that introduce a new player follow-up after a fixture run turn.
_FIXTURE_FOLLOWUP_PREFIXES: tuple[str, ...] = (
    "what about ",
    "how about ",
)

# Trailing suffixes to strip from the follow-up remainder.
_FIXTURE_INSTEAD_SUFFIXES: tuple[str, ...] = (
    " instead",
)

# First words that disqualify the bare-name pattern (full sentence starters).
_FIXTURE_INTERROGATIVE_STARTERS: frozenset[str] = frozenset({
    "what", "how", "who", "why", "when", "where",
    "should", "can", "could", "is", "are", "was", "were",
    "does", "do", "did", "will", "would", "have", "has",
    "compare", "sell", "buy", "get", "show", "tell", "and",
    "vs", "versus", "or",
})

# First words of prefix remainders that disqualify a fixture-run rewrite.
# Articles, determiners, and generic fixture/time nouns are not player names.
_FIXTURE_REMAINDER_NON_PLAYER_STARTERS: frozenset[str] = frozenset({
    # Articles and determiners
    "the", "a", "an", "this", "that", "these", "those",
    "my", "his", "her", "their", "its", "our", "your",
    # Generic fixture/game/time nouns
    "fixtures", "fixture", "games", "game", "week", "gameweek", "gw",
    "schedule", "next", "upcoming", "last", "previous", "current",
})

# Content words anywhere in a prefix remainder that disqualify a fixture-run
# rewrite.  These words cannot appear in a player name and mark the remainder
# as a generic descriptive phrase rather than a player reference.
# Checked across all words in the remainder (not just the first word).
_FIXTURE_REMAINDER_CONTENT_BLOCKLIST: frozenset[str] = frozenset({
    "fixtures", "fixture", "games", "game", "players", "player",
})


# ---------------------------------------------------------------------------
# Differential follow-up patterns  (Phase 8d-ii)
# ---------------------------------------------------------------------------
# Prefixes that introduce a player follow-up after a differential picks turn.
_DIFF_FOLLOWUP_PREFIXES: tuple[str, ...] = (
    "what about ",
    "how about ",
)

# Trailing suffixes to strip from the follow-up remainder.
_DIFF_INSTEAD_SUFFIXES: tuple[str, ...] = (
    " instead",
)

# First words that disqualify the bare-name pattern (sentence starters / verbs).
_DIFF_INTERROGATIVE_STARTERS: frozenset[str] = frozenset({
    "what", "how", "who", "why", "when", "where",
    "should", "can", "could", "is", "are", "was", "were",
    "does", "do", "did", "will", "would", "have", "has",
    "compare", "sell", "buy", "get", "show", "tell", "and",
    "vs", "versus", "or",
})

# Content words anywhere in the prefix remainder that disqualify a differential
# rewrite.  These signal generic phrases rather than player references.
_DIFF_REMAINDER_NON_PLAYER_STARTERS: frozenset[str] = frozenset({
    # Articles and determiners
    "the", "a", "an", "this", "that", "these", "those",
    "my", "his", "her", "their", "its", "our", "your",
    # Object/subject pronouns — never player names
    "him", "them", "one", "it", "me", "us", "he", "she", "they", "i",
    "you", "we",
    # Generic differential/pick/time nouns
    "differentials", "differential", "picks", "pick", "options", "option",
    "players", "player", "ones", "week", "gameweek", "gw",
    "next", "upcoming", "last", "previous", "current",
})

_DIFF_REMAINDER_CONTENT_BLOCKLIST: frozenset[str] = frozenset({
    # differential domain nouns
    "differentials", "differential", "picks", "pick", "options", "option",
    "players", "player",
    # object/subject pronouns — never player names
    "him", "them", "one", "it", "me", "us", "he", "she", "they", "you", "we",
    # generic pronouns/quantifiers — never player names
    "ones", "some", "others", "anyone",
    # FPL domain descriptors — never player names
    "ownership", "value", "form", "price", "cost", "points", "score", "stats",
    # generic quality adjectives — never player names in FPL context
    "good", "bad", "great", "poor", "low", "high", "cheap", "expensive",
    "popular", "unpopular",
})


# ---------------------------------------------------------------------------
# Player form follow-up patterns  (Phase 2.7c)
# ---------------------------------------------------------------------------
# Unambiguous signals that the follow-up is asking about recent-game form for
# the player established in the previous turn (last_player_query).
#
# Safety guard: ALL patterns require last_player_query to be set.  If it is
# not set, resolve_player_form_followup() returns None immediately.
#
# Pattern vocabulary:
#   _FORM_EXACT_PHRASES   — exact (normalised) strings that unambiguously mean
#                           "recent form / last N games", matched as full question
#   _FORM_FRAGMENT_PHRASES — substrings that, when present in the stripped question,
#                            unambiguously indicate a form follow-up
#   _FORM_N_GAMES_RE       — regex for "last N games/matches/partidos" etc.

# Exact-match phrases (after strip + lower + rstrip "?!.").
# These must be unambiguous on their own and require no player reference in the
# question (the player comes from state.last_player_query).
_FORM_EXACT_PHRASES: frozenset[str] = frozenset({
    # Spanish
    "y en los ultimos 5 partidos",
    "y en los últimos 5 partidos",
    "y en los ultimos partidos",
    "y en los últimos partidos",
    "en los ultimos partidos",
    "en los últimos partidos",
    "en los ultimas jornadas",
    "en las ultimas jornadas",
    "en las últimas jornadas",
    "ultimos partidos",
    "últimos partidos",
    "ultimas jornadas",
    "últimas jornadas",
    "su forma reciente",
    "y su forma",
    "forma reciente",
    "su forma",
    # English
    "recent form",
    "recent games",
    "recent matches",
    "last few games",
    "last few matches",
})

# Fragment substrings that unambiguously mark a form follow-up regardless of
# surrounding context.  Checked as lowercased substrings.
_FORM_FRAGMENT_PHRASES: tuple[str, ...] = (
    # Spanish N-game patterns
    "en los ultimos ",
    "en los últimos ",
    "en las ultimas ",
    "en las últimas ",
    # English N-game patterns
    "last ",     # "last 5 games", "last 3 matches" — validated further by N-games regex
    "past ",     # "past 5 games"
)

# Regex for "last/past N games/matches/partidos/jornadas" in the question.
# Used together with _FORM_FRAGMENT_PHRASES to validate "last ..." cases.
_FORM_N_GAMES_RE = re.compile(
    r'\b(?:last|past|ultimos?|últimos?|ultimas?|últimas?)\s+'
    r'([1-9][0-9]?)\s*'
    r'(?:jornadas?|partidos?|juegos?|gw|gameweeks?|games?|matches?|semanas?)\b',
    re.IGNORECASE,
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
    last_transfer:
        The ``(query_out, query_in)`` pair from the most recently completed
        successful transfer turn.  ``None`` until such a turn completes.
        Cleared when any successful non-transfer turn completes (Phase 7f).
    last_fixture_run_player:
        The player query from the most recently completed successful
        fixture run turn.  ``None`` until such a turn completes.
        Cleared when any successful non-fixture-run turn completes (Phase 8d-i).
    last_differential:
        ``True`` when the most recently completed successful turn was a
        differential picks turn.  ``False`` otherwise.  Used to gate
        differential follow-up resolution (Phase 8d-ii).
    last_resolver_source:
        The resolver-source string for the most recently completed turn, using
        the same five-value vocabulary as ``ResolverDebug.resolver_source``
        (Phase 5l).  ``None`` until the first turn completes.

    Mutated only by ``update_from_response()`` and ``clear()``.
    """

    last_player_query: str | None = field(default=None)
    turn_count: int = field(default=0)
    history: list[tuple[str, str]] = field(default_factory=list)
    last_comparison: tuple[str, str] | None = field(default=None)       # Phase 5c
    last_transfer: tuple[str, str] | None = field(default=None)         # Phase 7f
    last_fixture_run_player: str | None = field(default=None)           # Phase 8d-i
    last_differential: bool = field(default=False)                      # Phase 8d-ii
    last_resolver_source: str | None = field(default=None)              # Phase 5l

    def update_from_response(
        self,
        response: FinalResponse,
        resolved_query: str | None,
        question_text: str | None = None,
        comparison_queries: tuple[str, str] | None = None,   # Phase 5c
        transfer_queries: tuple[str, str] | None = None,     # Phase 7f
        fixture_run_query: str | None = None,                # Phase 8d-i
        differential_turn: bool = False,                     # Phase 8d-ii
        resolver_source: str | None = None,                  # Phase 5l
    ) -> None:
        """Update state after a completed turn.

        Stores *resolved_query* as the new ``last_player_query`` only when:

        - *resolved_query* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent`` is one of: captain_score, player_summary,
          player_resolve, player_form (Phase 2.7c)

        Sets ``last_comparison`` to *comparison_queries* when:

        - *comparison_queries* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent == INTENT_COMPARE_PLAYERS``

        Clears ``last_comparison`` after any successful non-comparison turn.

        Sets ``last_transfer`` to *transfer_queries* when:

        - *transfer_queries* is non-empty
        - ``response.outcome == OUTCOME_OK``
        - ``response.intent == INTENT_TRANSFER_ADVICE``

        Clears ``last_transfer`` after any successful non-transfer turn.

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
        transfer_queries:
            The ``(query_out, query_in)`` extracted from the route result when
            the intent is ``transfer_advice``.  Used to update
            ``last_transfer`` (Phase 7f).
        fixture_run_query:
            The player query extracted from the route result when the intent is
            ``player_fixture_run``.  Used to update ``last_fixture_run_player``
            (Phase 8d-i).
        differential_turn:
            ``True`` when the current turn is a successful differential picks
            turn.  Used to set ``last_differential`` (Phase 8d-ii).
        resolver_source:
            The resolver-source string for this turn (Phase 5l).  One of the
            values from the ``ResolverDebug.resolver_source`` vocabulary:
            ``"none"``, ``"comparison_followup"``, ``"comparison_followup_llm"``,
            ``"transfer_followup"``, ``"fixture_run_followup"``,
            ``"differential_followup"``, ``"fallback_regex"``, ``"llm"``.
            ``None`` is stored as-is when not provided (preserves previous
            value; callers should always supply this).
        """
        self.turn_count += 1
        if (
            resolved_query
            and response.outcome == OUTCOME_OK
            and response.intent in (
                INTENT_CAPTAIN_SCORE,
                INTENT_PLAYER_SUMMARY,
                INTENT_PLAYER_RESOLVE,
                INTENT_PLAYER_FORM,   # Phase 2.7c: form turns also anchor player context
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

        # Phase 7f: transfer context tracking
        if (
            transfer_queries
            and response.outcome == OUTCOME_OK
            and response.intent == INTENT_TRANSFER_ADVICE
        ):
            self.last_transfer = transfer_queries
        elif response.outcome == OUTCOME_OK and response.intent != INTENT_TRANSFER_ADVICE:
            # Any other successful turn clears transfer context
            self.last_transfer = None

        # Phase 8d-i: fixture run context tracking
        if (
            fixture_run_query
            and response.outcome == OUTCOME_OK
            and response.intent == INTENT_PLAYER_FIXTURE_RUN
        ):
            self.last_fixture_run_player = fixture_run_query
        elif response.outcome == OUTCOME_OK and response.intent != INTENT_PLAYER_FIXTURE_RUN:
            # Any other successful turn clears fixture run context
            self.last_fixture_run_player = None

        # Phase 8d-ii: differential context tracking
        if (
            differential_turn
            and response.outcome == OUTCOME_OK
            and response.intent == INTENT_DIFFERENTIAL_PICKS
        ):
            self.last_differential = True
        elif response.outcome == OUTCOME_OK:
            # Any other successful turn clears differential context
            self.last_differential = False

        if resolver_source is not None:                     # Phase 5l
            self.last_resolver_source = resolver_source

        if question_text:
            if len(self.history) >= 3:
                self.history.pop(0)
            self.history.append((question_text, response.intent))

    def clear(self) -> None:
        """Reset all state.  Call when starting a new conversation."""
        self.last_player_query = None
        self.turn_count = 0
        self.history.clear()
        self.last_comparison = None           # Phase 5c
        self.last_transfer = None             # Phase 7f
        self.last_fixture_run_player = None   # Phase 8d-i
        self.last_differential = False        # Phase 8d-ii
        self.last_resolver_source = None      # Phase 5l


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
# Transfer follow-up resolver  (Phase 7f)
# ---------------------------------------------------------------------------

def resolve_transfer_followup(question: str, state: ConversationState) -> str | None:
    """Detect a transfer follow-up and return the rewritten canonical question.

    Requires ``state.last_transfer`` to be set from a prior successful
    transfer turn.  Returns ``None`` when no follow-up pattern matches or
    when ``state.last_transfer`` is not set.

    Supported patterns (when ``state.last_transfer == (out, inn)``):

    * ``"What about Palmer instead?"``  → ``"sell out for Palmer"``
    * ``"How about Palmer instead?"``   → ``"sell out for Palmer"``
    * ``"What about Palmer?"``          → ``"sell out for Palmer"``
    * ``"How about Palmer?"``           → ``"sell out for Palmer"``
    * ``"Palmer instead?"``             → ``"sell out for Palmer"``  (bare name)

    Parameters
    ----------
    question:
        Raw user question.
    state:
        Current ``ConversationState``.

    Returns
    -------
    str | None
        Canonical transfer question if a follow-up pattern matched, else ``None``.

    Notes
    -----
    Always anchors to the ``last_transfer[0]`` (player_out) from the prior turn.
    The rewritten form ``"sell {out} for {new}"`` is recognised by the deterministic
    ``_try_route_transfer()`` router via the ``"sell"`` prefix and ``" for "`` connector.
    LLM-assisted transfer follow-up is intentionally deferred.
    """
    if not state.last_transfer:
        return None

    last_out, _ = state.last_transfer
    q_stripped = question.strip().rstrip("?!.")
    q_norm = q_stripped.lower()

    # Pattern: "what about {player}" / "how about {player}" [+ optional "instead"]
    for prefix in _TRANSFER_FOLLOWUP_PREFIXES:
        if q_norm.startswith(prefix):
            remainder_orig = q_stripped[len(prefix):].strip().rstrip("?!.,")
            remainder_norm = remainder_orig.lower()
            for suffix in _TRANSFER_INSTEAD_SUFFIXES:
                if remainder_norm.endswith(suffix):
                    remainder_orig = remainder_orig[: len(remainder_orig) - len(suffix)].strip()
                    break
            if remainder_orig:
                return f"sell {last_out} for {remainder_orig}"

    # Pattern: bare "{player} instead" (no prefix)
    for suffix in _TRANSFER_INSTEAD_SUFFIXES:
        if q_norm.endswith(suffix):
            player = q_stripped[: len(q_stripped) - len(suffix)].strip().rstrip("?!.,")
            if player:
                return f"sell {last_out} for {player}"

    return None


# ---------------------------------------------------------------------------
# Fixture run follow-up resolver  (Phase 8d-i)
# ---------------------------------------------------------------------------

def resolve_fixture_run_followup(question: str, state: ConversationState) -> str | None:
    """Detect a fixture run follow-up and return the rewritten canonical question.

    Requires ``state.last_fixture_run_player`` to be set from a prior successful
    fixture run turn.  Returns ``None`` when no follow-up pattern matches or
    when ``state.last_fixture_run_player`` is not set.

    Supported patterns (when ``state.last_fixture_run_player`` is set):

    * ``"What about Salah?"``    → ``"Salah fixtures"``
    * ``"How about Salah?"``     → ``"Salah fixtures"``
    * ``"Salah?"``               → ``"Salah fixtures"``  (bare name, ≤ 3 words,
                                                          no interrogative start)

    Parameters
    ----------
    question:
        Raw user question.
    state:
        Current ``ConversationState``.

    Returns
    -------
    str | None
        Canonical fixture run question if a follow-up pattern matched, else ``None``.

    Notes
    -----
    The rewritten form ``"{player} fixtures"`` is recognised by
    ``_try_route_fixture_run()`` via the ``" fixtures"`` suffix pattern.
    LLM-assisted fixture run follow-up is intentionally deferred.
    The bare-name pattern applies only when the stripped question is ≤ 3 words
    and does not start with a known interrogative or sentence-starting word.
    The prefix pattern applies two plausibility guards on the remainder:
    (1) first word must not be an article, determiner, or generic fixture/time
    noun (``_FIXTURE_REMAINDER_NON_PLAYER_STARTERS``); (2) no word in the
    remainder may appear in ``_FIXTURE_REMAINDER_CONTENT_BLOCKLIST`` (e.g.
    ``"fixtures"``, ``"game"``, ``"players"``).  Phrases that contain these
    content words cannot be player references and are not rewritten.
    """
    if not state.last_fixture_run_player:
        return None

    q_stripped = question.strip().rstrip("?!.")
    q_norm = q_stripped.lower()

    # Pattern: "what about {player}" / "how about {player}" [+ optional "instead"]
    # Guards: (1) remainder first word must not be an article, determiner, or
    # generic fixture/time noun; (2) remainder must not contain any content word
    # from _FIXTURE_REMAINDER_CONTENT_BLOCKLIST (e.g. "fixtures", "players").
    for prefix in _FIXTURE_FOLLOWUP_PREFIXES:
        if q_norm.startswith(prefix):
            remainder_orig = q_stripped[len(prefix):].strip().rstrip("?!.,")
            remainder_norm = remainder_orig.lower()
            for suffix in _FIXTURE_INSTEAD_SUFFIXES:
                if remainder_norm.endswith(suffix):
                    remainder_orig = remainder_orig[: len(remainder_orig) - len(suffix)].strip()
                    remainder_norm = remainder_orig.lower()
                    break
            remainder_words = set(remainder_norm.split())
            first_word = remainder_norm.split()[0] if remainder_norm.split() else ""
            has_content_block = bool(remainder_words & _FIXTURE_REMAINDER_CONTENT_BLOCKLIST)
            if (
                remainder_orig
                and first_word not in _FIXTURE_REMAINDER_NON_PLAYER_STARTERS
                and not has_content_block
            ):
                return f"{remainder_orig} fixtures"

    # Bare name pattern: ≤ 3 words, doesn't start with an interrogative/verb.
    # Guard: skip if the question already ends with a fixture-run suffix — it is
    # a direct fixture run query, not a follow-up reference.
    _ALREADY_FIXTURE_SUFFIXES = (
        " fixtures", " fixture run", " next fixtures", " next games",
        " upcoming fixtures",
    )
    already_fixture = any(q_norm.endswith(s) for s in _ALREADY_FIXTURE_SUFFIXES)
    words = q_stripped.split()
    if (
        not already_fixture
        and words
        and len(words) <= 3
        and words[0].lower() not in _FIXTURE_INTERROGATIVE_STARTERS
    ):
        player = " ".join(w.rstrip("?!.,") for w in words).strip()
        if player:
            return f"{player} fixtures"

    return None


# ---------------------------------------------------------------------------
# Differential follow-up resolver  (Phase 8d-ii)
# ---------------------------------------------------------------------------

def resolve_differential_followup(question: str, state: ConversationState) -> str | None:
    """Detect a differential picks follow-up and return the rewritten query.

    Requires ``state.last_differential`` to be ``True`` from a prior successful
    differential picks turn.  Returns ``None`` when no follow-up pattern matches
    or when ``state.last_differential`` is ``False``.

    Supported patterns (when ``state.last_differential`` is ``True``):

    * ``"What about Mbeumo?"``   -> ``"should I captain Mbeumo?"``
    * ``"How about Palmer?"``    -> ``"should I captain Palmer?"``
    * ``"Mbeumo?"``              -> ``"should I captain Mbeumo?"``  (bare name,
                                                                     ≤ 3 words,
                                                                     no interrogative start)

    Parameters
    ----------
    question:
        Raw user question.
    state:
        Current ``ConversationState``.

    Returns
    -------
    str | None
        Canonical captain-score question for the referenced player if a follow-up
        pattern matched, else ``None``.

    Notes
    -----
    The rewritten form ``"should I captain {player}?"`` routes to the existing
    deterministic captain score path (``INTENT_CAPTAIN_SCORE``).
    LLM-assisted differential follow-up is intentionally deferred.
    Prefix remainders are validated with the same two-guard approach used by
    ``resolve_fixture_run_followup``: first word must not be in
    ``_DIFF_REMAINDER_NON_PLAYER_STARTERS`` and no word may appear in
    ``_DIFF_REMAINDER_CONTENT_BLOCKLIST``.  The content blocklist covers
    domain nouns, generic pronouns (``"ones"``, ``"some"``), FPL descriptors
    (``"ownership"``, ``"value"``) and quality adjectives (``"good"``,
    ``"low"``) that cannot be player names.  The bare-name path applies the
    same content blocklist across all words in the phrase.
    """
    if not state.last_differential:
        return None

    q_stripped = question.strip().rstrip("?!.")
    q_norm = q_stripped.lower()

    # Pattern: "what about {player}" / "how about {player}" [+ optional "instead"]
    for prefix in _DIFF_FOLLOWUP_PREFIXES:
        if q_norm.startswith(prefix):
            remainder_orig = q_stripped[len(prefix):].strip().rstrip("?!.,")
            remainder_norm = remainder_orig.lower()
            for suffix in _DIFF_INSTEAD_SUFFIXES:
                if remainder_norm.endswith(suffix):
                    remainder_orig = remainder_orig[: len(remainder_orig) - len(suffix)].strip()
                    remainder_norm = remainder_orig.lower()
                    break
            remainder_words = set(remainder_norm.split())
            first_word = remainder_norm.split()[0] if remainder_norm.split() else ""
            has_content_block = bool(remainder_words & _DIFF_REMAINDER_CONTENT_BLOCKLIST)
            if (
                remainder_orig
                and first_word not in _DIFF_REMAINDER_NON_PLAYER_STARTERS
                and not has_content_block
            ):
                return f"should I captain {remainder_orig}?"

    # Bare name pattern: ≤ 3 words, doesn't start with an interrogative/verb.
    words = q_stripped.split()
    if (
        words
        and len(words) <= 3
        and words[0].lower() not in _DIFF_INTERROGATIVE_STARTERS
    ):
        player = " ".join(w.rstrip("?!.,") for w in words).strip()
        first = player.lower().split()[0] if player.split() else ""
        player_words = set(player.lower().split())
        has_content_block = bool(player_words & _DIFF_REMAINDER_CONTENT_BLOCKLIST)
        if player and first not in _DIFF_REMAINDER_NON_PLAYER_STARTERS and not has_content_block:
            return f"should I captain {player}?"

    return None


# ---------------------------------------------------------------------------
# Player form follow-up resolver  (Phase 2.7c)
# ---------------------------------------------------------------------------

def resolve_player_form_followup(question: str, state: ConversationState) -> str | None:
    """Detect a player-form follow-up and return the rewritten canonical question.

    Requires ``state.last_player_query`` to be set from a prior successful
    player-related turn (player_summary, captain_score, or player_resolve).
    Returns ``None`` when no form follow-up pattern matches or when
    ``state.last_player_query`` is not set.

    Safety guards
    -------------
    1. Primary guard: ``state.last_player_query`` must be non-None.
    2. Pattern guard: the follow-up must unambiguously refer to recent-game
       form — either an exact phrase match or an N-game fragment with a
       numeric count.  Weak or generic questions fall through.

    Supported patterns (when ``state.last_player_query == player``)::

        "y en los ultimos 5 partidos?"   → "historial de {player} en los ultimos 5 partidos"
        "en los últimos 3 partidos?"     → "historial de {player} en los últimos 3 partidos"
        "últimos partidos?"              → "historial de {player}"
        "recent form?"                   → "historial de {player}"
        "last 5 games?"                  → "historial de {player} en los ultimos 5 partidos"
        "y su forma?"                    → "historial de {player}"

    Parameters
    ----------
    question:
        Raw user question.
    state:
        Current ``ConversationState``.

    Returns
    -------
    str | None
        Canonical player-form question if a follow-up pattern matched, else ``None``.

    Notes
    -----
    The rewritten form ``"historial de {player}"`` (or with N-games suffix) is
    recognised by ``_try_route_player_form()`` via the ``"historial de"`` prefix.
    LLM-assisted player-form follow-up is intentionally deferred.
    Ambiguous questions (no form signal, or question too long to be a mere
    follow-up phrase) fall through to existing behavior without error.
    """
    # Safety guard 1: must have a previously resolved player
    if not state.last_player_query:
        return None

    player = state.last_player_query
    q_stripped = question.strip().rstrip("?!.")
    q_norm = q_stripped.lower()

    # Strip optional leading "y " (Spanish "and") connector
    q_core = q_norm
    if q_core.startswith("y "):
        q_core = q_core[2:].strip()

    # Guard: reject overly long questions (> 8 words) — they likely contain a
    # new player name or an intent of their own and should not be hijacked.
    if len(q_stripped.split()) > 8:
        return None

    # Check exact phrases first (unambiguous form signals)
    if q_core in _FORM_EXACT_PHRASES or q_norm in _FORM_EXACT_PHRASES:
        # Try to extract N from the question; if found, include it in the rewrite
        n_match = _FORM_N_GAMES_RE.search(q_norm)
        if n_match:
            n = int(n_match.group(1))
            return f"historial de {player} en los ultimos {n} partidos"
        return f"historial de {player}"

    # Check N-game fragment patterns ("en los ultimos N ...", "last N games", etc.)
    for frag in _FORM_FRAGMENT_PHRASES:
        if frag in q_norm:
            n_match = _FORM_N_GAMES_RE.search(q_norm)
            if n_match:
                n = int(n_match.group(1))
                return f"historial de {player} en los ultimos {n} partidos"
            # Fragment present but no N found — only rewrite if fragment is
            # one of the unambiguous Spanish patterns (not the weak "last "/"past ")
            if frag not in ("last ", "past "):
                return f"historial de {player}"

    return None


# ---------------------------------------------------------------------------
# Resolver debug helper (Phase 4g / Phase 5l)
# ---------------------------------------------------------------------------

def _map_resolver_source(resolution) -> str:
    """Map a ReferenceResolution to a resolver_source string.

    Resolver source mapping (Phase 5k: comparison-specific values preserved;
    Phase 7f: transfer_followup added; Phase 8d-i: fixture_run_followup added;
    Phase 8d-ii: differential_followup added;
    Phase 2.7c: player_form_followup added):
    - "comparison_followup"     -> "comparison_followup"      (Phase 5c det. comparison rewrite)
    - "comparison_followup_llm" -> "comparison_followup_llm"  (Phase 5f LLM comparison rewrite)
    - "transfer_followup"       -> "transfer_followup"        (Phase 7f det. transfer rewrite)
    - "fixture_run_followup"    -> "fixture_run_followup"     (Phase 8d-i det. fixture run rewrite)
    - "differential_followup"   -> "differential_followup"    (Phase 8d-ii det. differential rewrite)
    - "player_form_followup"    -> "player_form_followup"     (Phase 2.7c det. form rewrite)
    - "deterministic"           -> "fallback_regex"            (Phase 4e pronoun regex)
    - "none" (confidence 0.0)   -> "none"                     (no resolver ran)
    - any LLM source            -> "llm"                      (Phase 4f LLM resolution)

    Used by ``_make_resolver_debug()`` and ``ConversationSession.respond()``
    (Phase 5l state tracking).
    """
    src = resolution.reference_source
    if src == "comparison_followup":
        return "comparison_followup"
    if src == "comparison_followup_llm":
        return "comparison_followup_llm"
    if src == "transfer_followup":          # Phase 7f
        return "transfer_followup"
    if src == "fixture_run_followup":       # Phase 8d-i
        return "fixture_run_followup"
    if src == "differential_followup":      # Phase 8d-ii
        return "differential_followup"
    if src == "player_form_followup":       # Phase 2.7c
        return "player_form_followup"
    if src == "deterministic":
        return "fallback_regex"
    if src == "none" and resolution.confidence == 0.0:
        return "none"
    return "llm"


def _make_resolver_debug(resolution, original_question: str, rewritten_question: str):
    """Build a ResolverDebug from a ReferenceResolution.

    Lazy-imports ResolverDebug to avoid circular imports.
    Source mapping delegated to ``_map_resolver_source()``.
    """
    from .final_response import ResolverDebug  # noqa: PLC0415

    resolver_source = _map_resolver_source(resolution)
    resolver_confidence = (
        float(resolution.confidence) if resolver_source in ("llm", "comparison_followup_llm") else None
    )

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
            # Phase 7f: deterministic transfer follow-up (no client needed)
            xfer_rewritten = resolve_transfer_followup(question, self.state)
            if xfer_rewritten is not None:
                rewritten = xfer_rewritten
                resolution = ReferenceResolution(
                    resolved_query=None,
                    intent_guess=INTENT_TRANSFER_ADVICE,
                    reference_source="transfer_followup",
                    confidence=1.0,
                    language="en",
                    rewritten_question=xfer_rewritten,
                    fallback_reason=None,
                )
            else:
                # Phase 8d-i: deterministic fixture run follow-up (no client needed)
                fixture_rewritten = resolve_fixture_run_followup(question, self.state)
                if fixture_rewritten is not None:
                    rewritten = fixture_rewritten
                    resolution = ReferenceResolution(
                        resolved_query=None,
                        intent_guess=INTENT_PLAYER_FIXTURE_RUN,
                        reference_source="fixture_run_followup",
                        confidence=1.0,
                        language="en",
                        rewritten_question=fixture_rewritten,
                        fallback_reason=None,
                    )
                else:
                    # Phase 8d-ii: deterministic differential follow-up (no client needed)
                    diff_rewritten = resolve_differential_followup(question, self.state)
                    if diff_rewritten is not None:
                        rewritten = diff_rewritten
                        resolution = ReferenceResolution(
                            resolved_query=None,
                            intent_guess=INTENT_CAPTAIN_SCORE,
                            reference_source="differential_followup",
                            confidence=1.0,
                            language="en",
                            rewritten_question=diff_rewritten,
                            fallback_reason=None,
                        )
                    else:
                        # Phase 2.7c: deterministic player form follow-up (no client needed)
                        form_rewritten = resolve_player_form_followup(question, self.state)
                        if form_rewritten is not None:
                            rewritten = form_rewritten
                            resolution = ReferenceResolution(
                                resolved_query=None,
                                intent_guess=INTENT_PLAYER_FORM,
                                reference_source="player_form_followup",
                                confidence=1.0,
                                language="en",
                                rewritten_question=form_rewritten,
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

        # Compute resolver_source for state tracking (Phase 5l — always, not debug-only)
        _resolver_src = _map_resolver_source(resolution)

        # Build resolver debug bundle when debug is requested
        _resolver_debug = None
        if include_debug:
            _resolver_debug = _make_resolver_debug(resolution, question, rewritten)

        # Extract player_query, comparison_queries, transfer_queries, fixture_run_query,
        # and differential_turn for state tracking
        route_result = route(rewritten)
        player_query: str | None = None
        comparison_queries: tuple[str, str] | None = None
        transfer_queries: tuple[str, str] | None = None
        fixture_run_query: str | None = None
        differential_turn: bool = False
        if route_result is not None:
            player_query = route_result.tool_args.get("query") or None
            if route_result.tool_name == "compare_players":
                qa = route_result.tool_args.get("query_a", "")
                qb = route_result.tool_args.get("query_b", "")
                if qa and qb:
                    comparison_queries = (qa, qb)
            if route_result.tool_name == "get_transfer_advice":
                qout = route_result.tool_args.get("query_out", "")
                qin  = route_result.tool_args.get("query_in", "")
                if qout and qin:
                    transfer_queries = (qout, qin)
            if route_result.tool_name == "get_player_fixture_run":  # Phase 8d-i
                fq = route_result.tool_args.get("query", "")
                if fq:
                    fixture_run_query = fq
            if route_result.tool_name == "get_differential_picks":  # Phase 8d-ii
                differential_turn = True

        response = _respond(rewritten, bootstrap, **kwargs, _resolver_debug=_resolver_debug)
        self.state.update_from_response(
            response, player_query, question_text=rewritten,
            comparison_queries=comparison_queries,
            transfer_queries=transfer_queries,    # Phase 7f
            fixture_run_query=fixture_run_query,  # Phase 8d-i
            differential_turn=differential_turn,  # Phase 8d-ii
            resolver_source=_resolver_src,        # Phase 5l
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
