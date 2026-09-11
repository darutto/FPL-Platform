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

Zone grid (locked from the PoC — do not re-derive; handedness corrected)
-------------------------------------------------------------------------
Depth from Understat ``x``: ``in-box`` if x ≥ 0.84; ``edge-of-box`` if
0.70 ≤ x < 0.84; long-range shots are ignored as noise. Lateral from
Understat ``y``: ``right`` if y < 0.36; ``left`` if y > 0.64; else
``central``. Penalties are excluded from zonal aggregation (their xGA is
reported separately as context).

Coordinate orientation (flank-mirror fix, 2026-07-09)
-----------------------------------------------------
Understat's ``y`` axis grows toward the attacker's LEFT: the low band
(y < 0.36) is the attacker's RIGHT flank, the high band (y > 0.64) the
attacker's LEFT. The original T2a code had this mirrored ("left" for
y < 0.36) — proven wrong with known-flank players (right-siders
Saka/Salah/Bowen cluster in the low band; left-winger Mitoma in the high
band). The flank regression tests in test_zonal_weakness.py pin the
corrected orientation so it cannot silently re-invert.

The whole surface speaks ONE frame — the attacker/opportunity frame ("the
flank you attack down"): zone labels, verdicts ("ataca por la derecha"),
and the card's pitch view all agree. There is no defender-frame flip
anywhere anymore.

This is **zone-of-finish**, not buildup-flank: it says where conceded
chances are struck from, not which flank the attacking moves came down
(buildup-flank needs event-sequence data — Tier-2 FotMob, T3 follow-up).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

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
        latest_pointer_path,
        shots_parquet_path,
    )
    _FPL_TACTICAL_AVAILABLE = True
except ImportError:
    _FPL_TACTICAL_AVAILABLE = False
    PENALTY_SITUATION = None  # type: ignore[assignment]
    latest_pointer_path = None  # type: ignore[assignment]
    # fpl-tactical itself unavailable — fall back to the single source of
    # truth directly rather than a second, possibly-drifting literal copy.
    _FPL_DATA_CORE = os.path.join(_PKGS, "fpl-data-core")
    if _FPL_DATA_CORE not in sys.path:
        sys.path.append(_FPL_DATA_CORE)
    from fpl_data_core.season_registry import CURRENT_SEASON  # type: ignore[import] # noqa: E402


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Locked zone grid thresholds (PoC 2026-07-02 — do not re-derive).
IN_BOX_MIN_X: float = 0.84
EDGE_MIN_X: float = 0.70
# Lateral bands (attacker frame; Understat y grows toward the attacker's
# LEFT — flank-mirror fix 2026-07-09): low band = right flank, high = left.
RIGHT_MAX_Y: float = 0.36
LEFT_MIN_Y: float = 0.64

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

#: Team-scoped gates (i87). When get_zonal_opportunity is asked about ONE
#: team's players, the pool is ~eight attackers and the job is to rank them
#: against each other, not to find league standouts -- so the league gates
#: above are replaced by "any non-penalty shot, any zoned xG". Each row then
#: carries ``n_shots`` / ``zone_share`` / ``sample`` so the thinness is
#: visible instead of gated away. Never applied to the league-wide ranking.
TEAM_SCOPED_MIN_PLAYER_SHOTS: int = 1
TEAM_SCOPED_ZONE_SHARE_THRESHOLD: float = 0.0

#: i88 -- shot origin. Understat's non-penalty situations, as soccerdata
#: stores them. A player's zone profile keeps ALL of these (a centre-back's
#: far-post header from a corner is a real way to exploit a leaky left side
#: of the box), but each exploiter row says WHICH: ``origin`` is
#: ``open_play`` / ``set_piece`` / ``mixed`` from the set-piece share of the
#: player's xG in the zone that ranked them. Found 2026-09-11: Virgil van
#: Dijk ranked #2 "por la izquierda" against Fulham on two corner headers,
#: framed like a winger -- true signal, wrong story.
SET_PIECE_SITUATIONS: frozenset[str] = frozenset({
    "From Corner", "Set Piece", "Direct Freekick",
})
#: Above this set-piece share of the zone's xG the row is ``set_piece``;
#: below ``1 - ORIGIN_SET_PIECE_SHARE`` it is ``open_play``; between, ``mixed``.
ORIGIN_SET_PIECE_SHARE: float = 0.6

#: Max players listed per weak zone in get_zonal_opportunity.
TOP_PLAYERS_PER_ZONE: int = 5

#: Number of weakest zones surfaced (top by delta_vs_avg).
TOP_WEAK_ZONES: int = 2

#: T4b card — opportunity coding per in-box lateral zone, driven by
#: ``pct_over_avg = (xga_per_game / league_avg − 1) × 100``. "opp" = clearly
#: above league average (your best zone), "warm" = slightly above, "cool" =
#: at/below. Hand-tuned card heuristic, not a scoring-engine signal.
OPPORTUNITY_OPP_MIN_PCT: float = 15.0
OPPORTUNITY_WARM_MIN_PCT: float = 1.0

#: T4b zone-fit score scale. ``fit_score`` normalises the ranking value
#: ``zone_share × total_xg × max(pct_over_avg, 0) / 100`` to 0–10 across the
#: returned exploiters (10.0 = this answer's best zone/profile cross). The
#: delta weight is multiplicative so a modest scorer who concentrates xG in
#: a clearly-weak zone (+70%) outranks a volume scorer in a barely-weak one
#: (+2%) — the zone edge is the signal, volume only breaks it. Relative
#: within one answer — never comparable across questions.
FIT_SCORE_MAX: float = 10.0

#: Max exploiters returned for the card table (across all weak zones).
TOP_EXPLOITERS: int = 5

#: Attacker-frame lateral label → "the flank you attack down", in Spanish.
#: One frame everywhere — no defender-side flip (see orientation section).
_ATTACK_SIDE_ES: dict[str, str] = {
    "left": "por la izquierda",
    "right": "por la derecha",
    "central": "por el centro",
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
    if y < RIGHT_MAX_Y:
        lat = "right"
    elif y > LEFT_MIN_Y:
        lat = "left"
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
# Data provenance (i74) — every zonal answer names the season of its data
# ---------------------------------------------------------------------------
#
# Two rules make this a real provenance stamp instead of a tautology; both are
# pinned by mutation-killed tests in test_zonal_provenance.py.
#
#   1. WHAT THE STAMP SAYS comes from the on-disk pointer's own ``season``
#      field, never from CURRENT_SEASON. CURRENT_SEASON only *locates* the
#      store (it is the store key by construction), so a stamp sourced from it
#      could never disagree with the path — it would keep claiming the live
#      season over an empty, half-copied or mis-stamped parquet, because it
#      never looks at the content. When the pointer is absent or carries no
#      season we say so ("desconocida"); we never fall back to CURRENT_SEASON.
#
#   2. WHAT IT IS COMPARED AGAINST is the live season derived from the FPL
#      bootstrap (``fpl_historical.season_guard.derive_live_season``), never
#      CURRENT_SEASON. The store key IS CURRENT_SEASON, so comparing the two
#      reports "up to date" always — including today (2026-09-07: store
#      2025-2026, three gameweeks of 2026-2027 already played), which is
#      precisely the case the warning exists to catch. The comparison happens
#      in the tool wrappers, which are the layer that holds the bootstrap; the
#      engine accepts ``live_season`` and stays bootstrap-agnostic.
#
# Policy is DECLARE, never reject: a season mismatch downgrades the stamp, it
# never downgrades ``status`` to missing_context. Refusing would take the whole
# zonal surface offline until the season rotation (i73) lands.

#: Below this many stored matches the league baseline is too thin to trust —
#: a legitimately-stamped current-season store with only a few gameweeks in it
#: (exactly what the i73 rotation will create) says true things about its
#: season and still cannot support a league-relative signal. ~10 gameweeks of
#: a 20-team league; a full season is 380.
MIN_TRUSTWORTHY_MATCHES: int = 100

#: A full round of a 20-team league. Used only to translate the store's raw
#: (league-wide) match count into gameweeks for the "thin" label -- "sólo 30
#: partidos" reads as "this team has only played 30 matches," which is
#: wrong and alarming; "sólo 3 jornadas" says what's actually true.
MATCHES_PER_FULL_GAMEWEEK: int = 10


def _season_label(season: str) -> str:
    """``"2025-2026"`` -> ``"2025-26"`` for display; unknown shapes pass through."""
    parts = season.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 4:
        return f"{parts[0]}-{parts[1][2:]}"
    return season


def _read_pointer(store: Any) -> dict[str, Any] | None:
    """Return the provenance pointer describing the shots *store* resolves to.

    Mirrors ``_load_shots``'s resolution so the stamp always describes the
    bytes actually read: the owned store's ``_tactical_latest.json`` when
    *store* is None, the sibling pointer when *store* is a parquet path, and
    None for an in-memory DataFrame (tests / the nested call inside
    ``get_zonal_opportunity``) which carries no provenance at all.
    """
    if isinstance(store, pd.DataFrame):
        return None
    if store is None:
        if not _FPL_TACTICAL_AVAILABLE or latest_pointer_path is None:
            return None
        path = latest_pointer_path(CURRENT_SEASON)
    else:
        path = Path(store).parent / "_tactical_latest.json"
    if not path.exists():
        return None
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return pointer if isinstance(pointer, dict) else None


def build_data_provenance(
    pointer: dict[str, Any] | None, live_season: str | None
) -> dict[str, Any]:
    """Build the season stamp from *pointer* content vs the *live_season*.

    ``season`` is read out of the pointer file itself (rule 1 above);
    ``live_season`` must come from ``derive_live_season(bootstrap)`` (rule 2).
    ``status`` is one of:

    ``current``      pointer season == live season, with enough matches stored;
    ``stale_season`` pointer season != live season — the loud case;
    ``thin``         right season, but under ``MIN_TRUSTWORTHY_MATCHES``;
    ``unverified``   season known but no live season to check it against;
    ``unknown``      the store declares no season at all.

    Never raises and never guesses: an absent pointer yields ``unknown``,
    it does not silently adopt CURRENT_SEASON.
    """
    season = (pointer or {}).get("season")
    season = str(season) if season else None
    n_matches = (pointer or {}).get("n_matches")
    n_shots = (pointer or {}).get("n_shots")

    prov: dict[str, Any] = {
        "season": season,
        "season_label": _season_label(season) if season else None,
        "live_season": live_season,
        "live_season_label": _season_label(live_season) if live_season else None,
        "ingested_at": (pointer or {}).get("ingested_at"),
        "n_matches": int(n_matches) if isinstance(n_matches, (int, float)) else None,
        "n_shots": int(n_shots) if isinstance(n_shots, (int, float)) else None,
    }

    if season is None:
        prov["status"] = "unknown"
        prov["is_current"] = False
        prov["label"] = (
            "⚠ El almacén táctico no declara de qué temporada son estos datos"
        )
    elif live_season is None:
        prov["status"] = "unverified"
        prov["is_current"] = False
        prov["label"] = (
            f"Datos: temporada {prov['season_label']} "
            f"(no se pudo verificar la temporada en curso)"
        )
    elif season != live_season:
        prov["status"] = "stale_season"
        prov["is_current"] = False
        prov["label"] = (
            f"⚠ Datos de {prov['season_label']}, no de la temporada en curso "
            f"({prov['live_season_label']})"
        )
    elif prov["n_matches"] is not None and prov["n_matches"] < MIN_TRUSTWORTHY_MATCHES:
        prov["status"] = "thin"
        prov["is_current"] = True
        n_gameweeks = max(1, prov["n_matches"] // MATCHES_PER_FULL_GAMEWEEK)
        jornada_word = "jornada" if n_gameweeks == 1 else "jornadas"
        prov["label"] = (
            f"⚠ Datos de {prov['season_label']}, sólo {n_gameweeks} "
            f"{jornada_word} de liga — muestra corta para una lectura de liga"
        )
    else:
        prov["status"] = "current"
        prov["is_current"] = True
        prov["label"] = f"Datos: temporada {prov['season_label']}"
    return prov


def _provenance_for(store: Any, live_season: str | None) -> dict[str, Any]:
    """Convenience: read the pointer for *store* and stamp it."""
    return build_data_provenance(_read_pointer(store), live_season)


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


def _pct_over_avg(per_game: float, league_avg: float) -> float:
    """Deviation from the league baseline as a percentage (T4b card).

    ``league_avg <= 0`` cannot be divided through: 0 conceded against a 0
    baseline is no signal (0.0); anything conceded against a 0 baseline is
    capped at +100.0 rather than exploding.
    """
    if league_avg <= 0:
        return 0.0 if per_game <= 0 else 100.0
    return round((per_game / league_avg - 1.0) * 100.0, 1)


def _opportunity_level(pct_over_avg: float) -> str:
    """Map a zone's pct_over_avg to the card's opportunity coding."""
    if pct_over_avg >= OPPORTUNITY_OPP_MIN_PCT:
        return "opp"
    if pct_over_avg >= OPPORTUNITY_WARM_MIN_PCT:
        return "warm"
    return "cool"


_WEAKNESS_LABEL_ES: dict[str, str] = {
    "in-box": "Débil dentro del área",
    "edge-of-box": "Débil en la frontal del área",
}
_MARGINAL_LABEL_ES: dict[str, str] = {
    "in-box": "Ventaja leve dentro del área",
    "edge-of-box": "Ventaja leve en la frontal del área",
}


def _top_weak(weakest: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((z for z in weakest if z["delta_vs_avg"] > 0), None)


def weakness_strength(weakest: list[dict[str, Any]]) -> str:
    """``clear`` / ``marginal`` / ``none`` from the top weak zone's pct.

    i89: a lone exploiter under a +2% zone was being served with the same
    framing as a +70% one (found 2026-09-11, Sunderland: the only zone above
    average was in-box/left at +1.8%, one player in the league cleared the
    gate there, and the card presented him as if the read were strong).
    Thresholds are the card's own opportunity coding: ``clear`` = the top
    zone would shade "opp", ``marginal`` = it would shade "warm".
    """
    top = _top_weak(weakest)
    if top is None:
        return "none"
    pct = _pct_over_avg(top["xga_per_game"], top["league_avg"])
    if pct >= OPPORTUNITY_OPP_MIN_PCT:
        return "clear"
    if pct >= OPPORTUNITY_WARM_MIN_PCT:
        return "marginal"
    return "none"


def _weakness_label(weakest: list[dict[str, Any]]) -> str:
    """Card pill label from the top genuinely-weak zone's depth and strength."""
    top = _top_weak(weakest)
    strength = weakness_strength(weakest)
    if top is None or strength == "none":
        return "Sin debilidad clara"
    depth, _ = _split_zone(top["zone"])
    return (_WEAKNESS_LABEL_ES if strength == "clear" else _MARGINAL_LABEL_ES)[depth]


def _opportunity_verdict(team: str, weakest: list[dict[str, Any]]) -> str:
    """Spanish card verdict — attacker/opportunity frame ("ataca por…"),
    headline pct included. Never "débil por", never buy/sell. A marginal
    read says so FIRST, then names the least-bad zone."""
    top = _top_weak(weakest)
    strength = weakness_strength(weakest)
    if top is None or strength == "none":
        return (
            f"{team} no concede por encima de la media de la liga en "
            f"ninguna zona del área."
        )
    depth, lat = _split_zone(top["zone"])
    pct = _pct_over_avg(top["xga_per_game"], top["league_avg"])
    if strength == "marginal":
        return (
            f"{team} no concede claramente por encima de la media en ninguna "
            f"zona — la lectura más favorable es {_ATTACK_SIDE_ES[lat]} "
            f"{_DEPTH_ES[depth]} ({pct:+.0f}%), una ventaja leve."
        )
    return (
        f"Ataca a {team} {_ATTACK_SIDE_ES[lat]} {_DEPTH_ES[depth]} — "
        f"concede un {pct:+.0f}% sobre un equipo medio ahí."
    )


def _weakness_verdict(team: str, weakest: list[dict[str, Any]]) -> str:
    """Spanish one-liner for the text tool — same attacker/opportunity
    frame as the card ("ataca por…"). Never buy/sell."""
    above = [z for z in weakest if z["delta_vs_avg"] > 0]
    if not above or weakness_strength(weakest) == "none":
        return (
            f"{team} no concede por encima de la media de la liga en "
            f"ninguna zona del área."
        )
    if weakness_strength(weakest) == "marginal":
        return _opportunity_verdict(team, weakest)
    parts = []
    for z in above:
        depth, lat = _split_zone(z["zone"])
        parts.append(f"{_ATTACK_SIDE_ES[lat]} {_DEPTH_ES[depth]}")
    return (
        f"Ataca a {team} {' y '.join(parts)} — concede por encima de la "
        f"media de la liga ahí."
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def get_zonal_weakness(
    team: str, *, store: Any = None, live_season: str | None = None
) -> dict[str, Any]:
    """Relative zonal-weakness read for one team's defence.

    Returns ``status ∈ {ok, not_found, missing_context}``; on ok, each zone
    row carries ``xga_per_game``, the ``league_avg`` for that zone, the
    ``delta_vs_avg`` deviation (the signal — positive = leakier than the
    league), and ``rank`` (1 = league's most vulnerable defence in that
    zone). ``weakest_zones`` is the top-``TOP_WEAK_ZONES`` by delta;
    ``penalty_context`` reports penalty xGA separately (excluded from zones).
    """
    provenance = _provenance_for(store, live_season)
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
        "data_provenance": provenance,
    }


def compute_player_zone_shares(
    shots: pd.DataFrame,
    *,
    min_shots: int = MIN_PLAYER_SHOTS,
) -> dict[str, dict[str, Any]]:
    """Per-player share of own non-penalty xG per zone.

    Returns ``{player: {"team": str, "total_xg": float, "n_shots": int,
    "zone_share": {zone: share}}}`` for players with at least *min_shots*
    non-penalty shots (default ``MIN_PLAYER_SHOTS``). Long-range shots count
    toward the totals but no zone, so shares are conservative.
    """
    np_shots = _non_penalty(shots)
    out: dict[str, dict[str, Any]] = {}
    for player, rows in np_shots.groupby("player"):
        if len(rows) < min_shots:
            continue
        total_xg = float(rows["xg"].sum())
        if total_xg <= 0:
            continue
        zone_xg: dict[str, float] = {zone: 0.0 for zone in ZONES}
        zone_sp_xg: dict[str, float] = {zone: 0.0 for zone in ZONES}
        zone_shots: dict[str, int] = {zone: 0 for zone in ZONES}
        for row in rows.itertuples(index=False):
            zone = zone_of(row.x, row.y)
            if zone is not None:
                zone_xg[zone] += float(row.xg)
                zone_shots[zone] += 1
                if str(getattr(row, "situation", "")) in SET_PIECE_SITUATIONS:
                    zone_sp_xg[zone] += float(row.xg)
        out[str(player)] = {
            # a player's team = the side they shot for most recently
            "team": str(rows.sort_values("date").iloc[-1]["shooting_team"]),
            "total_xg": total_xg,
            "n_shots": int(len(rows)),
            "zone_share": {z: xg / total_xg for z, xg in zone_xg.items()},
            # i88: per-zone evidence -- shots taken there, and what fraction
            # of the zone's xG came from set pieces (0.0 when no zoned xG).
            "zone_shots": zone_shots,
            "zone_set_piece_share": {
                z: (zone_sp_xg[z] / xg if xg > 0 else 0.0) for z, xg in zone_xg.items()
            },
        }
    return out


def _origin_label(set_piece_share: float) -> str:
    """``set_piece`` / ``open_play`` / ``mixed`` from a zone's set-piece share."""
    if set_piece_share >= ORIGIN_SET_PIECE_SHARE:
        return "set_piece"
    if set_piece_share <= 1.0 - ORIGIN_SET_PIECE_SHARE:
        return "open_play"
    return "mixed"


def get_zonal_opportunity(
    opponent: str,
    *,
    position: str | None = None,
    team: "str | Sequence[str] | None" = None,
    store: Any = None,
    live_season: str | None = None,
) -> dict[str, Any]:
    """Join *opponent*'s weak zones to players who operate in those zones.

    i89: ``team`` may be one team or several -- "players from Arsenal,
    Liverpool and Man City to attack Brighton" is one table, ranked
    together, each row carrying its team. ``team_filter`` then reports
    ``requested_teams`` / ``matched_teams`` / ``unmatched_teams`` alongside
    the joined ``requested`` / ``matched`` strings the single-team callers
    and the card already read.

    A player "operates" in a zone when ≥ ``PLAYER_ZONE_XG_SHARE_THRESHOLD``
    of their own non-penalty xG comes from it (with ≥ ``MIN_PLAYER_SHOTS``
    shots). Players of *opponent* itself are excluded; the rest are ranked
    by their xG concentration in the zone, top ``TOP_PLAYERS_PER_ZONE``.

    ``team``, when given, restricts every ranking to players whose store
    team matches it (case-insensitive exact match against the store's own
    team names — same convention as ``opponent``). Without it, rankings run
    across the whole league. This exists because "which of TEAM's players
    can exploit OPPONENT" is a different, legitimate question from "who
    overall can exploit OPPONENT" — the unfiltered top-``TOP_EXPLOITERS``
    list can easily contain zero players from a specific team even when
    that team has a real (if not globally top-ranked) zonal fit; silently
    reusing the unfiltered list for a team-scoped question misreads "not in
    the global top 5" as "no such player exists," which is a materially
    different and false claim (found 2026-09-11 asking about Liverpool
    players against Fulham — none of Fulham's global top-5 exploiters play
    for Liverpool, which said nothing about whether any Liverpool player
    actually qualifies). ``team_filter`` in the response echoes what was
    (or was not) matched, so a caller can tell "filtered, zero qualified"
    apart from "filter didn't resolve."

    ``position`` is reserved: the Understat store carries no player
    positions, so filtering by position needs an FPL-bootstrap join (T4
    follow-up). It is accepted and ignored for now, and the tool schema
    does not expose it.

    T4b card enrichment (additive): ``zones`` carries the three in-box
    lateral cells (attacker-frame ``lateral`` ∈ left/central/right) with
    ``pct_over_avg`` and ``opportunity_level`` for the pitch view;
    ``exploiters`` is the flat ranked table — the zone-fit heuristic
    ``zone_share × total_xg × max(pct_over_avg, 0)/100`` normalised to
    a 0–10 ``fit_score`` (see ``FIT_SCORE_MAX``), deduped to each player's
    best zone, opponent's own players excluded; ``weakness_label`` /
    ``verdict`` / ``penalty_context`` feed the card header and footer.
    Everything is opportunity/suitability-framed — never buy/sell.
    """
    provenance = _provenance_for(store, live_season)
    shots = _load_shots(store)
    if shots is None:
        return {"status": "missing_context", "opponent": opponent}

    weakness = get_zonal_weakness(opponent, store=shots)
    if weakness["status"] != "ok":
        return {"status": weakness["status"], "opponent": opponent}
    matched = weakness["team"]

    # Gates. League-wide, the question is "who STANDS OUT in this zone" and
    # the gates prune a ~500-player pool to players with a real, established
    # zonal profile. Team-scoped, the question is "rank THIS team's
    # attackers by fit" -- a pool of maybe eight -- and the same gates just
    # empty the answer (measured 2026-09-11: 3 GWs in, Liverpool scoped
    # against Fulham returned [] because no Liverpool player had 10
    # non-penalty shots yet; a caller deciding between that team's wingers
    # learns nothing from an empty list). So a resolved team filter ranks
    # every player of that team with any zoned xG, with the thin per-player
    # samples made visible (``n_shots``, ``zone_share``, ``sample``) instead
    # of hidden behind a gate.
    requested_teams: list[str] = (
        [team] if isinstance(team, str) else [str(t) for t in (team or []) if str(t).strip()]
    )
    matched_teams: list[str] = []
    unmatched_teams: list[str] = []
    if requested_teams:
        # Match against every team that has shot for itself in the store
        # (shooting_team) -- not just teams already surviving into `shares`,
        # so a team with real data but no individual qualifying scorer
        # still resolves (to zero exploiters), rather than being reported
        # as an unresolved filter.
        store_teams = sorted(shots["shooting_team"].unique())
        for t in requested_teams:
            m = _match_team(t, store_teams)
            if m is None:
                unmatched_teams.append(t)
            elif m not in matched_teams:
                matched_teams.append(m)
    team_filter_matched: str | None = ", ".join(matched_teams) if matched_teams else None
    team_scoped = bool(matched_teams)
    min_shots = TEAM_SCOPED_MIN_PLAYER_SHOTS if team_scoped else MIN_PLAYER_SHOTS
    share_threshold = (
        TEAM_SCOPED_ZONE_SHARE_THRESHOLD if team_scoped else PLAYER_ZONE_XG_SHARE_THRESHOLD
    )

    shares = compute_player_zone_shares(shots, min_shots=min_shots)
    if requested_teams:
        _matched_set = set(matched_teams)
        shares = (
            {p: info for p, info in shares.items() if info["team"] in _matched_set}
            if team_scoped
            else {}
        )

    opportunities: list[dict[str, Any]] = []
    for zone_row in weakness["weakest_zones"]:
        if zone_row["delta_vs_avg"] <= 0:
            continue  # only zones genuinely above league average
        zone = zone_row["zone"]
        candidates = [
            (info["zone_share"][zone] * info["total_xg"], player)
            for player, info in shares.items()
            if info["team"] != matched
            and info["zone_share"][zone] >= share_threshold
            and info["zone_share"][zone] > 0
        ]
        candidates.sort(key=lambda pair: (-pair[0], pair[1]))
        opportunities.append(
            {
                "zone": zone,
                "delta_vs_avg": zone_row["delta_vs_avg"],
                "players": [player for _, player in candidates[:TOP_PLAYERS_PER_ZONE]],
            }
        )

    # ------------------------------------------------------------------
    # T4b card enrichment — pitch cells, ranked exploiters, header/footer.
    # ------------------------------------------------------------------
    zone_rows = {z["zone"]: z for z in weakness["zones"]}
    zones_out: list[dict[str, Any]] = []
    for lat in ("left", "central", "right"):
        row = zone_rows[f"in-box / {lat}"]
        pct = _pct_over_avg(row["xga_per_game"], row["league_avg"])
        zones_out.append(
            {
                "lateral": lat,
                "zone": row["zone"],
                "pct_over_avg": pct,
                "opportunity_level": _opportunity_level(pct),
            }
        )

    # Zone-fit ranking across the weak zones; each player keeps their best
    # zone (raw = zone_share × total_xg × max(pct, 0)/100, see FIT_SCORE_MAX
    # docs). Ties break alphabetically for determinism.
    raw_by_player: dict[str, tuple[float, str, str]] = {}
    for zone_row in weakness["weakest_zones"]:
        if zone_row["delta_vs_avg"] <= 0:
            continue
        zone = zone_row["zone"]
        pct = _pct_over_avg(zone_row["xga_per_game"], zone_row["league_avg"])
        weight = max(pct, 0.0) / 100.0
        for player, info in shares.items():
            if info["team"] == matched:
                continue
            share = info["zone_share"][zone]
            if share < share_threshold or share <= 0:
                continue
            raw = share * info["total_xg"] * weight
            prev = raw_by_player.get(player)
            if prev is None or raw > prev[0]:
                raw_by_player[player] = (raw, zone, info["team"])
    ranked = sorted(
        raw_by_player.items(), key=lambda kv: (-kv[1][0], kv[0])
    )[:TOP_EXPLOITERS]
    max_raw = ranked[0][1][0] if ranked else 0.0
    exploiters = [
        {
            "rank": i + 1,
            "player": player,
            "team": team_name,
            "zone": zone,
            "fit_score": round(FIT_SCORE_MAX * raw / max_raw, 1) if max_raw > 0 else 0.0,
            # Per-player evidence behind the score, so a thin sample is
            # visible rather than hidden behind a gate (matters most when
            # team-scoped, where the gates are relaxed on purpose).
            "n_shots": shares[player]["n_shots"],
            "zone_share": round(shares[player]["zone_share"][zone], 3),
            "sample": "thin" if shares[player]["n_shots"] < MIN_PLAYER_SHOTS else "ok",
            # i88: why this player fits THIS zone -- how many of their shots
            # were struck there, and whether that xG came from open play or
            # set pieces. A row can be a real fit and still be "two corner
            # headers"; the reader must be able to see which.
            "zone_shots": shares[player]["zone_shots"][zone],
            "set_piece_share": round(shares[player]["zone_set_piece_share"][zone], 3),
            "origin": _origin_label(shares[player]["zone_set_piece_share"][zone]),
        }
        for i, (player, (raw, zone, team_name)) in enumerate(ranked)
    ]

    result: dict[str, Any] = {
        "status": "ok",
        "opponent": matched,
        "opportunities": opportunities,
        "zones": zones_out,
        "exploiters": exploiters,
        "weakness_label": _weakness_label(weakness["weakest_zones"]),
        "verdict": _opportunity_verdict(matched, weakness["weakest_zones"]),
        "penalty_context": weakness["penalty_context"],
        "data_provenance": provenance,
    }
    result["weakness_strength"] = weakness_strength(weakness["weakest_zones"])
    if requested_teams:
        # matched is None when NO requested team resolved against the store
        # -- distinct from resolving fine but nobody on those teams having
        # any zoned xG at all (exploiters would then just be empty with
        # matched set). Partial resolution lists the misses in
        # unmatched_teams and proceeds with the rest.
        result["team_filter"] = {
            "requested": ", ".join(requested_teams),
            "matched": team_filter_matched,
            "requested_teams": requested_teams,
            "matched_teams": matched_teams,
            "unmatched_teams": unmatched_teams,
            # The gates actually applied, so the consumer knows the ranking
            # is "this team's attackers relative to each other" and not
            # "league standouts" -- and the LLM can say so.
            "min_shots": min_shots,
            "zone_share_threshold": share_threshold,
        }
    return result


# ---------------------------------------------------------------------------
# Player-centric outlook (T-player: /player Saka → next fixtures matchup read)
# ---------------------------------------------------------------------------

def _find_store_player(
    player_query: str, shares: dict[str, dict[str, Any]]
) -> tuple[str | None, list[str]]:
    """Match *player_query* against store player names.

    Case-insensitive exact match wins; otherwise substring. Returns
    ``(match, candidates)`` — a unique match, or None with the (possibly
    empty / multiple) candidate list for not_found / ambiguous handling.
    """
    q = player_query.strip().lower()
    exact = [p for p in shares if p.lower() == q]
    candidates = exact or [p for p in shares if q in p.lower()]
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, sorted(candidates)


def get_player_zonal_outlook(
    player_query: str,
    *,
    fixtures_for_team: Any,
    store: Any = None,
    live_season: str | None = None,
) -> dict[str, Any]:
    """Per-fixture zonal matchup read for one player's upcoming opponents.

    *fixtures_for_team* is a callable ``(store_team_name) -> list[fixture]``
    injected by the tool wrapper (fixtures live in the FPL bootstrap, not in
    the tactical store — the engine stays bootstrap-agnostic). Each fixture
    dict: ``{"gameweek": int, "opponent": <store team name>, "is_home": bool}``.

    A fixture is ``favorable`` when the opponent concedes above the league
    baseline in a zone (their top-``TOP_WEAK_ZONES``, positive delta only)
    where the player concentrates ≥ ``PLAYER_ZONE_XG_SHARE_THRESHOLD`` of
    their own non-penalty xG; ``neutral`` otherwise; ``no_data`` when the
    opponent is absent from the store (e.g. newly promoted side).

    Returns ``status ∈ {ok, not_found, ambiguous, missing_context}``; on ok:
    ``player``, ``team``, ``player_zones`` (zones the player operates in,
    share-sorted), ``outlook`` (per-fixture entries with ``matches`` carrying
    ``zone`` / ``delta_vs_avg`` / ``player_share``), and a Spanish,
    opportunity-framed ``verdict`` (never buy/sell).
    """
    provenance = _provenance_for(store, live_season)
    shots = _load_shots(store)
    if shots is None:
        return {"status": "missing_context", "player": player_query}

    shares = compute_player_zone_shares(shots)
    player, candidates = _find_store_player(player_query, shares)
    if player is None:
        if candidates:
            return {
                "status": "ambiguous",
                "player": player_query,
                "candidates": candidates[:5],
            }
        return {"status": "not_found", "player": player_query}

    info = shares[player]
    player_zones = sorted(
        (
            {"zone": zone, "share": round(share, 4)}
            for zone, share in info["zone_share"].items()
            if share >= PLAYER_ZONE_XG_SHARE_THRESHOLD
        ),
        key=lambda z: -z["share"],
    )

    fixtures = fixtures_for_team(info["team"]) or []
    if not fixtures:
        return {"status": "missing_context", "player": player, "team": info["team"]}

    profiles = compute_team_zone_profiles(shots)
    baseline = compute_league_baseline(profiles)

    outlook: list[dict[str, Any]] = []
    for fx in fixtures:
        opponent_raw = str(fx.get("opponent", ""))
        entry: dict[str, Any] = {
            "gameweek": int(fx.get("gameweek", 0)),
            "opponent": opponent_raw,
            "is_home": bool(fx.get("is_home", False)),
            "matches": [],
        }
        matched = _match_team(opponent_raw, list(profiles))
        if matched is None:
            entry["status"] = "no_data"
            outlook.append(entry)
            continue
        entry["opponent"] = matched
        deltas = sorted(
            (
                (
                    (profiles[matched][zone]["xga"] / profiles[matched][zone]["games"]
                     if profiles[matched][zone]["games"] else 0.0) - baseline[zone],
                    zone,
                )
                for zone in ZONES
            ),
            reverse=True,
        )[:TOP_WEAK_ZONES]
        for delta, zone in deltas:
            if delta <= 0:
                continue
            share = info["zone_share"][zone]
            if share >= PLAYER_ZONE_XG_SHARE_THRESHOLD:
                entry["matches"].append(
                    {
                        "zone": zone,
                        "delta_vs_avg": round(delta, 4),
                        "player_share": round(share, 4),
                    }
                )
        entry["status"] = "favorable" if entry["matches"] else "neutral"
        outlook.append(entry)

    favorable = [e for e in outlook if e["status"] == "favorable"]
    if favorable:
        gws = " y ".join(
            f"J{e['gameweek']} ({e['opponent']})" for e in favorable
        )
        verdict = (
            f"{player} genera su xG justo en zonas donde el rival concede por "
            f"encima de la media — cruce favorable en {gws}."
        )
    else:
        verdict = (
            f"Sin cruce zonal destacado para {player} en las próximas "
            f"{len(outlook)} jornadas."
        )

    return {
        "status": "ok",
        "player": player,
        "team": info["team"],
        "player_zones": player_zones,
        "outlook": outlook,
        "verdict": verdict,
        "data_provenance": provenance,
    }
