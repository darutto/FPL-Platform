"""Measure the frozen captaincy pool through its fixture-aware public seam.

MEASUREMENT ONLY. This companion exists because the first frozen script calls
the two-argument base primitive; after Slice 3 that call correctly exercises
the explicit no-fixture degradation path and therefore cannot observe the
participation change. Neither script is edited after its pre-change run.

Pre-registered expectation and decision rule
--------------------------------------------
Using the exact bootstrap frozen by Slice 0, players below full reliable
participation are expected to receive higher minutes risk and lower captain
scores; full participants are expected to keep their scores; no risk may fall;
and Haaland is expected to keep the same rank. The Haaland check applies only
to this snapshot. Compare the resulting JSONL files with the already-frozen
``measure_captaincy_scoring_inputs.py compare`` command. Its PROCEED / STOP rule
is unchanged and was committed before either post-change run.
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

from fpl_captain_engine import calculate_captain_score  # noqa: E402
from fpl_grounded_assistant.scoring_shared import _derive_scoring_inputs  # noqa: E402
from fpl_tool_contract.scoring_core import (  # noqa: E402
    captain_pool_elements,
    captain_time_context,
)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def measure(bootstrap_path: Path, out_path: Path) -> list[dict[str, Any]]:
    bootstrap_bytes = bootstrap_path.read_bytes()
    bootstrap = json.loads(bootstrap_bytes)
    bootstrap_sha256 = hashlib.sha256(bootstrap_bytes).hexdigest()
    fdr_map = bootstrap.get("fixture_difficulty_map", {})
    team_fixtures = bootstrap.get("team_fixtures")
    evaluated_gameweek = captain_time_context(bootstrap)["evaluated_gameweek"]

    rows: list[dict[str, Any]] = []
    for element in captain_pool_elements(bootstrap):
        inputs = _derive_scoring_inputs(
            element,
            fdr_map,
            team_fixtures,
            evaluated_gameweek,
        )
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"".join(_canonical_bytes(row) for row in rows))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    rows = measure(args.bootstrap, args.out)
    print(f"rows={len(rows)} out={args.out}")
    print(f"bootstrap_sha256={rows[0]['bootstrap_sha256'] if rows else '<empty>'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
