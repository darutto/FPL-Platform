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

from .dispatcher import OUTCOME_OK, INTENT_COMPARE_PLAYERS, INTENT_CAPTAIN_SCORE, INTENT_RANK_CANDIDATES  # noqa: F401 — re-exported
from .llm_layer import DEFAULT_MODEL
from .llm_review import ask_llm_safe


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
        Deterministic captain score used for this comparison.
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
    captain_score:   float
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
    """
    llm_text:      str
    response_text: str
    violations:    tuple[str, ...]
    prompt_used:   str
    model:         str
    resolver:      ResolverDebug | None = field(default=None)


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
    lr, review = ask_llm_safe(
        user_message,
        bootstrap,
        client=client,
        model=model,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
        api_key=api_key,
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
        )

    # Phase 5g/5i: populate structured comparison metadata for OK comparison turns
    comparison: ComparisonMeta | None = None
    if dr.intent == INTENT_COMPARE_PLAYERS and dr.outcome == OUTCOME_OK:
        ro = dr.raw_output

        def _make_player_ctx(pd: dict) -> ComparisonPlayerContext:
            rs = pd.get("role_signals", {})
            return ComparisonPlayerContext(
                web_name        = pd.get("web_name", ""),
                position        = pd.get("position", ""),
                captain_score   = float(pd.get("captain_score", 0.0)),
                role_bonus      = float(rs.get("role_bonus", 0.0)),
                set_piece_notes = tuple(rs.get("set_piece_notes") or []),
            )

        comparison = ComparisonMeta(
            winner   = ro.get("winner"),
            margin   = float(ro.get("margin", 0.0)),
            label    = ro.get("margin_label", "narrow"),
            reasons  = tuple(ro.get("comparison_reasons") or []),
            player_a = _make_player_ctx(ro.get("player_a", {})),  # Phase 5i
            player_b = _make_player_ctx(ro.get("player_b", {})),  # Phase 5i
        )

    # Phase 5n: populate structured captain score metadata for OK captain score turns
    captain: CaptainScoreMeta | None = None
    if dr.intent == INTENT_CAPTAIN_SCORE and dr.outcome == OUTCOME_OK:
        ro = dr.raw_output
        rs = ro.get("role_signals") or {}
        captain = CaptainScoreMeta(
            web_name        = ro.get("web_name", ""),
            team_short      = ro.get("team_short", ""),
            captain_score   = float(ro.get("captain_score", 0.0)),
            tier            = ro.get("tier", ""),
            role_bonus      = float(rs.get("role_bonus", 0.0)),
            set_piece_notes = tuple(rs.get("set_piece_notes") or []),
        )

    # Phase 5p: populate structured ranked candidates for OK rank_candidates turns
    captain_ranking: tuple[RankedCaptainEntry, ...] | None = None
    if dr.intent == INTENT_RANK_CANDIDATES and dr.outcome == OUTCOME_OK:
        ro = dr.raw_output
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
        captain_ranking = tuple(entries)

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
    )