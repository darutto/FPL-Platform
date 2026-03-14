"""
fpl_pipeline
============
Orchestration and context assembly for the FPL grounded assistant.

Phase 2e public surface
-----------------------
::

    assemble_captain_context(
        gameweek=None,      # int | None — override GW; None → resolve from bootstrap
        *,
        bootstrap=None,     # dict | None — pre-fetched bootstrap; None → live fetch
        fixtures=None,      # list | None — pre-fetched fixtures; None → live fetch
    ) -> dict

Returned dict keys::

    bootstrap               – FPL bootstrap with ``fixture_difficulty_map`` injected
    gameweek                – resolved GW number (int or None)
    fixtures                – raw fixture list for that GW (list of dicts)
    fixture_difficulty_map  – {team_id: fdr} derived from fixtures
    meta                    – inspectable assembly metadata dict

Caller burden removed (Phase 2e)
---------------------------------
Before Phase 2e, callers had to:

    1. bootstrap = get_bootstrap()
    2. gw       = get_current_gameweek(bootstrap)
    3. fixtures = get_fixtures(gw)
    4. bootstrap["fixture_difficulty_map"] = get_fixture_difficulty_map(fixtures, bootstrap)
    5. result   = ask("...", bootstrap, ...)

After Phase 2e:

    ctx    = assemble_captain_context()
    result = ask("...", ctx["bootstrap"], ...)

What remains explicit
---------------------
* Candidate selection — which players to evaluate.
* Manual overrides — explicit ``fixture_difficulty``, ``form``, etc. when desired.
* Blank-GW team FDR — teams absent from the fixture map still require an explicit
  ``fixture_difficulty`` override in ``candidate_inputs`` / per-candidate dict.
* ``ask()`` invocation — the harness call itself.
"""

from .context import assemble_captain_context

__all__ = ["assemble_captain_context"]