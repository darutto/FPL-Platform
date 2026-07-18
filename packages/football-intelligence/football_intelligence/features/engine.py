"""Deterministic, leakage-safe FI-5 feature computation."""
from __future__ import annotations
import hashlib, json
from collections import Counter
import pandas as pd
from football_intelligence.distribution.runtime import RuntimeBuildHandle
from .registry import FEATURE_REGISTRY_VERSION

ENGINE_VERSION = "fi5-engine-v1"; CUTOFF_POLICY_VERSION = "strictly-before-kickoff-v1"
ROLE_MAP = {"goalkeeper": ("goalkeeper", "center", "goalkeeper"), "central midfield": ("central_midfield", "center", "midfield"),
            "left wing": ("winger", "left", "attack"), "right wing": ("winger", "right", "attack"),
            "centre forward": ("forward", "center", "attack"), "central defender": ("center_back", "center", "defense")}


def _manifest_hash(handle):
    manifest = handle.manifest(); path = handle.cache_root / "builds" / manifest["build_id"] / "manifest.json"
    return manifest, hashlib.sha256(path.read_bytes()).hexdigest()


def _read(handle, name): return pd.read_parquet(handle.dataset_path(name))
def _iso(value): return pd.Timestamp(value).tz_convert("UTC") if pd.Timestamp(value).tzinfo else pd.Timestamp(value).tz_localize("UTC")
def _mode(values):
    counts = Counter(str(v) for v in values if pd.notna(v)); return sorted(counts, key=lambda x: (-counts[x], x))[0] if counts else None


def compute_features(handle: RuntimeBuildHandle) -> pd.DataFrame:
    manifest, source_hash = _manifest_hash(handle)
    fixtures = _read(handle, "fixtures").sort_values(["kickoff_utc", "fixture_id"])
    squads, lineups = _read(handle, "squads"), _read(handle, "lineups")
    players, injuries, suspensions = _read(handle, "players"), _read(handle, "injuries"), _read(handle, "suspensions")
    fixture_times = dict(zip(fixtures.fixture_id.astype(str), fixtures.kickoff_utc.map(_iso)))
    nominal = dict(zip(players.player_id.astype(str), players.positions_nominal.astype(str)))
    rows = []
    for fixture in fixtures.itertuples(index=False):
        cutoff = _iso(fixture.kickoff_utc); target_id = str(fixture.fixture_id)
        eligible_fixture_ids = set(fixtures[(fixtures.kickoff_utc.map(_iso) < cutoff) &
            (fixtures.status.astype(str) == "completed") &
            (fixtures.season_id.astype(str) == str(fixture.season_id)) &
            (fixtures.competition_id.astype(str) == str(fixture.competition_id))].fixture_id.astype(str))
        for team_id in (str(fixture.home_team_id), str(fixture.away_team_id)):
            members = squads[(squads.team_id.astype(str) == team_id) & (squads.valid_from.map(_iso) < cutoff) & (squads.valid_to.isna() | (squads.valid_to.map(lambda x: _iso(x) if pd.notna(x) else cutoff) >= cutoff))]
            for player_id in sorted(members.player_id.astype(str).unique()):
                history = lineups[(lineups.player_id.astype(str) == player_id) & lineups.fixture_id.astype(str).isin(eligible_fixture_ids)].copy()
                history["_kickoff"] = history.fixture_id.astype(str).map(fixture_times); history = history.sort_values(["_kickoff", "fixture_id"])
                appearances = history.tail(5); starts = history[history.started].tail(10)
                roles = [ROLE_MAP.get(str(v).casefold(), (None, None, None)) for v in starts.detailed_position]
                primary = _mode([r[0] for r in roles]); flank = _mode([r[1] for r in roles]); depth = _mode([r[2] for r in roles])
                dist_counts = Counter(r[1] for r in roles if r[1]); dist = {k: dist_counts[k] / len(roles) for k in sorted(dist_counts)} if roles else None
                role_stability = (sum(r[0] == primary for r in roles) / len(roles)) if roles else None
                nominal_text = nominal.get(player_id, "").casefold(); oop = None
                if primary: oop = 0.0 if any(x in nominal_text for x in ({"central_midfield": ("midfielder",), "winger": ("midfielder",), "forward": ("forward",), "center_back": ("defender",), "goalkeeper": ("goalkeeper",)}[primary])) else 1.0
                n = len(appearances); start_share = float(appearances.started.mean()) if n else None
                minutes = float(appearances.minutes.mean()) if n else None; cameo = float(((~appearances.started) & (appearances.minutes > 0)).mean()) if n else None
                previous = appearances.iloc[-1]._kickoff if n else None
                rest = (cutoff - previous).total_seconds() / 86400 if previous is not None else None
                team_prior = fixtures[((fixtures.home_team_id.astype(str) == team_id) | (fixtures.away_team_id.astype(str) == team_id)) & (fixtures.status.astype(str) == "completed") & fixtures.fixture_id.astype(str).map(lambda x: fixture_times[x] < cutoff) & fixtures.fixture_id.astype(str).map(lambda x: fixture_times[x] >= cutoff - pd.Timedelta(days=21))]
                active_injury = injuries[(injuries.player_id.astype(str) == player_id) & (injuries.recorded_at_utc.map(_iso) < cutoff) & (injuries.resolved_at_utc.isna() | (injuries.resolved_at_utc.map(lambda x: _iso(x) if pd.notna(x) else cutoff) >= cutoff))]
                active_susp = suspensions[(suspensions.player_id.astype(str) == player_id) & (suspensions.recorded_at_utc.map(_iso) < cutoff) & (suspensions.ends_on.isna() | (suspensions.ends_on.map(lambda x: _iso(x) if pd.notna(x) else cutoff) >= cutoff))]
                availability = 0.0 if len(active_susp) else (0.5 if len(active_injury) else 1.0)
                rows.append({"fixture_id": target_id, "team_id": team_id, "player_id": player_id,
                    "cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"), "window_start_utc": previous.isoformat().replace("+00:00", "Z") if previous is not None else None,
                    "eligible_observations": n, "canonical_build_id": manifest["build_id"], "canonical_manifest_hash": source_hash,
                    "feature_engine_version": ENGINE_VERSION, "feature_registry_version": FEATURE_REGISTRY_VERSION,
                    "primary_role": primary, "role_stability": role_stability, "flank": flank,
                    "flank_distribution": json.dumps(dist, sort_keys=True, separators=(",", ":")) if dist is not None else None,
                    "formation_depth": depth, "out_of_position_score": oop, "start_share_last_5": start_share,
                    "mean_minutes_last_5": minutes, "cameo_share_last_5": cameo,
                    "rotation_tendency": (1.0 - start_share) if start_share is not None else None,
                    "rest_days": rest, "fixture_congestion_index": len(team_prior), "availability_multiplier": availability,
                    "missing_reason": "insufficient_history" if not n else None})
    return pd.DataFrame(rows).sort_values(["fixture_id", "team_id", "player_id"], kind="mergesort").reset_index(drop=True)
