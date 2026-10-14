"""Multi-competition calendar per Premier League club, from a live-trial capture. Dev-only, no I/O.

The input is the frozen capture of ``live_capture.py`` (``live_trial_local`` provenance).
Nothing here publishes or serves it: the only caller is the dev-gated
``GET /fixtures/competitions`` endpoint, which refuses unless an explicit dev flag is set
(see ``fpl_grounded_assistant.competition_calendar``).

Decisions a reviewer should be able to find:

* **Rest days** are kickoff-to-kickoff gaps in days between a club's consecutive matches
  in ANY competition, the same definition as M3's ``previous_rest_days`` /
  ``next_rest_days`` anchors (``live_trial_checks._calendar``), taken over the whole
  calendar instead of per target fixture. Postponed/cancelled/abandoned fixtures are
  not matches and are skipped.
* **Whole rest days** (``rest_whole_days_before``) are ``floor(hours / 24)`` between the
  two kickoffs, not calendar dates: Tuesday 19:00 -> Saturday 15:30 is 92.5 h = 3 whole days
  (calendar dates would say 4). It is what the rotation notice compares against.
* **Gameweek of a non-PL match** is the first PL gameweek whose last kickoff is at or after it
  (``gameweek`` on every match; PL matches carry their own round). A Tuesday Champions League
  night therefore belongs to the gameweek that follows it. Known limit: a PL fixture
  rescheduled far from its round stretches that round's last kickoff. ``None`` after the last
  scheduled gameweek.
* **Off-Premier-League** means ``league_id != 8``. Only the 20 clubs of ``capture["teams"]``
  get a calendar; opponents are named by the provider's display name.
* **Rotation** is deliberately absent: M3 has no rest-days threshold (see PR description).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from .ingestion.live_trial import COMPETITIONS, _utc, fixture_status

PREMIER_LEAGUE_ID = 8
#: Short badge shown in the UI, per Sportmonks league id.
BADGES = {2: "UCL", 5: "UEL", 2286: "UECL", 1328: "UEFA-SC", 24: "FA", 27: "EFL"}
#: Sportmonks short codes that differ from FPL's (checked against the shipped bundle's 20 team codes).
SM_TO_FPL_CODE = {"CVC": "COV"}
_NOT_PLAYED = frozenset({"postponed", "cancelled", "abandoned"})


def _kickoff(fixture: Mapping[str, Any]) -> datetime:
    return datetime.strptime(_utc(fixture["starting_at"]), "%Y-%m-%dT%H:%M:%SZ")


def week_start(day: date) -> str:
    """ISO Monday of the week containing ``day`` (the free tier's bucket key)."""
    return (day - timedelta(days=day.weekday())).isoformat()


def build_calendar(capture: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """``{club code: [match, ...]}`` in kickoff order, every competition included.

    Each match: ``kickoff_utc``, ``week``, ``gameweek``, ``competition`` (badge or ``"PL"``), ``is_pl``,
    ``venue`` (``H``/``A``), ``opponent`` (display name), ``rest_days_before`` (None for the
    club's first match), ``rest_whole_days_before``, ``previous_competition`` and ``rest_days_after`` (None for the last).
    """
    clubs = {int(t["id"]): SM_TO_FPL_CODE.get(str(t["short_code"]), str(t["short_code"])) for t in capture["teams"]}
    gw_last: dict[int, datetime] = {}
    for fixture in capture["team_fixtures"]:
        name = (fixture.get("round") or {}).get("name", "")
        if int(fixture["league_id"]) == PREMIER_LEAGUE_ID and str(name).isdigit() and fixture_status(fixture) not in _NOT_PLAYED:
            gw = int(name)
            gw_last[gw] = max(gw_last.get(gw, datetime.min), _kickoff(fixture))
    gw_order = sorted(gw_last)

    def gameweek_of(fixture: Mapping[str, Any], kickoff: datetime) -> int | None:
        name = (fixture.get("round") or {}).get("name", "")
        if int(fixture["league_id"]) == PREMIER_LEAGUE_ID and str(name).isdigit():
            return int(name)
        return next((g for g in gw_order if gw_last[g] >= kickoff), None)

    per_club: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for fixture in capture["team_fixtures"]:
        league_id = int(fixture["league_id"])
        if league_id not in COMPETITIONS or fixture_status(fixture) in _NOT_PLAYED:
            continue
        kickoff = _kickoff(fixture)
        parts = {p["meta"]["location"]: p for p in fixture["participants"]}
        for side, other in (("home", "away"), ("away", "home")):
            club_id = int(parts[side]["id"])
            if club_id not in clubs or (club_id, int(fixture["id"])) in seen:
                continue
            seen.add((club_id, int(fixture["id"])))
            per_club[club_id].append({
                "kickoff_utc": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "week": week_start(kickoff.date()),
                "gameweek": gameweek_of(fixture, kickoff),
                "competition": "PL" if league_id == PREMIER_LEAGUE_ID else BADGES[league_id],
                "is_pl": league_id == PREMIER_LEAGUE_ID,
                "venue": "H" if side == "home" else "A",
                "opponent": str(parts[other]["name"]),
                "_kickoff": kickoff,
            })
    out: dict[str, list[dict[str, Any]]] = {}
    for club_id, code in clubs.items():
        matches = sorted(per_club.get(club_id, []), key=lambda m: m["_kickoff"])
        kickoffs = [m.pop("_kickoff") for m in matches]
        for i, match in enumerate(matches):
            match["rest_whole_days_before"] = None if i == 0 else int((kickoffs[i] - kickoffs[i - 1]).total_seconds() // 86400)
            match["previous_competition"] = None if i == 0 else matches[i - 1]["competition"]
            match["rest_days_before"] = None if i == 0 else round((kickoffs[i] - kickoffs[i - 1]).total_seconds() / 86400, 1)
            match["rest_days_after"] = None if i + 1 == len(matches) else round((kickoffs[i + 1] - kickoffs[i]).total_seconds() / 86400, 1)
        out[code] = matches
    return out
