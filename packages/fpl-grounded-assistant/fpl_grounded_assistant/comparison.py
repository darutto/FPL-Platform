"""
fpl_grounded_assistant.comparison
==================================
Phase 5a: deterministic two-player captain comparison.
Phase 5b: registered as a proper tool in TOOL_REGISTRY.
Phase 5d: comparison explainability — comparative reasons and margin label.

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
* Combining comparison with other intents
* Comparing more than two players

Output shape -- status "ok"
---------------------------
    status              "ok"
    query_a             original query for player A
    query_b             original query for player B
    player_a            dict: web_name, captain_score, tier, reasons, score_inputs
    player_b            dict: web_name, captain_score, tier, reasons, score_inputs
    winner              web_name of the higher-scoring player, or None on an exact tie
    margin              round(|score_a - score_b|, 2)
    margin_label        "narrow" | "moderate" | "clear"  (Phase 5d)
    comparison_reasons  list[str] — comparative advantage phrases  (Phase 5d)
    recommendation      human-readable comparison sentence (deterministic)

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
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

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
# Phase 5d: comparative explainability thresholds
# ---------------------------------------------------------------------------

#: Minimum form delta for "stronger form" advantage
_FORM_ADV_THRESHOLD: float = 1.5

#: Minimum FDR difference for "easier fixture" advantage (lower FDR = better)
_FDR_ADV_THRESHOLD: int = 1

#: Minimum xGI/90 delta for "higher xGI output" advantage
_XGI_ADV_THRESHOLD: float = 0.10

#: Minimum minutes_risk delta for "better minutes security" advantage
_RISK_ADV_THRESHOLD: float = 20.0

#: margin < _MARGIN_NARROW → "narrow" edge
_MARGIN_NARROW: float = 3.0

#: margin >= _MARGIN_CLEAR → "clear" edge
_MARGIN_CLEAR: float = 10.0


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

    # Phase 5d: comparative explainability
    if winner is not None:
        winner_scored = scored_a if winner == name_a else scored_b
        loser_scored  = scored_b if winner == name_a else scored_a
        comparison_reasons = _explain_comparison(winner_scored, loser_scored)
    else:
        comparison_reasons = []

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
        "winner":              winner,
        "margin":              margin,
        "margin_label":        _margin_label(margin),           # Phase 5d
        "comparison_reasons":  comparison_reasons,               # Phase 5d
        "recommendation":      _build_recommendation(
            name_a, score_a,
            name_b, score_b,
            winner, margin, comparison_reasons,
        ),
    }


# ---------------------------------------------------------------------------
# Phase 5d: comparative explainability
# ---------------------------------------------------------------------------

def _margin_label(margin: float) -> str:
    """Categorise a comparison margin as 'narrow', 'moderate', or 'clear'."""
    if margin < _MARGIN_NARROW:
        return "narrow"
    if margin >= _MARGIN_CLEAR:
        return "clear"
    return "moderate"


def _explain_comparison(
    winner: dict[str, Any],
    loser: dict[str, Any],
) -> list[str]:
    """Derive deterministic comparative advantage phrases for the winner.

    Inspects the ``score_inputs`` and ``role_signals`` of each scored player
    dict and returns short phrases describing *why* the winner leads.
    Returns an empty list when no individual signal crosses its threshold
    (e.g. both players have identical inputs or only marginal differences).

    Parameters
    ----------
    winner, loser:
        Full scored player dicts from ``_score_one()`` — must contain
        ``score_inputs`` (form, fixture_difficulty, xgi_per_90, minutes_risk)
        and ``role_signals`` (role_bonus).

    Returns
    -------
    list[str]
        Ordered list of advantage phrases, up to four entries.
        Never raises.
    """
    reasons: list[str] = []

    w_inp  = winner.get("score_inputs", {})
    l_inp  = loser.get("score_inputs", {})
    w_role = winner.get("role_signals", {})
    l_role = loser.get("role_signals", {})

    # 1. Form advantage
    w_form = float(w_inp.get("form", 0.0))
    l_form = float(l_inp.get("form", 0.0))
    if w_form - l_form >= _FORM_ADV_THRESHOLD:
        reasons.append(f"stronger form ({w_form:.1f} vs {l_form:.1f})")

    # 2. Fixture advantage (lower FDR = better)
    w_fdr = int(w_inp.get("fixture_difficulty", 3))
    l_fdr = int(l_inp.get("fixture_difficulty", 3))
    if l_fdr - w_fdr >= _FDR_ADV_THRESHOLD:
        reasons.append(f"easier fixture (FDR {w_fdr} vs {l_fdr})")

    # 3. xGI/90 advantage
    w_xgi = float(w_inp.get("xgi_per_90", 0.0))
    l_xgi = float(l_inp.get("xgi_per_90", 0.0))
    if w_xgi - l_xgi >= _XGI_ADV_THRESHOLD:
        reasons.append("higher xGI output")

    # 4. Minutes security advantage (lower risk = better)
    w_risk = float(w_inp.get("minutes_risk", 0.0))
    l_risk = float(l_inp.get("minutes_risk", 0.0))
    if l_risk - w_risk >= _RISK_ADV_THRESHOLD:
        reasons.append("better minutes security")

    # 5. Set-piece advantage
    w_bonus = float(w_role.get("role_bonus", 0.0))
    l_bonus = float(l_role.get("role_bonus", 0.0))
    if w_bonus > l_bonus:
        reasons.append("set-piece advantage")

    return reasons


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _build_recommendation(
    name_a: str,
    score_a: float,
    name_b: str,
    score_b: float,
    winner: str | None,
    margin: float,
    comparison_reasons: list[str],
) -> str:
    """Concise, grounded comparison sentence with comparative reasoning."""
    if winner is None:
        return (
            f"{name_a} ({score_a}) and {name_b} ({score_b})"
            " are tied on captain score."
        )

    loser        = name_b if winner == name_a else name_a
    winner_score = score_a if winner == name_a else score_b
    loser_score  = score_b if winner == name_a else score_a
    label        = _margin_label(margin)

    base = (
        f"{winner} ({winner_score}) edges {loser} ({loser_score})"
        f" — {label} margin ({margin})."
    )

    if comparison_reasons:
        clause = "; ".join(comparison_reasons[:3])
        return base + f"  Advantages: {clause}."
    return base


# ---------------------------------------------------------------------------
# Tool contract (Phase 5b)
# ---------------------------------------------------------------------------

COMPARE_PLAYERS_SPEC = ToolSpec(
    name="compare_players",
    description=(
        "Compare two FPL players as captain candidates using grounded scoring. "
        "Derives form, xgi_per_90, minutes_risk, and fixture difficulty directly "
        "from bootstrap element data.  Returns a structured comparison with "
        "captain scores, tiers, reason strings, and a winner recommendation. "
        "Returns status='not_found' or status='ambiguous' if either player "
        "cannot be uniquely resolved."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query_a": {
                "type":        "string",
                "description": "First player — name, web_name, alias, or FPL element id.",
            },
            "query_b": {
                "type":        "string",
                "description": "Second player — name, web_name, alias, or FPL element id.",
            },
        },
        "required": ["query_a", "query_b"],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type": "object",
                "required": ["status", "query_a", "query_b",
                             "player_a", "player_b", "winner", "margin", "recommendation"],
                "properties": {
                    "status":             {"type": "string", "enum": ["ok"]},
                    "query_a":            {"type": "string"},
                    "query_b":            {"type": "string"},
                    "player_a":           {"type": "object"},
                    "player_b":           {"type": "object"},
                    "winner":             {"type": ["string", "null"]},
                    "margin":             {"type": "number"},
                    "margin_label":       {"type": "string",
                                           "enum": ["narrow", "moderate", "clear"]},
                    "comparison_reasons": {"type": "array",
                                           "items": {"type": "string"}},
                    "recommendation":     {"type": "string"},
                },
            },
            {
                "title": "error",
                "type": "object",
                "required": ["status", "query_a", "query_b", "error_player", "message"],
                "properties": {
                    "status":       {"type": "string",
                                     "enum": ["not_found", "ambiguous", "error"]},
                    "query_a":      {"type": "string"},
                    "query_b":      {"type": "string"},
                    "error_player": {"type": "string"},
                    "message":      {"type": "string"},
                },
            },
        ]
    },
)


def _compare_players_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``compare_players()``."""
    return compare_players(args["query_a"], args["query_b"], bootstrap)


# Register with the shared tool registry so run_tool("compare_players", ...) works.
TOOL_REGISTRY.register(COMPARE_PLAYERS_SPEC, _compare_players_handler)
