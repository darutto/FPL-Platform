"""get_tier_eo: effective ownership among the top 10,000 managers (a published sample).

Reads the file the scheduled sampler published to R2 (``tier_eo_reader``): one fast GET, so unlike the
near-rank and league tools there is no background job. Needs no connected team; with one, the answer also
compares the user's squad against the top 10K (the same two groups as the other EO cards).

Behind ``FPL_TIER_EO_ENABLED`` (default OFF): when off the tool is not offered and a direct call returns
``status="disabled"``. The data is from the picks of the gameweek the FILE says (the latest, or the one
before it when the latest is not published yet); the answer states which, never the requested one.

Registers ``get_tier_eo`` in ``TOOL_REGISTRY`` as a side-effect of import. Its LLM schema lives in
``tool_schema_registry.TIER_EO_SCHEMA`` (kept OUT of ``_ALL_SCHEMAS``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fpl_player_registry import normalize_player_name
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from . import tier_eo_reader
from .get_my_squad import load_linked_squad
from .near_rank_eo_tool import (
    MAX_NAMED,
    TOP_N,
    _name_index,
    _row,
    _season,
    gw_and_valid_until,
    owned_ids,
    squad_comparison,
    wording_note,
)
from .orch_config import is_tier_eo_enabled
from .tool_schema_registry import TIER_EO_SCHEMA

TIER = "top10k"


def shape_result(data: dict[str, Any], bootstrap: dict[str, Any], player_names: list[str],
                 squad: dict[str, Any] | None, requested_gw: int) -> dict[str, Any]:
    """The compact answer for the model; ``gw`` is the gameweek of the picks in the FILE."""
    by_id, teams = _name_index(bootstrap)
    players = data["players"]
    own = owned_ids(squad)
    top_ids = sorted(players, key=lambda k: players[k]["eo"], reverse=True)[:TOP_N]
    named_ids: list[str] = []
    for name in player_names[:MAX_NAMED]:
        wanted = normalize_player_name(name)
        if not wanted:
            continue
        for element_id, element in by_id.items():
            if element_id in players and wanted in (normalize_player_name(element.get("web_name")),
                                                    normalize_player_name(element.get("second_name"))):
                named_ids.append(element_id)
    gw = int(data["gw"])
    n = int(data.get("n_sampled") or 0)
    older = gw < requested_gw
    note = ("EO = how many copies of the player the top 10,000 managers hold, counting captains double; "
            f"a published sample (n={n}) of GW {gw} picks, so read it as approximate. ")
    if older:
        note += (f"These are the GW {gw} picks (the GW {requested_gw} sample is not published yet): "
                 "say so in one short clause. ")
    return {
        "status": "ok", "tier": TIER, "gw": gw, "requested_gw": requested_gw, "picks_from_older_gw": older,
        "approx": True, "n_sampled": n, "label": f"sample, n={n}",
        "top_players": [_row(i, players[i], by_id, teams, own) for i in top_ids],
        "named_players": [_row(i, players[i], by_id, teams, own) for i in dict.fromkeys(named_ids)],
        **squad_comparison(players, squad, by_id, teams),
        "note": note + wording_note("Top 10K has him", "El top 10K lo tiene"),
    }


def latest_gw_found(bootstrap: dict[str, Any] | None, now: datetime | None = None) -> int | None:
    """The gameweek of the newest readable file (this one or the one before), else None. For /healthz."""
    boot = bootstrap or {}
    gw, _ = gw_and_valid_until(boot.get("events") or [], now or datetime.now(timezone.utc))
    season = _season(boot)
    if gw is None or season is None:
        return None
    data = tier_eo_reader.get_reader().latest(season, gw, TIER)
    return int(data["gw"]) if data else None


def get_tier_eo(bootstrap: dict[str, Any] | None, *, player_names: list[str] | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    if not is_tier_eo_enabled():
        return {"status": "disabled", "code": "tier_eo_disabled"}
    boot = bootstrap or {}
    gw, _ = gw_and_valid_until(boot.get("events") or [], now or datetime.now(timezone.utc))
    season = _season(boot)
    if gw is None or season is None:
        return {"status": "unavailable", "reason": "no_gameweek"}
    data = tier_eo_reader.get_reader().latest(season, gw, TIER)
    if data is None:
        return {"status": "unavailable", "reason": "not_published_yet",
                "message": "The top 10K sample for this gameweek is not available yet; say so and do not guess numbers."}
    squad = None
    if boot.get("_my_team_id"):
        try:
            squad = load_linked_squad(boot, gw)  # one small FPL call (the user's own picks); None if it fails
        except Exception:  # noqa: BLE001
            squad = None
    return shape_result(data, boot, list(player_names or []), squad, gw)


TIER_EO_SPEC = ToolSpec(
    name="get_tier_eo",
    description=TIER_EO_SCHEMA.description,  # one text for the model, here and in the schema
    parameters={
        "type": "object",
        "properties": {
            "player_names": {
                "type": "array", "items": {"type": "string"}, "maxItems": MAX_NAMED,
                "description": "Players whose EO the user asked about (web names); optional.",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "tier": {"type": "string"},
            "gw": {"type": "integer"},
            "requested_gw": {"type": "integer"},
            "picks_from_older_gw": {"type": "boolean"},
            "n_sampled": {"type": "integer"},
            "label": {"type": "string"},
            "top_players": {"type": "array"},
            "named_players": {"type": "array"},
            "reason": {"type": "string"},
        },
    },
)


def _handler(args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    names = args.get("player_names")
    return get_tier_eo(bootstrap, player_names=[n for n in names if isinstance(n, str)] if isinstance(names, list) else None)


TOOL_REGISTRY.register(TIER_EO_SPEC, _handler)
