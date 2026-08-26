"""
fpl_historical.rolling_strength
================================
Track D Step 2 — walk-forward, decaying team-strength model.

Computes attack/defence strength per team, per venue, from that team's OWN
real match history up to (but not including) a given gameweek checkpoint —
"what we knew at the time", instead of Step 1's single end-of-season
snapshot applied uniformly across the whole season (see
project_track_d_backtest_findings memory for the concrete miss this fixes:
Liverpool's captured strength_attack_home sat in the bottom third of the
league pool, nowhere near their real GW1 form).

Output fields match exactly what fixture_outlook.py reads from a bootstrap's
teams array (strength_attack_home/away, strength_defence_home/away) — this
is a drop-in input swap, fixture_outlook.py itself is unchanged.

Cold start (promoted teams / early season): rather than a hard switch
between "our own data" and "FPL's captured provisional rating" — which
would corrupt fixture_outlook.py's quintile bucketing, since FPL's raw
~1000-1400 strength scale and a goals-based average (~0-4) can't share one
pool without the smaller-scale values all collapsing into band 1 regardless
of true relative strength — the two signals are blended in RANK space
instead. See _blend_rank_and_rescale() for the exact formula. Not in scope:
cross-season blending (GW1 predictions still rely purely on FPL's captured
value, same as Step 1 — this model's value is for GW2+ once real matches
exist).
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Any

import pandas as pd

from .paths import merged_parquet_dir

#: Decay half-life, in gameweeks. A match this many GWs old carries half the
#: weight of a match played "now" (i.e. the GW immediately before as_of_gw).
DEFAULT_HALF_LIFE_GWS = 5.0

#: Shrinkage prior strength, in "equivalent decayed matches". At this much
#: accumulated decayed weight, a team's blend is roughly 50/50 own-data vs
#: FPL's captured fallback rating.
DEFAULT_PRIOR_WEIGHT = 3.0

#: Minimum number of teams that must have >=1 own match before the own-data
#: rank signal is trusted at all (avoids ranking over a near-empty pool in
#: the first gameweek or two).
_MIN_TEAMS_FOR_OWN_RANK = 5

#: The four fields fixture_outlook.py reads from bootstrap["teams"][*].
STRENGTH_FIELDS: tuple[str, ...] = (
    "strength_attack_home",
    "strength_attack_away",
    "strength_defence_home",
    "strength_defence_away",
)

# Output is rescaled onto roughly this range purely for readability/parity
# with FPL's own numbers — not functionally required. fixture_outlook.py's
# quintile bucketing only cares about relative order within the pool.
_OUTPUT_BASE = 1000.0
_OUTPUT_SPAN = 400.0


def _decay_weight(gw_ago: float, half_life_gws: float) -> float:
    """Exponential decay weight for a match `gw_ago` gameweeks in the past."""
    if gw_ago < 0:
        return 0.0
    return math.pow(0.5, gw_ago / half_life_gws)


def _percentile_rank(values: dict[int, float]) -> dict[int, float]:
    """Rank each team_id's value within `values` onto [0, 1] (0 = lowest)."""
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    if n == 1:
        return {ordered[0][0]: 0.5}
    return {team_id: i / (n - 1) for i, (team_id, _) in enumerate(ordered)}


def _decayed_avg_and_weight(
    observations: list[tuple[int, int]], as_of_gw: int, half_life_gws: float
) -> tuple[float | None, float]:
    """Decayed-weighted average + total weight for a list of (gw, value) pairs."""
    if not observations:
        return None, 0.0
    weighted_sum = 0.0
    weight_total = 0.0
    for gw, value in observations:
        w = _decay_weight(as_of_gw - gw, half_life_gws)
        weighted_sum += w * value
        weight_total += w
    if weight_total == 0.0:
        return None, 0.0
    return weighted_sum / weight_total, weight_total


def compute_rolling_strength(
    season: str,
    as_of_gw: int,
    *,
    half_life_gws: float = DEFAULT_HALF_LIFE_GWS,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    _teams_df: pd.DataFrame | None = None,
    _fixtures_df: pd.DataFrame | None = None,
) -> dict[int, dict[str, float]]:
    """Rolling attack/defence strength per team, as known before `as_of_gw`.

    Returns ``{team_id: {field: value, ...}}`` for each field in
    ``STRENGTH_FIELDS``. Uses ONLY matches with ``event_id < as_of_gw`` — no
    lookahead, so this is a genuine walk-forward computation.

    ``_teams_df`` / ``_fixtures_df`` let tests inject synthetic data instead
    of reading real parquet files (mirrors fixture_outlook.py's leading-
    underscore keyword-arg testing convention).
    """
    if _teams_df is not None and _fixtures_df is not None:
        teams_df, fixtures_df = _teams_df, _fixtures_df
    else:
        root = merged_parquet_dir(season)
        teams_df = pd.read_parquet(root / "teams.parquet")
        fixtures_df = pd.read_parquet(root / "fixtures.parquet")

    fallback: dict[int, dict[str, float]] = {
        int(row["team_id"]): {f: float(row[f]) for f in STRENGTH_FIELDS}
        for _, row in teams_df.iterrows()
    }
    team_ids = list(fallback.keys())

    # The all-fixtures endpoint contains future (unscored) rows alongside
    # completed matches.  A checkpoint must use final results only: accepting
    # a partially-played fixture would make the value depend on the moment in
    # the gameweek at which the process happened to start.
    required_fixture_columns = {
        "event_id", "team_h", "team_a", "team_h_score", "team_a_score",
    }
    missing_columns = required_fixture_columns - set(fixtures_df.columns)
    if missing_columns:
        raise ValueError(
            "fixtures data is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    scored = fixtures_df["team_h_score"].notna() & fixtures_df["team_a_score"].notna()
    if "finished" in fixtures_df.columns:
        scored &= fixtures_df["finished"].fillna(False).astype(bool)
    past = fixtures_df[(fixtures_df["event_id"] < as_of_gw) & scored]

    # Per (team_id, venue) -> [(gw, goals_scored, goals_conceded), ...].
    by_team_venue: dict[tuple[int, str], list[tuple[int, int, int]]] = {}
    for _, row in past.iterrows():
        gw = int(row["event_id"])
        home_id, away_id = int(row["team_h"]), int(row["team_a"])
        home_score, away_score = int(row["team_h_score"]), int(row["team_a_score"])
        by_team_venue.setdefault((home_id, "home"), []).append((gw, home_score, away_score))
        by_team_venue.setdefault((away_id, "away"), []).append((gw, away_score, home_score))

    result: dict[int, dict[str, float]] = {tid: {} for tid in team_ids}

    for axis_name, value_index in (("attack", 1), ("defence", 2)):
        for venue in ("home", "away"):
            field = f"strength_{axis_name}_{venue}"

            own_avg: dict[int, float] = {}
            own_weight: dict[int, float] = {}
            for tid in team_ids:
                observations = [
                    (t[0], t[value_index])
                    for t in by_team_venue.get((tid, venue), [])
                ]
                avg, weight = _decayed_avg_and_weight(observations, as_of_gw, half_life_gws)
                own_weight[tid] = weight
                if avg is not None:
                    own_avg[tid] = avg

            fallback_rank = _percentile_rank({tid: fallback[tid][field] for tid in team_ids})
            use_own_rank = len(own_avg) >= _MIN_TEAMS_FOR_OWN_RANK
            # Defence quality is the INVERSE of goals conceded: a team that
            # concedes FEW must rank HIGH on strength_defence to match FPL's
            # convention (high = good defence). Without this negation the own
            # signal (rank by conceded, high = bad) and the FPL fallback (high
            # = good) carry opposite signs and blend to near-noise. Attack is
            # already aligned: more goals scored = higher strength.
            rank_input = own_avg if axis_name == "attack" else {tid: -v for tid, v in own_avg.items()}
            own_rank = _percentile_rank(rank_input) if use_own_rank else {}

            for tid in team_ids:
                weight = own_weight[tid]
                blend = (weight / (weight + prior_weight)) if use_own_rank else 0.0
                team_own_rank = own_rank.get(tid, fallback_rank[tid])
                blended = blend * team_own_rank + (1.0 - blend) * fallback_rank[tid]
                result[tid][field] = _OUTPUT_BASE + blended * _OUTPUT_SPAN

    return result


def _resolve_as_of_gw(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]]) -> int | None:
    """Find the first GW whose results must not influence the strengths.

    Prefer FPL's ``is_current`` marker while a gameweek is live, excluding its
    partial results.  Immediately after a completed gameweek no current event
    remains, so ``is_next`` permits that newly finalised round to influence the
    upcoming one.  The final fallback makes the helper usable with minimal,
    test-injected bootstrap payloads as well.
    """
    events = bootstrap.get("events", [])
    if isinstance(events, list):
        for marker in ("is_current", "is_next"):
            marked = [event for event in events if isinstance(event, dict) and event.get(marker)]
            if marked:
                try:
                    return min(int(event["id"]) for event in marked)
                except (KeyError, TypeError, ValueError):
                    pass

        upcoming = []
        for event in events:
            if not isinstance(event, dict) or event.get("finished"):
                continue
            try:
                upcoming.append(int(event["id"]))
            except (KeyError, TypeError, ValueError):
                continue
        if upcoming:
            return min(upcoming)

    completed = []
    for fixture in fixtures:
        if not isinstance(fixture, dict) or not fixture.get("finished"):
            continue
        try:
            completed.append(int(fixture["event"]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(completed) + 1 if completed else None


def inject_rolling_strength(
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    *,
    as_of_gw: int | None = None,
) -> bool:
    """Replace bootstrap team-strength fields with final-result walk-forward values.

    ``bootstrap`` is updated in place so every downstream consumer sees one
    coherent set of strengths.  The function is intentionally conservative:
    incomplete bootstrap payloads, unscored fixtures, and cold starts leave
    the original FPL values untouched and return ``False`` rather than
    degrading fixture responses.  A successful cold-start computation still
    returns ``True`` because it preserves the FPL fallback rank by design.

    Args:
        bootstrap: FPL ``bootstrap-static`` shape containing ``teams`` and
            optionally ``events``.
        fixtures: FPL all-fixtures payload.  Only rows marked ``finished``
            with both scores present can contribute.
        as_of_gw: Explicit checkpoint for deterministic callers/tests.  When
            omitted it is inferred from bootstrap event markers.
    """
    teams = bootstrap.get("teams")
    if not isinstance(teams, list) or not isinstance(fixtures, list):
        return False

    checkpoint = as_of_gw if as_of_gw is not None else _resolve_as_of_gw(bootstrap, fixtures)
    if not isinstance(checkpoint, int) or checkpoint < 1:
        return False

    team_rows: list[dict[str, Any]] = []
    for team in teams:
        if not isinstance(team, dict):
            return False
        try:
            team_id = int(team["id"])
        except (KeyError, TypeError, ValueError):
            return False
        values: dict[str, float] = {}
        for field in STRENGTH_FIELDS:
            value = team.get(field)
            if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(float(value)):
                return False
            values[field] = float(value)
        team_rows.append({"team_id": team_id, **values})

    fixture_rows: list[dict[str, int | bool]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict) or not fixture.get("finished"):
            continue
        try:
            fixture_rows.append({
                "event_id": int(fixture["event"]),
                "team_h": int(fixture["team_h"]),
                "team_a": int(fixture["team_a"]),
                "team_h_score": int(fixture["team_h_score"]),
                "team_a_score": int(fixture["team_a_score"]),
                "finished": True,
            })
        except (KeyError, TypeError, ValueError):
            # An anomalous fixture must not prevent the valid final results
            # from informing strengths for the rest of the league.
            continue

    teams_df = pd.DataFrame(team_rows)
    fixtures_df = pd.DataFrame(
        fixture_rows,
        columns=["event_id", "team_h", "team_a", "team_h_score", "team_a_score", "finished"],
    )
    strengths = compute_rolling_strength(
        "live",
        checkpoint,
        _teams_df=teams_df,
        _fixtures_df=fixtures_df,
    )
    for team in teams:
        for field, value in strengths[int(team["id"])].items():
            team[field] = value
    return True
