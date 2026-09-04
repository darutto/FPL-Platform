"""
fpl_pipeline.context
====================
Phase 2e: Deterministic context assembly pipeline.

Assembles the full context required by the FPL captain tool path in a
single call, eliminating the multi-step setup burden from callers.

Design principles
-----------------
* All outputs are deterministic and inspectable.
* Every network-calling step is injectable (``bootstrap``, ``fixtures`` and
  ``all_fixtures`` parameters) so the function is fully testable without
  network access.
* The returned dict is self-documenting via the ``meta`` sub-dict.
* The returned ``bootstrap`` has ``fixture_difficulty_map`` and
    ``team_fixtures`` pre-injected so it can be passed directly to
    ``harness.ask()`` without further setup.

Network calls made (when not injected)
---------------------------------------
1. ``get_bootstrap()``          — if ``bootstrap`` is None
2. ``get_fixtures(gameweek)``   — if ``fixtures`` is None AND gameweek is not None

FDR canonical rule
------------------
FDR = opponent team's ``strength`` (1–5 scale from bootstrap teams).
Source: captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty

Blank-gameweek handling
-----------------------
Teams with no fixture in the resolved GW are absent from ``fixture_difficulty_map``.
They appear in ``meta["blank_gw_teams"]`` as a sorted list of team IDs.
The tool-contract layer will return a ``missing_argument`` error for these
teams unless the caller provides an explicit ``fixture_difficulty`` override.

Fixture-run support
-------------------
The assembled bootstrap also carries ``team_fixtures`` — per-team upcoming
fixture schedules built from the live fixtures endpoint from the resolved
gameweek onward. This supports ``player_fixture_run`` through the same live
bootstrap path used by CLI, REPL, and HTTP callers.
"""

from __future__ import annotations

import datetime
from typing import Any

from fpl_api_client import (
    get_bootstrap,
    get_current_gameweek,
    get_fixture_difficulty_map,
    get_fixtures,
    get_teams,
)
from fpl_api_client.fpl_client import get_all_fixtures


def _inject_walk_forward_team_strength(
    bootstrap: dict[str, Any],
    all_fixtures: list[dict[str, Any]] | None = None,
) -> bool:
    """Populate team strengths from completed real fixtures, fail-soft.

    ``fpl-pipeline`` remains usable as a standalone package: the historical
    model is an optional sibling dependency.  In the production server it is
    on ``sys.path`` and the resulting values are injected before fixture maps
    or any assistant tool receives this bootstrap.
    """
    try:
        from fpl_historical.rolling_strength import inject_rolling_strength

        fixtures = all_fixtures if all_fixtures is not None else get_all_fixtures()
        return inject_rolling_strength(bootstrap, fixtures)
    except Exception:  # The live bootstrap is still a valid fallback.
        return False


def _remaining_gameweeks(bootstrap: dict[str, Any], start_gw: int) -> list[int]:
    """Return sorted event ids from *start_gw* onward.

    Uses the bootstrap ``events`` list and keeps the current as well as future
    gameweeks. Finished past gameweeks are excluded.
    """
    remaining: list[int] = []
    for event in bootstrap.get("events", []):
        event_id = event.get("id")
        if event_id is None:
            continue
        gw = int(event_id)
        if gw < start_gw:
            continue
        if event.get("finished"):
            continue
        remaining.append(gw)
    if start_gw not in remaining:
        remaining.insert(0, start_gw)
    return sorted(set(remaining))


def _build_team_fixtures(
    fixture_batches: dict[int, list[dict[str, Any]]],
    bootstrap: dict[str, Any],
    *,
    official_fixture_context_complete: bool = False,
) -> dict[int, list[dict[str, Any]]]:
    """Build ``team_fixtures`` from partial or season-wide fixture batches.

    Alongside the schedule fields, retain completion, kickoff and actual
    minutes so the scoring layer can derive a trustworthy denominator. The
    completeness marker is true only for an injected official all-fixtures
    response, never for a partial per-GW batch.
    """
    # team.get("strength", 3) only falls back when the key is absent — the
    # FPL API can (and does, e.g. before a new season's ratings are published)
    # return the key present with an explicit `null`, which .get()'s default
    # doesn't catch and int(None) then raises. Guard the None case explicitly.
    strength_by_id: dict[int, int] = {
        int(team["id"]): int(team["strength"]) if team.get("strength") is not None else 3
        for team in bootstrap.get("teams", [])
    }
    team_fixtures: dict[int, list[dict[str, Any]]] = {}

    for fallback_gw, fixtures in fixture_batches.items():
        for fixture in fixtures:
            home_id = fixture.get("team_h")
            away_id = fixture.get("team_a")
            if home_id is None or away_id is None:
                continue

            gameweek_raw = fixture.get("event", fallback_gw)
            if gameweek_raw is None:
                continue
            gameweek = int(gameweek_raw)

            home_id = int(home_id)
            away_id = int(away_id)
            home_diff = int(fixture.get("team_h_difficulty", strength_by_id.get(away_id, 3)))
            away_diff = int(fixture.get("team_a_difficulty", strength_by_id.get(home_id, 3)))

            shared_context = {
                "finished": fixture.get("finished") is True,
                "kickoff_time": fixture.get("kickoff_time"),
                "minutes": fixture.get("minutes"),
                "official_fixture_context_complete": official_fixture_context_complete,
            }
            team_fixtures.setdefault(home_id, []).append({
                "gameweek": gameweek,
                "opponent_team": away_id,
                "is_home": True,
                "difficulty": home_diff,
                **shared_context,
            })
            team_fixtures.setdefault(away_id, []).append({
                "gameweek": gameweek,
                "opponent_team": home_id,
                "is_home": False,
                "difficulty": away_diff,
                **shared_context,
            })

    for fixture_list in team_fixtures.values():
        fixture_list.sort(key=lambda fx: (int(fx["gameweek"]), int(fx["opponent_team"])))

    return team_fixtures


def assemble_captain_context(
    gameweek: int | None = None,
    *,
    bootstrap: dict[str, Any] | None = None,
    fixtures: list[dict[str, Any]] | None = None,
    all_fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the full context required by the captain tool path.

    Parameters
    ----------
    gameweek : int | None
        Gameweek number to assemble for.  When ``None`` the current (or
        next) active GW is resolved from the bootstrap ``events`` array.
        Pass an explicit integer to override (e.g. for testing or future-GW
        previews).
    bootstrap : dict | None
        Pre-fetched FPL bootstrap dict (e.g. from a prior call to
        ``fpl_api_client.get_bootstrap()``).  When ``None``, a live
        bootstrap fetch is performed.  Passing a pre-fetched bootstrap
        avoids a redundant network call when the caller already holds one.
    fixtures : list[dict] | None
        Pre-fetched fixture list for the resolved GW.  When ``None`` and a
        GW is available, ``fpl_api_client.get_fixtures(gameweek)`` is called.
        Pass a list (including an empty list ``[]``) to skip the live fetch.
    all_fixtures : list[dict] | None
        Complete official season fixture list used for the historical minutes
        denominator. It is fetched only alongside a live bootstrap. With an
        injected bootstrap, omitting it activates explicit status-only
        degradation and never triggers a hidden network request.

    Returns
    -------
    dict with the following keys:

    ``bootstrap``
        The FPL bootstrap dict with ``fixture_difficulty_map`` and
        ``team_fixtures`` injected. Pass this directly to ``harness.ask()``
        — no further setup needed.

    ``gameweek``
        Resolved gameweek number (``int``) or ``None`` if the season has
        not started or has ended and no explicit GW was supplied.

    ``fixtures``
        Raw fixture list for the resolved GW (list of dicts).  Empty list
        when gameweek is ``None`` or no fixtures were found.

    ``fixture_difficulty_map``
        ``{team_id: fdr}`` for every team appearing in ``fixtures``.
        ``fdr`` is an integer 1–5 (opponent team strength).  Teams with a
        blank gameweek are absent from this dict.

    ``meta``
        Inspectable assembly metadata::

            {
                "gw_resolved_via":  str,        # "bootstrap" | "explicit" | "none"
                "fixture_count":    int,        # number of fixtures found
                "team_count":       int,        # number of teams in bootstrap
                "blank_gw_teams":   list[int],  # team IDs with no fixture this GW
                "assembled_at":     str,        # UTC ISO-8601 timestamp
            }

    Examples
    --------
    Typical usage::

        from fpl_pipeline import assemble_captain_context
        from fpl_grounded_assistant import ask

        ctx    = assemble_captain_context()
        result = ask("captain score for Haaland", ctx["bootstrap"])

    With explicit override (e.g. blank-GW team)::

        ctx    = assemble_captain_context()
        result = ask(
            "captain score for De Gea",
            ctx["bootstrap"],
            candidate_inputs={"fixture_difficulty": 2},
        )

    Test usage (no network)::

        ctx = assemble_captain_context(
            gameweek=28,
            bootstrap=MOCK_BOOTSTRAP,
            fixtures=MOCK_FIXTURES,
        )
    """
    # ------------------------------------------------------------------
    # 1. Bootstrap
    # ------------------------------------------------------------------
    bootstrap_was_fetched = bootstrap is None
    if bootstrap_was_fetched:
        bootstrap = get_bootstrap()

    # Reweight from final real results before any consumer receives the
    # bootstrap.  Explicitly supplied bootstraps stay fully deterministic and
    # never trigger an additional all-fixtures network request.
    if bootstrap_was_fetched and all_fixtures is None:
        try:
            fetched_all_fixtures = get_all_fixtures()
            all_fixtures = (
                fetched_all_fixtures
                if isinstance(fetched_all_fixtures, list)
                else None
            )
        except (OSError, TypeError, ValueError):
            all_fixtures = None
    if bootstrap_was_fetched:
        _inject_walk_forward_team_strength(bootstrap, all_fixtures)

    # ------------------------------------------------------------------
    # 2. Gameweek resolution
    # ------------------------------------------------------------------
    if gameweek is not None:
        gw: int | None = gameweek
        gw_resolved_via = "explicit"
    else:
        gw = get_current_gameweek(bootstrap)
        gw_resolved_via = "bootstrap" if gw is not None else "none"

    # ------------------------------------------------------------------
    # 3. Fixtures
    # ------------------------------------------------------------------
    fixture_batches: dict[int, list[dict[str, Any]]] = {}
    if fixtures is None:
        fetched_fixtures: list[dict[str, Any]] = []
        if gw is not None:
            fetched_fixtures = get_fixtures(gw)
            fixture_batches[gw] = fetched_fixtures

            for future_gw in _remaining_gameweeks(bootstrap, gw):
                if future_gw == gw:
                    continue
                fixture_batches[future_gw] = get_fixtures(future_gw)
    else:
        fetched_fixtures = fixtures
        if gw is not None:
            fixture_batches[gw] = fetched_fixtures

    # ------------------------------------------------------------------
    # 4. Fixture difficulty map  (pure computation — no network)
    # ------------------------------------------------------------------
    fdr_map: dict[int, int] = {}
    if fetched_fixtures:
        fdr_map = get_fixture_difficulty_map(fetched_fixtures, bootstrap)

    # ------------------------------------------------------------------
    # 5. Blank-GW team detection
    # ------------------------------------------------------------------
    teams = get_teams(bootstrap)
    all_team_ids: set[int] = {t["id"] for t in teams}
    fdr_team_ids: set[int] = set(fdr_map.keys())
    blank_gw_teams: list[int] = sorted(all_team_ids - fdr_team_ids)

    # ------------------------------------------------------------------
    # 6. Inject map into bootstrap  (in-place; caller's copy is updated)
    # ------------------------------------------------------------------
    bootstrap["fixture_difficulty_map"] = fdr_map
    team_fixture_batches = (
        {0: all_fixtures} if all_fixtures is not None else fixture_batches
    )
    bootstrap["team_fixtures"] = _build_team_fixtures(
        team_fixture_batches,
        bootstrap,
        official_fixture_context_complete=all_fixtures is not None,
    )

    # ------------------------------------------------------------------
    # 7. Build meta
    # ------------------------------------------------------------------
    meta: dict[str, Any] = {
        "gw_resolved_via": gw_resolved_via,
        "fixture_count":   len(fetched_fixtures),
        "team_count":      len(teams),
        "blank_gw_teams":  blank_gw_teams,
        "assembled_at":    datetime.datetime.utcnow().isoformat() + "Z",
        "minutes_fixture_source": (
            "official_all_fixtures" if all_fixtures is not None else "unavailable"
        ),
    }

    return {
        "bootstrap":              bootstrap,
        "gameweek":               gw,
        "fixtures":               fetched_fixtures,
        "fixture_difficulty_map": fdr_map,
        "meta":                   meta,
    }
