"""
fpl_grounded_assistant.fixture_context
======================================
Track D — FI3a.  Shared bridge that turns the fixture-outlook engine into an
**additive context signal** for the decision engines (compare / captain /
transfer / differential / chip).

Design contract (FI3a)
----------------------
* **Additive only.** This produces context — a verdict phrase and an advisory
  ``tiebreaker_signal`` (-1 / 0 / +1).  It NEVER feeds scoring inputs and never
  changes a winner, a score, or a recommendation.  The tuned engines stay
  authoritative.  (Replacing scoring inputs is FI3b, gated on Track B.)
* **Position picks the axis automatically** — attackers read the *attack* axis
  (ease of scoring), defenders/goalkeepers read the *defence* axis (ease of a
  clean sheet).  No manual toggle.
* **Schedule-only language.**  Phrases describe the calendar ("calendario
  ofensivo favorable J34–38"), never buy/sell.

Import-light on purpose: depends only on the pure ``fixture_outlook`` engine.
Team-name resolution (the heavy path that pulls the tool registry) is lazy —
imported inside the function only when a caller passes ``team_query`` instead
of a ``team_id``.
"""
from __future__ import annotations

from typing import Any

from .fixture_outlook import AXES, DEFAULT_HORIZON, get_team_outlook


# ---------------------------------------------------------------------------
# Position → axis  (with dynamic defensive-midfielder detection)
# ---------------------------------------------------------------------------
#
# GKP/DEF care about clean sheets (defence axis); FWD about scoring (attack).
# MID is the interesting case: most are attack-leaning, but a defensive
# midfielder (e.g. Caicedo) earns through *defensive contributions* (the FPL DC
# points) plus the midfield clean-sheet point — so the defence axis is the
# relevant read for him. We decide this DYNAMICALLY from the league's midfield
# distribution of defensive_contribution_per_90, rather than a hardcoded list.

#: A MID at/above this percentile of midfield dc_per_90 leans defensive.
_DEF_MID_PERCENTILE: float = 0.70   # top ~30% of midfielders by DC

#: Minimum number of midfielders with DC data before we trust the threshold.
_MIN_MID_SAMPLE: int = 8

#: FPL element_type code for midfielders.
_MID_TYPE: int = 3


def _dc_per_90(element: dict[str, Any]) -> float:
    try:
        return float(element.get("defensive_contribution_per_90", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _mid_dc_distribution(bootstrap: dict[str, Any]) -> list[float]:
    """Sorted dc_per_90 values for midfielders who actually contribute (>0)."""
    vals = [
        _dc_per_90(e)
        for e in bootstrap.get("elements", [])
        if int(e.get("element_type", 0) or 0) == _MID_TYPE
    ]
    return sorted(v for v in vals if v > 0)


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    n = len(sorted_vals)
    if n == 0:
        return None
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _percentile_rank(sorted_vals: list[float], value: float) -> float | None:
    """The percentile (0–100) a value sits at within a sorted distribution."""
    n = len(sorted_vals)
    if n == 0:
        return None
    below = sum(1 for v in sorted_vals if v <= value)
    return round(100.0 * below / n, 1)


def classify_player_axis(
    position: str | None,
    *,
    dc_per_90: float | None = None,
    bootstrap: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return ``(axis, role_meta)`` for a player.

    GKP/DEF → ``defence``; FWD → ``attack``.  MID is dynamic: ``defence`` when
    the player's ``dc_per_90`` lands at/above the league's defensive-midfield
    threshold (``_DEF_MID_PERCENTILE``), otherwise ``attack``.  When the data
    needed to classify a MID is missing, falls back to ``attack``.

    ``role_meta`` carries the explainable bits: ``role_lean`` (attack |
    defensive), ``is_defensive_mid``, and — for MIDs with data — ``dc_per_90``,
    ``mid_dc_threshold`` and ``dc_percentile`` (rank among midfielders).
    """
    pos = str(position or "").upper()

    if pos in ("GKP", "DEF"):
        return "defence", {"role_lean": "defensive", "is_defensive_mid": False}
    if pos == "FWD":
        return "attack", {"role_lean": "attack", "is_defensive_mid": False}

    if pos == "MID" and dc_per_90 is not None and bootstrap is not None:
        dist = _mid_dc_distribution(bootstrap)
        if len(dist) >= _MIN_MID_SAMPLE:
            threshold = _percentile(dist, _DEF_MID_PERCENTILE)
            defensive = threshold is not None and float(dc_per_90) >= threshold
            return (
                "defence" if defensive else "attack",
                {
                    "role_lean":        "defensive" if defensive else "attack",
                    "is_defensive_mid": bool(defensive),
                    "dc_per_90":        round(float(dc_per_90), 3),
                    "mid_dc_threshold": round(threshold, 3) if threshold else None,
                    "dc_percentile":    _percentile_rank(dist, float(dc_per_90)),
                },
            )

    # MID without data, or unknown position → broadest signal.
    return "attack", {"role_lean": "attack", "is_defensive_mid": False}


def axis_for_position(position: str | None) -> str:
    """Position-only axis (no dynamic MID detection). Kept for simple callers.

    GKP/DEF → ``defence``; everything else → ``attack``.
    """
    return classify_player_axis(position)[0]


# ---------------------------------------------------------------------------
# Tiebreaker signal + compact phrase
# ---------------------------------------------------------------------------

def _earliest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The soonest-starting run — the most actionable for the user."""
    return min(runs, key=lambda r: r["start_gw"]) if runs else None


def _tiebreaker_signal(runs: list[dict[str, Any]]) -> int:
    """Advisory schedule signal from the earliest run: +1 good, -1 bad, 0 none.

    Used ONLY as a tiebreaker hint by callers — never as a scoring input.
    """
    run = _earliest_run(runs)
    if run is None:
        return 0
    return 1 if run["type"] == "good" else -1


def _gw(n: int) -> str:
    return f"J{n}"


def _phrase(axis: str, runs: list[dict[str, Any]], defensive_mid: bool = False) -> str:
    """A short Spanish, schedule-only clause for the earliest run.

    ``defensive_mid`` softens the defence-axis wording: a defensive midfielder's
    value is broader than clean sheets (it's mostly defensive-contribution
    points), so we say "calendario defensivo" rather than "portería a cero".
    """
    run = _earliest_run(runs)
    if run is None:
        return "calendario sin rachas marcadas"
    span = f"{_gw(run['start_gw'])}–{_gw(run['end_gw'])}"
    good = run["type"] == "good"
    if axis == "attack":
        return (
            f"calendario ofensivo favorable ({span})" if good
            else f"calendario ofensivo exigente ({span})"
        )
    if defensive_mid:
        return (
            f"calendario defensivo favorable ({span})" if good
            else f"calendario defensivo exigente ({span})"
        )
    return (
        f"buen calendario para portería a cero ({span})" if good
        else f"calendario difícil para portería a cero ({span})"
    )


# ---------------------------------------------------------------------------
# Public bridge
# ---------------------------------------------------------------------------

def build_fixture_context(
    bootstrap: dict[str, Any],
    *,
    team_id: int | None = None,
    team_query: str | None = None,
    position: str | None = None,
    dc_per_90: float | None = None,
    axis: str | None = None,
    horizon: int = DEFAULT_HORIZON,
) -> dict[str, Any] | None:
    """Return additive fixture context for one player's team, or ``None``.

    Resolution
    ----------
    * ``axis``     — explicit axis wins.  Otherwise derived from ``position``,
      with **dynamic defensive-midfielder detection**: pass ``dc_per_90`` (the
      player's defensive_contribution_per_90) and a MID at/above the league
      defensive-midfield threshold reads the *defence* axis instead of attack.
    * ``team_id``  — preferred.  If absent and ``team_query`` is given, the team
      is resolved by name/alias (lazy import).

    Returns ``None`` (caller simply omits context) when the team cannot be
    resolved or no fixture data is available — never raises, never blocks the
    host engine.

    Output dict
    -----------
    ``axis`` ``team_short`` ``avg_band`` ``verdict``
    ``has_good_run`` ``has_bad_run``
    ``tiebreaker_signal`` (-1 / 0 / +1, advisory only)
    ``phrase`` (short Spanish schedule-only clause)
    ``role_lean`` (attack | defensive) ``is_defensive_mid``
    ``dc_per_90`` ``dc_percentile`` ``mid_dc_threshold`` (MIDs with data only)
    """
    horizon = int(horizon)
    if axis in AXES:
        resolved_axis, role_meta = axis, {}
    else:
        resolved_axis, role_meta = classify_player_axis(
            position, dc_per_90=dc_per_90, bootstrap=bootstrap,
        )

    if not bootstrap.get("team_fixtures"):
        return None

    if team_id is None and team_query:
        # Lazy import — only the team_query path pulls the tool-registry chain.
        from .team_fixture_calendar import _resolve_team
        team = _resolve_team(team_query, bootstrap)
        if team is None:
            return None
        team_id = int(team["id"])

    if team_id is None:
        return None

    outlook = get_team_outlook(bootstrap, int(team_id), resolved_axis, horizon)
    # No usable signal when there are no real fixtures (unknown team, or a team
    # that blanks the whole window → avg_band is None). Caller omits context.
    if not outlook.get("series") or outlook.get("avg_band") is None:
        return None

    runs = outlook["runs"]
    context = {
        "axis":              resolved_axis,
        "team_short":        outlook["team_short"],
        "avg_band":          outlook["avg_band"],
        "verdict":           outlook["verdict"],
        "has_good_run":      any(r["type"] == "good" for r in runs),
        "has_bad_run":       any(r["type"] == "bad" for r in runs),
        "tiebreaker_signal": _tiebreaker_signal(runs),
        "phrase":            _phrase(
            resolved_axis, runs,
            defensive_mid=bool(role_meta.get("is_defensive_mid")),
        ),
    }
    context.update(role_meta)   # role_lean, is_defensive_mid, dc_* (additive)
    return context


def fixture_tiebreaker_line(
    entries: "list[tuple[str, dict[str, Any] | None]]",
    *,
    emit: bool,
) -> str | None:
    """Shared schedule-only tiebreaker line for close-call decisions.

    ``entries`` is a list of ``(player_name, fixture_context_or_None)``.  Emits
    a single Spanish line surfacing each player's fixture phrase ONLY when
    ``emit`` is True (the caller's "this is close" gate) and at least one entry
    has usable context.  Schedule-only — never references buy/sell; it lays out
    the calendars and lets the user decide.
    """
    if not emit:
        return None
    parts = [f"{name}: {fc['phrase']}" for name, fc in entries if fc]
    if not parts:
        return None
    return "Muy parejos; por calendario — " + "; ".join(parts) + "."
