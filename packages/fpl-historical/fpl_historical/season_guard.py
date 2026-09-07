"""
fpl_historical.season_guard
============================
Live-API season-boundary guard (incident prevention, PR: fix/season-boundary-guard).

Root cause of the incident this exists to prevent: ``bootstrap-static`` has
no explicit season field and always serves whatever season is currently
live — nothing compared that against the season key a capture was writing
to, so once the live season rolled over, ``capture_season()`` kept writing
the new season's data under the old season's key every week.

Public API:
    derive_live_season(bootstrap) -> str | None
    assert_season_matches(bootstrap, target_season) -> None  (raises SeasonMismatchError)
"""

from __future__ import annotations

from typing import Any


class SeasonMismatchError(RuntimeError):
    """Raised when the live FPL API's season disagrees with a capture's target season.

    Reject, don't adapt: the caller must re-run with the correct ``--season``
    (or, if the old season truly still needs data, use a source other than
    the live API) — this module never silently writes under a different key
    than the one requested.
    """


def derive_live_season(bootstrap: dict[str, Any]) -> str | None:
    """Derive the season key ``bootstrap-static`` is currently serving.

    ``bootstrap-static`` carries no explicit season field. We derive it from
    ``deadline_time`` of event id=1 (the season's first gameweek): the FPL
    season always starts in the Jul/Aug window, so the season's start year
    is the deadline's calendar year if the deadline falls in Jul-Dec, else
    the previous year (a Jan-Jun deadline for event id=1 would be unusual
    but is handled the same way for robustness). E.g. a GW1 deadline of
    2026-08-14 -> ``"2026-2027"``.

    Returns ``None`` if event id=1 (or its ``deadline_time``) is missing —
    callers must treat that as "cannot verify" and decide accordingly; this
    function never guesses.

    What would break this derivation:
      - The FA moving the season start outside the Jul-Dec half of the
        calendar year (historically stable, but not a contract).
      - A void/restructured season where event ids are renumbered such that
        id=1 no longer corresponds to the season's actual first gameweek.
      - The FPL API publishing next season's fixtures (with next season's
        event id=1 deadline_time) during the close season before last
        season's owned store has been rotated. This is NOT a bug in this
        function — it is exactly the boundary case the guard exists to
        catch: if that happens, a capture targeting the old season key will
        correctly be rejected, and a human must explicitly decide whether to
        move the target key forward. The guard does not auto-adopt the new
        season.
    """
    events = bootstrap.get("events") or []
    event_one = next((e for e in events if e.get("id") == 1), None)
    if event_one is None:
        return None
    deadline = event_one.get("deadline_time")
    if not deadline or not isinstance(deadline, str) or len(deadline) < 7:
        return None
    try:
        year = int(deadline[0:4])
        month = int(deadline[5:7])
    except ValueError:
        return None
    start_year = year if month >= 7 else year - 1
    return f"{start_year}-{start_year + 1}"


def assert_season_matches(bootstrap: dict[str, Any], target_season: str) -> None:
    """Raise :class:`SeasonMismatchError` if the live API disagrees with *target_season*.

    Must be called before any capture output (raw dir, files, manifest) is
    created for *target_season* — this function performs no I/O itself and
    is safe to call before any write path is opened.

    If the live season cannot be derived (see :func:`derive_live_season`),
    this passes silently rather than blocking a capture on an unrelated data
    shape change — an inability to verify is not treated as a mismatch.
    """
    live_season = derive_live_season(bootstrap)
    if live_season is None or live_season == target_season:
        return
    raise SeasonMismatchError(
        f"Refusing to capture: the live FPL API is currently serving the "
        f"{live_season!r} season (derived from event id=1's deadline_time), "
        f"but this capture was requested for season {target_season!r}. "
        f"No files were written. "
        f"If {live_season!r} is the season you actually want to capture, "
        f"re-run with --season {live_season}. "
        f"If you deliberately want to keep capturing {target_season!r} data "
        f"(e.g. a historical backfill), the live bootstrap-static endpoint "
        f"cannot serve it — you need a different, season-specific source, "
        f"not this capture path."
    )
