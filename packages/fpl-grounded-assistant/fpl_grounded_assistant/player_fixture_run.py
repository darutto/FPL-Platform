"""
fpl_grounded_assistant.player_fixture_run
==========================================
Phase 7h: Deterministic player fixture run retrieval.

Provides a grounded fixture schedule for prompts like:
  "Haaland fixtures"
  "Salah next 5 games"
  "upcoming fixtures for Palmer"
  "fixtures for Saka"
  "fixture run for De Bruyne"

Design rules
------------
* Pure deterministic logic -- no LLM calls, no external API calls.
* Player resolution uses ``tool_resolve_player`` (fpl-tool-contract).
* Fixture data is read from ``bootstrap["team_fixtures"]`` — a dict mapping
  team IDs to lists of upcoming fixture dicts (gameweek, opponent_team,
  is_home, difficulty).
* Default horizon is 5 (matching "next 5 games" as the canonical prompt form).
* Opponent short names are resolved from bootstrap["teams"].
* Current gameweek is derived from bootstrap["events"] (is_current flag).
* Only fixtures at or after the current gameweek are returned, sorted
  by gameweek ascending.
* If ``team_fixtures`` is absent from bootstrap, returns status="missing_context".
* If the player's team is not in ``team_fixtures``, returns status="missing_context".

Fixture data requirement
------------------------
Bootstrap must contain a ``team_fixtures`` key:

    "team_fixtures": {
        <team_id>: [
            {"gameweek": <int>, "opponent_team": <team_id>, "is_home": <bool>,
             "difficulty": <int 1-5>},
            ...  # sorted by gameweek ascending
        ],
        ...
    }

This is an extension of the standard FPL bootstrap-static format.
In the live platform, this would be assembled from the FPL fixtures endpoint.

Output shape -- status "ok"
---------------------------
    status              "ok"
    query               original player query
    web_name            display name (e.g. "Haaland")
    team_short          3-char team abbreviation (e.g. "MCI")
    position            FPL position string (FWD/MID/DEF/GKP)
    horizon             number of fixtures actually returned
    current_gameweek    GW number at time of query (None if not determinable)
    fixtures            list of fixture dicts (see below)

Each fixture dict:
    gameweek        GW number
    opponent_short  3-char opponent abbreviation (e.g. "ARS")
    is_home         True if the player's team is at home
    difficulty      FDR 1-5 (from the player's team perspective)

Output shape -- status "not_found" / "ambiguous"
-------------------------------------------------
    status          error status from player lookup
    query           original player query
    message         descriptive message

Output shape -- status "missing_context"
-----------------------------------------
    status          "missing_context"
    query           original player query
    web_name        display name (if player was resolved)
    message         descriptive message explaining what data is absent

Deferred
--------
* Horizon override from user prompt (router always uses DEFAULT_HORIZON=5;
  programmatic callers may pass explicit horizon)
* DGW/BGW tagging for double or blank gameweeks
* xG/predicted-score overlay per fixture
* Venue/stadium name
"""
from __future__ import annotations

from typing import Any

from fpl_tool_contract import tool_resolve_player
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default number of upcoming fixtures to return.
DEFAULT_HORIZON: int = 5

#: Maximum allowed horizon (bounds the output list).
_MAX_HORIZON: int = 10


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def _get_current_gameweek(bootstrap: dict[str, Any]) -> int | None:
    """Return the current GW id from bootstrap events, or None."""
    for ev in bootstrap.get("events", []):
        if ev.get("is_current"):
            return int(ev["id"])
    return None


def _team_short_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    """Build a team_id → short_name lookup from bootstrap["teams"]."""
    return {
        int(t["id"]): str(t.get("short_name", f"T{t['id']}"))
        for t in bootstrap.get("teams", [])
    }


def _position_label(element_type: int) -> str:
    """Map FPL element_type int (1-4) to a position string."""
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(element_type, "UNK")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_player_fixture_run(
    query: str,
    bootstrap: dict[str, Any],
    horizon: int = DEFAULT_HORIZON,
) -> dict[str, Any]:
    """Retrieve a player's upcoming fixture run from bootstrap data.

    Resolves the player, looks up their team's fixture schedule from
    ``bootstrap["team_fixtures"]``, and returns the next ``horizon``
    fixtures from the current gameweek onwards.

    Parameters
    ----------
    query:
        Player name, web_name, alias, or numeric FPL element id.
    bootstrap:
        Raw FPL bootstrap dict.  Must contain a ``team_fixtures`` key with
        per-team fixture lists.  Falls back to ``status="missing_context"``
        when this key is absent.
    horizon:
        Number of upcoming fixtures to return (default 5, clamped to 1–10).

    Returns
    -------
    dict
        Always returned -- never raises.  Inspect ``"status"`` to detect
        errors.

    Examples
    --------
    >>> from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    >>> result = get_player_fixture_run("Haaland", STANDARD_BOOTSTRAP)
    >>> result["status"]
    'ok'
    >>> len(result["fixtures"])
    5
    """
    horizon = max(1, min(horizon, _MAX_HORIZON))

    # -- Player resolution ---------------------------------------------------
    resolve = tool_resolve_player(query, bootstrap)
    if resolve["status"] != "ok":
        return {
            "status":  resolve["status"],
            "query":   query,
            "message": resolve.get("message", f"Player '{query}' not found."),
        }

    player_id = resolve["player_id"]
    web_name  = resolve.get("web_name", query)

    # Retrieve the element for team and position
    element = next(
        (el for el in bootstrap.get("elements", []) if el.get("id") == player_id),
        None,
    )
    if element is None:
        return {
            "status":  "error",
            "query":   query,
            "message": f"Element data not found for player_id {player_id}.",
        }

    team_id   = int(element.get("team", 0))
    position  = _position_label(int(element.get("element_type", 0)))

    # -- Team short name lookup ----------------------------------------------
    short_map  = _team_short_map(bootstrap)
    team_short = short_map.get(team_id, f"T{team_id}")

    # -- Fixture data --------------------------------------------------------
    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    if not team_fixtures:
        return {
            "status":   "missing_context",
            "query":    query,
            "web_name": web_name,
            "message":  (
                "No fixture schedule available "
                "(team_fixtures not in bootstrap)."
            ),
        }

    # Keys may be int or str depending on the bootstrap source
    fixture_list: list[dict[str, Any]] | None = (
        team_fixtures.get(team_id)
        or team_fixtures.get(str(team_id))    # type: ignore[arg-type]
    )
    if not fixture_list:
        return {
            "status":   "missing_context",
            "query":    query,
            "web_name": web_name,
            "message":  (
                f"No fixture schedule available for {team_short} "
                f"(team id {team_id})."
            ),
        }

    # -- Filter and sort to upcoming fixtures --------------------------------
    current_gw = _get_current_gameweek(bootstrap)
    upcoming   = [
        f for f in fixture_list
        if current_gw is None or int(f["gameweek"]) >= current_gw
    ]
    upcoming.sort(key=lambda f: int(f["gameweek"]))
    upcoming = upcoming[:horizon]

    # -- Build structured fixture output -------------------------------------
    fixtures_out: list[dict[str, Any]] = []
    for fx in upcoming:
        opp_id    = int(fx.get("opponent_team", 0))
        opp_short = short_map.get(opp_id, f"T{opp_id}")
        is_home   = bool(fx.get("is_home", False))
        difficulty = int(fx.get("difficulty", 3))
        fixtures_out.append({
            "gameweek":       int(fx["gameweek"]),
            "opponent_short": opp_short,
            "is_home":        is_home,
            "difficulty":     difficulty,
        })

    return {
        "status":           "ok",
        "query":            query,
        "web_name":         web_name,
        "team_short":       team_short,
        "position":         position,
        "horizon":          len(fixtures_out),
        "current_gameweek": current_gw,
        "fixtures":         fixtures_out,
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

PLAYER_FIXTURE_RUN_SPEC = ToolSpec(
    name="get_player_fixture_run",
    description=(
        "Retrieve a player's upcoming fixture run from bootstrap data. "
        "Returns a bounded list of upcoming fixtures (gameweek, opponent, "
        "home/away, difficulty) for the player's team. "
        "Default horizon is 5 fixtures. "
        "Returns status='not_found' or status='ambiguous' if the player cannot "
        "be uniquely resolved. "
        "Returns status='missing_context' if fixture schedule data is not "
        "available in bootstrap (team_fixtures key absent or team not covered)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type":        "string",
                "description": (
                    "Player name, web_name, alias, or FPL element id."
                ),
            },
        },
        "required": ["query"],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type":  "object",
                "required": ["status", "query", "web_name", "team_short",
                             "position", "horizon", "fixtures"],
                "properties": {
                    "status":          {"type": "string", "enum": ["ok"]},
                    "query":           {"type": "string"},
                    "web_name":        {"type": "string"},
                    "team_short":      {"type": "string"},
                    "position":        {"type": "string"},
                    "horizon":         {"type": "integer"},
                    "current_gameweek": {"type": ["integer", "null"]},
                    "fixtures": {
                        "type":  "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "gameweek":       {"type": "integer"},
                                "opponent_short": {"type": "string"},
                                "is_home":        {"type": "boolean"},
                                "difficulty":     {"type": "integer"},
                            },
                        },
                    },
                },
            },
            {
                "title": "error",
                "type":  "object",
                "required": ["status", "query", "message"],
                "properties": {
                    "status":  {
                        "type": "string",
                        "enum": ["not_found", "ambiguous",
                                 "missing_context", "error"],
                    },
                    "query":   {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        ],
    },
)


def _get_player_fixture_run_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_player_fixture_run()``."""
    return get_player_fixture_run(args["query"], bootstrap)


# Register with the shared tool registry so run_tool("get_player_fixture_run", ...) works.
TOOL_REGISTRY.register(PLAYER_FIXTURE_RUN_SPEC, _get_player_fixture_run_handler)
