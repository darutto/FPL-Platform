"""
fpl_grounded_assistant.harness
================================
End-to-end grounded-assistant harness.

Ties together the deterministic router, the in-process tool runner,
and the safe-text renderer into a single ``ask()`` call.

Returned structure
------------------
::

    {
        "selected_tool":  str | None,      # tool name chosen by router
        "tool_input":     dict,            # args passed to run_tool
        "raw_output":     dict,            # raw dict from run_tool
        "answer_text":    str,             # rendered human-readable answer
        # present only when assembled context was passed:
        "context_meta":   dict | None,     # from assemble_captain_context()
    }

No LLM integration, no HTTP server, no live API calls — all data flows
through the bootstrap dict that the caller supplies.

Phase 2a changes
----------------
* ``ask()`` now accepts an optional ``candidate_inputs`` dict.  When the
  router identifies a ``get_captain_score`` intent, the harness merges
  ``candidate_inputs`` (form, fixture_difficulty, xgi_per_90, minutes_risk)
  into ``tool_args`` before calling ``run_tool``.  If ``candidate_inputs``
  is ``None``, the runner returns a ``missing_argument`` error which the
  renderer translates into a helpful message.

Phase 2b changes
----------------
* ``ask()`` now accepts an optional ``candidates_list`` parameter.  When the
  router identifies a ``rank_captain_candidates`` intent, the harness sets
  ``tool_args["candidates"] = candidates_list`` before calling ``run_tool``.
  If ``candidates_list`` is ``None`` or empty, the runner returns a
  ``missing_argument`` error which the renderer renders gracefully.

Phase 2c changes
----------------
* Auto-derivation of captain scoring inputs is now handled by the tool-contract
  layer (``tool_get_captain_score`` and ``tool_rank_captain_candidates``).  The
  harness no longer needs to supply ``form``, ``minutes_risk``, or ``xgi_per_90``
  explicitly — those are derived from the bootstrap element.
* ``candidate_inputs`` and ``candidates_list`` remain optional parameters so
  that callers can still supply explicit overrides.

Phase 2d changes
----------------
* ``fixture_difficulty`` is now also auto-derived by the tool-contract layer
  when the caller has pre-injected ``bootstrap["fixture_difficulty_map"]``
  (from ``fpl_api_client.get_fixture_difficulty_map``).  FDR = opponent team
  strength (1–5).
* When the map is present, neither ``candidate_inputs`` nor any
  ``fixture_difficulty`` key in ``candidates_list`` entries is required.
* ``fixture_difficulty`` can still be overridden explicitly via
  ``candidate_inputs`` (for ``get_captain_score``) or per-candidate dict
  (for ``rank_captain_candidates``).
* Teams with a blank gameweek (absent from the map) still require
  ``fixture_difficulty`` to be provided explicitly.
* Typical caller setup::

      from fpl_api_client import get_bootstrap, get_fixtures, get_fixture_difficulty_map
      bootstrap = get_bootstrap()
      fixtures  = get_fixtures(gameweek=get_current_gameweek(bootstrap))
      bootstrap["fixture_difficulty_map"] = get_fixture_difficulty_map(fixtures, bootstrap)
      result = ask("Who should I captain?", bootstrap, candidates_list=[{"query": "Haaland"}])

Phase 2e changes
----------------
* Context assembly burden is now owned by ``fpl_pipeline.assemble_captain_context()``.
  The caller no longer needs to call ``get_bootstrap``, ``get_current_gameweek``,
  ``get_fixtures``, and ``get_fixture_difficulty_map`` separately.  Typical setup::

      from fpl_pipeline import assemble_captain_context
      ctx    = assemble_captain_context()
      result = ask("Who should I captain?", ctx["bootstrap"], candidates_list=[...])

* ``ctx["bootstrap"]`` already has ``fixture_difficulty_map`` injected.
* ``ctx["meta"]["blank_gw_teams"]`` lists any teams without a fixture this GW.
* The harness itself is unchanged in Phase 2e — no new parameters.

Phase 2f changes
----------------
* ``ask()`` now accepts the **full assembled context dict** directly —
  not just the extracted ``ctx["bootstrap"]``.  The caller no longer needs
  to unpack the context::

      # Phase 2f (preferred)
      ctx    = assemble_captain_context()
      result = ask("Who should I captain?", ctx)          # pass ctx directly

      # Phase 2e (still works — backwards compatible)
      result = ask("Who should I captain?", ctx["bootstrap"])

      # Phase 2d (still works — backwards compatible)
      result = ask("Who should I captain?", bootstrap)

* Detection is automatic: if the first data argument has a nested
  ``"bootstrap"`` key whose value is a dict, it is treated as an assembled
  context; otherwise it is treated as a raw bootstrap.

* When assembled context is detected, the return dict gains a
  ``"context_meta"`` key containing ``ctx["meta"]`` (gameweek, fixture_count,
  blank_gw_teams, assembled_at, …).  This key is **absent** when a raw
  bootstrap is passed, preserving full backwards compatibility.

* No assembly logic lives inside the harness.  Context assembly remains
  entirely in ``fpl_pipeline.assemble_captain_context()``.

Known gaps (remaining before true LLM integration)
---------------------------------------------------
1. **Router precision**: purely keyword-based; "Salah is a great player" would
   not route correctly.  A real dispatcher will use intent classification.

2. **Stateless routing**: no conversation history; "What about his price?"
   cannot be resolved without pronoun context.

3. **No combined intents**: "Who is Salah and what gameweek is it?" routes only
   to the first matched intent and ignores the rest.

4. **Context assembly**: the caller must still assemble the bootstrap context
   (fetch → inject → ask).  Use ``fpl_pipeline.assemble_captain_context()``
   (Phase 2e) to do this in a single call — it returns a ``ctx`` dict whose
   ``ctx["bootstrap"]`` (or ``ctx`` itself, Phase 2f) is ready for ``ask()``.
"""
from __future__ import annotations

import os
from typing import Any

from fpl_grounded_assistant.catalogue import t
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY, Locale, DEFAULT_LOCALE
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.router import route
from .tool_dispatch import run_tool

# ---------------------------------------------------------------------------
# Phase M5: frozen routing_trace schema constants
#
# These constants pin the stable schema for routing_trace (graduated M5,
# 2026-05-17).  Test suites use them to assert completeness without hard-
# coding key lists in multiple places.
#
# ROUTING_TRACE_REQUIRED_KEYS — keys that MUST appear in every routing_trace
#   dict returned by ask_v2(), regardless of branch.  A frozen-schema test
#   should assert set(trace.keys()) >= ROUTING_TRACE_REQUIRED_KEYS.
#
# ROUTING_TRACE_OPTIONAL_KEYS — keys that MAY appear on specific branches.
#   Their presence is branch-conditional; absence on unrelated branches is
#   correct and expected.
# ---------------------------------------------------------------------------

def _tool_table_conclusions(tool: Any, raw_output: Any, bootstrap: Any) -> "list[dict[str, Any]] | None":
    """``table_conclusions`` for a ``rank_players_by_metric`` turn; None for any other tool or when none fires."""
    if tool != "rank_players_by_metric":
        return None
    from .table_conclusions import tool_ranking_conclusions  # noqa: PLC0415
    return tool_ranking_conclusions(raw_output, bootstrap) or None


def _resource_table_conclusions(decision: Any, bootstrap: Any) -> "list[dict[str, Any]] | None":
    """``table_conclusions`` for an ``@resource`` ranking; None for ``injuries`` etc. or when none fires."""
    from .table_conclusions import resource_ranking_conclusions  # noqa: PLC0415
    return resource_ranking_conclusions(
        decision.get("resource"), decision.get("resource_rows"), bootstrap,
    ) or None


ROUTING_TRACE_REQUIRED_KEYS: frozenset[str] = frozenset({
    "branch",
    "decision_kind",
    "decision_outcome",
    "router_hit",
    "classifier_called",
    "classifier_confidence",
    "classifier_intent",
    "orchestrator_called",
    "orchestrator_tool_calls",
    "orchestrator_outcome",
    "grounded",
    "feature_flag_orch_enabled",
    "feature_flag_football_intelligence_enabled",
    # G3 (raw-dump instrumentation): how many tools the model actually
    # requested (int) and whether it got a turn to write the final answer
    # itself, as opposed to a bare deterministic render() (bool). Both None
    # when the orchestrator did not run (mirrors orchestrator_tool_calls).
    # See OrchestratorResult.tool_call_count / .synthesis_turn.
    "tool_call_count",
    "synthesis_turn",
})

ROUTING_TRACE_OPTIONAL_KEYS: frozenset[str] = frozenset({
    "expansion_text",       # prompt-expansion branch: canonical text produced
    "workflow_intent",      # prompt branches: prompt_registry workflow intent label
    "dispatched_tool",      # prompt-dispatch branch: tool name invoked
    "classification_source",  # classifier_rewrite branch: "llm_classifier"
    "orchestrator_error",   # orchestrator-exception path: exception message string
    "player_resolution_strategy",  # deterministic player resolution strategy
    "player_candidate_count",      # candidates at the best resolver rank
    "player_lookup_branch",        # explicit/bare outcome or specialized fallthrough
    "player_lookup_diverted",      # why a terminal lookup went to the orchestrator
    # i80: projected straight off OrchestratorResult whenever the orchestrator
    # ran (both the grounded and the no-grounded-tool branches). The audit log
    # used to write retry_attempted=False as a literal; these are the values
    # it now reads instead of asserting from a constant.
    "retry_attempted",    # bool: OrchestratorResult.retry_attempted
    "evaluator_verdict",  # {approved, grounded, complete, safe, retry_feedback,
                          #   fail_open_reason (i124)} | None
    "retry_delivery",     # i125(b): orchestrator.RETRY_DELIVERIES value | None
    "tool_sequence",     # [tool name, ...] executed, from tool_calls_trace (same
                          #   field the routing JSONL projects as tool_sequence)
    "tool_args_sequence", # [args dict, ...] parallel to tool_sequence (i93-b: a
                          #   prod check can read WHICH axis / target_gw each
                          #   executed call carried, not only its name)
    "composed_primary_tool",  # i93: the calendar call promoted to the singular
                              #   slot of a composed turn (final_response.composed_primary_call)
    "web_search_enabled",  # bool: search_web was OFFERED this turn (tier + toggle)
    "search_web_ran",      # bool: search_web was actually EXECUTED this turn
})

# ---------------------------------------------------------------------------
# Unrecognised-query sentinel
# ---------------------------------------------------------------------------

_UNRECOGNISED = {
    "status":  "error",
    "code":    "unrecognised_query",
    "message": (
        "The question could not be mapped to a known tool. "
        "Try asking 'Who is [player]?', 'Give me a summary for [player]', "
        "or 'What is the current gameweek?'."
    ),
}


#: i60: orchestrator-chosen tools whose ``status="ambiguous"`` arms the
#: stable-id pick wizard (candidates come from the CURRENT bootstrap, so a
#: ``player_id`` is safe to hand back). ``find_players`` is not here: it is in
#: DEPRECATED_LLM_TOOL_NAMES and its PR #140 arming branch no longer exists on
#: this path (superseded by the deterministic player lookup). The UI keeps a
#: mirror set of the matching intents (ChatShell.tsx WIZARD_ARMING_INTENTS).
WIZARD_ARMING_TOOLS: frozenset[str] = frozenset({"get_player_snapshot", "get_player_form"})

#: Tools whose answer is NOT the player card: an ambiguous player arms rewrite chips that
#: re-ask the user's own question with the player named in full, never the stable-id
#: handoff (which answers with the generic snapshot and drops the question).
RESUME_QUESTION_TOOLS: frozenset[str] = frozenset({"get_position_changes", "get_player_involvement", "plan_to_sign"})

#: Tools whose own status (ok/ambiguous/not_found) must not be flattened to
#: "ok" just because the orchestrator call succeeded -- otherwise the frontend
#: has no signal to arm a wizard. Scoped deliberately; every other orch-only
#: tool keeps the historical "ok" hardcode (unaudited whether they rely on it).
STATUS_BEARING_TOOLS: frozenset[str] = WIZARD_ARMING_TOOLS | {"get_player_season_points"} | RESUME_QUESTION_TOOLS


def _unrecognised_message(locale: Locale = DEFAULT_LOCALE) -> str:
    """Deterministic fallback text for an unroutable question. F1: localized."""
    return t("harness.unrecognised", locale)


# ---------------------------------------------------------------------------
# F1: Evaluator-client singleton for production wiring
# ---------------------------------------------------------------------------
# Constructed once on first use (per provider); cached for the lifetime of
# the process.  Uses the same API key as the primary orchestrator but passes
# the cheapest model variant (evaluated per-call inside evaluator.py).
#
# Hard rules:
#   - If FPL_EVAL_DISABLED=1, returns None (orchestrator fail-open path).
#   - If client construction fails for any reason, returns None (fail-open).
#   - For Anthropic: the provider client is stateless w.r.t. model — the
#     same client object is passed and evaluator.py picks the haiku model
#     per-call. We reuse the same client construction as the primary.
#   - For OpenAI/Gemini: same pattern — provider client is model-agnostic.

_EVAL_DISABLED_ENV: str = "FPL_EVAL_DISABLED"
_TEST_MODE_TRUTHY_H: frozenset[str] = frozenset({"1", "true", "yes", "on"})

# Cache: (provider_str, api_key_str) → client or None
_eval_client_cache: dict[tuple[str, str | None], Any] = {}
_eval_client_cache_lock = __import__("threading").Lock()


def _build_eval_client(provider: str, api_key: str | None = None) -> Any | None:
    """Return a provider client suitable for the evaluator, or None on failure.

    This is the production-path singleton builder (F1 fix).  Called from
    ask_v2() just before invoking ask_orchestrated().  Returns cached client
    on subsequent calls for the same (provider, api_key) combination.

    Fail-open: any exception → return None.  Never raises.
    """
    # Honour the eval-disabled flag first
    if os.environ.get(_EVAL_DISABLED_ENV, "").strip().lower() in _TEST_MODE_TRUTHY_H:
        return None

    _key = (provider, api_key)
    with _eval_client_cache_lock:
        if _key in _eval_client_cache:
            return _eval_client_cache[_key]

    try:
        from .provider_client import PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI  # noqa: PLC0415
        if provider == PROVIDER_ANTHROPIC:
            from .llm_layer import _get_anthropic_client  # noqa: PLC0415
            client = _get_anthropic_client(api_key=api_key)
        elif provider == PROVIDER_OPENAI:
            # OpenAI: client built inline (mirrors orchestrator.py pattern)
            _oai_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            if not _oai_key:
                client = None
            else:
                import openai as _openai  # type: ignore[import-untyped]  # noqa: PLC0415
                client = _openai.OpenAI(api_key=_oai_key)
        elif provider == PROVIDER_GEMINI:
            _gem_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
            if not _gem_key:
                client = None
            else:
                import google.generativeai as _genai  # type: ignore[import-untyped]  # noqa: PLC0415
                _genai.configure(api_key=_gem_key)
                client = _genai
        else:
            # Unknown provider → fail-open
            client = None
    except Exception:  # noqa: BLE001
        client = None

    with _eval_client_cache_lock:
        _eval_client_cache[_key] = client
    return client


# ---------------------------------------------------------------------------
# Context detection helper
# ---------------------------------------------------------------------------

def _is_assembled_context(data: dict[str, Any]) -> bool:
    """Return True when *data* is an assembled context from ``assemble_captain_context()``.

    Detection rule: the assembled context has a nested ``"bootstrap"`` key
    whose value is a dict.  A raw FPL bootstrap dict does not contain such a
    key (the FPL API never nests a ``"bootstrap"`` key inside bootstrap-static).

    This keeps detection O(1) and avoids inspecting every possible key.
    """
    return isinstance(data.get("bootstrap"), dict)


def _resolve_bootstrap_and_meta(
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return *(bootstrap, meta)* from either an assembled context or a raw bootstrap.

    When *data* is an assembled context:
        * ``bootstrap`` = ``data["bootstrap"]`` (has ``fixture_difficulty_map`` injected)
        * ``meta``      = ``data["meta"]``

    When *data* is a raw bootstrap:
        * ``bootstrap`` = ``data`` unchanged
        * ``meta``      = ``None`` (no meta available)
    """
    if _is_assembled_context(data):
        return data["bootstrap"], data.get("meta")
    return data, None


def _carry_locale(actual_bootstrap: dict[str, Any], locale: Locale) -> dict[str, Any]:
    """i18n S3: put a non-default *locale* on a shallow copy of the bootstrap.

    Tool handlers write user-visible text and take no locale argument, so the
    locale rides on the per-request bootstrap under ``BOOTSTRAP_LOCALE_KEY`` --
    the same reasoning as ``_my_team_id`` (i39): a copy, never the shared
    server-level dict, and nothing at all for the default locale (an es turn
    sees exactly the object it always did).
    """
    if locale == DEFAULT_LOCALE:
        return actual_bootstrap
    carried = dict(actual_bootstrap)
    carried[BOOTSTRAP_LOCALE_KEY] = locale
    return carried


# ---------------------------------------------------------------------------
# Public harness entry point
# ---------------------------------------------------------------------------

def ask(
    question: str,
    bootstrap: dict[str, Any],
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    locale: Locale = DEFAULT_LOCALE,
) -> dict[str, Any]:
    """
    Route *question*, execute the matched tool, and render a safe answer.

    Parameters
    ----------
    question:
        A user-style natural-language question.
    bootstrap:
        Either:

        * A raw FPL bootstrap dict (``"elements"``, ``"teams"``, ``"events"``
          keys) — as returned by ``fpl_api_client.get_bootstrap()``.  For
          automatic FDR derivation also inject
          ``bootstrap["fixture_difficulty_map"]`` first (Phase 2d).

        * A **full assembled context dict** from
          ``fpl_pipeline.assemble_captain_context()`` — i.e. the entire
          ``ctx`` dict including ``"bootstrap"``, ``"gameweek"``,
          ``"fixtures"``, ``"meta"``, … (Phase 2f).  The harness extracts
          the nested bootstrap automatically.  When this form is used the
          return dict gains a ``"context_meta"`` key.

    candidate_inputs:
        Optional scoring inputs for captain score questions.  All four
        inputs (``form``, ``xgi_per_90``, ``minutes_risk``,
        ``fixture_difficulty``) are auto-derived from the bootstrap element
        and the injected ``fixture_difficulty_map`` — supply explicit values
        here only to override the auto-derived ones.

    candidates_list:
        Optional list of candidate dicts for ranking questions.  Each dict
        requires at minimum ``"query"``.  All scoring inputs are
        auto-derived unless explicitly overridden per-candidate.
        If omitted entirely, the runner returns a ``missing_argument`` error.

    Returns
    -------
    dict with keys:

        ``selected_tool``   — tool name (str) or ``None`` if unrecognised.
        ``tool_input``      — args dict passed to ``run_tool``.
        ``raw_output``      — raw response dict from ``run_tool``.
        ``answer_text``     — safe, human-readable sentence.
        ``context_meta``    — meta dict from assembled context (Phase 2f);
                              key is **absent** when raw bootstrap is passed,
                              preserving backwards compatibility.

    Examples
    --------
    Context-native (Phase 2f — recommended)::

        from fpl_pipeline import assemble_captain_context
        from fpl_grounded_assistant import ask

        ctx    = assemble_captain_context()
        result = ask("captain score for Haaland", ctx)
        # result["context_meta"]["blank_gw_teams"] → list of blank-GW team IDs

    Legacy raw-bootstrap (still works unchanged)::

        result = ask("captain score for Haaland", bootstrap)
        # No "context_meta" key in result
    """
    # ------------------------------------------------------------------
    # 1. Resolve bootstrap + optional meta
    # ------------------------------------------------------------------
    actual_bootstrap, context_meta = _resolve_bootstrap_and_meta(bootstrap)
    actual_bootstrap = _carry_locale(actual_bootstrap, locale)  # i18n S3

    # ------------------------------------------------------------------
    # 2. Route question
    # ------------------------------------------------------------------
    route_result = route(question)

    if route_result is None:
        result = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    _UNRECOGNISED,
            "answer_text":   _unrecognised_message(locale),
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        return result

    tool_args: dict[str, Any] = dict(route_result.tool_args)

    # ------------------------------------------------------------------
    # 3. Inject optional caller overrides
    # ------------------------------------------------------------------
    # Merge candidate_inputs into tool_args for captain score questions
    if route_result.tool_name == "get_captain_score" and candidate_inputs:
        tool_args.update(candidate_inputs)

    # Inject candidates_list for ranking questions
    if route_result.tool_name == "rank_captain_candidates" and candidates_list is not None:
        tool_args["candidates"] = candidates_list

    # ------------------------------------------------------------------
    # 4. Execute tool
    # ------------------------------------------------------------------
    raw_output = run_tool(
        route_result.tool_name,
        tool_args,
        actual_bootstrap,
    )

    answer_text = render(route_result.tool_name, raw_output, locale=locale)

    # ------------------------------------------------------------------
    # 5. Build return dict
    # ------------------------------------------------------------------
    result = {
        "selected_tool": route_result.tool_name,
        "tool_input":    tool_args,
        "raw_output":    raw_output,
        "answer_text":   answer_text,
    }
    if context_meta is not None:
        result["context_meta"] = context_meta
    return result


# ---------------------------------------------------------------------------
# Phase M2 (MCP_architecture): prompt dispatch helper
# ---------------------------------------------------------------------------

def _dispatch_prompt(
    prompt_name: str,
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    """Call the underlying deterministic helper for a MODE_DISPATCH prompt.

    Returns ``(tool_name, raw_output, tool_input)``.

    The registered tool handlers in ``TOOL_REGISTRY`` ignore the optional
    typed kwargs that prompts carry (``horizon``, ``ownership_threshold``,
    ``top_n``). We invoke the deterministic helpers directly so the typed
    arguments are honored — that is the whole point of dispatch mode.
    """
    if prompt_name == "calendarios":
        from .player_fixture_run import get_player_fixture_run
        query   = args["player"]
        horizon = int(args.get("horizon", 5))
        tool_input = {"query": query, "horizon": horizon}
        raw = get_player_fixture_run(query, bootstrap, horizon=horizon)
        return "get_player_fixture_run", raw, tool_input

    if prompt_name == "diferenciales":
        from .differential_picks import get_differential_picks
        threshold = float(args.get("threshold", 15.0))
        top_n     = int(args.get("top_n", 5))
        tool_input = {"ownership_threshold": threshold, "top_n": top_n}
        raw = get_differential_picks(
            bootstrap, ownership_threshold=threshold, top_n=top_n,
        )
        return "get_differential_picks", raw, tool_input

    return None, {"status": "error", "code": "unknown_dispatch_prompt"}, {}


# ---------------------------------------------------------------------------
# Phase M1 (MCP_architecture): ask_v2 — outer decision-router entrypoint
# ---------------------------------------------------------------------------

def ask_v2(
    question: str,
    bootstrap: dict[str, Any],
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    *,
    classifier_client: Any | None = None,
    orch_client: Any | None = None,
    orch_api_key: str | None = None,
    orch_provider: str | None = None,
    web_search_enabled: bool = False,
    selected_player_id: int | None = None,
    _enrich_existing_intents: bool = True,
    locale: Locale = DEFAULT_LOCALE,
    team_id: int | None = None,
    league_id: int | None = None,
) -> dict[str, Any]:
    """Phase M1/M2/M3 entrypoint composing `decision_router` + existing `ask()`.

    Behavior summary:

    * `@<resource>`  -> resource path; result dict carries `outcome="ok"`,
                        `resource_rows={...}`, and `routing_trace`.
    * `@<unknown>`   -> `outcome="unsupported"`, `suggestions=[...]`.
    * `/<prompt>`    -> M2: prompt registry dispatch / expansion.
    * plain text     -> deterministic general-player probe, then P1.a routing:
                         1. rich snapshot / ambiguity wizard when resolved
                         2. ask_orchestrated()             — LLM-primary (P1.a)
                         3. unsupported + suggestions

    Step 1 is gated by the ``FPL_ORCH_ENABLED`` environment variable (default
    OFF).  The ``classifier_client`` kwarg is accepted for backwards
    compatibility but has NO effect on the plain-text path post-P1.a.
    The orchestrator may call ``route()`` internally as a deterministic tool.

    A ``routing_trace`` dict is attached to every returned result.

    **Tier: stable (graduated M5, 2026-05-17).** ``routing_trace`` is an
    additive, optional field that is now part of the stable response contract
    for server-side consumers, automated tests, and traffic shaping.  The
    schema is pinned by ``ROUTING_TRACE_REQUIRED_KEYS`` and
    ``ROUTING_TRACE_OPTIONAL_KEYS`` in this module.  Changes to these key
    sets are breaking and must be documented with a phase label.

    Required keys (always present in every routing_trace)::

        {
          "branch":                  str,            # which ladder rung fired
          "decision_kind":           str,            # from decision_router: "resource"|"prompt"|"text"|...
          "decision_outcome":        str,            # from decision_router: OUTCOME_* constant
          "router_hit":              bool,           # True iff route() succeeded
          "classifier_called":       bool,           # True iff classify_intent_llm() was called
          "classifier_confidence":   float | None,   # LLM confidence, or None
          "classifier_intent":       str | None,     # LLM intent label, or None
          "orchestrator_called":     bool,           # True iff ask_orchestrated() was called
          "orchestrator_tool_calls": list[str] | None, # tools chosen by orchestrator
          "orchestrator_outcome":    str | None,     # orchestrator OUTCOME_* constant, or None
          "grounded":                bool,           # True iff a deterministic tool ran end-to-end
          "feature_flag_orch_enabled": bool,         # snapshot of FPL_ORCH_ENABLED at call time
          "feature_flag_football_intelligence_enabled": bool,
                                                     # snapshot of FI master flag
          "tool_call_count":         int | None,     # G3: tools the model actually requested, or None
          "synthesis_turn":          bool | None,    # G3: model wrote answer_text itself, or None
        }

    Optional keys (present only on specific branches)::

        "expansion_text"       (str)   prompt-expansion branch: canonical text produced
        "workflow_intent"      (str)   prompt branches: prompt_registry workflow intent
        "dispatched_tool"      (str)   prompt-dispatch branch: tool name invoked
        "classification_source" (str)  classifier_rewrite branch: "llm_classifier"
        "orchestrator_error"   (str)   orchestrator-exception path: exception message
        "player_resolution_strategy" (str | None) player resolver's best rank
        "player_candidate_count" (int) number of candidates at that rank
        "player_lookup_branch" (str) deterministic lookup/fallthrough branch

    See ``ROUTING_TRACE_REQUIRED_KEYS`` and ``ROUTING_TRACE_OPTIONAL_KEYS``
    for the machine-readable frozen-schema constants used by tests.

    **Structured metadata (G1 commit 2 addition):**

    Every returned dict also carries the 14 intent-specific structured-metadata
    keys produced by ``final_response._extract_structured_meta()``.  These keys
    are at the **top level** (no sub-key namespace) because none collide with the
    pre-existing keys in the ask_v2 return dict.  On branches that execute a
    deterministic tool (``route``, ``classifier_rewrite``, ``prompt`` with
    dispatch or expansion, ``orchestrator`` with a grounded tool call) the keys
    are populated from the real raw_output.  On all other branches
    (``resource``, ``unsupported``, ``needs_clarification``, orchestrator
    exception/no-grounded) all 14 values are ``None``.

    The 14 keys are::

        "comparison"           — ComparisonMeta | None
        "captain"              — CaptainScoreMeta | None
        "captain_ranking"      — tuple[RankedCaptainEntry, ...] | None
        "transfer"             — TransferMeta | None
        "chip"                 — ChipAdviceMeta | None
        "fixture_run"          — FixtureRunMeta | None
        "differential"         — DifferentialPicksMeta | None
        "player_form"          — PlayerFormMeta | None
        "injury_list"          — InjuryListMeta | None
        "price_changes"        — PriceChangesMeta | None
        "team_calendar"        — TeamFixtureCalendarMeta | None
        "team_schedule"        — TeamScheduleMeta | None
        "position_fixture_run" — PositionFixtureRunMeta | None
        "transfer_suggestion"  — TransferSuggestionMeta | None

    Note: ``ask_v2()`` does NOT apply squad_context overrides to these values.
    The adapter (``harness_adapter.py``, commit 3) is responsible for applying
    ``_apply_squad_overrides`` before projecting into ``AskResponse``.

    ``branch`` values::

        "resource"           — @resource matched and returned grounded rows.
        "prompt"             — /prompt matched (expansion or dispatch mode).
        "route"              — plain text resolved as a general player lookup.
        "orchestrator"       — plain text; orchestrator returned a grounded
                               tool call (P1.a primary path).
        "unsupported"        — no path produced a grounded answer.

        ["classifier_rewrite" no longer fires for plain text from ask_v2().]

    ``grounded`` is True iff at least one deterministic tool ran end-to-end
    via the tool runner. An orchestrator answer with no tool call sets
    ``grounded=False`` and surfaces the unsupported fallback message
    (per plan §M3: "orchestrator answer without tool call -> grounded=false").

    The existing ``ask()`` is **not modified**. This is purely additive and
    does not affect any caller of ``ask()``.

    ``grounded`` is True iff at least one deterministic tool ran end-to-end
    via the tool runner. An orchestrator answer with no tool call sets
    ``grounded=False`` and surfaces the unsupported fallback message
    (per plan §M3: "orchestrator answer without tool call -> grounded=false").

    The existing ``ask()`` is **not modified**. This is purely additive and
    does not affect any caller of ``ask()``.

    Parameters
    ----------
    classifier_client:
        Optional Anthropic-compatible client for ``classify_intent_llm``.
        When ``None``, step 2 is skipped and unrouted text falls straight
        to step 3 (or to unsupported).
    orch_client:
        Optional LLM client passed to ``ask_orchestrated``. Test runners
        inject mocks here. When ``None`` and no ``orch_api_key`` is given,
        ``ask_orchestrated`` resolves credentials from the environment.
    orch_api_key:
        Optional explicit API key for orchestrator provider resolution.
    orch_provider:
        Optional provider override ("anthropic" | "openai" | "gemini").
        When omitted, ``FPL_ORCH_PROVIDER`` env var is consulted via
        ``orch_config.get_orch_provider()``.
    web_search_enabled:
        Passed straight through to ``ask_orchestrated()``. Callers
        (``fpl_server.py``) must resolve tier eligibility + explicit opt-in
        BEFORE setting this to ``True`` — ``ask_v2()`` performs no gating.
    locale:
        Language-track carrier param. Forwarded to the deterministic text
        producers on the ``route`` / ``prompt`` branches (``ask()``,
        ``render()``, the unrecognised-query fallback) and, since i18n S0, to
        ``ask_orchestrated(locale=)``: the system-prompt line (en only), the
        evaluator, retries, the synthesis rounds and the deterministic
        composers/fallbacks inside the orchestrator all follow it.
    team_id:
        i39 carrier param — the connected user's FPL entry (team) id, when the
        request has one. ``None`` for every anonymous turn (the overwhelming
        majority). When present, injected as ``bootstrap["_my_team_id"]`` onto
        a **shallow copy** of ``actual_bootstrap`` — never a mutation of the
        caller's ``bootstrap`` dict, which in production is the single
        server-level cached bootstrap shared across every concurrent request
        (see ``fpl_server.py``'s module-level ``_bootstrap``). Mutating that
        shared object in place would leak one user's team id into another
        user's turn under FastAPI's threadpool — the same class of bug
        ``catalogue.py`` documents for locale. The copy is skipped entirely
        when ``team_id is None``, so a turn with no team connected sees the
        exact same ``actual_bootstrap`` object it always did. Read by the
        ``get_my_squad`` tool (``get_my_squad.py``); every other tool ignores
        the extra key.
    league_id:
        The user's chosen main mini-league id, when the request carries one. Injected as
        ``bootstrap["_my_league_id"]`` on a shallow copy, exactly like ``team_id`` (never a
        mutation of the shared bootstrap); read only by ``get_league_eo``. Skipped when None.
    """
    # Import here to avoid circulars at module-load time.
    from .decision_router import (
        decide,
        OUTCOME_OK_RESOURCE,
        OUTCOME_OK_PROMPT_DISPATCH,
        OUTCOME_OK_PROMPT_EXPANSION,
        OUTCOME_UNSUPPORTED,
        OUTCOME_NEEDS_CLARIFICATION,
        OUTCOME_FALLTHROUGH,
    )
    from fpl_tool_runner import run_tool as _run_tool
    from .renderer import render as _render
    from .dispatcher import _auto_candidates_from_bootstrap, OUTCOME_OK as _DISP_OUTCOME_OK, _TOOL_TO_INTENT
    from .orch_config import (
        get_orch_model,
        get_orch_provider,
        is_football_intelligence_enabled,
        is_orch_enabled,
    )
    from . import telemetry as _telemetry
    # G1 commit 2: deferred to avoid circular import (dispatcher imports ask from harness)
    from .final_response import _extract_structured_meta

    def _meta(tool_name: "str | None", raw_output: dict) -> "dict[str, Any]":
        """Derive structured metadata for a completed deterministic tool call."""
        if tool_name is None:
            return _extract_structured_meta("", {}, "unsupported")
        intent = _TOOL_TO_INTENT.get(tool_name, "")
        status = raw_output.get("status", "")
        outcome = _DISP_OUTCOME_OK if status == "ok" else "unsupported"
        return _extract_structured_meta(intent, raw_output, outcome, locale)  # i18n S3b

    _none_meta: "dict[str, Any]" = _extract_structured_meta("", {}, "unsupported")

    def _outcome_from_status(raw: dict) -> str:
        """Map dispatcher raw_output['status'] to AskResponse outcome value.

        Fix B (mcp-graduation G1.4): ask_v2() previously hard-coded
        result["outcome"] = "ok" on every tool-ran branch, discarding
        not_found / ambiguous / error / needs_clarification from the tool's
        actual raw_output["status"].  This helper restores parity with the
        dispatcher path (respond()) which derives outcome from status.

        Mirrors dispatcher._compute_outcome() semantics:
          - "ok"       → "ok"
          - "not_found"→ "not_found"
          - "ambiguous"→ "ambiguous"
          - "error"    → "error"
          - anything else (including "empty") → "error"  (matches _compute_outcome fallthrough)
          - "needs_clarification" → "needs_clarification"  (medium-confidence gate path)
        """
        s = raw.get("status", "")
        if s == "ok":                  return "ok"
        if s == "not_found":           return "not_found"
        if s == "ambiguous":           return "ambiguous"
        if s == "error":               return "error"
        if s == "needs_clarification": return "needs_clarification"
        if not s:                      return "unsupported"
        # Any unrecognised status (e.g. "empty") maps to "error" to match
        # dispatcher._compute_outcome() fallthrough logic.
        return "error"

    # Resolve bootstrap up-front so both branches operate on the same data
    actual_bootstrap, context_meta = _resolve_bootstrap_and_meta(bootstrap)

    # i39: inject the connected user's team id for get_my_squad, on a shallow
    # copy only — see the team_id docstring entry above for why this must
    # never mutate the shared bootstrap dict in place. Skipped entirely when
    # team_id is None so the no-team-connected path is byte-for-byte
    # unchanged (same object, not just same contents).
    if team_id is not None:
        actual_bootstrap = dict(actual_bootstrap)
        actual_bootstrap["_my_team_id"] = team_id
    if league_id is not None:
        actual_bootstrap = dict(actual_bootstrap)
        actual_bootstrap["_my_league_id"] = league_id

    # Free transfers the user states in this turn's own words ("tengo 3 cambios
    # disponibles"): plan_to_sign reads them from here when the model did not pass
    # them, so the hit cost never depends on the model remembering. Shallow copy,
    # same reasoning as the team id above; skipped when the text states none.
    from .free_transfers_text import extract_free_transfers as _extract_free_transfers  # noqa: PLC0415

    _stated_free_transfers = _extract_free_transfers(question)
    if _stated_free_transfers is not None:
        actual_bootstrap = dict(actual_bootstrap)
        actual_bootstrap["_free_transfers_stated"] = _stated_free_transfers

    # i18n S3: see _carry_locale (the sub-branches that call ask() do the same).
    actual_bootstrap = _carry_locale(actual_bootstrap, locale)

    # Stable-id wizard handoff: the structured id is authoritative. The
    # display question is deliberately ignored so a stale id can never fall
    # back to name matching and silently select another player.
    if selected_player_id is not None:
        from .get_player_snapshot import get_player_snapshot  # noqa: PLC0415

        _player_raw = get_player_snapshot(selected_player_id, bootstrap=actual_bootstrap)
        _player_outcome = _outcome_from_status(_player_raw)
        routing_trace = {
            "branch": "route",
            "decision_kind": "selected_player_id",
            "decision_outcome": _player_outcome,
            "router_hit": True,
            "classifier_called": False,
            "classifier_confidence": None,
            "classifier_intent": None,
            "orchestrator_called": False,
            "orchestrator_tool_calls": None,
            "orchestrator_outcome": None,
            "grounded": True,
            "tool_call_count": None,
            "synthesis_turn": None,
            "feature_flag_orch_enabled": is_orch_enabled(),
            "feature_flag_football_intelligence_enabled": is_football_intelligence_enabled(),
            "player_resolution_strategy": "id" if _player_outcome == "ok" else None,
            "player_candidate_count": 1 if _player_outcome == "ok" else 0,
            "player_lookup_branch": "selected_player_id",
        }
        result = {
            "selected_tool": "get_player_snapshot",
            "tool_input": {"player_name": selected_player_id},
            "raw_output": _player_raw,
            "answer_text": _render("get_player_snapshot", _player_raw, locale=locale),
            "outcome": _player_outcome,
            "kind": "text",
            "routing_trace": routing_trace,
            **_meta("get_player_snapshot", _player_raw),
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)
        return result

    # plan_to_sign follow-up ("who else can I sell to get the money?"): the UI
    # sends back the previous plan's state on this turn only; a recognised
    # phrase re-runs the same deterministic tool with it. No model call.
    # A tap on a move-count chip ("... Plan: Use hits (-4 each)") is the same tool with ``moves`` set, also
    # without a model: the chip text is the tool's own template and names the target, so it needs no state.
    if selected_player_id is None:
        from .plan_followup import (  # noqa: PLC0415
            followup_args as _plan_followup_args,
            is_plan_followup as _is_plan_followup,
            move_tap as _plan_move_tap,
            option_pick as _plan_option_pick,
            sanitize_plan_state as _sanitize_plan_state,
        )

        _plan_pick = None
        _plan_args = _plan_move_tap(question)
        _plan_raw = run_tool("plan_to_sign", _plan_args, actual_bootstrap) if _plan_args is not None else None
        if _plan_raw is not None and (_plan_raw.get("status") != "ok" or _plan_raw.get("stage") != "plan"):
            _plan_args = _plan_raw = None  # no plan to show (unknown or ambiguous target ...): the normal route answers
        if _plan_args is None and isinstance(actual_bootstrap.get("_plan_state"), dict):
            _plan_pick = _plan_option_pick(question)
            _plan_state_in = (
                _sanitize_plan_state(actual_bootstrap["_plan_state"])
                if _plan_pick is not None or _is_plan_followup(question)
                else None
            )
            if _plan_state_in is not None:
                _plan_args = _plan_followup_args(_plan_state_in, keep_shown=_plan_pick is not None)
                _plan_raw = run_tool("plan_to_sign", _plan_args, actual_bootstrap)
        if _plan_args is not None and _plan_raw is not None:
            if _plan_pick is not None:
                _plan_raw["focus"] = _plan_pick  # the card is about the option the user tapped
            _plan_outcome = _outcome_from_status(_plan_raw)
            routing_trace = {
                "branch": "route",
                "decision_kind": "plan_followup",
                "decision_outcome": _plan_outcome,
                "router_hit": True,
                "classifier_called": False,
                "classifier_confidence": None,
                "classifier_intent": None,
                "orchestrator_called": False,
                "orchestrator_tool_calls": None,
                "orchestrator_outcome": None,
                "grounded": True,
                "tool_call_count": None,
                "synthesis_turn": None,
                "feature_flag_orch_enabled": is_orch_enabled(),
                "feature_flag_football_intelligence_enabled": is_football_intelligence_enabled(),
            }
            result = {
                "selected_tool": "plan_to_sign",
                "tool_input": _plan_args,
                "raw_output": _plan_raw,
                "answer_text": _render("plan_to_sign", _plan_raw, locale=locale),
                "outcome": _plan_outcome,
                "kind": "text",
                "routing_trace": routing_trace,
                **_meta("plan_to_sign", _plan_raw),
            }
            from .atomic_tool_cards import maybe_atomic_tool_card  # noqa: PLC0415

            if result.get("generic_card") is None:
                _plan_card = maybe_atomic_tool_card("plan_to_sign", _plan_raw, None, locale)
                if _plan_card is not None:
                    result["generic_card"] = _plan_card
            if result.get("generic_card") is not None:
                from .plan_card import plan_one_line  # noqa: PLC0415

                # no model wrote this text, and the card shows the rest: one line for the option on the card
                result["answer_text"] = plan_one_line(_plan_raw, locale) or result["answer_text"]
            _plan_chips = _plan_to_sign_chips("plan_to_sign", _plan_raw, locale)
            if _plan_chips is not None:
                result["player_suggestions"] = _plan_chips
            if _plan_raw.get("plan_state") is not None:
                result["plan_state"] = _plan_raw["plan_state"]
            if context_meta is not None:
                result["context_meta"] = context_meta
            _telemetry.record(routing_trace)
            return result

    # An EO chip tap ("EO cerca de tu puesto", "EO top 10K", "EO en <liga>", "Cambiar de liga"): the chip's own text,
    # matched exactly, answers from the same tool without a model. Anything else, or any non-answer, goes on.
    if selected_player_id is None:
        from .eo_taps import eo_tap as _eo_tap, run_eo_tap as _run_eo_tap  # noqa: PLC0415

        _eo = _eo_tap(question)
        _eo_run = _run_eo_tap(_eo, actual_bootstrap, locale) if _eo is not None else None
        if _eo_run is not None:
            _eo_raw = _eo_run["raw"]
            routing_trace = {
                "branch": "route",
                "decision_kind": "eo_tap",
                "decision_outcome": "ok",
                "router_hit": True,
                "classifier_called": False,
                "classifier_confidence": None,
                "classifier_intent": None,
                "orchestrator_called": False,
                "orchestrator_tool_calls": None,
                "orchestrator_outcome": None,
                "grounded": True,
                "tool_call_count": None,
                "synthesis_turn": None,
                "feature_flag_orch_enabled": is_orch_enabled(),
                "feature_flag_football_intelligence_enabled": is_football_intelligence_enabled(),
            }
            result = {
                "selected_tool": _eo_run["tool"],
                "tool_input": _eo_run["args"],
                "raw_output": _eo_raw,
                # "calculating" is a complete, deterministic answer (the text and the pending marker); the poll's ready
                # answer then replaces it with the card
                "answer_text": _eo_run["text"],
                "outcome": "ok" if _eo_run["pending"] is not None else _outcome_from_status(_eo_raw),
                "kind": "text",
                "routing_trace": routing_trace,
                **_meta(_eo_run["tool"], _eo_raw),
            }
            if _eo_run["card"] is not None:
                result["generic_card"] = _eo_run["card"]
            if _eo_run["chips"] is not None:
                result["player_suggestions"] = _eo_run["chips"]
            if _eo_run["pending"] is not None:
                result["pending"] = _eo_run["pending"]
            if context_meta is not None:
                result["context_meta"] = context_meta
            _telemetry.record(routing_trace)
            return result

    decision = decide(question, actual_bootstrap, locale=locale)
    kind = decision["kind"]
    outcome = decision["outcome"]

    _orch_enabled = is_orch_enabled()
    _football_intelligence_enabled = is_football_intelligence_enabled()

    def _copy_existing_intent_evidence(result: dict[str, Any]) -> None:
        """Copy one finalized FI-7c bundle onto a successful stateless result."""
        if (
            not _enrich_existing_intents
            or not _football_intelligence_enabled
            or result.get("outcome") != "ok"
        ):
            return
        from .existing_intent_evidence import enrich_existing_intent_evidence

        evidence = enrich_existing_intent_evidence(
            result.get("selected_tool"),
            result.get("raw_output") or {},
            actual_bootstrap,
        )
        if evidence is not None:
            result["evidence"] = evidence

    # M3 routing_trace — additive observability dict attached to every result.
    # Keys are stable; values are filled in per-branch below.
    routing_trace: dict[str, Any] = {
        "branch":                    "unsupported",
        "decision_kind":             kind,
        "decision_outcome":          outcome,
        "router_hit":                False,
        "classifier_called":         False,
        "classifier_confidence":     None,
        "classifier_intent":         None,
        "orchestrator_called":       False,
        "orchestrator_tool_calls":   None,
        "orchestrator_outcome":      None,
        "grounded":                  False,
        "tool_call_count":           None,
        "synthesis_turn":            None,
        "feature_flag_orch_enabled": _orch_enabled,
        "feature_flag_football_intelligence_enabled": _football_intelligence_enabled,
    }

    if outcome == OUTCOME_OK_RESOURCE and kind == "resource":
        routing_trace["branch"]   = "resource"
        routing_trace["grounded"] = True
        result: dict[str, Any] = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    {"status": "ok"},
            "answer_text":   decision.get("message", ""),
            "outcome":       "ok",
            "kind":          "resource",
            "resource":      decision.get("resource"),
            "resource_rows": decision.get("resource_rows"),
            # The table's verdict (table_conclusions): None unless a rule fires.
            "table_conclusions": _resource_table_conclusions(decision, actual_bootstrap),
            "routing_trace": routing_trace,
            **_none_meta,  # resource branch: no deterministic tool ran → all 14 keys are None
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    if outcome == OUTCOME_NEEDS_CLARIFICATION:
        routing_trace["branch"] = "prompt"
        # Guided Comparison flow: attach deterministic tappable suggestions when
        # the clarification belongs to a compare prompt (intent==compare_players).
        # The prompt's workflow_intent is resolved from the registry so the
        # intent -> supplier map lives entirely in suggestions.py.
        from .prompt_registry import get_prompt_spec as _get_prompt_spec  # noqa: PLC0415
        from .suggestions import build_suggestion_dicts as _build_suggestion_dicts  # noqa: PLC0415
        _pn = decision.get("prompt_name")
        _spec = _get_prompt_spec(_pn) if _pn else None
        _clar_intent = _spec.workflow_intent if _spec is not None else None
        _player_suggestions = _build_suggestion_dicts(
            _clar_intent, "needs_clarification", actual_bootstrap,
        )
        result = {
            "selected_tool":  None,
            "tool_input":     {},
            "raw_output":     {"status": "needs_clarification"},
            "answer_text":    decision.get("message", ""),
            "outcome":        "needs_clarification",
            "kind":           "prompt",
            "prompt_name":    decision.get("prompt_name"),
            "missing_fields": decision.get("missing_fields", []),
            "errors":         decision.get("errors", []),
            "player_suggestions": _player_suggestions,  # Guided Comparison: list[dict] | None
            "routing_trace":  routing_trace,
            **_none_meta,  # needs_clarification: no tool ran → all 14 keys are None
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    if outcome == OUTCOME_OK_PROMPT_EXPANSION:
        canonical_text = decision.get("canonical_text", "")
        prompt_name    = decision.get("prompt_name")
        workflow_intent = decision.get("workflow_intent")
        # For /clasificacion the canonical text routes to rank_captain_candidates
        # which requires candidates_list. Honor the optional `n` arg by
        # auto-populating top-N candidates from bootstrap.
        eff_candidates = candidates_list
        if prompt_name == "clasificacion" and not eff_candidates:
            n = decision.get("args", {}).get("n", 5)
            eff_candidates = _auto_candidates_from_bootstrap(actual_bootstrap, top_n=int(n))
        result = ask(
            canonical_text,
            bootstrap,
            candidate_inputs=candidate_inputs,
            candidates_list=eff_candidates,
            locale=locale,
        )
        # Derive the outcome from the tool's actual status. This branch used to
        # hard-code "ok" whenever a tool was selected, which silently reported
        # ambiguous / not_found / error prompt turns as successes and left the
        # UI with no signal to act on. Mirrors the dispatcher path, and matches
        # what the plain-text and prompt-dispatch branches already do.
        _expansion_raw = result.get("raw_output") or {}
        result["outcome"] = (
            _outcome_from_status(_expansion_raw)
            if result.get("selected_tool")
            else "unsupported"
        )
        result["kind"] = "prompt"
        result["prompt_name"] = prompt_name
        result["workflow_intent"] = workflow_intent
        result["canonical_text"] = canonical_text
        # Ambiguous player inside a prompt turn: offer pick-one chips that
        # re-send the user's own command with the ambiguous slot resolved,
        # rather than dead-ending on "please clarify". None when the command
        # cannot be rewritten safely — see prompt_disambiguation.
        if result["outcome"] == "ambiguous":
            from .prompt_disambiguation import (  # noqa: PLC0415
                prompt_disambiguation_suggestions,
            )
            from .suggestions import suggestions_to_list as _sugg_to_list  # noqa: PLC0415

            result["player_suggestions"] = _sugg_to_list(
                prompt_disambiguation_suggestions(
                    question, prompt_name, _expansion_raw,
                )
            )
        routing_trace["branch"]            = "prompt"
        routing_trace["expansion_text"]    = canonical_text
        routing_trace["workflow_intent"]   = workflow_intent
        routing_trace["router_hit"]        = result.get("selected_tool") is not None
        routing_trace["grounded"]          = result.get("selected_tool") is not None
        result["routing_trace"] = routing_trace
        # prompt-expansion branch: extract metadata when tool ran, else all-None
        result.update(_meta(result.get("selected_tool"), result.get("raw_output", {})))
        _copy_existing_intent_evidence(result)
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    if outcome == OUTCOME_OK_PROMPT_DISPATCH:
        prompt_name     = decision.get("prompt_name")
        workflow_intent = decision.get("workflow_intent")
        args            = decision.get("args", {})
        tool_name, raw_output, tool_input = _dispatch_prompt(
            prompt_name, args, actual_bootstrap,
        )
        answer_text = _render(tool_name, raw_output, locale=locale) if tool_name else ""
        routing_trace["branch"]          = "prompt"
        routing_trace["dispatched_tool"] = tool_name
        routing_trace["workflow_intent"] = workflow_intent
        routing_trace["grounded"]        = tool_name is not None and raw_output.get("status") == "ok"
        # Derive the outcome from the tool's status rather than collapsing every
        # non-"ok" status to "error" — an ambiguous player is a recoverable
        # clarification the UI can offer chips for, not a failure.
        result = {
            "selected_tool":   tool_name,
            "tool_input":      tool_input,
            "raw_output":      raw_output,
            "answer_text":     answer_text,
            "outcome":         _outcome_from_status(raw_output),
            "kind":            "prompt",
            "prompt_name":     prompt_name,
            "workflow_intent": workflow_intent,
            "routing_trace":   routing_trace,
            **_meta(tool_name, raw_output),  # prompt-dispatch: real tool ran, extract metadata
        }
        if result["outcome"] == "ambiguous":
            from .prompt_disambiguation import (  # noqa: PLC0415
                prompt_disambiguation_suggestions,
            )
            from .suggestions import suggestions_to_list as _sugg_to_list  # noqa: PLC0415

            result["player_suggestions"] = _sugg_to_list(
                prompt_disambiguation_suggestions(question, prompt_name, raw_output)
            )
        if context_meta is not None:
            result["context_meta"] = context_meta
        _copy_existing_intent_evidence(result)
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    if outcome == OUTCOME_UNSUPPORTED:
        routing_trace["branch"] = "unsupported"
        result = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    {"status": "unsupported"},
            "answer_text":   decision.get("message", ""),
            "outcome":       "unsupported",
            "kind":          kind,
            "suggestions":   decision.get("suggestions", []),
            "routing_trace": routing_trace,
            **_none_meta,  # unsupported: no tool ran → all 14 keys are None
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    # ------------------------------------------------------------------
    # Deterministic general-player probe, then P1.a orchestrator routing
    # ------------------------------------------------------------------
    # General named-player lookups are resolved before orchestration. Everything
    # else continues through the post-P1.a orchestrator-primary path; classifier
    # rewriting remains absent.
    #
    # Ladder summary:
    #   1. deterministic rich player snapshot / ambiguity wizard
    #   2. ask_orchestrated()  — LLM-primary; gated by FPL_ORCH_ENABLED
    #   3. unsupported + suggestions  — when orchestrator disabled/unavailable
    #
    # Legacy: classifier_client kwarg is no longer consulted for plain-text
    # routing.  The parameter is kept for backwards-compat call-sites but
    # has NO effect on the plain-text path post-P1.a.
    assert outcome == OUTCOME_FALLTHROUGH
    cleaned_text = decision.get("text", question)

    # General named-player lookups are deterministic and precede orchestration.
    # Non-terminal misses retain the complete input for the existing LLM path.
    from .player_lookup import (  # noqa: PLC0415
        classify_player_lookup,
        execute_player_lookup,
        should_divert_player_lookup,
    )

    _player_lookup = classify_player_lookup(cleaned_text, actual_bootstrap)
    routing_trace["player_resolution_strategy"] = _player_lookup.resolution_strategy
    routing_trace["player_candidate_count"] = _player_lookup.candidate_count
    routing_trace["player_lookup_branch"] = _player_lookup.deterministic_branch
    routing_trace["web_search_enabled"] = bool(web_search_enabled)
    routing_trace["search_web_ran"] = False
    _divert, _divert_reason = should_divert_player_lookup(
        _player_lookup, cleaned_text, web_search_enabled
    )
    if _divert:
        routing_trace["player_lookup_diverted"] = _divert_reason
    if _player_lookup.terminal and not _divert:
        from .suggestions import (  # noqa: PLC0415
            player_disambiguation_suggestions,
            suggestions_to_list,
        )

        _player_raw = execute_player_lookup(_player_lookup, actual_bootstrap)
        _player_outcome = _outcome_from_status(_player_raw)
        routing_trace["branch"] = "route"
        routing_trace["router_hit"] = True
        routing_trace["grounded"] = True
        _player_meta = _meta("get_player_snapshot", _player_raw)
        result = {
            "selected_tool": "get_player_snapshot",
            "tool_input": {"player_name": _player_lookup.query},
            "raw_output": _player_raw,
            "answer_text": _render("get_player_snapshot", _player_raw, locale=locale),
            "outcome": _player_outcome,
            "kind": "text",
            "routing_trace": routing_trace,
            **_player_meta,
        }
        if _player_outcome == "ambiguous":
            result["player_suggestions"] = suggestions_to_list(
                player_disambiguation_suggestions(_player_raw.get("candidates", []))
            )
        _copy_existing_intent_evidence(result)
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)
        return result

    # --- Step 1 (P1.a): ask_orchestrated() — PRIMARY for plain text ---
    # The orchestrator runs when (a) the feature flag is ON AND (b) a
    # client/api_key is reachable. Either condition false -> step 2 (unsupported).
    if _orch_enabled and (orch_client is not None or orch_api_key is not None or
                          os.environ.get("ANTHROPIC_API_KEY") or
                          os.environ.get("OPENAI_API_KEY") or
                          os.environ.get("GOOGLE_API_KEY")):
        from .orchestrator import (
            ask_orchestrated,
            OUTCOME_OK as ORCH_OUTCOME_OK,
            OUTCOME_NO_TOOL as ORCH_OUTCOME_NO_TOOL,
            OUTCOME_TOOL_RESULT_ERROR as ORCH_OUTCOME_TOOL_RESULT_ERROR,
        )
        routing_trace["orchestrator_called"] = True
        _provider = orch_provider if orch_provider is not None else get_orch_provider()
        _model = get_orch_model(_provider)
        # F1: construct evaluator client on the production path (singleton, cached).
        # Fail-open: if disabled or construction fails, _eval_client is None and
        # the orchestrator's fail-open path (_apply_evaluator) is a no-op.
        _eval_client = _build_eval_client(_provider, api_key=orch_api_key)
        try:
            orch_result = ask_orchestrated(
                cleaned_text,
                actual_bootstrap,
                client=orch_client,
                api_key=orch_api_key,
                provider=_provider,
                model=_model,
                web_search_enabled=web_search_enabled,
                _eval_client=_eval_client,
                locale=locale,
            )
        except Exception as exc:  # noqa: BLE001  — defensive; ask_orchestrated never raises
            routing_trace["branch"]                  = "unsupported"
            routing_trace["orchestrator_outcome"]    = "exception"
            routing_trace["grounded"]                = False
            result = {
                "selected_tool": None,
                "tool_input":    {},
                "raw_output":    {"status": "unsupported", "code": "orchestrator_exception"},
                "answer_text":   _unrecognised_message(locale),
                "outcome":       "unsupported",
                "kind":          "text",
                "suggestions":   [f"@{r}" for r in _suggestions_for_text()],
                "orchestrator_error": str(exc),
                "routing_trace": routing_trace,
                **_none_meta,  # orchestrator exception: no tool ran → all 14 keys are None
            }
            if context_meta is not None:
                result["context_meta"] = context_meta
            _telemetry.record(routing_trace)  # M5 telemetry (orchestrator exception -> unsupported)
            return result

        routing_trace["orchestrator_outcome"] = orch_result.outcome

        # i116: Jev shadow. Off unless FPL_JEV_MODE=shadow; when off nothing
        # below runs and jev_router is never imported. When on it runs in a
        # daemon thread over the text the orchestrator just answered, writes
        # its own log, and never touches this turn's result.
        if os.environ.get("FPL_JEV_MODE", "").strip().lower() == "shadow":
            from .jev_router import shadow as _jev_shadow  # noqa: PLC0415

            _turn_id = _jev_shadow.new_turn_id()
            routing_trace[_jev_shadow.TURN_ID_TRACE_KEY] = _turn_id
            _jev_shadow.start(
                turn_id=_turn_id,
                question=cleaned_text,
                bootstrap=actual_bootstrap,
                provider=_provider,
                model=_model,
                api_key=orch_api_key,
                served_tool_sequence=[
                    e.get("name") for e in (orch_result.tool_calls_trace or ())
                    if isinstance(e, dict) and e.get("name")
                ],
            )

        # i131 rule 3: the orchestrator's outcome is the status of its slot,
        # executed[0]. A turn opened by a context call that came back non-ok
        # (get_my_squad -> no_team_connected, no linked team) reports
        # tool_result_error even when the tool that answers the question ran
        # ok afterwards -- and used to land in the unsupported branch below:
        # no selected_tool, no card, for a chip answer that was grounded. Such
        # a turn is grounded when composed_primary_call hands the slot to a
        # call whose own status is "ok" (the trace's ``success`` flag is not
        # enough: ambiguous / not_found / no_team_connected all count as
        # success there). A non-ok owner (e.g. an ambiguous snapshot, i60)
        # still falls through to the branch below, unchanged.
        from .final_response import composed_primary_call  # noqa: PLC0415
        _composed_call = composed_primary_call(orch_result.tool_calls_trace)
        _primary_call = _plan_call_owner(orch_result.tool_calls_trace) or _composed_call
        _owner_status = ((_primary_call or {}).get("output") or {}).get("status")
        _owner_rescues_turn = (
            orch_result.outcome == ORCH_OUTCOME_TOOL_RESULT_ERROR and _owner_status == "ok"
        )
        if (orch_result.outcome == ORCH_OUTCOME_OK or _owner_rescues_turn) and orch_result.tool_chosen:
            # Successful tool call — grounded answer.
            routing_trace["branch"]                  = "orchestrator"
            routing_trace["orchestrator_tool_calls"] = [orch_result.tool_chosen]
            routing_trace["grounded"]                = True
            # G3: orchestrator_tool_calls above is still first-tool-only (known,
            # documented debt -- not touched here to keep this commit behaviour-
            # neutral). These two DO carry the real turn shape:
            routing_trace["tool_call_count"]         = orch_result.tool_call_count
            routing_trace["synthesis_turn"]          = orch_result.synthesis_turn
            # i80: retry_attempted / evaluator_verdict / tool_sequence, straight
            # off the result. _orch_tool_names is the executed sequence the i58
            # card gate below reads -- one derivation, two consumers.
            _orch_tool_names = _project_orchestrator_run(routing_trace, orch_result)
            # i93: a composed turn (get_fixture_outlook + get_team_snapshot in
            # one round) keeps the CALENDAR call as its singular slot --
            # selected_tool, tool_input, raw_output and the intent the UI
            # renders -- whatever order the model emitted the two tool_use
            # blocks in. The orchestrator's own slot is executed[0], i.e. the
            # model's order; snapshot-first would silently drop the card. Read
            # off tool_calls_trace, the same field the i58 gate reads; None
            # for every non-composed turn, so nothing else changes. i131: the
            # same helper hands the slot to the answering tool when a
            # gameweek-anchor call (get_current_gameweek) opened the turn, or
            # (rule 3) a get_my_squad call did. _primary_call is computed above.
            if _composed_call is not None:
                routing_trace["composed_primary_tool"] = _composed_call["name"]
            _orch_tool = _primary_call["name"] if _primary_call else orch_result.tool_chosen
            _orch_args = dict(_primary_call.get("args") or {}) if _primary_call else dict(orch_result.tool_args)
            _orch_raw = dict(_primary_call.get("output") or {}) if _primary_call else dict(orch_result.tool_output)
            # get_player_snapshot's own status (ok/ambiguous/not_found/error)
            # must not be flattened to "ok" just because the orchestrator
            # call itself succeeded -- otherwise an ambiguous match reports
            # as a successful answer and the frontend has no signal to arm
            # a disambiguation wizard. Scoped to this one tool deliberately:
            # every other orch-only tool still gets the historical "ok"
            # hardcode below (unaudited whether they rely on it -- see the
            # PR description for the follow-up this intentionally excludes).
            _orch_outcome = (
                _outcome_from_status(_orch_raw)
                if _orch_tool in STATUS_BEARING_TOOLS
                else "ok"
            )
            _orch_meta = _meta(_orch_tool, _orch_raw)  # orchestrator: grounded tool ran
            # Structured card for open-ended atomic-tool answers (e.g.
            # rank_players_by_metric): compose a GenericCardMeta from the tool
            # output so the UI renders a card alongside the prose. Guarded to
            # turns that ran a SINGLE DISTINCT tool — a multi-tool synthesis'
            # answer_text covers tools not reflected in tool_output, so carding
            # it would present a card that does not cover the answer. i58: the
            # guard reads the executed tool sequence (tool_calls_trace, the same
            # field the routing JSONL projects as tool_sequence), not the call
            # counter — the i46 extra round calls the same tool again and left
            # those rescued turns (count 2, one tool) without a card.
            from .atomic_tool_cards import (
                is_single_distinct_tool_turn,
                maybe_atomic_tool_card,
            )
            _single_tool_turn = is_single_distinct_tool_turn(
                orch_result.tool_chosen,
                orch_result.tool_call_count,
                _orch_tool_names,
            )
            # A plan_to_sign call that ran ok owns the slot whatever else ran around it (get_my_squad first or
            # again on the retry), so its card is the turn's card.
            _plan_owns = _orch_tool == "plan_to_sign" and _orch_raw.get("stage") == "plan"
            if (_single_tool_turn or _plan_owns) and _orch_meta.get("generic_card") is None:
                _overlay = maybe_atomic_tool_card(_orch_tool if _plan_owns else orch_result.tool_chosen, _orch_raw, None, locale)
                if _overlay is not None:
                    _orch_meta["generic_card"] = _overlay  # dataclass; _to_dict serializes downstream
            # The cited sources of a search_web call that ran this turn (alone or beside
            # another tool): they reach the UI as titled links, so the prose carries none.
            from .search_web import (  # noqa: PLC0415
                strip_urls_from_prose,
                web_search_sources_from_trace,
            )
            _web_sources = web_search_sources_from_trace(
                getattr(orch_result, "tool_calls_trace", None)
            )
            result = {
                "selected_tool": _orch_tool,
                "tool_input":    _orch_args,
                "raw_output":    _orch_raw,
                "answer_text":   (
                    strip_urls_from_prose(orch_result.answer_text)
                    if _web_sources is not None else orch_result.answer_text
                ),
                "web_search_sources": _web_sources,
                "outcome":       _orch_outcome,
                "kind":          "text",
                # The table's verdict: only alongside the ranking card it talks
                # about (same single-tool gate), None unless a rule fires.
                "table_conclusions": (
                    _tool_table_conclusions(_orch_tool, _orch_raw, actual_bootstrap)
                    if _orch_meta.get("generic_card") is not None else None
                ),
                # i105: orchestrator_provider / orchestrator_model, what the
                # orchestrator ran with, for the audit line and debug bundle.
                **_project_orchestrator_identity(orch_result),
                # i106: guard reason + blocked text, for the audit line only.
                **_project_final_text_guard(orch_result),
                # i127: did the model write the text served (not "which branch").
                "llm_used":      _project_llm_used(orch_result),
                "routing_trace": routing_trace,
                # i96: every executed call (primary + retry), for the audit line.
                "tool_calls_trace": _project_tool_calls_trace(orch_result),
                # F3: expose token observability so P3 quota meter can read them.
                "tokens": {
                    "primary_input":    orch_result.primary_input_tokens,
                    "primary_output":   orch_result.primary_output_tokens,
                    "primary_cache_read": orch_result.primary_cache_read_tokens,
                    "evaluator":        orch_result.evaluator_input_tokens,
                    "retry_input":      orch_result.retry_input_tokens,
                    "retry_output":     orch_result.retry_output_tokens,
                    "retry_cache_read": orch_result.retry_cache_read_tokens,
                    "total":            orch_result.total_tokens,
                },
                **_orch_meta,
            }
            _chips = _ambiguity_suggestions(orch_result.tool_chosen, _orch_raw, cleaned_text, actual_bootstrap, locale)
            if _chips is None:
                _chips = _plan_to_sign_chips(_orch_tool, _orch_raw, locale)
            if _chips is None:
                _chips = _league_pick_chips(orch_result.tool_chosen, _orch_raw, locale)
            if _chips is None:
                _chips = _eo_switch_chips(_orch_tool, _orch_raw, locale)
            if _chips is not None:
                result["player_suggestions"] = _chips
            from .eo_poll import pending_marker as _pending_marker  # noqa: PLC0415

            _pending = _pending_marker(_orch_tool, _orch_raw)
            if _pending is not None:
                result["pending"] = _pending  # the UI polls POST /eo/poll for it (no model)
            if orch_result.tool_chosen in {
                "get_expected_minutes",
                "get_tactical_role",
                "get_fixture_context",
                "get_player_intelligence",
            }:
                result["evidence"] = _orch_raw.get("evidence")
            if _orch_tool == "plan_to_sign" and _orch_raw.get("plan_state") is not None:
                result["plan_state"] = _orch_raw["plan_state"]  # the UI sends it back on the next turn
            _copy_existing_intent_evidence(result)
            if context_meta is not None:
                result["context_meta"] = context_meta
            _telemetry.record(routing_trace)  # M5 telemetry (orchestrator grounded)
            return result

        # Orchestrator returned without a usable tool call. Per plan §M3:
        # "orchestrator answer without tool call -> grounded=false" and the
        # deterministic fallback (unsupported + suggestions) is shown.
        routing_trace["branch"]   = "unsupported"
        routing_trace["grounded"] = False
        # G3: these carry the real turn shape regardless of whether a tool was
        # named -- this branch is exactly where a single-tool bare render()
        # used to be indistinguishable from a genuine no-tool-call turn.
        routing_trace["tool_call_count"] = orch_result.tool_call_count
        routing_trace["synthesis_turn"]  = orch_result.synthesis_turn
        _project_orchestrator_run(routing_trace, orch_result)  # i80: same three keys
        if orch_result.tool_chosen:
            # Outcomes UNKNOWN_TOOL / TOOL_ERROR / TOOL_RESULT_ERROR — a tool
            # was named but execution did not yield ok. Record the attempt
            # for observability even though grounded stays False.
            routing_trace["orchestrator_tool_calls"] = [orch_result.tool_chosen]
        result = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    {"status": "unsupported", "code": "orchestrator_no_grounded_tool"},
            "answer_text":   orch_result.answer_text or _unrecognised_message(locale),
            "outcome":       "unsupported",
            "kind":          "text",
            "suggestions":   [f"@{r}" for r in _suggestions_for_text()],
            "orchestrator_outcome": orch_result.outcome,
            # i105: an LLM that picked no grounded tool was still an LLM that
            # ran and billed; the audit line prices it by this model.
            **_project_orchestrator_identity(orch_result),
            **_project_final_text_guard(orch_result),  # i106
            # i127: the orchestrator ran here too; the stamp reads what wrote
            # the text, not the branch (was always False on this branch).
            "llm_used": _project_llm_used(orch_result),
            # i96: this is the branch where a retry that ran a tool with a
            # non-ok status lands with selected_tool=None; the calls it
            # executed are still real and still audited.
            "tool_calls_trace": _project_tool_calls_trace(orch_result),
            "tokens": {
                "primary_input": orch_result.primary_input_tokens,
                "primary_output": orch_result.primary_output_tokens,
                "primary_cache_read": orch_result.primary_cache_read_tokens,
                "evaluator": orch_result.evaluator_input_tokens,
                "retry_input": orch_result.retry_input_tokens,
                "retry_output": orch_result.retry_output_tokens,
                "retry_cache_read": orch_result.retry_cache_read_tokens,
                "total": orch_result.total_tokens,
            },
            "routing_trace": routing_trace,
            **_none_meta,  # orchestrator no-grounded-tool: tool execution failed → all 14 keys None
        }
        # i60: an ambiguous player is not "ok", so the orchestrator reports
        # tool_result_error and the turn lands HERE, never in the grounded
        # branch above -- the chips armed there were unreachable for the very
        # case they exist for. Read the ambiguity off the executed calls (the
        # trace, not tool_chosen: a retry may have overwritten that slot) and
        # report the intent the UI arms on (ChatShell WIZARD_ARMING_INTENTS).
        _amb_call = _last_ambiguous_chip_call(orch_result.tool_calls_trace)
        if _amb_call is not None:
            _amb_chips = _ambiguity_suggestions(_amb_call["name"], _amb_call.get("output") or {}, cleaned_text, actual_bootstrap, locale)
            if _amb_chips is not None:
                result["outcome"] = "ambiguous"
                result["intent"] = _TOOL_TO_INTENT.get(_amb_call["name"], result.get("intent"))
                result["player_suggestions"] = _amb_chips
        # A ``computing`` EO answer is not "ok", so it lands HERE, never in the grounded branch: the marker the
        # UI polls on must be read off the executed calls too (same shape as the i60 ambiguity chips above).
        _computing_call = _last_computing_poll_call(orch_result.tool_calls_trace)
        if _computing_call is not None:
            from .eo_poll import pending_marker as _pending_marker  # noqa: PLC0415

            _pending = _pending_marker(_computing_call["name"], _computing_call.get("output") or {})
            if _pending is not None:
                result["pending"] = _pending
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)  # M5 telemetry (orchestrator no grounded tool -> unsupported)
        return result

    # --- Step 2 (P1.a): unsupported (orchestrator unreachable or disabled). ---
    # ask_v2() uses "unsupported" here; harness_adapter.py maps it to
    # "unsupported_intent" on the HTTP surface to match dispatcher semantics.
    routing_trace["branch"] = "unsupported"
    result = {
        "selected_tool": None,
        "tool_input":    {},
        "raw_output":    {"status": "unsupported", "code": "unrecognised_query"},
        "answer_text":   _unrecognised_message(locale),
        "outcome":       "unsupported",
        "kind":          "text",
        "suggestions":   [f"@{r}" for r in _suggestions_for_text()],
        "routing_trace": routing_trace,
        **_none_meta,  # step 4: full ladder miss → all 14 keys are None
    }
    if context_meta is not None:
        result["context_meta"] = context_meta
    _telemetry.record(routing_trace)  # M5 telemetry (step 2 P1.a: orchestrator disabled / unreachable)
    return result


def _suggestions_for_text() -> list[str]:
    """Return curated resource suggestions for the M3 text-unsupported path."""
    from .intent_aliases import list_resources
    return list(list_resources())


def _plan_call_owner(tool_calls_trace: Any) -> dict[str, Any] | None:
    """The executed plan_to_sign call that owns the turn's slot, or ``None``.

    The plan call owns it whenever one ran ok, even when ``get_my_squad`` opened or closed the turn (the model
    reads the squad around it, and a retry may read it again). Of several ok plan calls the last one that carries
    the user's chosen moves (stage ``plan``) wins, so a retry that forgot ``moves`` (and so only came back with
    the choose-moves step) does not replace the plan the user asked for.
    """
    calls = [
        e for e in tuple(tool_calls_trace or ())
        if isinstance(e, dict) and e.get("name") == "plan_to_sign" and (e.get("output") or {}).get("status") == "ok"
    ]
    if not calls:
        return None
    planned = [e for e in calls if (e.get("output") or {}).get("stage") == "plan"]
    return (planned or calls)[-1]


def _plan_to_sign_chips(
    tool_name: str | None, raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE,
) -> list[dict[str, Any]] | None:
    """The chips of plan_to_sign, or ``None``.

    ``choose_moves``: the tool owns the options and their wording (``move_options``); this only turns them into
    self-contained prompt-rewrite chips. ``plan``: one chip per option other than the one the card is about
    (``plan_card.option_chips``); the tap sends the chip's own label ("Option N: A → B" / «Opción N: A → B»), which the follow-up path
    answers without a model.
    """
    if tool_name != "plan_to_sign":
        return None
    from .suggestions import KIND_PLAN_OPTION, Suggestion, suggestions_to_list  # noqa: PLC0415

    if raw_output.get("stage") == "plan":
        from .plan_card import option_chips  # noqa: PLC0415

        return suggestions_to_list(tuple(
            Suggestion(label=c["label"], send_text=c["send_text"], kind=KIND_PLAN_OPTION)
            for c in option_chips(raw_output, locale)
        ) or None)
    if raw_output.get("stage") != "choose_moves":
        return None
    return suggestions_to_list(tuple(
        Suggestion(label=str(o["label"]), send_text=str(o["send_text"]), kind=KIND_PLAN_OPTION)
        for o in raw_output.get("move_options") or []
        if o.get("label") and o.get("send_text")
    ) or None)


def _league_pick_chips(tool_name: str | None, raw_output: dict[str, Any], locale: Locale) -> list[dict[str, Any]] | None:
    """The "which league?" chips of get_league_eo, or ``None``.

    One chip per private league of the user, labelled with its name; the tap re-asks the question
    with that league named and the UI stores the id as the main league (see ``Suggestion``).
    """
    if tool_name != "get_league_eo" or raw_output.get("stage") != "needs_league":
        return None
    from .catalogue import t  # noqa: PLC0415
    from .suggestions import KIND_LEAGUE_PICK, Suggestion, suggestions_to_list  # noqa: PLC0415

    return suggestions_to_list(tuple(
        Suggestion(label=str(lg["name"]), send_text=t("league_eo.chip_question", locale, league=str(lg["name"])),
                   kind=KIND_LEAGUE_PICK, league_id=int(lg["league_id"]))
        for lg in raw_output.get("leagues") or []
        if lg.get("name") and lg.get("league_id")
    ) or None)


def _eo_switch_chips(tool_name: str | None, raw_output: dict[str, Any], locale: Locale) -> list[dict[str, Any]] | None:
    """The one chip under an EO card that switches to the other view, or ``None``.

    Under the league card: "EO near your rank". Under the near-rank card: "EO in <main league>", only when
    the user's main league is known. Plain verbatim questions (they still go through the model).
    """
    if raw_output.get("status") != "ok" or raw_output.get("stage"):
        return None
    from .catalogue import t  # noqa: PLC0415
    from .suggestions import KIND_EO_SWITCH, Suggestion, suggestions_to_list  # noqa: PLC0415

    from .orch_config import is_tier_eo_enabled  # noqa: PLC0415

    texts: list[str] = []
    if tool_name == "get_league_eo" and raw_output.get("tier") == "league":
        texts.append(t("near_eo.title", locale))
    elif tool_name == "get_near_rank_eo" and raw_output.get("tier") == "near":
        name = (raw_output.get("main_league") or {}).get("name")
        if name:
            texts.append(t("league_eo.chip_question", locale, league=str(name)))
    elif tool_name == "get_tier_eo" and raw_output.get("tier") == "top10k":
        texts.append(t("near_eo.title", locale))
    if tool_name in {"get_league_eo", "get_near_rank_eo"} and is_tier_eo_enabled():
        texts.append(t("tier_eo.title", locale))  # read from the published file: only offered when the reader is on
    if tool_name == "get_league_eo" and raw_output.get("tier") == "league" and raw_output.get("other_leagues"):
        texts.append(t("league_eo.change_chip", locale))  # only with 2+ readable leagues (the cached list)
    if not texts:
        return None
    return suggestions_to_list(tuple(Suggestion(label=x, send_text=x, kind=KIND_EO_SWITCH) for x in texts))


def _ambiguity_suggestions(
    tool_name: str | None,
    raw_output: dict[str, Any],
    question: str | None = None,
    bootstrap: dict[str, Any] | None = None,
    locale: Locale = DEFAULT_LOCALE,
) -> list[dict[str, Any]] | None:
    """i60: the pick-one chips for an ambiguous player tool, or ``None``.

    One builder for both orchestrator branches. Current-season tools
    (WIZARD_ARMING_TOOLS) carry a stable ``player_id``; past-season points
    carry a canonical question and never an id -- historical ids do not cross
    seasons.
    """
    if raw_output.get("status") != "ambiguous":
        return None
    from .suggestions import (  # noqa: PLC0415
        historical_player_suggestions,
        player_disambiguation_suggestions,
        suggestions_to_list,
    )
    if tool_name in RESUME_QUESTION_TOOLS:
        from .suggestions import question_resume_suggestions  # noqa: PLC0415

        rewrites = suggestions_to_list(
            question_resume_suggestions(
                raw_output.get("candidates", []), str(raw_output.get("query") or ""), question, bootstrap,
            )
        ) if question else None
        if rewrites is None and tool_name == "plan_to_sign":
            # An ambiguous target must always arm a picker with its candidates, never an empty one: when the
            # user's wording cannot be re-asked, ask the plain question about each candidate.
            from .plan_card import target_pick_suggestions  # noqa: PLC0415

            return suggestions_to_list(target_pick_suggestions(raw_output.get("candidates", []), locale))
        return rewrites
    if tool_name in WIZARD_ARMING_TOOLS:
        # A question that says more than the name ("compara a Palmer y Saka") must not be
        # answered with the generic card: re-ask it per candidate. A bare name keeps the
        # deterministic, cheaper stable-id handoff; a failed rewrite falls back to it too.
        from .suggestions import (  # noqa: PLC0415
            question_is_only_the_name,
            question_resume_suggestions,
        )

        mention = str(raw_output.get("query") or "")
        if question and mention and not question_is_only_the_name(question, mention):
            rewrites = suggestions_to_list(
                question_resume_suggestions(raw_output.get("candidates", []), mention, question, bootstrap)
            )
            if rewrites is not None:
                return rewrites
        return suggestions_to_list(
            player_disambiguation_suggestions(raw_output.get("candidates", []))
        )
    if tool_name == "get_player_season_points":
        return suggestions_to_list(
            historical_player_suggestions(
                raw_output.get("candidates", []),
                str(raw_output.get("season") or ""),
            )
        )
    return None


def _last_ambiguous_chip_call(tool_calls_trace: Any) -> dict[str, Any] | None:
    """i60: the last executed call of a chip-arming tool that came back
    ``ambiguous``, read off ``tool_calls_trace`` (primary and retry calls)."""
    for _e in reversed(tuple(tool_calls_trace or ())):
        if (
            isinstance(_e, dict)
            and _e.get("name") in STATUS_BEARING_TOOLS
            and (_e.get("output") or {}).get("status") == "ambiguous"
        ):
            return _e
    return None


def _last_computing_poll_call(tool_calls_trace: Any) -> dict[str, Any] | None:
    """The last executed call of a pollable EO tool that came back ``computing`` (primary or retry)."""
    from .eo_poll import POLL_TOOLS  # noqa: PLC0415

    for _e in reversed(tuple(tool_calls_trace or ())):
        if (
            isinstance(_e, dict)
            and _e.get("name") in POLL_TOOLS
            and (_e.get("output") or {}).get("status") == "computing"
        ):
            return _e
    return None


def _project_orchestrator_run(routing_trace: dict[str, Any], orch_result: Any) -> list[str | None]:
    """i80: copy what the orchestrator run already produced onto ``routing_trace``.

    Nothing is computed here -- ``retry_attempted`` and ``evaluator_verdict``
    are ``OrchestratorResult`` fields set by ``_apply_evaluator`` (True /
    a verdict on every retry site), and ``tool_sequence`` is the executed
    tool-name list read off ``tool_calls_trace`` -- the SAME list the i58
    card gate consumes (returned so the caller reuses it rather than
    re-deriving it). The verdict is projected in the shape ``audit.AuditEntry``
    declares for ``evaluator_verdict`` so the audit line carries it verbatim.
    Called on both orchestrator branches (grounded and no-grounded-tool): a
    retry that still failed to ground is still a retry.
    """
    # getattr with defaults: this is observability, it must never turn a
    # returned result into a crash (the try/except above only wraps the call).
    _names: list[str | None] = [
        _e.get("name") for _e in (getattr(orch_result, "tool_calls_trace", None) or ())
    ]
    _verdict = getattr(orch_result, "evaluator_verdict", None)
    routing_trace["retry_attempted"] = bool(getattr(orch_result, "retry_attempted", False))
    # i125(b): what the rejected turn served, stamped at the return site.
    routing_trace["retry_delivery"] = getattr(orch_result, "retry_delivery", None)
    routing_trace["evaluator_verdict"] = (
        None if _verdict is None else {
            "approved":       _verdict.approved,
            "grounded":       _verdict.grounded,
            "complete":       _verdict.complete,
            "safe":           _verdict.safe,
            "retry_feedback": _verdict.retry_feedback,
            # i124: set only when the verdict is a fail-open (approved, unjudged).
            "fail_open_reason": getattr(_verdict, "fail_open_reason", None),
        }
    )
    routing_trace["tool_sequence"] = [_n for _n in _names if _n]
    # Did search_web actually run (vs merely offered)? Read off the same trace.
    routing_trace["search_web_ran"] = "search_web" in routing_trace["tool_sequence"]
    # i93-b: the args each executed call carried, parallel to tool_sequence
    # (same filter). Read off the trace like the names; nothing derived.
    routing_trace["tool_args_sequence"] = [
        dict(_e.get("args") or {})
        for _e in (getattr(orch_result, "tool_calls_trace", None) or ())
        if _e.get("name")
    ]
    return _names


def _project_orchestrator_identity(orch_result: Any) -> dict[str, str | None]:
    """i105: ``{"orchestrator_provider", "orchestrator_model"}`` read off the
    result -- the provider label ``ask_orchestrated`` stamped and the model it
    called with -- both ``None`` when no provider call succeeded (``llm_used``
    False: the result's ``model`` is then the ``"none"`` sentinel, which must
    not reach the audit line as a model id). Projected on both orchestrator
    branches (grounded and no-grounded-tool): an LLM that picked no grounded
    tool still ran and billed. The audit prices the turn by
    ``orchestrator_model``; ``DEFAULT_PROVIDER`` (a presentation env var) is
    never consulted.
    """
    if not bool(getattr(orch_result, "llm_used", False)):
        return {"orchestrator_provider": None, "orchestrator_model": None}
    _model = getattr(orch_result, "model", None)
    return {
        "orchestrator_provider": getattr(orch_result, "provider", None),
        "orchestrator_model":    None if _model in (None, "", "none") else str(_model),
    }


def _project_llm_used(orch_result: Any) -> bool:
    """i127: ``llm_used`` on both orchestrator branches -- True iff the text
    this turn serves was written by the model.

    Same meaning ``final_response`` documents for the field ("is final_text
    LLM-generated (and accepted)"), read off what ran: the served text is
    the model's own (``synthesis_turn``, False for a ``render()`` / static
    string -- and only ever True when a provider call returned that text, so
    it implies the result's own ``llm_used``), and the final-text guard did
    not replace it with its own sentence. Not "which branch": the
    no-grounded-tool branch runs the same LLM and used to stamp every such
    turn "Determinístico".
    """
    return (
        bool(getattr(orch_result, "synthesis_turn", False))
        and getattr(orch_result, "final_text_guard_reason", None) is None
    )


def _project_final_text_guard(orch_result: Any) -> dict[str, str | None]:
    """i106: ``{"final_text_guard_reason", "guarded_raw_answer_text"}`` read
    off the result. Both ``None`` on a clean turn. Internal dict keys only:
    they feed the audit line (both HTTP surfaces) and never an HTTP contract
    -- ``AskResponse``/``SessionAskResponse`` do not carry them.
    """
    return {
        "final_text_guard_reason": getattr(orch_result, "final_text_guard_reason", None),
        "guarded_raw_answer_text": getattr(orch_result, "guarded_raw_answer_text", None),
    }


def _project_tool_calls_trace(orch_result: Any) -> list[dict[str, Any]]:
    """i96: the executed calls, one compact record each, for the audit line.

    Read off ``OrchestratorResult.tool_calls_trace`` -- primary rounds AND the
    evaluator retry's own calls (``retry=True`` entries) -- and reduced to
    what ``audit.AuditEntry.tool_calls`` documents plus ``round``/``retry``.
    The full output stays out (it can be hundreds of KB); the status is what
    an audit reader needs. Returned on BOTH orchestrator branches, so a turn
    whose retry ran a tool that did not come back ``ok`` (harness branch
    "no grounded tool", ``selected_tool=None``) still audits every call it
    executed instead of ``tool_calls=[]``.
    """
    out: list[dict[str, Any]] = []
    for _e in (getattr(orch_result, "tool_calls_trace", None) or ()):
        if not isinstance(_e, dict) or not _e.get("name"):
            continue
        out.append({
            "name":          _e["name"],
            "args":          dict(_e.get("args") or {}),
            "output_status": str((_e.get("output") or {}).get("status") or "unknown"),
            "round":         _e.get("round"),
            "retry":         bool(_e.get("retry", False)),
        })
    return out
