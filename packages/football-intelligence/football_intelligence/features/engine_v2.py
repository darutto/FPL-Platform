"""Deterministic FI-5b(b) sufficient-statistic computation."""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pandas as pd

from football_intelligence.distribution.runtime import RuntimeBuildHandle
from football_intelligence.ingestion.builder_v2 import validate_context_build
from football_intelligence.ingestion.context_v2 import select_schedule, select_standings
from .registry_v2 import (
    COMPETITION_WEIGHTS, COMPETITION_WEIGHT_VERSION, CUTOFF_POLICY_VERSION,
    ENGINE_VERSION, FEATURE_REGISTRY_VERSION, RECENCY_WEIGHT_VERSION,
    ROLE_MAPPING_VERSION,
)

ROLE_MAP = {
    "goalkeeper": ("goalkeeper", "center", "goalkeeper"),
    "central defender": ("center_back", "center", "defense"),
    "left back": ("full_back", "left", "defense"),
    "right back": ("full_back", "right", "defense"),
    "left wing": ("winger", "left", "attack"),
    "right wing": ("winger", "right", "attack"),
    "central midfield": ("central_midfield", "center", "midfield"),
    "centre forward": ("forward", "center", "attack"),
}


class FeatureV2InputError(ValueError):
    """Validated FI-5b(b) sources contradict one another."""


def _validate_shared_fixtures(base_fixtures, context_fixtures):
    fields = ("season_id", "competition_id", "home_team_id", "away_team_id")
    base_by_id = {str(row.fixture_id): row for row in base_fixtures.itertuples(index=False)}
    context_by_id = {str(row.fixture_id): row for row in context_fixtures.itertuples(index=False)}
    for fixture_id in sorted(set(base_by_id) & set(context_by_id)):
        base_row, context_row = base_by_id[fixture_id], context_by_id[fixture_id]
        conflicts = tuple(field for field in fields if str(getattr(base_row, field)) != str(getattr(context_row, field)))
        if conflicts:
            raise FeatureV2InputError(
                f"cross-source fixture contradiction: fixture_id={fixture_id}; fields={','.join(conflicts)}"
            )


def _utc(value):
    parsed = pd.Timestamp(value)
    return parsed.tz_convert("UTC") if parsed.tzinfo else parsed.tz_localize("UTC")


def _z(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_source(handle):
    manifest = handle.manifest()
    path = handle.cache_root / "builds" / manifest["build_id"] / "manifest.json"
    return manifest, _hash(path)


def _context_source(build: Path):
    manifest = validate_context_build(build)
    return manifest, _hash(build / "manifest.json")


def _base_frames(handle):
    return {name: pd.read_parquet(handle.dataset_path(name)) for name in ("fixtures", "squads", "lineups")}


def _context_frames(build):
    return {name: pd.read_parquet(build / f"canonical/{name}.parquet") for name in (
        "fixtures", "competition_memberships", "fixture_schedule_snapshots", "team_standing_snapshots")}


def _records(frame):
    return tuple(frame.astype(object).where(pd.notna(frame), None).to_dict("records"))


def _mode(values):
    counts = Counter(values)
    return sorted(counts, key=lambda value: (-counts[value], value))[0] if counts else None


def _target_universe(base, context):
    metadata = context["fixtures"].set_index("fixture_id").to_dict("index")
    rows = []
    for fixture in base["fixtures"].sort_values(["kickoff_utc", "fixture_id"]).itertuples(index=False):
        fixture_id = str(fixture.fixture_id)
        if fixture_id not in metadata:
            continue
        cutoff = _utc(fixture.kickoff_utc)
        for team_id in (str(fixture.home_team_id), str(fixture.away_team_id)):
            members = base["squads"][(base["squads"].team_id.astype(str) == team_id)
                & (base["squads"].valid_from.map(_utc) < cutoff)
                & (base["squads"].valid_to.isna() | (base["squads"].valid_to.map(lambda x: _utc(x) if pd.notna(x) else cutoff) >= cutoff))]
            for player_id in sorted(members.player_id.astype(str).unique()):
                rows.append((fixture, metadata[fixture_id], team_id, player_id, cutoff))
    return rows


def _is_member(squads, team_id, player_id, at):
    rows = squads[(squads.team_id.astype(str) == team_id) & (squads.player_id.astype(str) == player_id)]
    return any(_utc(row.valid_from) < at and (pd.isna(row.valid_to) or _utc(row.valid_to) >= at) for row in rows.itertuples(index=False))


def compute_features_v2(base_handle: RuntimeBuildHandle, context_build: Path):
    """Return the four normalized v2 output frames and their source binding."""
    base_manifest, base_hash = _base_source(base_handle)
    context_manifest, context_hash = _context_source(context_build)
    base, context = _base_frames(base_handle), _context_frames(context_build)
    _validate_shared_fixtures(base["fixtures"], context["fixtures"])
    fixture_times = dict(zip(base["fixtures"].fixture_id.astype(str), base["fixtures"].kickoff_utc.map(_utc)))
    fixture_meta = base["fixtures"].set_index(base["fixtures"].fixture_id.astype(str)).to_dict("index")
    lineups = base["lineups"].copy()
    common_source = {
        "canonical_build_id": base_manifest["build_id"], "canonical_manifest_hash": base_hash,
        "context_build_id": context_manifest["build_id"], "context_manifest_hash": context_hash,
        "feature_engine_version": ENGINE_VERSION, "feature_registry_version": FEATURE_REGISTRY_VERSION,
        "cutoff_policy_version": CUTOFF_POLICY_VERSION, "assumption_status": "mock_validated",
    }
    player_rows, summary_rows, distribution_rows, team_rows = [], [], [], []
    team_seen = set()
    schedule_rows = _records(context["fixture_schedule_snapshots"])
    standing_rows = _records(context["team_standing_snapshots"])
    memberships = _records(context["competition_memberships"])
    context_fixture = context["fixtures"].set_index("fixture_id").to_dict("index")
    for fixture, target_meta, team_id, player_id, cutoff in _target_universe(base, context):
        target_id = str(fixture.fixture_id); cutoff_text = _z(cutoff)
        selected_schedule = select_schedule(schedule_rows, cutoff_text)
        schedule_by_id = {str(row["fixture_id"]): row for row in selected_schedule}
        eligible = []
        for candidate_id, meta in fixture_meta.items():
            candidate_id = str(candidate_id)
            known = schedule_by_id.get(candidate_id)
            if not known or known["competition_tier"] != "league" or known["status"] != "completed":
                continue
            kickoff = _utc(known["scheduled_kickoff_utc"])
            if kickoff >= cutoff or str(meta["season_id"]) != str(fixture.season_id) or str(meta["competition_id"]) != str(fixture.competition_id):
                continue
            if team_id not in (str(meta["home_team_id"]), str(meta["away_team_id"])) or not _is_member(base["squads"], team_id, player_id, kickoff):
                continue
            eligible.append((kickoff, candidate_id))
        slots = sorted(eligible)[-6:]
        history = []
        for kickoff, candidate_id in slots:
            matches = lineups[(lineups.fixture_id.astype(str) == candidate_id) & (lineups.team_id.astype(str) == team_id) & (lineups.player_id.astype(str) == player_id)]
            row = matches.iloc[0] if len(matches) else None
            history.append((kickoff, candidate_id, row))
        weights = list(range(7 - len(history), 7)); denominator = float(sum(weights))
        starts = [item for item in history if item[2] is not None and bool(item[2].started)]
        appearances = [item for item in history if item[2] is not None]
        cameos = [item for item in history if item[2] is not None and not bool(item[2].started) and float(item[2].minutes) > 0]
        numerator = float(sum(weight for weight, item in zip(weights, history) if item[2] is not None and bool(item[2].started)))
        player_rows.append({"fixture_id": target_id, "team_id": team_id, "player_id": player_id, "cutoff_utc": cutoff_text,
            "window_start_utc": _z(history[0][0]) if history else None, "eligible_team_fixtures_last_6": len(history),
            "weighted_start_share_last_6": numerator / denominator if denominator else None,
            "weighted_start_numerator_last_6": numerator, "weighted_start_denominator_last_6": denominator,
            "starts_last_6": len(starts), "appearances_last_6": len(appearances), "cameo_appearances_last_6": len(cameos),
            "mean_minutes_when_started_last_6": float(sum(float(x[2].minutes) for x in starts) / len(starts)) if starts else None,
            "mean_minutes_when_cameo_last_6": float(sum(float(x[2].minutes) for x in cameos) / len(cameos)) if cameos else None,
            "recency_weight_version": RECENCY_WEIGHT_VERSION if history else None, **common_source})

        league_fixture_ids = {candidate_id for _, candidate_id in eligible}
        all_prior = sorted((fixture_times.get(str(row.fixture_id)), str(row.fixture_id), row) for row in lineups.itertuples(index=False)
            if str(row.team_id) == team_id and str(row.player_id) == player_id and str(row.fixture_id) in league_fixture_ids and bool(row.started))[-10:]
        segments = {"last_10": all_prior, "last_3": all_prior[-3:], "prior_7": all_prior[:-3]}
        comparable = bool(segments["last_3"] and segments["prior_7"])
        for segment in ("last_10", "last_3", "prior_7"):
            values = segments[segment]; mapped = []
            for _, _, row in values:
                mapping = ROLE_MAP.get(str(row.detailed_position).casefold()) if pd.notna(row.detailed_position) else None
                if mapping: mapped.append(mapping)
            summary_rows.append({"fixture_id": target_id, "team_id": team_id, "player_id": player_id, "window_segment": segment,
                "cutoff_utc": cutoff_text, "eligible_starts": len(values), "mapped_starts": len(mapped), "unmapped_starts": len(values)-len(mapped),
                "modal_role": _mode([value[0] for value in mapped]), "role_change_comparable": comparable,
                "role_mapping_version": ROLE_MAPPING_VERSION, "role_basis": "observed", **common_source})
            counts = Counter(mapped)
            for (role, flank, depth), count in sorted(counts.items()):
                distribution_rows.append({"fixture_id": target_id, "team_id": team_id, "player_id": player_id, "window_segment": segment,
                    "role": role, "flank": flank, "formation_depth": depth, "cutoff_utc": cutoff_text,
                    "role_count": count, "role_share": count / len(values), "role_mapping_version": ROLE_MAPPING_VERSION,
                    "role_basis": "observed", **common_source})

        team_key = (target_id, team_id)
        if team_key in team_seen: continue
        team_seen.add(team_key)
        trailing, leading, previous_candidates, next_candidates = [], [], [], []
        for candidate_id, known in schedule_by_id.items():
            meta = context_fixture.get(candidate_id)
            if not meta or team_id not in (str(meta["home_team_id"]), str(meta["away_team_id"])): continue
            kickoff = _utc(known["scheduled_kickoff_utc"]); weight = COMPETITION_WEIGHTS.get(known["competition_tier"])
            if weight is None: continue
            item = (kickoff, weight, candidate_id, known)
            if known["status"] == "completed" and kickoff < cutoff:
                if cutoff - kickoff <= pd.Timedelta(days=365): previous_candidates.append(item)
                if cutoff - pd.Timedelta(days=21) <= kickoff: trailing.append(item)
            if known["status"] == "scheduled" and cutoff < kickoff and candidate_id != target_id:
                if kickoff - cutoff <= pd.Timedelta(days=365): next_candidates.append(item)
                if kickoff <= cutoff + pd.Timedelta(days=21): leading.append(item)
        ordering = lambda item: (item[0], item[1], item[2])
        trailing.sort(key=ordering); leading.sort(key=ordering)
        previous_candidates.sort(key=ordering); next_candidates.sort(key=ordering)
        standings = select_standings(standing_rows, memberships, str(fixture.competition_id), str(fixture.season_id), cutoff_text)
        standing = next((row for row in standings if str(row["team_id"]) == team_id), None)
        target_schedule = schedule_by_id.get(target_id)
        team_rows.append({"fixture_id": target_id, "team_id": team_id, "cutoff_utc": cutoff_text,
            "weighted_trailing_congestion_21d": float(sum(x[1] for x in trailing)),
            "weighted_leading_congestion_21d": float(sum(x[1] for x in leading)),
            "trailing_fixtures_considered": len(trailing), "leading_fixtures_considered": len(leading),
            "previous_rest_days": (cutoff - previous_candidates[-1][0]).total_seconds()/86400 if previous_candidates else None,
            "next_rest_days": (next_candidates[0][0] - cutoff).total_seconds()/86400 if next_candidates else None,
            "target_competition_tier": target_schedule["competition_tier"] if target_schedule else None,
            "target_competition_stage": target_meta["competition_stage"],
            "league_position_band": standing["league_position_band"] if standing else "unknown",
            "schedule_context_as_of_utc": max((x[3]["observed_at_utc"] for x in leading), default=None),
            "standing_context_as_of_utc": standing["as_of_utc"] if standing else None,
            "competition_weight_version": COMPETITION_WEIGHT_VERSION, **common_source})
    frames = {
        "player_fixture_module_inputs": pd.DataFrame(player_rows),
        "player_role_window_summary": pd.DataFrame(summary_rows),
        "player_role_distribution": pd.DataFrame(distribution_rows),
        "team_fixture_context_v2": pd.DataFrame(team_rows),
    }
    sort_keys = {
        "player_fixture_module_inputs": ["fixture_id", "team_id", "player_id"],
        "player_role_window_summary": ["fixture_id", "team_id", "player_id", "window_segment"],
        "player_role_distribution": ["fixture_id", "team_id", "player_id", "window_segment", "role", "flank", "formation_depth"],
        "team_fixture_context_v2": ["fixture_id", "team_id"],
    }
    for name, value in frames.items():
        frames[name] = value.sort_values(sort_keys[name], kind="mergesort").reset_index(drop=True) if len(value) else value
    return frames, common_source
