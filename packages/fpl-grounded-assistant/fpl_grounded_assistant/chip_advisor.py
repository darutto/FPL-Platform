"""
fpl_grounded_assistant.chip_advisor
=====================================
Phase 6b: Deterministic chip advice.
Phase 8c: DGW/BGW detection and free hit unblock.

Provides grounded chip recommendations for the four FPL chips:
  triple_captain, wildcard, bench_boost, free_hit

Design rules
------------
* Pure deterministic logic -- no LLM calls, no external API calls.
* Scoring uses the canonical ``calculate_captain_score`` formula from
  ``fpl_captain_engine`` (same engine as captain, comparison, and transfer).
* ``_derive_scoring_inputs`` is reused from ``transfer_advisor`` (shared helper).
* Chip names are extracted by the router, not by this module.
* All four chips return ``status="ok"`` when recognised; the ``recommendation``
  field distinguishes between ``conditions_favorable``, ``conditions_marginal``,
  ``conditions_unfavorable``, and ``missing_context``.

Supported chips and their grounding
--------------------------------------
triple_captain:
    Grounded in the top available MID/FWD captain score this week.
    Favorable (score >= 75): standout option exists -- TC is compelling.
    Marginal  (score >= 55): decent option, TC is defensible but not obvious.
    Unfavorable (score < 55): no standout option this week.

wildcard:
    Grounded in current gameweek timing.
    Unfavorable (GW <= 6): too early -- save for when squad issues accumulate.
    Marginal    (GW 7-28): viable mid-season window; depends on squad state.
    Unfavorable (GW >= 29): late season -- few gameweeks remain to benefit.

bench_boost:
    Grounded in average fixture difficulty (FDR) for top outfield players.
    Favorable   (avg FDR <= 2.5): generally easy fixtures.
    Marginal    (avg FDR <= 3.0): mixed fixture picture.
    Unfavorable (avg FDR > 3.0): generally difficult fixtures.
    Caveat: squad bench depth and game time are not available to this system.

free_hit (Phase 8c):
    Grounded in DGW/BGW detection from ``team_fixtures`` in bootstrap.
    DGW >= 6 teams:  conditions_favorable (large double gameweek)
    DGW 1-5 teams:   conditions_marginal  (partial double gameweek)
    BGW detected:    conditions_marginal  (save for next DGW)
    Normal GW:       conditions_unfavorable
    Missing data:    conditions_unfavorable (safe fallback)

    Detection uses the ``team_fixtures`` dict (introduced Phase 7h):
    - DGW: a team has more than one fixture in the current GW window
    - BGW: a team in ``team_fixtures`` has zero fixtures in the current GW

Intentionally deferred
-----------------------
* User squad context (which chips are still available, bench composition)
* Chip combination planning (e.g., triple captain + bench boost)
* Long-horizon fixture window beyond current GW
"""
from __future__ import annotations

from typing import Any

from fpl_captain_engine import calculate_captain_score
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .transfer_advisor import _derive_scoring_inputs


# ---------------------------------------------------------------------------
# Chip name constants
# ---------------------------------------------------------------------------

CHIP_TRIPLE_CAPTAIN: str = "triple_captain"
CHIP_WILDCARD:       str = "wildcard"
CHIP_BENCH_BOOST:    str = "bench_boost"
CHIP_FREE_HIT:       str = "free_hit"

SUPPORTED_CHIPS: frozenset[str] = frozenset({
    CHIP_TRIPLE_CAPTAIN,
    CHIP_WILDCARD,
    CHIP_BENCH_BOOST,
    CHIP_FREE_HIT,
})


# ---------------------------------------------------------------------------
# Recommendation thresholds
# ---------------------------------------------------------------------------

#: Top captain score >= this → TC is compelling ("conditions_favorable")
_TC_FAVORABLE_THRESHOLD: float = 75.0

#: Top captain score >= this → TC is defensible ("conditions_marginal")
_TC_MARGINAL_THRESHOLD: float = 55.0

#: GW <= this → too early to wildcard
_WC_EARLY_CUTOFF: int = 6

#: GW >= this → late season, limited value from wildcard
_WC_LATE_CUTOFF: int = 29

#: Average FDR for top 10 outfield players <= this → BB favorable
_BB_FAVORABLE_FDR: float = 2.5

#: Average FDR <= this → BB marginal
_BB_MARGINAL_FDR: float = 3.0

#: Free hit: DGW teams >= this → conditions_favorable (Phase 8c)
_FH_DGW_FAVORABLE_TEAMS: int = 6

#: Free hit: DGW teams >= this (but < _FH_DGW_FAVORABLE_TEAMS) → conditions_marginal (Phase 8c)
_FH_DGW_MARGINAL_TEAMS: int = 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_current_gameweek(bootstrap: dict[str, Any]) -> int | None:
    """Return the current GW id from bootstrap events, or None if unavailable."""
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            return event.get("id")
    return None


def _classify_gameweek_type(
    bootstrap: dict[str, Any],
) -> tuple[str, list[str], int, list[str], int]:
    """Classify the current gameweek as normal, double, blank, or mixed.

    Uses ``team_fixtures`` (introduced Phase 7h) and ``teams`` from the
    bootstrap to count how many fixtures each team has in the current GW.

    Parameters
    ----------
    bootstrap:
        FPL bootstrap dict.

    Returns
    -------
    tuple[str, list[str], int, list[str], int]
        ``(gw_type, dgw_teams, dgw_count, bgw_teams, bgw_count)`` where:

        * ``gw_type`` is ``"double"`` | ``"blank"`` | ``"mixed"`` |
          ``"normal"`` | ``"unknown"``
        * ``dgw_teams`` — short names of teams with > 1 fixture this GW
        * ``dgw_count`` — ``len(dgw_teams)``
        * ``bgw_teams`` — short names of teams with 0 fixtures this GW
        * ``bgw_count`` — ``len(bgw_teams)``

    Detection rules
    ---------------
    * DGW team: has > 1 fixture entry whose ``gameweek`` == current GW
    * BGW team: appears in ``team_fixtures`` but has 0 entries for current GW
    * ``"mixed"``: both DGW and BGW teams exist — common in late-season
      rescheduling and often the strongest Free Hit opportunity
    * Returns ``"unknown"`` when the current GW or team_fixtures are unavailable
    """
    current_gw = _get_current_gameweek(bootstrap)
    if current_gw is None:
        return ("unknown", [], 0, [], 0)

    team_fixtures: dict | None = bootstrap.get("team_fixtures")
    if not team_fixtures:
        return ("unknown", [], 0, [], 0)

    # Build a short-name lookup
    teams_list = bootstrap.get("teams", [])
    short_name: dict[int, str] = {
        t["id"]: t.get("short_name", str(t["id"]))
        for t in teams_list
        if "id" in t
    }

    dgw_shorts: list[str] = []
    bgw_shorts: list[str] = []

    for team_id_raw, fixtures in team_fixtures.items():
        team_id = int(team_id_raw)
        gw_count = sum(1 for f in fixtures if f.get("gameweek") == current_gw)
        sname = short_name.get(team_id, str(team_id))
        if gw_count > 1:
            dgw_shorts.append(sname)
        elif gw_count == 0:
            bgw_shorts.append(sname)

    dgw_shorts = sorted(dgw_shorts)
    bgw_shorts = sorted(bgw_shorts)

    if dgw_shorts and bgw_shorts:
        return ("mixed", dgw_shorts, len(dgw_shorts), bgw_shorts, len(bgw_shorts))
    if dgw_shorts:
        return ("double", dgw_shorts, len(dgw_shorts), [], 0)
    if bgw_shorts:
        return ("blank", [], 0, bgw_shorts, len(bgw_shorts))
    return ("normal", [], 0, [], 0)


def _score_outfield_players(bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    """Score all available MID/FWD players and return a list sorted by score desc.

    Uses ``calculate_captain_score`` from fpl_captain_engine with the same
    ``_derive_scoring_inputs`` helper used by transfer advice and comparison.

    Returns an empty list if no players can be scored.
    """
    import fpl_captain_engine          # noqa: F401 -- triggers sub-module sys.path
    from python.captain_tiers import classify_captain_tier

    elements = bootstrap.get("elements", [])
    fdr_map  = bootstrap.get("fixture_difficulty_map", {})
    scored: list[dict[str, Any]] = []

    for el in elements:
        if el.get("element_type") not in (3, 4):   # MID=3, FWD=4 only
            continue
        if el.get("status") in ("i", "s", "u"):    # skip definitely unavailable
            continue
        try:
            inputs = _derive_scoring_inputs(el, fdr_map)
            score  = round(
                calculate_captain_score(
                    inputs["form"],
                    inputs["fixture_difficulty"],
                    inputs["xgi_per_90"],
                    inputs["minutes_risk"],
                ),
                1,
            )
            tier = classify_captain_tier(
                score,
                inputs["minutes_risk"],
                inputs["xgi_per_90"],
            )
            scored.append({
                "web_name":      el.get("web_name", "Unknown"),
                "captain_score": score,
                "tier":          tier,
                "fdr":           int(fdr_map.get(el.get("team"), 3)),
            })
        except Exception:   # noqa: BLE001
            continue

    return sorted(scored, key=lambda x: x["captain_score"], reverse=True)


# ---------------------------------------------------------------------------
# Per-chip advice functions
# ---------------------------------------------------------------------------

def _advise_triple_captain(bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Compute triple captain conditions from the top available captain score."""
    ranked = _score_outfield_players(bootstrap)
    if not ranked:
        return {
            "recommendation": "missing_context",
            "signals": {},
            "advice_text": (
                "Triple captain conditions: missing context. "
                "Player scores could not be computed from the available data."
            ),
        }

    top       = ranked[0]
    top_score = top["captain_score"]
    top_name  = top["web_name"]
    top_tier  = top["tier"]

    if top_score >= _TC_FAVORABLE_THRESHOLD:
        recommendation = "conditions_favorable"
        label  = "favorable"
        phrase = (
            f"There is a standout option: {top_name} "
            f"(captain score {top_score}, tier: {top_tier}). "
            f"Conditions support using the triple captain chip."
        )
    elif top_score >= _TC_MARGINAL_THRESHOLD:
        recommendation = "conditions_marginal"
        label  = "marginal"
        phrase = (
            f"A decent but not exceptional option exists: {top_name} "
            f"(captain score {top_score}, tier: {top_tier}). "
            f"Consider whether a stronger option may appear in a later gameweek."
        )
    else:
        recommendation = "conditions_unfavorable"
        label  = "unfavorable"
        phrase = (
            f"No standout captain option this week. Best available: {top_name} "
            f"(captain score {top_score}, tier: {top_tier}). "
            f"It may be worth saving the triple captain chip."
        )

    return {
        "recommendation": recommendation,
        "signals": {
            "top_player":        top_name,
            "top_captain_score": top_score,
            "top_tier":          top_tier,
        },
        "advice_text": (
            f"Triple captain conditions: {label}. {phrase} "
            f"Note: whether you still have this chip available is not known to this system."
        ),
    }


def _advise_wildcard(
    bootstrap: dict[str, Any],
    current_gw: int,
) -> dict[str, Any]:
    """Compute wildcard conditions from gameweek timing."""
    if current_gw <= _WC_EARLY_CUTOFF:
        recommendation = "conditions_unfavorable"
        label  = "unfavorable"
        phrase = (
            f"It is early in the season (GW{current_gw}). "
            "Playing the wildcard this early limits your ability to react "
            "to injuries and fixture swings later in the season."
        )
    elif current_gw >= _WC_LATE_CUTOFF:
        recommendation = "conditions_unfavorable"
        label  = "unfavorable"
        phrase = (
            f"It is late in the season (GW{current_gw}). "
            "Few gameweeks remain to benefit from a full wildcard rebuild."
        )
    else:
        recommendation = "conditions_marginal"
        label  = "marginal"
        phrase = (
            f"You are in a viable wildcard window (GW{current_gw}). "
            "Whether to use it depends on how many squad issues you need to fix "
            "and your upcoming fixture outlook."
        )

    return {
        "recommendation": recommendation,
        "signals": {
            "current_gameweek": current_gw,
            "early_cutoff":     _WC_EARLY_CUTOFF,
            "late_cutoff":      _WC_LATE_CUTOFF,
        },
        "advice_text": (
            f"Wildcard conditions: {label}. {phrase} "
            "Note: squad composition and which wildcard you still hold are not "
            "available to this system."
        ),
    }


def _advise_bench_boost(bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Compute bench boost conditions from average FDR for top outfield players."""
    ranked = _score_outfield_players(bootstrap)
    if not ranked:
        return {
            "recommendation": "missing_context",
            "signals": {},
            "advice_text": (
                "Bench boost conditions: missing context. "
                "Fixture signals could not be computed from the available data."
            ),
        }

    top_n   = ranked[:10]
    fdrs    = [p["fdr"] for p in top_n]
    avg_fdr = round(sum(fdrs) / len(fdrs), 2) if fdrs else 3.0

    if avg_fdr <= _BB_FAVORABLE_FDR:
        recommendation = "conditions_favorable"
        label  = "favorable"
        phrase = (
            f"Top outfield players have generally easy fixtures this week "
            f"(average FDR: {avg_fdr}). Conditions support playing bench boost."
        )
    elif avg_fdr <= _BB_MARGINAL_FDR:
        recommendation = "conditions_marginal"
        label  = "marginal"
        phrase = (
            f"Top outfield players have mixed fixtures this week "
            f"(average FDR: {avg_fdr}). Bench boost may be viable but is not "
            f"compelling on fixture signals alone."
        )
    else:
        recommendation = "conditions_unfavorable"
        label  = "unfavorable"
        phrase = (
            f"Top outfield players face generally difficult fixtures this week "
            f"(average FDR: {avg_fdr}). Fixture conditions do not favour bench boost."
        )

    return {
        "recommendation": recommendation,
        "signals": {
            "average_fdr_top10": avg_fdr,
            "top_player_count":  len(top_n),
        },
        "advice_text": (
            f"Bench boost conditions: {label}. {phrase} "
            "This assessment is based on global fixture signals only. "
            "Bench depth and whether your bench players have guaranteed game time "
            "are not available to this system."
        ),
    }


def _advise_free_hit(
    bootstrap: dict[str, Any],
    current_gw: int | None,
) -> dict[str, Any]:
    """Free hit advice grounded in DGW/BGW detection (Phase 8c / 8c1).

    Uses ``_classify_gameweek_type`` to determine whether the current
    gameweek is a double, blank, mixed, or normal GW.

    Recommendation logic:
    - mixed (DGW+BGW): dgw_count >= 6 → conditions_favorable
                       dgw_count 1-5  → conditions_marginal
    - double:          dgw_count >= 6 → conditions_favorable
                       dgw_count 1-5  → conditions_marginal
    - blank:                           conditions_marginal (save for next DGW)
    - normal / unknown:                conditions_unfavorable (safe fallback)

    The ``current_gw`` parameter is ``int | None``.  When ``None`` (current GW
    unknown), the GW label is omitted from ``advice_text`` so no fake "GW0"
    is ever surfaced to callers.
    """
    gw_type, dgw_teams, dgw_count, bgw_teams, bgw_count = _classify_gameweek_type(bootstrap)

    # Backward-compat "affected_*" fields + new granular breakdowns
    if gw_type == "mixed":
        affected_teams_bc = sorted(dgw_teams + bgw_teams)
        affected_count_bc = dgw_count + bgw_count
    elif gw_type == "double":
        affected_teams_bc = dgw_teams
        affected_count_bc = dgw_count
    elif gw_type == "blank":
        affected_teams_bc = bgw_teams
        affected_count_bc = bgw_count
    else:
        affected_teams_bc = []
        affected_count_bc = 0

    signals: dict[str, Any] = {
        "current_gameweek":    current_gw,   # int | None — never coerced to 0
        "gameweek_type":       gw_type,
        # Phase 8c1: granular breakdown (additive)
        "dgw_teams":           dgw_teams,
        "dgw_count":           dgw_count,
        "bgw_teams":           bgw_teams,
        "bgw_count":           bgw_count,
        # Backward compat (kept for existing callers)
        "affected_teams":      affected_teams_bc,
        "affected_team_count": affected_count_bc,
    }

    # GW label — omitted when GW is unknown to avoid "GW0" in output
    gw_label = f" (GW{current_gw})" if current_gw is not None else ""

    def _team_str(teams: list[str]) -> str:
        return ", ".join(teams) if teams else "unknown"

    if gw_type == "mixed":
        # Both DGW and BGW teams present — often the strongest FH opportunity:
        # avoid blanked players AND stack double gameweek assets.
        if dgw_count >= _FH_DGW_FAVORABLE_TEAMS:
            recommendation = "conditions_favorable"
            label = "favorable"
        else:
            recommendation = "conditions_marginal"
            label = "marginal"
        phrase = (
            f"A mixed gameweek is detected: {dgw_count} team(s) play twice "
            f"({_team_str(dgw_teams)}) and {bgw_count} team(s) have no fixture "
            f"({_team_str(bgw_teams)}). "
            "Free hit lets you avoid blanked players and field double gameweek "
            "assets — often one of the strongest Free Hit opportunities."
        )
    elif gw_type == "double":
        if dgw_count >= _FH_DGW_FAVORABLE_TEAMS:
            recommendation = "conditions_favorable"
            label = "favorable"
            phrase = (
                f"A large double gameweek is detected: {dgw_count} team(s) "
                f"play twice this week ({_team_str(dgw_teams)}). "
                "Free hit conditions are strong — use it to field the best "
                "available XI for this double gameweek."
            )
        else:
            recommendation = "conditions_marginal"
            label = "marginal"
            phrase = (
                f"A partial double gameweek is detected: {dgw_count} team(s) "
                f"play twice this week ({_team_str(dgw_teams)}). "
                "Free hit may be viable but a larger double gameweek would be "
                "a stronger opportunity."
            )
    elif gw_type == "blank":
        recommendation = "conditions_marginal"
        label = "marginal"
        phrase = (
            f"A blank gameweek is detected: {bgw_count} team(s) have no "
            f"fixture this week ({_team_str(bgw_teams)}). "
            "Free hit can help cover blanked players, but saving it for an "
            "upcoming double gameweek is often the stronger play."
        )
    else:
        # normal or unknown — unfavorable (safe fallback for missing data too)
        recommendation = "conditions_unfavorable"
        label = "unfavorable"
        phrase = (
            "No blank or double gameweek detected this week. "
            "Free hit is most effective in blank or double gameweeks. "
            "Consider saving it for a better opportunity."
        )

    return {
        "recommendation": recommendation,
        "signals": signals,
        "advice_text": (
            f"Free hit conditions: {label}{gw_label}. {phrase} "
            "Note: whether you still have this chip available is not known "
            "to this system."
        ),
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def get_chip_advice(chip: str, bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic chip advice for the given FPL chip.

    Parameters
    ----------
    chip:
        One of the SUPPORTED_CHIPS constants:
        ``triple_captain``, ``wildcard``, ``bench_boost``, ``free_hit``.
    bootstrap:
        FPL bootstrap dict (fpl-data-core format).

    Returns
    -------
    dict
        Always ``status="ok"`` for recognised chips.  Key fields:

        status          "ok"
        chip            the requested chip name
        current_gameweek  int | None
        recommendation  "conditions_favorable" | "conditions_marginal" |
                        "conditions_unfavorable" | "missing_context"
        signals         chip-specific deterministic signal dict
        advice_text     human-readable recommendation string

    Notes
    -----
    * ``recommendation="missing_context"`` means the system lacks the data
      required to give meaningful advice (e.g. free_hit without DGW/BGW data),
      not that the chip is unavailable.
    * Whether the user actually holds the chip is unknown to this system;
      the ``advice_text`` notes this explicitly.
    """
    current_gw = _get_current_gameweek(bootstrap)

    if chip == CHIP_TRIPLE_CAPTAIN:
        result = _advise_triple_captain(bootstrap)
    elif chip == CHIP_WILDCARD:
        if current_gw is None:
            result = {
                "recommendation": "missing_context",
                "signals": {},
                "advice_text": (
                    "Wildcard conditions: missing context. "
                    "The current gameweek could not be determined from the available data."
                ),
            }
        else:
            result = _advise_wildcard(bootstrap, current_gw)
    elif chip == CHIP_BENCH_BOOST:
        result = _advise_bench_boost(bootstrap)
    elif chip == CHIP_FREE_HIT:
        result = _advise_free_hit(bootstrap, current_gw)  # None is safe — no GW0 leak
    else:
        # Defensive fallback -- routing should prevent unknown chip names
        return {
            "status":           "not_found",
            "chip":             chip,
            "current_gameweek": current_gw,
            "recommendation":   "unsupported",
            "signals":          {},
            "advice_text":      f"'{chip}' is not a recognised FPL chip name.",
        }

    return {
        "status":           "ok",
        "chip":             chip,
        "current_gameweek": current_gw,
        "recommendation":   result["recommendation"],
        "signals":          result["signals"],
        "advice_text":      result["advice_text"],
    }


# ---------------------------------------------------------------------------
# Tool spec and handler
# ---------------------------------------------------------------------------

def _get_chip_advice_handler(
    tool_args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool runner handler for get_chip_advice."""
    chip = tool_args.get("chip", "")
    return get_chip_advice(chip=chip, bootstrap=bootstrap)


CHIP_ADVICE_SPEC = ToolSpec(
    name="get_chip_advice",
    description=(
        "Deterministic chip conditions advice for FPL chips: "
        "triple_captain, wildcard, bench_boost, free_hit. "
        "Returns conditions_favorable / conditions_marginal / conditions_unfavorable "
        "or missing_context (when necessary data is unavailable)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "chip": {
                "type":        "string",
                "description": (
                    "The FPL chip to advise on: "
                    "triple_captain, wildcard, bench_boost, or free_hit"
                ),
                "enum": ["triple_captain", "wildcard", "bench_boost", "free_hit"],
            },
        },
        "required": ["chip"],
    },
    output_schema={
        "type": "object",
        "required": ["status", "chip", "current_gameweek",
                     "recommendation", "signals", "advice_text"],
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ok", "not_found"],
            },
            "chip": {"type": "string"},
            "current_gameweek": {"type": ["integer", "null"]},
            "recommendation": {
                "type": "string",
                "enum": [
                    "conditions_favorable",
                    "conditions_marginal",
                    "conditions_unfavorable",
                    "missing_context",
                    "unsupported",
                ],
            },
            "signals": {"type": "object"},
            "advice_text": {"type": "string"},
        },
    },
)

TOOL_REGISTRY.register(CHIP_ADVICE_SPEC, _get_chip_advice_handler)
