"""Sportmonks-mock to provider-neutral canonical row normalizers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from football_data_contract import (canonical_competition_id, canonical_fixture_id,
    canonical_player_id, canonical_season_id)

from .authority import select_player_authority
from .keys import validate_edition_key, validate_fixture_key
from .schemas import SCHEMA_VERSION, SCHEMAS
from .team_registry import TeamRegistry


@dataclass(frozen=True)
class NormalizationResult:
    tables: dict[str, tuple[dict, ...]]
    warnings: tuple[dict, ...]
    quarantine: tuple[dict, ...]
    source_version: str
    assumption_status: str
    captured_at: str


class NormalizationError(ValueError):
    """A local replay snapshot is structurally invalid."""


def normalize_fixture(path: Path, registry: TeamRegistry, build_id: str) -> NormalizationResult:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NormalizationError("malformed local replay JSON") from exc
    required_families = {"_fixture", "competition", "season", "teams", "owned_players",
        "player_crosswalks", "players", "fixtures", "squads", "lineups", "formations",
        "substitutions", "injuries", "suspensions", "coaches", "referees",
        "team_statistics", "player_statistics"}
    missing = sorted(required_families - set(source))
    if missing:
        raise NormalizationError(f"local replay missing required families: {', '.join(missing)}")
    if any(not isinstance(source[name], list) for name in required_families - {"_fixture", "competition", "season"}):
        raise NormalizationError("local replay entity families must be arrays")
    meta = source["_fixture"]
    tables: dict[str, list[dict]] = {name: [] for name in SCHEMAS}
    warnings: list[dict] = []
    quarantine: list[dict] = []

    def trace(provider_id, timestamp=None):
        return {"source_provider": "sportmonks", "source_provider_id": str(provider_id),
                "source_timestamp": timestamp, "ingestion_run_id": build_id,
                "schema_version": SCHEMA_VERSION}

    competition = source["competition"]
    competition_id = canonical_competition_id(competition["governing_body"], competition["registry_key"], competition["category"])
    tables["competitions"].append({"competition_id": competition_id, "name": competition["name"], "tier": competition["tier"], "country": competition.get("country"), **trace(competition["id"])})
    season = source["season"]
    edition_key = validate_edition_key(season["edition_key"])
    season_id = canonical_season_id(competition_id, edition_key)
    tables["seasons"].append({"season_id": season_id, "competition_id": competition_id, "edition_key": edition_key, "label": season["label"], **trace(season["id"])})

    team_ids: dict[str, str] = {}
    for raw in source["teams"]:
        team_id = registry.resolve("sportmonks", str(raw["id"]), meta["captured_at"][:10])
        if team_id is None:
            quarantine.append(_report("missing_team_mapping", "teams", raw["id"]))
            continue
        team_ids[str(raw["id"])] = team_id
        tables["teams"].append({"team_id": team_id, "name": raw["name"], "short_code": raw["short_code"], **trace(raw["id"])})

    owned = {row["fpl_id"]: row for row in source["owned_players"]}
    provider_to_fpl: dict[str, str] = {}
    ambiguous_provider_players: set[str] = set()
    for row in source["player_crosswalks"]:
        provider_id = row["sportmonks_id"]
        if provider_id in provider_to_fpl and provider_to_fpl[provider_id] != row["fpl_id"]:
            ambiguous_provider_players.add(provider_id)
        provider_to_fpl[provider_id] = row["fpl_id"]
    player_ids: dict[str, str] = {}
    for raw in source["players"]:
        provider_id = str(raw["id"])
        if provider_id in ambiguous_provider_players:
            quarantine.append(_report("ambiguous_player", "players", raw["id"]))
            continue
        fpl_id = provider_to_fpl.get(provider_id)
        authority = select_player_authority(owned.get(fpl_id), None, None) if fpl_id else None
        if authority is None:
            quarantine.append(_report("unmatched_player", "players", raw["id"]))
            continue
        player_id = canonical_player_id(authority["full_name"], authority.get("birth_date"))
        player_ids[str(raw["id"])] = player_id
        tables["players"].append({"player_id": player_id, "full_name": authority["full_name"], "known_name": authority["known_name"], "birth_date": authority.get("birth_date"), "nationality": authority.get("nationality"), "positions_nominal": json.dumps(authority.get("positions", []), separators=(",", ":")), **trace(raw["id"])})

    fixture_ids: dict[str, str] = {}
    for raw in source["fixtures"]:
        home = team_ids.get(str(raw["home_team_id"])); away = team_ids.get(str(raw["away_team_id"]))
        if not home or not away:
            quarantine.append(_report("missing_foreign_key", "fixtures", raw["id"])); continue
        if home == away:
            quarantine.append(_report("identical_fixture_teams", "fixtures", raw["id"])); continue
        key = validate_fixture_key(raw["fixture_key"])
        fixture_id = canonical_fixture_id(competition_id, season_id, home, away, key)
        fixture_ids[str(raw["id"])] = fixture_id
        status = raw.get("status", "unknown")
        if status not in {"scheduled", "live", "completed", "postponed", "cancelled", "abandoned", "unknown"}:
            warnings.append(_report("unknown_provider_fixture_status", "fixtures", raw["id"]))
            status = "unknown"
        tables["fixtures"].append({"fixture_id": fixture_id, "season_id": season_id, "competition_id": competition_id, "home_team_id": home, "away_team_id": away, "fixture_key": key, "kickoff_utc": raw["kickoff"], "status": status, "gameweek": raw.get("gameweek"), **trace(raw["id"], raw["kickoff"])})

    def refs(raw):
        return (fixture_ids.get(str(raw.get("fixture_id"))), team_ids.get(str(raw.get("team_id"))), player_ids.get(str(raw.get("player_id"))))
    for raw in source["squads"]:
        _, team, player = refs(raw)
        _append(tables, quarantine, "squads", raw, team and player, {"team_id": team, "player_id": player, "valid_from": raw["valid_from"], "valid_to": raw.get("valid_to"), **trace(raw["id"])})
    for raw in source["lineups"]:
        fixture, team, player = refs(raw)
        _append(tables, quarantine, "lineups", raw, fixture and team and player, {"fixture_id": fixture, "team_id": team, "player_id": player, "started": raw["started"], "minutes": raw["minutes"], "formation": raw["formation"], "grid_slot": raw.get("grid_slot"), "detailed_position": raw.get("position"), **trace(raw["id"])})
    for raw in source["formations"]:
        fixture, team, _ = refs(raw)
        _append(tables, quarantine, "formations", raw, fixture and team, {"fixture_id": fixture, "team_id": team, "formation_string": raw["formation"], "formation_source_timestamp": raw["source_timestamp"], **trace(raw["id"], raw["source_timestamp"])})
    for raw in source["substitutions"]:
        fixture, team, _ = refs(raw); off = player_ids.get(str(raw["player_off_id"])); on = player_ids.get(str(raw["player_on_id"]))
        _append(tables, quarantine, "substitutions", raw, fixture and team and off and on, {"fixture_id": fixture, "team_id": team, "player_off_id": off, "player_on_id": on, "minute": raw["minute"], **trace(raw["id"])})
    for family, fields in (("injuries", ("recorded_at", "detail", "expected_return", "resolved_at")), ("suspensions", ("recorded_at", "reason", "starts_on", "ends_on", "fixtures_remaining"))):
        for raw in source[family]:
            player = player_ids.get(str(raw["player_id"])); row = {"player_id": player, **trace(raw["id"])}
            for field in fields: row["recorded_at_utc" if field == "recorded_at" else "resolved_at_utc" if field == "resolved_at" else field] = raw.get(field)
            _append(tables, quarantine, family, raw, player, row)
    for family in ("coaches", "referees"):
        for raw in source[family]:
            fixture, team, _ = refs(raw); required = team if family == "coaches" else fixture
            row = ({"team_id": team} if family == "coaches" else {"fixture_id": fixture})
            _append(tables, quarantine, family, raw, required, {**row, "name": raw["name"], **trace(raw["id"])})
    for family, target in (("team_statistics", "team_fixture_statistics"), ("player_statistics", "player_fixture_statistics")):
        for raw in source[family]:
            fixture, team, player = refs(raw); required = fixture and team and (player if family == "player_statistics" else True)
            names = [item[0] for item in SCHEMAS[target] if item[0] not in {"source_provider", "source_provider_id", "source_timestamp", "ingestion_run_id", "schema_version"}]
            row = {name: raw.get(name) for name in names}; row.update({"fixture_id": fixture, "team_id": team})
            if family == "player_statistics": row["player_id"] = player
            _append(tables, quarantine, target, raw, required, {**row, **trace(raw["id"])})

    ordered = {name: tuple(sorted(rows, key=lambda row: tuple(str(row.get(field[0], "")) for field in SCHEMAS[name]))) for name, rows in tables.items()}
    return NormalizationResult(ordered, tuple(sorted(warnings, key=str)), tuple(sorted(quarantine, key=lambda row: (row["reason"], row["family"], row["provider_ref"]))), meta["version"], meta["assumption_status"], meta["captured_at"])


def _append(tables, quarantine, family, raw, valid, row):
    if not valid:
        quarantine.append(_report("missing_foreign_key", family, raw.get("id", "unknown")))
    else:
        tables[family].append(row)


def _report(reason, family, provider_id):
    return {"reason": reason, "family": family, "provider_ref": f"sportmonks/{provider_id}"}
