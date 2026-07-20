"""Provider-neutral FI-5b(a) canonical scheduling and standings context."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 2
STATUSES = frozenset({"scheduled", "live", "completed", "postponed", "cancelled", "abandoned", "unknown"})
TIERS = frozenset({"league", "domestic_cup", "continental", "unknown"})
STAGES = frozenset({"league", "qualification", "group", "league_phase", "round_of_32", "round_of_16", "quarter_final", "semi_final", "final", "replay", "unknown"})
BANDS = ("top", "upper_mid", "lower_mid", "bottom")
TRACE = (("source_provider", "string", False), ("source_timestamp", "string", False),
         ("assumption_status", "string", False), ("schema_version", "Int64", False))
SCHEMAS = {
    "competitions": (("competition_id", "string", False),) + TRACE,
    "seasons": (("season_id", "string", False), ("competition_id", "string", False)) + TRACE,
    "teams": (("team_id", "string", False),) + TRACE,
    "fixtures": (("fixture_id", "string", False), ("competition_id", "string", False),
                 ("season_id", "string", False), ("home_team_id", "string", False),
                 ("away_team_id", "string", False), ("competition_stage", "string", False)) + TRACE,
    "competition_memberships": (("competition_id", "string", False), ("season_id", "string", False),
        ("team_id", "string", False), ("effective_from_utc", "string", False),
        ("effective_to_utc", "string", True)) + TRACE,
    "fixture_schedule_snapshots": (("fixture_id", "string", False), ("observed_at_utc", "string", False),
        ("scheduled_kickoff_utc", "string", False), ("status", "string", False),
        ("competition_tier", "string", False)) + TRACE,
    "team_standing_snapshots": (("competition_id", "string", False), ("season_id", "string", False),
        ("as_of_utc", "string", False), ("team_id", "string", False), ("observed_position", "Int64", True),
        ("played", "Int64", False), ("wins", "Int64", False), ("draws", "Int64", False),
        ("losses", "Int64", False), ("goals_for", "Int64", False), ("goals_against", "Int64", False),
        ("goal_difference", "Int64", False), ("points_before_deduction", "Int64", False),
        ("points_deduction", "Int64", False)) + TRACE,
}
PRIMARY_KEYS = {
    "competitions": ("competition_id",), "seasons": ("season_id",), "teams": ("team_id",),
    "fixtures": ("fixture_id",),
    "competition_memberships": ("competition_id", "season_id", "team_id", "effective_from_utc"),
    "fixture_schedule_snapshots": ("fixture_id", "observed_at_utc"),
    "team_standing_snapshots": ("competition_id", "season_id", "as_of_utc", "team_id"),
}

class ContextValidationError(ValueError):
    """A canonical v2 context contract was violated."""

def utc(value: object, label: str) -> str:
    if not isinstance(value, str): raise ContextValidationError(f"{label} must be UTC ISO text")
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc: raise ContextValidationError(f"{label} must be UTC ISO text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContextValidationError(f"{label} must be UTC aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _collapse(name: str, rows: Iterable[dict]) -> tuple[dict, ...]:
    normalized: dict[tuple, dict] = {}
    for raw in rows:
        row = {column: raw.get(column) for column, _, _ in SCHEMAS[name]}
        for column in ("observed_at_utc", "as_of_utc", "scheduled_kickoff_utc", "effective_from_utc", "source_timestamp"):
            if column in row and row[column] is not None: row[column] = utc(row[column], f"{name}.{column}")
        if row.get("effective_to_utc") is not None: row["effective_to_utc"] = utc(row["effective_to_utc"], f"{name}.effective_to_utc")
        row["schema_version"] = SCHEMA_VERSION
        key = tuple(row[field] for field in PRIMARY_KEYS[name])
        if key in normalized and normalized[key] != row:
            raise ContextValidationError(f"conflicting canonical primary key: {name} {key}")
        normalized[key] = row
    return tuple(normalized[key] for key in sorted(normalized))

def normalize_context(payload: dict) -> tuple[dict[str, tuple[dict, ...]], tuple[dict, ...]]:
    if set(SCHEMAS) - set(payload): raise ContextValidationError("missing canonical v2 dataset")
    tables = {name: _collapse(name, payload[name]) for name in SCHEMAS}
    validate_tables(tables)
    return tables, standings_warnings(tables["team_standing_snapshots"], tables["competition_memberships"])

def active_teams(memberships: Iterable[dict], competition_id: str, season_id: str, at_utc: str) -> tuple[str, ...]:
    at = utc(at_utc, "membership timestamp")
    selected = []
    for row in memberships:
        if row["competition_id"] == competition_id and row["season_id"] == season_id and row["effective_from_utc"] <= at and (row["effective_to_utc"] is None or at < row["effective_to_utc"]):
            selected.append(row["team_id"])
    if len(selected) != len(set(selected)): raise ContextValidationError("overlapping effective memberships")
    return tuple(sorted(selected))

def _valid_standing_table(rows: tuple[dict, ...], memberships: Iterable[dict]) -> bool:
    if not rows: return False
    first = rows[0]; expected = active_teams(memberships, first["competition_id"], first["season_id"], first["as_of_utc"])
    if tuple(sorted(row["team_id"] for row in rows)) != expected: return False
    n = len(rows); positions = [row["observed_position"] for row in rows if row["observed_position"] is not None]
    if len(positions) != len(set(positions)) or any(value < 1 or value > n for value in positions): return False
    for row in rows:
        values = [row[k] for k in ("played", "wins", "draws", "losses", "goals_for", "goals_against", "goal_difference", "points_before_deduction", "points_deduction")]
        if any(value is None or not isinstance(value, int) for value in values): return False
        if any(row[k] < 0 for k in ("played", "wins", "draws", "losses", "goals_for", "goals_against", "points_deduction")): return False
        if row["played"] != row["wins"] + row["draws"] + row["losses"]: return False
        if row["goal_difference"] != row["goals_for"] - row["goals_against"]: return False
    return True

def rank_table(rows: Iterable[dict]) -> tuple[dict, ...]:
    ranked = sorted(rows, key=lambda r: (-(r["points_before_deduction"] - r["points_deduction"]), -r["goal_difference"], -r["goals_for"], -r["wins"], r["team_id"]))
    n = len(ranked)
    return tuple({**row, "recomputed_rank": index, "league_position_band": BANDS[math.floor(4 * (index - 1) / n)]} for index, row in enumerate(ranked, 1))

def standings_warnings(rows: Iterable[dict], memberships: Iterable[dict]) -> tuple[dict, ...]:
    grouped: dict[tuple, list[dict]] = {}
    for row in rows: grouped.setdefault((row["competition_id"], row["season_id"], row["as_of_utc"]), []).append(row)
    warnings = []
    for key in sorted(grouped):
        group = tuple(grouped[key])
        if _valid_standing_table(group, memberships):
            for row in rank_table(group):
                if row["observed_position"] is not None and row["observed_position"] != row["recomputed_rank"]:
                    warnings.append({"reason": "observed_position_mismatch", "competition_id": key[0], "season_id": key[1], "as_of_utc": key[2], "team_id": row["team_id"]})
    return tuple(sorted(warnings, key=lambda x: tuple(x.values())))

def select_schedule(rows: Iterable[dict], cutoff_utc: str) -> tuple[dict, ...]:
    cutoff = utc(cutoff_utc, "cutoff_utc"); chosen = {}
    for row in rows:
        if row["observed_at_utc"] < cutoff and (row["fixture_id"] not in chosen or row["observed_at_utc"] > chosen[row["fixture_id"]]["observed_at_utc"]): chosen[row["fixture_id"]] = row
    return tuple(chosen[key] for key in sorted(chosen))

def select_standings(rows: Iterable[dict], memberships: Iterable[dict], competition_id: str, season_id: str, cutoff_utc: str) -> tuple[dict, ...]:
    cutoff = utc(cutoff_utc, "cutoff_utc"); grouped = {}
    for row in rows:
        if row["competition_id"] == competition_id and row["season_id"] == season_id and row["as_of_utc"] < cutoff:
            grouped.setdefault(row["as_of_utc"], []).append(row)
    for timestamp in sorted(grouped, reverse=True):
        group = tuple(grouped[timestamp])
        if _valid_standing_table(group, memberships): return rank_table(group)
    return ()

def validate_tables(tables: dict[str, tuple[dict, ...]]) -> None:
    competitions = {r["competition_id"] for r in tables["competitions"]}; seasons = {r["season_id"]: r["competition_id"] for r in tables["seasons"]}; teams = {r["team_id"] for r in tables["teams"]}; fixtures = {r["fixture_id"] for r in tables["fixtures"]}
    for row in tables["fixtures"]:
        if row["competition_stage"] not in STAGES: raise ContextValidationError("invalid competition stage")
        if row["competition_id"] not in competitions or seasons.get(row["season_id"]) != row["competition_id"] or row["home_team_id"] not in teams or row["away_team_id"] not in teams: raise ContextValidationError("fixture foreign key failure")
    for row in tables["competition_memberships"]:
        if row["competition_id"] not in competitions or seasons.get(row["season_id"]) != row["competition_id"] or row["team_id"] not in teams: raise ContextValidationError("membership foreign key failure")
        if row["effective_to_utc"] is not None and row["effective_to_utc"] <= row["effective_from_utc"]: raise ContextValidationError("invalid membership interval")
    membership_groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in tables["competition_memberships"]:
        membership_groups.setdefault((row["competition_id"], row["season_id"], row["team_id"]), []).append(row)
    for key, rows in membership_groups.items():
        ordered = sorted(rows, key=lambda row: row["effective_from_utc"])
        for previous, current in zip(ordered, ordered[1:]):
            if previous["effective_to_utc"] is None or current["effective_from_utc"] < previous["effective_to_utc"]:
                raise ContextValidationError(f"overlapping effective memberships: {key}")
    for row in tables["fixture_schedule_snapshots"]:
        if row["fixture_id"] not in fixtures: raise ContextValidationError("schedule fixture foreign key failure")
        if row["status"] not in STATUSES or row["competition_tier"] not in TIERS: raise ContextValidationError("invalid schedule vocabulary")
    for row in tables["team_standing_snapshots"]:
        if row["competition_id"] not in competitions or seasons.get(row["season_id"]) != row["competition_id"] or row["team_id"] not in teams: raise ContextValidationError("standing foreign key failure")
        if row["points_before_deduction"] < 0: raise ContextValidationError("points_before_deduction must be nonnegative")

def frame(name: str, rows: tuple[dict, ...]) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=[c for c, _, _ in SCHEMAS[name]])
    for column, dtype, nullable in SCHEMAS[name]:
        result[column] = result[column].astype(dtype)
        if not nullable and result[column].isna().any(): raise ContextValidationError(f"null {name}.{column}")
    return result.sort_values(list(PRIMARY_KEYS[name]), kind="mergesort").reset_index(drop=True)

def semantic_hash(value: pd.DataFrame) -> str:
    records = value.astype(object).where(pd.notna(value), None).to_dict("records")
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
