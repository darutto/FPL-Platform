"""
fpl_grounded_assistant.dispatcher
==================================
Phase 2k: Minimal model-facing dispatcher.
Phase 2l: Intent manifest, outcome field, improved failure messaging.

Provides a typed ``dispatch()`` entrypoint and an explicit intent registry
for all supported natural-language question types.

This module is the model-facing surface that a future LLM tool-use loop
will call.  All backend execution remains deterministic: the dispatcher
delegates directly to ``ask()`` (harness layer) without adding any LLM
calls, fuzzy matching, or multi-turn state.

Orchestration boundary (must not blur across slices)
----------------------------------------------------
``route()``    — intent guess: keyword pattern → tool name
``ask()``      — grounded backend execution: tool name + bootstrap → raw dict
``dispatch()`` — model-facing adapter: question → DispatchResult

Supported intents (v1, heuristic)
----------------------------------
``INTENT_CAPTAIN_SCORE``
    "Should I captain X?" / "Captain score for X"
``INTENT_RANK_CANDIDATES``
    "Top captains this week" / "Captain rankings"
``INTENT_CURRENT_GAMEWEEK``
    "What is the current gameweek?"
``INTENT_PLAYER_SUMMARY``
    "Give me a summary for X" / "Stats for X"
``INTENT_PLAYER_RESOLVE``
    "Who is X?" / "Find X"

Outcome vocabulary
------------------
Every ``DispatchResult`` carries an ``outcome`` that unambiguously describes
the combined result of routing + tool execution:

``OUTCOME_OK``                 — tool executed and answered successfully
``OUTCOME_UNSUPPORTED_INTENT`` — question not mappable to any supported intent
``OUTCOME_NOT_FOUND``          — intent matched but player was not found
``OUTCOME_AMBIGUOUS``          — intent matched but player query is ambiguous
``OUTCOME_MISSING_ARGUMENTS``  — intent matched but required args were missing
``OUTCOME_ERROR``              — intent matched but tool returned an error

What is intentionally deferred
--------------------------------
* LLM-based intent classification
* Multi-turn conversation memory
* Pronoun resolution ("What about his form?")
* Combined intents ("Who is Salah and what gameweek is it?")
* Broad fuzzy matching beyond existing keyword patterns
* UI integration

Phase 2l note: intent manifest and outcome constants are v1; document
changes explicitly in later slices.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .harness import ask
from .intent_classifier import classify_intent_llm
from .router import route


# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTENT_CAPTAIN_SCORE:    str = "captain_score"
INTENT_RANK_CANDIDATES:  str = "rank_candidates"
INTENT_CURRENT_GAMEWEEK: str = "current_gameweek"
INTENT_PLAYER_SUMMARY:   str = "player_summary"
INTENT_PLAYER_RESOLVE:   str = "player_resolve"
INTENT_COMPARE_PLAYERS:       str = "compare_players"       # Phase 5a
INTENT_TRANSFER_ADVICE:       str = "transfer_advice"       # Phase 6a
INTENT_CHIP_ADVICE:           str = "chip_advice"           # Phase 6b
INTENT_MULTI_INTENT:          str = "multi_intent"          # Phase 6c
INTENT_PLAYER_FIXTURE_RUN:    str = "player_fixture_run"    # Phase 7h
INTENT_DIFFERENTIAL_PICKS:    str = "differential_picks"    # Phase 7g
INTENT_PLAYER_FORM:             str = "player_form"             # Phase 2.6d
INTENT_INJURY_LIST:             str = "injury_list"             # Phase 2.6d
INTENT_PRICE_CHANGES:           str = "price_changes"           # Phase 2.6d
INTENT_TEAM_FIXTURE_CALENDAR:   str = "team_fixture_calendar"   # Phase 2.6e
INTENT_TEAM_SCHEDULE:           str = "team_schedule"            # Phase 2.6e.3
INTENT_POSITION_FIXTURE_RUN:    str = "position_fixture_run"     # Phase 2.6e.4
INTENT_TRANSFER_SUGGESTION:     str = "transfer_suggestion"       # Phase 2.6h
INTENT_UNSUPPORTED:             str = "unsupported"

SUPPORTED_INTENTS: frozenset[str] = frozenset({
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,            # Phase 6b
    INTENT_PLAYER_FIXTURE_RUN,     # Phase 7h
    INTENT_DIFFERENTIAL_PICKS,     # Phase 7g
    INTENT_PLAYER_FORM,              # Phase 2.6d
    INTENT_INJURY_LIST,              # Phase 2.6d
    INTENT_PRICE_CHANGES,            # Phase 2.6d
    INTENT_TEAM_FIXTURE_CALENDAR,    # Phase 2.6e
    INTENT_TEAM_SCHEDULE,            # Phase 2.6e.3
    INTENT_POSITION_FIXTURE_RUN,     # Phase 2.6e.4
    INTENT_TRANSFER_SUGGESTION,      # Phase 2.6h
})


# ---------------------------------------------------------------------------
# Intent hint support  (V2 slash-command routing bias)
#
# _HINT_CANONICAL_TEMPLATES maps each hintable intent to a canonical question
# template.  Templates with ``{question}`` substitute the stripped user
# question.  Templates without ``{question}`` are fixed (self-contained intents
# that need no player extraction).
#
# The allowlist is intentionally narrower than SUPPORTED_INTENTS: only the
# six V2 slash-command targets are included.  ``current_gameweek``,
# ``player_summary``, and ``player_resolve`` are excluded because they are
# either trivially routable already or not targeted by slash commands.
# ---------------------------------------------------------------------------

_HINT_CANONICAL_TEMPLATES: dict[str, str] = {
    INTENT_CAPTAIN_SCORE:      "should I captain {question}",
    INTENT_RANK_CANDIDATES:    "top captains this week",
    INTENT_COMPARE_PLAYERS:    "compare {question}",
    INTENT_TRANSFER_ADVICE:    "sell {question}",
    INTENT_CHIP_ADVICE:        "should I use {question} this week",
    INTENT_PLAYER_FIXTURE_RUN: "{question} fixtures",
    INTENT_DIFFERENTIAL_PICKS: "differentials",
}

# Derived from template keys — the only values accepted for intent_hint.
INTENT_HINT_ALLOWLIST: frozenset[str] = frozenset(_HINT_CANONICAL_TEMPLATES)


# ---------------------------------------------------------------------------
# Outcome constants  (Phase 2l)
# ---------------------------------------------------------------------------

OUTCOME_OK:                 str = "ok"
OUTCOME_UNSUPPORTED_INTENT: str = "unsupported_intent"
OUTCOME_NOT_FOUND:          str = "not_found"
OUTCOME_AMBIGUOUS:          str = "ambiguous"
OUTCOME_MISSING_ARGUMENTS:  str = "missing_arguments"
OUTCOME_ERROR:              str = "error"


# ---------------------------------------------------------------------------
# Tool name → intent label
# ---------------------------------------------------------------------------

_TOOL_TO_INTENT: dict[str, str] = {
    "get_captain_score":          INTENT_CAPTAIN_SCORE,
    "rank_captain_candidates":    INTENT_RANK_CANDIDATES,
    "get_current_gameweek":       INTENT_CURRENT_GAMEWEEK,
    "get_player_summary":         INTENT_PLAYER_SUMMARY,
    "resolve_player":             INTENT_PLAYER_RESOLVE,
    "compare_players":            INTENT_COMPARE_PLAYERS,         # Phase 5a
    "get_transfer_advice":        INTENT_TRANSFER_ADVICE,         # Phase 6a
    "get_chip_advice":            INTENT_CHIP_ADVICE,             # Phase 6b
    "get_player_fixture_run":     INTENT_PLAYER_FIXTURE_RUN,      # Phase 7h
    "get_differential_picks":     INTENT_DIFFERENTIAL_PICKS,      # Phase 7g
    "get_player_form":              INTENT_PLAYER_FORM,             # Phase 2.6d
    "get_injury_list":              INTENT_INJURY_LIST,             # Phase 2.6d
    "get_price_changes":            INTENT_PRICE_CHANGES,           # Phase 2.6d
    "get_team_fixture_calendar":    INTENT_TEAM_FIXTURE_CALENDAR,   # Phase 2.6e
    "get_team_schedule":            INTENT_TEAM_SCHEDULE,            # Phase 2.6e.3
    "get_position_fixture_run":     INTENT_POSITION_FIXTURE_RUN,     # Phase 2.6e.4
    "get_transfer_suggestion":      INTENT_TRANSFER_SUGGESTION,       # Phase 2.6h
}


# ---------------------------------------------------------------------------
# Intent manifest  (Phase 2l)
# ---------------------------------------------------------------------------

INTENT_MANIFEST: dict[str, dict[str, Any]] = {
    INTENT_CAPTAIN_SCORE: {
        "tool":                    "get_captain_score",
        "description":             "Score a single player as a captain candidate",
        "requires_player_query":   True,
        "requires_candidates_list": False,
        "example_phrasings": [
            "should I captain Haaland",
            "captain score for Salah",
            "captaincy for De Bruyne",
            "get captain score for Saka",
            "should I pick Haaland as captain",
        ],
    },
    INTENT_RANK_CANDIDATES: {
        "tool":                    "rank_captain_candidates",
        "description":             "Rank a list of captain candidates by score",
        "requires_player_query":   False,
        "requires_candidates_list": True,
        "example_phrasings": [
            "top captains this week",
            "captain rankings",
            "rank my captains",
            "best captains",
            "give me captain rankings",
        ],
    },
    INTENT_CURRENT_GAMEWEEK: {
        "tool":                    "get_current_gameweek",
        "description":             "Get the current FPL gameweek number",
        "requires_player_query":   False,
        "requires_candidates_list": False,
        "example_phrasings": [
            "what is the current gameweek",
            "current gw",
            "what gameweek is it",
            "which gameweek are we in",
        ],
    },
    INTENT_PLAYER_SUMMARY: {
        "tool":                    "get_player_summary",
        "description":             "Get a cost, position, and status summary for a player",
        "requires_player_query":   True,
        "requires_candidates_list": False,
        "example_phrasings": [
            "give me a summary for Salah",
            "stats for Haaland",
            "tell me about Saka",
            "summary of De Bruyne",
        ],
    },
    INTENT_PLAYER_RESOLVE: {
        "tool":                    "resolve_player",
        "description":             "Look up a player identity by name or alias",
        "requires_player_query":   True,
        "requires_candidates_list": False,
        "example_phrasings": [
            "who is Haaland",
            "find Salah",
            "look up De Bruyne",
            "search for Saka",
        ],
    },
    INTENT_COMPARE_PLAYERS: {
        "tool":                    "compare_players",
        "description":             "Compare two players by position-aware score (captain score + position heuristic)",
        "requires_player_query":   False,
        "requires_candidates_list": False,
        "example_phrasings": [
            "compare Haaland and Salah",
            "Haaland vs Salah",
            "who is better, Haaland or Salah",
            "compare Saka vs Salah",
            "who would you captain between Haaland and Salah",
        ],
    },
    INTENT_TRANSFER_ADVICE: {                                  # Phase 6a
        "tool":                    "get_transfer_advice",
        "description":             "Deterministic transfer recommendation for selling one player and buying another",
        "requires_player_query":   False,
        "requires_candidates_list": False,
        "example_phrasings": [
            "should I sell Saka for Palmer",
            "should I transfer out Bruno for Foden",
            "sell Haaland for Salah",
            "transfer out Saka for Palmer",
            "swap Saka for Palmer",
            "replace Bruno with Foden",
        ],
    },
    INTENT_CHIP_ADVICE: {                                      # Phase 6b
        "tool":                    "get_chip_advice",
        "description":             "Deterministic chip advice for FPL chips (triple captain, wildcard, bench boost, free hit)",
        "requires_player_query":   False,
        "requires_candidates_list": False,
        "example_phrasings": [
            "should I use triple captain this week",
            "should I wildcard this week",
            "should I bench boost now",
            "should I free hit this gameweek",
            "is this a good week for bench boost",
            "wildcard this week",
        ],
    },
    INTENT_PLAYER_FIXTURE_RUN: {                               # Phase 7h
        "tool":                    "get_player_fixture_run",
        "description":             "Retrieve upcoming fixture run for a player (default 5 fixtures)",
        "requires_player_query":   True,
        "requires_candidates_list": False,
        "example_phrasings": [
            "Haaland fixtures",
            "Salah next 5 games",
            "upcoming fixtures for Palmer",
            "fixtures for Saka",
            "fixture run for De Bruyne",
            "Haaland next games",
        ],
    },
    INTENT_DIFFERENTIAL_PICKS: {                               # Phase 7g
        "tool":                    "get_differential_picks",
        "description":             "Return top differential FPL picks (ownership < 15%, ranked by position score)",
        "requires_player_query":   False,
        "requires_candidates_list": False,
        "example_phrasings": [
            "good differentials",
            "differential options",
            "low ownership picks",
            "best differentials this week",
            "differentials",
            "show me differentials",
            "low owned players",
        ],
    },
}


# ---------------------------------------------------------------------------
# DispatchResult
# ---------------------------------------------------------------------------

_UNSUPPORTED_ANSWER = (
    "I couldn't match that question to a supported query. "
    "Supported questions include: captain score for a player, captain rankings, "
    "player comparison, transfer advice, chip advice, player fixture run, "
    "differential picks, player summary, player lookup, and current gameweek."
)

_MISSING_CANDIDATES_ANSWER = (
    "Captain rankings require a candidates list. "
    "Please provide players to rank via the candidates_list parameter."
)

_AUTO_CANDIDATES_TOP_N = 10


def _auto_candidates_from_bootstrap(
    bootstrap: dict[str, Any],
    top_n: int = _AUTO_CANDIDATES_TOP_N,
) -> list[dict[str, Any]]:
    """Return the top-N available players by form as a candidates list.

    Used when ``rank_captain_candidates`` is triggered but no explicit
    ``candidates_list`` is provided.  Selects available players only
    (``status == 'a'``), sorted by form descending.  Each entry is a
    minimal ``{"query": web_name}`` dict — scoring inputs are auto-derived
    by the tool layer from the bootstrap element.
    """
    elements = [
        e for e in bootstrap.get("elements", [])
        if e.get("status") == "a" and e.get("web_name")
    ]
    elements.sort(key=lambda e: float(e.get("form", "0") or 0), reverse=True)
    return [{"query": e["web_name"]} for e in elements[:top_n]]


@dataclass(frozen=True)
class DispatchResult:
    """Typed result returned by ``dispatch()``.

    Attributes
    ----------
    intent:
        Semantic intent label — one of the ``INTENT_*`` constants, or
        ``INTENT_UNSUPPORTED`` when no supported intent was matched.
    question:
        The original question string, preserved with original casing.
    selected_tool:
        The tool name executed by the backend runner, or ``None`` when
        ``intent == INTENT_UNSUPPORTED``.
    raw_output:
        The structured dict returned by the tool runner.  For unsupported
        questions this is
        ``{"status": "unsupported", "code": "unsupported_intent", "question": <question>}``.
    answer_text:
        Human-readable rendered answer.  Always a non-empty string.
    context_meta:
        The ``meta`` dict from an assembled context (Phase 2f), or ``None``
        when a raw bootstrap was passed or the intent was unsupported.
    outcome:
        Unified outcome label — one of the ``OUTCOME_*`` constants.
        Combines ``intent`` and ``raw_output["status"]`` so callers can
        distinguish unsupported intent / missing arguments / ambiguous player
        / not found / ok without inspecting two fields separately.
    classification_source:
        How intent was determined (Phase 4k).  ``None`` when deterministic
        ``route()`` succeeded on the first attempt.  ``"llm_classifier"``
        when the LLM classifier was used as a fallback and its
        ``canonical_question`` was successfully re-routed.
    """
    intent:               str
    question:             str
    selected_tool:        str | None
    raw_output:           dict[str, Any]
    answer_text:          str
    context_meta:         dict[str, Any] | None
    outcome:              str   # Phase 2l: OUTCOME_* constant
    classification_source: str | None = field(default=None)  # Phase 4k


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _try_route_with_hint(
    question: str,
    intent_hint: str,
) -> "tuple[RouteResult, str] | None":
    """Attempt to route *question* biased toward *intent_hint*.

    Returns ``(RouteResult, canonical_question)`` when the hint produces a
    valid route, ``None`` otherwise.

    The hint is applied only when:

    * ``intent_hint`` is in ``INTENT_HINT_ALLOWLIST``.
    * A canonical question can be synthesised (non-empty player for
      player-requiring intents).
    * ``route(canonical_question)`` succeeds.

    For self-contained intents (``rank_candidates``, ``differential_picks``)
    the canonical question is fixed and always routes.  For player-requiring
    intents, the stripped user question is substituted into a template; if the
    result is empty the hint is silently ignored.

    Parameters
    ----------
    question:
        The original user question (may be a bare player name, a partial
        sentence, or a complete question that ``route()`` already handled).
    intent_hint:
        Caller-supplied intent label.  Any value outside
        ``INTENT_HINT_ALLOWLIST`` returns ``None`` immediately.

    Returns
    -------
    tuple[RouteResult, str] | None
        ``(route_result, effective_question)`` on success so that ``dispatch()``
        can pass the canonical form to ``ask()``.  ``None`` on any failure.
    """
    if intent_hint not in INTENT_HINT_ALLOWLIST:
        return None

    template = _HINT_CANONICAL_TEMPLATES[intent_hint]
    uses_question = "{question}" in template

    if uses_question:
        q_strip = question.strip().rstrip("?!.")
        if not q_strip:
            return None
        canonical = template.format(question=q_strip)
    else:
        canonical = template

    rr = route(canonical)
    if rr is None:
        return None
    return rr, canonical


def _compute_outcome(intent: str, raw_output: dict[str, Any]) -> str:
    """Derive a unified ``OUTCOME_*`` label from ``intent`` + ``raw_output``."""
    if intent == INTENT_UNSUPPORTED:
        return OUTCOME_UNSUPPORTED_INTENT
    status = raw_output.get("status", "error")
    if status == "ok":
        return OUTCOME_OK
    if status == "not_found":
        return OUTCOME_NOT_FOUND
    if status == "ambiguous":
        return OUTCOME_AMBIGUOUS
    if status == "error":
        if raw_output.get("code") == "missing_argument":
            return OUTCOME_MISSING_ARGUMENTS
        return OUTCOME_ERROR
    return OUTCOME_ERROR


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def dispatch(
    question: str,
    bootstrap: dict[str, Any],
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    classifier_client: Any = None,
    intent_hint: str | None = None,
) -> DispatchResult:
    """
    Model-facing dispatcher.  Accepts a natural-language question, routes it
    through the grounded assistant backend, and returns a typed
    ``DispatchResult``.

    Unsupported prompts are handled safely — no exception is raised.

    Parameters
    ----------
    question:
        A user-style natural-language question.
    bootstrap:
        Either a raw FPL bootstrap dict or a full assembled context dict
        from ``fpl_pipeline.assemble_captain_context()`` (Phase 2f).
        The harness layer handles context detection automatically.
    candidate_inputs:
        Optional explicit scoring overrides for ``get_captain_score``.
        All four scoring inputs are auto-derived from bootstrap; pass
        explicit values here only to override.
    candidates_list:
        Optional list of candidate dicts for ``rank_captain_candidates``.
        Each dict requires at minimum ``"query"``.

    Returns
    -------
    DispatchResult
        Always returned — never raises.  Check ``result.outcome`` for a
        unified status, or ``result.intent`` to inspect the semantic intent.

    outcome values
    --------------
    ``OUTCOME_OK``                 — successful answer
    ``OUTCOME_UNSUPPORTED_INTENT`` — question not routable
    ``OUTCOME_NOT_FOUND``          — player not found
    ``OUTCOME_AMBIGUOUS``          — player query is ambiguous
    ``OUTCOME_MISSING_ARGUMENTS``  — required args missing (e.g. no candidates_list)
    ``OUTCOME_ERROR``              — tool returned an unexpected error

    Examples
    --------
    Supported question::

        result = dispatch("Should I captain Haaland?", bootstrap)
        assert result.outcome == OUTCOME_OK
        assert result.intent  == INTENT_CAPTAIN_SCORE

    Unsupported question::

        result = dispatch("Is Haaland fit?", bootstrap)
        assert result.outcome == OUTCOME_UNSUPPORTED_INTENT
        assert result.selected_tool is None

    Missing candidates::

        result = dispatch("top captains this week", bootstrap)  # no candidates_list
        assert result.outcome == OUTCOME_MISSING_ARGUMENTS
    """
    # Pre-check intent via deterministic router before executing any tool.
    route_result = route(question)
    classification_source: str | None = None
    # effective_question is what ask() will use; stays as original unless
    # hint synthesis or Phase 4k classification rewrites it to a canonical form.
    effective_question: str = question

    # V2: intent_hint bias — fires ONLY when deterministic route() returns None.
    # Applies a canonical-question template for the hinted intent; falls back
    # silently when the hint is invalid, not in allowlist, or produces no route.
    if route_result is None and intent_hint is not None:
        _hint_result = _try_route_with_hint(question, intent_hint)
        if _hint_result is not None:
            route_result, effective_question = _hint_result
            classification_source = "intent_hint"

    # Phase 4k: LLM classification fallback — fires ONLY when route() returns None.
    if route_result is None and classifier_client is not None:
        classification = classify_intent_llm(question, classifier_client)
        if classification is not None:
            # Re-route the canonical question through the deterministic router.
            # Player extraction still happens inside route() — not in the classifier.
            route_result = route(classification.canonical_question)
            if route_result is not None:
                classification_source = "llm_classifier"
                # Pass canonical question to ask() so its internal route() also succeeds.
                effective_question = classification.canonical_question

    if route_result is None:
        return DispatchResult(
            intent=INTENT_UNSUPPORTED,
            question=question,
            selected_tool=None,
            raw_output={
                "status":   "unsupported",
                "code":     "unsupported_intent",
                "question": question,
            },
            answer_text=_UNSUPPORTED_ANSWER,
            context_meta=None,
            outcome=OUTCOME_UNSUPPORTED_INTENT,
        )

    # Delegate to harness — inherits all context detection (Phase 2f) and
    # auto-derivation (Phase 2c/2d) logic.
    # Use effective_question (canonical form when Phase 4k classification fired)
    # so harness.ask()'s internal route() call also succeeds.

    # Auto-populate candidates for ranking intent when none are provided.
    # Users naturally ask "top captains this week" without specifying players;
    # auto-select the top-N available players by form from the bootstrap.
    effective_candidates = candidates_list
    if (
        route_result.tool_name == "rank_captain_candidates"
        and not effective_candidates
    ):
        effective_candidates = _auto_candidates_from_bootstrap(bootstrap)

    result = ask(
        effective_question,
        bootstrap,
        candidate_inputs=candidate_inputs,
        candidates_list=effective_candidates,
    )

    raw_output = result["raw_output"]
    intent     = _TOOL_TO_INTENT.get(route_result.tool_name, INTENT_UNSUPPORTED)
    outcome    = _compute_outcome(intent, raw_output)

    # Improve answer_text for the missing-candidates case: the generic runner
    # message ("missing required argument: candidates") is not caller-friendly.
    answer_text = result["answer_text"]
    if outcome == OUTCOME_MISSING_ARGUMENTS and intent == INTENT_RANK_CANDIDATES:
        answer_text = _MISSING_CANDIDATES_ANSWER

    return DispatchResult(
        intent=intent,
        question=question,
        selected_tool=result["selected_tool"],
        raw_output=raw_output,
        answer_text=answer_text,
        context_meta=result.get("context_meta"),
        outcome=outcome,
        classification_source=classification_source,
    )