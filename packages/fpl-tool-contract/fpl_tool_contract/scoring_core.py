"""Cross-layer captain-scoring input primitives.

Single source of truth for the *base* scoring-input derivation shared across
package layers. It lives in ``fpl-tool-contract`` because that is the lowest
layer every consumer can import: ``tools.py`` here, and the grounded-assistant
consumers (``comparison``, ``transfer_advisor``, ``differential_picks``,
``chip_advisor``) which sit above it.

Scope is deliberately the *base* four values only — ``form``, ``xgi_per_90``
(raw), ``minutes_risk``, ``fixture_difficulty``. The home/away venue adjustment
(``is_home``/``effective_fdr``) and the minutes-shrunk rate
(``xgi_per_90_shrunk``) are grounded-assistant concerns — the latter depends on
``position_score.shrink_rate_by_minutes``, which is a higher layer — so they are
composed on top of this base in ``fpl_grounded_assistant.scoring_shared``.

This module imports only stdlib/typing, so nothing below it can cycle back.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping

# Minutes-risk table: maps FPL ``status`` codes to a 0–100 risk score.
#   a = available, d = doubtful, i = injured, s = suspended, u = unavailable.
_STATUS_RISK: dict[str, float] = {
    "a": 0.0,
    "d": 30.0,
    "i": 100.0,
    "s": 100.0,
    "u": 100.0,
}

#: Neutral fixture difficulty used when the team's FDR is unknown *or* the FPL
#: API ships it present-but-null (season launch: fixtures exist before their
#: difficulty ratings are populated).
NEUTRAL_FDR: int = 3
MAX_CAPTAIN_HORIZON: int = 8


def captain_pool_elements(bootstrap: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the deterministic global captain pool for *bootstrap*.

    The product's global captain comparison means available midfielders and
    forwards. Keeping that eligibility rule here prevents ranking and chip
    advice from drifting. Player id is the tie-breaker, so pool order does not
    depend on raw bootstrap element ordering.
    """
    eligible = [
        element
        for element in bootstrap.get("elements", [])
        if element.get("element_type") in (3, 4)
        and element.get("status") not in ("i", "s", "u")
        and element.get("id") is not None
    ]
    return sorted(eligible, key=lambda element: int(element["id"]))


def captain_time_context(
    bootstrap: Mapping[str, Any],
    gameweek: int | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    """Resolve and describe the captaincy evaluation window.

    ``gameweek=None`` always means the canonical current-or-next event and is
    labelled as such in ``notice``. ``horizon`` defaults to one gameweek.
    """
    try:
        resolved_horizon = 1 if horizon is None else int(horizon)
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon must be an integer") from exc
    if not 1 <= resolved_horizon <= MAX_CAPTAIN_HORIZON:
        raise ValueError(
            f"horizon must be between 1 and {MAX_CAPTAIN_HORIZON} gameweeks"
        )

    current: int | None = None
    for event in bootstrap.get("events", []):
        if event.get("is_current") and not event.get("finished"):
            current = int(event["id"])
            break
    if current is None:
        for event in bootstrap.get("events", []):
            if event.get("is_next") and not event.get("finished"):
                current = int(event["id"])
                break

    if gameweek is None:
        evaluated = current
        source = "current"
    else:
        try:
            evaluated = int(gameweek)
        except (TypeError, ValueError) as exc:
            raise ValueError("gameweek must be an integer") from exc
        if not 1 <= evaluated <= 38:
            raise ValueError("gameweek must be between 1 and 38")
        source = "caller"

    if evaluated is None:
        notice = "The current gameweek could not be determined from the available data."
        gw_to = None
    else:
        gw_to = min(38, evaluated + resolved_horizon - 1)
        if gw_to == evaluated:
            label = "current gameweek" if source == "current" else "requested gameweek"
            notice = f"Evaluated the {label} GW{evaluated}."
        else:
            label = "current window" if source == "current" else "requested window"
            notice = (
                f"Evaluated the {label} GW{evaluated}-GW{gw_to} "
                f"({gw_to - evaluated + 1} gameweeks)."
            )

    return {
        "current_gameweek": current,
        "evaluated_gameweek": evaluated,
        "gameweek_to": gw_to,
        "horizon": resolved_horizon,
        "source": source,
        "notice": notice,
    }


def fixture_difficulty_map_for_window(
    bootstrap: Mapping[str, Any],
    time_context: Mapping[str, Any],
) -> tuple[dict[int, int | None], str]:
    """Return average per-team FDR for the resolved window and its source."""
    start = time_context.get("evaluated_gameweek")
    end = time_context.get("gameweek_to")
    team_fixtures = bootstrap.get("team_fixtures")
    if start is None or end is None or not isinstance(team_fixtures, Mapping):
        return dict(bootstrap.get("fixture_difficulty_map", {})), "current_fallback"

    result: dict[int, int] = {}
    for raw_team_id, fixtures in team_fixtures.items():
        if not isinstance(fixtures, list):
            continue
        difficulties: list[int] = []
        for fixture in fixtures:
            try:
                fixture_gw = int(fixture.get("gameweek"))
                difficulty = int(fixture.get("difficulty"))
            except (TypeError, ValueError):
                continue
            if int(start) <= fixture_gw <= int(end):
                difficulties.append(difficulty)
        if difficulties:
            average = sum(difficulties) / len(difficulties)
            result[int(raw_team_id)] = max(1, min(5, int(average + 0.5)))
    return result, "team_fixtures"


def bootstrap_for_captain_window(
    bootstrap: Mapping[str, Any],
    time_context: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return a shallow bootstrap view whose fixture signals match the window."""
    fdr_map, fixture_source = fixture_difficulty_map_for_window(bootstrap, time_context)
    window_bootstrap = dict(bootstrap)
    window_bootstrap["fixture_difficulty_map"] = fdr_map

    evaluated = time_context.get("evaluated_gameweek")
    if evaluated is not None:
        events = [
            {
                **event,
                "is_current": int(event.get("id", -1)) == int(evaluated),
                "is_next": False,
            }
            for event in bootstrap.get("events", [])
        ]
        if not any(int(event.get("id", -1)) == int(evaluated) for event in events):
            events.append({"id": int(evaluated), "is_current": True, "is_next": False})
        window_bootstrap["events"] = events
    return window_bootstrap, fixture_source


def captain_window_needs_fixture_data(
    time_context: Mapping[str, Any],
    fixture_source: str,
) -> bool:
    """Whether a non-current window would otherwise reuse current-only FDR."""
    if fixture_source == "team_fixtures":
        return False
    evaluated = time_context.get("evaluated_gameweek")
    current = time_context.get("current_gameweek")
    horizon = int(time_context.get("horizon", 1))
    return evaluated is not None and (evaluated != current or horizon > 1)


def missing_captain_fixture_notice(time_context: Mapping[str, Any]) -> str:
    """Describe a requested window that cannot be evaluated safely."""
    start = time_context.get("evaluated_gameweek")
    end = time_context.get("gameweek_to")
    if start is None:
        return "Could not determine the requested gameweek."
    if end is None or end == start:
        return f"Could not evaluate the requested gameweek GW{start}."
    return f"Could not evaluate the requested window GW{start}-GW{end}."


def _availability_risk(element: Mapping[str, Any]) -> float:
    """Return the existing status/chance risk, independent of participation."""
    status = element.get("status", "u")
    chance = element.get("chance_of_playing_this_round")
    if chance is not None and status == "d":
        try:
            chance_value = float(chance)
        except (TypeError, ValueError):
            return _STATUS_RISK["d"]
        return max(0.0, min(100.0, 100.0 - chance_value))
    return _STATUS_RISK.get(str(status), 50.0)


def _display_number(value: float) -> int | float:
    """Keep whole-minute metadata readable without discarding real fractions."""
    return int(value) if value.is_integer() else round(value, 2)


def derive_minutes_context(
    element: Mapping[str, Any],
    team_fixtures: Mapping[Any, Any] | None,
) -> dict[str, Any]:
    """Derive auditable participation risk from official completed fixtures.

    The denominator is the sum of each finished fixture's actual ``minutes``
    for the player's current team, restricted to fixtures whose kickoff date
    is on or after ``team_join_date``.  This counts doubles individually,
    counts no fixture in a blank, follows postponed fixtures to their actual
    date, and does not charge a recent signing for matches before joining.

    A complete all-fixtures fetch is marked on every normalized fixture by the
    pipeline.  Without that marker, a valid join date, and trustworthy minute
    values, participation is not inferred: callers receive the pre-existing
    availability/status risk and an explicit degradation reason.
    """
    availability_risk = _availability_risk(element)
    try:
        minutes_played = float(element.get("minutes", 0) or 0)
        starts = int(element.get("starts", 0) or 0)
    except (TypeError, ValueError):
        minutes_played = math.nan
        starts = 0

    base: dict[str, Any] = {
        "minutes_played": (
            _display_number(minutes_played) if math.isfinite(minutes_played) else None
        ),
        "minutes_available": None,
        "starts": max(0, starts),
        "fixtures_available": None,
        "participation_percent": None,
        "participation_risk": None,
        "availability_risk": availability_risk,
        "minutes_risk": availability_risk,
        "source": "availability_status",
        "degraded": True,
        "degradation_reason": None,
    }

    if not math.isfinite(minutes_played) or minutes_played < 0:
        base["degradation_reason"] = "invalid_player_minutes"
        return base

    try:
        team_id = int(element["team"])
    except (KeyError, TypeError, ValueError):
        base["degradation_reason"] = "missing_team"
        return base

    if not isinstance(team_fixtures, Mapping):
        base["degradation_reason"] = "missing_official_fixtures"
        return base
    # A bootstrap that has been through JSON carries string team keys, so look
    # both up: silently missing the int key would degrade to status-only risk —
    # reinstating the very defect this derivation exists to remove.
    fixtures = team_fixtures.get(team_id)
    if fixtures is None:
        fixtures = team_fixtures.get(str(team_id))
    if not isinstance(fixtures, list) or not fixtures:
        base["degradation_reason"] = "missing_official_fixtures"
        return base
    if not all(
        isinstance(fixture, Mapping)
        and fixture.get("official_fixture_context_complete") is True
        for fixture in fixtures
    ):
        base["degradation_reason"] = "incomplete_official_fixtures"
        return base

    join_date_raw = element.get("team_join_date")
    try:
        join_date = dt.date.fromisoformat(str(join_date_raw)[:10])
    except (TypeError, ValueError):
        base["degradation_reason"] = "invalid_team_join_date"
        return base

    available = 0.0
    fixture_count = 0
    for fixture in fixtures:
        if fixture.get("finished") is not True:
            continue
        kickoff_raw = fixture.get("kickoff_time")
        try:
            kickoff_date = dt.datetime.fromisoformat(
                str(kickoff_raw).replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError):
            base["degradation_reason"] = "invalid_finished_fixture_kickoff"
            return base
        if kickoff_date < join_date:
            continue
        try:
            fixture_minutes = float(fixture.get("minutes"))
        except (TypeError, ValueError):
            base["degradation_reason"] = "invalid_finished_fixture_minutes"
            return base
        if not math.isfinite(fixture_minutes) or fixture_minutes <= 0:
            base["degradation_reason"] = "invalid_finished_fixture_minutes"
            return base
        available += fixture_minutes
        fixture_count += 1

    if available <= 0:
        base["fixtures_available"] = 0
        base["degradation_reason"] = "no_completed_fixtures_since_join"
        return base
    if minutes_played > available:
        base["minutes_available"] = _display_number(available)
        base["fixtures_available"] = fixture_count
        base["degradation_reason"] = "player_minutes_exceed_available"
        return base

    participation = max(0.0, min(100.0, minutes_played / available * 100.0))
    participation_risk = 100.0 - participation
    minutes_risk = max(participation_risk, availability_risk)
    return {
        **base,
        "minutes_available": _display_number(available),
        "fixtures_available": fixture_count,
        "participation_percent": round(participation, 1),
        "participation_risk": round(participation_risk, 1),
        "minutes_risk": round(minutes_risk, 1),
        "source": "official_completed_fixtures",
        "degraded": False,
        "degradation_reason": None,
    }


def _derive_base_scoring_inputs(
    element: dict[str, Any],
    fdr_map: Mapping[int, int | None],
    team_fixtures: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """Derive the base captain-scoring inputs from a raw FPL bootstrap element.

    Returns a dict with keys ``form`` (float), ``xgi_per_90`` (float, raw),
    ``minutes_risk`` (float), ``fixture_difficulty`` (int).

    ``fdr_map`` values may be ``None``: the FPL ``fixture_difficulty_map`` ships
    a present-but-null value per team at season launch, so a plain
    ``.get(team_id, default)`` does **not** fire the default — it returns
    ``None`` and ``int(None)`` raises. Both a missing key and a null value fall
    back to :data:`NEUTRAL_FDR`.
    """
    form = float(element.get("form", "0") or 0)

    minutes = float(element.get("minutes", 0) or 0)
    xgi_raw = float(element.get("expected_goal_involvements", "0") or 0)
    xgi_per_90 = (xgi_raw / (minutes / 90.0)) if minutes > 0 else 0.0

    minutes_risk = derive_minutes_context(element, team_fixtures)["minutes_risk"]

    team_id = element.get("team")
    _raw_fdr = fdr_map.get(team_id)
    fixture_difficulty = int(_raw_fdr) if _raw_fdr is not None else NEUTRAL_FDR

    return {
        "form":               form,
        "xgi_per_90":         round(xgi_per_90, 6),
        "minutes_risk":       minutes_risk,
        "fixture_difficulty": fixture_difficulty,
    }
