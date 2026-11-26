"""Runs a ``QuerySpec`` over the bootstrap and checked per-gameweek data. Pure: no fetching, no text.

    needed_gameweeks(spec, bootstrap)  -> the gameweeks to load
    run_query(spec, bootstrap, batch)  -> QueryResult

*batch* is what ``gw_live_cache`` serves: ``gameweeks`` ({gw: data with ``status``, ``revision``,
``fixtures``, ``rows``, ``fixture_minutes``}), ``unavailable`` ({gw: reason}) and ``bad_metrics``.

A result is ``complete`` only when every gameweek it reads is loaded and no metric it uses failed the
batch's sum check; otherwise it has no rows. The sum check (gameweek sums = season totals) cannot run while
a match waits for final data: ``sum_check`` is then ``not_checked`` and whatever shows the answer must say so.

How matches and rows are counted:

* The **window** counts gameweeks. ``season`` and ``last_n`` end at the last finished one; a gameweek asked
  for by number may be in progress (the result is then ``provisional``).
* A **team match** is one club in one fixture. A match set selects team matches.
* A player's gameweek row belongs to the fixtures he has minutes in, else to his current club's fixtures.
  It counts when all of them are in the set. A double gameweek the set cuts in half cannot be split: the
  answer is then ``data_unavailable``, never a guess.
* **Club means current club.** Matches before a player joined it are not that club's matches of his.
* **Team xG** of a match is the most common ``expected_goals_conceded`` among the opponents who played 90
  minutes. The sum of the club's own shooters is a cross-check: where the two differ by more than
  ``SHOOTER_TOLERANCE`` the result carries a range. Opponents' values tied for most common are a range
  too: none is picked. Nothing is ever averaged. **Where a range is set, the range is the answer**;
  ``value`` then only orders the rows (the mode, or the low end of a tie).

Nothing imports this module at runtime yet (query layer, PR 3).
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from football_intelligence.position_changes import ABSENCE_MIN_EACH_SIDE, SMALL_SAMPLE_BELOW
from fpl_player_registry import (POSITION_BY_ELEMENT_TYPE, RANK_AUTO_RESOLVE_MAX, candidate_dicts,
                                 resolve_player_candidates)

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_spec import (PLAYER_PREDICATES, WINDOW_PREDICATES, Predicate, QuerySpec,
                                               parse_date, unsupported_reasons)
from fpl_grounded_assistant.team_fixture_calendar import _resolve_team_result

COMPLETE = "complete"
NEEDS_CLARIFICATION = "needs_clarification"
UNSUPPORTED = "unsupported_constraint"
DATA_UNAVAILABLE = "data_unavailable"

#: A tie at the cutoff is shown whole, up to this many rows (or ``top_n`` when that is larger).
TIE_ROWS_MAX = 15
#: Opponents' mode and shooters' sum further apart than this, in one match, are shown as a range.
SHOOTER_TOLERANCE = 0.1
#: A player has "played" a match for the with-set from this many minutes; 1 to one less is mixed.
PLAYED_MINUTES = 60

_SET_PIECE_FIELDS = {"penalties": "penalties_order", "direct_freekicks": "direct_freekicks_order",
                     "corners": "corners_and_indirect_freekicks_order"}
#: Team metrics read from the final score; the two xG ones come from player rows.
_SCORE_METRICS = {"team_goals": lambda m: m.goals_for, "team_goals_conceded": lambda m: m.goals_against,
                  "team_clean_sheets": lambda m: int(m.goals_against == 0)}


# ----------------------------------------------------------------------------------------------------- results

@dataclass(frozen=True)
class Row:
    id: int                                   # element id, or team id at team grain
    name: str
    club: str                                 # current club short code
    value: float
    position: str = ""
    parts: tuple[float, ...] = ()             # (first, second) for minus / plus
    value_range: tuple[float, float] | None = None
    matches: int = 0                          # appearances, or the club's matches
    minutes: int | None = None                # in the window (the season for today's-value metrics)
    price: float | None = None
    owned: float | None = None


@dataclass(frozen=True)
class Side:
    """One set of matches of a comparison."""

    matches: tuple[tuple[int, int], ...]      # (gameweek, fixture id), in kickoff order
    gameweeks: tuple[int, ...]
    n: int
    home: int
    away: int
    mean_fdr: float | None                    # today's difficulty values, not the day's
    total: float
    per_match: float
    value: float                              # what the spec's operator asks for
    per_match_values: tuple[float, ...]
    per_match_bounds: tuple[tuple[float, float], ...] = ()    # (low, high) per match; equal when certain
    total_range: tuple[float, float] | None = None


@dataclass(frozen=True)
class Comparison:
    team_id: int
    club: str
    sides: tuple[Side, Side]                  # (match_set, compare_to)
    mixed: tuple[tuple[int, int], ...]        # (gameweek, minutes): 1..59', in neither set
    before_join: tuple[int, ...]              # gameweeks left out: played before the player joined the club
    small_sample: bool
    ranges_overlap: bool


@dataclass(frozen=True)
class QueryResult:
    state: str
    spec: QuerySpec
    reason: str | None = None                             # enum; set on every non-complete state
    unsupported: tuple[str, ...] = ()
    clarify: Mapping[str, Any] | None = None              # {kind, written, candidates}
    missing_gameweeks: tuple[int, ...] = ()
    bad_metrics: tuple[str, ...] = ()
    gameweeks: tuple[int, ...] = ()                       # executed window of match_set
    compare_gameweeks: tuple[int, ...] = ()
    provisional: bool = False
    min_minutes: int = 0                                  # the floor actually applied
    players: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)   # as written -> resolved
    clubs: Mapping[str, str] = field(default_factory=dict)                   # as written -> short code
    rows: tuple[Row, ...] = ()
    tied_omitted: int = 0                                 # rows tied with the last one shown, left out
    comparison: Comparison | None = None
    cross_check: str = "not_applicable"                   # team xG: agree | range | unavailable
    revisions: Mapping[int, str] = field(default_factory=dict)
    sum_check: str = "not_applicable"                     # complete only: passed | not_checked | not_applicable


class _Stop(Exception):
    def __init__(self, state: str, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.state, self.reason, self.extra = state, reason, extra


@dataclass(frozen=True)
class _Match:
    team: int
    opponent: int
    fixture: int
    gameweek: int
    home: bool
    kickoff: str
    goals_for: int
    goals_against: int
    fdr: float | None


# ------------------------------------------------------------------------------------------------ the windows

def finished_gameweeks(bootstrap: Mapping[str, Any]) -> tuple[int, ...]:
    return tuple(sorted(int(e["id"]) for e in bootstrap.get("events") or [] if e.get("finished")))


def _window_predicate(preds: Iterable[Predicate]) -> Predicate:
    return next((p for p in preds if p.pred in WINDOW_PREDICATES), Predicate("season", True))


def _since(pred: Predicate) -> str:
    year, _, _ = parse_date(pred.value)
    if year is None:
        raise ValueError("since_date has no year: assign it before running the query")
    return pred.value


def _window_gameweeks(preds: tuple[Predicate, ...], bootstrap: Mapping[str, Any]) -> tuple[int, ...]:
    """The gameweeks a set can touch. For ``since_date`` a superset: kickoff dates decide later."""
    window = _window_predicate(preds)
    finished = finished_gameweeks(bootstrap)
    if window.pred == "season":
        return finished
    if window.pred == "last_n":
        return finished[-window.value:]
    if window.pred == "gw":
        return (window.value,)
    if window.pred == "gw_range":
        return tuple(range(window.value[0], window.value[1] + 1))
    since = _since(window)
    deadlines = {int(e["id"]): str(e.get("deadline_time") or "")[:10] for e in bootstrap.get("events") or []}
    return tuple(gw for gw in finished if not deadlines.get(gw + 1) or deadlines[gw + 1] >= since)


def _sets(spec: QuerySpec) -> list[tuple[Predicate, ...]]:
    return [spec.match_set] + ([spec.compare_to] if spec.compare_to is not None else [])


def needed_gameweeks(spec: QuerySpec, bootstrap: Mapping[str, Any]) -> tuple[int, ...]:
    """The gameweeks :func:`run_query` reads; empty for today's-value metrics and unsupported specs."""
    if unsupported_reasons(spec) or cat.METRICS[spec.metric].group == "snapshot":
        return ()
    return tuple(sorted({gw for s in _sets(spec) for gw in _window_gameweeks(s, bootstrap)}))


# ------------------------------------------------------------------------------------------------- the engine

class _Run:
    def __init__(self, spec: QuerySpec, bootstrap: Mapping[str, Any], batch: Any) -> None:
        self.spec = spec
        self.bootstrap = bootstrap
        self.batch = batch
        self.elements = {int(e["id"]): e for e in bootstrap.get("elements") or []}
        self.teams = {int(t["id"]): t for t in bootstrap.get("teams") or []}
        self.players: dict[str, dict[str, Any]] = {}
        self.clubs: dict[str, str] = {}
        self.matches: list[_Match] = []
        self.cross_check = "not_applicable"

    # -- names ----------------------------------------------------------------

    def code(self, team_id: int) -> str:
        return str(self.teams.get(team_id, {}).get("short_name") or "")

    def club_id(self, written: str) -> int:
        outcome = _resolve_team_result(written, self.bootstrap)
        if outcome["status"] != "ok":
            raise _Stop(NEEDS_CLARIFICATION, f"club_{outcome['status']}", clarify={
                "kind": "club", "written": written, "candidates": tuple(outcome.get("candidates") or ())})
        team_id = int(outcome["team_data"]["id"])
        self.clubs[written] = self.code(team_id)
        return team_id

    def player_id(self, written: str, club_ids: set[int]) -> int:
        elements = list(self.elements.values())
        teams = self.bootstrap.get("teams") or []
        found = resolve_player_candidates(written, elements, teams, allow_substring=False)
        if found.status == "ambiguous" and len(club_ids) == 1:          # the club in the same spec settles it
            narrowed = resolve_player_candidates(written, elements, teams, allow_substring=False,
                                                 team_hint=self.code(next(iter(club_ids))))
            if narrowed.status == "ok":
                found = narrowed
        match = found.player
        if match is None or match.rank > RANK_AUTO_RESOLVE_MAX:
            raise _Stop(NEEDS_CLARIFICATION, f"player_{'not_found' if not found.matches else 'ambiguous'}",
                        clarify={"kind": "player", "written": written,
                                 "candidates": tuple(candidate_dicts(found.best_matches))})
        element = self.elements[match.record.id]
        self.players[written] = {"id": match.record.id, "name": element["web_name"],
                                 "team_id": int(element["team"]), "club": self.code(int(element["team"]))}
        return match.record.id

    def club_filters(self) -> list[tuple[str, set[int]]]:
        out = []
        for f in self.spec.filters:
            if f.field == "club":
                names = f.value if isinstance(f.value, tuple) else (f.value,)
                out.append((f.op, {self.club_id(n) for n in names}))
        return out

    # -- data -----------------------------------------------------------------

    def require(self, gameweeks: Iterable[int]) -> None:
        loaded = getattr(self.batch, "gameweeks", {})
        missing = tuple(sorted(gw for gw in set(gameweeks) if gw not in loaded))
        if missing:
            reasons = getattr(self.batch, "unavailable", {})
            raise _Stop(DATA_UNAVAILABLE, str(reasons.get(missing[0]) or "not_loaded"), missing_gameweeks=missing)

    def require_metrics(self, metrics: Iterable[str]) -> None:
        bad = tuple(sorted(set(metrics) & set(getattr(self.batch, "bad_metrics", ()))))
        if bad:
            raise _Stop(DATA_UNAVAILABLE, "invariant_failed", bad_metrics=bad)

    def load_matches(self, gameweeks: Iterable[int]) -> None:
        gameweeks = tuple(gameweeks)
        if not gameweeks:
            raise _Stop(DATA_UNAVAILABLE, "no_finished_gameweek")
        self.require(gameweeks)
        self.matches = []
        for gw in sorted(set(gameweeks)):
            for fx in self.batch.gameweeks[gw].fixtures:
                home_goals, away_goals = fx.get("team_h_score"), fx.get("team_a_score")
                if home_goals is None or away_goals is None:       # not played yet
                    continue
                for home in (True, False):
                    team, opponent = (fx["team_h"], fx["team_a"]) if home else (fx["team_a"], fx["team_h"])
                    fdr = fx.get("team_h_difficulty" if home else "team_a_difficulty")
                    self.matches.append(_Match(
                        int(team), int(opponent), int(fx["id"]), gw, home, str(fx.get("kickoff_time") or ""),
                        int(home_goals if home else away_goals), int(away_goals if home else home_goals),
                        None if fdr is None else float(fdr)))
        self.matches.sort(key=lambda m: (m.kickoff, m.fixture, m.team))

    def minutes_in(self, element_id: int, match: _Match) -> int:
        data = self.batch.gameweeks[match.gameweek]
        return int(data.fixture_minutes.get(element_id, {}).get(match.fixture, 0))

    def value_of(self, element_id: int, gameweek: int, metric: str) -> float:
        row = self.batch.gameweeks[gameweek].rows.get(element_id)
        return float(row[metric]) if row is not None else 0.0     # no row: he scored nothing that week

    def joined_by(self, element_id: int, match: _Match) -> bool:
        joined = self.elements[element_id].get("team_join_date")
        return not joined or match.kickoff[:10] >= str(joined)[:10]

    # -- match sets -----------------------------------------------------------

    def select(self, preds: tuple[Predicate, ...]) -> tuple[tuple[int, ...], list[_Match]]:
        """(the window's gameweeks, the team matches in the set)."""
        window = _window_predicate(preds)
        gameweeks = _window_gameweeks(preds, self.bootstrap)
        chosen = [m for m in self.matches if m.gameweek in set(gameweeks)]
        if window.pred == "since_date":
            chosen = [m for m in chosen if m.kickoff[:10] >= _since(window)]
            gameweeks = tuple(sorted({m.gameweek for m in chosen}))
        for p in preds:
            if p.pred == "venue":
                chosen = [m for m in chosen if m.home == (p.value == "home")]
            elif p.pred in PLAYER_PREDICATES:
                pid = self.players[p.value]["id"]
                club = self.players[p.value]["team_id"]
                chosen = [m for m in chosen if m.team == club and self.joined_by(pid, m)]
                if p.pred == "player_played_60":
                    chosen = [m for m in chosen if self.minutes_in(pid, m) >= PLAYED_MINUTES]
                else:
                    chosen = [m for m in chosen if self.minutes_in(pid, m) == 0]
        return gameweeks, chosen

    # -- team values ----------------------------------------------------------

    def team_xg(self, match: _Match) -> tuple[float, float, float]:
        """(sort key, low, high) of the xG of the club of *match*; low == high when the measures agree."""
        data = self.batch.gameweeks[match.gameweek]
        seen: list[float] = []
        shooters, splittable = 0.0, True
        for element_id, minutes in data.fixture_minutes.items():
            if match.fixture not in minutes or element_id not in self.elements:
                continue
            team = int(self.elements[element_id]["team"])
            if team not in (match.team, match.opponent) or not self.joined_by(element_id, match):
                continue
            only_this = len(minutes) == 1                   # else his row also holds another match
            if team == match.opponent:
                if only_this and minutes[match.fixture] == 90:
                    seen.append(round(self.value_of(element_id, match.gameweek, "expected_goals_conceded"), 2))
            elif only_this:
                shooters += self.value_of(element_id, match.gameweek, "expected_goals")
            else:
                splittable = False
        if not seen:
            raise _Stop(DATA_UNAVAILABLE, "team_xg_unmeasured", missing_gameweeks=(match.gameweek,))
        counts = Counter(seen)
        top = max(counts.values())
        modes = [v for v, n in counts.items() if n == top]
        key, low, high = min(modes), min(modes), max(modes)
        if not splittable or "expected_goals" in set(getattr(self.batch, "bad_metrics", ())):
            if self.cross_check != "range":
                self.cross_check = "unavailable"
        else:
            if self.cross_check == "not_applicable":
                self.cross_check = "agree"
            if shooters < low - SHOOTER_TOLERANCE - 1e-9 or shooters > high + SHOOTER_TOLERANCE + 1e-9:
                low, high = min(low, round(shooters, 2)), max(high, round(shooters, 2))
        if low != high:
            self.cross_check = "range"
        return key, low, high

    def team_metric(self, metric: str, match: _Match) -> tuple[float, float, float]:
        """(value, low, high) of one team metric in one match."""
        if metric in _SCORE_METRICS:
            value = float(_SCORE_METRICS[metric](match))
            return value, value, value
        if metric == "team_expected_goals_conceded":          # the opponent's team xG
            match = next(m for m in self.matches if m.fixture == match.fixture and m.team == match.opponent)
        return self.team_xg(match)

    def team_values(self, match: _Match) -> tuple[float, float, float, tuple[float, ...]]:
        """The spec's metric (with its second one) in one match: (value, low, high, parts)."""
        value, low, high = self.team_metric(self.spec.metric, match)
        second = self.spec.second_metric
        if second is None:
            return value, low, high, ()
        other, other_low, other_high = self.team_metric(second, match)
        if self.spec.operator == "minus":
            return value - other, low - other_high, high - other_low, (value, other)
        return value + other, low + other_low, high + other_high, (value, other)


def _rounded(value: float) -> float:
    return round(value, 6) + 0.0                              # + 0.0: no "-0.0"


def _passes(value: float, op: str, bound: Any) -> bool:
    value = _rounded(value)
    if op == "between":
        return bound[0] <= value <= bound[1]
    return {"eq": value == bound, "lt": value < bound, "le": value <= bound,
            "gt": value > bound, "ge": value >= bound}[op]


def _in_set(item: Any, op: str, wanted: Any) -> bool:
    values = wanted if isinstance(wanted, (tuple, set)) else (wanted,)
    return (item in values) != (op == "not")


def _cut(ranked: list[Row], top_n: int) -> tuple[tuple[Row, ...], int]:
    """The first *top_n*, plus the rows tied with the last of them, up to ``TIE_ROWS_MAX``."""
    if len(ranked) <= top_n:
        return tuple(ranked), 0
    last = ranked[top_n - 1].value
    end = top_n
    while end < len(ranked) and ranked[end].value == last:
        end += 1
    shown = min(end, max(top_n, TIE_ROWS_MAX))
    return tuple(ranked[:shown]), end - shown


def _ordered(rows: list[Row], order: str) -> list[Row]:
    sign = -1 if order == "desc" else 1
    return sorted(rows, key=lambda r: (sign * r.value, -(r.minutes or 0), r.name, r.id))


def _require_matches(chosen: list[_Match]) -> None:
    """A window with no match played in it has no values: a table of zeros would not be an answer."""
    if not chosen:
        raise _Stop(DATA_UNAVAILABLE, "no_matches")


# ------------------------------------------------------------------------------------------------ player rows

def _static_candidates(run: _Run) -> list[int]:
    """Players passing the filters that do not depend on the window."""
    spec = run.spec
    clubs = run.club_filters()
    named = [p for s in _sets(spec) for p in s if p.pred in PLAYER_PREDICATES]
    club_ids = {i for op, ids in clubs if op != "not" for i in ids}
    for p in named:
        run.player_id(p.value, club_ids)
    for p in named:                                       # a with / without set holds only that club's matches
        subject = run.players[p.value]["team_id"]
        if any(not _in_set(subject, op, ids) for op, ids in clubs):
            raise _Stop(UNSUPPORTED, "opponent", unsupported=("opponent",))

    out = []
    for element_id, element in run.elements.items():
        position = POSITION_BY_ELEMENT_TYPE.get(element.get("element_type"))
        if position is None:                              # not one of the four playing positions
            continue
        if named and int(element["team"]) != run.players[named[0].value]["team_id"]:
            continue
        keep = all(_in_set(int(element["team"]), op, ids) for op, ids in clubs)
        for f in spec.filters:
            if not keep:
                break
            if f.field == "position":
                keep = _in_set(position, f.op, f.value)
            elif f.field == "price":
                keep = _passes(element["now_cost"] / 10, f.op, f.value)
            elif f.field == "owned_now":
                keep = _passes(float(element["selected_by_percent"]), f.op, f.value)
            elif f.field == "set_piece":                  # "takes them" = first on the club's list
                wanted = f.value if isinstance(f.value, tuple) else (f.value,)
                takes = any(element.get(_SET_PIECE_FIELDS[w]) == 1 for w in wanted)
                keep = takes != (f.op == "not")
        if keep:
            out.append(element_id)
    return out


def _player_row(run: _Run, element_id: int, value: float, minutes: int, matches: int,
                parts: tuple[float, ...] = ()) -> Row:
    element = run.elements[element_id]
    return Row(id=element_id, name=str(element["web_name"]), club=run.code(int(element["team"])),
               position=POSITION_BY_ELEMENT_TYPE[element["element_type"]], value=_rounded(value),
               parts=tuple(_rounded(p) for p in parts), matches=matches, minutes=minutes,
               price=element["now_cost"] / 10, owned=float(element["selected_by_percent"]))


def _minute_filters_pass(spec: QuerySpec, minutes: int, floor: int) -> bool:
    return minutes >= floor and all(
        _passes(minutes, f.op, f.value) for f in spec.filters if f.field == "minutes_in_window")


def _snapshot_list(run: _Run) -> dict[str, Any]:
    spec = run.spec
    row = cat.METRICS[spec.metric]
    finished = finished_gameweeks(run.bootstrap)
    floor = cat.minutes_floor(spec.metric, spec.operator, spec.order, len(finished))
    ranked = []
    for element_id in _static_candidates(run):
        element = run.elements[element_id]
        raw = element.get(row.field)
        minutes = int(element.get("minutes") or 0)
        if raw is None or raw == "" or not _minute_filters_pass(spec, minutes, floor):
            continue
        value = float(raw)
        if row.unit == "order" and value <= 0:                 # not on the list
            continue
        if spec.metric == "now_cost":
            value /= 10
        ranked.append(_player_row(run, element_id, value, minutes, 0))
    rows, omitted = _cut(_ordered(ranked, spec.order), spec.top_n)
    return {"rows": rows, "tied_omitted": omitted, "min_minutes": floor, "gameweeks": finished}


def _player_list(run: _Run) -> dict[str, Any]:
    spec = run.spec
    candidates = _static_candidates(run)
    run.load_matches(needed_gameweeks(spec, run.bootstrap))
    metrics = [m for m in (spec.metric, spec.second_metric) if m is not None]
    has_player_set = any(p.pred in PLAYER_PREDICATES for p in spec.match_set)
    gameweeks, chosen = run.select(spec.match_set)
    _require_matches(chosen)
    selected = {(m.gameweek, m.fixture) for m in chosen}
    club_fixtures: dict[tuple[int, int], set[int]] = {}
    for m in run.matches:
        club_fixtures.setdefault((m.gameweek, m.team), set()).add(m.fixture)
    # Without a cut inside the gameweek, every row of the window counts, whichever club it was scored for.
    whole_gameweeks = not has_player_set and _window_predicate(spec.match_set).pred != "since_date"
    floor_basis = len({m.fixture for m in chosen}) if has_player_set else len(gameweeks)
    floor = cat.minutes_floor(spec.metric, spec.operator, spec.order, floor_basis)
    uses_minutes = (floor > 0 or spec.operator == "per_90" or has_player_set
                    or any(f.field == "minutes_in_window" for f in spec.filters))
    run.require_metrics(metrics + (["minutes"] if uses_minutes else []))

    window = set(gameweeks)
    ranked, cut_in_half = [], set()
    for element_id in candidates:
        team = int(run.elements[element_id]["team"])
        sums = [0.0] * len(metrics)
        minutes = appearances = 0
        for gw in window:
            data = run.batch.gameweeks[gw]
            played = data.fixture_minutes.get(element_id, {})
            appearances += sum(1 for f in played if (gw, f) in selected)
            mine = set(played) or club_fixtures.get((gw, team), set())
            inside = {f for f in mine if (gw, f) in selected}
            row = data.rows.get(element_id)
            if row is None:
                continue
            if whole_gameweeks or (inside and inside == mine):
                for i, metric in enumerate(metrics):
                    sums[i] += float(row[metric])
                minutes += int(row.get("minutes", 0))
            elif inside and any(row[m] for m in metrics + ["minutes"]):
                cut_in_half.add(gw)
        if not _minute_filters_pass(spec, minutes, floor):
            continue
        value = sums[0]
        if spec.operator == "per_match":
            if not appearances:
                continue
            value /= appearances
        elif spec.operator == "per_90":
            if not minutes:
                continue
            value = value * 90 / minutes
        elif spec.operator == "per_million":
            value /= run.elements[element_id]["now_cost"] / 10
        elif spec.operator == "minus":
            value -= sums[1]
        elif spec.operator == "plus":
            value += sums[1]
        ranked.append(_player_row(run, element_id, value, minutes, appearances,
                                  tuple(sums) if len(sums) == 2 else ()))
    if cut_in_half:
        raise _Stop(DATA_UNAVAILABLE, "double_gameweek_split", missing_gameweeks=tuple(sorted(cut_in_half)))
    rows, omitted = _cut(_ordered(ranked, spec.order), spec.top_n)
    return {"rows": rows, "tied_omitted": omitted, "min_minutes": floor, "gameweeks": gameweeks}


# -------------------------------------------------------------------------------------------------- team rows

def _team_metrics_needed(run: _Run) -> None:
    metrics = [run.spec.metric, run.spec.second_metric]
    needed = []
    if any(m in ("team_expected_goals", "team_expected_goals_conceded") for m in metrics):
        needed = ["expected_goals_conceded", "minutes"]
    if any(p.pred in PLAYER_PREDICATES for s in _sets(run.spec) for p in s):
        needed.append("minutes")
    run.require_metrics(needed)


def _team_subjects(run: _Run) -> tuple[list[tuple[str, set[int]]], int | None]:
    """The club filters, and the club of the named player when the spec has one."""
    clubs = run.club_filters()
    named = [p for s in _sets(run.spec) for p in s if p.pred in PLAYER_PREDICATES]
    club_ids = {i for op, ids in clubs if op != "not" for i in ids}
    subject = None
    for p in named:
        run.player_id(p.value, club_ids)
        subject = run.players[p.value]["team_id"]
    if subject is not None and any(not _in_set(subject, op, ids) for op, ids in clubs):
        written = named[0].value
        raise _Stop(NEEDS_CLARIFICATION, "player_not_at_club", clarify={
            "kind": "player_club", "written": written, "candidates": (dict(run.players[written]),)})
    return clubs, subject


def _team_list(run: _Run) -> dict[str, Any]:
    spec = run.spec
    clubs, subject = _team_subjects(run)
    run.load_matches(needed_gameweeks(spec, run.bootstrap))
    _team_metrics_needed(run)
    gameweeks, chosen = run.select(spec.match_set)
    _require_matches([m for m in chosen if subject is None or m.team == subject])
    ranked = []
    for team in run.teams:
        if (subject is not None and team != subject) or not all(_in_set(team, op, ids) for op, ids in clubs):
            continue
        matches = [m for m in chosen if m.team == team]
        if not matches:
            continue
        values = [run.team_values(m) for m in matches]
        per = len(matches) if spec.operator == "per_match" else 1
        value, low, high = (sum(v[i] for v in values) / per for i in range(3))
        parts = tuple(sum(v[3][i] for v in values) / per for i in range(len(values[0][3])))
        ranked.append(Row(id=team, name=str(run.teams[team]["name"]), club=run.code(team), value=_rounded(value),
                          parts=tuple(_rounded(p) for p in parts), matches=len(matches),
                          value_range=None if _rounded(low) == _rounded(high) else (_rounded(low), _rounded(high))))
    rows, omitted = _cut(_ordered(ranked, spec.order), spec.top_n)
    return {"rows": rows, "tied_omitted": omitted, "gameweeks": gameweeks}


def _side(run: _Run, matches: list[_Match], gameweeks: tuple[int, ...]) -> Side:
    values = [run.team_values(m) for m in matches]
    total = sum(v[0] for v in values)
    low, high = sum(v[1] for v in values), sum(v[2] for v in values)
    n = len(matches)
    fdr = [m.fdr for m in matches if m.fdr is not None]
    return Side(
        matches=tuple((m.gameweek, m.fixture) for m in matches),
        gameweeks=tuple(sorted({m.gameweek for m in matches})), n=n,
        home=sum(m.home for m in matches), away=sum(not m.home for m in matches),
        mean_fdr=round(sum(fdr) / len(fdr), 2) if fdr else None,
        total=_rounded(total), per_match=_rounded(total / n),
        value=_rounded(total / n if run.spec.operator == "per_match" else total),
        per_match_values=tuple(_rounded(v[0]) for v in values),
        per_match_bounds=tuple((_rounded(v[1]), _rounded(v[2])) for v in values),
        total_range=None if _rounded(low) == _rounded(high) else (_rounded(low), _rounded(high)))


def _comparison(run: _Run) -> dict[str, Any]:
    spec = run.spec
    clubs, subject = _team_subjects(run)
    team = subject if subject is not None else next(next(iter(ids)) for op, ids in clubs if op == "eq")
    run.load_matches(needed_gameweeks(spec, run.bootstrap))
    _team_metrics_needed(run)
    selected = []
    for preds in _sets(spec):
        gameweeks, chosen = run.select(preds)
        selected.append((gameweeks, [m for m in chosen if m.team == team]))

    named = [p for s in _sets(spec) for p in s if p.pred in PLAYER_PREDICATES]
    mixed, before_join = [], []
    if named:
        pid = run.players[named[0].value]["id"]
        windows = {gw for gameweeks, _ in selected for gw in gameweeks}
        for m in run.matches:
            if m.team != team or m.gameweek not in windows:
                continue
            if not run.joined_by(pid, m):
                before_join.append(m.gameweek)
            elif 0 < run.minutes_in(pid, m) < PLAYED_MINUTES:
                mixed.append((m.gameweek, run.minutes_in(pid, m)))

    sizes = [len(matches) for _, matches in selected]
    minimum = ABSENCE_MIN_EACH_SIDE if named else 1
    windows_out = {"gameweeks": selected[0][0], "compare_gameweeks": selected[1][0]}
    if min(sizes) < minimum:
        raise _Stop(DATA_UNAVAILABLE, "too_few_matches", **windows_out)
    first, second = (_side(run, matches, gameweeks) for gameweeks, matches in selected)
    a, b = ((min(lo for lo, _ in s.per_match_bounds), max(hi for _, hi in s.per_match_bounds))
            for s in (first, second))
    return {**windows_out, "comparison": Comparison(
        team_id=team, club=run.code(team), sides=(first, second), mixed=tuple(mixed),
        before_join=tuple(sorted(set(before_join))), small_sample=min(sizes) < SMALL_SAMPLE_BELOW,
        ranges_overlap=a[0] <= b[1] and b[0] <= a[1])}


# ------------------------------------------------------------------------------------------------------ entry

def _sum_check(spec: QuerySpec, batch: Any, used: tuple[int, ...]) -> str:
    """Whether the player rows behind a complete answer were checked against the season totals."""
    scores_only = (spec.grain == "team"
                   and all(m in _SCORE_METRICS for m in (spec.metric, spec.second_metric) if m)
                   and not any(p.pred in PLAYER_PREDICATES for s in _sets(spec) for p in s))
    if not used or scores_only:
        return "not_applicable"
    # "failed" with a complete answer: only metrics this answer does not use failed
    return "not_checked" if getattr(batch, "invariant", "not_checked") == "not_checked" else "passed"

def run_query(spec: QuerySpec, bootstrap: Mapping[str, Any], batch: Any = None) -> QueryResult:
    """Execute *spec*. Raises ValueError only for a ``since_date`` still without a year."""
    reasons = unsupported_reasons(spec)
    if reasons:
        return QueryResult(UNSUPPORTED, spec, reason=reasons[0], unsupported=reasons)
    run = _Run(spec, bootstrap, batch)
    snapshot = cat.METRICS[spec.metric].group == "snapshot"
    try:
        if snapshot:
            out = _snapshot_list(run)
        elif spec.shape == "comparison":
            out = _comparison(run)
        elif spec.grain == "team":
            out = _team_list(run)
        else:
            out = _player_list(run)
    except _Stop as stop:
        extra = dict(stop.extra)
        if not snapshot:                      # a refusal still says which window it was about
            extra.setdefault("gameweeks", _window_gameweeks(spec.match_set, bootstrap))
        return QueryResult(stop.state, spec, reason=stop.reason, players=run.players, clubs=run.clubs, **extra)
    used = () if snapshot else needed_gameweeks(spec, bootstrap)
    return QueryResult(
        COMPLETE, spec, players=run.players, clubs=run.clubs, cross_check=run.cross_check,
        sum_check=_sum_check(spec, batch, used),
        provisional=any(batch.gameweeks[gw].status != "final" for gw in used),
        revisions={gw: batch.gameweeks[gw].revision for gw in used}, **out)
