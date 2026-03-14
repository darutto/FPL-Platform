"""
fpl_pipeline.context
====================
Phase 2e: Deterministic context assembly pipeline.

Assembles the full context required by the FPL captain tool path in a
single call, eliminating the multi-step setup burden from callers.

Design principles
-----------------
* All outputs are deterministic and inspectable.
* Every network-calling step is injectable (``bootstrap`` and ``fixtures``
  parameters) so the function is fully testable without network access.
* The returned dict is self-documenting via the ``meta`` sub-dict.
* The returned ``bootstrap`` has ``fixture_difficulty_map`` pre-injected so
  it can be passed directly to ``harness.ask()`` without further setup.

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


def assemble_captain_context(
    gameweek: int | None = None,
    *,
    bootstrap: dict[str, Any] | None = None,
    fixtures: list[dict[str, Any]] | None = None,
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

    Returns
    -------
    dict with the following keys:

    ``bootstrap``
        The FPL bootstrap dict with ``fixture_difficulty_map`` injected.
        Pass this directly to ``harness.ask()`` — no further setup needed.

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
    if bootstrap is None:
        bootstrap = get_bootstrap()

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
    if fixtures is None:
        fetched_fixtures: list[dict[str, Any]] = []
        if gw is not None:
            fetched_fixtures = get_fixtures(gw)
    else:
        fetched_fixtures = fixtures

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

    # ------------------------------------------------------------------
    # 7. Build meta
    # ------------------------------------------------------------------
    meta: dict[str, Any] = {
        "gw_resolved_via": gw_resolved_via,
        "fixture_count":   len(fetched_fixtures),
        "team_count":      len(teams),
        "blank_gw_teams":  blank_gw_teams,
        "assembled_at":    datetime.datetime.utcnow().isoformat() + "Z",
    }

    return {
        "bootstrap":              bootstrap,
        "gameweek":               gw,
        "fixtures":               fetched_fixtures,
        "fixture_difficulty_map": fdr_map,
        "meta":                   meta,
    }