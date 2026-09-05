"""Attach one complete official fixture snapshot to a frozen bootstrap.

This is data capture only. It exists so the Slice 3 pre/post measurement uses
team-specific completed fixtures rather than inferring availability from the
gameweek number. Each normalized fixture is marked complete only because the
source is the official all-fixtures endpoint fetched in one call.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
for package_dir in (REPO_ROOT / "packages").iterdir():
    if package_dir.is_dir():
        sys.path.insert(0, str(package_dir))

from fpl_api_client.fpl_client import get_all_fixtures  # noqa: E402


def _team_fixtures(
    fixtures: list[dict[str, Any]],
    bootstrap: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    strengths = {
        int(team["id"]): int(team["strength"]) if team.get("strength") is not None else 3
        for team in bootstrap.get("teams", [])
    }
    result: dict[int, list[dict[str, Any]]] = {}
    for fixture in fixtures:
        event = fixture.get("event")
        home = fixture.get("team_h")
        away = fixture.get("team_a")
        if event is None or home is None or away is None:
            continue
        event, home, away = int(event), int(home), int(away)
        shared = {
            "gameweek": event,
            "finished": fixture.get("finished") is True,
            "kickoff_time": fixture.get("kickoff_time"),
            "minutes": fixture.get("minutes"),
            "official_fixture_context_complete": True,
        }
        result.setdefault(home, []).append(
            {
                **shared,
                "opponent_team": away,
                "is_home": True,
                "difficulty": int(
                    fixture.get("team_h_difficulty") or strengths.get(away, 3)
                ),
            }
        )
        result.setdefault(away, []).append(
            {
                **shared,
                "opponent_team": home,
                "is_home": False,
                "difficulty": int(
                    fixture.get("team_a_difficulty") or strengths.get(home, 3)
                ),
            }
        )
    for rows in result.values():
        rows.sort(key=lambda row: (row["gameweek"], row["opponent_team"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    bootstrap = json.loads(args.bootstrap.read_bytes())
    fixtures = get_all_fixtures()
    bootstrap["team_fixtures"] = _team_fixtures(fixtures, bootstrap)
    bootstrap["_minutes_fixture_snapshot"] = {
        "source": "official_all_fixtures",
        "fixture_count": len(fixtures),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(bootstrap, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"fixtures={len(fixtures)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
