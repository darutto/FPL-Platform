"""FI-9 criterion (f): run M1, M2 and M3 on the live-trial store and check them against what happened.

Every check compares a module output with an independent fact:

* **M2** against the position the player actually played in the target fixture
  (the provider's detailed position) and against the side of the grid cell he
  occupied, with a "same as the last start" baseline beside it.
* **M1** as a hold-out: history up to the gameweek before the target, the
  start probability of every squad member against who actually started, with
  Brier scores, calibration bands and the large misses, against two baselines.
* **M3** against the calendar: congestion, weights and rest days recomputed from
  the raw capture, never from the pipeline.

Nothing here is a product feature and nothing leaves the machine. The numeric
report (`aggregate`) carries counts and rates only; the people behind them go in
a separate local detail file (`detail`).

Availability (M1) is a closed explicit input. A hold-out cannot know who was
injured at the time, so the headline uses ``AVAILABLE`` for everyone (form only);
the players the capture later shows as absent are reported as the known source of
the large misses, not removed from the score.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from football_data_contract.enums import AvailabilityState

from football_intelligence.features.engine_v2 import ROLE_MAP_V3
from football_intelligence.grid import grid_side
from football_intelligence.modules.expected_minutes import (
    AvailabilityInput, ExpectedMinutesInput, evaluate_expected_minutes,
)
from football_intelligence.modules.fixture_context import FixtureContextInput, evaluate_fixture_context
from football_intelligence.modules.contracts import ModuleStatus
from football_intelligence.modules.tactical_role import (
    RoleDistributionRow, RoleWindowSummary, TacticalRoleInput, evaluate_tactical_role,
)
from football_data_contract.enums import SignalBasis

NOMINAL = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
BAND_EDGES = (0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0000001)
LARGE_MISS_HIGH = 0.8      # predicted at least this likely to start and did not
LARGE_MISS_LOW = 0.1       # predicted at most this likely to start and did
GRID_RIGHT_AT_HOME = 1     # col 1 is the home team's right; away is mirrored (CONTRACT.md "Lineup grid semantics")


# ------------------------------------------------------------------ frames

@dataclass(frozen=True)
class Frames:
    manifest: dict
    summary: pd.DataFrame
    distribution: pd.DataFrame
    player: pd.DataFrame
    team: pd.DataFrame
    summary_index: dict
    distribution_index: dict
    player_index: dict
    team_index: dict


def _group(frame: pd.DataFrame, keys: Sequence[str]) -> dict:
    out: dict = defaultdict(list)
    for row in frame.itertuples(index=False):
        out[tuple(str(getattr(row, k)) for k in keys)].append(row)
    return out


def load_frames(feature_build: Path) -> Frames:
    import json
    manifest = json.loads((Path(feature_build) / "manifest.json").read_text(encoding="utf-8"))
    read = lambda name: pd.read_parquet(Path(feature_build) / manifest["output_files"][name])
    summary, distribution = read("player_role_window_summary"), read("player_role_distribution")
    player, team = read("player_fixture_module_inputs"), read("team_fixture_context_v2")
    key3, key2 = ("fixture_id", "team_id", "player_id"), ("fixture_id", "team_id")
    return Frames(manifest, summary, distribution, player, team, _group(summary, key3), _group(distribution, key3),
                  {k: v[0] for k, v in _group(player, key3).items()}, {k: v[0] for k, v in _group(team, key2).items()})


def _none(value):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA else value


# ------------------------------------------------------------------ inputs from validated frames
# The module loaders (`load_*_input`) revalidate the whole build for every call; for thousands of
# targets the build is validated once (build_features_v2 does it) and the rows are lifted here.

def role_input(frames: Frames, fixture_id: str, team_id: str, player_id: str, nominal: str | None,
               calculated_at: str) -> TacticalRoleInput:
    key = (fixture_id, team_id, player_id)
    rows = frames.summary_index.get(key)
    manifest = frames.manifest
    if not rows:
        return TacticalRoleInput(fixture_id, team_id, player_id, calculated_at, None, None, None, nominal)
    summaries = tuple(RoleWindowSummary(
        window_segment=str(r.window_segment), eligible_starts=int(r.eligible_starts), mapped_starts=int(r.mapped_starts),
        unmapped_starts=int(r.unmapped_starts), modal_role=_none(r.modal_role),
        role_change_comparable=bool(r.role_change_comparable), role_mapping_version=str(r.role_mapping_version),
        role_basis=SignalBasis(str(r.role_basis))) for r in rows)
    distribution = tuple(RoleDistributionRow(
        window_segment=str(r.window_segment), role=str(r.role), flank=str(r.flank), formation_depth=str(r.formation_depth),
        role_count=int(r.role_count), role_share=float(r.role_share), role_mapping_version=str(r.role_mapping_version),
        role_basis=SignalBasis(str(r.role_basis))) for r in frames.distribution_index.get(key, ()))
    return TacticalRoleInput(fixture_id, team_id, player_id, calculated_at, manifest["feature_registry_version"],
                             manifest["feature_build_id"], manifest["built_at"], nominal,
                             summaries=summaries, distribution=distribution)


def minutes_input(frames: Frames, fixture_id: str, team_id: str, player_id: str, calculated_at: str,
                  availability: AvailabilityInput) -> ExpectedMinutesInput | None:
    p = frames.player_index.get((fixture_id, team_id, player_id))
    if p is None:
        return None
    t = frames.team_index.get((fixture_id, team_id))
    return ExpectedMinutesInput(
        fixture_id, team_id, player_id, calculated_at, str(p.feature_registry_version), str(p.feature_build_id),
        weighted_start_share_last_6=_none(p.weighted_start_share_last_6),
        weighted_start_denominator_last_6=float(p.weighted_start_denominator_last_6),
        eligible_team_fixtures_last_6=int(p.eligible_team_fixtures_last_6),
        cameo_appearances_last_6=int(p.cameo_appearances_last_6),
        mean_minutes_when_started_last_6=_none(p.mean_minutes_when_started_last_6),
        mean_minutes_when_cameo_last_6=_none(p.mean_minutes_when_cameo_last_6),
        weighted_trailing_congestion_21d=None if t is None else _none(t.weighted_trailing_congestion_21d),
        weighted_leading_congestion_21d=None if t is None else _none(t.weighted_leading_congestion_21d),
        availability=availability)


def context_input(frames: Frames, fixture_id: str, team_id: str, calculated_at: str) -> FixtureContextInput:
    t = frames.team_index.get((fixture_id, team_id))
    if t is None:
        return FixtureContextInput(fixture_id, team_id, calculated_at, None, None, None,
                                   missing_reason="fixture_context_row_unavailable")
    return FixtureContextInput(
        fixture_id, team_id, calculated_at, str(t.feature_registry_version), str(t.feature_build_id),
        str(frames.manifest["built_at"]),
        weighted_trailing_congestion_21d=float(t.weighted_trailing_congestion_21d),
        weighted_leading_congestion_21d=float(t.weighted_leading_congestion_21d),
        trailing_fixtures_considered=int(t.trailing_fixtures_considered),
        leading_fixtures_considered=int(t.leading_fixtures_considered),
        previous_rest_days=_none(t.previous_rest_days), next_rest_days=_none(t.next_rest_days),
        target_competition_tier=_none(t.target_competition_tier), target_competition_stage=str(t.target_competition_stage),
        league_position_band=str(t.league_position_band), schedule_context_as_of_utc=_none(t.schedule_context_as_of_utc),
        standing_context_as_of_utc=_none(t.standing_context_as_of_utc),
        competition_weight_version=str(t.competition_weight_version))


# ------------------------------------------------------------------ statistics (pure, tested)

def brier(pairs: Iterable[tuple[float, int]]) -> float | None:
    values = [(p - y) ** 2 for p, y in pairs]
    return sum(values) / len(values) if values else None


def calibration_bands(pairs: Iterable[tuple[float, int]], edges: Sequence[float] = BAND_EDGES) -> list[dict[str, Any]]:
    """Per band: how many, mean predicted, observed rate. Empty bands are kept and say so."""
    rows = []
    items = list(pairs)
    for low, high in zip(edges, edges[1:]):
        inside = [(p, y) for p, y in items if low <= p < high]
        rows.append({"band": f"{low:.1f}-{min(high, 1.0):.1f}", "n": len(inside),
                     "mean_predicted": (sum(p for p, _ in inside) / len(inside)) if inside else None,
                     "observed_rate": (sum(y for _, y in inside) / len(inside)) if inside else None})
    return rows


def agreement(pairs: Iterable[tuple[Any, Any]]) -> dict[str, Any]:
    items = list(pairs)
    hit = sum(1 for a, b in items if a == b)
    return {"n": len(items), "agree": hit, "rate": (hit / len(items)) if items else None}


def flank_of(detailed_position: str | None) -> str | None:
    detailed_position = _none(detailed_position)
    entry = ROLE_MAP_V3.get(str(detailed_position).casefold()) if detailed_position else None
    return entry[1] if entry else None


def role_of(detailed_position: str | None) -> str | None:
    detailed_position = _none(detailed_position)
    entry = ROLE_MAP_V3.get(str(detailed_position).casefold()) if detailed_position else None
    return entry[0] if entry else None


def _flank_text(flank) -> str | None:
    """The module's Flank enum in the store's vocabulary: its `central` is the feature store's `center`."""
    if flank is None:
        return None
    return {"central": "center"}.get(flank.value, flank.value)


def availability(state: AvailabilityState | None = AvailabilityState.AVAILABLE) -> AvailabilityInput:
    return AvailabilityInput(state=state)


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ------------------------------------------------------------------ the store, read back

@dataclass(frozen=True)
class Base:
    fixtures: pd.DataFrame
    lineups: pd.DataFrame
    players: pd.DataFrame
    squads: pd.DataFrame


def load_base(v1_root: Path) -> Base:
    from .live_trial import LiveTrialBuildHandle
    handle = LiveTrialBuildHandle(v1_root)
    read = lambda name: pd.read_parquet(handle.dataset_path(name))
    return Base(read("fixtures"), read("lineups"), read("players"), read("squads"))


def nominal_of(positions_nominal: str | None) -> str | None:
    import json
    try:
        first = (json.loads(positions_nominal or "[]") or [None])[0]
    except ValueError:
        return None
    return {"goalkeeper": "GK", "defender": "DEF", "midfielder": "MID", "forward": "FWD"}.get(first)


def _played(base: Base, fixture_id: str) -> pd.DataFrame:
    return base.lineups[base.lineups.fixture_id == fixture_id]


def _target_fixtures(base: Base, gameweek: int) -> list[Any]:
    done = base.fixtures[(base.fixtures.gameweek == gameweek) & (base.fixtures.status == "completed")]
    return list(done.sort_values(["kickoff_utc", "fixture_id"]).itertuples(index=False))


# ------------------------------------------------------------------ M2

def last_starts(base: Base) -> dict[str, list[tuple[str, str | None]]]:
    """Per player, (kickoff, detailed position) of every start in the store, oldest first."""
    kickoff = dict(zip(base.fixtures.fixture_id, base.fixtures.kickoff_utc))
    out: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for r in base.lineups[base.lineups.started].itertuples(index=False):
        out[r.player_id].append((kickoff[r.fixture_id], _none(r.detailed_position)))
    for rows in out.values():
        rows.sort(key=lambda item: item[0])
    return out


def last_start_position(starts: Mapping[str, Sequence[tuple[str, str | None]]], player_id: str, before_kickoff: str) -> str | None:
    """The detailed position of the player's most recent start strictly before ``before_kickoff`` (None without one)."""
    earlier = [position for kickoff, position in starts.get(player_id, ()) if kickoff < before_kickoff]
    return earlier[-1] if earlier else None


def baseline_comparison(starters: Sequence[Mapping[str, Any]], mapped: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """M2 against "the same position as his last start", over every starter the baseline answers for and over
    the like-for-like subset the module also answered, with who is right where they differ."""
    with_baseline = [d for d in starters if d["baseline_role"] is not None and d["actual_role"] is not None]
    wide_baseline = [d for d in with_baseline if d["baseline_flank"] in ("left", "right") or d["actual_flank"] in ("left", "right")]
    like_for_like = [d for d in mapped if d["baseline_role"] is not None]
    like_wide = [d for d in like_for_like if d["predicted_flank"] in ("left", "right") or d["actual_flank"] in ("left", "right")
                 or d["baseline_flank"] in ("left", "right")]
    return {
        "answers": len(with_baseline), "of_starters": len(starters),
        "role_agreement_all_it_answers": agreement((d["baseline_role"], d["actual_role"]) for d in with_baseline),
        "flank_agreement_all_it_answers": agreement((d["baseline_flank"], d["actual_flank"]) for d in wide_baseline),
        "like_for_like_subset": {
            "n": len(like_for_like),
            "role_module": agreement((d["predicted_role"], d["actual_role"]) for d in like_for_like),
            "role_baseline": agreement((d["baseline_role"], d["actual_role"]) for d in like_for_like),
            "flank_module": agreement((d["predicted_flank"], d["actual_flank"]) for d in like_wide),
            "flank_baseline": agreement((d["baseline_flank"], d["actual_flank"]) for d in like_wide),
            "module_right_baseline_wrong": sum(1 for d in like_for_like if d["predicted_role"] == d["actual_role"] != d["baseline_role"]),
            "baseline_right_module_wrong": sum(1 for d in like_for_like if d["baseline_role"] == d["actual_role"] != d["predicted_role"]),
            "both_right": sum(1 for d in like_for_like if d["predicted_role"] == d["actual_role"] == d["baseline_role"]),
            "both_wrong": sum(1 for d in like_for_like if d["actual_role"] not in (d["predicted_role"], d["baseline_role"])),
        },
        # When does the module differ from "repeat the last start", and who is right then?
        "where_module_and_baseline_differ": {
            "n": sum(1 for d in like_for_like if d["predicted_role"] != d["baseline_role"]),
            "module_right": sum(1 for d in like_for_like if d["predicted_role"] != d["baseline_role"] and d["predicted_role"] == d["actual_role"]),
            "baseline_right": sum(1 for d in like_for_like if d["predicted_role"] != d["baseline_role"] and d["baseline_role"] == d["actual_role"]),
            "neither": sum(1 for d in like_for_like if d["predicted_role"] != d["baseline_role"] and d["actual_role"] not in (d["predicted_role"], d["baseline_role"])),
        },
        # The cases that matter most: the player played a different role than at his last start.
        "role_changes_since_last_start": {
            "n": sum(1 for d in like_for_like if d["actual_role"] != d["baseline_role"]),
            "module_predicted_the_new_role": sum(1 for d in like_for_like if d["actual_role"] != d["baseline_role"] and d["predicted_role"] == d["actual_role"]),
            "module_detected_a_change_beforehand": sum(1 for d in like_for_like if d["actual_role"] != d["baseline_role"] and d["role_change"]),
        },
    }


def run_m2(frames: Frames, base: Base, gameweek: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Predict from history strictly before each fixture of ``gameweek``; compare with what each player did there."""
    calculated_at = frames.manifest["built_at"]
    names = base.players.set_index("player_id")
    detail: list[dict[str, Any]] = []
    starts = last_starts(base)
    for fixture in _target_fixtures(base, gameweek):
        rows = _played(base, fixture.fixture_id)
        widths = rows[rows.started].assign(_row=lambda d: d.grid_slot.map(lambda g: int(g.split(":")[0]) if isinstance(g, str) and ":" in g else -1),
                                           _col=lambda d: d.grid_slot.map(lambda g: int(g.split(":")[1]) if isinstance(g, str) and ":" in g else -1))
        for r in rows.itertuples(index=False):
            player = names.loc[r.player_id]
            nominal = nominal_of(player.positions_nominal)
            result = evaluate_tactical_role(role_input(frames, fixture.fixture_id, r.team_id, r.player_id, nominal, calculated_at))
            actual_role, actual_flank = role_of(r.detailed_position), flank_of(r.detailed_position)
            is_home = r.team_id == fixture.home_team_id
            width = int(widths[(widths.team_id == r.team_id) & (widths._row == (int(r.grid_slot.split(":")[0]) if isinstance(r.grid_slot, str) and ":" in r.grid_slot else -2))]._col.max() or 0) if r.started else 0
            detail.append({
                "fixture_id": fixture.fixture_id, "team_id": r.team_id, "player_id": r.player_id, "name": player.full_name,
                "started": bool(r.started), "status": result.status.value, "nominal": nominal,
                "actual_position": _none(r.detailed_position), "actual_role": actual_role, "actual_flank": actual_flank,
                "grid_slot": _none(r.grid_slot), "grid_side": grid_side(_none(r.grid_slot), width, is_home) if r.started else None,
                "baseline_role": role_of(last_start_position(starts, r.player_id, fixture.kickoff_utc)),
                "baseline_flank": flank_of(last_start_position(starts, r.player_id, fixture.kickoff_utc)),
                "predicted_role": result.primary_role,
                "predicted_flank": _flank_text(result.primary_flank),
                "out_of_position": result.out_of_position_score, "role_change": result.role_change_detected,
                "reason_codes": list(result.reason_codes)})
    starters = [d for d in detail if d["started"]]
    ok = [d for d in starters if d["status"] == ModuleStatus.OK.value]
    mapped = [d for d in ok if d["actual_role"] is not None]
    wide = [d for d in mapped if d["predicted_flank"] in ("left", "right") or d["actual_flank"] in ("left", "right")]
    grid = [d for d in ok if d["grid_side"] is not None and d["predicted_flank"] in ("left", "right")]
    confusion = Counter((d["predicted_role"], d["actual_role"]) for d in mapped if d["predicted_role"] != d["actual_role"])
    baseline = baseline_comparison(starters, mapped)
    aggregate = {
        "gameweek": gameweek, "starters": len(starters), "module_ok": len(ok), "module_missing_context": len(starters) - len(ok),
        "coverage_rate": (len(ok) / len(starters)) if starters else None,
        "role_agreement": agreement((d["predicted_role"], d["actual_role"]) for d in mapped),
        "flank_agreement_where_a_side_is_involved": agreement((d["predicted_flank"], d["actual_flank"]) for d in wide),
        "predicted_flank_vs_grid_edge": agreement((d["predicted_flank"], d["grid_side"]) for d in grid),
        "baseline_same_position_as_last_start": baseline,
        "unmapped_actual_position": len(ok) - len(mapped),
        "most_common_disagreements": [{"predicted": a, "actual": b, "n": n} for (a, b), n in confusion.most_common(8)],
        "out_of_position_flagged": sum(1 for d in ok if d["out_of_position"] is not None and d["out_of_position"] >= 1.0),
        "out_of_position_partial": sum(1 for d in ok if d["out_of_position"] is not None and 0.0 < d["out_of_position"] < 1.0),
        "role_change_detected": sum(1 for d in ok if d["role_change"]),
    }
    return aggregate, detail


# ------------------------------------------------------------------ M1

def run_m1(frames: Frames, base: Base, gameweek: int, *, absent: set[str] = frozenset()) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    calculated_at = frames.manifest["built_at"]
    names = base.players.set_index("player_id")
    detail: list[dict[str, Any]] = []
    for fixture in _target_fixtures(base, gameweek):
        played = {r.player_id: r for r in _played(base, fixture.fixture_id).itertuples(index=False)}
        for team_id in (fixture.home_team_id, fixture.away_team_id):
            for (fid, tid, pid), _row in frames.player_index.items():
                if fid != fixture.fixture_id or tid != team_id:
                    continue
                item = minutes_input(frames, fid, tid, pid, calculated_at, availability())
                result = evaluate_expected_minutes(item)
                got = played.get(pid)
                detail.append({
                    "fixture_id": fid, "team_id": tid, "player_id": pid, "name": names.loc[pid].full_name,
                    "status": result.status.value, "start_probability": result.start_probability,
                    "expected_minutes": result.expected_minutes, "share": item.weighted_start_share_last_6,
                    "history": item.eligible_team_fixtures_last_6,
                    "started": int(bool(got is not None and got.started)),
                    "minutes": int(got.minutes) if got is not None else 0, "later_absent": pid in absent})
    scored = [d for d in detail if d["status"] == ModuleStatus.OK.value and d["start_probability"] is not None]
    pairs = [(d["start_probability"], d["started"]) for d in scored]
    rate = (sum(y for _, y in pairs) / len(pairs)) if pairs else None
    share_pairs = [(d["share"], d["started"]) for d in scored if d["share"] is not None]
    played_rows = [d for d in scored if d["minutes"] > 0 and d["expected_minutes"] is not None]
    high_miss = [d for d in scored if d["start_probability"] >= LARGE_MISS_HIGH and not d["started"]]
    low_hit = [d for d in scored if d["start_probability"] <= LARGE_MISS_LOW and d["started"]]
    aggregate = {
        "gameweek": gameweek, "squad_members_evaluated": len(detail), "module_ok": len(scored),
        "module_missing_context": len(detail) - len(scored), "actual_start_rate": rate,
        "mean_predicted_start_probability": (sum(p for p, _ in pairs) / len(pairs)) if pairs else None,
        "brier_module": brier(pairs),
        "brier_constant_base_rate": brier((rate, y) for _, y in pairs) if rate is not None else None,
        "brier_raw_weighted_share": brier(share_pairs), "share_pairs": len(share_pairs),
        "calibration_bands": calibration_bands(pairs),
        "large_misses": {"predicted_start_not_started": len(high_miss),
                         "of_which_later_absent_per_fpl_status": sum(1 for d in high_miss if d["later_absent"]),
                         "predicted_not_start_but_started": len(low_hit)},
        "expected_minutes_mae_for_players_who_played": (sum(abs(d["expected_minutes"] - d["minutes"]) for d in played_rows) / len(played_rows)) if played_rows else None,
        "players_who_played_evaluated": len(played_rows),
    }
    return aggregate, detail


# ------------------------------------------------------------------ M3

def _calendar(capture: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """Every fixture of every club, from the raw capture (no pipeline in the path)."""
    from .live_trial import COMPETITIONS, _location, _utc, fixture_status
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for fixture in capture["team_fixtures"]:
        row = {"league_id": int(fixture["league_id"]), "kickoff": _utc(fixture["starting_at"]), "status": fixture_status(fixture),
               "weight": {"league": 1.0, "domestic_cup": 1.0, "continental": 1.25}[COMPETITIONS[int(fixture["league_id"])]["context_tier"]],
               "continental": COMPETITIONS[int(fixture["league_id"])]["context_tier"] == "continental", "id": int(fixture["id"])}
        for where in ("home", "away"):
            out[int(_location(fixture, where)["id"])].append(row)
    return out


def expected_context(calendar: Sequence[Mapping[str, Any]], kickoff: str, target_id: int, known_after_hours: float) -> dict[str, Any]:
    """Trailing/leading weights and rest days for one team at one cutoff, straight from its calendar."""
    from .live_trial import _plus_hours
    cut = iso(kickoff)
    trailing = leading = 0.0
    n_trailing = n_leading = 0
    prev = nxt = None
    for f in calendar:
        k = iso(f["kickoff"])
        completed_known = f["status"] == "completed" and iso(_plus_hours(f["kickoff"], known_after_hours)) < cut
        if completed_known and k < cut:
            if (cut - k).total_seconds() <= 21 * 86400:
                trailing += f["weight"]; n_trailing += 1
            if (cut - k).days <= 365:
                prev = max(prev, k) if prev else k
        if f["status"] != "completed" or k > cut:
            if k > cut and f["id"] != target_id and f["status"] in ("scheduled", "completed", "live"):
                if (k - cut).total_seconds() <= 21 * 86400:
                    leading += f["weight"]; n_leading += 1
                if (k - cut).days <= 365:
                    nxt = min(nxt, k) if nxt else k
    return {"trailing": trailing, "leading": leading, "n_trailing": n_trailing, "n_leading": n_leading,
            "previous_rest_days": ((cut - prev).total_seconds() / 86400) if prev else None,
            "next_rest_days": ((nxt - cut).total_seconds() / 86400) if nxt else None}


def run_m3(frames: Frames, base: Base, capture: Mapping[str, Any], index: Mapping[int, str], *,
           known_after_hours: float, until_gameweek: int | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Every league fixture whose kickoff is before the build: M3 output against the calendar recomputed from the capture."""
    calendar = _calendar(capture)
    club_of = {canonical: sm for sm, canonical in index.items()}
    calculated_at = frames.manifest["built_at"]
    detail: list[dict[str, Any]] = []
    fixtures = base.fixtures if until_gameweek is None else base.fixtures[base.fixtures.gameweek <= until_gameweek]
    for fixture in fixtures.sort_values(["kickoff_utc", "fixture_id"]).itertuples(index=False):
        for team_id in (fixture.home_team_id, fixture.away_team_id):
            sm_club = club_of[team_id]
            result = evaluate_fixture_context(context_input(frames, fixture.fixture_id, team_id, calculated_at))
            target = next((f for f in calendar[sm_club] if f["league_id"] == 8 and f["kickoff"] == fixture.kickoff_utc), None)
            expected = expected_context(calendar[sm_club], fixture.kickoff_utc, target["id"] if target else -1, known_after_hours)
            european = any(f["continental"] and abs((iso(f["kickoff"]) - iso(fixture.kickoff_utc)).total_seconds()) <= 21 * 86400 and f["kickoff"] != fixture.kickoff_utc
                           for f in calendar[sm_club])
            row = frames.team_index.get((fixture.fixture_id, team_id))
            detail.append({
                "fixture_id": fixture.fixture_id, "team_id": team_id, "gameweek": int(fixture.gameweek) if pd.notna(fixture.gameweek) else None,
                "status": result.status.value, "reason_codes": list(result.reason_codes), "european_within_21d": european,
                "congestion_index": result.congestion_index, "priority": None if result.fixture_priority is None else result.fixture_priority.value,
                "feature_trailing": None if row is None else float(row.weighted_trailing_congestion_21d),
                "feature_leading": None if row is None else float(row.weighted_leading_congestion_21d),
                "feature_previous_rest": None if row is None else _none(row.previous_rest_days),
                "feature_next_rest": None if row is None else _none(row.next_rest_days),
                "expected": expected})
    have = [d for d in detail if d["feature_trailing"] is not None]
    close = lambda a, b: (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-6)
    ok = [d for d in detail if d["status"] == ModuleStatus.OK.value]
    eu = [d["congestion_index"] for d in ok if d["european_within_21d"]]
    non = [d["congestion_index"] for d in ok if not d["european_within_21d"]]
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None
    aggregate = {
        "team_fixtures": len(detail), "feature_rows": len(have), "module_ok": len(ok),
        "module_missing_context": Counter(r for d in detail if d["status"] != ModuleStatus.OK.value for r in d["reason_codes"]),
        "trailing_matches_calendar": agreement((round(d["feature_trailing"], 6), round(d["expected"]["trailing"], 6)) for d in have),
        "leading_matches_calendar": agreement((round(d["feature_leading"], 6), round(d["expected"]["leading"], 6)) for d in have),
        "previous_rest_matches_calendar": {"n": len(have), "agree": sum(1 for d in have if close(d["feature_previous_rest"], d["expected"]["previous_rest_days"]))},
        "next_rest_matches_calendar": {"n": len(have), "agree": sum(1 for d in have if close(d["feature_next_rest"], d["expected"]["next_rest_days"]))},
        "congestion_index_mean_with_european_fixture_within_21d": mean(eu), "n_with_european": len(eu),
        "congestion_index_mean_without": mean(non), "n_without_european": len(non),
    }
    aggregate["module_missing_context"] = dict(aggregate["module_missing_context"])
    return aggregate, detail


# ------------------------------------------------------------------ Leo-validated sides, manual-review sample, the whole run

#: What Leo confirmed against a Sofascore line-up for Arsenal-Leeds (2026-10-10): the side of six Arsenal starters.
#: M2 speaks of roles and flanks, so the central ones are (role, centre) and the wide ones carry a side.
LEO_VALIDATED = {
    "konsa": ("center_back", "center"), "gabriel": ("center_back", "center"),
    "rice": ("central_midfield", "center"), "lewis-skelly": ("central_midfield", "center"),
    "saka": ("winger", "right"), "madueke": ("winger", "left"),
}


def check_leo_validated(m2_detail: Sequence[Mapping[str, Any]], fixture_players: Mapping[str, str]) -> dict[str, Any]:
    """Compare M2 (history only) and the position actually played with the six sides Leo confirmed.

    ``fixture_players`` maps a lower-cased surname to the player_id in the Arsenal-Leeds fixture rows.
    """
    by_player = {d["player_id"]: d for d in m2_detail}
    rows = []
    for surname, (role, flank) in LEO_VALIDATED.items():
        player_id = fixture_players.get(surname)
        d = by_player.get(player_id) if player_id else None
        rows.append({"player": surname, "expected": (role, flank),
                     "actual": None if d is None else (d["actual_role"], d["actual_flank"]),
                     "predicted": None if d is None else (d["predicted_role"], d["predicted_flank"]),
                     "module_status": None if d is None else d["status"]})
    found = [r for r in rows if r["actual"] is not None]
    return {"n_expected": len(rows), "n_found": len(found),
            "actual_matches_leo": sum(1 for r in found if r["actual"] == r["expected"]),
            "predicted_matches_leo": sum(1 for r in found if r["predicted"] == r["expected"]),
            "module_ok": sum(1 for r in found if r["module_status"] == "ok"), "rows": rows}


def review_sample(m1_detail: Sequence[Mapping[str, Any]], m2_detail: Sequence[Mapping[str, Any]], *,
                  european_teams: set[str], newcomers: set[str], leo_players: set[str], per_category: int = 5) -> list[dict[str, Any]]:
    """At least 20 players across the cases the review asked for. Deterministic: sorted, then the first few per category."""
    m2 = {(d["fixture_id"], d["player_id"]): d for d in m2_detail}
    rows = []
    for d in m1_detail:
        if d["status"] != ModuleStatus.OK.value:
            continue
        other = m2.get((d["fixture_id"], d["player_id"]), {})
        rows.append({**d, "m2_status": other.get("status"), "predicted_role": other.get("predicted_role"),
                     "predicted_flank": other.get("predicted_flank"), "actual_position": other.get("actual_position"),
                     "out_of_position": other.get("out_of_position"), "nominal": other.get("nominal")})
    rows.sort(key=lambda r: (r["fixture_id"], r["player_id"]))
    pick = lambda predicate: [r for r in rows if predicate(r)][:per_category]
    groups = {
        "fixed_starter": pick(lambda r: r["start_probability"] >= 0.8 and r["started"] == 1 and r["team_id"] not in european_teams),
        "rotation_european_club": pick(lambda r: r["team_id"] in european_teams and 0.2 <= r["start_probability"] <= 0.8),
        "out_of_position": pick(lambda r: (r["out_of_position"] or 0) > 0.0),
        "newcomer": pick(lambda r: r["player_id"] in newcomers),
        "leo_team": pick(lambda r: r["player_id"] in leo_players),
        "large_miss": pick(lambda r: (r["start_probability"] >= LARGE_MISS_HIGH and not r["started"])
                           or (r["start_probability"] <= LARGE_MISS_LOW and r["started"])),
    }
    seen, sample = set(), []
    for category, members in groups.items():
        for r in members:
            if (r["fixture_id"], r["player_id"]) in seen:
                continue
            seen.add((r["fixture_id"], r["player_id"]))
            sample.append({"category": category, **r})
    return sample


def run_all(store_root: Path, features_build: Path, capture: Mapping[str, Any], *, holdout_gameweek: int = 6,
            m3_until_gameweek: int | None = None, leo_players: set[str] = frozenset()) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the three checks. Returns (aggregate, detail); only the first is ever versioned."""
    from football_data_contract import canonical_player_id
    from .live_trial import RESULT_KNOWN_AFTER_HOURS, build_team_registry

    frames = load_frames(features_build)
    base = load_base(Path(store_root) / "v1" / "premier-league")
    _, index = build_team_registry(capture)
    absent = {canonical_player_id(f"{e['first_name']} {e['second_name']}".strip(), (e.get("birth_date") or "")[:10] or None)
              for e in capture["fpl"]["elements"] if e.get("status") in ("i", "s", "u")}
    m2_aggregate, m2_detail = run_m2(frames, base, holdout_gameweek)
    m1_aggregate, m1_detail = run_m1(frames, base, holdout_gameweek, absent=absent)
    m3_aggregate, m3_detail = run_m3(frames, base, capture, index, known_after_hours=RESULT_KNOWN_AFTER_HOURS,
                                     until_gameweek=m3_until_gameweek)
    names = base.players.set_index("player_id").full_name
    arsenal = next((c for c in capture["teams"] if c["name"] == "Arsenal"), None)
    arsenal_id = index[int(arsenal["id"])] if arsenal else None
    arsenal_rows = [d for d in m2_detail if d["team_id"] == arsenal_id]
    surnames = {}
    for d in arsenal_rows:
        low = d["name"].casefold()
        for surname in LEO_VALIDATED:
            if surname.replace("-", " ") in low.replace("-", " "):
                surnames[surname] = d["player_id"]
    leo = check_leo_validated([d for d in arsenal_rows if d["fixture_id"] == _arsenal_leeds(base, arsenal_id)], surnames)
    european = {d["team_id"] for d in m3_detail if d["european_within_21d"]}
    newcomers = _newcomers(base, holdout_gameweek)
    sample = review_sample(m1_detail, m2_detail, european_teams=european, newcomers=newcomers, leo_players=set(leo_players))
    aggregate = {"store": {"assumption_status": frames.manifest["assumption_status"], "feature_build": frames.manifest["feature_build_id"]},
                 "m1": m1_aggregate, "m2": m2_aggregate, "m3": m3_aggregate, "leo_validated_arsenal": {
                     k: v for k, v in leo.items() if k != "rows"},
                 "manual_review_sample": dict(Counter(r["category"] for r in sample)) | {"total": len(sample)}}
    detail = {"m1": m1_detail, "m2": m2_detail, "m3": m3_detail, "leo_validated_rows": leo["rows"],
              "manual_review": sample, "names": {pid: names.get(pid) for pid in {d["player_id"] for d in m2_detail}}}
    return aggregate, detail


def _arsenal_leeds(base: Base, arsenal_id: str | None) -> str | None:
    rows = base.fixtures[(base.fixtures.gameweek == 6) & ((base.fixtures.home_team_id == arsenal_id) | (base.fixtures.away_team_id == arsenal_id))]
    return None if rows.empty else rows.iloc[0].fixture_id


def _newcomers(base: Base, gameweek: int) -> set[str]:
    """Squad members who joined after the season began (the squad row starts after the first kickoff)."""
    first = base.fixtures.kickoff_utc.min()
    return set(base.squads[base.squads.valid_from > first[:10]].player_id)


# ------------------------------------------------------------------ Leo's table and the command line

def fetch_leo_picks(entry_id: int, gameweek: int) -> list[int]:
    """FPL element ids of an entry's picks for one gameweek (public, read-only)."""
    import sys
    root = Path(__file__).resolve().parents[3] / "fpl-api-client"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from fpl_api_client.fpl_client import ENTRY_PICKS_URL, fetch_json  # noqa: PLC0415
    return [int(p["element"]) for p in fetch_json(ENTRY_PICKS_URL.format(team_id=entry_id, gameweek=gameweek))["picks"]]


def leo_player_ids(capture: Mapping[str, Any], element_ids: Iterable[int]) -> set[str]:
    from football_data_contract import canonical_player_id
    wanted = set(element_ids)
    return {canonical_player_id(f"{e['first_name']} {e['second_name']}".strip(), (e.get("birth_date") or "")[:10] or None)
            for e in capture["fpl"]["elements"] if int(e["id"]) in wanted}


def render_review_table(sample: Sequence[Mapping[str, Any]], clubs: Mapping[str, str], limit: int = 10) -> str:
    """A short table for a human: one line per player, the evidence next to what happened. Names appear here only."""
    order = ["fixed_starter", "rotation_european_club", "out_of_position", "newcomer", "leo_team", "large_miss"]
    chosen, seen, per = [], set(), Counter()
    for category in order * 2:
        for row in sample:
            key = (row["fixture_id"], row["player_id"])
            if row["category"] == category and key not in seen and per[category] < (2 if category != "leo_team" else 3):
                chosen.append(row); seen.add(key); per[category] += 1
                break
        if len(chosen) >= limit:
            break
    lines = ["| player | club | case | before the match: start chance / expected minutes / role | what happened | makes sense? |",
             "|---|---|---|---|---|---|"]
    for r in chosen[:limit]:
        role = f"{r.get('predicted_role') or '—'}" + (f" ({r['predicted_flank']})" if r.get("predicted_flank") in ("left", "right") else "")
        happened = (f"started, {r['minutes']} min" if r["started"] else (f"came on, {r['minutes']} min" if r["minutes"] else "did not play"))
        if r.get("actual_position"):
            happened += f", {r['actual_position']}"
        lines.append(f"| {r['name']} | {clubs.get(r['team_id'], '')} | {r['category'].replace('_', ' ')} | "
                     f"{r['start_probability']:.0%} / {r['expected_minutes']:.0f} min / {role} | {happened} |  |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(prog="live_trial_checks", description="Run M1-M3 on a live-trial store and write local results.")
    parser.add_argument("--root", type=Path, required=True, help="store root built by live_trial")
    parser.add_argument("--features", type=Path, required=True, help="feature build directory (builds-v2/<id>)")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="local output directory (not versioned)")
    parser.add_argument("--holdout-gameweek", type=int, default=6)
    parser.add_argument("--m3-until-gameweek", type=int, default=7, help="M3 is judged on fixtures up to here: later ones see an incomplete calendar")
    parser.add_argument("--leo-entry", type=int, default=None)
    args = parser.parse_args(argv)
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    leo = leo_player_ids(capture, fetch_leo_picks(args.leo_entry, args.holdout_gameweek)) if args.leo_entry else set()
    aggregate, detail = run_all(args.root, args.features, capture, holdout_gameweek=args.holdout_gameweek,
                                 m3_until_gameweek=args.m3_until_gameweek, leo_players=leo)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "aggregate.json").write_text(json.dumps(aggregate, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.out / "detail.json").write_text(json.dumps(detail, default=str), encoding="utf-8")
    from .live_trial import build_team_registry
    _, index = build_team_registry(capture)
    names = {canonical: next((c["name"] for c in capture["teams"] if int(c["id"]) == sm), "") for sm, canonical in index.items()}
    (args.out / "review_for_leo.md").write_text(render_review_table(detail["manual_review"], names), encoding="utf-8")
    print(json.dumps(aggregate["manual_review_sample"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
