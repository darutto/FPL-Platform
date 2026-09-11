"""
fpl_grounded_assistant.zonal_weakness_tool
==========================================
Tactical track (T2b / T4a reach) — orchestrator tool wrappers for the
zonal-weakness engine.

This is the **only** place ``TOOL_REGISTRY`` is touched for the tactical
track — the engine in ``zonal_weakness.py`` stays pure and side-effect-free,
mirroring the Track D ``fixture_outlook`` / ``fixture_outlook_tool`` split.
Importing this module (done by ``__init__.py``) registers
``get_zonal_weakness`` and ``get_zonal_opportunity`` so ``run_tool(...)``
works and the orchestrator can reach them from plain-text questions.

Atomic-tool pattern: the LLM-facing schemas live in
``tool_schema_registry`` (``GET_ZONAL_WEAKNESS_SCHEMA`` /
``GET_ZONAL_OPPORTUNITY_SCHEMA``, members of ``_ALL_SCHEMAS``) and the tools
are deliberately kept OUT of ``SUPPORTED_INTENTS`` / the classifier.
T4b partial promotion: ``get_zonal_opportunity`` alone is additionally
mapped in ``_TOOL_TO_INTENT`` (intent ``zonal_opportunity``) so its payload
projects to ``DefensiveZonesMeta`` and the UI renders the Defensive Zones
card; ``get_zonal_weakness`` / ``get_player_zonal_outlook`` stay
text-narrated by the orchestrator.

Handlers return ``status ∈ {ok, not_found, missing_context}`` and never
raise into the orchestrator: an absent tactical store (or any unexpected
engine failure) degrades to ``missing_context``.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .zonal_weakness import (
    get_player_zonal_outlook,
    get_zonal_opportunity,
    get_zonal_weakness,
)
# Reuse the proven team-name resolver (name / short_name / alias) and the
# current-GW helper (fixtures come from bootstrap["team_fixtures"]).
from .player_matching import resolve_fpl_player
from .team_fixture_calendar import (
    _TEAM_RESOLVE_ALIASES,
    _get_current_gameweek,
    _resolve_team,
)

# ---------------------------------------------------------------------------
# i74 — the season the stamp is checked AGAINST comes from the live bootstrap,
# never from the store key. ``fpl_tactical.paths.CURRENT_SEASON`` *is* the
# store key by construction, so comparing the store against it reports "up to
# date" unconditionally — including today, which is exactly the case the
# warning exists to catch. ``derive_live_season`` reads GW1's deadline out of
# bootstrap-static and is the same function the capture guard already uses.
# sys.path shim mirrors owned_store_fallback.py (no pyproject in this repo).
# ---------------------------------------------------------------------------
_FPL_HISTORICAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fpl-historical",
)
if _FPL_HISTORICAL not in sys.path:
    sys.path.append(_FPL_HISTORICAL)

try:
    from fpl_historical.season_guard import derive_live_season  # type: ignore[import]
except ImportError:  # pragma: no cover - fpl-historical absent on this deploy
    derive_live_season = None  # type: ignore[assignment]


def _live_season(bootstrap: dict[str, Any] | None) -> str | None:
    """Season the FPL API is currently serving, or None when unverifiable.

    Never falls back to a stored season constant: "cannot verify" is a real,
    separately-labelled state, and guessing here would silently restore the
    tautology this whole stamp exists to break.
    """
    if derive_live_season is None or not bootstrap:
        return None
    try:
        return derive_live_season(bootstrap)
    except Exception:  # noqa: BLE001 — never raise into the orchestrator
        return None

# ---------------------------------------------------------------------------
# FPL bootstrap → Understat store team naming bridge.
# _resolve_team canonicalises free text to a bootstrap team dict, but the
# tactical store keeps Understat titles ("Manchester City", not "Man City").
# Keyed by FPL short_name (stable), values are Understat titles as stored.
# ---------------------------------------------------------------------------
# Grows across rollovers rather than tracking one season's roster exactly:
# a promoted team's short code is added when it needs one, and a relegated
# team's entry is left in place rather than deleted, because other code
# (and tests) may still reference a team that isn't in this season's top
# flight. Updated 2026-09 (i83, season rollover to 2026-27): added Coventry,
# Hull and Ipswich (Understat's own short-form titles for these three,
# confirmed against the live tactical store's actual team column -- NOT
# their FPL bootstrap display names "Coventry City"/"Hull City"/"Ipswich
# Town", which don't match Understat's naming and were the original cause
# of this gap: those three teams silently returned not_found for the
# entire 2026-27 season opening until this fix.
_SHORT_TO_UNDERSTAT: dict[str, str] = {
    "ARS": "Arsenal",
    "AVL": "Aston Villa",
    "BOU": "Bournemouth",
    "BRE": "Brentford",
    "BHA": "Brighton",
    "BUR": "Burnley",
    "CHE": "Chelsea",
    "COV": "Coventry",          # promoted 2026-27
    "CRY": "Crystal Palace",
    "EVE": "Everton",
    "FUL": "Fulham",
    "HUL": "Hull",              # promoted 2026-27
    "IPS": "Ipswich",           # promoted 2026-27
    "LEE": "Leeds",
    "LIV": "Liverpool",
    "MCI": "Manchester City",
    "MUN": "Manchester United",
    "NEW": "Newcastle United",
    "NFO": "Nottingham Forest",
    "SUN": "Sunderland",
    "TOT": "Tottenham",
    "WHU": "West Ham",
    "WOL": "Wolverhampton Wanderers",
}


# Inverted bridge for the T4b card: store (Understat) team name → FPL short.
_UNDERSTAT_TO_SHORT: dict[str, str] = {
    v.lower(): k for k, v in _SHORT_TO_UNDERSTAT.items()
}

_POSITION_SHORT: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _enrich_exploiters(
    exploiters: list[dict[str, Any]], bootstrap: dict[str, Any]
) -> list[dict[str, Any]]:
    """Best-effort FPL enrichment of engine exploiter rows (T4b card).

    Adds ``team_short`` (store team name → FPL short via the inverted
    ``_SHORT_TO_UNDERSTAT`` bridge) and ``web_name`` / ``position`` via the
    shared accent-robust matcher (``player_matching.resolve_fpl_player``:
    full name → web_name → second_name, ambiguous surnames never guessed).

    Degrade gracefully: unmatched players keep the store name as
    ``web_name`` and get ``position: ""``; a player is never dropped.
    """
    out: list[dict[str, Any]] = []
    for entry in exploiters:
        e = dict(entry)
        e["team_short"] = _UNDERSTAT_TO_SHORT.get(str(e.get("team", "")).lower(), "")
        el = resolve_fpl_player(str(e.get("player", "")), bootstrap)
        if el is not None:
            e["web_name"] = str(el.get("web_name") or e.get("player", ""))
            e["position"] = _POSITION_SHORT.get(el.get("element_type"), "")
        else:
            e["web_name"] = str(e.get("player", ""))
            e["position"] = ""
        out.append(e)
    return out


def _to_store_team(team_query: str, bootstrap: dict[str, Any]) -> str:
    """Best-effort translation of free text into a store (Understat) team name.

    Resolution: bootstrap resolver first (aliases / short names), bridged via
    short_name; falls back to the raw query — the engine matches store names
    case-insensitively, so Understat-style names pass straight through.
    """
    team = _resolve_team(team_query, bootstrap or {})
    if team is not None:
        short = str(team.get("short_name", "")).upper()
        if short in _SHORT_TO_UNDERSTAT:
            return _SHORT_TO_UNDERSTAT[short]
        name = team.get("name")
        if name:
            return str(name)
    return team_query


# ---------------------------------------------------------------------------
# i86 — deterministic subject-team inference for get_zonal_opportunity.
#
# The `team` parameter (i85) is correct when passed, but the orchestrator
# is not reliable about passing it: measured live 2026-09-11, "¿Qué
# jugadores de liverpool pueden explotar las zonas débiles del Fulham?"
# was still dispatched as {opponent: Fulham} with no `team`, even with the
# schema description spelling out exactly that case. A team the user
# literally named is a fact, not a modelling choice, so the handler reads
# the original question (exposed by ask_orchestrated() under the key
# below) and backfills `team` when the question unambiguously names ONE
# team other than the opponent. Anything less than unambiguous -- no other
# team, two other teams, an opponent that didn't resolve -- leaves the
# model's arguments untouched: this must never invent a filter.
# ---------------------------------------------------------------------------

#: Must equal orchestrator.QUESTION_CONTEXT_KEY (pinned by a test; spelled
#: here to avoid importing the orchestrator from a tool module).
_QUESTION_KEY: str = "_question"


def _mentioned_teams(question: str, bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    """Bootstrap teams named anywhere in *question*, deduped by short_name.

    Matches, all as whole words/phrases:
    - a team's bootstrap ``name`` (case-insensitive);
    - an alias from ``_TEAM_RESOLVE_ALIASES`` (case-insensitive), resolved
      through the same resolver every team tool uses;
    - a ``short_name`` code, UPPERCASE ONLY in the original text ("LIV"),
      because lowercase three-letter codes collide with ordinary words
      ("sun", "new", "lee", "eve", "che").
    """
    teams = (bootstrap or {}).get("teams", []) or []
    q_lower = question.lower()
    found: dict[str, dict[str, Any]] = {}

    def _phrase_in(phrase: str, text: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None

    for t in teams:
        short = str(t.get("short_name", "") or "")
        name = str(t.get("name", "") or "").lower()
        if name and _phrase_in(name, q_lower):
            found[short] = t
        elif short and re.search(rf"(?<!\w){re.escape(short)}(?!\w)", question):
            found[short] = t
    for alias, code in _TEAM_RESOLVE_ALIASES.items():
        if _phrase_in(alias, q_lower):
            t = _resolve_team(code, bootstrap or {})
            if t is not None:
                found.setdefault(str(t.get("short_name", "") or ""), t)
    return list(found.values())


def infer_subject_team(
    question: str, opponent_query: str, bootstrap: dict[str, Any]
) -> str | None:
    """The one team, other than *opponent_query*, that *question* names.

    Returns that team's ``short_name``, or ``None`` when the question names
    no other team, more than one, or when the opponent itself doesn't
    resolve (then every mention could be the opponent under another name,
    and guessing would filter to the wrong side).
    """
    if not question:
        return None
    opponent = _resolve_team(opponent_query, bootstrap or {})
    if opponent is None:
        return None
    opp_short = str(opponent.get("short_name", "") or "")
    others = [
        t for t in _mentioned_teams(question, bootstrap)
        if str(t.get("short_name", "") or "") != opp_short
    ]
    if len(others) != 1:
        return None
    return str(others[0].get("short_name", "") or "") or None


def _get_zonal_weakness_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine. Never raises."""
    team_query = str(args.get("team", "") or "").strip()
    if not team_query:
        return {"status": "not_found", "team": "", "message": "No team given."}
    try:
        result = get_zonal_weakness(
            _to_store_team(team_query, bootstrap),
            live_season=_live_season(bootstrap),
        )
    except Exception as exc:  # noqa: BLE001 — never raise into the orchestrator
        return {"status": "missing_context", "team": team_query, "message": str(exc)}
    if result["status"] == "not_found":
        result["message"] = f"No zonal data for '{team_query}' in the tactical store."
    elif result["status"] == "missing_context":
        result["message"] = (
            "Tactical (Understat zonal) store not available on this deployment."
        )
    return result


def _get_zonal_opportunity_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine. Never raises."""
    opponent_query = str(args.get("opponent", "") or "").strip()
    if not opponent_query:
        return {"status": "not_found", "opponent": "", "message": "No opponent given."}
    team_query = str(args.get("team", "") or "").strip()
    team_source = "explicit" if team_query else None
    if not team_query:
        # i86: the model omitted `team`; if the user's own question names
        # exactly one other team, that is the filter they asked for.
        inferred = infer_subject_team(
            str((bootstrap or {}).get(_QUESTION_KEY, "") or ""),
            opponent_query,
            bootstrap,
        )
        if inferred:
            team_query = inferred
            team_source = "inferred"
    try:
        result = get_zonal_opportunity(
            _to_store_team(opponent_query, bootstrap),
            team=_to_store_team(team_query, bootstrap) if team_query else None,
            live_season=_live_season(bootstrap),
        )
    except Exception as exc:  # noqa: BLE001 — never raise into the orchestrator
        return {
            "status": "missing_context", "opponent": opponent_query,
            "message": str(exc),
        }
    if result["status"] == "not_found":
        result["message"] = (
            f"No zonal data for '{opponent_query}' in the tactical store."
        )
    elif result["status"] == "missing_context":
        result["message"] = (
            "Tactical (Understat zonal) store not available on this deployment."
        )
    elif result["status"] == "ok":
        if result.get("exploiters"):
            result["exploiters"] = _enrich_exploiters(result["exploiters"], bootstrap)
        tf = result.get("team_filter")
        if tf is not None:
            # Provenance of the filter: did the model pass it, or did the
            # handler recover it from the question the model was given?
            tf["source"] = team_source
            if tf["matched"] is None:
                result["message"] = (
                    f"'{team_query}' did not match any team in the tactical store — "
                    f"exploiters/opportunities are empty, not unfiltered."
                )
    return result


GET_ZONAL_WEAKNESS_SPEC = ToolSpec(
    name="get_zonal_weakness",
    description=(
        "Use only when the user asks purely which zones a team concedes in, "
        "with no mention of players or exploiting (those → "
        "get_zonal_opportunity). Where the attacking opportunity is per zone: "
        "xGA/game vs league baseline, owned Understat data; penalties "
        "excluded and reported separately. Opportunity read only — no buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team": {
                "type":        "string",
                "description": "Team name / short_name / alias (e.g. 'Crystal Palace', 'CRY').",
            },
        },
        "required":             ["team"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":          {"type": "string"},
            "team":            {"type": "string"},
            "zones":           {"type": "array"},
            "weakest_zones":   {"type": "array"},
            "penalty_context": {"type": "object"},
            "verdict":         {"type": "string"},
            "data_provenance": {"type": "object"},  # i74 season stamp
        },
    },
)

GET_ZONAL_OPPORTUNITY_SPEC = ToolSpec(
    name="get_zonal_opportunity",
    description=(
        "Use whenever the user asks who/which players can exploit or attack "
        "an opponent's weak zones — even if the question also asks which "
        "zones they concede. Primary tool for any 'zones + players' question: "
        "where to attack WITH the matched players to exploit each zone. "
        "Opportunity signal only — no buy/sell advice. If the user asks about "
        "a SPECIFIC team's players (e.g. 'which Liverpool players can exploit "
        "Fulham'), pass `team` — without it, the ranking is unfiltered across "
        "the whole league and may contain zero players from the team the user "
        "actually asked about even when some exist; that is NOT the same as "
        "'no such player.'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "opponent": {
                "type":        "string",
                "description": "Opposing team name / short_name / alias whose defence to probe.",
            },
            "team": {
                "type":        "string",
                "description": (
                    "Optional. Team name / short_name / alias to restrict the "
                    "exploiter ranking to — only that team's players are "
                    "considered. Omit for an unfiltered, league-wide ranking."
                ),
            },
        },
        "required":             ["opponent"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":          {"type": "string"},
            "opponent":        {"type": "string"},
            "opportunities":   {"type": "array"},
            "zones":           {"type": "array"},   # T4b: 3 in-box lateral cells
            "exploiters":      {"type": "array"},   # T4b: ranked zone-fit table
            "team_filter":     {"type": "object"},  # i85/i86: {requested, matched, source}; present when `team` was given or inferred from the question
            "weakness_label":  {"type": "string"},  # T4b
            "verdict":         {"type": "string"},  # T4b
            "penalty_context": {"type": "object"},  # T4b
            "data_provenance": {"type": "object"},   # i74 season stamp
        },
    },
)


# ---------------------------------------------------------------------------
# T-player: player-centric zonal outlook over upcoming fixtures
# ---------------------------------------------------------------------------

#: GW lookahead for the player outlook (a 5-fixture report is a wall of text).
DEFAULT_OUTLOOK_HORIZON: int = 3
MAX_OUTLOOK_HORIZON: int = 5


def _team_to_store_name(team: dict[str, Any]) -> str:
    """Bridge one bootstrap team dict to its Understat store name."""
    short = str(team.get("short_name", "")).upper()
    return _SHORT_TO_UNDERSTAT.get(short) or str(team.get("name", ""))


def _get_player_zonal_outlook_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine. Never raises.

    The engine is bootstrap-agnostic: this wrapper injects a
    ``fixtures_for_team`` callback that reads ``bootstrap["team_fixtures"]``
    and translates opponent ids to Understat store names via the short-name
    bridge.
    """
    player_query = str(args.get("player", "") or "").strip()
    if not player_query:
        return {"status": "not_found", "player": "", "message": "No player given."}
    try:
        horizon = int(args.get("horizon", DEFAULT_OUTLOOK_HORIZON))
    except (TypeError, ValueError):
        horizon = DEFAULT_OUTLOOK_HORIZON
    horizon = max(1, min(horizon, MAX_OUTLOOK_HORIZON))

    bootstrap = bootstrap or {}
    team_fixtures: dict = bootstrap.get("team_fixtures") or {}
    current_gw = _get_current_gameweek(bootstrap)
    if not team_fixtures or current_gw is None:
        return {
            "status": "missing_context",
            "player": player_query,
            "message": (
                "No team fixture schedule available "
                "(team_fixtures/current GW not in bootstrap)."
            ),
        }

    teams_by_id: dict[int, dict[str, Any]] = {
        int(t["id"]): t for t in bootstrap.get("teams", []) if t.get("id") is not None
    }

    def fixtures_for_team(store_team_name: str) -> list[dict[str, Any]]:
        team_id = next(
            (
                tid for tid, t in teams_by_id.items()
                if _team_to_store_name(t).lower() == store_team_name.lower()
            ),
            None,
        )
        if team_id is None:
            return []
        raw = team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []
        window = sorted(
            (f for f in raw
             if current_gw <= int(f.get("gameweek", 0)) < current_gw + horizon),
            key=lambda f: int(f.get("gameweek", 0)),
        )
        out: list[dict[str, Any]] = []
        for f in window:
            opp = teams_by_id.get(int(f.get("opponent_team", 0)))
            out.append({
                "gameweek": int(f.get("gameweek", 0)),
                "opponent": _team_to_store_name(opp) if opp else str(f.get("opponent_team", "?")),
                "is_home": bool(f.get("is_home", False)),
            })
        return out

    try:
        result = get_player_zonal_outlook(
            player_query,
            fixtures_for_team=fixtures_for_team,
            live_season=_live_season(bootstrap),
        )
    except Exception as exc:  # noqa: BLE001 — never raise into the orchestrator
        return {"status": "missing_context", "player": player_query, "message": str(exc)}

    if result["status"] == "not_found":
        result["message"] = (
            f"No shot profile for '{player_query}' in the tactical store "
            f"(needs >=10 non-penalty shots this season)."
        )
    elif result["status"] == "ambiguous":
        result["message"] = (
            f"Multiple players match '{player_query}': "
            f"{', '.join(result.get('candidates', []))}."
        )
    elif result["status"] == "missing_context" and "message" not in result:
        result["message"] = (
            "Tactical store or upcoming fixtures unavailable for this player."
        )
    return result


GET_PLAYER_ZONAL_OUTLOOK_SPEC = ToolSpec(
    name="get_player_zonal_outlook",
    description=(
        "Use when the subject is a specific named player and whether their "
        "upcoming fixtures suit them zonally (do the next opponents' weak "
        "zones fit the player's shot profile). Per-GW favorable/neutral "
        "matchup read over the next 1-5 fixtures. Opportunity signal only — "
        "no buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player": {
                "type":        "string",
                "description": "Player name as known (e.g. 'Saka', 'Bukayo Saka').",
            },
            "horizon": {
                "type":        "integer",
                "description": "Upcoming GWs to analyse (1-5, default 3).",
            },
        },
        "required":             ["player"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":       {"type": "string"},
            "player":       {"type": "string"},
            "team":         {"type": "string"},
            "player_zones": {"type": "array"},
            "outlook":      {"type": "array"},
            "verdict":      {"type": "string"},
            "data_provenance": {"type": "object"},  # i74 season stamp
        },
    },
)


TOOL_REGISTRY.register(GET_ZONAL_WEAKNESS_SPEC, _get_zonal_weakness_handler)
TOOL_REGISTRY.register(GET_ZONAL_OPPORTUNITY_SPEC, _get_zonal_opportunity_handler)
TOOL_REGISTRY.register(GET_PLAYER_ZONAL_OUTLOOK_SPEC, _get_player_zonal_outlook_handler)
