"""Probe whether Understat has published a season, and whether we hold it (i77).

    python scripts/probe_understat_season.py --season 2027-2028
    python scripts/probe_understat_season.py --next-after 2026-2027   # same thing

Why this exists
---------------
The tactical-store refresh cron re-ingested a FINISHED season every Monday
from July to September 2026, in green, and nobody noticed. Rotating to the
new season (i73, delivery 2) is blocked on a third party -- Understat
publishing it -- and until this step there was nothing that said when that
had happened. The trigger was "someone remembers".

What it does (one schedule read, one R2 HEAD; nothing is written)
-----------------------------------------------------------------
For the season given it reads Understat's schedule through soccerdata (the
same call ``fpl_tactical.understat_client`` makes, minus the 380 shot pulls)
and checks whether our tactical store for that season exists on R2 (the
provenance pointer key ``publish._season_transfer_plan`` uploads first).
Then it classifies:

    schedule empty,     store absent   -> UNPUBLISHED             notice,  exit 0
    schedule empty,     store present  -> UNPUBLISHED_STORE_PRESENT warning, exit 0
    schedule published, store absent   -> PUBLISHED_NO_STORE      ERROR,   exit 1
    schedule published, store present  -> PUBLISHED               notice,  exit 0
    the probe itself failed            -> PROBE_FAILED            ERROR,   exit 2

``PUBLISHED_NO_STORE`` is the rotation moment: Understat has the season and we
have never stored it. It fails the job on purpose -- a failure that is meant
to be seen, not one to be ignored. Detecting it does NOT ingest anything or
bump ``current_season``: that stays a human-approved operation (i70's guard).

It also writes ``published``, ``store_exists``, ``outcome``, ``season`` and
``matches`` to ``$GITHUB_OUTPUT`` when that variable is set, so a workflow can
gate later steps on them (a step cannot end "neutral" in Actions; skipping the
ingest via ``if:`` while the job stays green is the equivalent).

The (3, 0) trap -- read this before touching ``_classify``
-----------------------------------------------------------
Measured 2026-09-13: ``read_schedule()`` for an unpublished season returns a
frame of shape ``(3, 0)`` -- three index labels over ZERO columns, i.e. empty
-- and ``(380, 17)`` for a published one. ``shape[0] == 0`` is therefore the
wrong test (it is 3), and ``reset_index()`` -- which ``understat_client``
applies before returning -- turns that frame into ``(3, 1)`` with
``.empty == False``. The probe classifies the RAW frame with ``.empty`` and
reports ``matches = 0`` for it, never 3.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

# Make ``fpl_tactical`` importable when run as ``python scripts/...`` from the
# package directory or the repo root (the workflow sets PYTHONPATH as well).
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))

# --- outcomes ---------------------------------------------------------------

UNPUBLISHED = "unpublished"
UNPUBLISHED_STORE_PRESENT = "unpublished_store_present"
PUBLISHED_NO_STORE = "published_no_store"
PUBLISHED = "published"
PROBE_FAILED = "probe_failed"

EXIT_PROCEED = 0
EXIT_ROTATION_PENDING = 1
EXIT_PROBE_FAILED = 2

_SEASON_KEY = re.compile(r"^(\d{4})-(\d{4})$")


def next_season_key(season: str) -> str:
    """``"2026-2027" -> "2027-2028"``. Raises ValueError on a malformed key."""
    m = _SEASON_KEY.match(season or "")
    if not m or int(m.group(2)) != int(m.group(1)) + 1:
        raise ValueError(f"not a season key of the form YYYY-YYYY+1: {season!r}")
    start = int(m.group(1)) + 1
    return f"{start}-{start + 1}"


# --- the two network boundaries (replaced in tests, never reached there) ----

def read_schedule(season: str) -> Any:
    """Understat's schedule for *season*, RAW (no ``reset_index``) -- see the
    module docstring for why the raw frame is the one to classify."""
    import soccerdata as sd  # lazy: weekly-workflow dependency only

    from fpl_tactical.understat_client import DEFAULT_LEAGUE

    return sd.Understat(leagues=DEFAULT_LEAGUE, seasons=season).read_schedule()


def tactical_store_exists_on_r2(season: str) -> bool:
    """True iff the season's provenance pointer exists on R2.

    Uses the same client and key layout ``fpl_tactical.publish`` uploads with,
    so "exists" here means exactly "publish has run for this season". A 404 is
    ``False``; any other failure propagates (credentials, network) so it is
    reported as a probe failure rather than mistaken for an absent store.
    """
    from fpl_tactical import publish

    client = publish._make_r2_client()
    bucket = os.environ.get(publish.ENV_R2_BUCKET, "").strip()
    pointer_key = publish._season_transfer_plan(season)[0][1]
    try:
        client.head_object(Bucket=bucket, Key=pointer_key)
    except Exception as exc:  # noqa: BLE001 -- only a 404 means "absent"
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


# --- classification (pure) ---------------------------------------------------

def _matches(schedule: Any) -> int:
    """Rows of a published schedule; 0 for the empty ``(3, 0)`` frame."""
    if schedule is None or getattr(schedule, "empty", True):
        return 0
    return int(len(schedule))


def _classify(matches: int, store_exists: bool) -> tuple[str, int]:
    """(outcome, exit code) for one probe. The only decision table here."""
    published = matches > 0
    if published and not store_exists:
        return PUBLISHED_NO_STORE, EXIT_ROTATION_PENDING
    if published:
        return PUBLISHED, EXIT_PROCEED
    if store_exists:
        return UNPUBLISHED_STORE_PRESENT, EXIT_PROCEED
    return UNPUBLISHED, EXIT_PROCEED


def _message(outcome: str, season: str, matches: int) -> str:
    if outcome == PUBLISHED_NO_STORE:
        return (
            f"::error::Understat publicó {season}: ejecutar la entrega de i73 "
            f"pendiente (ingestar y publicar el store táctico de {season}, "
            f"después subir current_season). Calendario: {matches} partidos; "
            f"store táctico en R2: ausente."
        )
    if outcome == PUBLISHED:
        return (
            f"::notice::Understat publica {season} ({matches} partidos en el "
            f"calendario) y el store táctico existe en R2."
        )
    if outcome == UNPUBLISHED_STORE_PRESENT:
        return (
            f"::warning::Understat no publica {season} pero existe un store "
            f"táctico en R2 para esa temporada: revisar con qué clave se escribió."
        )
    return f"::notice::Understat aún no publica {season}"


def _write_outputs(path: str | None, rows: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in rows.items():
            value = str(value).lower() if isinstance(value, bool) else value
            fh.write(f"{key}={value}\n")


# --- entry point ---------------------------------------------------------------

def main(
    argv: list[str] | None = None,
    *,
    read_schedule_fn: Callable[[str], Any] | None = None,
    store_exists_fn: Callable[[str], bool] | None = None,
    stdout: Any = None,
) -> int:
    ap = argparse.ArgumentParser(description="Probe Understat for one season (i77).")
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--season", help="season key to probe, e.g. 2027-2028")
    which.add_argument("--next-after", metavar="SEASON",
                       help="probe the season after this key, e.g. --next-after 2026-2027")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"),
                    help="file to append step outputs to (default: $GITHUB_OUTPUT)")
    args = ap.parse_args(argv)
    out = stdout or sys.stdout

    read_fn = read_schedule_fn or read_schedule
    store_fn = store_exists_fn or tactical_store_exists_on_r2

    try:
        season = args.season or next_season_key(args.next_after)
    except ValueError as exc:
        print(f"::error::sonda de Understat: {exc}", file=out)
        return EXIT_PROBE_FAILED

    try:
        matches = _matches(read_fn(season))
        store_exists = bool(store_fn(season))
    except Exception as exc:  # noqa: BLE001 -- a failed probe is reported, not hidden
        print(
            f"::error::sonda de Understat falló para {season}: "
            f"{type(exc).__name__}: {exc}",
            file=out,
        )
        _write_outputs(args.github_output, {
            "season": season, "outcome": PROBE_FAILED,
        })
        return EXIT_PROBE_FAILED

    outcome, code = _classify(matches, store_exists)
    print(_message(outcome, season, matches), file=out)
    _write_outputs(args.github_output, {
        "season": season,
        "published": matches > 0,
        "store_exists": store_exists,
        "matches": matches,
        "outcome": outcome,
    })
    return code


if __name__ == "__main__":
    sys.exit(main())
