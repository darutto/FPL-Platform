"""
fpl_grounded_assistant.comparison
==================================
Phase 5a: deterministic two-player captain comparison.

Compares two players by captain_score using scoring inputs derived directly
from their bootstrap element data (form, xgi_per_90, minutes_risk,
fixture_difficulty).

Design rules
------------
* Pure deterministic logic -- no LLM calls, no external API calls.
* Scoring uses the canonical ``calculate_captain_score`` formula from
  ``fpl_captain_engine``.  The formula is not modified.
* Tier is classified via ``classify_captain_tier`` (fpl-captain-engine).
* Role signals are derived via ``derive_role_signals`` (fpl-captain-engine).
* Reason strings are produced by ``explain_captain`` (this package).
* Player resolution uses ``tool_resolve_player`` (fpl-tool-contract).
* If either player is not found or ambiguous, the comparison is not attempted
  -- the error is surfaced immediately.

Deferred
--------
* Follow-up comparison ("and Salah?") via session resolver
* Combining comparison with other intents
* Comparing more than two players

Output shape -- status "ok"
---------------------------
    status          "ok"
    query_a         original query for player A
    query_b         original query for player B
    player_a        dict: web_name, captain_score, tier, reasons, score_inputs
    player_b        dict: web_name, captain_score, tier, reasons, score_inputs
    winner          web_name of the higher-scoring player, or None on an exact tie
    margin          round(|score_a - score_b|, 2)
    recommendation  human-readable comparison sentence (deterministic fallback text)

Output shape -- status "not_found" / "ambiguous"
-------------------------------------------------
    status          error status of the failing player lookup
    query_a         original query for player A
    query_b         original query for player B
    error_player    the query that failed
    message         descriptive message from the failed lookup
"""
from __future__ import annotations

from typing import Any

from fpl_tool_contract import tool_resolve_player
from fpl_captain_engine import calculate_captain_score

from .explainer import explain_captain


# ---------------------------------------------------------------------------
# Minutes-risk table
# ---------------------------------------------------------------------------

_STATUS_RISK: dict[str, float] = {
    "a": 0.0,
    "d": 30.0,
    "i": 100.0,
    "s": 100.0,
    "u": 100.0,
}


# ---------------------------------------------------------------------------
# Scoring input derivation
# ---------------------------------------------------------------------------

def _derive_scoring_inputs(
    element: dict[str, Any],
    fdr_map: dict[int, int],
) -> dict[str, Any]:
    """Derive captain scoring inputs from a raw FPL bootstrap element.

    Parameters
    ----------
    element:
        Raw element dict from ``bootstrap["elements"]``.
    fdr_map:
        ``bootstrap.get("fixture_difficulty_map", {})`` — maps team_id to FDR.
        Falls back to FDR=3 when the team is absent from the map.

    Returns
    -------
    dict with keys: form (float), xgi_per_90 (float), minutes_risk (float),
    fixture_difficulty (int).
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

    team_id = element.get("team")
    fixture_difficulty = int(fdr_map.get(team_id, 3))

    return {
        "form":               form,
        "xgi_per_90":         round(xgi_per_90, 6),
        "minutes_risk":       minutes_risk,
        "fixture_difficulty": fixture_difficulty,
    }


# ---------------------------------------------------------------------------
# Per-player scoring
# ---------------------------------------------------------------------------

def _score_one(query: str, bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Resolve a player and compute their grounded captain score.

    Returns a complete scoring dict on success, or an error dict
    (status="not_found" / "ambiguous" / "error") on failure.
    """
    # Import triggers sys.path setup for python.* sub-modules
    import fpl_captain_engine  # noqa: F401
    from python.captain_tiers import classify_captain_tier
    from python.role_evaluator import derive_role_signals

    resolve = tool_resolve_player(query, bootstrap)
    if resolve["status"] != "ok":
        return resolve

    player_id = resolve["player_id"]
    element   = next(
        (el for el in bootstrap.get("elements", []) if el.get("id") == player_id),
        None,
    )
    if element is None:
        return {
            "status":  "error",
            "query":   str(query),
            "message": f"Element not found for player_id {player_id}.",
        }

    fdr_map = bootstrap.get("fixture_difficulty_map", {})
    inputs  = _derive_scoring_inputs(element, fdr_map)

    score = round(
        calculate_captain_score(
            inputs["form"],
            inputs["fixture_difficulty"],
            inputs["xgi_per_90"],
            inputs["minutes_risk"],
        ),
        2,
    )

    tier         = classify_captain_tier(score, inputs["minutes_risk"], inputs["xgi_per_90"])
    role_signals = derive_role_signals(element)

    raw_for_explain = {
        "status":        "ok",
        "captain_score": score,
        "score_inputs":  {
            "form":               inputs["form"],
            "fixture_difficulty": inputs["fixture_difficulty"],
            "xgi_per_90":         inputs["xgi_per_90"],
            "minutes_risk":       inputs["minutes_risk"],
        },
        "tier":         tier,
        "role_signals": role_signals,
    }

    return {
        "status":        "ok",
        "web_name":      resolve["web_name"],
        "name":          resolve["name"],
        "team":          resolve["team"],
        "position":      resolve["position"],
        "captain_score": score,
        "tier":          tier,
        "role_signals":  role_signals,
        "score_inputs":  raw_for_explain["score_inputs"],
        "reasons":       explain_captain(raw_for_explain),
        "query":         str(query),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_players(
    query_a: str,
    query_b: str,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Compare two players as captain candidates using grounded scoring.

    Derives scoring inputs (form, xgi_per_90, minutes_risk, FDR) from the
    bootstrap element for each player.  Uses the canonical
    ``calculate_captain_score`` formula unchanged.

    Parameters
    ----------
    query_a, query_b:
        Player name, web_name, alias, or numeric id for each comparison side.
    bootstrap:
        Raw FPL bootstrap dict.  Inject ``fixture_difficulty_map`` for
        accurate FDR; falls back to FDR=3 if absent.

    Returns
    -------
    dict
        Always returned -- never raises.  Inspect ``"status"`` to detect errors.

    Examples
    --------
    >>> from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    >>> result = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)
    >>> result["status"]
    'ok'
    >>> result["winner"]
    'Salah'
    """
    scored_a = _score_one(query_a, bootstrap)
    if scored_a["status"] != "ok":
        return {
            "status":       scored_a["status"],
            "query_a":      query_a,
            "query_b":      query_b,
            "error_player": query_a,
            "message":      scored_a.get("message", f"Could not score '{query_a}'."),
        }

    scored_b = _score_one(query_b, bootstrap)
    if scored_b["status"] != "ok":
        return {
            "status":       scored_b["status"],
            "query_a":      query_a,
            "query_b":      query_b,
            "error_player": query_b,
            "message":      scored_b.get("message", f"Could not score '{query_b}'."),
        }

    score_a = scored_a["captain_score"]
    score_b = scored_b["captain_score"]
    name_a  = scored_a["web_name"]
    name_b  = scored_b["web_name"]

    if score_a > score_b:
        winner = name_a
        margin = round(score_a - score_b, 2)
    elif score_b > score_a:
        winner = name_b
        margin = round(score_b - score_a, 2)
    else:
        winner = None
        margin = 0.0

    return {
        "status":   "ok",
        "query_a":  query_a,
        "query_b":  query_b,
        "player_a": {
            "web_name":      name_a,
            "captain_score": score_a,
            "tier":          scored_a["tier"],
            "reasons":       scored_a["reasons"],
            "score_inputs":  scored_a["score_inputs"],
        },
        "player_b": {
            "web_name":      name_b,
            "captain_score": score_b,
            "tier":          scored_b["tier"],
            "reasons":       scored_b["reasons"],
            "score_inputs":  scored_b["score_inputs"],
        },
        "winner":         winner,
        "margin":         margin,
        "recommendation": _build_recommendation(
            name_a, score_a, scored_a["reasons"],
            name_b, score_b, scored_b["reasons"],
            winner, margin,
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _reason_clause(reasons: list[str]) -> str:
    """Up to 2 reasons joined by '; ', or empty string."""
    if not reasons:
        return ""
    return "; ".join(reasons[:2])


def _build_recommendation(
    name_a: str,
    score_a: float,
    reasons_a: list[str],
    name_b: str,
    score_b: float,
    reasons_b: list[str],
    winner: str | None,
    margin: float,
) -> str:
    """Concise, grounded comparison sentence."""
    if winner is None:
        base = (
            f"{name_a} ({score_a}) and {name_b} ({score_b})"
            " are tied on captain score."
        )
    else:
        loser        = name_b if winner == name_a else name_a
        winner_score = score_a if winner == name_a else score_b
        loser_score  = score_b if winner == name_a else score_a
        base = (
            f"{winner} ({winner_score}) edges {loser} ({loser_score})"
            f" — margin {margin}."
        )

    parts = []
    clause_a = _reason_clause(reasons_a)
    clause_b = _reason_clause(reasons_b)
    if clause_a:
        parts.append(f"{name_a}: {clause_a}")
    if clause_b:
        parts.append(f"{name_b}: {clause_b}")
    if parts:
        return base + "  " + "  ".join(parts) + "."
    return base
