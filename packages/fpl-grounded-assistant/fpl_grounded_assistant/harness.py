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

from typing import Any

from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.router import route
from fpl_tool_runner import run_tool

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
) -> dict[str, Any]:
    """Phase M1 entrypoint composing `decision_router` + existing `ask()`.

    Behavior summary:

    * `@<resource>`  -> resource path; result dict carries `outcome="ok"`,
                        `resource_rows={...}`, and `routing_trace`.
    * `@<unknown>`   -> `outcome="unsupported"`, `suggestions=[...]`.
    * `/<prompt>`    -> M1 returns `outcome="unsupported"` (M2 owns this).
    * plain text     -> falls through to existing `ask()`; the returned
                        dict is identical to today's `ask()` output plus
                        an additive `routing_trace` key.

    The existing `ask()` is **not modified**. This is purely additive and
    does not affect any caller of `ask()`.
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
    from .dispatcher import _auto_candidates_from_bootstrap

    # Resolve bootstrap up-front so both branches operate on the same data
    actual_bootstrap, context_meta = _resolve_bootstrap_and_meta(bootstrap)

    decision = decide(question, actual_bootstrap)
    kind = decision["kind"]
    outcome = decision["outcome"]

    routing_trace = {
        "decision_kind": kind,
        "decision_outcome": outcome,
    }

    if outcome == OUTCOME_OK_RESOURCE and kind == "resource":
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
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        return result

    if outcome == OUTCOME_NEEDS_CLARIFICATION:
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
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
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
        routing_trace["expansion_text"] = canonical_text
        routing_trace["workflow_intent"] = workflow_intent
        result["routing_trace"] = routing_trace
        return result

    if outcome == OUTCOME_OK_PROMPT_DISPATCH:
        prompt_name     = decision.get("prompt_name")
        workflow_intent = decision.get("workflow_intent")
        args            = decision.get("args", {})
        tool_name, raw_output, tool_input = _dispatch_prompt(
            prompt_name, args, actual_bootstrap,
        )
        answer_text = _render(tool_name, raw_output) if tool_name else ""
        routing_trace["dispatched_tool"] = tool_name
        routing_trace["workflow_intent"] = workflow_intent
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
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        return result

    if outcome == OUTCOME_UNSUPPORTED:
        result = {
            "selected_tool": None,
            "tool_input":    {},
            "raw_output":    {"status": "unsupported"},
            "answer_text":   decision.get("message", ""),
            "outcome":       "unsupported",
            "kind":          kind,
            "suggestions":   decision.get("suggestions", []),
            "routing_trace": routing_trace,
        }
        if context_meta is not None:
            result["context_meta"] = context_meta
        return result

    # Fallthrough (plain text) — delegate to existing ask()
    assert outcome == OUTCOME_FALLTHROUGH
    # Use the cleaned text (post-honorific-strip / NFC) for routing.
    cleaned_text = decision.get("text", question)
    result = ask(
        cleaned_text,
        bootstrap,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
    )
    result["outcome"] = "ok" if result.get("selected_tool") else "unsupported"
    result["kind"] = "text"
    result["routing_trace"] = routing_trace
    return result