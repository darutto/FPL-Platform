"""
fpl_grounded_assistant.final_response
======================================
Unified final-response policy layer.

Phase 3c: Unified final response policy.

This module is the outermost caller-facing surface of the fpl-grounded-assistant
stack.  It encapsulates the full pipeline and exposes a single ``FinalResponse``
object that makes the final-response policy explicit and unambiguous.

Stack layers (innermost to outermost)
--------------------------------------
::

    respond()
      └── ask_llm_safe()           ← review gate (Phase 3b)
            └── ask_llm()          ← LLM presentation (Phase 3a)
                  └── adapt()      ← deterministic adapter (Phase 2m)
                        └── dispatch()   ← typed dispatcher (Phase 2k/2l)
                              └── ask()  ← grounded harness (Phase 1h)

Final-response policy
---------------------
``final_text`` is always ``review.safe_text``:

* LLM called, review passed → ``final_text = llm_text``   (``llm_used=True``)
* LLM not called (fallback) → ``final_text = response_text``  (``llm_used=False``)
* LLM called, review failed → ``final_text = response_text``  (``llm_used=False``)

This single rule eliminates ambiguity for callers — they always get the safest
available text without inspecting internal review state.

Caller-facing vs debug-facing
------------------------------
``FinalResponse`` exposes six caller-facing fields::

    final_text    — the text to show the user
    outcome       — OUTCOME_* constant for routing decisions
    supported     — intent within scope (True) or not (False)
    intent        — INTENT_* constant for logging and analytics
    review_passed — did LLM text pass parity checks?
    llm_used      — is final_text LLM-generated (and accepted)?

And one optional debug bundle::

    debug — FinalResponseDebug | None

The debug bundle is ``None`` by default.  Callers may opt in with
``include_debug=True`` to get internal fields (``llm_text``, ``response_text``,
``violations``, ``prompt_used``, ``model``) for diagnostics and regression
testing.  These fields are explicitly **not** part of the caller-facing contract.

``llm_used`` semantics
-----------------------
``llm_used=True`` means exactly: an actual Anthropic API call was made AND the
returned text passed the deterministic parity review.  When ``llm_used=False``
the deterministic ``response_text`` is surfaced, which is always safe regardless
of reason (no API key, API error, review failure, etc.).

Intentionally deferred
-----------------------
* Multi-turn conversation memory
* Pronoun resolution
* Combined intents
* UI integration
* Model-based review (Phase 3b established deterministic-only review)
* Streaming responses
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dispatcher import OUTCOME_OK, INTENT_COMPARE_PLAYERS, INTENT_CAPTAIN_SCORE, INTENT_RANK_CANDIDATES, INTENT_MULTI_INTENT, INTENT_TRANSFER_ADVICE, INTENT_CHIP_ADVICE, INTENT_PLAYER_FIXTURE_RUN, INTENT_DIFFERENTIAL_PICKS  # noqa: F401 — re-exported
from .dispatcher import _TOOL_TO_INTENT, INTENT_UNSUPPORTED  # Orch-4a: tool->intent map
from .multi_intent import detect_multi_intent
from .llm_layer import DEFAULT_MODEL
from .llm_review import ask_llm_safe
from .orch_config import is_orch_enabled, get_orch_provider  # Orch-4a: feature flag
from .orchestrator import (  # Orch-4a/4c: orchestration entrypoint and audit constants
    ask_orchestrated,
    OrchestratorResult,
    OUTCOME_OK          as ORCH_OUTCOME_OK,
    OUTCOME_NO_CLIENT   as ORCH_OUTCOME_NO_CLIENT,        # Orch-4c re-export
    OUTCOME_LLM_ERROR   as ORCH_OUTCOME_LLM_ERROR,        # Orch-4c re-export
    OUTCOME_NO_TOOL     as ORCH_OUTCOME_NO_TOOL,          # Orch-4c re-export
    OUTCOME_UNKNOWN_TOOL as ORCH_OUTCOME_UNKNOWN_TOOL,    # Orch-4c re-export
    OUTCOME_TOOL_ERROR  as ORCH_OUTCOME_TOOL_ERROR,       # Orch-4c re-export
    OUTCOME_TOOL_RESULT_ERROR as ORCH_OUTCOME_TOOL_RESULT_ERROR,  # Orch-4c re-export
)


# ---------------------------------------------------------------------------
# Captain score metadata bundle  (Phase 5n)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaptainScoreMeta:
    """Structured captain score output for programmatic access.

    Populated on ``FinalResponse`` when ``intent == captain_score`` and
    ``outcome == ok``.  ``None`` for all other turns.

    All values are taken directly from the deterministic backend output
    (``tool_get_captain_score``); nothing is computed in this layer.

    Attributes
    ----------
    web_name:
        Player display name (e.g. ``"Haaland"``).
    team_short:
        Short team name (e.g. ``"MCI"``).
    captain_score:
        Deterministic captain score (0–100 range, unrounded from engine).
    tier:
        Tier classification: ``"safe"``, ``"upside"``, ``"differential"``,
        ``"avoid"``, or ``"low_confidence"``.
    role_bonus:
        Numeric role contribution from set-piece involvement
        (e.g. ``5.0`` for penalty taker, ``0.0`` for no role).
    set_piece_notes:
        Tuple of role-key strings (e.g. ``("penalty_taker_1",)``).
        Empty tuple when no set-piece role is recorded.
    """

    web_name:        str
    team_short:      str
    captain_score:   float
    tier:            str
    role_bonus:      float
    set_piece_notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Ranked captain candidate metadata  (Phase 5p)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankedCaptainEntry:
    """One entry in a ranked captain candidates list.

    Populated as elements of ``FinalResponse.captain_ranking`` when
    ``intent == rank_candidates`` and ``outcome == ok``.

    All values come directly from the deterministic ``tool_rank_captain_candidates``
    output; nothing is computed in this layer.

    Attributes
    ----------
    rank:
        1-based rank position by captain_score descending.
    web_name:
        Player display name (e.g. ``"Salah"``).
    team_short:
        Short team name (e.g. ``"LIV"``).
    captain_score:
        Deterministic captain score for this player.
    tier:
        Tier classification: ``"safe"``, ``"upside"``, ``"differential"``,
        ``"avoid"``, or ``"low_confidence"``.
    role_bonus:
        Numeric role contribution from set-piece involvement.
    set_piece_notes:
        Tuple of role-key strings (e.g. ``("penalty_taker_1",)``).
        Empty tuple when no set-piece role is recorded.
    """

    rank:            int
    web_name:        str
    team_short:      str
    captain_score:   float
    tier:            str
    role_bonus:      float
    set_piece_notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Transfer advice metadata bundle  (Phase 7a)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransferMeta:
    """Structured transfer advice output for programmatic access.

    Populated on ``FinalResponse`` when ``intent == transfer_advice`` and
    ``outcome == ok``.  ``None`` for all other turns.

    All values are taken directly from the deterministic backend output
    (``get_transfer_advice``); nothing is computed in this layer.

    Attributes
    ----------
    player_out:
        Web name of the player being sold (e.g. ``"Saka"``).
    player_in:
        Web name of the player being bought (e.g. ``"Salah"``).
    recommendation:
        Transfer recommendation: ``"transfer_in"`` (score_delta > 5.0),
        ``"marginal_transfer_in"`` (0 < delta ≤ 5.0), or
        ``"hold"`` (delta ≤ 0).
    score_delta:
        Deterministic captain score difference: ``captain_score_in − captain_score_out``.
        Positive when player_in scores higher; negative when player_out is better.
    price_delta:
        Cost difference in tenths of £: ``now_cost_in − now_cost_out``.
        Positive when player_in is more expensive.  Informational only; does
        not affect the recommendation.
    reasons:
        Tuple of deterministic advantage phrases for player_in
        (e.g. ``("stronger form (9.5 vs 8.0)", "easier fixture (FDR 2 vs 4)")``).
        Empty tuple when no single signal clears its threshold, or when the
        recommendation is ``"hold"`` and player_in has no clear edge.
    """

    player_out:        str
    player_in:         str
    recommendation:    str
    score_delta:       float
    price_delta:       int
    reasons:           tuple[str, ...]
    budget_constraint: bool = False  # Phase 8e1: True when price_delta > squad_context.itb
    hit_warning:       bool = False  # Phase 8e2: True when free_transfers==1 AND recommendation==marginal_transfer_in


# ---------------------------------------------------------------------------
# Chip advice metadata bundle  (Phase 7b)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChipAdviceMeta:
    """Structured chip advice output for programmatic access.

    Populated on ``FinalResponse`` when ``intent == chip_advice`` and
    ``outcome == ok``.  ``None`` for all other turns.

    All values are taken directly from the deterministic backend output
    (``get_chip_advice``); nothing is computed in this layer.

    Attributes
    ----------
    chip:
        The FPL chip name: ``"triple_captain"``, ``"wildcard"``,
        ``"bench_boost"``, or ``"free_hit"``.
    recommendation:
        Conditions assessment: ``"conditions_favorable"``,
        ``"conditions_marginal"``, ``"conditions_unfavorable"``, or
        ``"missing_context"`` (when required data is unavailable,
        e.g. free_hit without DGW/BGW detection).
    gw:
        Current gameweek number at the time of the query.  ``None``
        when the gameweek could not be determined from bootstrap.
    signal_value:
        Chip-specific deterministic numeric signal used to derive the
        recommendation:

        * ``triple_captain`` — top available MID/FWD captain score
          (e.g. ``83.5``).
        * ``wildcard`` — current gameweek number as a float
          (e.g. ``22.0``).
        * ``bench_boost`` — average FDR for the top 10 outfield
          players (e.g. ``2.4``).
        * ``free_hit`` — number of DGW/BGW affected teams (float), or
          ``0.0`` for normal gameweek.  ``None`` when team_fixtures
          data is unavailable (safe fallback).

        ``None`` when the signal could not be computed.
    signal_label:
        Human-readable description of ``signal_value`` so callers
        can display it without chip-specific branching
        (e.g. ``"top captain score"``, ``"current gameweek"``,
        ``"average FDR (top 10)"``).
        ``None`` when ``signal_value`` is ``None``.
    """

    chip:             str
    recommendation:   str
    gw:               "int | None"
    signal_value:     "float | None"
    signal_label:     "str | None"
    chip_unavailable: bool = False  # Phase 8e1: True when chip not in squad_context.chips_remaining


# ---------------------------------------------------------------------------
# Fixture run metadata  (Phase 7h)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FixtureEntry:
    """A single fixture in a player's upcoming fixture run.

    Attributes
    ----------
    gameweek:
        FPL gameweek number (e.g. ``28``).
    opponent_short:
        3-char opponent team abbreviation (e.g. ``"ARS"``).
    is_home:
        ``True`` when the player's team plays at home.
    difficulty:
        FDR 1-5 from the player's team perspective (1=easy, 5=hard).
    """

    gameweek:       int
    opponent_short: str
    is_home:        bool
    difficulty:     int


@dataclass(frozen=True)
class FixtureRunMeta:
    """Structured fixture run output for programmatic access.

    Populated on ``FinalResponse`` when ``intent == player_fixture_run`` and
    ``outcome == ok``.  ``None`` for all other turns.

    All values are taken directly from the deterministic backend output
    (``get_player_fixture_run``); nothing is computed in this layer.

    Attributes
    ----------
    web_name:
        Player display name (e.g. ``"Haaland"``).
    team_short:
        Short team name (e.g. ``"MCI"``).
    position:
        FPL position string: ``"FWD"``, ``"MID"``, ``"DEF"``, or ``"GKP"``.
    horizon:
        Number of fixtures returned (may be < 5 if fewer remain in bootstrap).
    current_gameweek:
        GW number at the time of the query.  ``None`` if not determinable.
    fixtures:
        Tuple of :class:`FixtureEntry` objects ordered by gameweek ascending.
        Contains only fixtures at or after ``current_gameweek``.
    """

    web_name:         str
    team_short:       str
    position:         str
    horizon:          int
    current_gameweek: "int | None"
    fixtures:         tuple[FixtureEntry, ...]


# ---------------------------------------------------------------------------
# Differential picks metadata  (Phase 7g)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DifferentialEntry:
    """One entry in a differential picks result.

    Attributes
    ----------
    rank:
        1-based rank position by ``position_score`` descending
        (Phase 8a1).
    web_name:
        Player display name (e.g. ``"Palmer"``).
    team_short:
        Short team name (e.g. ``"CHE"``).
    position:
        FPL position string: ``"FWD"``, ``"MID"``, ``"DEF"``, or ``"GKP"``.
    captain_score:
        Canonical deterministic captain score.  Preserved for auditability.
    position_score:
        Position-aware heuristic evaluation score (Phase 8a1, Layer 2).
        Used for ranking.  Equal to ``captain_score`` for MID/FWD players
        (same weight profile as canonical formula).  Operationally
        comparable across positions; not a calibrated prediction.
    ownership:
        ``selected_by_percent`` as a float (e.g. ``1.0``).
    now_cost:
        Current price in tenths of £ (e.g. ``75`` = £7.5m).
    """

    rank:            int
    web_name:        str
    team_short:      str
    position:        str
    captain_score:   float   # Layer 1 canonical — preserved for auditability
    position_score:  float   # Layer 2 heuristic — ranking signal
    ownership:       float
    now_cost:        int
    is_home:         bool | None  # Phase 8b: True=home, False=away, None=unknown


@dataclass(frozen=True)
class DifferentialPicksMeta:
    """Structured differential picks output for programmatic access.

    Populated on ``FinalResponse`` when ``intent == differential_picks`` and
    ``outcome == ok``.  ``None`` for all other turns.

    All values are taken directly from the deterministic backend output
    (``get_differential_picks``); nothing is computed in this layer.

    Attributes
    ----------
    ownership_threshold:
        Ownership percentage ceiling used for filtering (default 15.0).
    top_n:
        Number of picks returned (may be < 5 if fewer eligible players exist).
    picks:
        Tuple of :class:`DifferentialEntry` objects ordered by
        ``position_score`` descending (Phase 8a1; rank 1 = highest).
    """

    ownership_threshold: float
    top_n:               int
    picks:               tuple[DifferentialEntry, ...]


# ---------------------------------------------------------------------------
# Per-player context bundle  (Phase 5i)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComparisonPlayerContext:
    """Bounded per-player context for a comparison turn.

    Exposed on ``ComparisonMeta.player_a`` and ``ComparisonMeta.player_b``
    when ``intent == compare_players`` and ``outcome == ok``.

    Fields are a strict subset of the deterministic comparison payload —
    no values are computed here; all come from ``compare_players()`` raw
    output.

    Attributes
    ----------
    web_name:
        Player display name (e.g. ``"Haaland"``).
    position:
        FPL position string: ``"FWD"``, ``"MID"``, ``"DEF"``, or ``"GKP"``.
    captain_score:
        Canonical deterministic captain score (form 40% / fixture 30% /
        xGI/90 20% / minutes 10%).  Layer 1, preserved for auditability.
    position_score:
        Position-aware heuristic evaluation score (Phase 8a1, Layer 2).
        Uses position-specific weight profiles over shared normalised
        components.  Equal to ``captain_score`` for MID/FWD players
        (same weight profile as canonical formula).  Operationally
        comparable across positions; not a calibrated prediction.
    is_home:
        ``True`` if the player's team plays at home this GW, ``False`` if
        away, ``None`` if venue is unknown (no team_fixtures data available).
        Phase 8b.
    effective_fdr:
        Home/away adjusted fixture difficulty rating (1.0–5.0, float).
        Home teams receive ``raw_fdr − 0.5``; away teams ``raw_fdr + 0.5``,
        clamped to [1.0, 5.0].  Used by Layer 2 (``position_score``).
        Layer 1 (``captain_score``) always uses the raw integer FDR.
        Phase 8b.
    role_bonus:
        Numeric role contribution to captain score from set-piece involvement
        (e.g. ``5.0`` for penalty taker, ``0.5`` for secondary free-kick
        taker, ``0.0`` for no set-piece role).
    set_piece_notes:
        Tuple of role-key strings that describe the player's set-piece
        involvement (e.g. ``("penalty_taker_1",)``).  Empty tuple when no
        set-piece role is recorded.
    """

    web_name:        str
    position:        str
    captain_score:   float                # Layer 1 canonical — preserved for auditability
    position_score:  float                # Layer 2 heuristic — ranking signal
    is_home:         bool | None          # Phase 8b: True=home, False=away, None=unknown
    effective_fdr:   float                # Phase 8b: home/away adjusted FDR (1.0–5.0)
    role_bonus:      float
    set_piece_notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Comparison metadata bundle  (Phase 5g / 5i)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComparisonMeta:
    """Structured comparison output for programmatic access.

    Populated on ``FinalResponse`` when ``intent == compare_players`` and
    ``outcome == ok``.  ``None`` for all other turns.

    Attributes
    ----------
    winner:
        Display name of the winning player, or ``None`` when the two players
        are tied on captain score.
    margin:
        Absolute difference between the two captain scores.  Zero on a tie.
    label:
        Categorical margin label — one of ``"narrow"``, ``"moderate"``, or
        ``"clear"`` (Phase 5d thresholds).
    reasons:
        Tuple of deterministic advantage phrases explaining why the winner
        scored higher (e.g. ``"stronger form (9.5 vs 8.0)"``).
        Empty tuple when no single factor clears the advantage threshold or
        when the comparison is tied.
    player_a:
        Bounded per-player context for the first comparison player (Phase 5i).
        ``None`` only on legacy construction without this field.
    player_b:
        Bounded per-player context for the second comparison player (Phase 5i).
        ``None`` only on legacy construction without this field.
    """

    winner:  str | None
    margin:  float
    label:   str
    reasons: tuple[str, ...]
    player_a: "ComparisonPlayerContext | None" = field(default=None)  # Phase 5i
    player_b: "ComparisonPlayerContext | None" = field(default=None)  # Phase 5i


# ---------------------------------------------------------------------------
# Resolver debug bundle (Phase 4g)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolverDebug:
    """Resolver-path metadata for debugging reference resolution.

    Only populated when ``ConversationSession.respond()`` is called with
    ``include_debug=True``.  Always ``None`` in the debug bundle for direct
    ``respond()`` calls (no session context available).

    Attributes
    ----------
    resolver_used:
        Whether a resolver (LLM or deterministic) actually changed the question.
        ``True`` when ``resolver_source`` is not ``"none"``.
    resolver_source:
        Which resolver path was taken:
        ``"comparison_followup"``     — Phase 5c deterministic comparison follow-up rewrite
        ``"comparison_followup_llm"`` — Phase 5f LLM comparison follow-up rewrite
        ``"llm"``                     — Phase 4f LLM reference resolution (confidence >= threshold)
        ``"fallback_regex"``          — Phase 4e deterministic pronoun substitution used
        ``"none"``                    — No resolver ran; original question used unchanged
    resolver_confidence:
        LLM-reported confidence (0.0-1.0) when ``resolver_source == "llm"``.
        ``None`` for non-LLM paths.
    rewritten_question:
        The canonical English question sent to the deterministic backend.
        Equals the original question when ``resolver_used=False``.
    fallback_reason:
        Why the LLM resolver was not used (if applicable):
        ``"llm_unavailable"`` — no client, LLM error, or parse failure
        ``"low_confidence"``  — LLM returned but confidence < threshold
        ``None``              — LLM was used (no fallback) or no resolution needed
    """
    resolver_used:       bool
    resolver_source:     str
    resolver_confidence: float | None
    rewritten_question:  str
    fallback_reason:     str | None


# ---------------------------------------------------------------------------
# Debug bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinalResponseDebug:
    """Internal fields for debugging and regression testing.

    Only populated when ``respond()`` is called with ``include_debug=True``.
    Not intended for production caller consumption.

    Attributes
    ----------
    llm_text:
        The raw text returned by the LLM (or the deterministic fallback when
        ``llm_called=False``).  May differ from ``FinalResponse.final_text``
        when the review rejected it.
    response_text:
        The deterministic backend text (``adapter_response.response_text``).
        Always the ultimate safety net — identical to ``final_text`` whenever
        ``FinalResponse.llm_used=False``.
    violations:
        Tuple of violation strings from the review layer.  Empty when the
        review passed.
    prompt_used:
        The user-turn prompt that was (or would have been) sent to the LLM.
        Useful for diagnosing unexpected LLM behaviour.
    model:
        The Anthropic model identifier, or ``"none"`` when the deterministic
        fallback was used.
    resolver:
        Optional resolver debug bundle (Phase 4g).  Populated only when
        ``ConversationSession.respond()`` is used with ``include_debug=True``.
        Always ``None`` for direct stateless ``respond()`` calls.
    classification_source:
        How intent was determined (Phase 4k).  ``None`` when deterministic
        ``route()`` succeeded directly.  ``"llm_classifier"`` when the LLM
        classifier produced the canonical question that unlocked routing.
        Always ``None`` when ``include_debug=False``.
    """
    llm_text:              str
    response_text:         str
    violations:            tuple[str, ...]
    prompt_used:           str
    model:                 str
    resolver:              ResolverDebug | None = field(default=None)
    classification_source: str | None           = field(default=None)  # Phase 4k


# ---------------------------------------------------------------------------
# Caller-facing response
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinalResponse:
    """The canonical caller-facing output of a single ``respond()`` call.

    Attributes
    ----------
    final_text:
        The text to surface to the user.  Guaranteed non-empty.  Policy:
        equals ``llm_text`` when ``llm_used=True``; equals ``response_text``
        (deterministic ground truth) when ``llm_used=False``.
    outcome:
        The ``OUTCOME_*`` constant from the grounded backend.  Use for
        routing decisions: e.g. distinguish ``OUTCOME_OK`` vs.
        ``OUTCOME_NOT_FOUND`` vs. ``OUTCOME_UNSUPPORTED_INTENT``.
    supported:
        Whether the intent was within the supported scope of the dispatcher.
        ``True`` for all outcomes except ``OUTCOME_UNSUPPORTED_INTENT``.
    intent:
        The ``INTENT_*`` constant from the grounded backend.  Useful for
        logging, analytics, and debugging routing decisions.
    review_passed:
        Whether the LLM text passed the deterministic parity review.  When
        ``False``, ``final_text`` contains the deterministic fallback.
    llm_used:
        Whether LLM-generated text appears in ``final_text``.
        ``True`` iff ``llm_called=True`` AND ``review_passed=True``.
        When ``False``, ``final_text`` is purely deterministic.
    debug:
        Optional internal debug bundle.  ``None`` by default; populated when
        ``respond()`` is called with ``include_debug=True``.
    comparison:
        Structured comparison output (Phase 5g).  Populated when
        ``intent == compare_players`` and ``outcome == ok``; ``None``
        otherwise.  Provides programmatic access to ``winner``,
        ``margin``, ``label``, and ``reasons`` without parsing
        ``final_text``.
    captain:
        Structured captain score output (Phase 5n).  Populated when
        ``intent == captain_score`` and ``outcome == ok``; ``None``
        otherwise.  Provides programmatic access to ``web_name``,
        ``team_short``, ``captain_score``, ``tier``, ``role_bonus``,
        and ``set_piece_notes`` without parsing ``final_text``.
    captain_ranking:
        Structured ranked candidates output (Phase 5p).  Populated when
        ``intent == rank_candidates`` and ``outcome == ok``; ``None``
        otherwise.  A tuple of :class:`RankedCaptainEntry` objects ordered
        by ``rank`` (1 = highest captain score).  Contains only successfully
        scored candidates — failed entries are omitted.
    sub_responses:
        Tuple of per-sub-intent ``FinalResponse`` objects (Phase 6c).
        Populated when ``intent == multi_intent``; ``None`` for all
        single-intent turns.  Each entry holds the full ``FinalResponse``
        for one independently-resolved sub-question, including its own
        ``final_text``, ``outcome``, ``intent``, and structured metadata.
        Debug bundles inside sub-responses are always ``None`` in Phase 6c.
    transfer:
        Structured transfer advice output (Phase 7a).  Populated when
        ``intent == transfer_advice`` and ``outcome == ok``; ``None``
        otherwise.  Provides programmatic access to ``player_out``,
        ``player_in``, ``recommendation``, ``score_delta``, ``price_delta``,
        and ``reasons`` without parsing ``final_text``.
    chip:
        Structured chip advice output (Phase 7b).  Populated when
        ``intent == chip_advice`` and ``outcome == ok``; ``None``
        otherwise.  Provides programmatic access to ``chip``,
        ``recommendation``, ``gw``, ``signal_value``, and
        ``signal_label`` without parsing ``final_text``.
    fixture_run:
        Structured fixture run output (Phase 7h).  Populated when
        ``intent == player_fixture_run`` and ``outcome == ok``; ``None``
        otherwise.  Provides programmatic access to ``web_name``,
        ``team_short``, ``position``, ``horizon``, ``current_gameweek``,
        and ``fixtures`` without parsing ``final_text``.
    differential:
        Structured differential picks output (Phase 7g).  Populated when
        ``intent == differential_picks`` and ``outcome == ok``; ``None``
        otherwise.  Provides programmatic access to ``ownership_threshold``,
        ``top_n``, and ``picks`` (tuple of :class:`DifferentialEntry`)
        without parsing ``final_text``.
    orch_outcome:
        Orchestration audit field (Orch-4c).  Captures the outcome of the
        LLM-orchestration attempt when ``FPL_ORCH_ENABLED`` is ON.
        Absence/presence semantics:

        * ``None``   — orchestration was not attempted (flag OFF, or
          multi-intent turn which bypasses the gate).
        * ``"ok"``   — orchestration succeeded; ``final_text`` and all
          structured metadata came from the orch path.
        * Any other ORCH_OUTCOME_* string — orchestration was attempted but
          returned a non-OK outcome; the deterministic path ran and is
          authoritative for ``final_text``, ``outcome``, and all metadata.

        This field is independent of ``outcome``: ``outcome`` always reflects
        the deterministic dispatcher result; ``orch_outcome`` reflects only
        the orchestrator gate result.
    """
    final_text:      str
    outcome:         str
    supported:       bool
    intent:          str
    review_passed:   bool
    llm_used:        bool
    debug:           FinalResponseDebug | None
    comparison:      ComparisonMeta | None                 = field(default=None)  # Phase 5g
    captain:         CaptainScoreMeta | None               = field(default=None)  # Phase 5n
    captain_ranking: tuple[RankedCaptainEntry, ...] | None = field(default=None)  # Phase 5p
    sub_responses:   "tuple[FinalResponse, ...] | None"    = field(default=None)  # Phase 6c
    transfer:        "TransferMeta | None"                 = field(default=None)  # Phase 7a
    chip:            "ChipAdviceMeta | None"               = field(default=None)  # Phase 7b
    fixture_run:     "FixtureRunMeta | None"               = field(default=None)  # Phase 7h
    differential:    "DifferentialPicksMeta | None"        = field(default=None)  # Phase 7g
    orch_outcome:    "str | None"                          = field(default=None)  # Orch-4c


# ---------------------------------------------------------------------------
# Final-response policy constant
# ---------------------------------------------------------------------------

#: Human-readable summary of the ``final_text`` selection policy.
FINAL_TEXT_POLICY: str = (
    "final_text = review.safe_text: "
    "llm_text when (llm_called AND review_passed), "
    "response_text otherwise"
)


# ---------------------------------------------------------------------------
# Multi-intent orchestrator  (Phase 6c)
# ---------------------------------------------------------------------------

def _respond_multi(
    sub_questions: list[str],
    bootstrap: dict[str, Any],
    *,
    client: Any,
    model: str,
    candidate_inputs: dict[str, Any] | None,
    candidates_list: list[dict[str, Any]] | None,
    api_key: str | None,
    classifier_client: Any,
    squad_context: dict[str, Any] | None = None,  # Phase 8e1: forwarded to each sub-call
) -> "FinalResponse":
    """Execute each sub-question independently and combine into a multi-intent response.

    Called only from ``respond()`` when ``detect_multi_intent`` succeeds.
    Each sub-question is passed through the full single-intent pipeline.
    Sub-responses always have ``debug=None`` (opt-in debug is not supported
    for multi-intent turns in Phase 6c).

    Parameters
    ----------
    sub_questions:
        Two independently-routable sub-question strings, as returned by
        ``detect_multi_intent()``.
    bootstrap:
        FPL bootstrap dict forwarded unchanged to each sub-turn.
    client, model, candidate_inputs, candidates_list, api_key, classifier_client:
        Forwarded unchanged to each ``respond()`` sub-call.
    squad_context:
        Optional per-turn squad state (Phase 8e1).  Forwarded unchanged to
        each ``respond()`` sub-call so hard constraints apply consistently
        across all sub-intents in a multi-intent turn.

    Returns
    -------
    FinalResponse
        ``intent=INTENT_MULTI_INTENT``, combined ``final_text``,
        ``outcome=OUTCOME_OK`` when all sub-intents succeed, else the first
        non-OK sub-outcome.  ``sub_responses`` holds the per-sub-intent
        ``FinalResponse`` tuple.
    """
    sub_list: list[FinalResponse] = []
    for q in sub_questions:
        sub = respond(
            q,
            bootstrap,
            client=client,
            model=model,
            candidate_inputs=candidate_inputs,
            candidates_list=candidates_list,
            api_key=api_key,
            include_debug=False,      # sub-responses do not surface debug bundles
            classifier_client=classifier_client,
            _multi_intent_depth=1,    # prevent nested multi-intent splitting
            squad_context=squad_context,  # Phase 8e1: forward per-turn constraint state
        )
        sub_list.append(sub)

    sub_responses = tuple(sub_list)

    # Combine final_text with blank-line separator
    final_text = "\n\n".join(r.final_text for r in sub_responses)

    # outcome: OK only if every sub-intent succeeded
    combined_outcome: str = OUTCOME_OK
    for r in sub_responses:
        if r.outcome != OUTCOME_OK:
            combined_outcome = r.outcome
            break

    # supported: True when all sub-intents are within scope
    combined_supported: bool = all(r.supported for r in sub_responses)

    return FinalResponse(
        final_text=final_text,
        outcome=combined_outcome,
        supported=combined_supported,
        intent=INTENT_MULTI_INTENT,
        review_passed=all(r.review_passed for r in sub_responses),
        llm_used=any(r.llm_used for r in sub_responses),
        debug=None,
        sub_responses=sub_responses,
    )


# ---------------------------------------------------------------------------
# Orch-4b: intent-specific metadata extraction helpers
#
# Each helper takes a raw tool_output dict and returns the structured metadata
# object, or None on any failure.  Safe degradation is the contract — callers
# must not raise even when required keys are missing or malformed.
#
# These helpers are shared by:
#   * respond()              — deterministic path (refactored from inline code)
#   * _orch_result_to_final_response() — orchestration success path
# ---------------------------------------------------------------------------

def _extract_comparison_player_ctx(pd: dict) -> "ComparisonPlayerContext":
    """Build a ComparisonPlayerContext from one player dict in compare_players output."""
    rs  = pd.get("role_signals", {})
    si  = pd.get("score_inputs", {})
    raw_canonical = float(pd.get("captain_score", 0.0))
    raw_fdr       = int(si.get("fixture_difficulty", 3))
    return ComparisonPlayerContext(
        web_name        = pd.get("web_name", ""),
        position        = pd.get("position", ""),
        captain_score   = raw_canonical,
        position_score  = float(pd.get("position_score", raw_canonical)),
        is_home         = si.get("is_home"),
        effective_fdr   = float(si.get("effective_fdr", raw_fdr)),
        role_bonus      = float(rs.get("role_bonus", 0.0)),
        set_piece_notes = tuple(rs.get("set_piece_notes") or []),
    )


def _extract_comparison_meta(ro: "dict[str, Any]") -> "ComparisonMeta | None":
    """Extract ComparisonMeta from a compare_players tool_output dict."""
    try:
        return ComparisonMeta(
            winner   = ro.get("winner"),
            margin   = float(ro.get("margin", 0.0)),
            label    = ro.get("margin_label", "narrow"),
            reasons  = tuple(ro.get("comparison_reasons") or []),
            player_a = _extract_comparison_player_ctx(ro.get("player_a", {})),
            player_b = _extract_comparison_player_ctx(ro.get("player_b", {})),
        )
    except Exception:  # noqa: BLE001
        return None


def _extract_captain_meta(ro: "dict[str, Any]") -> "CaptainScoreMeta | None":
    """Extract CaptainScoreMeta from a get_captain_score tool_output dict."""
    try:
        rs = ro.get("role_signals") or {}
        return CaptainScoreMeta(
            web_name        = ro.get("web_name", ""),
            team_short      = ro.get("team_short", ""),
            captain_score   = float(ro.get("captain_score", 0.0)),
            tier            = ro.get("tier", ""),
            role_bonus      = float(rs.get("role_bonus", 0.0)),
            set_piece_notes = tuple(rs.get("set_piece_notes") or []),
        )
    except Exception:  # noqa: BLE001
        return None


def _extract_captain_ranking_meta(
    ro: "dict[str, Any]",
) -> "tuple[RankedCaptainEntry, ...] | None":
    """Extract a ranked captain entries tuple from a rank_captain_candidates output."""
    try:
        entries = []
        for c in ro.get("ranked_candidates", []):
            if c.get("status") != "ok":
                continue
            rs = c.get("role_signals") or {}
            entries.append(RankedCaptainEntry(
                rank            = int(c.get("rank", 0)),
                web_name        = c.get("web_name", ""),
                team_short      = c.get("team_short", ""),
                captain_score   = float(c.get("captain_score", 0.0)),
                tier            = c.get("tier", ""),
                role_bonus      = float(rs.get("role_bonus", 0.0)),
                set_piece_notes = tuple(rs.get("set_piece_notes") or []),
            ))
        return tuple(entries)
    except Exception:  # noqa: BLE001
        return None


def _extract_transfer_meta(ro: "dict[str, Any]") -> "TransferMeta | None":
    """Extract TransferMeta from a get_transfer_advice tool_output dict."""
    try:
        return TransferMeta(
            player_out     = ro["player_out"]["web_name"],
            player_in      = ro["player_in"]["web_name"],
            recommendation = ro["recommendation"],
            score_delta    = float(ro.get("score_delta", 0.0)),
            price_delta    = int(ro.get("price_delta", 0)),
            reasons        = tuple(ro.get("transfer_reasons") or []),
        )
    except Exception:  # noqa: BLE001
        return None


def _extract_chip_meta(ro: "dict[str, Any]") -> "ChipAdviceMeta | None":
    """Extract ChipAdviceMeta from a get_chip_advice tool_output dict."""
    try:
        chip_name = ro.get("chip", "")
        signals   = ro.get("signals") or {}
        gw_raw    = ro.get("current_gameweek")

        if chip_name == "triple_captain":
            sv = signals.get("top_captain_score")
            sl: "str | None" = "top captain score" if sv is not None else None
        elif chip_name == "wildcard":
            sv = signals.get("current_gameweek")
            sl = "current gameweek" if sv is not None else None
        elif chip_name == "bench_boost":
            sv = signals.get("average_fdr_top10")
            sl = "average FDR (top 10)" if sv is not None else None
        elif chip_name == "free_hit":
            # Phase 8c/8c1: DGW/BGW/mixed detection.
            # Prefer granular dgw_count/bgw_count (Phase 8c1) with fallback
            # to affected_team_count for backward compat.
            gw_type   = signals.get("gameweek_type")
            dgw_count = signals.get("dgw_count")
            bgw_count = signals.get("bgw_count")
            ac        = signals.get("affected_team_count")   # backward compat
            if gw_type == "double":
                raw = dgw_count if dgw_count is not None else ac
                sv  = float(raw) if raw is not None else None
                sl  = "double gameweek teams" if sv is not None else None
            elif gw_type == "blank":
                raw = bgw_count if bgw_count is not None else ac
                sv  = float(raw) if raw is not None else None
                sl  = "blank gameweek teams" if sv is not None else None
            elif gw_type == "mixed":
                sv = float(dgw_count) if dgw_count is not None else None
                sl = "mixed gameweek (double teams)" if sv is not None else None
            elif gw_type == "normal":
                sv = 0.0
                sl = "normal gameweek"
            else:
                sv = None
                sl = None
        else:  # unknown chip
            sv = None
            sl = None

        return ChipAdviceMeta(
            chip           = chip_name,
            recommendation = ro.get("recommendation", ""),
            gw             = int(gw_raw) if gw_raw is not None else None,
            signal_value   = float(sv) if sv is not None else None,
            signal_label   = sl,
        )
    except Exception:  # noqa: BLE001
        return None


def _extract_fixture_run_meta(ro: "dict[str, Any]") -> "FixtureRunMeta | None":
    """Extract FixtureRunMeta from a get_player_fixture_run tool_output dict."""
    try:
        return FixtureRunMeta(
            web_name         = ro.get("web_name", ""),
            team_short       = ro.get("team_short", ""),
            position         = ro.get("position", ""),
            horizon          = int(ro.get("horizon", 0)),
            current_gameweek = ro.get("current_gameweek"),
            fixtures         = tuple(
                FixtureEntry(
                    gameweek       = int(fx["gameweek"]),
                    opponent_short = fx["opponent_short"],
                    is_home        = bool(fx["is_home"]),
                    difficulty     = int(fx["difficulty"]),
                )
                for fx in ro.get("fixtures", [])
            ),
        )
    except Exception:  # noqa: BLE001
        return None


def _extract_differential_meta(ro: "dict[str, Any]") -> "DifferentialPicksMeta | None":
    """Extract DifferentialPicksMeta from a get_differential_picks tool_output dict."""
    try:
        return DifferentialPicksMeta(
            ownership_threshold = float(ro.get("ownership_threshold", 15.0)),
            top_n               = int(ro.get("top_n", 0)),
            picks               = tuple(
                DifferentialEntry(
                    rank           = int(p["rank"]),
                    web_name       = p["web_name"],
                    team_short     = p["team_short"],
                    position       = p["position"],
                    captain_score  = float(p["captain_score"]),
                    position_score = float(p.get("position_score", p["captain_score"])),
                    ownership      = float(p["ownership"]),
                    now_cost       = int(p["now_cost"]),
                    is_home        = p.get("is_home"),
                )
                for p in ro.get("picks", [])
            ),
        )
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Orch-4d: shared squad_context override helper
#
# Applies budget_constraint, hit_warning, and chip_unavailable post-processing
# to (transfer, chip, final_text) for BOTH the deterministic and orch-success
# paths.  Centralising the logic here eliminates semantic drift between paths.
#
# Override semantics (unchanged from Phase 8e1/8e2 deterministic policy):
#   budget_constraint  — hard block; replaces final_text when price_delta > itb
#   hit_warning        — advisory; sets flag only, final_text unchanged
#   chip_unavailable   — hard block; replaces final_text when chip not available
# ---------------------------------------------------------------------------

def _apply_squad_overrides(
    *,
    transfer: "TransferMeta | None",
    chip: "ChipAdviceMeta | None",
    final_text: str,
    squad_context: "dict[str, Any] | None",
) -> "tuple[TransferMeta | None, ChipAdviceMeta | None, str]":
    """Apply squad_context hard-block and advisory overrides post-metadata-build.

    Shared by ``respond()`` (deterministic path) and
    ``_orch_result_to_final_response()`` (orch-success path) so that override
    semantics are identical regardless of which path ran.

    Parameters
    ----------
    transfer:
        Populated ``TransferMeta`` from the current turn, or ``None``.
    chip:
        Populated ``ChipAdviceMeta`` from the current turn, or ``None``.
    final_text:
        Current ``final_text`` string before overrides.
    squad_context:
        Optional per-turn squad state dict.  ``None`` disables all overrides.

    Returns
    -------
    (transfer, chip, final_text)
        Tuple with overrides applied.  Unchanged if ``squad_context`` is
        ``None`` or no override condition fires.
    """
    _squad           = squad_context or {}
    _itb             = _squad.get("itb")              # tenths of £, optional
    _chips_remaining = _squad.get("chips_remaining")  # list[str] or None
    _free_transfers  = _squad.get("free_transfers")   # int or None

    # ------------------------------------------------------------------ budget
    if transfer is not None and _itb is not None:
        if transfer.price_delta > _itb:
            price_m  = transfer.price_delta / 10.0
            itb_m    = float(_itb) / 10.0
            final_text = (
                f"Budget constraint: bringing in {transfer.player_in} costs "
                f"+\u00a3{price_m:.1f}m but you have \u00a3{itb_m:.1f}m in the bank."
            )
            transfer = TransferMeta(
                player_out=transfer.player_out,
                player_in=transfer.player_in,
                recommendation=transfer.recommendation,
                score_delta=transfer.score_delta,
                price_delta=transfer.price_delta,
                reasons=transfer.reasons,
                budget_constraint=True,
            )

    # ---------------------------------------------------------------- hit_warn
    # Advisory only — sets flag, does NOT override final_text.
    # Fires exclusively when free_transfers==1 AND recommendation==marginal_transfer_in.
    if (
        transfer is not None
        and _free_transfers == 1
        and transfer.recommendation == "marginal_transfer_in"
    ):
        transfer = TransferMeta(
            player_out=transfer.player_out,
            player_in=transfer.player_in,
            recommendation=transfer.recommendation,
            score_delta=transfer.score_delta,
            price_delta=transfer.price_delta,
            reasons=transfer.reasons,
            budget_constraint=transfer.budget_constraint,
            hit_warning=True,
        )

    # --------------------------------------------------------- chip_unavailable
    if chip is not None and _chips_remaining is not None:
        if chip.chip not in _chips_remaining:
            final_text = (
                f"Chip unavailable: {chip.chip} is not in your chips remaining."
            )
            chip = ChipAdviceMeta(
                chip=chip.chip,
                recommendation=chip.recommendation,
                gw=chip.gw,
                signal_value=chip.signal_value,
                signal_label=chip.signal_label,
                chip_unavailable=True,
            )

    return transfer, chip, final_text


# ---------------------------------------------------------------------------
# Orch-4a/4b/4d: orchestration result -> FinalResponse mapper
# ---------------------------------------------------------------------------

def _orch_result_to_final_response(
    result: OrchestratorResult,
    *,
    include_debug: bool = False,
    squad_context: "dict[str, Any] | None" = None,
) -> "FinalResponse":
    """Map a successful ``OrchestratorResult`` to a ``FinalResponse``.

    Called only when ``result.outcome == ORCH_OUTCOME_OK``.  Structured
    metadata fields are populated from ``result.tool_output`` using the same
    extraction helpers as the deterministic path.  Each helper degrades
    safely to ``None`` when required fields are absent — no exceptions escape.

    Squad-context overrides (budget_constraint, hit_warning, chip_unavailable)
    are applied via :func:`_apply_squad_overrides` so that orch-success
    responses honour the same hard-block and advisory rules as the
    deterministic path (Orch-4d parity).

    Parameters
    ----------
    result:
        A successful ``OrchestratorResult`` (outcome == ORCH_OUTCOME_OK).
    include_debug:
        When ``True``, populate a minimal ``FinalResponseDebug`` from
        orchestration fields (no review/violations data available).
    squad_context:
        Optional per-turn squad state dict forwarded from ``respond()``.
        ``None`` disables all overrides (default).

    Returns
    -------
    FinalResponse
        Contract-compliant response.  ``final_text`` is the grounded
        orchestrated answer with any applicable squad overrides applied.
        ``llm_used`` mirrors ``result.llm_used``.
        Structured metadata fields are populated for applicable intents.
    """
    intent     = _TOOL_TO_INTENT.get(result.tool_chosen or "", INTENT_UNSUPPORTED)
    ro         = result.tool_output
    final_text = result.answer_text

    # Populate intent-specific structured metadata from grounded tool_output.
    # Dispatched by intent so only the relevant helper runs.
    comparison:      "ComparisonMeta | None"                 = None
    captain:         "CaptainScoreMeta | None"               = None
    captain_ranking: "tuple[RankedCaptainEntry, ...] | None" = None
    transfer:        "TransferMeta | None"                   = None
    chip:            "ChipAdviceMeta | None"                 = None
    fixture_run:     "FixtureRunMeta | None"                 = None
    differential:    "DifferentialPicksMeta | None"          = None

    if intent == INTENT_CAPTAIN_SCORE:
        captain = _extract_captain_meta(ro)
    elif intent == INTENT_RANK_CANDIDATES:
        captain_ranking = _extract_captain_ranking_meta(ro)
    elif intent == INTENT_COMPARE_PLAYERS:
        comparison = _extract_comparison_meta(ro)
    elif intent == INTENT_TRANSFER_ADVICE:
        transfer = _extract_transfer_meta(ro)
    elif intent == INTENT_CHIP_ADVICE:
        chip = _extract_chip_meta(ro)
    elif intent == INTENT_PLAYER_FIXTURE_RUN:
        fixture_run = _extract_fixture_run_meta(ro)
    elif intent == INTENT_DIFFERENTIAL_PICKS:
        differential = _extract_differential_meta(ro)

    # Orch-4d: apply squad_context overrides (budget, hit_warning, chip_unavail)
    # using the same shared helper as the deterministic path for parity.
    transfer, chip, final_text = _apply_squad_overrides(
        transfer=transfer,
        chip=chip,
        final_text=final_text,
        squad_context=squad_context,
    )

    debug: "FinalResponseDebug | None" = None
    if include_debug:
        debug = FinalResponseDebug(
            llm_text=final_text,
            response_text=final_text,
            violations=(),
            prompt_used="",          # not captured in orchestrator path
            model=result.model,
            resolver=None,
            classification_source="orchestrator",  # marks orch path in debug
        )

    return FinalResponse(
        final_text=final_text,
        outcome=OUTCOME_OK,
        supported=True,
        intent=intent,
        review_passed=True,          # orchestrator output is always grounded
        llm_used=result.llm_used,
        debug=debug,
        comparison=comparison,
        captain=captain,
        captain_ranking=captain_ranking,
        transfer=transfer,
        chip=chip,
        fixture_run=fixture_run,
        differential=differential,
        orch_outcome=ORCH_OUTCOME_OK,  # Orch-4c: audit — orch path was used
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def respond(
    user_message: str,
    bootstrap: dict[str, Any],
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    include_debug: bool = False,
    _resolver_debug: ResolverDebug | None = None,
    classifier_client: Any = None,
    _multi_intent_depth: int = 0,  # Phase 6c: prevents recursive multi-intent splitting
    squad_context: dict[str, Any] | None = None,  # Phase 8e1: optional per-turn squad state
    intent_hint: str | None = None,  # V2: optional slash-command routing bias
) -> FinalResponse:
    """Run the full pipeline and return a single caller-facing ``FinalResponse``.

    This is the recommended entrypoint for external callers.  It orchestrates
    the complete stack — ``adapt()`` → ``ask_llm()`` → ``review_llm_response()``
    — and applies the unified final-response policy to produce a single clean
    object without exposing internal ambiguity.

    Parameters
    ----------
    user_message:
        Raw user question.
    bootstrap:
        FPL bootstrap dict (or assembled context from
        ``assemble_captain_context()``).
    client:
        Optional pre-built ``anthropic.Anthropic`` instance.  When ``None``,
        ``ask_llm()`` uses ``api_key`` or ``ANTHROPIC_API_KEY`` env var.
    model:
        Anthropic model identifier.  Defaults to ``DEFAULT_MODEL``.
    candidate_inputs:
        Optional scoring overrides forwarded to ``adapt()``.
    candidates_list:
        Optional list of candidate dicts forwarded to ``adapt()``.
    api_key:
        Explicit API key (only used when ``client`` is ``None``).
    include_debug:
        When ``True``, populate ``FinalResponse.debug`` with internal fields
        (``llm_text``, ``response_text``, ``violations``, ``prompt_used``,
        ``model``).  Defaults to ``False``.
    _resolver_debug:
        Internal — populated by ``ConversationSession.respond()`` with
        resolver metadata.  Not part of the public caller contract.
        External callers should leave this as ``None``.

    Returns
    -------
    FinalResponse
        Always returns — never raises.

    Notes
    -----
    ``FinalResponse.final_text`` policy (authoritative):

    * LLM called + review passed  →  ``final_text = llm_text``
    * LLM not called (fallback)   →  ``final_text = response_text``
    * LLM called + review failed  →  ``final_text = response_text``

    ``llm_used`` captures whether LLM text is actually in ``final_text``:
    ``llm_used = lr.llm_called and review.passed``.
    """
    # Orch-4c: tracks whether orchestration was attempted and what outcome it
    # returned.  None = orch OFF (not attempted); non-None = attempted but
    # non-OK (fallback to deterministic).  Set to ORCH_OUTCOME_OK on early
    # return from _orch_result_to_final_response, so this variable is only
    # read when the deterministic path runs.
    _orch_outcome: str | None = None

    # -----------------------------------------------------------------------
    # Phase 6c: multi-intent detection (only at depth 0 to prevent recursion)
    # -----------------------------------------------------------------------
    if _multi_intent_depth == 0:
        sub_questions = detect_multi_intent(user_message)
        if sub_questions is not None:
            return _respond_multi(
                sub_questions,
                bootstrap,
                client=client,
                model=model,
                candidate_inputs=candidate_inputs,
                candidates_list=candidates_list,
                api_key=api_key,
                classifier_client=classifier_client,
                squad_context=squad_context,  # Phase 8e1: forward per-turn constraint state
            )

        # -------------------------------------------------------------------
        # Orch-4a/4c: orchestration gate (single-intent, depth-0 only)
        #
        # When FPL_ORCH_ENABLED is truthy, attempt ask_orchestrated().
        # On ORCH_OUTCOME_OK, map result to FinalResponse and return early.
        # On any non-OK outcome (NO_CLIENT, LLM_ERROR, NO_TOOL, UNKNOWN_TOOL,
        # TOOL_ERROR, TOOL_RESULT_ERROR), fall through to the deterministic
        # path — grounded behavior is always preserved.
        #
        # Orch-4c: the non-OK outcome is captured in _orch_outcome and
        # forwarded to FinalResponse.orch_outcome for operator audit.
        # Non-OK outcome policy:
        #   no_client         → no LLM client; deterministic runs without LLM
        #   llm_error         → API exception; deterministic runs without LLM
        #   no_tool           → LLM gave text not tool; deterministic runs normally
        #   unknown_tool      → unregistered tool; deterministic runs normally
        #   tool_error        → run_tool() raised; deterministic runs normally
        #   tool_result_error → tool status != ok; deterministic runs normally
        # In all cases: final_text = deterministic; outcome = deterministic;
        # orch_outcome = the non-OK string for audit.
        # -------------------------------------------------------------------
        if is_orch_enabled():
            _orch = ask_orchestrated(
                user_message,
                bootstrap,
                client=client,
                model=model,
                api_key=api_key,
                provider=get_orch_provider(),
            )
            if _orch.outcome == ORCH_OUTCOME_OK:
                return _orch_result_to_final_response(
                    _orch,
                    include_debug=include_debug,
                    squad_context=squad_context,   # Orch-4d: override parity
                )
            _orch_outcome = _orch.outcome  # Orch-4c: capture non-OK for audit

    lr, review = ask_llm_safe(
        user_message,
        bootstrap,
        client=client,
        model=model,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
        api_key=api_key,
        classifier_client=classifier_client,
        intent_hint=intent_hint,
    )

    ar = lr.adapter_response
    dr = ar.dispatch_result

    # -----------------------------------------------------------------------
    # Final-response policy — single explicit rule
    # -----------------------------------------------------------------------
    final_text    = review.safe_text                   # encodes the full fallback logic
    review_passed = review.passed
    llm_used      = lr.llm_called and review.passed    # LLM text generated AND accepted

    # -----------------------------------------------------------------------
    # Debug bundle (opt-in only)
    # -----------------------------------------------------------------------
    debug: FinalResponseDebug | None = None
    if include_debug:
        debug = FinalResponseDebug(
            llm_text=lr.llm_text,
            response_text=ar.response_text,
            violations=review.violations,
            prompt_used=lr.prompt_used,
            model=lr.model,
            resolver=_resolver_debug,
            classification_source=dr.classification_source,
        )

    # Populate structured metadata using shared Orch-4b extraction helpers.
    # Each call is intent-gated and degrades safely to None on any failure.
    comparison: ComparisonMeta | None = None
    if dr.intent == INTENT_COMPARE_PLAYERS and dr.outcome == OUTCOME_OK:
        comparison = _extract_comparison_meta(dr.raw_output)

    captain: CaptainScoreMeta | None = None
    if dr.intent == INTENT_CAPTAIN_SCORE and dr.outcome == OUTCOME_OK:
        captain = _extract_captain_meta(dr.raw_output)

    captain_ranking: "tuple[RankedCaptainEntry, ...] | None" = None
    if dr.intent == INTENT_RANK_CANDIDATES and dr.outcome == OUTCOME_OK:
        captain_ranking = _extract_captain_ranking_meta(dr.raw_output)

    transfer: TransferMeta | None = None
    if dr.intent == INTENT_TRANSFER_ADVICE and dr.outcome == OUTCOME_OK:
        transfer = _extract_transfer_meta(dr.raw_output)

    chip: ChipAdviceMeta | None = None
    if dr.intent == INTENT_CHIP_ADVICE and dr.outcome == OUTCOME_OK:
        chip = _extract_chip_meta(dr.raw_output)

    fixture_run: FixtureRunMeta | None = None
    if dr.intent == INTENT_PLAYER_FIXTURE_RUN and dr.outcome == OUTCOME_OK:
        fixture_run = _extract_fixture_run_meta(dr.raw_output)

    differential: DifferentialPicksMeta | None = None
    if dr.intent == INTENT_DIFFERENTIAL_PICKS and dr.outcome == OUTCOME_OK:
        differential = _extract_differential_meta(dr.raw_output)

    # Orch-4d: squad_context overrides via shared helper (Phase 8e1/8e2 semantics).
    # budget_constraint / chip_unavailable replace final_text (hard blocks).
    # hit_warning is advisory — sets flag only, final_text unchanged.
    transfer, chip, final_text = _apply_squad_overrides(
        transfer=transfer,
        chip=chip,
        final_text=final_text,
        squad_context=squad_context,
    )

    return FinalResponse(
        final_text=final_text,
        outcome=dr.outcome,
        supported=ar.supported,
        intent=dr.intent,
        review_passed=review_passed,
        llm_used=llm_used,
        debug=debug,
        comparison=comparison,
        captain=captain,
        captain_ranking=captain_ranking,
        transfer=transfer,
        chip=chip,
        fixture_run=fixture_run,
        differential=differential,
        orch_outcome=_orch_outcome,  # Orch-4c: None=off, non-OK string=fell back
    )