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
    candidates      ambiguous only -- the tied players from the resolver,
                    for a pick-one wizard. Absent when none were produced.

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
from .fixture_context import build_fixture_context, fixture_tiebreaker_line  # FI3a
from .position_score import (
    compute_position_score,
    redistribute_preseason_weights,
    shrink_rate_by_minutes,
    POSITION_PROFILES,
)


# ---------------------------------------------------------------------------
# Shared scoring helpers — canonical homes are scoring_core (cross-layer base)
# and scoring_shared (grounded-assistant). Re-imported here so this module's
# public surface is unchanged for __init__.py re-exports and the consumers that
# import _derive_scoring_inputs from transfer_advisor (chip_advisor,
# differential_picks, phase scripts).
# ---------------------------------------------------------------------------

from fpl_tool_contract.scoring_core import _STATUS_RISK  # noqa: F401  (compat re-export)
from .scoring_shared import (  # noqa: F401  (compat re-exports)
    _FORM_ADV_THRESHOLD,
    _FDR_ADV_THRESHOLD,
    _XGI_ADV_THRESHOLD,
    _RISK_ADV_THRESHOLD,
    _SET_PIECE_SHORT,
    _venue_tag,
    _set_piece_advantage_phrase,
    HOME_FDR_ADJUSTMENT,
    _resolve_venue,
    _compute_effective_fdr,
    _derive_scoring_inputs,
)


# ---------------------------------------------------------------------------
# Recommendation thresholds  (transfer-advisor-local, not shared)
# ---------------------------------------------------------------------------

#: score_delta > this → "transfer_in"  (player_in clearly better)
_TRANSFER_THRESHOLD_STRONG: float = 5.0

#: 0 < score_delta <= _TRANSFER_THRESHOLD_STRONG → "marginal_transfer_in"
#: score_delta <= 0 → "hold"


def _get_current_gw(bootstrap: dict[str, Any]) -> int | None:
    """Return the current-or-next GW id, or None.

    Delegates to the canonical ``get_current_gameweek`` resolver so this
    behaves identically everywhere: it falls back to ``is_next`` when no
    event is ``is_current`` — the pre-season / between-GW state (e.g. GW1
    before kickoff), which a bare ``is_current`` check misses.
    """
    from fpl_api_client import get_current_gameweek
    return get_current_gameweek(bootstrap)




# ---------------------------------------------------------------------------
# Per-player scoring (extended with now_cost)
# ---------------------------------------------------------------------------

def _score_one(query: str, bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Resolve a player, compute their captain score, and include now_cost.

    Returns a complete scoring dict on success, or an error dict
    (status="not_found" / "ambiguous" / "error") on failure.
    """
    from fpl_captain_engine import classify_captain_tier, derive_role_signals
    from fpl_api_client import is_form_informative

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
    minutes      = float(element.get("minutes", 0) or 0)
    saves_per_90 = shrink_rate_by_minutes(float(element.get("saves_per_90", 0) or 0), minutes)
    cs_per_90    = shrink_rate_by_minutes(float(element.get("clean_sheets_per_90", 0) or 0), minutes)
    dc_per_90    = shrink_rate_by_minutes(float(element.get("defensive_contribution_per_90", 0) or 0), minutes)

    # Preseason: form is 0 for ~everyone, so its weight is dead. Redistribute
    # it (mostly onto xgi — see position_score.py) rather than let it silently
    # compress every score toward a ~60/100 ceiling. Re-derived on every call
    # from the live bootstrap, so this stops applying the moment `form` is
    # genuinely populated again — nothing to persist or remember to revert.
    weights_override = None
    label_override = None
    if not is_form_informative(bootstrap):
        pos_key = position_str.upper()
        base_profile = POSITION_PROFILES.get(pos_key, POSITION_PROFILES["MID"])
        weights_override = redistribute_preseason_weights(base_profile)
        label_override = pos_key if pos_key in POSITION_PROFILES else "MID"

    ps_result = compute_position_score(
        position=position_str,
        form=inputs["form"],
        fixture_difficulty=inputs["effective_fdr"],
        xgi_per_90=inputs["xgi_per_90_shrunk"],
        minutes_risk=inputs["minutes_risk"],
        saves_per_90=saves_per_90,
        clean_sheets_per_90=cs_per_90,
        dc_per_90=dc_per_90,
        weights_override=weights_override,
        weights_override_label=label_override,
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
        "team_id":          element.get("team"),   # FI3a: for fixture context
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
    def _failed(failed_side: dict[str, Any], failed_query: str) -> dict[str, Any]:
        """Surface a failed side's status, preserving any disambiguation candidates.

        ``candidates`` is forwarded verbatim when the resolver produced one
        (ambiguous side only), so the caller can offer pick-one chips instead
        of a clarification the user has to answer by retyping.
        """
        out = {
            "status":       failed_side["status"],
            "query_out":    query_out,
            "query_in":     query_in,
            "error_player": failed_query,
            "message":      failed_side.get("message", f"Could not score '{failed_query}'."),
        }
        candidates = failed_side.get("candidates")
        if candidates:
            out["candidates"] = candidates
        return out

    scored_out = _score_one(query_out, bootstrap)
    if scored_out["status"] != "ok":
        return _failed(scored_out, query_out)

    scored_in = _score_one(query_in, bootstrap)
    if scored_in["status"] != "ok":
        return _failed(scored_in, query_in)

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

    # FI3a: additive fixture context — never changes score/delta/recommendation.
    # Axis auto-picked per position (incl. dynamic defensive-mid detection).
    # The tiebreaker line surfaces only on close calls (not a strong upgrade).
    fc_out = build_fixture_context(
        bootstrap, team_id=scored_out.get("team_id"), position=scored_out.get("position"),
        dc_per_90=scored_out.get("score_inputs", {}).get("dc_per_90"),
    )
    fc_in = build_fixture_context(
        bootstrap, team_id=scored_in.get("team_id"), position=scored_in.get("position"),
        dc_per_90=scored_in.get("score_inputs", {}).get("dc_per_90"),
    )
    fixture_tiebreaker = fixture_tiebreaker_line(
        [(name_in, fc_in), (name_out, fc_out)],
        emit=(recommendation in ("marginal_transfer_in", "hold")),
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
            "fixture_context": fc_out,                         # FI3a (additive)
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
            "fixture_context": fc_in,                          # FI3a (additive)
        },
        "score_delta":          score_delta,
        "price_delta":          price_delta,
        "recommendation":       recommendation,
        "transfer_reasons":     transfer_reasons,
        "recommendation_text":  recommendation_text,
        "fixture_tiebreaker":   fixture_tiebreaker,            # FI3a (additive, may be None)
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
                    # Ambiguous only — the tied players, for a pick-one wizard.
                    "candidates":   {"type": "array", "items": {"type": "object"}},
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
