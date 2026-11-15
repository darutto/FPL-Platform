"""Calendar of the other competitions from public sources, phase F1: everything that does not depend on the source.

Nothing here touches the network, a clock or a file. A source-specific converter (a later phase, once Leo
approves a source) maps its raw page to ``SourceMatch`` rows and calls :func:`convert_matches`; everything
after that is shared and tested on hand-written data.

    raw page -> [source converter] -> SourceMatch rows -> convert_matches -> CompetitionSnapshot
    [CompetitionSnapshot, ...] -> build_public_calendar -> {club code: [match, ...]}

The output is exactly the shape ``build_calendar`` (``live_trial_calendar``) gives and that
``fpl_grounded_assistant.competition_calendar`` consumes, plus one extra key on Premier League matches,
``calendar_complete`` (see below). Rest days are computed by the same ``finish_calendar`` as the trial calendar.

Decisions a reviewer should be able to find:

* **Missing data is not "no match".** A competition is *complete* only when its converter says the fixture
  list is final up to a date (``complete_as_of``, a BOUND, inclusive); otherwise it is *partial*. A snapshot
  older than ``stale_after`` is *stale*, and a competition the deployment claims to cover but supplied no
  snapshot for is *missing*. A Premier League match carries ``calendar_complete: True`` only when every covered
  competition is complete and fresh AND the smallest of their bounds is on or after that match's kickoff date;
  otherwise False, and the rotation notice is not issued (``competition_calendar._rotates``): a calendar with a
  hole, or one that only guarantees November, can silently hide the match that explains December's rest days.
* **Clubs are mapped by an explicit alias table, never guessed.** The 20 Premier League clubs are matched by
  accent- and punctuation-insensitive name aliases (:data:`PL_CLUB_ALIASES`). A name that is not a Premier
  League club is the *opponent*; its three-letter code comes from the source if it gave one, from a table the
  converter injects, or is :data:`UNKNOWN_CODE` and the name is listed in ``CompetitionSnapshot.unmapped``.
* **Postponed matches are not matches** (no confirmed kickoff): they are skipped, as in the trial calendar,
  and counted in ``CompetitionSnapshot.postponed``. A played match still counts for the rest days after it.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Literal, Mapping, Protocol, Sequence

from .live_trial_calendar import finish_calendar, week_start

Status = Literal["scheduled", "postponed", "played"]
Completeness = Literal["complete", "partial", "stale", "missing"]

#: Badges, as in ``live_trial_calendar.BADGES`` plus ``PL`` for the Premier League itself.
COMPETITIONS = ("PL", "UCL", "UEL", "UECL", "UEFA-SC", "FA", "EFL")
STATUSES = ("scheduled", "postponed", "played")
#: Shown instead of a guessed code when no source or table knows the opponent (flagged in ``unmapped``).
UNKNOWN_CODE = "???"
#: Weekly refresh plus slack; a snapshot older than this is stale (proposal: weekly + daily in match weeks).
DEFAULT_STALE_AFTER = timedelta(days=8)

#: FPL three-letter code -> accepted names (any of them, after normalisation). 2026-27 Premier League clubs.
PL_CLUB_ALIASES: dict[str, tuple[str, ...]] = {
    "ARS": ("Arsenal", "Arsenal FC"),
    "AVL": ("Aston Villa", "Aston Villa FC", "Villa"),
    "BHA": ("Brighton", "Brighton & Hove Albion", "Brighton and Hove Albion", "Brighton Hove Albion"),
    "BOU": ("Bournemouth", "AFC Bournemouth"),
    "BRE": ("Brentford", "Brentford FC"),
    "CHE": ("Chelsea", "Chelsea FC"),
    "COV": ("Coventry City", "Coventry", "Coventry City FC"),
    "CRY": ("Crystal Palace", "Crystal Palace FC", "Palace"),
    "EVE": ("Everton", "Everton FC"),
    "FUL": ("Fulham", "Fulham FC"),
    "HUL": ("Hull City", "Hull", "Hull City AFC"),
    "IPS": ("Ipswich Town", "Ipswich", "Ipswich Town FC"),
    "LEE": ("Leeds", "Leeds United", "Leeds United FC"),
    "LIV": ("Liverpool", "Liverpool FC"),
    "MCI": ("Man City", "Manchester City", "Manchester City FC"),
    "MUN": ("Man Utd", "Man United", "Manchester United", "Manchester United FC"),
    "NEW": ("Newcastle", "Newcastle United", "Newcastle United FC"),
    "NFO": ("Nott'm Forest", "Nottingham Forest", "Nottm Forest", "Nottingham Forest FC"),
    "SUN": ("Sunderland", "Sunderland AFC"),
    "TOT": ("Spurs", "Tottenham", "Tottenham Hotspur", "Tottenham Hotspur FC"),
}


def normalize_club_name(name: str) -> str:
    """Lowercase, accent-free, letters and digits only: ``"Nott'm Forest"`` and ``"NOTTM FOREST"`` compare equal."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in folded).split())


_ALIAS_TO_CODE: dict[str, str] = {}
for _code, _names in PL_CLUB_ALIASES.items():
    for _name in _names:
        _key = normalize_club_name(_name)
        if _ALIAS_TO_CODE.setdefault(_key, _code) != _code:
            raise RuntimeError(f"alias {_name!r} maps to two clubs")


def pl_club_code(name: str) -> str | None:
    """The FPL code of a Premier League club by name, or None when the name is not one of the 20 (never a guess)."""
    return _ALIAS_TO_CODE.get(normalize_club_name(name))


@dataclass(frozen=True)
class SourceMatch:
    """One match as a source converter hands it over, before any club mapping."""

    competition: str
    home_name: str
    away_name: str
    #: ``YYYY-MM-DDTHH:MM:SSZ`` (UTC).
    kickoff_utc: str
    status: Status = "scheduled"
    #: Source-provided three-letter codes, when it has them (used for non-Premier-League clubs).
    home_code: str | None = None
    away_code: str | None = None
    #: Premier League matches only: the round number.
    gameweek: int | None = None


@dataclass(frozen=True)
class FixtureRecord:
    """One match from one Premier League club's side. The normalized record of the plan."""

    competition: str
    season: str
    club: str  # FPL three-letter code
    opponent: str
    opponent_code: str  # three letters, or UNKNOWN_CODE (flagged in the snapshot)
    kickoff_utc: str
    venue: Literal["H", "A"]
    status: Status
    source: str
    fetched_at: str
    gameweek: int | None = None


@dataclass(frozen=True)
class CompetitionSnapshot:
    """The fixtures of one competition as read from one source at one moment."""

    competition: str
    season: str
    source: str
    fetched_at: str
    #: ISO date (``YYYY-MM-DD``, inclusive) up to which the source guarantees the list is final; None = partial.
    complete_as_of: str | None
    records: tuple[FixtureRecord, ...] = ()
    #: Names that matched no Premier League club and for which no code was available (flagged, not guessed).
    unmapped: tuple[str, ...] = ()
    #: Matches skipped because they were postponed (no confirmed kickoff).
    postponed: int = 0

    @property
    def is_complete(self) -> bool:
        return self.complete_as_of is not None


class SourceConverter(Protocol):
    """What a source-specific converter provides (a later phase). Pure: raw data in, snapshot out, no I/O."""

    competition: str
    source: str

    def convert(self, raw: Any, *, season: str, fetched_at: str) -> CompetitionSnapshot: ...


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def convert_matches(
    matches: Iterable[SourceMatch],
    *,
    competition: str,
    season: str,
    source: str,
    fetched_at: str,
    complete_as_of: str | None = None,
    known_codes: Mapping[str, str] | None = None,
) -> CompetitionSnapshot:
    """Map source matches to club-perspective records for the Premier League clubs.

    ``known_codes`` maps club names (normalised here, see :func:`normalize_club_name`) to three-letter codes
    for the converter's non-Premier-League clubs. Matches with no Premier League side are dropped (they are not
    any club's calendar); an opponent with no code is kept with :data:`UNKNOWN_CODE` and listed in ``unmapped``.
    """
    if competition not in COMPETITIONS:
        raise ValueError(f"unknown competition {competition!r}")
    _parse_utc(fetched_at)
    if complete_as_of is not None:
        date.fromisoformat(complete_as_of)  # a malformed bound fails loudly instead of reading as "complete"
    known = {normalize_club_name(k): v for k, v in (known_codes or {}).items()}
    records: list[FixtureRecord] = []
    unmapped: set[str] = set()
    postponed = 0

    def opponent_code(name: str, given: str | None) -> str:
        pl = pl_club_code(name)
        if pl is not None:
            return pl
        code = (given or known.get(normalize_club_name(name)) or "").strip().upper()
        if len(code) == 3 and code.isalpha():
            return code
        unmapped.add(name)
        return UNKNOWN_CODE

    for m in matches:
        if m.competition != competition:
            raise ValueError(f"match of {m.competition!r} in a {competition!r} conversion")
        if m.status not in STATUSES:
            raise ValueError(f"unknown status {m.status!r}")
        _parse_utc(m.kickoff_utc)  # a malformed kickoff fails loudly instead of landing in the calendar
        if m.status == "postponed":
            postponed += 1
            continue
        sides = ((m.home_name, m.away_name, m.away_code, "H"), (m.away_name, m.home_name, m.home_code, "A"))
        for own, other, other_given, venue in sides:
            club = pl_club_code(own)
            if club is None:
                continue
            records.append(FixtureRecord(
                competition=competition, season=season, club=club, opponent=other,
                opponent_code=opponent_code(other, other_given), kickoff_utc=m.kickoff_utc,
                venue=venue,  # type: ignore[arg-type]
                status=m.status, source=source, fetched_at=fetched_at, gameweek=m.gameweek,
            ))
    records.sort(key=lambda r: (r.kickoff_utc, r.club))
    return CompetitionSnapshot(
        competition=competition, season=season, source=source, fetched_at=fetched_at,
        complete_as_of=complete_as_of, records=tuple(records), unmapped=tuple(sorted(unmapped)), postponed=postponed,
    )


def snapshot_status(
    snapshot: CompetitionSnapshot | None, now: datetime, stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> Completeness:
    """``missing`` (no snapshot), ``stale`` (too old), ``partial`` (no completeness claim) or ``complete``.

    Stale wins over complete: a list that was complete a month ago says nothing about postponements since.
    """
    if snapshot is None:
        return "missing"
    if now - _parse_utc(snapshot.fetched_at) > stale_after:
        return "stale"
    return "complete" if snapshot.is_complete else "partial"


def calendar_status(
    snapshots: Sequence[CompetitionSnapshot],
    covered: Sequence[str],
    now: datetime,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> dict[str, dict[str, Any]]:
    """Per covered competition: its status, source, fetch time and the date it is complete up to."""
    by_comp = {s.competition: s for s in snapshots}
    out: dict[str, dict[str, Any]] = {}
    for comp in covered:
        snap = by_comp.get(comp)
        out[comp] = {
            "status": snapshot_status(snap, now, stale_after),
            "source": snap.source if snap else None,
            "fetched_at": snap.fetched_at if snap else None,
            "complete_as_of": snap.complete_as_of if snap else None,
            "unmapped": list(snap.unmapped) if snap else [],
        }
    return out


def build_public_calendar(
    snapshots: Sequence[CompetitionSnapshot],
    *,
    now: datetime,
    covered: Sequence[str] | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> dict[str, list[dict[str, Any]]]:
    """``{club code: [match, ...]}`` in kickoff order, the shape ``competition_calendar`` consumes.

    ``snapshots`` carry every competition the deployment has, the Premier League included (its rows carry the
    round number in ``gameweek``; a converter for the FPL fixtures is a later phase). ``covered`` is what the
    deployment *claims* to cover (default: the competitions it has snapshots for); a covered competition with
    no snapshot is *missing*. Each Premier League match gets ``calendar_complete``: True only when every covered
    non-Premier-League competition is complete and fresh and the smallest ``complete_as_of`` among them is on or
    after the match's own kickoff date. When it is False the rotation notice is suppressed.
    """
    by_comp: dict[str, CompetitionSnapshot] = {}
    for s in snapshots:
        if s.competition in by_comp:
            raise ValueError(f"two snapshots for {s.competition!r}")
        by_comp[s.competition] = s
    wanted = [c for c in (covered if covered is not None else by_comp) if c != "PL"]
    complete = all(snapshot_status(by_comp.get(c), now, stale_after) == "complete" for c in wanted)
    # The guarantee only reaches the earliest bound among the covered competitions (None when nothing is covered).
    bound = min((date.fromisoformat(by_comp[c].complete_as_of) for c in wanted), default=None) if complete else None  # type: ignore[arg-type]
    nothing_to_cover = not wanted

    pl_rows = [r for r in (by_comp["PL"].records if "PL" in by_comp else ()) if r.status != "postponed"]
    gw_last: dict[int, datetime] = {}
    for r in pl_rows:
        if r.gameweek is not None:
            gw_last[r.gameweek] = max(gw_last.get(r.gameweek, datetime.min), _parse_utc(r.kickoff_utc))
    gw_order = sorted(gw_last)

    per_club: dict[str, list[dict[str, Any]]] = {code: [] for code in PL_CLUB_ALIASES}
    for comp, snap in by_comp.items():
        for r in snap.records:
            if r.status == "postponed":
                continue
            kickoff = _parse_utc(r.kickoff_utc)
            is_pl = comp == "PL"
            if is_pl and r.gameweek is not None:
                gameweek: int | None = r.gameweek
            else:
                gameweek = next((g for g in gw_order if gw_last[g] >= kickoff), None)
            match: dict[str, Any] = {
                "kickoff_utc": r.kickoff_utc,
                "week": week_start(kickoff.date()),
                "gameweek": gameweek,
                "competition": comp,
                "is_pl": is_pl,
                "venue": r.venue,
                "opponent": r.opponent,
                "opponent_code": r.opponent_code,
                "_kickoff": kickoff,
            }
            if is_pl:
                match["calendar_complete"] = complete and (nothing_to_cover or (bound is not None and kickoff.date() <= bound))
            per_club[r.club].append(match)
    return finish_calendar(per_club)
