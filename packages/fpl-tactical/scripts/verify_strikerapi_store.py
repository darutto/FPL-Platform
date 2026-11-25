"""Fail unless the StrikerAPI working store is a validated one (workflow step)."""

from __future__ import annotations

import argparse
import json
import sys

from fpl_tactical.paths import SOURCE_STRIKERAPI, source_pointer_path, source_shots_path
from fpl_tactical.publish import _check_strikerapi_pair


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    args = ap.parse_args()
    pointer = source_pointer_path(args.season, SOURCE_STRIKERAPI)
    try:
        _check_strikerapi_pair(pointer, source_shots_path(args.season, SOURCE_STRIKERAPI))
    except Exception as exc:  # noqa: BLE001
        print(f"verify FAILED: {exc}", file=sys.stderr)
        return 1
    p = json.loads(pointer.read_text(encoding="utf-8"))
    print(f"{p['n_matches']} matches, {p['n_shots']} shots, through GW {p.get('data_through_gw')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
