"""
fpl_grounded_assistant.zonal_weakness
=====================================
Tactical track (T2a) — zonal defensive-weakness engine.

Pure and deterministic — no LLM, no tool registry, no network. Reads the
owned tactical parquet store built by ``packages/fpl-tactical`` (Understat
shot events) and turns it into a **relative** zonal-weakness signal. The
tool wrapper (T2b, ``zonal_weakness_tool.py``) is where ``TOOL_REGISTRY``
is touched — mirroring the ``fixture_outlook`` engine/tool split of Track D.

The signal is relative, never absolute
--------------------------------------
Central in-box zones dominate raw xGA for every team in the league (PoC,
2026-07-02: league avg in-box xGA/game — left 0.079 · central 1.159 ·
right 0.081), so raw zone totals say nothing about a *particular* defence.
The only meaningful signal is **deviation from the league baseline per
zone** (``delta_vs_avg``). Verdicts are Spanish, opportunity/weakness-framed
only — advice framing (buy/sell/captain) stays owned by the deterministic
advice engines.

Zone grid (locked from the PoC — do not re-derive)
--------------------------------------------------
Depth from Understat ``x``: ``in-box`` if x ≥ 0.84; ``edge-of-box`` if
0.70 ≤ x < 0.84; long-range shots are ignored as noise. Lateral from
Understat ``y``: ``left`` if y < 0.36; ``right`` if y > 0.64; else
``central``. Penalties are excluded from zonal aggregation (their xGA is
reported separately as context).

Coordinate orientation caveat
-----------------------------
Understat's ``y`` axis is fixed with the attack always pointing the same
way, so the lateral labels are from the **attacking team's perspective**:
a defence that leaks shots in the ``left`` lateral band is weak down *its
own right side*. Verdicts flip the axis into the defending team's frame
("por su costado derecho"); the raw ``zone`` labels in the payload keep the
attacker frame. A test asserts this orientation.

This is **zone-of-finish**, not buildup-flank: it says where conceded
chances are struck from, not which flank the attacking moves came down
(buildup-flank needs event-sequence data — Tier-2 FotMob, T3 follow-up).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# sys.path shim — mirror owned_store_fallback.py's pattern so the shared
# fpl_tactical constants/paths are importable without pyproject changes.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))         # fpl_grounded_assistant/
_PKG  = os.path.dirname(_HERE)                             # fpl-grounded-assistant/
_PKGS = os.path.dirname(_PKG)                              # packages/
_FPL_TACTICAL = os.path.join(_PKGS, "fpl-tactical")

if _FPL_TACTICAL not in sys.path:
    sys.path.insert(0, _FPL_TACTICAL)

# If fpl-tactical is not on disk this module still loads; every public
# function then degrades to status="missing_context" (the store cannot be
# located without fpl_tactical.paths either, so the two go together).
try:
    from fpl_tactical import PENALTY_SITUATION  # type: ignore[import]
    from fpl_tactical.paths import (  # type: ignore[import]
        CURRENT_SEASON,
        shots_parquet_path,
    )
    _FPL_TACTICAL_AVAILABLE = True
except ImportError:
    _FPL_TACTICAL_AVAILABLE = False
    PENALTY_SITUATION = None  # type: ignore[assignment]
    CURRENT_SEASON = "2025-2026"  # fallback so default args still resolve


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Locked zone grid thresholds (PoC 2026-07-02 — do not re-derive).
IN_BOX_MIN_X: float = 0.84
EDGE_MIN_X: float = 0.70
LEFT_MAX_Y: float = 0.36
RIGHT_MIN_Y: float = 0.64

#: All zone keys, attacker-perspective lateral labels.
ZONES: tuple[str, ...] = tuple(
    f"{depth} / {lat}"
    for depth in ("in-box", "edge-of-box")
    for lat in ("left", "central", "right")
)

#: A player "operates" in a zone when at least this share of their own
#: non-penalty xG comes from it (T2c opportunity matcher).
PLAYER_ZONE_XG_SHARE_THRESHOLD: float = 0.25

#: Minimum non-penalty shots before a player's zone profile is trusted.
MIN_PLAYER_SHOTS: int = 10

#: Max players listed per weak zone in get_zonal_opportunity.
TOP_PLAYERS_PER_ZONE: int = 5

#: Number of weakest zones surfaced (top by delta_vs_avg).
TOP_WEAK_ZONES: int = 2

#: Attacker-frame lateral label → defending team's own side, in Spanish.
#: (Attacker's left is the defence's right — see orientation caveat above.)
_DEFENSIVE_SIDE_ES: dict[str, str] = {
    "left": "su costado derecho",
    "right": "su costado izquierdo",
    "central": "el centro",
}

_DEPTH_ES: dict[str, str] = {
    "in-box": "dentro del área",
    "edge-of-box": "en la frontal del área",
}


def zone_of(x: float, y: float) -> str | None:
    """Return the zone key for a shot at Understat (x, y), or None if long-range."""
    if x >= IN_BOX_MIN_X:
        depth = "in-box"
    elif x >= EDGE_MIN_X:
        depth = "edge-of-box"
    else:
        return None
    if y < LEFT_MAX_Y:
        lat = "left"
    elif y > RIGHT_MIN_Y:
        lat = "right"
    else:
        lat = "central"
    return f"{depth} / {lat}"


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------

def _load_shots(store: Any) -> pd.DataFrame | None:
    """Resolve *store* into the shots DataFrame, or None when unavailable.

    *store* may be a pandas DataFrame (tests), a path to the season parquet,
    or None → the default owned-store location for CURRENT_SEASON.
    """
    if isinstance(store, pd.DataFrame):
        return store if len(store) else None
    if store is None:
        if not _FPL_TACTICAL_AVAILABLE:
            return None
        path = shots_parquet_path(CURRENT_SEASON)
    else:
        path = Path(store)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return df if len(df) else None


def _non_penalty(shots: pd.DataFrame) -> pd.DataFrame:
    """Drop penalties using the shared fpl_tactical constant."""
    return shots[shots["situation"] != PENALTY_SITUATION]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_team_zone_profiles(
    shots: pd.DataFrame, *, min_x: float = EDGE_MIN_X
) -> dict[str, dict[str, dict[str, float]]]:
    """Per-team defensive zone profiles from normalized shot rows.

    Returns ``{team: {zone: {"shots": n, "xga": x, "goals": g, "games": m}}}``
    with every team carrying all zones (zero-filled) so downstream baselines
    average correctly. Penalties are excluded; ``games`` counts the team's
    distinct matches in the store (including matches with no in-zone shots).
    """
    games = shots.groupby("conceding_team")["match_id"].nunique()
    np_shots = _non_penalty(shots)

    profiles: dict[str, dict[str, dict[str, float]]] = {
        team: {
            zone: {"shots": 0, "xga": 0.0, "goals": 0, "games": int(n_games)}
            for zone in ZONES
        }
        for team, n_games in games.items()
    }
    for row in np_shots.itertuples(index=False):
        if row.x < min_x:
            continue
        zone = zone_of(row.x, row.y)
        if zone is None:
            continue
        cell = profiles[row.conceding_team][zone]
        cell["shots"] += 1
        cell["xga"] += float(row.xg)
        cell["goals"] += 1 if row.result == "Goal" else 0
    return profiles


def compute_league_baseline(
    profiles: dict[str, dict[str, dict[str, float]]],
) -> dict[str, float]:
    """League mean xGA/game per zone across all teams in *profiles*."""
    if not profiles:
        return {}
    baseline: dict[str, float] = {}
    for zone in ZONES:
        per_game = [
            team_zones[zone]["xga"] / team_zones[zone]["games"]
            for team_zones in profiles.values()
            if team_zones[zone]["games"] > 0
        ]
        baseline[zone] = sum(per_game) / len(per_game) if per_game else 0.0
    return baseline


def _match_team(name: str, teams: list[str]) -> str | None:
    """Case-insensitive exact match of *name* against stored team names."""
    lowered = name.strip().lower()
    for team in teams:
        if team.lower() == lowered:
            return team
    return None


def _split_zone(zone: str) -> tuple[str, str]:
    depth, lat = zone.split(" / ")
    return depth, lat


def _weakness_verdict(team: str, weakest: list[dict[str, Any]]) -> str:
    """Spanish, weakness/opportunity-framed one-liner. Never buy/sell."""
    above = [z for z in weakest if z["delta_vs_avg"] > 0]
    if not above:
        return (
            f"{team} no concede por encima de la media de la liga en "
            f"ninguna zona del área."
        )
    parts = []
    for z in above:
        depth, lat = _split_zone(z["zone"])
        parts.append(f"{_DEPTH_ES[depth]} por {_DEFENSIVE_SIDE_ES[lat]}")
    return f"{team} concede por encima de la media {' y '.join(parts)}."


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def get_zonal_weakness(team: str, *, store: Any = None) -> dict[str, Any]:
    """Relative zonal-weakness read for one team's defence.

    Returns ``status ∈ {ok, not_found, missing_context}``; on ok, each zone
    row carries ``xga_per_game``, the ``league_avg`` for that zone, the
    ``delta_vs_avg`` deviation (the signal — positive = leakier than the
    league), and ``rank`` (1 = league's most vulnerable defence in that
    zone). ``weakest_zones`` is the top-``TOP_WEAK_ZONES`` by delta;
    ``penalty_context`` reports penalty xGA separately (excluded from zones).
    """
    shots = _load_shots(store)
    if shots is None:
        return {"status": "missing_context", "team": team}

    profiles = compute_team_zone_profiles(shots)
    matched = _match_team(team, list(profiles))
    if matched is None:
        return {"status": "not_found", "team": team}

    baseline = compute_league_baseline(profiles)

    # League-wide per-zone deltas → rank of each team within each zone.
    deltas_by_zone: dict[str, dict[str, float]] = {}
    for zone in ZONES:
        deltas_by_zone[zone] = {
            t: (p[zone]["xga"] / p[zone]["games"] if p[zone]["games"] else 0.0)
            - baseline[zone]
            for t, p in profiles.items()
        }

    zones_out: list[dict[str, Any]] = []
    for zone in ZONES:
        cell = profiles[matched][zone]
        per_game = cell["xga"] / cell["games"] if cell["games"] else 0.0
        delta = deltas_by_zone[zone][matched]
        rank = 1 + sum(
            1 for d in deltas_by_zone[zone].values() if d > delta
        )
        zones_out.append(
            {
                "zone": zone,
                "xga_per_game": round(per_game, 4),
                "league_avg": round(baseline[zone], 4),
                "delta_vs_avg": round(delta, 4),
                "rank": rank,
            }
        )
    weakest = sorted(zones_out, key=lambda z: -z["delta_vs_avg"])[:TOP_WEAK_ZONES]

    team_rows = shots[shots["conceding_team"] == matched]
    pen_rows = team_rows[team_rows["situation"] == PENALTY_SITUATION]
    n_games = int(team_rows["match_id"].nunique())
    pen_xga = float(pen_rows["xg"].sum())

    return {
        "status": "ok",
        "team": matched,
        "zones": zones_out,
        "weakest_zones": weakest,
        "penalty_context": {
            "penalty_xga": round(pen_xga, 4),
            "penalty_xga_per_game": round(pen_xga / n_games, 4) if n_games else 0.0,
        },
        "verdict": _weakness_verdict(matched, weakest),
    }


def compute_player_zone_shares(
    shots: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Per-player share of own non-penalty xG per zone.

    Returns ``{player: {"team": str, "total_xg": float, "n_shots": int,
    "zone_share": {zone: share}}}`` for players with at least
    ``MIN_PLAYER_SHOTS`` non-penalty shots. Long-range shots count toward
    the totals but no zone, so shares are conservative.
    """
    np_shots = _non_penalty(shots)
    out: dict[str, dict[str, Any]] = {}
    for player, rows in np_shots.groupby("player"):
        if len(rows) < MIN_PLAYER_SHOTS:
            continue
        total_xg = float(rows["xg"].sum())
        if total_xg <= 0:
            continue
        zone_xg: dict[str, float] = {zone: 0.0 for zone in ZONES}
        for row in rows.itertuples(index=False):
            zone = zone_of(row.x, row.y)
            if zone is not None:
                zone_xg[zone] += float(row.xg)
        out[str(player)] = {
            # a player's team = the side they shot for most recently
            "team": str(rows.sort_values("date").iloc[-1]["shooting_team"]),
            "total_xg": total_xg,
            "n_shots": int(len(rows)),
            "zone_share": {z: xg / total_xg for z, xg in zone_xg.items()},
        }
    return out


def get_zonal_opportunity(
    opponent: str, *, position: str | None = None, store: Any = None
) -> dict[str, Any]:
    """Join *opponent*'s weak zones to players who operate in those zones.

    A player "operates" in a zone when ≥ ``PLAYER_ZONE_XG_SHARE_THRESHOLD``
    of their own non-penalty xG comes from it (with ≥ ``MIN_PLAYER_SHOTS``
    shots). Players of *opponent* itself are excluded; the rest are ranked
    by their xG concentration in the zone, top ``TOP_PLAYERS_PER_ZONE``.

    ``position`` is reserved: the Understat store carries no player
    positions, so filtering by position needs an FPL-bootstrap join (T4
    follow-up). It is accepted and ignored for now, and the tool schema
    does not expose it.
    """
    shots = _load_shots(store)
    if shots is None:
        return {"status": "missing_context", "opponent": opponent}

    weakness = get_zonal_weakness(opponent, store=shots)
    if weakness["status"] != "ok":
        return {"status": weakness["status"], "opponent": opponent}
    matched = weakness["team"]

    shares = compute_player_zone_shares(shots)
    opportunities: list[dict[str, Any]] = []
    for zone_row in weakness["weakest_zones"]:
        if zone_row["delta_vs_avg"] <= 0:
            continue  # only zones genuinely above league average
        zone = zone_row["zone"]
        candidates = [
            (info["zone_share"][zone] * info["total_xg"], player)
            for player, info in shares.items()
            if info["team"] != matched
            and info["zone_share"][zone] >= PLAYER_ZONE_XG_SHARE_THRESHOLD
        ]
        candidates.sort(key=lambda pair: (-pair[0], pair[1]))
        opportunities.append(
            {
                "zone": zone,
                "delta_vs_avg": zone_row["delta_vs_avg"],
                "players": [player for _, player in candidates[:TOP_PLAYERS_PER_ZONE]],
            }
        )
    return {"status": "ok", "opponent": matched, "opportunities": opportunities}
