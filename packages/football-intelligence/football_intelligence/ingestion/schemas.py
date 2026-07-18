"""Explicit ordered parquet schemas for the FI-4a canonical store."""
from __future__ import annotations

SCHEMA_VERSION = 1
TRACE = (
    ("source_provider", "string", False),
    ("source_provider_id", "string", False),
    ("source_timestamp", "string", True),
    ("ingestion_run_id", "string", False),
    ("schema_version", "Int64", False),
)

SCHEMAS = {
    "competitions": (("competition_id", "string", False), ("name", "string", False), ("tier", "string", False), ("country", "string", True)) + TRACE,
    "seasons": (("season_id", "string", False), ("competition_id", "string", False), ("edition_key", "string", False), ("label", "string", False)) + TRACE,
    "teams": (("team_id", "string", False), ("name", "string", False), ("short_code", "string", False)) + TRACE,
    "fixtures": (("fixture_id", "string", False), ("season_id", "string", False), ("competition_id", "string", False), ("home_team_id", "string", False), ("away_team_id", "string", False), ("fixture_key", "string", False), ("kickoff_utc", "string", False), ("status", "string", False), ("gameweek", "Int64", True)) + TRACE,
    "players": (("player_id", "string", False), ("full_name", "string", False), ("known_name", "string", False), ("birth_date", "string", True), ("nationality", "string", True), ("positions_nominal", "string", False)) + TRACE,
    "squads": (("team_id", "string", False), ("player_id", "string", False), ("valid_from", "string", False), ("valid_to", "string", True)) + TRACE,
    "lineups": (("fixture_id", "string", False), ("team_id", "string", False), ("player_id", "string", False), ("started", "boolean", False), ("minutes", "Int64", False), ("formation", "string", False), ("grid_slot", "string", True), ("detailed_position", "string", True)) + TRACE,
    "formations": (("fixture_id", "string", False), ("team_id", "string", False), ("formation_string", "string", False), ("formation_source_timestamp", "string", False)) + TRACE,
    "substitutions": (("fixture_id", "string", False), ("team_id", "string", False), ("player_off_id", "string", False), ("player_on_id", "string", False), ("minute", "Int64", False)) + TRACE,
    "injuries": (("player_id", "string", False), ("recorded_at_utc", "string", False), ("detail", "string", False), ("expected_return", "string", True), ("resolved_at_utc", "string", True)) + TRACE,
    "suspensions": (("player_id", "string", False), ("recorded_at_utc", "string", False), ("reason", "string", False), ("starts_on", "string", True), ("ends_on", "string", True), ("fixtures_remaining", "Int64", True)) + TRACE,
    "coaches": (("team_id", "string", False), ("name", "string", False)) + TRACE,
    "referees": (("fixture_id", "string", False), ("name", "string", False)) + TRACE,
    "team_fixture_statistics": (("fixture_id", "string", False), ("team_id", "string", False), ("possession_pct", "Float64", True), ("shots", "Int64", True), ("shots_on_target", "Int64", True), ("expected_goals", "Float64", True)) + TRACE,
    "player_fixture_statistics": (("fixture_id", "string", False), ("player_id", "string", False), ("team_id", "string", False), ("minutes", "Int64", False), ("goals", "Int64", False), ("assists", "Int64", False), ("shots", "Int64", True), ("expected_goals", "Float64", True), ("expected_assists", "Float64", True), ("tackles", "Int64", True), ("interceptions", "Int64", True)) + TRACE,
}

PRIMARY_KEYS = {
    "competitions": ("competition_id",), "seasons": ("season_id",),
    "teams": ("team_id",), "fixtures": ("fixture_id",), "players": ("player_id",),
    "squads": ("team_id", "player_id", "valid_from"),
    "lineups": ("fixture_id", "player_id"), "formations": ("fixture_id", "team_id"),
    "substitutions": ("fixture_id", "minute", "player_off_id", "player_on_id"),
    "injuries": ("player_id", "recorded_at_utc", "detail"),
    "suspensions": ("player_id", "recorded_at_utc", "reason"),
    "coaches": ("team_id", "name"), "referees": ("fixture_id", "name"),
    "team_fixture_statistics": ("fixture_id", "team_id"),
    "player_fixture_statistics": ("fixture_id", "player_id"),
}
