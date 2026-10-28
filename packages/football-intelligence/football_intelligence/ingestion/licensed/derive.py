"""Licensed matchday store, step 1: provider records -> derived tables. Pure: no I/O, no clock, no network.

Input is what the fetch step (a later PR) reads through ``sportmonks-client``, as plain records:

* PL fixtures from ``fixtures/between`` with ``participants;lineups.detailedPosition;formations;state;metadata``;
* ``squads/teams/{id}`` rows (``player_id``, ``team_id``, ``jersey_number``);
* ``teams/{id}?include=sidelined`` rows;
* ``fixtures/between/{start}/{end}/{team_id}`` rows with ``participants;state`` for the cups.

Output is keyed by FPL ids only. The Sportmonks ids are used to join and then dropped: the only place they
survive is the crosswalk, which is built by its own step and passed in here. Decisions a reviewer should be
able to find:

* **Nothing is guessed.** A club is an FPL code by the ``public_calendar`` alias table or it is not a PL club;
  a fixture is an FPL fixture by its (home, away) pair, which is unique in a season; a player is an FPL
  element by the crosswalk. Whatever fails a join is dropped and counted in :class:`DeriveReport`, so a
  missing player is visible, not silently absent.
* **Predicted vs confirmed** is the provider's own flag (``metadata`` type 572); absent or malformed is
  ``None``, never inferred from the row count.
* **Side** is the validated grid rule (:func:`football_intelligence.grid.grid_side`); only starters have one.
* **Cups are best effort**: only FA Cup and Carabao are kept (UCL/UEL/UECL come from public sources), and
  every snapshot is ``partial`` (``complete_as_of=None``): the provider guarantees no completeness.
* **Sidelined** rows are de-duplicated by the provider's sideline id before the id is dropped.

The report holds counts only: it is what the job logs, and the repository's logs are public.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from football_intelligence.grid import grid_side
from football_intelligence.ingestion.live_trial import fixture_status
from football_intelligence.ingestion.licensed.player_stats import lineup_stats
from football_intelligence.public_calendar import CompetitionSnapshot, SourceMatch, convert_matches, pl_club_code

PREMIER_LEAGUE_ID = 8
#: Off-PL competitions this store keeps, by Sportmonks league id (badges as in ``public_calendar``).
CUP_LEAGUES = {24: "FA", 27: "EFL"}
LINEUP_CONFIRMED_TYPE_ID = 572
STARTER_TYPE_ID = 11
SOURCE = "sportmonks-starter"
_CALENDAR_STATUS = {"scheduled": "scheduled", "live": "scheduled", "completed": "played",
                    "postponed": "postponed", "cancelled": "postponed", "abandoned": "postponed"}


@dataclass(frozen=True)
class FplFixture:
    """One FPL fixture, from the free FPL feed: the target key of every lineup row."""

    fixture_id: int
    home: str  # FPL three-letter code
    away: str


@dataclass
class DeriveReport:
    """Counts only (it is logged, and the logs are public)."""

    fixtures_seen: int = 0
    fixtures_unmatched: int = 0
    #: Distinct provider clubs in sidelined/squad rows that are not one of the 20 (their rows are dropped).
    teams_unmatched: int = 0
    lineup_rows_seen: int = 0
    players_unmatched: int = 0
    sidelined_duplicates: int = 0
    cup_fixtures_kept: int = 0
    other_competitions_dropped: int = 0
    rows: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedTables:
    lineup_snapshots: tuple[dict[str, Any], ...]
    lineup_slots: tuple[dict[str, Any], ...]
    sidelined: tuple[dict[str, Any], ...]
    squad_membership: tuple[dict[str, Any], ...]
    cup_snapshots: tuple[CompetitionSnapshot, ...]
    report: DeriveReport
    player_match_stats: tuple[dict[str, Any], ...] = ()


def lineup_confirmed(fixture: Mapping[str, Any]) -> bool | None:
    """The provider's own confirmed flag, or None when the element is absent or malformed (never guessed)."""
    for item in fixture.get("metadata") or []:
        if item.get("type_id") == LINEUP_CONFIRMED_TYPE_ID:
            value = (item.get("values") or {}).get("confirmed")
            return value if isinstance(value, bool) else None
    return None


def _utc(provider_time: str) -> str:
    """``2026-10-24 14:00:00`` (provider, UTC) -> ``2026-10-24T14:00:00Z``."""
    return datetime.strptime(provider_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%SZ")


def _sides(fixture: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {(p.get("meta") or {}).get("location"): p for p in fixture.get("participants") or []}


def _row_widths(starters: Iterable[Mapping[str, Any]]) -> dict[tuple[int, int], int]:
    """(team id, grid row) -> the highest column used in that row by the team's starters."""
    widths: dict[tuple[int, int], int] = defaultdict(int)
    for row in starters:
        slot = row.get("formation_field")
        if isinstance(slot, str) and ":" in slot:
            r, c = slot.split(":", 1)
            if r.isdigit() and c.isdigit():
                key = (int(row["team_id"]), int(r))
                widths[key] = max(widths[key], int(c))
    return widths


def derive(
    *,
    observed_at: str,
    season: str,
    pl_fixtures: Iterable[Mapping[str, Any]],
    squads: Iterable[Mapping[str, Any]],
    sidelined: Iterable[Mapping[str, Any]],
    team_fixtures: Iterable[Mapping[str, Any]],
    fpl_fixtures: Iterable[FplFixture],
    team_codes: Mapping[int, str],
    crosswalk: Mapping[int, int],
    stat_type_names: Mapping[int, str] | None = None,
) -> DerivedTables:
    """Derived tables for one ingestion pass. ``team_codes`` maps Sportmonks club ids to FPL codes (see
    :func:`team_codes_from`); ``crosswalk`` maps Sportmonks player ids to FPL element ids.
    ``stat_type_names`` (provider type id -> developer name, read from the provider) turns on the per-player match
    statistics of COMPLETED fixtures; without it no statistics row is derived."""
    datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%SZ")  # a malformed stamp fails loudly
    report = DeriveReport()
    by_pair = {(f.home, f.away): f.fixture_id for f in fpl_fixtures}
    unmatched_players: set[int] = set()
    unmatched_teams: set[int] = set()

    def element(player_id: Any) -> int | None:
        found = crosswalk.get(int(player_id)) if player_id is not None else None
        if found is None and player_id is not None:
            unmatched_players.add(int(player_id))
        return found

    snapshots: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    match_stats: list[dict[str, Any]] = []
    for fixture in pl_fixtures:
        report.fixtures_seen += 1
        sides = _sides(fixture)
        home, away = sides.get("home"), sides.get("away")
        codes = {loc: pl_club_code(str(p.get("name") or "")) for loc, p in (("home", home), ("away", away)) if p}
        fpl_id = by_pair.get((codes.get("home"), codes.get("away")))
        if fpl_id is None:
            report.fixtures_unmatched += 1
            continue
        home_id = int(home["id"])
        team_code = {home_id: codes["home"], int(away["id"]): codes["away"]}
        lineups = fixture.get("lineups") or []
        report.lineup_rows_seen += len(lineups)
        starters = [r for r in lineups if r.get("type_id") == STARTER_TYPE_ID]
        widths = _row_widths(starters)
        formation = {int(f["participant_id"]): f.get("formation") for f in fixture.get("formations") or []}
        confirmed = lineup_confirmed(fixture)
        state = fixture_status(fixture)
        for team_id, code in team_code.items():
            team_rows = [r for r in lineups if int(r["team_id"]) == team_id]
            if not team_rows:
                continue
            snapshots.append({
                "fixture_id": fpl_id, "team": code, "observed_at": observed_at, "state": state,
                "confirmed": confirmed, "formation": formation.get(team_id),
                "n_starters": sum(1 for r in team_rows if r.get("type_id") == STARTER_TYPE_ID),
                "n_bench": sum(1 for r in team_rows if r.get("type_id") != STARTER_TYPE_ID),
            })
            for r in team_rows:
                el = element(r.get("player_id"))
                if el is None:
                    continue
                starter = r.get("type_id") == STARTER_TYPE_ID
                slot = r.get("formation_field") if starter else None
                row_no = int(slot.split(":", 1)[0]) if isinstance(slot, str) and slot.split(":", 1)[0].isdigit() else None
                width = widths.get((team_id, row_no), 0) if row_no is not None else 0
                slots.append({
                    "fixture_id": fpl_id, "team": code, "observed_at": observed_at, "element": el,
                    "starter": starter,
                    "detailed_position": (r.get("detailedposition") or {}).get("name") if starter else None,
                    "grid_slot": slot, "side": grid_side(slot, width, team_id == home_id) if starter else None,
                })
                measures = lineup_stats(r, stat_type_names) if stat_type_names and state == "completed" else None
                if measures is not None:
                    match_stats.append({"element": el, "fixture_id": fpl_id, "team": code, "observed_at": observed_at,
                                        **measures})

    seen_sidelines: set[int] = set()
    absences: list[dict[str, Any]] = []
    for row in sidelined:
        sideline_id = int(row["id"])
        if sideline_id in seen_sidelines:
            report.sidelined_duplicates += 1
            continue
        seen_sidelines.add(sideline_id)
        code = team_codes.get(int(row["team_id"]))
        if code is None:  # club first: a player of an unmapped club is not an unmatched player
            unmatched_teams.add(int(row["team_id"]))
            continue
        el = element(row.get("player_id"))
        if el is None:
            continue
        absences.append({
            "element": el, "team": code, "category": row.get("category"), "start_date": row.get("start_date"),
            "end_date": row.get("end_date"), "games_missed": row.get("games_missed"),
            "completed": row.get("completed"), "observed_at": observed_at,
        })

    members: list[dict[str, Any]] = []
    for row in squads:
        code = team_codes.get(int(row["team_id"]))
        if code is None:  # club first: a player of an unmapped club is not an unmatched player
            unmatched_teams.add(int(row["team_id"]))
            continue
        el = element(row.get("player_id"))
        if el is None:
            continue
        members.append({"team": code, "element": el, "jersey_number": row.get("jersey_number"),
                        "observed_at": observed_at})

    cup_matches: dict[str, dict[int, SourceMatch]] = {badge: {} for badge in CUP_LEAGUES.values()}
    for fixture in team_fixtures:
        league = int(fixture["league_id"])
        if league == PREMIER_LEAGUE_ID:
            continue
        badge = CUP_LEAGUES.get(league)
        if badge is None:
            report.other_competitions_dropped += 1
            continue
        sides = _sides(fixture)
        if not {"home", "away"} <= set(sides):
            continue
        # Each club's call returns the same tie: one match per provider fixture id.
        cup_matches[badge][int(fixture["id"])] = SourceMatch(
            competition=badge, home_name=str(sides["home"].get("name") or ""),
            away_name=str(sides["away"].get("name") or ""), kickoff_utc=_utc(fixture["starting_at"]),
            status=_CALENDAR_STATUS.get(fixture_status(fixture), "scheduled"),  # type: ignore[arg-type]
            home_code=sides["home"].get("short_code"), away_code=sides["away"].get("short_code"),
        )
    cups = tuple(convert_matches(matches.values(), competition=badge, season=season, source=SOURCE,
                                 fetched_at=observed_at, complete_as_of=None)
                 for badge, matches in sorted(cup_matches.items()))
    report.cup_fixtures_kept = sum(len(m) for m in cup_matches.values())

    report.players_unmatched = len(unmatched_players)
    report.teams_unmatched = len(unmatched_teams)
    tables = DerivedTables(tuple(snapshots), tuple(slots), tuple(absences), tuple(members), cups, report,
                           tuple(match_stats))
    report.rows = {"lineup_snapshots": len(tables.lineup_snapshots), "lineup_slots": len(tables.lineup_slots),
                   "sidelined": len(tables.sidelined), "squad_membership": len(tables.squad_membership),
                   "cup_records": sum(len(c.records) for c in cups), "player_match_stats": len(match_stats)}
    return tables


def team_codes_from(teams: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """Sportmonks club id -> FPL code, by the ``public_calendar`` alias table on the club's name (never guessed).
    A name that is not one of the 20 is left out, and :func:`derive` counts the rows it then drops."""
    out: dict[int, str] = {}
    for team in teams:
        code = pl_club_code(str(team.get("name") or ""))
        if code is not None:
            out[int(team["id"])] = code
    codes = Counter(out.values())
    if any(n > 1 for n in codes.values()):
        raise ValueError("two provider clubs map to one FPL code")
    return out
