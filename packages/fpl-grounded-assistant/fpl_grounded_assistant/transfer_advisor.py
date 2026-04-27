"""
fpl_grounded_assistant.transfer_advisor
========================================
Phase 6a: Deterministic transfer advice.

Provides grounded two-player transfer recommendation for prompts like:
  "should I sell Saka for Palmer?"
  "should I transfer out Bruno for Foden?"
  "sell Haaland for Salah"
  "swap Saka for Palmer"

Design rules
------------
* Pure deterministic logic -- no LLM calls, no external API calls.
* Scoring uses the canonical ``calculate_captain_score`` formula from
  ``fpl_captain_engine``.  The formula is not modified.
* Tier is classified via ``classify_captain_tier`` (fpl-captain-engine).
* Role signals are derived via ``derive_role_signals`` (fpl-captain-engine).
* Player resolution uses ``tool_resolve_player`` (fpl-tool-contract).
* If either player is not found or ambiguous, advice is not attempted --
  the error is surfaced immediately.
* Price delta is derived from bootstrap element ``now_cost`` (tenths of £).
* The recommendation is based on ``captain_score`` delta only; price is
  shown as informational context but does not change the recommendation.

Recommendation vocabulary
--------------------------
``"transfer_in"``
    player_in captain_score is clearly better (delta > 5.0).
``"marginal_transfer_in"``
    player_in has a small but positive delta (0 < delta <= 5.0).
``"hold"``
    player_out is same or better (delta <= 0).

Output shape -- status "ok"
---------------------------
    status              "ok"
    query_out           original query for the player being sold
    query_in            original query for the player being bought
    player_out          dict: web_name, captain_score, tier, reasons,
                              score_inputs, role_signals, now_cost, cost_m
    player_in           dict: same keys
    score_delta         round(captain_score_in - captain_score_out, 2)
    price_delta         now_cost_in - now_cost_out  (tenths of £, can be neg)
    recommendation      "transfer_in" | "marginal_transfer_in" | "hold"
    transfer_reasons    list[str] -- deterministic advantage phrases for player_in
    recommendation_text human-readable recommendation sentence (deterministic)

Output shape -- status "not_found" / "ambiguous"
-------------------------------------------------
    status          error status of the failing player lookup
    query_out       original query for the player being sold
    query_in        original query for the player being bought
    error_player    the query that failed to resolve
    message         descriptive message from the failed lookup

Deferred
--------
* Transfer cost in FPL context (e.g. hit for extra transfers)
* Considering wildcard / free-hit chip state
* Multi-player transfer planning
* Follow-up transfer questions in session context
"""
from __future__ import annotations

from typing import Any

from fpl_tool_contract import tool_resolve_player
from fpl_captain_engine import calculate_captain_score
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .explainer import explain_captain
from .position_score import compute_position_score


# ---------------------------------------------------------------------------
# Minutes-risk table (same as comparison.py)
# ---------------------------------------------------------------------------

_STATUS_RISK: dict[str, float] = {
    "a": 0.0,
    "d": 30.0,
    "i": 100.0,
    "s": 100.0,
    "u": 100.0,
}


# ---------------------------------------------------------------------------
# Advantage thresholds (mirror comparison.py)
# ---------------------------------------------------------------------------

#: Minimum form delta (in - out) for "stronger form" advantage
_FORM_ADV_THRESHOLD: float = 1.5

#: Minimum FDR difference (out_fdr - in_fdr) for "easier fixture" advantage
_FDR_ADV_THRESHOLD: int = 1

#: Minimum xGI/90 delta (in - out) for "higher xGI output" advantage
_XGI_ADV_THRESHOLD: float = 0.10

#: Minimum minutes_risk delta (out - in) for "better minutes security" advantage
_RISK_ADV_THRESHOLD: float = 20.0


# ---------------------------------------------------------------------------
# Recommendation thresholds
# ---------------------------------------------------------------------------

#: score_delta > this → "transfer_in"  (player_in clearly better)
_TRANSFER_THRESHOLD_STRONG: float = 5.0

#: 0 < score_delta <= _TRANSFER_THRESHOLD_STRONG → "marginal_transfer_in"
#: score_delta <= 0 → "hold"


# ---------------------------------------------------------------------------
# Set-piece labels (same as comparison.py — kept local to avoid coupling)
# ---------------------------------------------------------------------------

_SET_PIECE_SHORT: dict[str, str] = {
    "penalty_taker_1":  "pen",
    "penalty_taker_2":  "pen2",
    "freekick_taker_1": "fk",
    "freekick_taker_2": "fk2",
}


def _set_piece_advantage_phrase(
    in_role: dict[str, Any],
    out_role: dict[str, Any],
) -> str | None:
    """Return a set-piece advantage phrase for player_in, or ``None``.

    Fires when player_in's ``role_bonus`` strictly exceeds player_out's.
    """
    in_bonus  = float(in_role.get("role_bonus", 0.0))
    out_bonus = float(out_role.get("role_bonus", 0.0))
    if in_bonus <= out_bonus:
        return None

    in_notes  = in_role.get("set_piece_notes", [])
    out_notes = out_role.get("set_piece_notes", [])

    if not in_notes:
        return "set-piece advantage"

    in_label = _SET_PIECE_SHORT.get(in_notes[0], in_notes[0])
    if out_notes:
        out_label = _SET_PIECE_SHORT.get(out_notes[0], out_notes[0])
        return f"set-piece advantage ({in_label} vs {out_label})"
    return f"set-piece advantage ({in_label})"


def _venue_tag(is_home: bool | None) -> str:
    """Return a short venue suffix for display: 'H', 'A', or ''."""
    if is_home is True:
        return "H"
    if is_home is False:
        return "A"
    return ""


# ---------------------------------------------------------------------------
# Scoring input derivation (same logic as comparison.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 8b: home/away fixture awareness
# ---------------------------------------------------------------------------

#: Home/away FDR adjustment magnitude.
#: Home team gets ``raw_fdr - HOME_FDR_ADJUSTMENT`` (easier at home).
#: Away team gets ``raw_fdr + HOME_FDR_ADJUSTMENT`` (harder away).
#: Net effect on fixture_score: ±10 points (via ``(6 - fdr) * 20``).
HOME_FDR_ADJUSTMENT: float = 0.5


def _get_current_gw(bootstrap: dict[str, Any]) -> int | None:
    """Return the current GW id from bootstrap events, or None."""
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            return event.get("id")
    return None


def _resolve_venue(
    team_id: int | None,
    team_fixtures: dict | None,
    current_gw: int | None,
) -> bool | None:
    """Return ``True`` if the team plays at home this GW, ``False`` if away,
    or ``None`` if venue cannot be determined."""
    if team_id is None or team_fixtures is None or current_gw is None:
        return None
    fixtures = team_fixtures.get(team_id)
    if not fixtures:
        return None
    for fix in fixtures:
        if fix.get("gameweek") == current_gw:
            return fix.get("is_home")
    return None


def _compute_effective_fdr(
    raw_fdr: int,
    is_home: bool | None,
) -> float:
    """Apply home/away adjustment to raw FDR.

    Returns a float FDR clamped to [1.0, 5.0].  When ``is_home`` is
    ``None`` (venue unknown), returns ``raw_fdr`` unchanged.
    """
    if is_home is None:
        return float(raw_fdr)
    if is_home:
        return max(1.0, min(5.0, raw_fdr - HOME_FDR_ADJUSTMENT))
    return max(1.0, min(5.0, raw_fdr + HOME_FDR_ADJUSTMENT))


def _derive_scoring_inputs(
    element: dict[str, Any],
    fdr_map: dict[int, int],
    team_fixtures: dict | None = None,
    current_gw: int | None = None,
) -> dict[str, Any]:
    """Derive captain scoring inputs from a raw FPL bootstrap element.

    Phase 8b: when ``team_fixtures`` and ``current_gw`` are provided,
    computes ``effective_fdr`` (home/away adjusted) and ``is_home``.
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

    # Phase 8b: home/away venue resolution and effective FDR
    is_home = _resolve_venue(team_id, team_fixtures, current_gw)
    effective_fdr = _compute_effective_fdr(fixture_difficulty, is_home)

    return {
        "form":               form,
        "xgi_per_90":         round(xgi_per_90, 6),
        "minutes_risk":       minutes_risk,
        "fixture_difficulty": fixture_difficulty,
        "is_home":            is_home,
        "effective_fdr":      round(effective_fdr, 1),
    }


# ---------------------------------------------------------------------------
# Per-player scoring (extended with now_cost)
# ---------------------------------------------------------------------------

def _score_one(query: str, bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Resolve a player, compute their captain score, and include now_cost.

    Returns a complete scoring dict on success, or an error dict
    (status="not_found" / "ambiguous" / "error") on failure.
    """
    import fpl_captain_engine  # noqa: F401  -- triggers sub-module sys.path setup
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

    fdr_map        = bootstrap.get("fixture_difficulty_map", {})
    team_fixtures  = bootstrap.get("team_fixtures")
    current_gw     = _get_current_gw(bootstrap)
    inputs  = _derive_scoring_inputs(element, fdr_map, team_fixtures, current_gw)

    # Layer 1: canonical captain_score uses raw fixture_difficulty (int)
    score = round(
        calculate_captain_score(
            inputs["form"],
            inputs["fixture_difficulty"],
            inputs["xgi_per_90"],
            inputs["minutes_risk"],
        ),
        2,
    )

    # Phase 8a1/8b: position-aware heuristic evaluation (Layer 2)
    # Uses effective_fdr (home/away adjusted) for fixture component
    position_str = resolve["position"]
    saves_per_90 = float(element.get("saves_per_90", 0) or 0)
    cs_per_90    = float(element.get("clean_sheets_per_90", 0) or 0)
    dc_per_90    = float(element.get("defensive_contribution_per_90", 0) or 0)

    ps_result = compute_position_score(
        position=position_str,
        form=inputs["form"],
        fixture_difficulty=inputs["effective_fdr"],
        xgi_per_90=inputs["xgi_per_90"],
        minutes_risk=inputs["minutes_risk"],
        saves_per_90=saves_per_90,
        clean_sheets_per_90=cs_per_90,
        dc_per_90=dc_per_90,
    )

    tier         = classify_captain_tier(ps_result.position_score, inputs["minutes_risk"], inputs["xgi_per_90"])
    role_signals = derive_role_signals(element)
    now_cost     = int(element.get("now_cost", 0))
    cost_m       = f"£{now_cost / 10:.1f}m"

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

    full_score_inputs = {
        "form":               inputs["form"],
        "fixture_difficulty": inputs["fixture_difficulty"],
        "xgi_per_90":         inputs["xgi_per_90"],
        "minutes_risk":       inputs["minutes_risk"],
        "saves_per_90":       round(saves_per_90, 4),
        "clean_sheets_per_90": round(cs_per_90, 4),
        "dc_per_90":          round(dc_per_90, 4),
        "is_home":            inputs["is_home"],
        "effective_fdr":      inputs["effective_fdr"],
        "position_score":     ps_result.position_score,
        "position_profile":   ps_result.position_profile,
        "components":         ps_result.components,
        "weights":            ps_result.weights,
    }

    return {
        "status":           "ok",
        "web_name":         resolve["web_name"],
        "name":             resolve["name"],
        "team":             resolve["team"],
        "position":         resolve["position"],
        "captain_score":    score,
        "position_score":   ps_result.position_score,
        "tier":             tier,
        "role_signals":     role_signals,
        "score_inputs":     full_score_inputs,
        "reasons":          explain_captain(raw_for_explain),
        "now_cost":         now_cost,
        "cost_m":           cost_m,
        "query":            str(query),
    }


# ---------------------------------------------------------------------------
# Transfer advantage phrases
# ---------------------------------------------------------------------------

def _build_transfer_reasons(
    in_scored: dict[str, Any],
    out_scored: dict[str, Any],
) -> list[str]:
    """Derive deterministic advantage phrases for player_in over player_out.

    Returns a list of short reason strings describing why player_in
    has an edge.  Empty when no individual signal crosses its threshold.

    Parameters
    ----------
    in_scored:
        Full scored player dict from ``_score_one()`` for the player being
        transferred in.
    out_scored:
        Full scored player dict from ``_score_one()`` for the player being
        transferred out.

    Returns
    -------
    list[str]
        Ordered list of advantage phrases, up to five entries.
        Never raises.
    """
    reasons: list[str] = []

    in_inp  = in_scored.get("score_inputs", {})
    out_inp = out_scored.get("score_inputs", {})
    in_role = in_scored.get("role_signals", {})
    out_role = out_scored.get("role_signals", {})

    # 1. Form advantage
    in_form  = float(in_inp.get("form", 0.0))
    out_form = float(out_inp.get("form", 0.0))
    if in_form - out_form >= _FORM_ADV_THRESHOLD:
        reasons.append(f"stronger form ({in_form:.1f} vs {out_form:.1f})")

    # 2. Fixture advantage (lower FDR = easier fixture)
    # Phase 8b: use effective_fdr (home/away adjusted) for threshold check
    in_efdr  = float(in_inp.get("effective_fdr", in_inp.get("fixture_difficulty", 3)))
    out_efdr = float(out_inp.get("effective_fdr", out_inp.get("fixture_difficulty", 3)))
    if out_efdr - in_efdr >= _FDR_ADV_THRESHOLD:
        in_raw  = int(in_inp.get("fixture_difficulty", 3))
        out_raw = int(out_inp.get("fixture_difficulty", 3))
        in_v  = _venue_tag(in_inp.get("is_home"))
        out_v = _venue_tag(out_inp.get("is_home"))
        reasons.append(f"easier fixture (FDR {in_raw}{in_v} vs {out_raw}{out_v})")

    # 3. xGI/90 advantage
    in_xgi  = float(in_inp.get("xgi_per_90", 0.0))
    out_xgi = float(out_inp.get("xgi_per_90", 0.0))
    if in_xgi - out_xgi >= _XGI_ADV_THRESHOLD:
        reasons.append("higher xGI output")

    # 4. Minutes security (lower risk = better)
    in_risk  = float(in_inp.get("minutes_risk", 0.0))
    out_risk = float(out_inp.get("minutes_risk", 0.0))
    if out_risk - in_risk >= _RISK_ADV_THRESHOLD:
        reasons.append("better minutes security")

    # 5. Set-piece advantage
    sp_phrase = _set_piece_advantage_phrase(in_role, out_role)
    if sp_phrase is not None:
        reasons.append(sp_phrase)

    return reasons


# ---------------------------------------------------------------------------
# Recommendation text builder
# ---------------------------------------------------------------------------

def _build_recommendation_text(
    in_name: str,
    out_name: str,
    score_in: float,
    score_out: float,
    score_delta: float,
    price_delta: int,
    recommendation: str,
    reasons: list[str],
) -> str:
    """Build a deterministic, grounded recommendation sentence.

    Parameters
    ----------
    in_name, out_name:
        Player display names.
    score_in, score_out:
        Captain scores.
    score_delta:
        ``score_in - score_out`` (positive → player_in is better).
    price_delta:
        ``now_cost_in - now_cost_out`` in tenths of £ (positive → more expensive).
    recommendation:
        ``"transfer_in"``, ``"marginal_transfer_in"``, or ``"hold"``.
    reasons:
        Advantage phrases for player_in (may be empty).

    Returns
    -------
    str
        One or two sentences.
    """
    reasons_clause = ""
    if reasons:
        reasons_clause = "  Advantages: " + "; ".join(reasons[:4]) + "."

    price_note = ""
    if price_delta != 0:
        price_m = abs(price_delta) / 10.0
        if price_delta > 0:
            price_note = f"  Net cost: +\u00a3{price_m:.1f}m."
        else:
            price_note = f"  Net saving: \u00a3{price_m:.1f}m."

    delta_abs = abs(score_delta)

    if recommendation == "transfer_in":
        return (
            f"Recommendation: Transfer in {in_name}. "
            f"Score: {score_in:.0f} vs {out_name}'s {score_out:.0f} "
            f"(+{delta_abs:.1f}).{reasons_clause}{price_note}"
        )

    if recommendation == "marginal_transfer_in":
        return (
            f"Marginal: Consider {in_name} over {out_name}. "
            f"Score: {score_in:.0f} vs {score_out:.0f} "
            f"(+{delta_abs:.1f}).{reasons_clause}{price_note}"
        )

    # "hold" — player_out is same or better
    delta_str = f"{score_delta:.1f}" if score_delta < 0 else "0.0"
    return (
        f"Recommendation: Hold {out_name}. "
        f"Score: {score_out:.0f} vs {in_name}'s {score_in:.0f} "
        f"({delta_str}).{reasons_clause}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_transfer_advice(
    query_out: str,
    query_in: str,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Produce grounded transfer advice for selling player_out and buying player_in.

    Derives scoring inputs (form, xgi_per_90, minutes_risk, FDR) and price
    from bootstrap element data for each player.  Uses the canonical
    ``calculate_captain_score`` formula unchanged.

    Parameters
    ----------
    query_out:
        Player name, web_name, alias, or numeric id for the player to sell.
    query_in:
        Player name, web_name, alias, or numeric id for the player to buy.
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
    >>> result = get_transfer_advice("Saka", "Salah", STANDARD_BOOTSTRAP)
    >>> result["status"]
    'ok'
    >>> result["recommendation"] in ("transfer_in", "marginal_transfer_in", "hold")
    True
    """
    scored_out = _score_one(query_out, bootstrap)
    if scored_out["status"] != "ok":
        return {
            "status":       scored_out["status"],
            "query_out":    query_out,
            "query_in":     query_in,
            "error_player": query_out,
            "message":      scored_out.get("message", f"Could not score '{query_out}'."),
        }

    scored_in = _score_one(query_in, bootstrap)
    if scored_in["status"] != "ok":
        return {
            "status":       scored_in["status"],
            "query_out":    query_out,
            "query_in":     query_in,
            "error_player": query_in,
            "message":      scored_in.get("message", f"Could not score '{query_in}'."),
        }

    # Phase 8a1: use position_score for recommendation and delta (Layer 2)
    score_out = scored_out["position_score"]
    score_in  = scored_in["position_score"]
    name_out  = scored_out["web_name"]
    name_in   = scored_in["web_name"]

    score_delta = round(score_in - score_out, 2)
    price_delta = scored_in["now_cost"] - scored_out["now_cost"]   # tenths of £

    if score_delta > _TRANSFER_THRESHOLD_STRONG:
        recommendation = "transfer_in"
    elif score_delta > 0:
        recommendation = "marginal_transfer_in"
    else:
        recommendation = "hold"

    transfer_reasons = _build_transfer_reasons(scored_in, scored_out)

    # For "hold", show player_out's advantages over player_in so the text
    # explains WHY to hold (not confusingly list player_in's minor edges).
    if recommendation == "hold":
        hold_reasons = _build_transfer_reasons(scored_out, scored_in)
        display_reasons = hold_reasons
    else:
        display_reasons = transfer_reasons

    recommendation_text = _build_recommendation_text(
        name_in, name_out,
        score_in, score_out,
        score_delta, price_delta,
        recommendation, display_reasons,
    )

    return {
        "status":    "ok",
        "query_out": query_out,
        "query_in":  query_in,
        "player_out": {
            "web_name":        name_out,
            "captain_score":   scored_out["captain_score"],    # Layer 1 canonical
            "position_score":  scored_out["position_score"],   # Layer 2 heuristic
            "tier":            scored_out["tier"],
            "reasons":         scored_out["reasons"],
            "score_inputs":    scored_out["score_inputs"],
            "role_signals":    scored_out.get("role_signals", {}),
            "now_cost":        scored_out["now_cost"],
            "cost_m":          scored_out["cost_m"],
        },
        "player_in": {
            "web_name":        name_in,
            "captain_score":   scored_in["captain_score"],    # Layer 1 canonical
            "position_score":  scored_in["position_score"],   # Layer 2 heuristic
            "tier":            scored_in["tier"],
            "reasons":         scored_in["reasons"],
            "score_inputs":    scored_in["score_inputs"],
            "role_signals":    scored_in.get("role_signals", {}),
            "now_cost":        scored_in["now_cost"],
            "cost_m":          scored_in["cost_m"],
        },
        "score_delta":          score_delta,
        "price_delta":          price_delta,
        "recommendation":       recommendation,
        "transfer_reasons":     transfer_reasons,
        "recommendation_text":  recommendation_text,
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

TRANSFER_ADVICE_SPEC = ToolSpec(
    name="get_transfer_advice",
    description=(
        "Produce grounded transfer advice for selling one FPL player and buying "
        "another.  Derives form, xgi_per_90, minutes_risk, fixture difficulty, and "
        "price from bootstrap element data.  Returns a structured recommendation "
        "(transfer_in / marginal_transfer_in / hold) with captain scores, price "
        "delta, and deterministic advantage phrases. "
        "Returns status='not_found' or status='ambiguous' if either player "
        "cannot be uniquely resolved."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query_out": {
                "type":        "string",
                "description": "Player to sell -- name, web_name, alias, or FPL element id.",
            },
            "query_in": {
                "type":        "string",
                "description": "Player to buy -- name, web_name, alias, or FPL element id.",
            },
        },
        "required": ["query_out", "query_in"],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type": "object",
                "required": ["status", "query_out", "query_in",
                             "player_out", "player_in", "score_delta",
                             "price_delta", "recommendation", "recommendation_text"],
                "properties": {
                    "status":               {"type": "string", "enum": ["ok"]},
                    "query_out":            {"type": "string"},
                    "query_in":             {"type": "string"},
                    "player_out":           {"type": "object"},
                    "player_in":            {"type": "object"},
                    "score_delta":          {"type": "number"},
                    "price_delta":          {"type": "number"},
                    "recommendation":       {
                        "type": "string",
                        "enum": ["transfer_in", "marginal_transfer_in", "hold"],
                    },
                    "transfer_reasons":     {"type": "array",
                                             "items": {"type": "string"}},
                    "recommendation_text":  {"type": "string"},
                },
            },
            {
                "title": "error",
                "type": "object",
                "required": ["status", "query_out", "query_in", "error_player", "message"],
                "properties": {
                    "status":       {"type": "string",
                                     "enum": ["not_found", "ambiguous", "error"]},
                    "query_out":    {"type": "string"},
                    "query_in":     {"type": "string"},
                    "error_player": {"type": "string"},
                    "message":      {"type": "string"},
                },
            },
        ]
    },
)


def _get_transfer_advice_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler -- delegates to ``get_transfer_advice()``."""
    return get_transfer_advice(args["query_out"], args["query_in"], bootstrap)


# Register with the shared tool registry so run_tool("get_transfer_advice", ...) works.
TOOL_REGISTRY.register(TRANSFER_ADVICE_SPEC, _get_transfer_advice_handler)
