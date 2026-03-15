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

from dataclasses import dataclass
from typing import Any

from .harness import ask
from .router import route


# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTENT_CAPTAIN_SCORE:    str = "captain_score"
INTENT_RANK_CANDIDATES:  str = "rank_candidates"
INTENT_CURRENT_GAMEWEEK: str = "current_gameweek"
INTENT_PLAYER_SUMMARY:   str = "player_summary"
INTENT_PLAYER_RESOLVE:   str = "player_resolve"
INTENT_COMPARE_PLAYERS:  str = "compare_players"   # Phase 5a
INTENT_UNSUPPORTED:      str = "unsupported"

SUPPORTED_INTENTS: frozenset[str] = frozenset({
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_COMPARE_PLAYERS,
})


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
    "get_captain_score":       INTENT_CAPTAIN_SCORE,
    "rank_captain_candidates": INTENT_RANK_CANDIDATES,
    "get_current_gameweek":    INTENT_CURRENT_GAMEWEEK,
    "get_player_summary":      INTENT_PLAYER_SUMMARY,
    "resolve_player":          INTENT_PLAYER_RESOLVE,
    "compare_players":         INTENT_COMPARE_PLAYERS,   # Phase 5a
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
        "description":             "Compare two players as captain candidates by grounded captain score",
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
}


# ---------------------------------------------------------------------------
# DispatchResult
# ---------------------------------------------------------------------------

_UNSUPPORTED_ANSWER = (
    "I couldn't match that question to a supported query. "
    "Supported questions include: captain score for a player, captain rankings, "
    "player comparison, player summary, player lookup, and current gameweek."
)

_MISSING_CANDIDATES_ANSWER = (
    "Captain rankings require a candidates list. "
    "Please provide players to rank via the candidates_list parameter."
)


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
    """
    intent:        str
    question:      str
    selected_tool: str | None
    raw_output:    dict[str, Any]
    answer_text:   str
    context_meta:  dict[str, Any] | None
    outcome:       str  # Phase 2l: OUTCOME_* constant


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

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
    result = ask(
        question,
        bootstrap,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
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
    )