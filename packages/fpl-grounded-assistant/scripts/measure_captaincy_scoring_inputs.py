"""Freeze and compare the captaincy scoring-input ranking.

MEASUREMENT ONLY. Commit this script together with the pre-change observation
and do not edit it after observing either side of the comparison.

Pre-registered snapshot expectation
------------------------------------
On the frozen 2026-09-03 bootstrap, replacing status-only minutes risk with
reliable minutes participation is expected to lower every partially
participating player's score, leave fully participating players' scores
unchanged, and leave Haaland at the same rank. This is a check of this frozen
snapshot, not a product invariant. If Haaland changes rank, stop and inspect
for an unintended second change.

Pre-registered comparison rule
------------------------------
Match observations by ``player_id``. The comparison is PROCEED only when:

* at least one player's ``minutes_risk`` rises and every such score falls;
* every player whose ``minutes_risk`` is unchanged keeps the same score;
* no player's ``minutes_risk`` falls; and
* Haaland exists on both sides and keeps the same rank.

Any missing player, duplicate player id, or violated condition is
STOP_AND_INVESTIGATE. The rule is intentionally written before the first live
capture or post-change run.

Examples (from the repository root)::

    python packages/fpl-grounded-assistant/scripts/measure_captaincy_scoring_inputs.py capture \
      --gameweek 3 \
      --bootstrap field-notes/artifacts/captaincy-scoring-bootstrap-2026-09-03.json \
      --out field-notes/artifacts/captaincy-scoring-inputs-pre-2026-09-03.jsonl

    python packages/fpl-grounded-assistant/scripts/measure_captaincy_scoring_inputs.py measure \
      --bootstrap field-notes/artifacts/captaincy-scoring-bootstrap-2026-09-03.json \
      --out field-notes/artifacts/captaincy-scoring-inputs-post-2026-09-03.jsonl

    python packages/fpl-grounded-assistant/scripts/measure_captaincy_scoring_inputs.py compare \
      --before field-notes/artifacts/captaincy-scoring-inputs-pre-2026-09-03.jsonl \
      --after field-notes/artifacts/captaincy-scoring-inputs-post-2026-09-03.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
for package_dir in (REPO_ROOT / "packages").iterdir():
    if package_dir.is_dir():
        sys.path.insert(0, str(package_dir))

from fpl_api_client import (  # noqa: E402
    get_bootstrap,
    get_fixture_difficulty_map,
    get_fixtures,
)
from fpl_captain_engine import calculate_captain_score  # noqa: E402
from fpl_pipeline.context import _build_team_fixtures  # noqa: E402
from fpl_tool_contract.scoring_core import (  # noqa: E402
    _derive_base_scoring_inputs,
    captain_pool_elements,
)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _measure(bootstrap_path: Path, out_path: Path) -> list[dict[str, Any]]:
    bootstrap_bytes = bootstrap_path.read_bytes()
    bootstrap = json.loads(bootstrap_bytes)
    bootstrap_sha256 = hashlib.sha256(bootstrap_bytes).hexdigest()
    fdr_map = bootstrap.get("fixture_difficulty_map", {})

    rows: list[dict[str, Any]] = []
    for element in captain_pool_elements(bootstrap):
        inputs = _derive_base_scoring_inputs(element, fdr_map)
        score = round(
            calculate_captain_score(
                inputs["form"],
                inputs["fixture_difficulty"],
                inputs["xgi_per_90"],
                inputs["minutes_risk"],
            ),
            2,
        )
        rows.append(
            {
                "bootstrap_sha256": bootstrap_sha256,
                "player_id": int(element["id"]),
                "web_name": str(element.get("web_name", "")),
                "minutes": int(element.get("minutes", 0) or 0),
                "starts": int(element.get("starts", 0) or 0),
                "penalties_order": element.get("penalties_order"),
                "form": inputs["form"],
                "xgi_per_90": inputs["xgi_per_90"],
                "minutes_risk": inputs["minutes_risk"],
                "captain_score": score,
            }
        )

    rows.sort(key=lambda row: (-row["captain_score"], row["player_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    _write_bytes(
        out_path,
        b"".join(_canonical_bytes(row) for row in rows),
    )
    return rows


def _capture(gameweek: int, bootstrap_path: Path, out_path: Path) -> None:
    bootstrap = get_bootstrap()
    fixtures = get_fixtures(gameweek)
    bootstrap["fixture_difficulty_map"] = get_fixture_difficulty_map(fixtures, bootstrap)
    bootstrap["team_fixtures"] = _build_team_fixtures(
        {gameweek: fixtures}, bootstrap
    )
    _write_bytes(bootstrap_path, _canonical_bytes(bootstrap))
    rows = _measure(bootstrap_path, out_path)
    print(f"captured={bootstrap_path} rows={len(rows)} out={out_path}")
    print(f"bootstrap_sha256={rows[0]['bootstrap_sha256'] if rows else '<empty>'}")


def _load_rows(path: Path) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        player_id = int(row["player_id"])
        if player_id in rows:
            raise ValueError(f"duplicate player_id={player_id} in {path}")
        rows[player_id] = row
    return rows


def _compare(before_path: Path, after_path: Path) -> int:
    before = _load_rows(before_path)
    after = _load_rows(after_path)
    reasons: list[str] = []
    if set(before) != set(after):
        reasons.append("player sets differ")

    increased_risk = 0
    for player_id in sorted(set(before) & set(after)):
        old = before[player_id]
        new = after[player_id]
        old_risk = float(old["minutes_risk"])
        new_risk = float(new["minutes_risk"])
        old_score = float(old["captain_score"])
        new_score = float(new["captain_score"])
        if new_risk < old_risk:
            reasons.append(f"{old['web_name']}: minutes_risk fell")
        elif new_risk > old_risk:
            increased_risk += 1
            if new_score >= old_score:
                reasons.append(f"{old['web_name']}: higher risk did not lower score")
        elif new_score != old_score:
            reasons.append(f"{old['web_name']}: score changed with unchanged risk")

    if increased_risk == 0:
        reasons.append("no player received higher minutes_risk")

    before_haaland = next((row for row in before.values() if row["web_name"] == "Haaland"), None)
    after_haaland = next((row for row in after.values() if row["web_name"] == "Haaland"), None)
    if before_haaland is None or after_haaland is None:
        reasons.append("Haaland missing from one side")
    elif before_haaland["rank"] != after_haaland["rank"]:
        reasons.append(
            "Haaland rank changed "
            f"{before_haaland['rank']}->{after_haaland['rank']}"
        )

    verdict = "PROCEED" if not reasons else "STOP_AND_INVESTIGATE"
    print(f"changed_risk_players={increased_risk}")
    print(f"VERDICT={verdict}")
    for reason in reasons:
        print(f"  - {reason}")
    return 0 if not reasons else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--gameweek", required=True, type=int)
    capture.add_argument("--bootstrap", required=True, type=Path)
    capture.add_argument("--out", required=True, type=Path)

    measure = subparsers.add_parser("measure")
    measure.add_argument("--bootstrap", required=True, type=Path)
    measure.add_argument("--out", required=True, type=Path)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--before", required=True, type=Path)
    compare.add_argument("--after", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "capture":
        _capture(args.gameweek, args.bootstrap, args.out)
        return 0
    if args.command == "measure":
        rows = _measure(args.bootstrap, args.out)
        print(f"rows={len(rows)} out={args.out}")
        print(f"bootstrap_sha256={rows[0]['bootstrap_sha256'] if rows else '<empty>'}")
        return 0
    return _compare(args.before, args.after)


if __name__ == "__main__":
    raise SystemExit(main())
