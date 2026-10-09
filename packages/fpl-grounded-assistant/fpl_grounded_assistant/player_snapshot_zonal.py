"""
fpl_grounded_assistant.player_snapshot_zonal
============================================
Bloque 10: the zonal profile of a player against the PENDING matches of the
next three gameweeks, composed deterministically inside ``get_player_snapshot``
so «háblame de X» brings the card AND the zonal read in one answer.

Everything here is best-effort enrichment. ``compose_player_zonal`` never
raises and never changes the snapshot's ``status``: any failure, missing
input or invalid zonal datum returns ``zonal=None`` plus an internal reason
(logged, never put in the payload the model sees).

Three decisions worth re-reading before changing anything:

Identity (store player <-> FPL element)
    The Understat store carries a player NAME only -- no id (the ids in
    ``football-identity-registry`` corpus are synthetic and not stable). So
    identity is: normalised full name (first + second name) equal to exactly
    one store name AND exactly one FPL element, with the store team equal to
    the element's CURRENT team. A second method accepts the shared exact
    resolver (``resolve_store_player``: web_name / nickname at rank 0) under
    the same uniqueness and team conditions. The team comparison is a control,
    not proof; a mismatch (a transfer with no reliable link) omits the
    section rather than guess. Prefix/substring matching is never used.

Calendar
    The team is the element's team in the CURRENT bootstrap, never the
    store's historical club. The window starts at the first gameweek in which
    the team has a PENDING match (``started`` false) and covers that
    gameweek plus the next two. In-play and finished matches are excluded;
    a missing/odd flag omits the section. State comes from the explicit
    fixture flags (``started`` / ``finished`` / ``finished_provisional``),
    never from ``kickoff_time``.

Fixture state source
    ``bootstrap["team_fixtures"]`` is assembled once at server start and
    carries only ``finished``, so it cannot tell pending from in-play. State
    is read from ``bootstrap["_gw_fixtures"]`` when present (tests, no
    network) and otherwise from one ``/fixtures/`` request cached 60 s. An
    empty, malformed or failed response is never cached.

``share`` is a 0-1 fraction of the player's non-penalty xG. Converting to a
percentage is the UI's single job.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from fpl_player_registry import normalize_player_name

from .zonal_weakness import (
    ZONES,
    _FPL_TACTICAL_AVAILABLE,
    _load_shots,
    _provenance_for,
    build_player_outlook,
    compute_league_baseline,
    compute_player_zone_shares,
    compute_team_zone_profiles,
    player_zone_list,
)
from .zonal_weakness_tool import (
    _UNDERSTAT_TO_SHORT,
    _live_season,
    _team_to_store_name,
    resolve_store_player,
)

try:  # the path helper only exists when fpl-tactical is importable
    from .zonal_weakness import CURRENT_SEASON, shots_parquet_path
except ImportError:  # pragma: no cover
    CURRENT_SEASON = None  # type: ignore[assignment]
    shots_parquet_path = None  # type: ignore[assignment]

_LOG = logging.getLogger("fpl_grounded_assistant.player_snapshot_zonal")

#: Gameweeks covered by the section, starting at the first with a pending match.
WINDOW_GWS: int = 3
#: Fixture-state cache lifetime and the longest the card waits for the API.
FIXTURES_TTL_S: float = 60.0
FIXTURES_TIMEOUT_S: float = 2.5

_VALID_STATUS = frozenset({"favorable", "neutral", "no_data"})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComposeResult:
    """What ``compose_player_zonal`` decided. ``zonal`` is None when omitted."""
    zonal:  "dict[str, Any] | None"
    reason: str                     # "ok" or the omission reason
    method: "str | None" = None     # identity method that selected the profile
    store_player: "str | None" = None


def _omit(reason: str, method: "str | None" = None) -> ComposeResult:
    return ComposeResult(zonal=None, reason=reason, method=method)


# ---------------------------------------------------------------------------
# Test seams
# ---------------------------------------------------------------------------

#: A DataFrame / parquet path used instead of the owned store (tests only).
_STORE_OVERRIDE: Any = None
#: Replaces the HTTP fetch of all fixtures (tests only). Must return the list.
_FETCH_ALL_FIXTURES: "Callable[[], Any] | None" = None
#: Replaces the clock used by the fixtures cache (tests only).
_MONOTONIC: Callable[[], float] = time.monotonic


# ---------------------------------------------------------------------------
# Fixture state provider
# ---------------------------------------------------------------------------

_fixtures_cache: "dict[str, Any]" = {"at": None, "data": None}


def reset_caches() -> None:
    """Drop every cache in this module (tests)."""
    _fixtures_cache.update(at=None, data=None)
    _store_cache.clear()


def _fetch_all_fixtures_http() -> Any:
    """One short, non-retrying request for every fixture of the season."""
    import requests  # noqa: PLC0415 -- already a dependency of the API client
    from fpl_api_client.fpl_client import ALL_FIXTURES_URL  # noqa: PLC0415

    resp = requests.get(ALL_FIXTURES_URL, timeout=FIXTURES_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _well_formed(data: Any) -> bool:
    """A response worth caching: a non-empty list of fixture dicts."""
    if not isinstance(data, list) or not data:
        return False
    return all(
        isinstance(f, dict) and "team_h" in f and "team_a" in f for f in data
    )


def get_fixture_states(bootstrap: dict[str, Any]) -> "tuple[list[dict[str, Any]] | None, str]":
    """``(fixtures, source)`` or ``(None, reason)``.

    Order: ``bootstrap["_gw_fixtures"]`` (no network) -> 60 s cache -> one
    request. Empty, malformed or failed responses are not cached.
    """
    injected = bootstrap.get("_gw_fixtures")
    if isinstance(injected, dict) and injected:
        flat: list[dict[str, Any]] = []
        for gw_key, rows in injected.items():
            for f in rows or []:
                if isinstance(f, dict):
                    row = dict(f)
                    row.setdefault("event", _to_int(gw_key))
                    flat.append(row)
        if _well_formed(flat):
            return flat, "bootstrap"
        return None, "fixtures_injected_malformed"

    now = _MONOTONIC()
    cached_at, cached = _fixtures_cache["at"], _fixtures_cache["data"]
    if cached is not None and cached_at is not None and now - cached_at < FIXTURES_TTL_S:
        return cached, "cache"

    fetch = _FETCH_ALL_FIXTURES or _fetch_all_fixtures_http
    try:
        data = fetch()
    except Exception:  # noqa: BLE001 -- timeout, DNS, HTTP, bad JSON
        return None, "fixtures_fetch_failed"
    if not _well_formed(data):
        return None, "fixtures_response_invalid"
    _fixtures_cache.update(at=now, data=data)
    return data, "live"


def _to_int(v: Any) -> "int | None":
    try:
        if isinstance(v, bool):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def classify_fixture(f: dict[str, Any]) -> str:
    """``pending`` | ``live`` | ``done`` | ``unknown``, from explicit flags only."""
    started = f.get("started")
    finished = f.get("finished")
    provisional = f.get("finished_provisional")
    if not all(isinstance(x, bool) for x in (started, finished, provisional)):
        return "unknown"
    if finished or provisional:
        return "done"
    if started:
        return "live"
    return "pending"


def pending_window(
    fixtures: list[dict[str, Any]], team_id: int,
) -> "tuple[list[dict[str, Any]] | None, str, tuple[int, int] | None]":
    """The team's pending matches in the 3-gameweek window.

    Returns ``(rows, reason, (gw_from, gw_to))``; ``rows`` is None when the
    section must be omitted (``reason`` says why).
    """
    mine: list[dict[str, Any]] = []
    for f in fixtures:
        if team_id not in (_to_int(f.get("team_h")), _to_int(f.get("team_a"))):
            continue
        gw = _to_int(f.get("event"))
        if gw is None:      # postponed / unscheduled: no gameweek, no invented rival
            continue
        mine.append({**f, "_gw": gw, "_state": classify_fixture(f)})
    if not mine:
        return None, "no_calendar", None
    mine.sort(key=lambda f: (f["_gw"], str(f.get("kickoff_time") or ""), _to_int(f.get("id")) or 0))

    start = next((f["_gw"] for f in mine if f["_state"] == "pending"), None)
    if start is None:
        # nothing pending: either the season is over or a flag is unreadable
        if any(f["_state"] == "unknown" for f in mine):
            return None, "fixture_state_unknown", None
        return None, "no_pending_fixtures", None
    end = start + WINDOW_GWS - 1
    in_window = [f for f in mine if start <= f["_gw"] <= end]
    # An unreadable flag inside the window could be a pending match we would
    # silently drop: omit instead of showing a partial calendar.
    if any(f["_state"] == "unknown" for f in in_window):
        return None, "fixture_state_unknown", None
    # ...and one before the start could mean the "first pending" is wrong.
    if any(f["_state"] == "unknown" for f in mine if f["_gw"] < start):
        return None, "fixture_state_unknown", None
    rows = [f for f in in_window if f["_state"] == "pending"]
    return rows, "ok", (start, end)


# ---------------------------------------------------------------------------
# Store bundle (read once per store version)
# ---------------------------------------------------------------------------

_store_cache: "dict[tuple, dict[str, Any]]" = {}


def _bundle_from_shots(shots: pd.DataFrame) -> dict[str, Any]:
    shares = compute_player_zone_shares(shots)
    profiles = compute_team_zone_profiles(shots)
    index: dict[str, list[str]] = {}
    for name in shares:
        index.setdefault(normalize_player_name(name), []).append(name)
    return {
        "shares": shares,
        "profiles": profiles,
        "baseline": compute_league_baseline(profiles),
        "name_index": index,
    }


def _store_key(store: Any) -> "tuple | None":
    """Cache key tied to the store's bytes (path + mtime + size), or None
    when the store is in memory and must not be cached."""
    if isinstance(store, pd.DataFrame):
        return None
    if store is None:
        if not _FPL_TACTICAL_AVAILABLE or shots_parquet_path is None:
            return None
        path = Path(shots_parquet_path(CURRENT_SEASON))
    else:
        path = Path(store)
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def load_store_bundle(store: Any) -> "dict[str, Any] | None":
    key = _store_key(store)
    if key is not None and key in _store_cache:
        return _store_cache[key]
    shots = _load_shots(store)
    if shots is None:
        return None
    bundle = _bundle_from_shots(shots)
    if key is not None:
        _store_cache.clear()        # one store version at a time
        _store_cache[key] = bundle
    return bundle


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def _full_name(el: dict[str, Any]) -> str:
    return normalize_player_name(
        f"{el.get('first_name') or ''} {el.get('second_name') or ''}".strip()
    )


def _team_short(el: dict[str, Any], teams_by_id: dict[int, dict[str, Any]]) -> str:
    t = teams_by_id.get(_to_int(el.get("team")) or -1) or {}
    return str(t.get("short_name") or "").upper()


def select_store_profile(
    element: dict[str, Any],
    bootstrap: dict[str, Any],
    bundle: dict[str, Any],
) -> "tuple[str | None, str | None, str]":
    """``(store_name, method, reason)``: the one store profile that is this
    element, or ``(None, None, reason)``. Never a guess."""
    shares = bundle["shares"]
    index = bundle["name_index"]
    elements = bootstrap.get("elements") or []
    teams_by_id = {
        int(t["id"]): t for t in bootstrap.get("teams", []) if t.get("id") is not None
    }
    current_short = _team_short(element, teams_by_id)
    if not current_short:
        return None, None, "team_unknown"

    def team_ok(store_name: str) -> bool:
        # _UNDERSTAT_TO_SHORT is keyed by the lower-cased store team title.
        store_team = str(shares[store_name]["team"]).lower()
        return _UNDERSTAT_TO_SHORT.get(store_team, "").upper() == current_short

    full = _full_name(element)
    if full:
        homonyms = [e for e in elements if _full_name(e) == full]
        cands = index.get(full, [])
        if len(cands) > 1:
            return None, None, "store_name_collision"
        if len(cands) == 1:
            if len(homonyms) > 1:
                return None, None, "bootstrap_name_collision"
            if not team_ok(cands[0]):
                return None, "full_name", "team_mismatch"
            return cands[0], "full_name_team_match", "ok"

    # Second method: the shared exact resolver. Pre-filter by a shared token so
    # we resolve a handful of names, not the whole store.
    tokens = {
        tok
        for field in ("web_name", "second_name")
        for tok in normalize_player_name(element.get(field) or "").split()
        if len(tok) >= 3
    }
    pool = [
        name for name in shares
        if tokens & set(normalize_player_name(name).split())
    ]
    resolved = [
        name for name in pool
        if (r := resolve_store_player(name, bootstrap)) is not None
        and r.get("id") == element.get("id")
    ]
    if len(resolved) > 1:
        return None, None, "store_candidates_multiple"
    if len(resolved) == 1:
        if not team_ok(resolved[0]):
            return None, "resolver_exact", "team_mismatch"
        return resolved[0], "resolver_exact_team_match", "ok"
    return None, None, "no_store_profile"


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def _valid_zonal(zonal: dict[str, Any]) -> bool:
    try:
        zones = zonal["zones"]
        if not zones:
            return False
        for z in zones:
            s = z["share"]
            if z["zone"] not in ZONES or isinstance(s, bool) or not math.isfinite(s) or not 0.0 <= s <= 1.0:
                return False
        if not zonal["fixtures"]:
            return False
        for fx in zonal["fixtures"]:
            if fx["status"] not in _VALID_STATUS:
                return False
            for m in fx["matches"]:
                if not 0.0 <= m["player_share"] <= 1.0 or not math.isfinite(m["delta_vs_avg"]):
                    return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _verdict(web_name: str, fixtures: list[dict[str, Any]]) -> "tuple[str, str]":
    favorable = [f for f in fixtures if f["status"] == "favorable"]
    if favorable:
        gws = " y ".join(f"J{f['gameweek']} ({f['opponent']})" for f in favorable)
        return "favorable", (
            f"{web_name} genera su xG justo en zonas donde el rival concede por "
            f"encima de la media — cruce favorable en {gws}."
        )
    if all(f["status"] == "no_data" for f in fixtures):
        return "no_data", (
            "Sin datos zonales de los rivales de estos partidos, "
            "no se puede valorar el cruce."
        )
    return "neutral", (
        f"Sin cruce zonal destacado para {web_name} en los partidos de las "
        "próximas 3 jornadas."
    )


def _compose(
    element: dict[str, Any], bootstrap: dict[str, Any],
) -> ComposeResult:
    store = _STORE_OVERRIDE
    bundle = load_store_bundle(store)
    if bundle is None:
        return _omit("store_unavailable")

    name, method, reason = select_store_profile(element, bootstrap, bundle)
    if name is None:
        return _omit(reason, method)

    info = bundle["shares"][name]
    zones = player_zone_list(info)
    if not zones:
        return _omit("no_zone_over_threshold", method)

    fixtures_all, src = get_fixture_states(bootstrap)
    if fixtures_all is None:
        return _omit(src, method)

    teams_by_id = {
        int(t["id"]): t for t in bootstrap.get("teams", []) if t.get("id") is not None
    }
    team_id = _to_int(element.get("team"))
    if team_id is None or team_id not in teams_by_id:
        return _omit("team_unknown", method)

    rows, why, window = pending_window(fixtures_all, team_id)
    if rows is None or window is None:
        return _omit(why, method)
    if not rows:
        return _omit("no_pending_fixtures", method)

    engine_fixtures: list[dict[str, Any]] = []
    for f in rows:
        home = _to_int(f.get("team_h")) == team_id
        opp = teams_by_id.get(_to_int(f.get("team_a" if home else "team_h")) or -1)
        if opp is None:
            return _omit("opponent_unknown", method)
        engine_fixtures.append({
            "gameweek": f["_gw"],
            "opponent": _team_to_store_name(opp),
            "is_home": home,
        })

    provenance = _provenance_for(store, _live_season(bootstrap))
    outlook = build_player_outlook(
        name, info, engine_fixtures, bundle["profiles"], bundle["baseline"], provenance,
    )

    out_fixtures: list[dict[str, Any]] = []
    for f, entry in zip(rows, outlook["outlook"]):
        home = entry["is_home"]
        opp = teams_by_id[_to_int(f.get("team_a" if home else "team_h"))]
        out_fixtures.append({
            "gameweek": entry["gameweek"],
            "fixture_id": _to_int(f.get("id")),
            "opponent": str(opp.get("name") or opp.get("short_name") or ""),
            "opponent_short": str(opp.get("short_name") or ""),
            "is_home": home,
            "status": entry["status"],
            "matches": entry["matches"],
        })
    kind, verdict = _verdict(str(element.get("web_name") or name), out_fixtures)
    zonal = {
        "zones": zones,
        "window": {"gw_from": window[0], "gw_to": window[1]},
        "fixtures": out_fixtures,
        "verdict_kind": kind,
        "verdict": verdict,
        "data_provenance": provenance,
    }
    if not _valid_zonal(zonal):
        return _omit("invalid_zonal_payload", method)
    return ComposeResult(zonal=zonal, reason="ok", method=method, store_player=name)


def compose_player_zonal(
    element: dict[str, Any], bootstrap: dict[str, Any],
) -> ComposeResult:
    """Never raises. Logs one structured line per call (internal diagnosis)."""
    t0 = time.monotonic()
    try:
        result = _compose(element, bootstrap)
    except Exception as exc:  # noqa: BLE001 -- enrichment must not break the card
        result = _omit(f"exception:{type(exc).__name__}")
    try:
        _LOG.info(
            "player_zonal %s",
            json.dumps({
                "event": "player_zonal_composition",
                "element_id": element.get("id"),
                "included": result.zonal is not None,
                "reason": result.reason,
                "method": result.method,
                "ms": round((time.monotonic() - t0) * 1000, 1),
            }),
        )
    except Exception:  # noqa: BLE001
        pass
    return result
