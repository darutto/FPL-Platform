#!/usr/bin/env python
"""
One-shot fetcher for a 2022 World Cup dataset via api-football.com.

Pulls fixtures, group standings, and per-fixture player statistics
(minutes, cards, GK saves, key passes, duels, dribbles, rating) for the
WC2022 tournament (league id 1, season 2022) and writes them as JSON under
``packages/worldcup-api-client/data/wc2022/``.

This is a standalone historical dataset for later ML/calibration work — it
is NOT wired into the live worldcup-assistant.

Run once (free plan: 100 req/day, 10 req/min):

    cd packages/worldcup-api-client
    python scripts/fetch_wc2022_dataset.py

Requires ``API_FOOTBALL_KEY`` to be set (loaded from
``packages/worldcup-assistant/.env``).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PKG_ROOT = _THIS_DIR.parent
_REPO_ROOT = _PKG_ROOT.parent.parent
sys.path.insert(0, str(_PKG_ROOT))

from worldcup_api_client.api_football_client import (  # noqa: E402
    MIN_REQUEST_INTERVAL_S,
    ApiFootballError,
    get_fixtures,
    get_fixture_players,
    get_standings,
)

SEASON = 2022
DATA_DIR = _PKG_ROOT / "data" / "wc2022"
FIXTURE_PLAYERS_DIR = DATA_DIR / "fixture_players"


def _load_env() -> None:
    """Load API_FOOTBALL_KEY from worldcup-assistant/.env (mirrors start_server.py)."""
    env_file = _REPO_ROOT / "packages" / "worldcup-assistant" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def _save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {path.relative_to(_PKG_ROOT)} ({len(json.dumps(data))} bytes)")


def main() -> None:
    _load_env()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching WC2022 fixtures...")
    fixtures = get_fixtures(SEASON)
    _save(DATA_DIR / "fixtures.json", fixtures)
    print(f"  {len(fixtures)} fixtures")
    time.sleep(MIN_REQUEST_INTERVAL_S)

    print("Fetching WC2022 standings...")
    standings = get_standings(SEASON)
    _save(DATA_DIR / "standings.json", standings)
    print(f"  {len(standings)} groups")
    time.sleep(MIN_REQUEST_INTERVAL_S)

    finished = [f for f in fixtures if f["fixture"]["status"]["short"] == "FT"]
    print(f"Fetching per-player stats for {len(finished)} finished fixtures "
          f"(~{len(finished) * MIN_REQUEST_INTERVAL_S / 60:.1f} min)...")

    skipped: list[int] = []
    for i, f in enumerate(finished, start=1):
        fixture_id = f["fixture"]["id"]
        out_path = FIXTURE_PLAYERS_DIR / f"{fixture_id}.json"
        if out_path.exists():
            print(f"  [{i}/{len(finished)}] fixture {fixture_id}: already cached, skipping")
            continue
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        try:
            players = get_fixture_players(fixture_id)
            _save(out_path, players)
            print(f"  [{i}/{len(finished)}] fixture {fixture_id} ({home} vs {away}): ok")
        except ApiFootballError as exc:
            print(f"  [{i}/{len(finished)}] fixture {fixture_id} ({home} vs {away}): FAILED - {exc}")
            skipped.append(fixture_id)
        if i < len(finished):
            time.sleep(MIN_REQUEST_INTERVAL_S)

    print("\nDone.")
    print(f"  fixtures.json: {len(fixtures)} entries")
    print(f"  standings.json: {len(standings)} groups")
    print(f"  fixture_players/: {len(list(FIXTURE_PLAYERS_DIR.glob('*.json')))} files")
    if skipped:
        print(f"  FAILED fixture ids: {skipped}")


if __name__ == "__main__":
    main()
