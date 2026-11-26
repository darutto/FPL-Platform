"""StrikerAPI ``list_games`` rows -> :class:`~.public_calendar.CompetitionSnapshot` (UCL / UEL / UECL).

Pure: no network, no clock, no file. The shared calendar logic lives in ``public_calendar``; this is only
the source-specific converter, its completeness rule and the JSON shape of the stored snapshot.

Fail closed. A competition's page set is rejected WHOLE (:class:`SourceRejected`, so the caller keeps the
previous snapshot of that competition) when any row has a status this module does not know, a missing or
malformed ``starts_at``, a missing ``game_id`` or team name, or a ``game_id`` that appears twice. Statuses:
``scheduled`` and ``final`` are the ones seen in real replies; ``postponed`` is ASSUMED (not seen). Anything
else, including an abandoned or cancelled match, is unknown on purpose.

Completeness (``complete_as_of``, an inclusive UTC date) is claimed only when ALL hold: the paging reached
its end; the League Phase has exactly its number of games (144 in UCL and UEL, 108 in UECL); and none of
them is postponed (a postponed match has no confirmed new date). The bound is the last League Phase date.
Knockout stage names have not been seen in a real reply, so no knockout stage ever extends the bound: after
the last matchday and before the draw (and until this table learns those names) a January match past the
bound is not covered.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from .public_calendar import CompetitionSnapshot, FixtureRecord, SourceMatch, Status, convert_matches

PROVENANCE = "strikerapi_calendar"
#: ``list_games`` league parameter -> calendar badge.
LEAGUES: dict[str, str] = {"ucl": "UCL", "uel": "UEL", "uecl": "UECL"}
LEAGUE_PHASE = "League Phase"
LEAGUE_PHASE_GAMES: dict[str, int] = {"UCL": 144, "UEL": 144, "UECL": 108}
_STATUS: dict[str, Status] = {"scheduled": "scheduled", "final": "played", "postponed": "postponed"}
SCHEMA_VERSION = 1


class SourceRejected(ValueError):
    """The competition's reply cannot be trusted; nothing of it may be used."""


def kickoff_utc(starts_at: Any) -> str:
    """``"2027-01-27T20:00:00.000Z"`` -> ``"2027-01-27T20:00:00Z"``. Only an explicit UTC time is accepted."""
    if not isinstance(starts_at, str) or not starts_at.strip():
        raise SourceRejected("a game has no starts_at")
    try:
        parsed = datetime.fromisoformat(starts_at.strip().replace("Z", "+00:00"))
    except ValueError:
        raise SourceRejected("a game has a malformed starts_at") from None
    if parsed.utcoffset() != timedelta(0):
        raise SourceRejected("a game's starts_at is not in UTC")
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _team(game: Mapping[str, Any], side: str) -> tuple[str, str | None]:
    team = game.get(side)
    name = team.get("name") if isinstance(team, Mapping) else None
    if not isinstance(name, str) or not name.strip():
        raise SourceRejected(f"a game has no {side} team name")
    abbrev = team.get("abbrev")  # type: ignore[union-attr]
    return name.strip(), abbrev if isinstance(abbrev, str) else None


def source_matches(games: Sequence[Mapping[str, Any]], competition: str) -> list[SourceMatch]:
    seen: set[str] = set()
    out: list[SourceMatch] = []
    for game in games:
        if not isinstance(game, Mapping):
            raise SourceRejected("a game is not an object")
        game_id = str(game.get("game_id") or "").strip()
        if not game_id:
            raise SourceRejected("a game has no game_id")
        if game_id in seen:
            raise SourceRejected("a game_id appears twice")
        seen.add(game_id)
        raw_status = game.get("status")
        status = _STATUS.get(raw_status) if isinstance(raw_status, str) else None
        if status is None:
            raise SourceRejected(f"unknown game status {str(raw_status)[:30]!r}")
        home, home_code = _team(game, "home")
        away, away_code = _team(game, "away")
        out.append(SourceMatch(
            competition=competition, home_name=home, away_name=away, kickoff_utc=kickoff_utc(game.get("starts_at")),
            status=status, home_code=home_code, away_code=away_code,
        ))
    return out


def complete_bound(games: Sequence[Mapping[str, Any]], competition: str, *, paged_to_end: bool) -> str | None:
    """The inclusive date the competition's list is whole up to, or None (see the module docstring)."""
    if not paged_to_end:
        return None
    phase = [g for g in games if g.get("stage") == LEAGUE_PHASE]
    if len(phase) != LEAGUE_PHASE_GAMES.get(competition) or any(g.get("status") == "postponed" for g in phase):
        return None
    return max(kickoff_utc(g.get("starts_at")) for g in phase)[:10]


def convert_competition(
    games: Sequence[Mapping[str, Any]], *, competition: str, season: str, fetched_at: str, paged_to_end: bool,
) -> CompetitionSnapshot:
    """One competition's whole ``list_games`` reply as a snapshot of the Premier League clubs' matches."""
    if competition not in LEAGUE_PHASE_GAMES:
        raise ValueError(f"not a StrikerAPI calendar competition: {competition!r}")
    if not games:
        raise SourceRejected("the reply has no games")
    matches = source_matches(games, competition)  # validates every row before any claim is made
    return convert_matches(
        matches, competition=competition, season=season, source=PROVENANCE, fetched_at=fetched_at,
        complete_as_of=complete_bound(games, competition, paged_to_end=paged_to_end),
    )


# -- the stored snapshot file --------------------------------------------------

def snapshot_to_dict(snapshot: CompetitionSnapshot) -> dict[str, Any]:
    return {
        "fetched_at": snapshot.fetched_at, "complete_as_of": snapshot.complete_as_of,
        "postponed": snapshot.postponed, "unmapped": list(snapshot.unmapped),
        "records": [asdict(r) for r in snapshot.records],
    }


def snapshot_from_dict(competition: str, season: str, data: Mapping[str, Any]) -> CompetitionSnapshot:
    """The inverse of :func:`snapshot_to_dict`; raises on anything that is not that shape."""
    records = tuple(FixtureRecord(**r) for r in data["records"])
    for r in records:
        if r.competition != competition or r.source != PROVENANCE or r.season != season:
            raise SourceRejected("a stored record does not belong to its competition")
        datetime.strptime(r.kickoff_utc, "%Y-%m-%dT%H:%M:%SZ")
    datetime.strptime(data["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
    bound = data.get("complete_as_of")
    if bound is not None:
        datetime.strptime(bound, "%Y-%m-%d")
    return CompetitionSnapshot(
        competition=competition, season=season, source=PROVENANCE, fetched_at=data["fetched_at"],
        complete_as_of=bound, records=records, unmapped=tuple(data.get("unmapped") or ()),
        postponed=int(data.get("postponed") or 0),
    )
