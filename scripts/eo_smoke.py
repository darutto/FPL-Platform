"""EO smoke test: can this machine reach the public FPL API? (3 requests.)

Run from a GitHub Actions runner by .github/workflows/eo-smoke-test.yml. It makes
exactly three read-only requests to the free public FPL API:

  1. bootstrap-static                      (finds the last finished gameweek)
  2. leagues-classic/314/standings, page 1 (the overall league; gives one entry id)
  3. entry/{id}/event/{gw}/picks           (that entry's picks for the last finished GW)

It logs the step name, HTTP status, elapsed time and (for a failure) the error
class, and nothing else: no manager names, no entry ids, no picks, no values are
printed, and nothing is stored or published. Exit code 0 only if all three
requests returned 200.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

BASE = "https://fantasy.premierleague.com/api"
OVERALL_LEAGUE = 314
USER_AGENT = "fpl-platform-eo-smoke/1.0 (read-only, 3 requests)"
TIMEOUT_S = 20

Fetch = Callable[[str], tuple[int, Any]]


def http_get(url: str) -> tuple[int, Any]:
    """GET *url* -> (status, parsed JSON or None). Never raises on HTTP errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ConnectionError(type(exc).__name__) from None


def last_finished_gw(bootstrap: dict[str, Any]) -> int | None:
    done = [e["id"] for e in bootstrap.get("events") or [] if e.get("finished")]
    return max(done) if done else None


def first_entry_id(standings: dict[str, Any]) -> int | None:
    results = ((standings.get("standings") or {}).get("results")) or []
    return results[0].get("entry") if results else None


def _step(name: str, url: str, fetch: Fetch) -> tuple[int | None, Any]:
    start = time.monotonic()
    try:
        status, body = fetch(url)
        error = ""
    except ConnectionError as exc:
        status, body, error = None, None, f" error={exc}"
    ms = int((time.monotonic() - start) * 1000)
    print(f"{name}: status={status} elapsed_ms={ms}{error}")
    return status, body


def run(fetch: Fetch = http_get) -> int:
    ok = True
    status, bootstrap = _step("bootstrap", f"{BASE}/bootstrap-static/", fetch)
    gw = last_finished_gw(bootstrap) if status == 200 and bootstrap else None
    ok &= status == 200 and gw is not None
    if gw is None:
        print("last finished gameweek: not found")

    status, standings = _step(
        "standings_page_1", f"{BASE}/leagues-classic/{OVERALL_LEAGUE}/standings/?page_standings=1", fetch
    )
    entry = first_entry_id(standings) if status == 200 and standings else None
    ok &= status == 200 and entry is not None

    if entry is None or gw is None:
        print("picks: skipped (missing gameweek or entry id)")
        return 1
    status, _ = _step("picks", f"{BASE}/entry/{entry}/event/{gw}/picks/", fetch)
    ok &= status == 200
    print("result:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
