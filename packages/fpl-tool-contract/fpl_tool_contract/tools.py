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
                 ask for clarification before answering.
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
from fpl_player_registry import build_registry
from fpl_query_tools import get_current_gameweek_from_bootstrap, get_player_summary

# ---------------------------------------------------------------------------
# Phase 5m: scoring input derivation helpers
# ---------------------------------------------------------------------------

_STATUS_RISK: dict[str, float] = {
    "a": 0.0,
    "d": 30.0,
    "i": 100.0,
    "s": 100.0,
    "u": 100.0,
}


def _derive_scoring_inputs_from_element(
    element: dict,
    bootstrap: dict,
) -> dict:
    """Derive captain scoring inputs from a raw FPL bootstrap element.

    Returns a dict with keys: form, xgi_per_90, minutes_risk,
    fixture_difficulty.  Mirrors the derivation in comparison._score_one().
    """
    form = float(element.get("form", "0") or 0)

    minutes = float(element.get("minutes", 0) or 0)
    xgi_raw = float(element.get("expected_goal_involvements", "0") or 0)
    xgi_per_90 = (xgi_raw / (minutes / 90.0)) if minutes > 0 else 0.0

    status = element.get("status", "u")
    chance = element.get("chance_of_playing_this_round")
    if chance is not None and status == "d":
        minutes_risk = max(0.0, min(100.0, (1.0 - chance / 100.0) * 100.0))
    else:
        minutes_risk = _STATUS_RISK.get(status, 50.0)

    fdr_map = bootstrap.get("fixture_difficulty_map", {})
    team_id = element.get("team")
    fixture_difficulty = int(fdr_map.get(team_id, 3))

    return {
        "form":               form,
        "xgi_per_90":         round(xgi_per_90, 6),
        "minutes_risk":       minutes_risk,
        "fixture_difficulty": fixture_difficulty,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_with_status(
    query: str | int,
    bootstrap: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Decompose bootstrap, detect ambiguity, call get_player_summary.

    Returns (status, summary_or_None) where status is one of
    "ok" | "ambiguous" | "not_found".

    Ambiguity is detected by checking ``registry.ambiguous_web_names``
    *before* delegating to fpl_query_tools, because resolve_player_query
    returns None for both ambiguous and not-found and loses the distinction.
    """
    players = get_players(bootstrap)
    teams   = get_teams(bootstrap)

    # Numeric queries cannot be ambiguous (ids are always unique)
    q = str(query).strip()
    is_numeric = False
    try:
        int(q)
        is_numeric = True
    except (ValueError, TypeError):
        pass

    if not is_numeric:
        reg = build_registry(players, teams)
        if q.lower() in reg.ambiguous_web_names:
            return "ambiguous", None

    summary = get_player_summary(query, players, teams)
    if summary is None:
        return "not_found", None

    return "ok", summary


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
    ``status``   "ambiguous"
    ``query``    Original query
    ``message``  Instruction for the LLM to ask for clarification

    Returns — status "not_found"
    ----------------------------
    ``status``   "not_found"
    ``query``    Original query
    ``message``  Instruction for the LLM to acknowledge no match
    """
    status, summary = _resolve_with_status(query, bootstrap)

    if status == "ambiguous":
        return {
            "status":  "ambiguous",
            "query":   str(query),
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
    status, summary = _resolve_with_status(query, bootstrap)

    if status == "ambiguous":
        return {
            "status":  "ambiguous",
            "query":   str(query),
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
    }


def tool_get_captain_score(
    query: str | int,
    bootstrap: dict[str, Any],
    candidate_inputs: dict[str, Any] | None = None,
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
    # Validate explicit inputs before player resolution (fast-fail on bad inputs)
    if candidate_inputs:
        validation_error = _validate_candidate_inputs(candidate_inputs)
        if validation_error:
            return validation_error

    status, summary = _resolve_with_status(query, bootstrap)

    if status == "ambiguous":
        return {
            "status":  "ambiguous",
            "query":   str(query),
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
        derived = _derive_scoring_inputs_from_element(element, bootstrap)
    else:
        derived = {"form": 5.0, "fixture_difficulty": 3, "xgi_per_90": 0.30, "minutes_risk": 0.0}

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
        "query": str(query),
    }


def tool_rank_captain_candidates(
    candidates: list[dict[str, Any]],
    bootstrap: dict[str, Any],
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
        List of candidate dicts (at least one required).
    bootstrap:
        Full bootstrap dict from ``fpl_api_client.get_bootstrap()``.

    Returns — status "ok"
    ----------------------
    ``status``             "ok"
    ``ranked_candidates``  Sorted list of candidate result dicts.
                           ok entries first (sorted by captain_score desc),
                           then error/ambiguous/not_found entries.
                           Each ok entry has: rank, player_id, web_name, name,
                           team, team_short, position, captain_score,
                           score_inputs, query, index.
                           Each non-ok entry has: status, query/message,
                           index, and an error code where applicable.
    ``total``              Number of successfully scored candidates.
    ``error_count``        Number of candidates that failed to resolve or
                           were missing required scoring fields.

    Returns — status "error"
    -------------------------
    ``status``  "error"
    ``code``    "missing_argument"
    ``message`` Descriptive message
    """
    if not candidates:
        return {
            "status":  "error",
            "code":    "missing_argument",
            "message": "candidates list is empty — at least one candidate is required.",
        }

    ok_results:     list[dict[str, Any]] = []
    non_ok_results: list[dict[str, Any]] = []

    for i, c in enumerate(candidates):
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
        status, summary = _resolve_with_status(query, bootstrap)
        if status != "ok":
            non_ok_results.append({
                "status":  status,
                "query":   str(query),
                "message": (
                    f"Multiple players share '{query}'. Provide full name or ID."
                    if status == "ambiguous"
                    else f"No player found matching '{query}'."
                ),
                "index": i,
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
            derived = _derive_scoring_inputs_from_element(element, bootstrap)
            ci = {**derived, **{k: c[k] for k in _REQUIRED_CANDIDATE_KEYS if k in c}}
        else:
            # Element not found — require explicit inputs
            validation_error = _validate_candidate_inputs(c)
            if validation_error:
                non_ok_results.append({**validation_error, "query": str(query), "index": i})
                continue
            ci = c

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
            "query":         str(query),
        })

    # Sort ok results by captain_score descending and assign rank
    ok_results.sort(key=lambda x: x["captain_score"], reverse=True)
    for rank, entry in enumerate(ok_results, start=1):
        entry["rank"] = rank

    return {
        "status":            "ok",
        "ranked_candidates": ok_results + non_ok_results,
        "total":             len(ok_results),
        "error_count":       len(non_ok_results),
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