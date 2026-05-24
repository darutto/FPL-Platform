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

from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.router import route
from fpl_tool_runner import run_tool

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
})

ROUTING_TRACE_OPTIONAL_KEYS: frozenset[str] = frozenset({
    "expansion_text",       # prompt-expansion branch: canonical text produced
    "workflow_intent",      # prompt branches: prompt_registry workflow intent label
    "dispatched_tool",      # prompt-dispatch branch: tool name invoked
    "classification_source",  # classifier_rewrite branch: "llm_classifier"
    "orchestrator_error",   # orchestrator-exception path: exception message string
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


# ---------------------------------------------------------------------------
# Public harness entry point
# ---------------------------------------------------------------------------

def ask(
    question: str,
    bootstrap: dict[str, Any],
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
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

    # ------------------------------------------------------------------
    # 2. Route question
    # ------------------------------------------------------------------
    route_result = route(question)

    if route_result is None:
        result = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    _UNRECOGNISED,
            "answer_text":   _UNRECOGNISED["message"],
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

    answer_text = render(route_result.tool_name, raw_output)

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
) -> dict[str, Any]:
    """Phase M1/M2/M3 entrypoint composing `decision_router` + existing `ask()`.

    Behavior summary:

    * `@<resource>`  -> resource path; result dict carries `outcome="ok"`,
                        `resource_rows={...}`, and `routing_trace`.
    * `@<unknown>`   -> `outcome="unsupported"`, `suggestions=[...]`.
    * `/<prompt>`    -> M2: prompt registry dispatch / expansion.
    * plain text     -> P1.a orchestrator-primary routing:
                         1. ask_orchestrated()             — LLM-primary (P1.a)
                         2. unsupported + suggestions

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
        }

    Optional keys (present only on specific branches)::

        "expansion_text"       (str)   prompt-expansion branch: canonical text produced
        "workflow_intent"      (str)   prompt branches: prompt_registry workflow intent
        "dispatched_tool"      (str)   prompt-dispatch branch: tool name invoked
        "classification_source" (str)  classifier_rewrite branch: "llm_classifier"
        "orchestrator_error"   (str)   orchestrator-exception path: exception message

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
        "orchestrator"       — plain text; orchestrator returned a grounded
                               tool call (P1.a primary path).
        "unsupported"        — no path produced a grounded answer.

        [P1.a: "route" and "classifier_rewrite" no longer fire for plain text
        from ask_v2().  They remain in harness_adapter.py as legacy branches
        (defensive) in case synthetic dicts or session paths produce them.]

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
    from .orch_config import is_orch_enabled, get_orch_provider
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
        return _extract_structured_meta(intent, raw_output, outcome)

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

    decision = decide(question, actual_bootstrap)
    kind = decision["kind"]
    outcome = decision["outcome"]

    _orch_enabled = is_orch_enabled()

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
        "feature_flag_orch_enabled": _orch_enabled,
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
            "routing_trace": routing_trace,
            **_none_meta,  # resource branch: no deterministic tool ran → all 14 keys are None
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    if outcome == OUTCOME_NEEDS_CLARIFICATION:
        routing_trace["branch"] = "prompt"
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
        )
        result["outcome"] = "ok" if result.get("selected_tool") else "unsupported"
        result["kind"] = "prompt"
        result["prompt_name"] = prompt_name
        result["workflow_intent"] = workflow_intent
        result["canonical_text"] = canonical_text
        routing_trace["branch"]            = "prompt"
        routing_trace["expansion_text"]    = canonical_text
        routing_trace["workflow_intent"]   = workflow_intent
        routing_trace["router_hit"]        = result.get("selected_tool") is not None
        routing_trace["grounded"]          = result.get("selected_tool") is not None
        result["routing_trace"] = routing_trace
        # prompt-expansion branch: extract metadata when tool ran, else all-None
        result.update(_meta(result.get("selected_tool"), result.get("raw_output", {})))
        _telemetry.record(routing_trace)  # M5 telemetry
        return result

    if outcome == OUTCOME_OK_PROMPT_DISPATCH:
        prompt_name     = decision.get("prompt_name")
        workflow_intent = decision.get("workflow_intent")
        args            = decision.get("args", {})
        tool_name, raw_output, tool_input = _dispatch_prompt(
            prompt_name, args, actual_bootstrap,
        )
        answer_text = _render(tool_name, raw_output) if tool_name else ""
        routing_trace["branch"]          = "prompt"
        routing_trace["dispatched_tool"] = tool_name
        routing_trace["workflow_intent"] = workflow_intent
        routing_trace["grounded"]        = tool_name is not None and raw_output.get("status") == "ok"
        result = {
            "selected_tool":   tool_name,
            "tool_input":      tool_input,
            "raw_output":      raw_output,
            "answer_text":     answer_text,
            "outcome":         "ok" if raw_output.get("status") == "ok" else "error",
            "kind":            "prompt",
            "prompt_name":     prompt_name,
            "workflow_intent": workflow_intent,
            "routing_trace":   routing_trace,
            **_meta(tool_name, raw_output),  # prompt-dispatch: real tool ran, extract metadata
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
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
    # P1.a text-branch: orchestrator-primary routing
    # ------------------------------------------------------------------
    # Post-P1.a, plain-text questions go DIRECTLY to ask_orchestrated().
    # Steps 1 (route() first-try) and 2 (classifier_rewrite) have been
    # REMOVED from the plain-text path.  The orchestrator MAY call route()
    # internally as one of its tools (it is a fine deterministic resolver),
    # but route() is no longer the gatekeeper.
    #
    # Ladder summary (P1.a):
    #   1. ask_orchestrated()  — LLM-primary; gated by FPL_ORCH_ENABLED
    #   2. unsupported + suggestions  — when orchestrator disabled/unavailable
    #
    # Legacy: classifier_client kwarg is no longer consulted for plain-text
    # routing.  The parameter is kept for backwards-compat call-sites but
    # has NO effect on the plain-text path post-P1.a.
    assert outcome == OUTCOME_FALLTHROUGH
    cleaned_text = decision.get("text", question)

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
        )
        routing_trace["orchestrator_called"] = True
        _provider = orch_provider if orch_provider is not None else get_orch_provider()
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
                _eval_client=_eval_client,
            )
        except Exception as exc:  # noqa: BLE001  — defensive; ask_orchestrated never raises
            routing_trace["branch"]                  = "unsupported"
            routing_trace["orchestrator_outcome"]    = "exception"
            routing_trace["grounded"]                = False
            result = {
                "selected_tool": None,
                "tool_input":    {},
                "raw_output":    {"status": "unsupported", "code": "orchestrator_exception"},
                "answer_text":   _UNRECOGNISED["message"],
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

        if orch_result.outcome == ORCH_OUTCOME_OK and orch_result.tool_chosen:
            # Successful tool call — grounded answer.
            routing_trace["branch"]                  = "orchestrator"
            routing_trace["orchestrator_tool_calls"] = [orch_result.tool_chosen]
            routing_trace["grounded"]                = True
            _orch_raw = dict(orch_result.tool_output)
            result = {
                "selected_tool": orch_result.tool_chosen,
                "tool_input":    dict(orch_result.tool_args),
                "raw_output":    _orch_raw,
                "answer_text":   orch_result.answer_text,
                # Intentional "ok": this branch only fires when orch_result.outcome == ORCH_OUTCOME_OK.
                "outcome":       "ok",
                "kind":          "text",
                "orchestrator_model": orch_result.model,
                "routing_trace": routing_trace,
                # F3: expose token observability so P3 quota meter can read them.
                "tokens": {
                    "primary_input":    orch_result.primary_input_tokens,
                    "primary_output":   orch_result.primary_output_tokens,
                    "primary_cache_read": orch_result.primary_cache_read_tokens,
                    "evaluator":        orch_result.evaluator_input_tokens,
                    "retry_input":      orch_result.retry_input_tokens,
                    "retry_output":     orch_result.retry_output_tokens,
                    "total":            orch_result.total_tokens,
                },
                **_meta(orch_result.tool_chosen, _orch_raw),  # orchestrator: grounded tool ran
            }
            if context_meta is not None:
                result["context_meta"] = context_meta
            _telemetry.record(routing_trace)  # M5 telemetry (orchestrator grounded)
            return result

        # Orchestrator returned without a usable tool call. Per plan §M3:
        # "orchestrator answer without tool call -> grounded=false" and the
        # deterministic fallback (unsupported + suggestions) is shown.
        routing_trace["branch"]   = "unsupported"
        routing_trace["grounded"] = False
        if orch_result.tool_chosen:
            # Outcomes UNKNOWN_TOOL / TOOL_ERROR / TOOL_RESULT_ERROR — a tool
            # was named but execution did not yield ok. Record the attempt
            # for observability even though grounded stays False.
            routing_trace["orchestrator_tool_calls"] = [orch_result.tool_chosen]
        result = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    {"status": "unsupported", "code": "orchestrator_no_grounded_tool"},
            "answer_text":   orch_result.answer_text or _UNRECOGNISED["message"],
            "outcome":       "unsupported",
            "kind":          "text",
            "suggestions":   [f"@{r}" for r in _suggestions_for_text()],
            "orchestrator_outcome": orch_result.outcome,
            "routing_trace": routing_trace,
            **_none_meta,  # orchestrator no-grounded-tool: tool execution failed → all 14 keys None
        }
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
        "answer_text":   _UNRECOGNISED["message"],
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