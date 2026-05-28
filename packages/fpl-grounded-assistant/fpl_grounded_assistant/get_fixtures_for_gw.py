"""
fpl_grounded_assistant.get_fixtures_for_gw
==========================================
P2.4: Atomic get_fixtures_for_gw tool — all fixtures for a specific gameweek
with FDR (Fixture Difficulty Rating) per team.

Addresses the failed query class: "dame el calendario de partidos para la
fecha 38" / "show me fixtures for gameweek 12".

Fetch path
----------
Uses ``get_fixtures()`` from ``fpl_api_client.fpl_client`` — the existing
GW-scoped fixture endpoint (``/api/fixtures/?event=<gw>``).

Test-injection path
-------------------
Pass a pre-fetched list as the ``fixtures`` argument, or embed in the
bootstrap under ``_gw_fixtures``:

    bootstrap["_gw_fixtures"] = {
        "38": [{"id": 1, "team_h": 1, "team_a": 2, ...}]
    }

When ``fixtures`` is supplied directly it takes precedence over everything.
When ``_gw_fixtures`` is present in bootstrap, the live API is not called.

FDR resolution
--------------
Each FPL fixture carries ``team_h_difficulty`` and ``team_a_difficulty``
fields — these are used directly as the per-team FDR (1–5 scale), exactly as
returned by the FPL API.  The bootstrap's team strength values are only a
fallback if the fixture fields are missing.

Caching
-------
An in-process dict keyed by ``gw_number`` caches raw fixture lists.
Past-GW data is stable; future GWs may shift (kickoff_time).  The cache is
read-only after population — never mutated in place.

Registration
------------
Registers ``get_fixtures_for_gw`` in ``TOOL_REGISTRY`` as a side-effect of
import.  ``__init__.py`` imports this module so
``run_tool("get_fixtures_for_gw", ...)`` works.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fpl_api_client.fpl_client import get_fixtures
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

# Owned-store fallback (deferred-safe per CONTRACT §11.3 — mirrors fpl_server.py)
try:
    from fpl_grounded_assistant.owned_store_fallback import (  # noqa: E402
        load_fixtures_for_gw_from_owned_store,
        OwnedStoreUnavailable,
    )
except ImportError:
    load_fixtures_for_gw_from_owned_store = None  # type: ignore[assignment]
    OwnedStoreUnavailable = None                  # type: ignore[assignment,misc]

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Valid GW range (standard Premier League season).
_GW_MIN: int = 1
_GW_MAX: int = 38

#: Simple per-process fixture cache: {gw_number: list[fixture_dict]}.
#: Read-only after initial population.
_fixture_cache: dict[int, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Internal fetch helper
# ---------------------------------------------------------------------------

def _fetch_fixtures_for_gw(
    gw_number: int,
    bootstrap: "dict[str, Any] | None",
    fixtures_override: "list[dict[str, Any]] | None",
) -> "list[dict[str, Any]] | None":
    """Return raw fixture list for *gw_number*.

    Resolution order
    ----------------
    1. ``fixtures_override`` — caller-supplied (test injection); instant.
    2. ``bootstrap["_gw_fixtures"][str(gw_number)]`` — bootstrap injection; instant.
    3. In-process cache hit — instant.
    4. Live API via ``get_fixtures(gw_number)`` — network call.

    Returns ``None`` on fetch failure.
    """
    # 0. H4d: operator-only force-fallback switch.  Shared flag with the
    # element-summary tool: when FPL_FORCE_FALLBACK_TOOLS is truthy
    # (1/true/yes) we skip the live get_fixtures() call (and the override
    # / bootstrap / cache short-circuits) and jump straight to the
    # owned-store fallback.  Intended for smoke-testing only.
    _force_flag = os.environ.get("FPL_FORCE_FALLBACK_TOOLS", "").strip().lower()
    if _force_flag in {"1", "true", "yes"}:
        if load_fixtures_for_gw_from_owned_store is None:
            return None
        try:
            fb_fixtures, provenance = load_fixtures_for_gw_from_owned_store(gw_number)
        except Exception:  # noqa: BLE001
            return None
        _LOG.warning(
            "fixtures_fallback %s",
            json.dumps({
                "event":             "fixtures_forced_fallback",
                "env_var":           "FPL_FORCE_FALLBACK_TOOLS",
                "gw_number":         gw_number,
                "merged_at":         provenance.merged_at,
                "staleness_hours":   provenance.staleness_hours,
                "incremental_count": provenance.incremental_count,
            }),
        )
        # NOTE: do NOT cache forced-fallback results (mirrors non-forced path).
        return list(fb_fixtures)

    # 1. Direct override (test injection via function param).
    if fixtures_override is not None:
        return list(fixtures_override)

    # 2. Bootstrap injection path.
    if bootstrap is not None:
        injected = bootstrap.get("_gw_fixtures", {})
        key = str(gw_number)
        if key in injected:
            return list(injected[key])

    # 3. In-process cache.
    if gw_number in _fixture_cache:
        return list(_fixture_cache[gw_number])

    # 4. Live API.
    live_ok = False
    raw_live: "list[dict[str, Any]] | None" = None
    try:
        raw = get_fixtures(gw_number)
        if isinstance(raw, list):
            raw_live = list(raw)
            live_ok = True
    except Exception:  # noqa: BLE001
        live_ok = False

    if live_ok and raw_live is not None:
        # Cache before returning (read-only copy stored).
        _fixture_cache[gw_number] = list(raw_live)
        return list(raw_live)

    # 5. Owned-store fallback (CONTRACT §11.3 — H4b Seam 2).
    # Skip entirely if the helper failed to import.
    if load_fixtures_for_gw_from_owned_store is None:
        return None

    try:
        fb_fixtures, provenance = load_fixtures_for_gw_from_owned_store(gw_number)
    except Exception as fallback_exc:  # noqa: BLE001
        if OwnedStoreUnavailable is not None and isinstance(
            fallback_exc, OwnedStoreUnavailable
        ):
            return None
        # Unexpected fallback error — log and return None (live already failed).
        _LOG.error(
            "fixtures_fallback %s",
            json.dumps({
                "event":     "fixtures_owned_store_error",
                "gw_number": gw_number,
                "error":     str(fallback_exc),
            }),
        )
        return None

    _LOG.warning(
        "fixtures_fallback %s",
        json.dumps({
            "event":             "fixtures_owned_store_fallback",
            "gw_number":         gw_number,
            "merged_at":         provenance.merged_at,
            "staleness_hours":   provenance.staleness_hours,
            "incremental_count": provenance.incremental_count,
        }),
    )
    # NOTE: do NOT cache fallback results — they may be stale and live may recover.
    return list(fb_fixtures)


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def _build_short_map(bootstrap: "dict[str, Any]") -> dict[int, str]:
    """Return {team_id: short_name} from bootstrap."""
    return {
        int(t["id"]): str(t.get("short_name", f"T{t['id']}"))
        for t in bootstrap.get("teams", [])
    }


def _build_all_team_ids(bootstrap: "dict[str, Any]") -> set[int]:
    """Return the full set of team ids from bootstrap."""
    return {int(t["id"]) for t in bootstrap.get("teams", [])}


# ---------------------------------------------------------------------------
# Fixture field extraction
# ---------------------------------------------------------------------------

def _extract_fixture(
    fix: dict[str, Any],
    short_map: dict[int, str],
) -> dict[str, Any]:
    """Build the public fixture dict from a raw FPL fixture record.

    FDR source priority:
        1. ``team_h_difficulty`` / ``team_a_difficulty`` on the fixture itself.
        2. Fallback to 3 (average difficulty) when fields are absent.
    """
    home_id  = int(fix.get("team_h", 0))
    away_id  = int(fix.get("team_a", 0))
    home_fdr = int(fix.get("team_h_difficulty") or 3)
    away_fdr = int(fix.get("team_a_difficulty") or 3)

    home_score: "int | None" = fix.get("team_h_score")
    away_score: "int | None" = fix.get("team_a_score")
    if home_score is not None:
        home_score = int(home_score)
    if away_score is not None:
        away_score = int(away_score)

    minutes: "int | None" = fix.get("minutes")
    if minutes is not None:
        minutes = int(minutes)

    return {
        "id":              int(fix.get("id", 0)),
        "kickoff_time":    fix.get("kickoff_time"),
        "home_team_short": short_map.get(home_id, f"T{home_id}"),
        "away_team_short": short_map.get(away_id, f"T{away_id}"),
        "home_fdr":        home_fdr,
        "away_fdr":        away_fdr,
        "finished":        bool(fix.get("finished", False)),
        "home_score":      home_score,
        "away_score":      away_score,
        "minutes":         minutes,
    }


# ---------------------------------------------------------------------------
# Blank/double GW detection
# ---------------------------------------------------------------------------

def _compute_team_fixture_counts(
    fixtures: list[dict[str, Any]],
) -> dict[str, int]:
    """Return {team_short: count} for teams appearing in the fixture list."""
    counts: dict[str, int] = {}
    for fix in fixtures:
        for key in ("home_team_short", "away_team_short"):
            short = fix[key]
            counts[short] = counts.get(short, 0) + 1
    return counts


def _build_summary(
    fixtures: list[dict[str, Any]],
    all_team_shorts: set[str],
) -> dict[str, Any]:
    """Build the summary block from the extracted fixture list.

    Parameters
    ----------
    fixtures:
        Already-extracted fixture dicts (with home_team_short, away_team_short,
        home_fdr, away_fdr, id).
    all_team_shorts:
        Full set of team shorts from bootstrap — used to identify blank_gw_teams.
    """
    counts = _compute_team_fixture_counts(fixtures)
    playing_teams = set(counts.keys())

    double_gw_teams = sorted(t for t, c in counts.items() if c > 1)
    blank_gw_teams  = sorted(all_team_shorts - playing_teams)

    total = len(fixtures)

    # Easiest/hardest for home team: tiebreak by fixture id (lower first).
    easiest_home = ""
    hardest_home = ""
    if fixtures:
        sorted_by_home_fdr = sorted(fixtures, key=lambda f: (f["home_fdr"], f["id"]))
        easiest_home = sorted_by_home_fdr[0]["home_team_short"]
        sorted_by_home_fdr_desc = sorted(fixtures, key=lambda f: (-f["home_fdr"], f["id"]))
        hardest_home = sorted_by_home_fdr_desc[0]["home_team_short"]

    return {
        "total_fixtures":          total,
        "easiest_for_home_team":   easiest_home,
        "hardest_for_home_team":   hardest_home,
        "double_gw_teams":         double_gw_teams,
        "blank_gw_teams":          blank_gw_teams,
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_fixtures_for_gw(
    gw_number: int,
    bootstrap: "dict[str, Any] | None" = None,
    fixtures: "list[dict[str, Any]] | None" = None,
) -> dict[str, Any]:
    """All fixtures for a specific gameweek with FDR.

    Args:
        gw_number: 1-38 (or whatever the current season's GW range is).
                   Out of range → status="invalid_argument".
        bootstrap: live FPL bootstrap (for team names, FDR data).
        fixtures: optional pre-fetched fixtures list (for test injection).

    Returns one of:
        # GW has fixtures (the normal case):
        {
            "status": "ok",
            "gw": <int>,
            "is_blank": <bool>,         # true if no fixtures in this GW
            "is_double": <bool>,        # true if >=1 team plays >1 fixture
            "finished": <bool>,         # all fixtures finished?
            "fixtures": [
                {
                    "id": <int>,
                    "kickoff_time": <str | None>,
                    "home_team_short": <str>,
                    "away_team_short": <str>,
                    "home_fdr": <int>,
                    "away_fdr": <int>,
                    "finished": <bool>,
                    "home_score": <int | None>,
                    "away_score": <int | None>,
                    "minutes": <int | None>
                },
                ...
            ],
            "summary": {
                "total_fixtures": <int>,
                "easiest_for_home_team": <str>,
                "hardest_for_home_team": <str>,
                "double_gw_teams": <list[str]>,
                "blank_gw_teams": <list[str]>
            }
        }
        # GW out of range:
        {
            "status": "invalid_argument",
            "code": "out_of_range",
            "message": "Gameweek <N> is out of range (valid: 1-38)."
        }
        # FPL API fetch failed:
        {
            "status": "error",
            "code": "fetch_failed",
            "message": "Could not fetch fixtures: <reason>"
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate range
    # ------------------------------------------------------------------
    try:
        gw_number = int(gw_number)
    except (ValueError, TypeError):
        return {
            "status":  "invalid_argument",
            "code":    "out_of_range",
            "message": f"Gameweek must be an integer in range {_GW_MIN}-{_GW_MAX}.",
        }

    if not (_GW_MIN <= gw_number <= _GW_MAX):
        return {
            "status":  "invalid_argument",
            "code":    "out_of_range",
            "message": f"Gameweek {gw_number} is out of range (valid: {_GW_MIN}-{_GW_MAX}).",
        }

    # ------------------------------------------------------------------
    # 1. Bootstrap guard — we need teams for short_names and blank_gw_teams
    # ------------------------------------------------------------------
    if bootstrap is None:
        # No bootstrap → can still attempt fetch but team names will be generic.
        short_map       = {}
        all_team_shorts = set()
    else:
        short_map       = _build_short_map(bootstrap)
        all_team_shorts = {v for v in short_map.values()}

    # ------------------------------------------------------------------
    # 2. Fetch fixture data
    # ------------------------------------------------------------------
    raw_fixtures = _fetch_fixtures_for_gw(gw_number, bootstrap, fixtures)

    if raw_fixtures is None:
        return {
            "status":  "error",
            "code":    "fetch_failed",
            "message": f"Could not fetch fixtures: API call for GW{gw_number} failed or timed out.",
        }

    # ------------------------------------------------------------------
    # 3. Extract fixture dicts
    # ------------------------------------------------------------------
    extracted = [_extract_fixture(f, short_map) for f in raw_fixtures]

    # ------------------------------------------------------------------
    # 4. Compute is_blank / is_double / finished
    # ------------------------------------------------------------------
    is_blank  = len(extracted) == 0
    is_double = False
    if not is_blank:
        counts    = _compute_team_fixture_counts(extracted)
        is_double = any(c > 1 for c in counts.values())

    all_finished = bool(extracted) and all(f["finished"] for f in extracted)

    # ------------------------------------------------------------------
    # 5. Build summary
    # ------------------------------------------------------------------
    summary = _build_summary(extracted, all_team_shorts)

    return {
        "status":   "ok",
        "gw":       gw_number,
        "is_blank": is_blank,
        "is_double": is_double,
        "finished": all_finished,
        "fixtures": extracted,
        "summary":  summary,
    }


# ---------------------------------------------------------------------------
# Cache utility (test helper)
# ---------------------------------------------------------------------------

def _clear_fixture_cache() -> None:
    """Clear the in-process fixture cache (test helper)."""
    _fixture_cache.clear()


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_FIXTURES_FOR_GW_SPEC = ToolSpec(
    name="get_fixtures_for_gw",
    description=(
        "All fixtures for a GW with FDR per team. Returns fixture list (kickoff, teams, FDR, "
        "scores) + summary (totals, easiest/hardest, DGW+BGW teams). "
        "status=invalid_argument on out-of-range gw_number."
    ),
    parameters={
        "type": "object",
        "properties": {
            "gw_number": {
                "type":        "integer",
                "description": "Gameweek number (1-38)",
                "minimum":     1,
                "maximum":     38,
            },
        },
        "required":             ["gw_number"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":   {"type": "string"},
            "gw":       {"type": "integer"},
            "is_blank": {"type": "boolean"},
            "is_double": {"type": "boolean"},
            "finished": {"type": "boolean"},
            "fixtures": {"type": "array"},
            "summary":  {"type": "object"},
        },
    },
)


def _get_fixtures_for_gw_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_fixtures_for_gw()``."""
    try:
        gw = args.get("gw_number")
        if gw is None:
            return {
                "status":  "invalid_argument",
                "code":    "missing_gw_number",
                "message": "gw_number is required.",
            }
        return get_fixtures_for_gw(
            gw_number=gw,
            bootstrap=bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_fixtures_for_gw raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_fixtures_for_gw", ...) works.
TOOL_REGISTRY.register(GET_FIXTURES_FOR_GW_SPEC, _get_fixtures_for_gw_handler)
