#!/usr/bin/env python3
"""Operational verification for the i73 Entrega 2 season rollover.

Exercises the tools reachable via production's live /ask endpoint and
prints each assertion's actual value (never just pass/fail). Run manually
against the deployed Railway URL after a bump/cron redeploy:

    python scripts/verify_prod_rollover.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --expected-season 2026-2027

i82 closed the reachability gap this script used to document: both
get_player_season_points and get_historical_gameweek_top_scorer are now in
the LLM catalogue, so the two checks below run live via /ask with
debug=True and assert on the tool's own raw_output (season, totals, rows)
-- never on the synthesis text alone. The previous-season value is computed
here from --expected-season, independently of anything the backend says.

i92: before those two /ask checks, /healthz.owned_store_seasons (a filesystem
scan of the container's store) must list both the expected season and the
previous one as complete. That check runs FIRST so a later season_points
miss is attributable to data (this check red) or to routing (this check
green), never to both at once.
"""
from __future__ import annotations

import argparse
import json
import sys

import requests

# Windows consoles default to cp1252; the Spanish questions below would
# otherwise crash the print, not the check.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


#: i90: the live FPL API, used to compute an INDEPENDENT expected fixture
#: scope -- never read matched_teams and then ask "does this look right,"
#: always compute the answer from a second source first.
_FPL_API = "https://fantasy.premierleague.com/api"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Base URL, e.g. https://.../  (no trailing /ask)")
    parser.add_argument("--expected-season", required=True)
    parser.add_argument("--user-id", default="verify-prod-rollover-i73")
    parser.add_argument(
        "--zonal-fixture-opponent",
        default=None,
        help=(
            "i90: also verify the fixture-derived default scope of "
            "get_zonal_opportunity for this team (FPL display name, e.g. "
            "'Fulham'). Skipped when omitted."
        ),
    )
    parser.add_argument(
        "--zonal-fixture-horizon", type=int, default=5,
        help="i90: horizon to ask for and to independently compute against (default 5).",
    )
    return parser.parse_args()


def _ask(base_url: str, question: str, user_id: str, extra_args: dict | None = None) -> dict:
    payload = {"question": question, "debug": True}
    if extra_args:
        payload.update(extra_args)
    resp = requests.post(
        f"{base_url.rstrip('/')}/ask",
        headers={"Content-Type": "application/json", "X-User-Id": user_id},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _live_fpl_expected_opponents(team_name: str, horizon: int) -> tuple[list[str], list[str], int]:
    """Independently compute who plays *team_name* in the next *horizon*
    gameweeks, straight from the live FPL API -- never from anything the
    backend under test returned. Returns (opponent FPL display names,
    opponent FPL short_name codes -- same order, gameweek order -- and
    current_gw)."""
    bootstrap = requests.get(f"{_FPL_API}/bootstrap-static/", timeout=30).json()
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    team_id = next(
        (t["id"] for t in bootstrap["teams"] if t["name"].lower() == team_name.lower()), None,
    )
    if team_id is None:
        raise SystemExit(f"[verify_prod_rollover] unknown FPL team name: {team_name!r}")
    current_gw = next(
        (e["id"] for e in bootstrap["events"] if e.get("is_current")),
        next((e["id"] for e in bootstrap["events"] if e.get("is_next")), None),
    )
    if current_gw is None:
        raise SystemExit("[verify_prod_rollover] could not determine current gameweek from bootstrap-static")

    fixtures = requests.get(f"{_FPL_API}/fixtures/", timeout=30).json()
    window = sorted(
        (
            f for f in fixtures
            if f.get("event") is not None
            and current_gw <= f["event"] < current_gw + horizon
            and team_id in (f.get("team_h"), f.get("team_a"))
        ),
        key=lambda f: f["event"],
    )
    names: list[str] = []
    short_names: list[str] = []
    for f in window:
        opp_id = f["team_a"] if f["team_h"] == team_id else f["team_h"]
        opp = teams_by_id[opp_id]
        if opp["name"] not in names:
            names.append(opp["name"])
            short_names.append(str(opp["short_name"]).upper())
    return names, short_names, current_gw


def verify_zonal_fixture_scope(
    base_url: str, user_id: str, opponent: str, horizon: int, failures: list[str],
) -> None:
    """i90: with no team named, get_zonal_opportunity's default scope must
    be *opponent*'s own next `horizon` gameweeks -- never the whole league,
    and never silently wrong when the FPL->Understat name bridge has a gap.

    Understat store names (e.g. 'Manchester City') and FPL display names
    (e.g. 'Man City') don't compare as strings, and re-deriving the bridge
    here to force a string match would make this check test itself, not
    the backend -- the same trap i74's provenance stamp already had to
    avoid (compare against an independent source, never against the
    variable that produced the thing being checked). A COUNT-only check
    would dodge that trap but is too weak to catch the failure mode that
    matters: five right rivals and five wrong ones both count to five
    (review finding, i90 -- this is the check shape that gave six green
    runs during the i70 incident).

    The exact, code-level, still-independent check: each exploiter row
    already carries `team_short` (FPL short_name, via the SAME bridge that
    built matched_teams -- so a bridge bug shows up here too), and the
    live FPL API gives short_name for each expected rival directly, no
    bridge needed on that side. `{team_short in the response}` must be a
    SUBSET of `{short_name of the live-computed expected rivals}`: any
    code outside that set is either the bridge naming the wrong team or a
    team that shouldn't be in scope at all. `unmatched_teams` stays the
    hard, string-exact contract for the other failure direction (a rival
    that couldn't resolve at all): must always be empty.
    """
    print(
        f"\n[verify_prod_rollover] i90 zonal fixture scope: "
        f"get_zonal_opportunity(opponent={opponent!r}, no team, horizon={horizon}) via /ask",
        flush=True,
    )
    question = (
        f"¿En qué zonas es débil defensivamente el {opponent} y qué jugadores "
        f"pueden explotarlas en las próximas {horizon} jornadas?"
    )
    body = _ask(base_url, question, user_id)
    zonal = body.get("zonal_opportunity") or {}
    tf = zonal.get("team_filter") or {}
    source = tf.get("source")
    matched_teams = tf.get("matched_teams") or []
    unmatched_teams = tf.get("unmatched_teams") or []
    fixture_window = tf.get("fixture_window") or {}
    exploiter_short_codes = {
        str(e["team_short"]).upper()
        for e in (zonal.get("exploiters") or [])
        if e.get("team_short")
    }
    print(
        f"  backend: source={source!r} matched_teams={matched_teams!r} "
        f"unmatched_teams={unmatched_teams!r} fixture_window={fixture_window!r} "
        f"exploiter team_short codes={sorted(exploiter_short_codes)!r}",
        flush=True,
    )

    expected_names, expected_short_codes, current_gw = _live_fpl_expected_opponents(opponent, horizon)
    print(
        f"  live FPL (independent): current_gw={current_gw} "
        f"expected_opponents={expected_names!r} short_codes={expected_short_codes!r}",
        flush=True,
    )

    if unmatched_teams:
        failures.append(
            f"zonal fixture scope: unmatched_teams={unmatched_teams!r} -- "
            f"name-bridge gap in prod (a rival's FPL->Understat code failed to resolve)"
        )

    if not expected_short_codes:
        if source not in (None, "fixtures_empty_fallback"):
            failures.append(
                f"zonal fixture scope: live calendar has no fixtures for {opponent} "
                f"in the window, but backend source={source!r} (expected None or "
                f"'fixtures_empty_fallback')"
            )
        return

    if source != "fixtures":
        failures.append(
            f"zonal fixture scope: expected source='fixtures' (live calendar has "
            f"{len(expected_short_codes)} opponent(s) in window), got {source!r}"
        )
        return

    if fixture_window.get("from_gw") != current_gw:
        failures.append(
            f"zonal fixture scope: fixture_window.from_gw={fixture_window.get('from_gw')!r}, "
            f"live current_gw={current_gw}"
        )
    if len(matched_teams) != len(expected_short_codes):
        failures.append(
            f"zonal fixture scope: matched_teams has {len(matched_teams)} entries "
            f"({matched_teams!r}), live FPL calendar independently has "
            f"{len(expected_short_codes)} ({expected_names!r}) -- counts must match "
            f"even though the two lists use different team-name conventions"
        )
    # The exact check: every team_short actually served must be a rival the
    # live calendar independently confirms is scheduled -- code-level, so a
    # bridge bug that names the WRONG team fails here even if the COUNT
    # happens to match (the failure mode a count-only check cannot see).
    stray_codes = exploiter_short_codes - set(expected_short_codes)
    if stray_codes:
        failures.append(
            f"zonal fixture scope: exploiter rows carry team_short={sorted(stray_codes)!r} "
            f"not among the live-computed expected rivals {expected_short_codes!r} for "
            f"{opponent} -- the FPL->Understat bridge served the wrong team"
        )


def _previous_season(season: str) -> str:
    start, end = (int(x) for x in season.split("-"))
    return f"{start - 1}-{end - 1}"


def verify_owned_store_seasons(base_url: str, expected_season: str, failures: list[str]) -> bool:
    """i92: BEFORE any /ask, read /healthz.owned_store_seasons -- the seasons
    that exist on the container's disk, scanned from the filesystem -- and
    require both the expected season and the one before it, complete.

    Ordering is the point: if this fails, a later season_points miss is a
    DATA problem; if this passes and Salah still fails, it is routing or
    resolution. One check per cause. Returns True when both seasons are
    present and complete.
    """
    previous = _previous_season(expected_season)
    print("\n[verify_prod_rollover] i92 /healthz owned_store_seasons (disk scan)", flush=True)
    resp = requests.get(f"{base_url.rstrip('/')}/healthz", timeout=30)
    resp.raise_for_status()
    body = resp.json()
    on_disk = body.get("owned_store_seasons")
    sync_block = body.get("owned_store_sync") or {}
    print(f"  owned_store_sync (startup, first season)={sync_block!r}", flush=True)
    print(f"  owned_store_seasons (disk)={on_disk!r}", flush=True)
    if not isinstance(on_disk, list):
        failures.append("healthz: owned_store_seasons missing -- backend predates i92 or the key was dropped")
        return False
    by_season = {row.get("season"): row for row in on_disk if isinstance(row, dict)}
    ok = True
    for season in (expected_season, previous):
        row = by_season.get(season)
        if row is None:
            failures.append(f"healthz: season {season!r} is not on the container's disk (have {sorted(by_season)!r})")
            ok = False
        elif not row.get("complete"):
            failures.append(f"healthz: season {season!r} on disk but incomplete: {row!r}")
            ok = False
        else:
            print(f"  season {season}: present, merged_at={row.get('merged_at')!r}", flush=True)
    return ok


def verify_season_tools(base_url: str, user_id: str, expected_season: str, failures: list[str]) -> None:
    """i82: the two owned-store season tools, live, asserted on raw_output.

    1. "cuántos puntos hizo Salah la temporada pasada" -> tool_calls contains
       get_player_season_points, raw_output.season == previous(expected),
       summary.total_points > 0.
    2. "quién hizo más puntos en la jornada 3" -> tool_calls contains
       get_historical_gameweek_top_scorer, raw_output.season == expected,
       entries non-empty, and final_text carries no "No renderer".
    Every assertion prints the value it saw.
    """
    previous = _previous_season(expected_season)

    print(
        "\n[verify_prod_rollover] i82 get_player_season_points "
        "(Salah, temporada pasada) via /ask",
        flush=True,
    )
    body = _ask(base_url, "¿Cuántos puntos hizo Salah la temporada pasada?", user_id)
    debug = body.get("debug") or {}
    tool_calls = (debug.get("routing_trace") or {}).get("orchestrator_tool_calls") or []
    raw = debug.get("raw_output") or {}
    season = raw.get("season")
    total_points = (raw.get("summary") or {}).get("total_points")
    print(
        f"  tool_calls={tool_calls!r} selected_tool={debug.get('selected_tool')!r} "
        f"tool_input={debug.get('tool_input')!r}",
        flush=True,
    )
    print(f"  raw_output.season={season!r} (expected {previous!r}) total_points={total_points!r}", flush=True)
    print(f"  final_text={body.get('final_text', '')!r}", flush=True)
    if "get_player_season_points" not in tool_calls:
        failures.append(f"season_points: expected get_player_season_points in tool_calls, got {tool_calls!r}")
    if season != previous:
        failures.append(f"season_points: raw_output.season={season!r}, expected {previous!r}")
    if not isinstance(total_points, (int, float)) or total_points <= 0:
        failures.append(f"season_points: total_points={total_points!r}, expected > 0")

    print(
        "\n[verify_prod_rollover] i82 get_historical_gameweek_top_scorer "
        "(jornada 3) via /ask",
        flush=True,
    )
    body = _ask(base_url, "¿Quién hizo más puntos en la jornada 3?", user_id)
    debug = body.get("debug") or {}
    tool_calls = (debug.get("routing_trace") or {}).get("orchestrator_tool_calls") or []
    raw = debug.get("raw_output") or {}
    season = raw.get("season")
    entries = raw.get("entries") or []
    final_text = body.get("final_text", "")
    print(
        f"  tool_calls={tool_calls!r} selected_tool={debug.get('selected_tool')!r} "
        f"tool_input={debug.get('tool_input')!r}",
        flush=True,
    )
    print(
        f"  raw_output.status={raw.get('status')!r} season={season!r} (expected {expected_season!r}) "
        f"entries={len(entries)} first={entries[0] if entries else None!r}",
        flush=True,
    )
    print(f"  final_text={final_text!r}", flush=True)
    if "get_historical_gameweek_top_scorer" not in tool_calls:
        failures.append(
            f"top_scorer: expected get_historical_gameweek_top_scorer in tool_calls, got {tool_calls!r}"
        )
    if season != expected_season:
        failures.append(f"top_scorer: raw_output.season={season!r}, expected {expected_season!r}")
    if not entries:
        failures.append(f"top_scorer: no entries (status={raw.get('status')!r} code={raw.get('code')!r})")
    if "No renderer" in final_text:
        failures.append("top_scorer: final_text contains 'No renderer'")


def main() -> None:
    args = _parse_args()
    failures: list[str] = []

    print("[verify_prod_rollover] get_zonal_weakness (team=Arsenal) via /ask", flush=True)
    body = _ask(args.url, "En que zonas es debil defensivamente el Arsenal?", args.user_id)
    trace = (body.get("debug") or {}).get("routing_trace") or {}
    tool_calls = trace.get("orchestrator_tool_calls") or []
    outcome = body.get("outcome")
    final_text = body.get("final_text", "")
    print(f"  outcome={outcome!r} tool_calls={tool_calls!r}", flush=True)
    print(f"  final_text={final_text!r}", flush=True)

    if "get_zonal_weakness" not in tool_calls:
        failures.append(f"expected get_zonal_weakness to be called, got {tool_calls!r}")
    if outcome != "ok":
        failures.append(f"expected outcome='ok', got {outcome!r}")
    if not final_text.strip():
        failures.append("final_text was empty")

    # i92: data first, then routing -- so a failure below is attributable.
    seasons_ok = verify_owned_store_seasons(args.url, args.expected_season, failures)
    if not seasons_ok:
        print(
            "  -> a season_points miss below is a DATA gap (container disk), "
            "not routing; the tool checks still run so the trace is on record.",
            flush=True,
        )
    verify_season_tools(args.url, args.user_id, args.expected_season, failures)

    if args.zonal_fixture_opponent:
        verify_zonal_fixture_scope(
            args.url, args.user_id, args.zonal_fixture_opponent,
            args.zonal_fixture_horizon, failures,
        )
    else:
        print(
            "\n[verify_prod_rollover] i90 zonal fixture scope: SKIPPED "
            "(pass --zonal-fixture-opponent to run it)",
            flush=True,
        )

    if failures:
        print("\n[verify_prod_rollover] FAILED:", file=sys.stderr, flush=True)
        for f in failures:
            print(f"  - {f}", file=sys.stderr, flush=True)
        sys.exit(1)

    print("\n[verify_prod_rollover] all checks passed.", flush=True)


if __name__ == "__main__":
    main()
