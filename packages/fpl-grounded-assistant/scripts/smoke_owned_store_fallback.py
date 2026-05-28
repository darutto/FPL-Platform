"""
scripts/smoke_owned_store_fallback.py
=====================================
Operator smoke script for the owned-store fallback path (H4d).

Sets the two force-fallback env vars BEFORE importing fpl_server, so the
in-module flag reads land at startup time and tools take the fallback path.

What this script exercises (independently, so one failure does not abort
the others):

    (a) fpl_server._fetch_bootstrap_with_retry()  -> forced bootstrap fallback
    (b) player_form._fetch_element_summary(1)     -> forced tool fallback
    (c) get_fixtures_for_gw._fetch_fixtures_for_gw(1) -> forced tool fallback
    (d) player_fixture_run.get_player_fixture_run("fixture run for haaland",
        bootstrap)  -> end-to-end: response is NOT missing_context

Exit code: 0 on full pass (4/4), 1 on any failure.

This is a manual/local smoke. It is NOT a pytest test and must not be
auto-collected. Pre-requisites for a real PASS:

    - packages/fpl-historical/data/historical/seasons/2025-2026/parquet_merged/
      contains the merged parquet files
    - packages/fpl-historical/data/historical/seasons/2025-2026/_owned_latest.json
      pointer exists and references those files
    - All sibling packages (fpl-api-client, fpl-historical, ...) importable

Usage:
    cd packages/fpl-grounded-assistant
    python scripts/smoke_owned_store_fallback.py
    # or
    python -m scripts.smoke_owned_store_fallback
"""
from __future__ import annotations

import os
import sys
import traceback

# CRITICAL: set the force-fallback flags BEFORE importing anything that
# reads them at module-load time.
os.environ["FPL_FORCE_FALLBACK_BOOTSTRAP"] = "1"
os.environ["FPL_FORCE_FALLBACK_TOOLS"] = "1"

# Ensure the package root is on sys.path so `import fpl_server` works when
# the script is invoked from the package root or via -m.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_HERE)  # packages/fpl-grounded-assistant
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

import fpl_server  # noqa: E402
from fpl_grounded_assistant import player_form  # noqa: E402
# NOTE: `fpl_grounded_assistant.get_fixtures_for_gw` resolves to the
# re-exported *function* (see __init__.py), shadowing the submodule.
# Grab the actual submodule out of sys.modules to reach the private
# _fetch_fixtures_for_gw helper.
import fpl_grounded_assistant.get_fixtures_for_gw  # noqa: F401,E402  (ensures it's loaded)
get_fixtures_for_gw_mod = sys.modules["fpl_grounded_assistant.get_fixtures_for_gw"]
from fpl_grounded_assistant import player_fixture_run  # noqa: E402


def _step(label: str, fn):
    """Run one smoke step; return True on pass, False on failure. Never raises."""
    try:
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}: {detail}")
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {label}: unexpected exception {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


def step_a():
    bs = fpl_server._fetch_bootstrap_with_retry()
    if not isinstance(bs, dict):
        return False, f"expected dict, got {type(bs).__name__}"
    tf = bs.get("team_fixtures")
    if not isinstance(tf, dict) or not tf:
        return False, "bootstrap['team_fixtures'] missing or empty"
    return True, (
        f"bootstrap returned, team_fixtures populated "
        f"({len(tf)} teams, {len(bs.get('elements', []))} elements)"
    )


def step_b():
    summary = player_form._fetch_element_summary(1, {})
    if not isinstance(summary, dict):
        return False, f"expected dict, got {type(summary).__name__}"
    if "history" not in summary:
        return False, "summary missing 'history' key"
    return True, f"element_summary(1) returned, history rows={len(summary['history'])}"


def step_c():
    fixtures = get_fixtures_for_gw_mod._fetch_fixtures_for_gw(
        1, bootstrap=None, fixtures_override=None,
    )
    if not isinstance(fixtures, list):
        return False, f"expected list, got {type(fixtures).__name__}"
    return True, f"fixtures(gw=1) returned, count={len(fixtures)}"


def step_d(bootstrap):
    if not isinstance(bootstrap, dict):
        return False, "step (a) bootstrap unavailable; cannot run end-to-end"
    resp = player_fixture_run.get_player_fixture_run(
        "fixture run for haaland", bootstrap,
    )
    if not isinstance(resp, dict):
        return False, f"expected dict, got {type(resp).__name__}"
    if resp.get("status") == "missing_context":
        return False, f"got missing_context: reason={resp.get('reason')}"
    return True, f"player_fixture_run status={resp.get('status')}"


def main() -> int:
    print("== H4d owned-store fallback smoke ==")
    print(f"FPL_FORCE_FALLBACK_BOOTSTRAP={os.environ.get('FPL_FORCE_FALLBACK_BOOTSTRAP')}")
    print(f"FPL_FORCE_FALLBACK_TOOLS={os.environ.get('FPL_FORCE_FALLBACK_TOOLS')}")
    print("")

    # Step (a) — we keep the bootstrap for step (d).
    bootstrap_for_d: dict | None = None

    def _step_a_capture():
        nonlocal bootstrap_for_d
        bs = fpl_server._fetch_bootstrap_with_retry()
        bootstrap_for_d = bs if isinstance(bs, dict) else None
        if not isinstance(bs, dict):
            return False, f"expected dict, got {type(bs).__name__}"
        tf = bs.get("team_fixtures")
        if not isinstance(tf, dict) or not tf:
            return False, "bootstrap['team_fixtures'] missing or empty"
        return True, (
            f"bootstrap returned, team_fixtures populated "
            f"({len(tf)} teams, {len(bs.get('elements', []))} elements)"
        )

    results = [
        _step("(a) forced bootstrap fallback",        _step_a_capture),
        _step("(b) forced element_summary fallback",  step_b),
        _step("(c) forced fixtures fallback",         step_c),
        _step("(d) end-to-end player_fixture_run",    lambda: step_d(bootstrap_for_d)),
    ]

    passes = sum(1 for r in results if r)
    total = len(results)
    summary = f"PASS {passes}/{total}" if passes == total else f"FAIL {passes}/{total}"
    print("")
    print(f"== {summary} ==")
    return 0 if passes == total else 1


if __name__ == "__main__":
    sys.exit(main())
