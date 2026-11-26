"""How many StrikerAPI shooters resolve with the EXISTING store-name resolver.

Reads saved get_shot_map captures from a local folder (never committed, no call to the
vendor) and the public FPL bootstrap, runs ``resolve_store_player`` on every distinct
shooter name, and prints the counts and the misses. No alias is added here.

Usage: python scripts/measure_strikerapi_identity.py <packages dir> <captures dir> [glob]
"""
import glob
import html
import json
import os
import sys

PK = os.path.abspath(sys.argv[1])
sys.path[:0] = [os.path.join(PK, p) for p in (
    "fpl-grounded-assistant", "fpl-data-core", "fpl-api-client", "fpl-player-registry",
    "fpl-query-tools", "fpl-tool-contract", "fpl-tool-runner", "fpl-captain-engine",
    "football-data-contract", "fpl-tactical")]
import requests  # noqa: E402

from fpl_grounded_assistant.zonal_weakness_tool import resolve_store_player  # noqa: E402

pattern = sys.argv[3] if len(sys.argv) > 3 else "*.json"
shots_by_name: dict[str, int] = {}
for path in sorted(glob.glob(os.path.join(sys.argv[2], pattern))):
    data = json.load(open(path, encoding="utf-8")).get("data")
    if not isinstance(data, dict) or "shots" not in data:
        continue
    for s in data["shots"]:
        name = html.unescape(str(s.get("player")))
        shots_by_name[name] = shots_by_name.get(name, 0) + 1

boot = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=60).json()
resolved, missed = {}, {}
for name, n in shots_by_name.items():
    el = resolve_store_player(name, boot)
    (resolved if el else missed)[name] = n

total_shots = sum(shots_by_name.values())
print(f"distinct shooters {len(shots_by_name)}; resolved {len(resolved)}; missed {len(missed)}")
print(f"shots covered {sum(resolved.values())} of {total_shots} "
      f"({100 * sum(resolved.values()) / max(total_shots, 1):.1f} %)")
for name, n in sorted(missed.items(), key=lambda kv: -kv[1]):
    print(f"  MISS {name} ({n} shots)")
