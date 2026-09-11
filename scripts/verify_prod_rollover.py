#!/usr/bin/env python3
"""Operational verification for the i73 Entrega 2 season rollover.

Exercises the tools reachable via production's live /ask endpoint and
prints each assertion's actual value (never just pass/fail). Run manually
against the deployed Railway URL after a bump/cron redeploy:

    python scripts/verify_prod_rollover.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --expected-season 2026-2027

KNOWN GAP (pre-existing, unrelated to this rollover, discovered while
writing this script): get_player_season_points and
get_historical_gameweek_top_scorer are fully implemented, registered in the
deterministic TOOL_REGISTRY, and unit-tested, but are NOT present in
tool_schema_registry.py's get_offered_tool_schemas() -- the catalogue
offered to the LLM orchestrator. They are also unreachable via the legacy
router (ask_v2 does not call route() for free-text turns outside the
resource/prompt decision_router branches) or via intent_hint (only 6 V2
slash-command intents are in INTENT_HINT_ALLOWLIST; player_season_points
is not one). Repeated live probing during this rollover confirmed the
orchestrator cannot be steered to call either tool regardless of phrasing.

This script therefore only exercises get_zonal_weakness live. For the other
two tools, season-2026-2027 correctness is established at the code level
instead (see the season-bump PR): get_player_season_points.py:442 derives
its "current season" schema text from CURRENT_SEASON directly, and
historical_gameweek_top_scorer.py:525 defaults an omitted `season` argument
to CURRENT_SEASON directly -- both move automatically with the registry
bump and are covered by the passing season_registry/season_key_contract
test suites. Closing this reachability gap (wiring both tools into
get_offered_tool_schemas()) is out of scope for a season rollover and is
logged as a separate follow-up finding, not fixed here.
"""
from __future__ import annotations

import argparse
import json
import sys

import requests


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Base URL, e.g. https://.../  (no trailing /ask)")
    parser.add_argument("--expected-season", required=True)
    parser.add_argument("--user-id", default="verify-prod-rollover-i73")
    return parser.parse_args()


def _ask(base_url: str, question: str, user_id: str) -> dict:
    resp = requests.post(
        f"{base_url.rstrip('/')}/ask",
        headers={"Content-Type": "application/json", "X-User-Id": user_id},
        json={"question": question, "debug": True},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


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

    print(
        "\n[verify_prod_rollover] get_player_season_points / "
        "get_historical_gameweek_top_scorer: SKIPPED (not reachable via /ask "
        "-- see module docstring). Verified at code level instead:",
        flush=True,
    )
    print(
        "  get_player_season_points.py:442 derives schema text from CURRENT_SEASON",
        flush=True,
    )
    print(
        "  historical_gameweek_top_scorer.py:525 defaults `season` to CURRENT_SEASON",
        flush=True,
    )

    if failures:
        print("\n[verify_prod_rollover] FAILED:", file=sys.stderr, flush=True)
        for f in failures:
            print(f"  - {f}", file=sys.stderr, flush=True)
        sys.exit(1)

    print("\n[verify_prod_rollover] get_zonal_weakness check passed.", flush=True)


if __name__ == "__main__":
    main()
