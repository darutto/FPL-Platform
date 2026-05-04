"""
fpl_grounded_assistant.position_fixture_run
============================================
Phase 2.6e.4: Position-filtered fixture calendar ranking.

Answers questions like:
  "defenders with best fixtures next 5 gameweeks"
  "best teams for midfielders next 3 GWs"
  "mejores equipos para delanteros proximas 4 jornadas"

Design
------
The ranking logic delegates entirely to ``get_team_fixture_calendar``.
The only addition is a ``position`` label that frames the output contextually
("Best teams for defenders").  All teams are ranked — the position does not
filter which teams appear, since every PL club has players of every position.

Accepted position codes
-----------------------
FPL code  Aliases accepted
GKP       gkp, goalkeeper, goalkeepers, portero, porteros
DEF       def, defender, defenders, defensa, defensas, defensor, defensores
MID       mid, midfielder, midfielders, centrocampista, centrocampistas,
          mediocampista, mediocampistas, medio, medios
FWD       fwd, forward, forwards, striker, strikers, delantero, delanteros,
          atacante, atacantes, punta, puntas
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .team_fixture_calendar import DEFAULT_HORIZON, DEFAULT_TOP_N, get_team_fixture_calendar


# ---------------------------------------------------------------------------
# Position alias resolution
# ---------------------------------------------------------------------------

_POSITION_ALIASES: dict[str, str] = {
    # GKP
    "gkp":              "GKP",
    "goalkeeper":       "GKP",
    "goalkeepers":      "GKP",
    "portero":          "GKP",
    "porteros":         "GKP",
    # DEF
    "def":              "DEF",
    "defender":         "DEF",
    "defenders":        "DEF",
    "defensa":          "DEF",
    "defensas":         "DEF",
    "defensor":         "DEF",
    "defensores":       "DEF",
    # MID
    "mid":              "MID",
    "midfielder":       "MID",
    "midfielders":      "MID",
    "centrocampista":   "MID",
    "centrocampistas":  "MID",
    "mediocampista":    "MID",
    "mediocampistas":   "MID",
    "medio":            "MID",
    "medios":           "MID",
    # FWD
    "fwd":              "FWD",
    "forward":          "FWD",
    "forwards":         "FWD",
    "striker":          "FWD",
    "strikers":         "FWD",
    "delantero":        "FWD",
    "delanteros":       "FWD",
    "atacante":         "FWD",
    "atacantes":        "FWD",
    "punta":            "FWD",
    "puntas":           "FWD",
}

_POSITION_LABELS: dict[str, str] = {
    "GKP": "goalkeepers",
    "DEF": "defenders",
    "MID": "midfielders",
    "FWD": "forwards",
}


def _resolve_position(position_query: str) -> str | None:
    """Map a free-text position string to a canonical FPL code, or ``None``."""
    return _POSITION_ALIASES.get(position_query.lower().strip())


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def get_position_fixture_run(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Rank teams by upcoming fixture difficulty for a specific player position.

    Parameters
    ----------
    args:
        ``position_query`` (str) — position name or alias (e.g. "defenders").
        ``mode``           (str) — "easiest" or "hardest" (default "easiest").
        ``horizon``        (int) — GW lookahead window (default 5, max 10).
    bootstrap:
        FPL bootstrap dict with ``team_fixtures`` and ``teams`` keys.

    Returns — status "ok"
    ----------------------
    All fields from ``get_team_fixture_calendar`` plus:
    ``position``        canonical code ("DEF", "MID", "FWD", "GKP")
    ``position_label``  human-readable label ("defenders", etc.)

    Returns — status "invalid_position"
    ------------------------------------
    When ``position_query`` does not resolve to a known position code.

    Returns — status "missing_context"
    ------------------------------------
    Propagated from ``get_team_fixture_calendar`` when team_fixtures absent.
    """
    position_query = str(args.get("position_query", "")).strip()
    mode           = str(args.get("mode", "easiest"))
    horizon        = int(args.get("horizon", DEFAULT_HORIZON))

    position = _resolve_position(position_query)
    if position is None:
        return {
            "status":         "invalid_position",
            "position_query": position_query,
            "message": (
                f"Unknown position '{position_query}'. "
                "Accepted: goalkeeper, defender, midfielder, forward "
                "(or Spanish equivalents)."
            ),
        }

    result = get_team_fixture_calendar(
        bootstrap,
        mode=mode,
        horizon=horizon,
        top_n=DEFAULT_TOP_N,
    )

    if result["status"] != "ok":
        return result

    return {
        **result,
        "position":       position,
        "position_label": _POSITION_LABELS[position],
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

POSITION_FIXTURE_RUN_SPEC = ToolSpec(
    name="get_position_fixture_run",
    description=(
        "Rank teams by upcoming fixture difficulty for a specific player position "
        "(defenders, midfielders, forwards, or goalkeepers). "
        "Returns the same ranked-team list as get_team_fixture_calendar plus "
        "position and position_label fields. "
        "Returns status='invalid_position' for unrecognised position queries. "
        "Returns status='missing_context' when fixture data is absent."
    ),
    parameters={
        "type": "object",
        "properties": {
            "position_query": {
                "type":        "string",
                "description": "Position name or alias, e.g. 'defenders', 'delanteros'.",
            },
            "mode": {
                "type":        "string",
                "enum":        ["easiest", "hardest"],
                "description": "Sort order: 'easiest' or 'hardest'.",
            },
            "horizon": {
                "type":        "integer",
                "description": "GW lookahead window (default 5, max 10).",
            },
        },
        "required": ["position_query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":           {"type": "string"},
            "position":         {"type": "string"},
            "position_label":   {"type": "string"},
            "mode":             {"type": "string"},
            "horizon":          {"type": "integer"},
            "current_gameweek": {"type": ["integer", "null"]},
            "top_n":            {"type": "integer"},
            "teams":            {"type": "array"},
        },
    },
)

TOOL_REGISTRY.register(POSITION_FIXTURE_RUN_SPEC, get_position_fixture_run)
