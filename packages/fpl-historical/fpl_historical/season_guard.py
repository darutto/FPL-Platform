"""
fpl_historical.season_guard
============================
Live-API season-boundary guard (incident prevention, PR: fix/season-boundary-guard).

Root cause of the incident this exists to prevent: ``bootstrap-static`` has
no explicit season field and always serves whatever season is currently
live — nothing compared that against the season key a capture was writing
to, so once the live season rolled over, ``capture_season()`` kept writing
the new season's data under the old season's key every week.

The guard fails CLOSED. There are three states, not two: the live season
matches, it disagrees, or it could not be determined at all. The third is
NOT folded into the first — an absent reading is not a favourable reading.
The window in which the bootstrap event list is rebuilt *is* the season
rollover, i.e. the moment of highest risk is exactly the moment the payload
is most likely to arrive in an unexpected shape, so an unverifiable season
rejects. The cost asymmetry is not a tie: over-rejecting costs one skipped,
loudly-visible capture; over-admitting costs a silently overwritten season.

An operator who has looked and decided the unverifiable payload is benign
can pass ``allow_unverified_season=True`` (CLI: ``--allow-unverified-season``).
That valve covers ONLY the undetermined case. A *confirmed* mismatch is
always rejected and has no override.

Public API:
    derive_live_season(bootstrap) -> str | None
    assert_season_matches(bootstrap, target_season, *, allow_unverified_season=False)
        -> None  (raises SeasonMismatchError or SeasonUndeterminedError)
"""

from __future__ import annotations

from typing import Any


class SeasonGuardError(RuntimeError):
    """Base class for every season-boundary guard rejection.

    Catch this to mean "the guard refused; nothing was written". Catch one
    of the two subclasses to distinguish *why* it refused.
    """


class SeasonMismatchError(SeasonGuardError):
    """Raised when the live FPL API's season disagrees with a capture's target season.

    Reject, don't adapt: the caller must re-run with the correct ``--season``
    (or, if the old season truly still needs data, use a source other than
    the live API) — this module never silently writes under a different key
    than the one requested.

    This is the *confirmed disagreement* case: a live season was
    successfully derived and it is not the one requested. It has no
    override — see :class:`SeasonUndeterminedError` for the case that does.
    """


class SeasonUndeterminedError(SeasonGuardError):
    """Raised when the live FPL API's season could not be determined at all.

    Distinct from :class:`SeasonMismatchError`: that one means "I looked and
    found a *different* season"; this one means "I looked and could not see
    any season". The remedies differ, so the exceptions do too.

    This is the guard's fail-closed branch. It is overridable — deliberately,
    by a human, via ``allow_unverified_season=True`` — because an unrelated
    change in the bootstrap payload's shape is a legitimate reason to want a
    capture to proceed anyway. The override must be typed on purpose; the
    default is to refuse.
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


def assert_season_matches(
    bootstrap: dict[str, Any],
    target_season: str,
    *,
    allow_unverified_season: bool = False,
) -> None:
    """Verify the live API is serving *target_season*, or refuse.

    Must be called before any capture output (raw dir, files, manifest) is
    created for *target_season* — this function performs no I/O itself and
    is safe to call before any write path is opened.

    Three outcomes, not two:

    - live season == *target_season*  -> returns, capture proceeds.
    - live season != *target_season*  -> :class:`SeasonMismatchError`.
      Always. *allow_unverified_season* does not reach this branch and
      cannot suppress it: a confirmed disagreement is never overridable.
    - live season could not be derived -> :class:`SeasonUndeterminedError`,
      unless *allow_unverified_season* is true, in which case the capture
      proceeds unverified. Absence of a reading is not a favourable
      reading; the operator has to say so explicitly.
    """
    live_season = derive_live_season(bootstrap)

    if live_season is None:
        if allow_unverified_season:
            return
        raise SeasonUndeterminedError(
            f"Refusing to capture: could not determine which season the live "
            f"FPL API is currently serving, so this capture's target season "
            f"{target_season!r} could not be verified. "
            f"The season is derived from event id=1's deadline_time in "
            f"bootstrap-static; that event, or its deadline_time, is missing "
            f"or unreadable in the payload just fetched. "
            f"No files were written. "
            f"This is deliberately not treated as a pass: the bootstrap event "
            f"list is rebuilt at the season rollover, which is exactly when a "
            f"capture writing to the wrong season key does the most damage. "
            f"Inspect the bootstrap-static payload first. If you have checked "
            f"it and the missing field is unrelated to a season change, re-run "
            f"with --allow-unverified-season to proceed without verification. "
            f"That flag covers only this case; it cannot override a season "
            f"that was determined and did not match."
        )

    if live_season == target_season:
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
