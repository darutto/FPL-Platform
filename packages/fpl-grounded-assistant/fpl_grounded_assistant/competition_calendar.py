"""Multi-competition calendar endpoint logic (``GET /fixtures/competitions``). Dev-only data.

Two sources. In production the cups (FA, Carabao) come from the synced licensed store
(``licensed_starter``, best-effort: always partial, so the rotation notice is never issued from them) plus the
Premier League fixtures; Europe is not in the Starter plan and is absent. In development the local Sportmonks
trial capture (``live_trial_local`` provenance, never published) is used when BOTH dev variables are set: ``FI_DEV_ALLOW_LIVE_TRIAL_LOCAL=1`` and
``FI_DEV_LIVE_TRIAL_CAPTURE=<path to capture.json>``; with neither source the endpoint answers
``available: false``. Neither variable may appear
in any prod path (Dockerfile, deploy config, CI); a test greps for it.

The tier is decided here, on the server, from the tier the caller passes in (the
single ``tier_of(request)`` seam in ``fpl_server``, which i153 will harden). The free
payload is a constant, ``{"available": true, "tier": "free"}``: it is never a filtered
copy of the premium one, so it cannot leak an opponent, a competition or even a count.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_intelligence.live_trial_calendar import build_calendar

ENV_ALLOW = "FI_DEV_ALLOW_LIVE_TRIAL_LOCAL"
ENV_CAPTURE = "FI_DEV_LIVE_TRIAL_CAPTURE"
#: Tiers that get the detail: Gafete de cancha ($5, patreon_basic) and above (Leo, 2026-10-14).
#: Every other tier (patreon_tribuna $1, free) gets the counts-only view with the lock mark.
DETAIL_TIERS = frozenset({"patreon_basic", "patreon_plus", "patreon_premium"})
#: PRODUCT constants, decided by Leo (not M3 thresholds: M3 has none for rest days).
#: ROTATION_REST_DAYS (2026-10-14): a Premier League match warns of possible rotation when the
#: club's previous match was this many WHOLE days before it or fewer (floor(hours/24) between
#: kickoffs: 3 whole days = 72h to <96h, so Tuesday night -> Saturday afternoon warns; 96h does not).
#: ROTATION_AFTER (decided by Leo 2026-10-14: only after a European/cup match): the notice needs the
#: previous match to be one of these competitions (UEFA Super Cup included: a European match, added
#: at Leo's "after Europe or cup" intent); PL -> PL never warns. Rest days are always shown.
ROTATION_REST_DAYS = 3
ROTATION_AFTER = frozenset({"UCL", "UEL", "UECL", "UEFA-SC", "FA", "EFL"})

_cache: dict[tuple[str, float], dict[str, list[dict[str, Any]]]] = {}
_LOG = logging.getLogger(__name__)
#: Cups the licensed store covers (best-effort, always ``partial``). Europe is NOT in the Starter plan.
LICENSED_COVERED = ("FA", "EFL")
_PL_TTL_SECONDS = 600
_pl_cache: dict[str, Any] = {"at": 0.0, "rows": None}
_licensed_cache: dict[str, Any] = {}


def _pl_snapshot(season: str, fetched_at: str):
    """Premier League fixtures (FPL API, cached) as a snapshot, so the board can lay cups and league on one timeline."""
    from football_intelligence.public_calendar import CompetitionSnapshot, FixtureRecord

    now = time.time()
    if _pl_cache["rows"] is None or now - _pl_cache["at"] > _PL_TTL_SECONDS:
        from fpl_api_client.fpl_client import get_all_fixtures, get_bootstrap
        codes = {int(t["id"]): str(t["short_name"]) for t in get_bootstrap().get("teams", ())}
        _pl_cache.update(at=now, rows=(codes, get_all_fixtures()))
    codes, fixtures = _pl_cache["rows"]
    records = []
    for f in fixtures:
        kickoff, event = f.get("kickoff_time"), f.get("event")
        home, away = codes.get(int(f.get("team_h", 0))), codes.get(int(f.get("team_a", 0)))
        if not kickoff or event is None or home is None or away is None:
            continue  # unscheduled (no kickoff or round): not a match yet
        for club, other, venue in ((home, away, "H"), (away, home, "A")):
            records.append(FixtureRecord("PL", season, club, other, other, kickoff, venue, "scheduled",
                                         "fpl_api", fetched_at, int(event)))
    return CompetitionSnapshot("PL", season, "fpl_api", fetched_at, None, tuple(records))


def _licensed_calendar() -> dict[str, list[dict[str, Any]]] | None:
    """FA/Carabao from the synced licensed store (``licensed_starter``) plus the PL fixtures, or None.

    Never raises: an unsynced store, a refused build or an unreachable FPL API all read as "no data", which the
    endpoint answers as ``available: false`` -- never as an empty calendar ("no match").
    """
    try:
        from football_intelligence.distribution.licensed_runtime import handle_from_env
        from football_intelligence.public_calendar import CompetitionSnapshot, FixtureRecord, build_public_calendar, calendar_status

        handle = handle_from_env()
        manifest = handle.manifest()
        key = manifest["build_id"]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        europe = _europe_layer(now)                      # None with the flag off: nothing below changes
        if europe is not None:
            key = (key, europe["fingerprint"])
        hit = _licensed_cache.get("calendar")
        if hit and hit["build"] == key and time.time() - hit["at"] < _PL_TTL_SECONDS:
            return hit["value"]
        snaps, recs = handle.table("cup_snapshots"), handle.table("cup_records")
        season = str(snaps["season"].iloc[0]) if len(snaps) else ""
        snapshots = []
        for row in snaps.to_dict("records"):
            rows = recs[recs["competition"] == row["competition"]].to_dict("records")
            snapshots.append(CompetitionSnapshot(
                competition=row["competition"], season=str(row["season"]), source=str(row["source"]),
                fetched_at=str(row["fetched_at"]),
                complete_as_of=row["complete_as_of"] if isinstance(row["complete_as_of"], str) else None,
                records=tuple(FixtureRecord(
                    competition=r["competition"], season=str(r["season"]), club=r["club"], opponent=r["opponent"],
                    opponent_code=r["opponent_code"], kickoff_utc=r["kickoff_utc"], venue=r["venue"],
                    status=r["status"], source=str(r["source"]), fetched_at=str(r["fetched_at"]),
                    gameweek=int(r["gameweek"]) if r["gameweek"] == r["gameweek"] and r["gameweek"] is not None else None)
                    for r in rows),
                postponed=int(row["postponed"] or 0)))
        snapshots.append(_pl_snapshot(season, now.strftime("%Y-%m-%dT%H:%M:%SZ")))
        covered = LICENSED_COVERED
        if europe is not None:
            snapshots.extend(europe["snapshots"])
            covered = (*LICENSED_COVERED, *EUROPE_COVERED)   # one that is missing keeps the calendar incomplete
        value = build_public_calendar(snapshots, now=now, covered=covered)
        # What the board may say about the data: which cups are covered and how complete each is. Cups are
        # best-effort, so "partial"/"missing" means "not confirmed", never "no match".
        states = calendar_status(snapshots, covered, now)
        coverage = {c: v["status"] for c, v in states.items()}
        meta = {"provenance": "licensed_starter", "built_at": manifest.get("built_at"), "coverage": coverage}
        if europe is not None:
            used = {s.competition for s in europe["snapshots"]}
            _mark_europe(value, used)
            meta["provenance"] = "licensed_starter+strikerapi_calendar"
            meta["europe"] = {
                "provenance": "strikerapi_calendar", "built_at": europe["built_at"],
                "competitions": {c: {"status": states[c]["status"], "complete_as_of": states[c]["complete_as_of"]}
                                 for c in EUROPE_COVERED},
                "used": sorted(used),
            }
        _licensed_cache["calendar"] = {"build": key, "at": time.time(), "value": value, "meta": meta}
        return value
    except Exception as exc:  # noqa: BLE001 -- fail-soft by design; log the type only, never a row
        _LOG.info("licensed competition calendar unavailable: %s", type(exc).__name__)
        return None


# -- Europe from StrikerAPI (provenance ``strikerapi_calendar``), behind a flag, default OFF -----------------------
#: With the flag off nothing below runs and every response is byte-identical to before.
ENV_EUROPE_FLAG = "FPL_EUROPE_CALENDAR_STRIKERAPI"
ENV_EUROPE_PATH = "FPL_EUROPE_CALENDAR_PATH"
DEFAULT_EUROPE_PATH = "data/europe-calendar/europe.json"
EUROPE_COVERED = ("UCL", "UEL", "UECL")
#: How often the private R2 object is read again (the job refreshes it a few times a week), and how soon after
#: a failed read.
_EUROPE_R2_TTL_SECONDS = 6 * 3600
_EUROPE_R2_RETRY_SECONDS = 600
_europe_r2: dict[str, Any] = {"next_at": 0.0, "client": None}
#: Held while a refresh runs: at most one at a time, and nobody ever waits for it.
_europe_r2_lock = threading.Lock()


def europe_enabled() -> bool:
    return os.environ.get(ENV_EUROPE_FLAG, "").strip().lower() in ("1", "true", "yes")


def _europe_path() -> Path:
    return Path(os.environ.get(ENV_EUROPE_PATH, "").strip() or DEFAULT_EUROPE_PATH)


def _europe_fetch(season: str) -> bytes:
    """One GET of the private object, on a client with the tier-EO reader's short timeouts and NO retry.

    ``get_object``, not ``download_file``: the transfer manager retries downloads on its own.
    """
    from fpl_tactical.europe_calendar import r2_key

    from . import owned_store_sync as sync
    from . import tier_eo_reader

    if _europe_r2["client"] is None:
        _europe_r2["client"] = tier_eo_reader._make_client(total_attempts=1)
    answer = _europe_r2["client"].get_object(
        Bucket=os.environ.get(sync.ENV_R2_BUCKET, "").strip(), Key=r2_key(tier_eo_reader._r2_prefix(), season))
    return answer["Body"].read()


def _refresh_worker(season: str) -> None:
    """Fetch and swap the local file. Holds ``_europe_r2_lock`` on entry and releases it. Never raises."""
    wait = _EUROPE_R2_RETRY_SECONDS
    try:
        raw = _europe_fetch(season)
        if not isinstance(json.loads(raw), dict):          # never replace a good file with something unreadable
            raise ValueError("not a calendar object")
        path = _europe_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".json.part")
        part.write_bytes(raw)
        os.replace(str(part), str(path))
        wait = _EUROPE_R2_TTL_SECONDS
    except Exception as exc:  # noqa: BLE001 -- no R2, no object, no package, a timeout: keep whatever file there is
        _LOG.info("europe calendar not refreshed: %s", type(exc).__name__)
    finally:
        _europe_r2["next_at"] = time.time() + wait
        _europe_r2_lock.release()


def _refresh_europe_file(season: str) -> "threading.Thread | None":
    """Start a background copy of the private R2 object when one is due. Returns at once, ALWAYS.

    This runs on a user's request, so the request never waits for R2: it serves the file that is there now and
    a later request sees the new one. At most one refresh is in flight. Returns the thread it started, or None.
    """
    if time.time() < _europe_r2["next_at"] or not _europe_r2_lock.acquire(blocking=False):
        return None
    try:
        if time.time() < _europe_r2["next_at"]:              # another request finished one just now
            _europe_r2_lock.release()
            return None
        thread = threading.Thread(target=_refresh_worker, args=(season,), name="europe-calendar-refresh", daemon=True)
        thread.start()
        return thread
    except Exception as exc:  # noqa: BLE001 -- could not even start: free the slot
        _europe_r2_lock.release()
        _LOG.info("europe calendar refresh not started: %s", type(exc).__name__)
        return None


def _europe_season() -> str:
    from fpl_data_core.season_registry import CURRENT_SEASON

    return CURRENT_SEASON


def _europe_layer(now: datetime) -> dict[str, Any] | None:
    """The usable European snapshots, or None (then the calendar is exactly what it is without this source).

    A competition is used only when its stored snapshot is well formed, of the current season and not stale.
    None when the flag is off, there is no file, or no competition is usable. Never raises.
    """
    if not europe_enabled():
        return None
    try:
        from football_intelligence.public_calendar import snapshot_status
        from football_intelligence.strikerapi_calendar import PROVENANCE, SCHEMA_VERSION, snapshot_from_dict

        season = _europe_season()
        _refresh_europe_file(season)
        payload = json.loads(_europe_path().read_text(encoding="utf-8"))
        if (payload.get("schema_version") != SCHEMA_VERSION or payload.get("provenance") != PROVENANCE
                or payload.get("season") != season):
            return None
        fresh = []
        for competition in EUROPE_COVERED:
            try:
                snap = snapshot_from_dict(competition, season, payload["competitions"][competition])
            except Exception as exc:  # noqa: BLE001 -- one bad competition is "missing", not the whole layer
                _LOG.info("europe calendar competition unusable: %s %s", competition, type(exc).__name__)
                continue
            if snapshot_status(snap, now) != "stale":
                fresh.append(snap)
        if not fresh:
            return None
        return {"snapshots": fresh, "built_at": payload.get("built_at"),
                "fingerprint": tuple((s.competition, s.fetched_at, len(s.records), s.complete_as_of) for s in fresh)}
    except Exception as exc:  # noqa: BLE001 -- fail-soft; log the type only, never a row
        _LOG.info("europe calendar unavailable: %s", type(exc).__name__)
        return None


def _mark_europe(calendar: dict[str, list[dict[str, Any]]], competitions: set[str]) -> None:
    """Whole hours between kickoffs, and ``europe_prior`` on a PL match that follows a verified European one.

    The same rule the hand-made layer has: a known kickoff before a Premier League match is a fact (a match the
    calendar is missing could only make the rest SHORTER), so its notice does not wait for a complete
    calendar. ``calendar_complete`` itself is untouched.
    """
    for matches in calendar.values():
        for i, m in enumerate(matches):
            if not i:
                continue
            previous = matches[i - 1]
            m["rest_hours_before"] = int(
                (_parse(m["kickoff_utc"]) - _parse(previous["kickoff_utc"])).total_seconds() // 3600)
            if m["is_pl"] and previous["competition"] in competitions:
                m["europe_prior"] = True


ENV_MANUAL = "FPL_MANUAL_CALENDAR_PATH"
DEFAULT_MANUAL_PATH = "data/calendar-manual/europe_manual.json"
#: Placeholder time of a match whose kickoff is unknown or unverified; ordering only, never shown as a time.
_UNKNOWN_TIME = "T12:00:00Z"
_manual_cache: dict[tuple[str, float], dict[str, Any] | None] = {}
#: Production delivery: the layer's JSON pasted as a Railway variable, written to ``FPL_MANUAL_CALENDAR_PATH`` at start.
ENV_MANUAL_JSON = "FPL_MANUAL_CALENDAR_JSON"
_MANUAL_COMPETITIONS = {"UCL", "UEL", "UECL"}


def _valid_match(m: Any) -> bool:
    if not isinstance(m, dict):
        return False
    try:
        datetime.strptime(m["date"], "%Y-%m-%d")
        if m["kickoff_known"] is True:
            _parse(m["kickoff_utc"])
        elif m["kickoff_known"] is not False:
            return False
        return (m["competition"] in _MANUAL_COMPETITIONS and m["venue"] in ("H", "A")
                and all(isinstance(m[k], str) for k in ("club", "opponent", "opponent_code")))
    except (KeyError, TypeError, ValueError):
        return False


def _valid_layer(layer: Any) -> bool:
    """Every row checked, not just the envelope: one bad row (a typo in a pasted variable) = no layer, never a 500."""
    if not isinstance(layer, dict):
        return False
    try:
        datetime.strptime(layer["list_date"], "%Y-%m-%d")
    except (KeyError, TypeError, ValueError):
        return False
    matches = layer.get("matches")
    return (layer.get("schema_version") == 1 and layer.get("provenance") == "manual_curated"
            and isinstance(matches, list) and all(_valid_match(m) for m in matches))


def _manual_layer() -> dict[str, Any] | None:
    """The hand-compiled European layer (``manual_curated``) or None. Validated; never raises, never logs a row."""
    path = Path(os.environ.get(ENV_MANUAL, "").strip() or DEFAULT_MANUAL_PATH)
    try:
        key = (str(path), path.stat().st_mtime)
        if key not in _manual_cache:
            _manual_cache.clear()
            layer = json.loads(path.read_text(encoding="utf-8"))
            _manual_cache[key] = layer if _valid_layer(layer) else None
        return _manual_cache[key]
    except Exception as exc:  # noqa: BLE001 -- absent or unreadable layer = no layer
        _LOG.info("manual calendar layer unavailable: %s", type(exc).__name__)
        return None


def materialize_manual_layer() -> dict[str, Any]:
    """Startup: ``FPL_MANUAL_CALENDAR_JSON`` -> the file ``_manual_layer`` reads. Never raises; logs counts only.

    Absent variable: nothing is touched (a local file keeps working). Invalid: nothing is written, so production
    (no file on its disk) has no layer, never a wrong one. Returns ``{state, matches, list_date}`` for the caller.
    """
    raw = os.environ.get(ENV_MANUAL_JSON, "").strip()
    status: dict[str, Any] = {"state": "absent", "matches": 0, "list_date": None}
    if raw:
        try:
            layer = json.loads(raw)
            if not _valid_layer(layer):
                raise ValueError("not a manual_curated layer")
            path = Path(os.environ.get(ENV_MANUAL, "").strip() or DEFAULT_MANUAL_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(layer, ensure_ascii=False), encoding="utf-8")
            status = {"state": "written", "matches": len(layer["matches"]), "list_date": layer["list_date"]}
        except Exception as exc:  # noqa: BLE001 -- a bad variable degrades to "no layer"
            status = {"state": f"invalid:{type(exc).__name__}", "matches": 0, "list_date": None}
    _LOG.info("manual calendar layer: state=%s matches=%d list_date=%s",
              status["state"], status["matches"], status["list_date"])
    return status


def _parse(kickoff_utc: str) -> datetime:
    return datetime.strptime(kickoff_utc, "%Y-%m-%dT%H:%M:%SZ")


def _with_manual(calendar: dict[str, list[dict[str, Any]]], layer: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """A copy of ``calendar`` with the manual European matches laid in, rest days recomputed from real hours.

    Only matches with a verified kickoff take part in the rest-day arithmetic; one without (``kickoff_known:
    false``) is added afterwards with no rest fields, so a doubtful hour never produces a number or a notice.
    A Premier League match whose previous match is a verified manual one gets ``europe_prior`` (a known fact, so
    the notice does not wait for a complete calendar: a hole can only hide a *closer* match, never undo this one).
    """
    from football_intelligence.live_trial_calendar import finish_calendar

    manual_ids: set[int] = set()
    per_club: dict[str, list[dict[str, Any]]] = {}
    loose: dict[str, list[dict[str, Any]]] = {}
    for code, ms in calendar.items():
        rows = [{**m, "_kickoff": _parse(m["kickoff_utc"])} for m in ms]
        pl_days = sorted((m["kickoff_utc"][:10], m["gameweek"]) for m in ms if m["is_pl"] and m["gameweek"] is not None)
        for x in layer["matches"]:
            if x["club"] != code:
                continue
            gw = next((g for g in sorted({g for _, g in pl_days})
                       if max(d for d, gg in pl_days if gg == g) >= x["date"]), None)
            row = {"kickoff_utc": x.get("kickoff_utc") if x["kickoff_known"] else x["date"] + _UNKNOWN_TIME,
                   "kickoff_known": bool(x["kickoff_known"]), "week": None, "gameweek": gw,
                   "competition": x["competition"], "is_pl": False, "venue": x["venue"], "opponent": x["opponent"],
                   "opponent_code": x["opponent_code"]}
            if x["kickoff_known"]:
                row["_kickoff"] = _parse(row["kickoff_utc"])
                manual_ids.add(id(row))
                rows.append(row)
            else:
                loose.setdefault(code, []).append({**row, "rest_days_before": None, "rest_whole_days_before": None,
                                                   "rest_days_after": None, "previous_competition": None})
        per_club[code] = rows
    out = finish_calendar(per_club)
    for code, ms in out.items():
        for i, m in enumerate(ms):
            if i:  # whole hours between the two kickoffs: the notice quotes them
                m["rest_hours_before"] = int((_parse(m["kickoff_utc"]) - _parse(ms[i - 1]["kickoff_utc"])).total_seconds() // 3600)
            if m["is_pl"] and i and id(ms[i - 1]) in manual_ids:
                m["europe_prior"] = True
        ms.extend(loose.get(code, ()))
        ms.sort(key=lambda m: m["kickoff_utc"])
    return out


def _manual_without(layer: dict[str, Any], competitions: set[str]) -> dict[str, Any] | None:
    """The hand-made layer minus the competitions another source now covers (never both), or None when empty."""
    matches = [m for m in layer["matches"] if m["competition"] not in competitions]
    if not matches:
        return None
    return {**layer, "matches": matches,
            "competitions": [c for c in layer.get("competitions", []) if c not in competitions]}


def _dev_gate_open() -> bool:
    return os.environ.get(ENV_ALLOW, "").strip() == "1"


def _calendar() -> dict[str, list[dict[str, Any]]] | None:
    """The calendar: the dev trial capture when its gate is open, else the licensed store, else None."""
    if os.environ.get(ENV_ALLOW, "").strip() != "1":
        return _licensed_calendar()
    raw = os.environ.get(ENV_CAPTURE, "").strip()
    path = Path(raw) if raw else None
    if path is None or not path.is_file():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        _cache[key] = build_calendar(json.loads(path.read_text(encoding="utf-8")))
    return _cache[key]


def _in_window(match: dict[str, Any], date_from: str | None, date_to: str | None) -> bool:
    day = match["kickoff_utc"][:10]
    return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)


def _rotates(m: dict[str, Any]) -> bool:
    """The rotation notice rule (see ROTATION_REST_DAYS / ROTATION_AFTER) for one Premier League match."""
    days = m["rest_whole_days_before"]
    # A calendar with a hole (a competition partial, stale or missing: ``calendar_complete`` False, set by the
    # public-data calendar) never warns: missing data is not "no match", and it can hide the match behind the rest days.
    # The trial calendar has no such key and is unaffected.
    if m.get("calendar_complete", True) is False and not m.get("europe_prior"):
        return False
    return days is not None and days <= ROTATION_REST_DAYS and m["previous_competition"] in ROTATION_AFTER


def competitions_response(tier: str, team: str | None, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    calendar = _calendar()
    if calendar is None:
        return {"available": False}
    if tier in DETAIL_TIERS:
        wanted = {code: ms for code, ms in calendar.items() if team is None or code == team.strip().upper()}
        # Premium only: free never gets the notice nor a hint of it. `matches` are the other
        # competitions; `pl_matches` carry the Premier League kickoffs so the board can lay
        # both on one timeline in real date order, each with the whole rest days before it.
        data = _licensed_cache.get("calendar", {}).get("meta") if not _dev_gate_open() else None
        manual = _manual_layer() if data else None  # layered on the licensed calendar only, never on the dev capture
        if manual and data.get("europe"):
            manual = _manual_without(manual, set(data["europe"]["used"]))
        if manual:
            wanted = {c: ms for c, ms in _with_manual(calendar, manual).items() if c in wanted}
        if data and manual:
            data = {**data, "provenance": f"{data['provenance']}+manual_curated", "manual": {
                "provenance": "manual_curated", "list_date": manual["list_date"], "coverage": "partial", "frozen": True,
                "competitions": manual.get("competitions", []), "matches": len(manual["matches"])}}
        return {"available": True, "tier": "premium", **({"data": data} if data else {}), "teams": {
            code: {
                "matches": [
                    {**{k: m[k] for k in ("kickoff_utc", "week", "gameweek", "competition", "venue", "opponent",
                                          "opponent_code", "rest_days_before", "rest_whole_days_before",
                                          "rest_days_after", "previous_competition")},
                     **({"kickoff_known": False} if m.get("kickoff_known") is False else {})}
                    for m in ms if not m["is_pl"] and _in_window(m, date_from, date_to)],
                "pl_matches": [
                    {**{k: m[k] for k in ("kickoff_utc", "week", "gameweek", "venue", "opponent", "opponent_code",
                                          "rest_whole_days_before", "previous_competition")},
                     "rest_hours_before": m.get("rest_hours_before"), "rotation": _rotates(m)}
                    for m in ms if m["is_pl"] and _in_window(m, date_from, date_to)]}
            for code, ms in wanted.items()}}
    # Free/Tribuna: the layer exists and is locked, and that is ALL they are told. No rival,
    # competition, rest or per-week count: nothing about the calendar leaves the server.
    return {"available": True, "tier": "free"}
