"""
fpl_tool_contract.tools
========================
LLM-friendly tool wrappers over fpl-query-tools.

Every function returns a plain dict with a mandatory ``"status"`` key.
Status values are first-class — callers must not infer success from the
presence or absence of other keys.

Status vocabulary
-----------------
``"ok"``         Resolution succeeded; all answer fields are present.
``"ambiguous"``  Multiple players share the query string; the caller must
                 ask for clarification before answering.  Single-player tools
                 also return a ``candidates`` list of the tied players so the
                 caller can offer a pick-one wizard.
``"not_found"``  No player matched the query; the caller should say so.
``"error"``      Runner-level failure (unknown tool, missing required arg,
                 or invalid candidate_inputs).

Tool signatures accept a *bootstrap* dict directly (the raw response from
``fpl_api_client.get_bootstrap()``) rather than pre-split players/teams
lists.  This matches the natural boundary of an LLM tool call — the tool
receives one context object, not pre-processed slices.

Dependencies (all Tier A, parity-validated)
--------------------------------------------
fpl_api_client   — get_players, get_teams                   (Phase 1c)
fpl_player_registry — build_registry                        (Phase 1d)
fpl_query_tools  — get_player_summary,
                   get_current_gameweek_from_bootstrap       (Phase 1e)
fpl_captain_engine — calculate_captain_score                 (Phase 2b)

Phase 2a additions
------------------
- tool_get_captain_score: accepts query + bootstrap + candidate_inputs
  (form, fixture_difficulty, xgi_per_90, minutes_risk) and returns a
  structured captain score dict consistent with the tool contract style.

Phase 2b changes
----------------
- Removed inlined _calculate_captain_score; now imports calculate_captain_score
  from fpl_captain_engine (canonical formula — single source of truth).
- Added _validate_candidate_inputs() for structured, consistent error responses
  when required scoring fields are missing or invalid.
- Added tool_rank_captain_candidates(candidates, bootstrap): scores and ranks
  a list of captain candidates using the canonical engine formula; partial
  failures (ambiguous/not_found) are included at the end of the ranked list
  with their error status.

Still excludes
--------------
- LLM integration
- Live API calls
- Consumer app wiring
"""

from __future__ import annotations

from typing import Any

from fpl_api_client.fpl_client import get_players, get_teams
from fpl_captain_engine import (
    calculate_captain_score,
    classify_captain_tier,   # Phase 5m
    derive_role_signals,     # Phase 5m
)
from fpl_player_registry import resolve_player_candidates
from fpl_query_tools import get_current_gameweek_from_bootstrap, get_player_summary
from fpl_tool_contract.scoring_core import (
    _derive_base_scoring_inputs,
    bootstrap_for_captain_window,
    captain_pool_elements,
    captain_time_context,
    captain_window_needs_fixture_data,
    derive_minutes_context,
    missing_captain_fixture_notice,
)

DERIVED_CAPTAIN_POOL_LIMIT = 12

# ---------------------------------------------------------------------------
# Phase 5m: scoring input derivation helpers
# ---------------------------------------------------------------------------


def _derive_scoring_inputs_from_element(
    element: dict,
    bootstrap: dict,
) -> dict:
    """Derive captain scoring inputs from a raw FPL bootstrap element.

    Returns a dict with keys: form, xgi_per_90, minutes_risk,
    fixture_difficulty. Thin wrapper over the canonical, null-safe
    ``scoring_core._derive_base_scoring_inputs`` (the fixture_difficulty map
    ships present-but-null values at season launch, which the old inline
    ``int(fdr_map.get(team, 3))`` crashed on).
    """
    fdr_map = bootstrap.get("fixture_difficulty_map", {})
    return _derive_base_scoring_inputs(
        element, fdr_map, bootstrap.get("team_fixtures")
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: Position label by bootstrap ``element_type`` code.  Local to this module —
#: the canonical registry stores the raw code, and the tool contract is the
#: layer that owns the "GKP"/"DEF"/"MID"/"FWD" vocabulary.
_POSITION_BY_ELEMENT_TYPE: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

#: Cap on ambiguous candidates surfaced to the caller.  Matches
#: ``get_player_snapshot._MAX_AMBIGUOUS_CANDIDATES`` so both disambiguation
#: paths offer the same number of choices.
_MAX_AMBIGUOUS_CANDIDATES: int = 5


def _candidates_from_matches(matches: Any) -> list[dict[str, Any]]:
    """Build identity-only candidate dicts from canonical ``PlayerMatch`` records.

    Deliberately narrow: id / web_name / team_short / position / match_rank are
    everything a disambiguation chip needs.  The richer 31-field grounding
    payload built by ``find_players._build_match_dict`` lives downstream in
    fpl-grounded-assistant and must not be reached for from this leaf package.

    Ordering is the resolver's own (rank, then total_points desc, then id), so
    the same bootstrap always yields the same candidate order.
    """
    return [
        {
            "id":          match.record.id,
            "web_name":    match.record.web_name,
            "first_name":  match.record.first_name,
            "second_name": match.record.second_name,
            # Full name is what actually breaks the tie: two players sharing a
            # web_name ("Palmer") differ on their first name, so this is the
            # string a caller re-sends to resolve to exactly one of them.
            "name":        f"{match.record.first_name} {match.record.second_name}".strip(),
            "team_short":  match.record.team_short_name,
            "position":    _POSITION_BY_ELEMENT_TYPE.get(match.record.element_type, ""),
            "match_rank":  match.rank,
        }
        for match in matches[:_MAX_AMBIGUOUS_CANDIDATES]
    ]


def _resolve_with_status(
    query: str | int,
    bootstrap: dict[str, Any],
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    """Decompose bootstrap, resolve canonically, and call get_player_summary.

    Returns (status, summary_or_None, candidates) where status is one of
    "ok" | "ambiguous" | "not_found".

    The canonical resolver preserves ambiguity before the legacy summary
    adapter, which returns ``None`` for both ambiguous and not-found queries.

    ``candidates`` is populated on "ambiguous" only (empty list otherwise).
    The resolver already ranks every tied match, so carrying them out costs
    nothing and is what lets callers offer a disambiguation wizard instead of
    a dead-end "please clarify" sentence.
    """
    players = get_players(bootstrap)
    teams   = get_teams(bootstrap)

    resolution = resolve_player_candidates(
        query,
        players,
        teams,
        allow_prefix=True,
        allow_substring=False,
    )
    if resolution.status == "ambiguous":
        return "ambiguous", None, _candidates_from_matches(resolution.best_matches)

    summary = get_player_summary(query, players, teams)
    if resolution.status == "not_found" or summary is None:
        return "not_found", None, []

    return "ok", summary, []


# Required keys for captain scoring inputs
_REQUIRED_CANDIDATE_KEYS: tuple[str, ...] = (
    "form",
    "fixture_difficulty",
    "xgi_per_90",
    "minutes_risk",
)


def _validate_candidate_inputs(
    candidate_inputs: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate the four required captain-scoring fields.

    Returns a structured ``"error"`` dict if validation fails, or ``None``
    if all required keys are present.

    This is used by both ``tool_get_captain_score`` (called with a single
    candidate dict) and ``tool_rank_captain_candidates`` (called per-item
    in the candidates list).
    """
    if not candidate_inputs:
        return {
            "status":  "error",
            "code":    "missing_argument",
            "message": (
                "Captain scoring requires 'form', 'fixture_difficulty', "
                "'xgi_per_90', and 'minutes_risk' in candidate_inputs, "
                "but candidate_inputs is empty or None."
            ),
        }

    missing = [k for k in _REQUIRED_CANDIDATE_KEYS if k not in candidate_inputs]
    if missing:
        missing_str = ", ".join(f"'{k}'" for k in missing)
        return {
            "status":  "error",
            "code":    "missing_argument",
            "message": (
                f"Captain scoring missing required field(s): {missing_str}. "
                f"Please provide all of: "
                f"form, fixture_difficulty, xgi_per_90, minutes_risk."
            ),
        }

    return None


# ---------------------------------------------------------------------------
# Public tool surface
# ---------------------------------------------------------------------------

def tool_resolve_player(
    query: str | int,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a player query and return core identity fields.

    Use this when the caller only needs to confirm *which* player was found
    (e.g. before asking a follow-up question about them).  For a richer
    summary, use :func:`tool_get_player_summary`.

    Parameters
    ----------
    query:
        Player id (int), web_name, first/second name, or known alias.
    bootstrap:
        Full bootstrap dict from ``fpl_api_client.get_bootstrap()``.

    Returns — status "ok"
    ----------------------
    ``status``        "ok"
    ``player_id``     FPL element id
    ``web_name``      FPL display name
    ``name``          "First Last" full name
    ``team``          Full team name
    ``team_short``    Three-letter abbreviation
    ``position``      "GKP" / "DEF" / "MID" / "FWD"
    ``status_label``  "Available" / "Doubtful" / "Injured" / "Suspended" / "Unavailable"
    ``resolved_via``  "id" / "web_name" / "exact_name" / "alias"
    ``query``         The original query string

    Returns — status "ambiguous"
    ----------------------------
    ``status``      "ambiguous"
    ``query``       Original query
    ``candidates``  Up to 5 identity dicts for the tied players — ``id``,
                    ``web_name``, ``first_name``, ``second_name``, ``name``,
                    ``team_short``, ``position``, ``match_rank``.  Lets a
                    caller render a disambiguation wizard instead of a
                    dead-end clarification sentence.
    ``message``     Instruction for the LLM to ask for clarification

    Returns — status "not_found"
    ----------------------------
    ``status``   "not_found"
    ``query``    Original query
    ``message``  Instruction for the LLM to acknowledge no match
    """
    status, summary, candidates = _resolve_with_status(query, bootstrap)

    if status == "ambiguous":
        return {
            "status":     "ambiguous",
            "query":      str(query),
            "candidates": candidates,
            "message": (
                f"Multiple players share the name '{query}'. "
                "Ask the user to clarify — for example by providing "
                "a player id, full name, or team name."
            ),
        }

    if status == "not_found":
        return {
            "status":  "not_found",
            "query":   str(query),
            "message": f"No player found matching '{query}'.",
        }

    return {
        "status":       "ok",
        "player_id":    summary["id"],
        "web_name":     summary["web_name"],
        "name":         summary["name"],
        "team":         summary["team"],
        "team_short":   summary["team_short"],
        "position":     summary["position"],
        "status_label": summary["status"],
        "resolved_via": summary["query_resolved_via"],
        "query":        str(query),
    }


def tool_get_player_summary(
    query: str | int,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Return a full player summary suitable for grounded answer generation.

    Includes all identity fields from :func:`tool_resolve_player` plus
    cost and ownership data.

    Returns — status "ok"
    ----------------------
    Same as ``tool_resolve_player`` plus:
    ``cost_m``               Cost in £m (e.g. 14.5), or ``None`` if unknown
    ``selected_by_percent``  Ownership string (e.g. "52.3"), or ``None``

    Returns — status "ambiguous" / "not_found"
    -------------------------------------------
    Same as ``tool_resolve_player``.
    """
    status, summary, candidates = _resolve_with_status(query, bootstrap)

    if status == "ambiguous":
        return {
            "status":     "ambiguous",
            "query":      str(query),
            "candidates": candidates,
            "message": (
                f"Multiple players share the name '{query}'. "
                "Ask the user to clarify — for example by providing "
                "a player id, full name, or team name."
            ),
        }

    if status == "not_found":
        return {
            "status":  "not_found",
            "query":   str(query),
            "message": f"No player found matching '{query}'.",
        }

    # Enrich with season totals from the bootstrap element  (Phase 2.6d Story 2.2)
    element = next(
        (e for e in bootstrap.get("elements", []) if e.get("id") == summary["id"]),
        None,
    )
    total_points = int(element["total_points"]) if element and element.get("total_points") is not None else None
    form_val     = element.get("form") if element else None
    minutes_val  = int(element["minutes"]) if element and element.get("minutes") is not None else None

    return {
        "status":               "ok",
        "player_id":            summary["id"],
        "web_name":             summary["web_name"],
        "name":                 summary["name"],
        "team":                 summary["team"],
        "team_short":           summary["team_short"],
        "position":             summary["position"],
        "cost_m":               summary["cost_m"],
        "status_label":         summary["status"],
        "selected_by_percent":  summary["selected_by_percent"],
        "resolved_via":         summary["query_resolved_via"],
        "query":                str(query),
        # Phase 2.6d Story 2.2: season totals (None when not in bootstrap)
        "total_points":         total_points,
        "form":                 form_val,
        "minutes":              minutes_val,
    }


def tool_get_captain_score(
    query: str | int,
    bootstrap: dict[str, Any],
    candidate_inputs: dict[str, Any] | None = None,
    *,
    gameweek: int | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    """Return a captain score for a resolved player.

    Resolves the player identity from *bootstrap*, then computes the captain
    score.  When *candidate_inputs* is ``None`` or empty, scoring inputs are
    auto-derived from the player's bootstrap element (Phase 5m).  Explicit
    values in *candidate_inputs* take precedence over derived values.

    Parameters
    ----------
    query:
        Player id (int), web_name, first/second name, or known alias.
    bootstrap:
        Full bootstrap dict from ``fpl_api_client.get_bootstrap()``.
    candidate_inputs:
        Optional dict with scoring inputs:
        ``form``               — recent form (last 4 GW average points)
        ``fixture_difficulty`` — FDR 1–5 (1 = easiest, 5 = hardest)
        ``xgi_per_90``         — expected goal involvements per 90 minutes
        ``minutes_risk``       — minutes risk 0–100 (0 = guaranteed starter)
        When ``None`` or ``{}``, all four are derived from the bootstrap
        element automatically.

    Returns — status "ok"
    ----------------------
    ``status``          "ok"
    ``player_id``       FPL element id
    ``web_name``        FPL display name
    ``name``            "First Last" full name
    ``team``            Full team name
    ``team_short``      Three-letter abbreviation
    ``position``        "GKP" / "DEF" / "MID" / "FWD"
    ``captain_score``   Composite score 0–100 (float, 2 d.p.)
    ``tier``            Captain tier: "safe" / "upside" / "differential" /
                        "avoid" / "low_confidence"  (Phase 5m)
    ``role_signals``    Set-piece role signals dict  (Phase 5m)
    ``score_inputs``    Dict of the four inputs used
    ``minutes_context`` Played/available minutes, starts, participation source,
                        and explicit degradation metadata
    ``query``           The original query string

    Returns — status "ambiguous" / "not_found"
    -------------------------------------------
    Same shape as ``tool_resolve_player``.

    Returns — status "error"
    -------------------------
    ``status``  "error"
    ``code``    "missing_argument"
    ``message`` Descriptive message listing missing fields
    """
    try:
        time_context = captain_time_context(bootstrap, gameweek, horizon)
        scoring_bootstrap, fixture_source = bootstrap_for_captain_window(
            bootstrap, time_context
        )
        time_context["fixture_source"] = fixture_source
    except ValueError as exc:
        return {"status": "error", "code": "invalid_argument", "message": str(exc)}
    has_explicit_fixture = bool(
        candidate_inputs and "fixture_difficulty" in candidate_inputs
    )
    if (
        captain_window_needs_fixture_data(time_context, fixture_source)
        and not has_explicit_fixture
    ):
        time_context["notice"] = missing_captain_fixture_notice(time_context)
        return {
            "status": "error",
            "code": "missing_context",
            "message": (
                f"{time_context['notice']} Future team fixtures "
                "are not available in bootstrap."
            ),
            "time_context": time_context,
        }

    # Validate explicit inputs before player resolution (fast-fail on bad inputs)
    if candidate_inputs:
        validation_error = _validate_candidate_inputs(candidate_inputs)
        if validation_error:
            return validation_error

    status, summary, candidates = _resolve_with_status(query, bootstrap)

    if status == "ambiguous":
        return {
            "status":     "ambiguous",
            "query":      str(query),
            "candidates": candidates,
            "message": (
                f"Multiple players share the name '{query}'. "
                "Ask the user to clarify — for example by providing "
                "a player id, full name, or team name."
            ),
        }

    if status == "not_found":
        return {
            "status":  "not_found",
            "query":   str(query),
            "message": f"No player found matching '{query}'.",
        }

    # Look up bootstrap element for input derivation and role signals (Phase 5m)
    player_id = summary["id"]
    element = next(
        (e for e in bootstrap.get("elements", []) if e.get("id") == player_id),
        None,
    )

    # Build final scoring inputs: derived values as base, explicit values override
    if element is not None:
        derived = _derive_scoring_inputs_from_element(element, scoring_bootstrap)
        minutes_context = derive_minutes_context(
            element, scoring_bootstrap.get("team_fixtures")
        )
    else:
        derived = {"form": 5.0, "fixture_difficulty": 3, "xgi_per_90": 0.30, "minutes_risk": 0.0}
        minutes_context = None

    ci = {**derived, **(candidate_inputs or {})}

    form               = float(ci["form"])
    fixture_difficulty = ci["fixture_difficulty"]
    xgi_per_90         = float(ci["xgi_per_90"])
    minutes_risk       = float(ci["minutes_risk"])

    # Use canonical formula from fpl_captain_engine; round to 2 d.p. for display
    score = round(calculate_captain_score(form, fixture_difficulty, xgi_per_90, minutes_risk), 2)

    # Phase 5m: compute tier and role signals
    tier         = classify_captain_tier(score, minutes_risk, xgi_per_90)
    role_signals = derive_role_signals(element) if element is not None else {}

    return {
        "status":        "ok",
        "player_id":     player_id,
        "web_name":      summary["web_name"],
        "name":          summary["name"],
        "team":          summary["team"],
        "team_short":    summary["team_short"],
        "position":      summary["position"],
        "captain_score": score,
        "tier":          tier,          # Phase 5m
        "role_signals":  role_signals,  # Phase 5m
        "score_inputs": {
            "form":               form,
            "fixture_difficulty": int(fixture_difficulty),
            "xgi_per_90":         xgi_per_90,
            "minutes_risk":       minutes_risk,
        },
        "minutes_context": minutes_context,
        "time_context": time_context,
        "query": str(query),
    }


def tool_rank_captain_candidates(
    candidates: list[dict[str, Any]] | None,
    bootstrap: dict[str, Any],
    *,
    gameweek: int | None = None,
    horizon: int | None = None,
    squad_player_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Score and rank a list of captain candidates by composite captain score.

    Each candidate dict must contain:
    - ``query``              — player identifier (id, web_name, alias, etc.)
    - ``form``               — recent form (last 4 GW average points)
    - ``fixture_difficulty`` — FDR 1–5 (1 = easiest, 5 = hardest)
    - ``xgi_per_90``         — expected goal involvements per 90 minutes
    - ``minutes_risk``       — minutes risk 0–100 (0 = guaranteed starter)

    Each candidate is resolved against *bootstrap*.  Candidates that resolve
    successfully are scored and ranked by ``captain_score`` descending.
    Candidates that fail (ambiguous, not_found, or missing scoring fields)
    are included at the end of the ``ranked_candidates`` list with their
    error status — no candidate is silently dropped.

    Parameters
    ----------
    candidates:
        Optional list of candidate dicts. When absent or empty, the
        deterministic bootstrap pool is ranked and its top 12 are returned.
        Caller-provided lists are never truncated.
    bootstrap:
        Full bootstrap dict from ``fpl_api_client.get_bootstrap()``.
    squad_player_ids:
        Optional IDs resolved by the grounded-assistant layer. The pure
        contract never fetches a squad. Eligible owned players are retained
        even when they fall below the global top-12 cutoff.

    Returns — status "ok"
    ----------------------
    ``status``             "ok"
    ``ranked_candidates``  Sorted list of candidate result dicts.
                           ok entries first (sorted by captain_score desc),
                           then error/ambiguous/not_found entries.
                           Each ok entry has: rank, player_id, web_name, name,
                           team, team_short, position, captain_score,
                           score_inputs, minutes_context, query, index.
                           Each non-ok entry has: status, query/message,
                           index, and an error code where applicable.
    ``total``              Number of successfully scored candidates.
    ``pool_size``          Candidate count before the derived-pool output cap.
    ``squad_source``       connected when squad IDs were supplied, otherwise
                           not_connected (the grounded layer may override this
                           to unavailable after a failed squad fetch).
    ``squad_excluded``     Every owned player omitted from the ranking, with
                           reason unavailable, not_eligible_position, or unresolved.
    ``error_count``        Number of candidates that failed to resolve or
                           were missing required scoring fields.

    Returns — status "error"
    -------------------------
    ``status``  "error"
    ``code``    "missing_argument"
    ``message`` Descriptive message
    """
    try:
        time_context = captain_time_context(bootstrap, gameweek, horizon)
        scoring_bootstrap, fixture_source = bootstrap_for_captain_window(
            bootstrap, time_context
        )
        time_context["fixture_source"] = fixture_source
    except ValueError as exc:
        return {"status": "error", "code": "invalid_argument", "message": str(exc)}
    has_explicit_fixtures = bool(candidates) and all(
        isinstance(candidate, dict) and "fixture_difficulty" in candidate
        for candidate in candidates or []
    )
    if (
        captain_window_needs_fixture_data(time_context, fixture_source)
        and not has_explicit_fixtures
    ):
        time_context["notice"] = missing_captain_fixture_notice(time_context)
        return {
            "status": "error",
            "code": "missing_context",
            "message": (
                f"{time_context['notice']} Future team fixtures "
                "are not available in bootstrap."
            ),
            "time_context": time_context,
        }

    pool_source = "caller" if candidates else "derived"
    owned_ids: set[int] = set()
    if squad_player_ids is not None:
        for player_id in squad_player_ids:
            try:
                owned_ids.add(int(player_id))
            except (TypeError, ValueError):
                continue
    squad_source = "connected" if squad_player_ids is not None else "not_connected"

    elements_by_id = {
        int(element["id"]): element
        for element in bootstrap.get("elements", [])
        if element.get("id") is not None
    }
    squad_excluded_by_id: dict[int, dict[str, Any]] = {}
    for player_id in sorted(owned_ids):
        element = elements_by_id.get(player_id)
        reason: str | None = None
        if element is None:
            reason = "unresolved"
        elif element.get("status") in ("i", "s", "u"):
            reason = "unavailable"
        elif element.get("element_type") not in (3, 4):
            reason = "not_eligible_position"
        if reason is not None:
            squad_excluded_by_id[player_id] = {
                "player_id": player_id,
                "web_name": str(
                    element.get("web_name") if element is not None else f"#{player_id}"
                ),
                "status": str(
                    element.get("status") if element is not None else "unknown"
                ),
                "reason": reason,
            }
    candidates_to_rank = candidates or [
        {"query": element["id"]}
        for element in captain_pool_elements(bootstrap)
    ]

    ok_results:     list[dict[str, Any]] = []
    non_ok_results: list[dict[str, Any]] = []

    for i, c in enumerate(candidates_to_rank):
        query = c.get("query")

        # Missing query
        if query is None:
            non_ok_results.append({
                "status":  "error",
                "code":    "missing_argument",
                "message": f"Candidate at index {i} is missing 'query'.",
                "index":   i,
            })
            continue

        # Resolve player identity first (needed for element derivation)
        status, summary, cand_matches = _resolve_with_status(query, bootstrap)
        if status != "ok":
            try:
                unresolved_player_id = int(query)
            except (TypeError, ValueError):
                unresolved_player_id = None
            non_ok_results.append({
                "status":  status,
                "query":   str(query),
                "message": (
                    f"Multiple players share '{query}'. Provide full name or ID."
                    if status == "ambiguous"
                    else f"No player found matching '{query}'."
                ),
                "index": i,
                "owned": unresolved_player_id in owned_ids,
                **(
                    {"player_id": unresolved_player_id}
                    if unresolved_player_id in owned_ids
                    else {}
                ),
                **({"candidates": cand_matches} if status == "ambiguous" else {}),
            })
            continue

        # Look up bootstrap element for derivation and role signals (Phase 5m)
        player_id = summary["id"]
        element = next(
            (e for e in bootstrap.get("elements", []) if e.get("id") == player_id),
            None,
        )

        # Build scoring inputs: derived values as base, explicit candidate values override
        has_all_explicit = all(k in c for k in _REQUIRED_CANDIDATE_KEYS)
        if has_all_explicit:
            ci = c
        elif element is not None:
            derived = _derive_scoring_inputs_from_element(element, scoring_bootstrap)
            ci = {**derived, **{k: c[k] for k in _REQUIRED_CANDIDATE_KEYS if k in c}}
        else:
            # Element not found — require explicit inputs
            validation_error = _validate_candidate_inputs(c)
            if validation_error:
                non_ok_results.append({
                    **validation_error,
                    "query": str(query),
                    "index": i,
                    "player_id": player_id,
                    "owned": player_id in owned_ids,
                })
                continue
            ci = c

        minutes_context = (
            derive_minutes_context(element, scoring_bootstrap.get("team_fixtures"))
            if element is not None
            else None
        )

        form  = float(ci["form"])
        fdr   = ci["fixture_difficulty"]
        xgi   = float(ci["xgi_per_90"])
        risk  = float(ci["minutes_risk"])
        score = round(calculate_captain_score(form, fdr, xgi, risk), 2)

        # Phase 5m: tier and role signals
        tier         = classify_captain_tier(score, risk, xgi)
        role_signals = derive_role_signals(element) if element is not None else {}

        ok_results.append({
            "status":        "ok",
            "index":         i,
            "player_id":     player_id,
            "web_name":      summary["web_name"],
            "name":          summary["name"],
            "team":          summary["team"],
            "team_short":    summary["team_short"],
            "position":      summary["position"],
            "captain_score": score,
            "tier":          tier,          # Phase 5m
            "role_signals":  role_signals,  # Phase 5m
            "score_inputs": {
                "form":               form,
                "fixture_difficulty": int(fdr),
                "xgi_per_90":         xgi,
                "minutes_risk":       risk,
            },
            "minutes_context": minutes_context,
            "query":         str(query),
            "owned":         player_id in owned_ids,
        })

    # Sort ok results by captain_score descending and assign rank
    ok_results.sort(key=lambda x: x["captain_score"], reverse=True)
    for rank, entry in enumerate(ok_results, start=1):
        entry["rank"] = rank

    ranked_owned_ids = {
        int(entry["player_id"])
        for entry in ok_results
        if entry.get("owned") and entry.get("player_id") is not None
    }
    for player_id in sorted(owned_ids - ranked_owned_ids):
        if player_id in squad_excluded_by_id:
            continue
        element = elements_by_id.get(player_id)
        squad_excluded_by_id[player_id] = {
            "player_id": player_id,
            "web_name": str(
                element.get("web_name") if element is not None else f"#{player_id}"
            ),
            "status": str(
                element.get("status") if element is not None else "unknown"
            ),
            "reason": "unresolved",
        }
    squad_excluded = [
        squad_excluded_by_id[player_id]
        for player_id in sorted(squad_excluded_by_id)
    ]

    ranked_candidates = ok_results + non_ok_results
    pool_size = len(ranked_candidates)
    if pool_source == "derived":
        global_top = ranked_candidates[:DERIVED_CAPTAIN_POOL_LIMIT]
        retained_ids = {
            entry.get("player_id") for entry in global_top
            if entry.get("player_id") is not None
        }
        owned_outside_global_top = [
            entry for entry in ranked_candidates[DERIVED_CAPTAIN_POOL_LIMIT:]
            if entry.get("status") == "ok"
            and entry.get("owned")
            and entry.get("player_id") not in retained_ids
        ]
        ranked_candidates = global_top + owned_outside_global_top

    for entry in ranked_candidates:
        entry.setdefault("owned", False)

    returned_ok_count = sum(
        entry.get("status") == "ok" for entry in ranked_candidates
    )
    returned_error_count = len(ranked_candidates) - returned_ok_count

    return {
        "status":            "ok",
        "pool_source":       pool_source,
        "squad_source":      squad_source,
        "squad_excluded":    squad_excluded,
        "time_context":      time_context,
        "ranked_candidates": ranked_candidates,
        "pool_size":         pool_size,
        "total":             returned_ok_count,
        "error_count":       returned_error_count,
    }


def tool_get_current_gameweek(
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Return the current (or next) gameweek from bootstrap.

    Returns — status "ok"
    ----------------------
    ``status``    "ok"
    ``gameweek``  Gameweek number (int)

    Returns — status "not_found"
    ----------------------------
    ``status``   "not_found"
    ``message``  Explanation string
    """
    gw = get_current_gameweek_from_bootstrap(bootstrap)
    if gw is None:
        return {
            "status":  "not_found",
            "message": "No active or upcoming gameweek found in bootstrap.",
        }
    return {
        "status":   "ok",
        "gameweek": gw,
    }
