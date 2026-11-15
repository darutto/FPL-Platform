"""Hand-compiled European calendar (``manual_curated``): the text list -> a small local JSON layer. No I/O, no clock.

The list is a manual compilation of public facts that Leo keeps OUTSIDE git (``data/calendar-manual/``); its
origin is still to be registered. This module only converts its shape, and the tests use synthetic text.

Decisions a reviewer should be able to find:

* **A time makes the match countable; a missing or unverified one does not.** A line may end in
  ``- HH:MM EST / HH:MM <zone>``; both are converted to UTC and must be the same instant (a mismatch is returned in
  ``warnings`` and the match is marked unverified). A match with no time, a mismatching time, or one the caller lists as
  ``unverified`` carries ``kickoff_known: False``: it is shown, but no rest day or rotation notice is computed from it
  (a gap needs hours; a doubtful hour must not warn anyone).
* **Always ``partial``.** The list is not the full calendar (no already-played rounds, nothing after its last
  date), so it can never claim completeness; it is also **frozen**: it is not refreshed, and says so.
* **Clubs by registry alias only** (:func:`public_calendar.pl_club_code`); a club that is not one of the 20 is an
  error, never a guess. The opponent is a display name only; its code is the registry's for a Premier League club
  and empty otherwise (the UI derives a three-letter tile from the name).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from .public_calendar import normalize_club_name, pl_club_code

SCHEMA_VERSION = 1
PROVENANCE = "manual_curated"
COMPETITION_HEADERS = {"champions league": "UCL", "europa league": "UEL", "conference league": "UECL"}
_VENUES = {"local": "H", "visitante": "A"}
_LINE = re.compile(r"^-\s*(\d{2})/(\d{2})/(\d{4})\s+vs\s+(.+?)\s+\((Local|Visitante)\)"
                   r"(?:\s*-\s*(\d{2}):(\d{2})\s+EST\s*/\s*(\d{2}):(\d{2})\s+([A-Z]{2,4}))?\s*$", re.IGNORECASE)
#: Whole-hour UTC offsets of the zones the list uses in the winter months it covers (Nov-Jan: no summer time).
_EST_OFFSET = -5
ZONE_OFFSETS = {"GMT": 0, "WET": 0, "CET": 1, "EET": 2, "TRT": 3}


class ManualCalendarError(ValueError):
    """The list is not in the expected shape (the message carries the line number, never the data)."""


def _utc(day: date, hour: str, minute: str, offset: int) -> datetime:
    return datetime(day.year, day.month, day.day, int(hour), int(minute)) - timedelta(hours=offset)


def parse_manual_europe(text: str, *, list_date: str, season: str = "2026-2027",
                        unverified: frozenset[tuple[str, str]] = frozenset()) -> dict[str, Any]:
    """The layer for ``text``. ``list_date`` (``YYYY-MM-DD``) is when the list was compiled: the visible date stamp.

    ``unverified`` is a set of ``(club code, ISO date)`` whose time is doubtful (sources disagree): kept, flagged.
    The result's ``warnings`` lists (line number, reason) for every time that could not be confirmed.
    """
    date.fromisoformat(list_date)
    warnings: list[dict[str, Any]] = []
    competition: str | None = None
    club: str | None = None
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        header = COMPETITION_HEADERS.get(normalize_club_name(line))
        if header is not None:
            competition, club = header, None
            continue
        found = _LINE.match(line)
        if found is None:
            if line.startswith("-"):
                raise ManualCalendarError(f"line {number}: not a match line")
            code = pl_club_code(line)
            if code is None:
                if competition is None:
                    continue  # the title, before the first competition block
                raise ManualCalendarError(f"line {number}: not a Premier League club")
            club = code
            continue
        if competition is None or club is None:
            raise ManualCalendarError(f"line {number}: match outside a competition/club block")
        day, month, year, opponent, venue, eh, em, lh, lm, zone = found.groups()
        try:
            when = date(int(year), int(month), int(day))
        except ValueError as exc:
            raise ManualCalendarError(f"line {number}: invalid date") from exc
        iso = when.isoformat()
        kickoff_utc: str | None = None
        if eh is not None:
            offset = ZONE_OFFSETS.get(zone.upper())
            if offset is None:
                raise ManualCalendarError(f"line {number}: unknown time zone")
            est, local = _utc(when, eh, em, _EST_OFFSET), _utc(when, lh, lm, offset)
            if est != local:
                warnings.append({"line": number, "reason": "est_local_mismatch"})
            elif (club, iso) in unverified:
                warnings.append({"line": number, "reason": "listed_unverified"})
            else:
                kickoff_utc = est.strftime("%Y-%m-%dT%H:%M:%SZ")

        if (competition, club, iso) in seen:
            raise ManualCalendarError(f"line {number}: duplicate match")
        seen.add((competition, club, iso))
        match = {"competition": competition, "club": club, "opponent": opponent,
                 "opponent_code": pl_club_code(opponent) or "", "date": iso,
                 "venue": _VENUES[venue.lower()], "kickoff_known": kickoff_utc is not None}
        if kickoff_utc is not None:
            match["kickoff_utc"] = kickoff_utc
        matches.append(match)
    if not matches:
        raise ManualCalendarError("no matches found")
    matches.sort(key=lambda m: (m["date"], m["club"]))
    return {"schema_version": SCHEMA_VERSION, "provenance": PROVENANCE, "season": season, "list_date": list_date,
            "coverage": "partial", "frozen": True,
            "competitions": sorted({m["competition"] for m in matches}), "warnings": warnings, "matches": matches}
