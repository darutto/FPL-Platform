"""
T2c end-to-end smoke: real tactical store → zonal-weakness engine.

Loads the owned 2025/26 parquet (run `python -m fpl_tactical.cli ingest`
first if absent), prints Crystal Palace's verdict + weakest zones, and the
league's most-vulnerable defences per in-box flank. Must reproduce the PoC
qualitative result (2026-07-02): Palace leak down THEIR right (attacker's
left); Sunderland / Aston Villa down their left (attacker's right).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PKGS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PKGS / "fpl-tactical"))

# Load the engine directly from its file (repo test convention — avoids the
# fpl_grounded_assistant/__init__ dispatcher/harness graph).
_ENGINE = _PKGS / "fpl-grounded-assistant" / "fpl_grounded_assistant" / "zonal_weakness.py"
_spec = importlib.util.spec_from_file_location("zonal_weakness", _ENGINE)
zw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zw)

from fpl_tactical import store  # noqa: E402
from fpl_tactical.paths import CURRENT_SEASON  # noqa: E402

shots = store.read_shots(CURRENT_SEASON)
if shots is None:
    sys.exit("No tactical store — run: python -m fpl_tactical.cli ingest")

print(f"store: {len(shots)} shots, {shots['match_id'].nunique()} matches\n")

out = zw.get_zonal_weakness("Crystal Palace", store=shots)
print(f"=== {out['team']} ===")
print(f"verdict: {out['verdict']}")
for z in out["weakest_zones"]:
    print(f"  {z['zone']:22} xGA/g {z['xga_per_game']:.3f}  "
          f"avg {z['league_avg']:.3f}  delta {z['delta_vs_avg']:+.3f}  rank {z['rank']}")
print(f"  penalty context: {out['penalty_context']}\n")

profiles = zw.compute_team_zone_profiles(shots)
baseline = zw.compute_league_baseline(profiles)
for zone, defenders_side in (("in-box / left", "their RIGHT (attacker's left)"),
                             ("in-box / right", "their LEFT (attacker's right)")):
    rows = sorted(
        ((p[zone]["xga"] / p[zone]["games"] - baseline[zone], team)
         for team, p in profiles.items()),
        reverse=True,
    )[:3]
    print(f"most vulnerable down {defenders_side}:")
    for delta, team in rows:
        print(f"  {team:26} {delta:+.3f} vs avg")
    print()

opp = zw.get_zonal_opportunity("Crystal Palace", store=shots)
print("opportunity vs Crystal Palace:")
for o in opp["opportunities"]:
    print(f"  {o['zone']:22} delta {o['delta_vs_avg']:+.3f}  players: {', '.join(o['players'])}")
