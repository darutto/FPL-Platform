"""
fpl_grounded_assistant.fixture_outlook
======================================
Track D — Fixture Intelligence.

FI0: Two-axis fixture difficulty model (deterministic).
FI1: Run / tendency detection.

This module is the **engine** for the fixture-outlook feature.  It is pure
and deterministic — no LLM, no live API calls beyond the bootstrap that is
already in hand.  The tool wrapper (FI2), player integration (FI3), and the
visual surfaces (FI4/FI5/FI7) build on top of the public functions here.

Why two axes?
-------------
A single FDR number conflates two very different questions:

* **attack**  — how hard is it for *this* team to score?  (matters for
  attackers / captaincy)
* **defence** — how hard is it for *this* team to keep a clean sheet?
  (matters for defenders / goalkeepers)

NextXI's ticker splits these with an attack/clean-sheet toggle.  We compute
**both** and let the caller pick the axis — FI3 maps it from player position
(attacker → ``attack``, DEF/GKP → ``defence``).

The difficulty model (FI0, FDR-first)
-------------------------------------
Difficulty is **FDR-first**: each fixture's band is FPL's own official FDR
(``difficulty``, already a 1–5 value). The ML0 evaluation harness
(``scripts/backtest_fixture_difficulty.py``) scored every 2025-26 team-fixture
against season xG and found FPL's FDR out-predicts our home-grown
opponent-strength quintile banding on BOTH axes (attack +0.281 vs +0.087,
defence +0.307 vs +0.145), so FDR is the primary signal.

The opponent venue-aware **strength** model is retained only as a *fallback*
for fixtures that carry no usable FDR:

* attack difficulty for our team  = opponent's **defence** strength at the
  venue the opponent is playing (we home → opponent away → ``..._away``).
* defence difficulty for our team = opponent's **attack** strength at that
  venue.

bucketed into 5 bands via league-wide quintile thresholds, then finally band 3.

Because FDR is axis-agnostic, attack and defence bands coincide when FDR is
present; ``axis`` still selects the verdict wording (and, via FI3a, the
per-player axis). Re-separating the axes with a walk-forward defensive-form
overlay (the ML0-validated improvement) is a later step, gated on a runtime
rolling-form pipeline. Poisson / expected-goals calibration remains FI6.

Run / tendency detection (FI1)
------------------------------
Over a bounded horizon (default **10 GWs** — long enough to surface genuine
runs), each GW is classified ``good`` (band ≤ 2), ``bad`` (band ≥ 4) or
``neutral`` (band 3).  Blank GWs break runs.  Consecutive same-class stretches
of length ≥ 3 become a *run*, graded ``strong`` (≥ 5 GWs) or ``mild`` (3–4).

Language discipline
-------------------
Output is **schedule-only** — it highlights good/bad *runs* ("calendario
verde J34–38"), never buy/sell advice.  Transfer/captain framing stays owned
by the advice engines (FI3).  This preserves the ``team_fixture_calendar``
invariant.
"""
from __future__ import annotations

import math
from typing import Any

# NOTE: this engine is intentionally dependency-light — stdlib only, no
# intra-package imports.  The four bootstrap helpers below mirror the ones in
# ``team_fixture_calendar`` but are inlined on purpose: that module registers
# tools on import (pulling the whole tool-runner graph), and FI0/FI1 must stay
# a pure, side-effect-free engine.  The tool wrapper (FI2) is where
# ``TOOL_REGISTRY`` is touched.


def _get_current_gameweek(bootstrap: dict[str, Any]) -> int | None:
    for ev in bootstrap.get("events", []):
        if ev.get("is_current"):
            return int(ev["id"])
    return None


def _team_short_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    return {
        int(t["id"]): str(t.get("short_name", f"T{t['id']}"))
        for t in bootstrap.get("teams", [])
    }


def _team_name_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    return {
        int(t["id"]): str(t.get("name", f"Team {t['id']}"))
        for t in bootstrap.get("teams", [])
    }


def _get_active_gws(
    team_fixtures: dict,
    current_gw: int,
    horizon: int,
) -> frozenset[int]:
    """GWs in ``[current_gw, current_gw+horizon)`` that have ≥1 fixture from
    any team.  A GW absent here is treated as 'no data', not a blank."""
    gw_end = current_gw + horizon
    active: set[int] = set()
    for raw_fixtures in team_fixtures.values():
        for f in raw_fixtures:
            gw = int(f.get("gameweek", 0))
            if current_gw <= gw < gw_end:
                active.add(gw)
    return frozenset(active)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: The two difficulty axes.
AXES: tuple[str, str] = ("attack", "defence")

#: Default GW lookahead window for the outlook (long enough for real runs).
DEFAULT_HORIZON: int = 10

#: Maximum allowed horizon.
_MAX_HORIZON: int = 15

#: A run must be at least this many GWs long to be highlighted.
_MIN_RUN_LEN: int = 3

#: A run of this length or longer is graded "strong" (else "mild").
_STRONG_RUN_LEN: int = 5

#: Number of difficulty bands (1 = easiest … 5 = hardest). Parity with FDR.
_N_BANDS: int = 5

#: Per-axis opponent-strength fields, keyed by (axis, opponent_is_home).
#  For *our team*, attack difficulty is driven by the opponent's DEFENCE
#  strength; defence difficulty by the opponent's ATTACK strength. We read the
#  field for the venue the *opponent* is playing at.
_STRENGTH_FIELDS: dict[tuple[str, bool], str] = {
    ("attack",  True):  "strength_defence_home",
    ("attack",  False): "strength_defence_away",
    ("defence", True):  "strength_attack_home",
    ("defence", False): "strength_attack_away",
}


# ---------------------------------------------------------------------------
# Strength helpers (FI0)
# ---------------------------------------------------------------------------

def _teams_by_id(bootstrap: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(t["id"]): t for t in bootstrap.get("teams", []) if "id" in t}


def _strength_value(team: dict[str, Any] | None, field: str) -> int | None:
    """Return a positive integer strength value, or ``None`` when unusable."""
    if not team:
        return None
    raw = team.get(field)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _quintile_thresholds(values: list[int]) -> list[float] | None:
    """Return the 4 quintile cut points (20/40/60/80th pct) for *values*.

    Returns ``None`` when there is not enough data to form thresholds.
    Uses linear interpolation between ranks so ties degrade gracefully.
    """
    pool = sorted(v for v in values if v is not None)
    n = len(pool)
    if n < _N_BANDS:  # need at least one value per band for a meaningful split
        return None

    def _pct(p: float) -> float:
        idx = p * (n - 1)
        lo = math.floor(idx)
        hi = math.ceil(idx)
        if lo == hi:
            return float(pool[lo])
        frac = idx - lo
        return pool[lo] * (1.0 - frac) + pool[hi] * frac

    return [_pct(0.2), _pct(0.4), _pct(0.6), _pct(0.8)]


def _bucket(value: float, thresholds: list[float]) -> int:
    """Map a strength *value* to a 1–5 band (1 = easiest, 5 = hardest).

    Low opponent strength → weak opponent → easy → band 1.
    """
    for band, cut in enumerate(thresholds, start=1):
        if value <= cut:
            return band
    return _N_BANDS


def build_axis_thresholds(
    bootstrap: dict[str, Any],
    axis: str,
) -> list[float] | None:
    """Build league-wide quintile thresholds for *axis*.

    The pool is every team's relevant strength at *both* venues, so the bands
    are calibrated across the whole league rather than a single fixture.
    """
    # attack difficulty reads opponent DEFENCE; defence reads opponent ATTACK.
    home_field = _STRENGTH_FIELDS[(axis, True)]
    away_field = _STRENGTH_FIELDS[(axis, False)]
    pool: list[int] = []
    for team in bootstrap.get("teams", []):
        for field in (home_field, away_field):
            v = _strength_value(team, field)
            if v is not None:
                pool.append(v)
    return _quintile_thresholds(pool)


def _fixture_band(
    fixture: dict[str, Any],
    axis: str,
    teams_by_id: dict[int, dict[str, Any]],
    thresholds: list[float] | None,
) -> int:
    """Difficulty band (1–5) for one fixture on *axis*, with graceful fallback.

    Order of preference (FDR-first since the ML0 evaluation harness showed
    FPL's own FDR out-predicts our opponent-strength quintile banding on both
    axes — attack +0.281 vs +0.087, defence +0.307 vs +0.145 vs season xG):
    1. The fixture's official FDR (``difficulty``) — already a 1–5 value.
    2. Opponent venue-aware strength bucketed against league thresholds
       (fallback only when the fixture carries no usable FDR).
    3. Band 3 (neutral).

    FDR is axis-agnostic, so attack and defence bands are numerically equal
    when FDR is present; ``axis`` still drives the verdict wording and (via
    FI3a) the per-player axis choice. The defence-form overlay that would
    re-separate the axes is a later step, gated on a runtime rolling-form
    pipeline (see project_track_d_backtest_findings memory).
    """
    try:
        fdr = int(fixture.get("difficulty"))
        if 1 <= fdr <= _N_BANDS:
            return fdr
    except (TypeError, ValueError):
        pass

    # Fallback: opponent venue-aware strength (opponent plays the opposite
    # venue to us), then neutral.
    opponent_id = int(fixture.get("opponent_team", 0) or 0)
    is_home = bool(fixture.get("is_home", False))
    opponent = teams_by_id.get(opponent_id)
    if thresholds is not None and opponent is not None:
        field = _STRENGTH_FIELDS[(axis, not is_home)]
        val = _strength_value(opponent, field)
        if val is not None:
            return _bucket(float(val), thresholds)

    return 3


# ---------------------------------------------------------------------------
# Per-GW series + classification (FI1 input)
# ---------------------------------------------------------------------------

def _classify(band: int | None) -> str:
    """good (≤2) / bad (≥4) / neutral (3) / blank (None)."""
    if band is None:
        return "blank"
    if band <= 2:
        return "good"
    if band >= 4:
        return "bad"
    return "neutral"


def _team_axis_series(
    team_id: int,
    team_fixtures: dict,
    axis: str,
    current_gw: int | None,
    horizon: int,
    teams_by_id: dict[int, dict[str, Any]],
    short_map: dict[int, str],
    thresholds: list[float] | None,
    active_gws: frozenset[int],
) -> list[dict[str, Any]]:
    """Build the ordered per-GW difficulty series for one team on *axis*.

    Each entry: ``gameweek``, ``band`` (1–5 or None for blank), ``klass``,
    ``is_dgw``, ``is_bgw``, ``fixtures`` (opponent_short, is_home, band).
    A DGW collapses to the rounded mean of its fixtures' bands; a blank GW
    (active but no fixture) yields ``band=None`` and breaks runs.
    """
    raw = team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []

    # Bucket this team's fixtures by GW.
    by_gw: dict[int, list[dict[str, Any]]] = {}
    for f in raw:
        gw = int(f.get("gameweek", 0))
        by_gw.setdefault(gw, []).append(f)

    if current_gw is None:
        # No current GW determinable — walk the earliest `horizon` GWs we have.
        gw_range = sorted(by_gw)[:horizon]
    else:
        gw_range = list(range(current_gw, current_gw + horizon))

    series: list[dict[str, Any]] = []
    for gw in gw_range:
        fixtures = by_gw.get(gw, [])
        if not fixtures:
            # Blank only counts (and renders) when the GW is otherwise active.
            if current_gw is not None and gw not in active_gws:
                continue
            series.append({
                "gameweek": gw,
                "band":     None,
                "klass":    "blank",
                "is_dgw":   False,
                "is_bgw":   True,
                "fixtures": [],
            })
            continue

        per_fixture = []
        bands: list[int] = []
        for f in fixtures:
            band = _fixture_band(f, axis, teams_by_id, thresholds)
            bands.append(band)
            per_fixture.append({
                "opponent_short": short_map.get(
                    int(f.get("opponent_team", 0) or 0),
                    f"T{f.get('opponent_team', '?')}",
                ),
                "is_home": bool(f.get("is_home", False)),
                "band":    band,
            })

        gw_band = int(round(sum(bands) / len(bands)))
        gw_band = max(1, min(gw_band, _N_BANDS))
        series.append({
            "gameweek": gw,
            "band":     gw_band,
            "klass":    _classify(gw_band),
            "is_dgw":   len(fixtures) >= 2,
            "is_bgw":   False,
            "fixtures": per_fixture,
        })

    return series


# ---------------------------------------------------------------------------
# Run / tendency detection (FI1)
# ---------------------------------------------------------------------------

def detect_runs(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find good/bad runs (≥ ``_MIN_RUN_LEN`` consecutive GWs) in *series*.

    Only ``good`` and ``bad`` stretches form runs; ``neutral`` and ``blank``
    entries break them.  Each run is graded ``strong`` (≥ 5) or ``mild``.
    """
    runs: list[dict[str, Any]] = []
    run_start: int | None = None
    run_klass: str | None = None

    def _flush(end_idx: int) -> None:
        if run_start is None or run_klass is None:
            return
        length = end_idx - run_start + 1
        if length >= _MIN_RUN_LEN:
            runs.append({
                "type":      run_klass,
                "start_gw":  series[run_start]["gameweek"],
                "end_gw":    series[end_idx]["gameweek"],
                "length":    length,
                "intensity": "strong" if length >= _STRONG_RUN_LEN else "mild",
            })

    for i, entry in enumerate(series):
        klass = entry["klass"]
        if klass in ("good", "bad"):
            if klass == run_klass:
                continue  # extend current run
            _flush(i - 1)  # close previous run (if any)
            run_start, run_klass = i, klass
        else:
            _flush(i - 1)
            run_start, run_klass = None, None

    _flush(len(series) - 1)
    return runs


# ---------------------------------------------------------------------------
# Verdict (FI1) — Spanish, schedule-only
# ---------------------------------------------------------------------------

def _gw(n: int) -> str:
    return f"J{n}"


def build_verdict(
    runs: list[dict[str, Any]],
    axis: str,
    series: list[dict[str, Any]],
) -> str:
    """One-line Spanish, schedule-only summary of the team's outlook.

    Highlights the *earliest* upcoming run (good or bad).  Never references
    transfers/buy/sell — only the shape of the schedule.
    """
    if not series:
        return "Sin fixtures en el horizonte."

    if not runs:
        return "Calendario sin rachas claras en el horizonte."

    # Earliest-starting run is the most actionable for the user.
    primary = min(runs, key=lambda r: r["start_gw"])
    span = f"{_gw(primary['start_gw'])}–{_gw(primary['end_gw'])}"
    n = primary["length"]
    strong = primary["intensity"] == "strong"

    if axis == "attack":
        if primary["type"] == "good":
            kind = "muy asequible" if strong else "asequible"
            return f"Buen tramo ofensivo: {n} jornadas de calendario {kind} ({span})."
        kind = "muy exigente" if strong else "exigente"
        return f"Tramo ofensivo {kind}: {n} jornadas duras ({span})."

    # defence axis
    if primary["type"] == "good":
        kind = "muy favorable" if strong else "favorable"
        return f"Buen tramo para portería a cero: calendario {kind} ({span})."
    kind = "muy complicado" if strong else "complicado"
    return f"Tramo {kind} para mantener la portería a cero ({span})."


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def _avg_band(series: list[dict[str, Any]]) -> float | None:
    bands = [e["band"] for e in series if e["band"] is not None]
    if not bands:
        return None
    return round(sum(bands) / len(bands), 2)


def get_team_outlook(
    bootstrap: dict[str, Any],
    team_id: int,
    axis: str,
    horizon: int = DEFAULT_HORIZON,
    *,
    _thresholds: list[float] | None = None,
    _current_gw: int | None = None,
    _active_gws: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Compute the fixture outlook for one team on one axis.

    The leading-underscore keyword args let the all-teams path share the
    expensive league-wide computations (thresholds, current GW, active GWs).
    Callers normally omit them.

    Returns
    -------
    ``team_id`` / ``team_short`` / ``team_name`` / ``axis`` / ``horizon``
    ``avg_band``  mean difficulty across played GWs (None if all blank)
    ``series``    per-GW list (gameweek, band, klass, is_dgw, is_bgw, fixtures)
    ``runs``      detected good/bad runs
    ``verdict``   one-line Spanish schedule-only summary
    """
    axis = axis if axis in AXES else "attack"
    horizon = max(1, min(int(horizon), _MAX_HORIZON))

    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    teams_by_id = _teams_by_id(bootstrap)
    short_map = _team_short_map(bootstrap)
    name_map = _team_name_map(bootstrap)

    current_gw = _current_gw if _current_gw is not None else _get_current_gameweek(bootstrap)
    thresholds = _thresholds if _thresholds is not None else build_axis_thresholds(bootstrap, axis)
    if _active_gws is not None:
        active_gws = _active_gws
    elif current_gw is not None:
        active_gws = _get_active_gws(team_fixtures, current_gw, horizon)
    else:
        active_gws = frozenset()

    series = _team_axis_series(
        team_id, team_fixtures, axis, current_gw, horizon,
        teams_by_id, short_map, thresholds, active_gws,
    )
    runs = detect_runs(series)

    return {
        "team_id":    team_id,
        "team_short": short_map.get(team_id, f"T{team_id}"),
        "team_name":  name_map.get(team_id, f"Team {team_id}"),
        "axis":       axis,
        "horizon":    horizon,
        "avg_band":   _avg_band(series),
        "series":     series,
        "runs":       runs,
        "verdict":    build_verdict(runs, axis, series),
    }


def get_all_team_outlooks(
    bootstrap: dict[str, Any],
    axis: str = "attack",
    horizon: int = DEFAULT_HORIZON,
) -> dict[str, Any]:
    """Outlook for every team on *axis* — the data behind the grid (FI4/FI7).

    Teams are ordered by ``avg_band`` ascending (easiest schedule first).
    Returns ``status='missing_context'`` when fixture data is absent.
    """
    axis = axis if axis in AXES else "attack"
    horizon = max(1, min(int(horizon), _MAX_HORIZON))

    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    if not team_fixtures:
        return {
            "status": "missing_context",
            "message": "No team fixture schedule available (team_fixtures not in bootstrap).",
        }

    current_gw = _get_current_gameweek(bootstrap)
    thresholds = build_axis_thresholds(bootstrap, axis)
    active_gws = (
        _get_active_gws(team_fixtures, current_gw, horizon)
        if current_gw is not None else frozenset()
    )

    outlooks: list[dict[str, Any]] = []
    for raw_key in team_fixtures:
        team_id = int(raw_key)
        outlook = get_team_outlook(
            bootstrap, team_id, axis, horizon,
            _thresholds=thresholds,
            _current_gw=current_gw,
            _active_gws=active_gws,
        )
        if not outlook["series"]:
            continue
        outlooks.append(outlook)

    if not outlooks:
        return {
            "status": "missing_context",
            "message": (
                f"No upcoming fixtures found in the horizon "
                f"(horizon={horizon} GWs from GW{current_gw})."
            ),
        }

    # Easiest schedule first; blank-only avg_band sorts last.
    outlooks.sort(key=lambda o: (o["avg_band"] is None, o["avg_band"] or 0, o["team_short"]))

    return {
        "status":           "ok",
        "axis":             axis,
        "horizon":          horizon,
        "current_gameweek": current_gw,
        "thresholds_available": thresholds is not None,
        "teams":            outlooks,
    }
