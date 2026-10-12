"""One end-to-end FI-9 criterion-(f) run: mapping -> capture -> stores -> features -> M1/M2/M3 checks.

usage: python scripts/run_trial_checks.py TAG HOLDOUT_GW [M3_UNTIL_GW] [--leo-entry ID] [--force] [--no-update]

Run it from the checkout that holds ``trial-output/`` (the local, gitignored data). It writes
``trial-output/runs/TAG/`` and, only when every step succeeded, the marker ``trial-output/runs/TAG/DONE``.
A TAG that already has the marker is **not** run again and spends no request (use ``--force`` to redo it).
Before any capture it asks the provider whether all 10 fixtures of the hold-out gameweek are finished
(8 requests at most) and stops with exit code 3 if not, so a run cannot be wasted on an unfinished gameweek.
Needs ``SPORTMONKS_API_TOKEN``; it never prints it. Raw captures stay local and are never committed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

PKG = Path(__file__).resolve().parent.parent
REPO = PKG.parents[1]
FI = REPO / "packages" / "football-intelligence"
EXIT_NOT_FINISHED = 3
ACK = ["--live", "--i-understand-this-is-live"]

PRECHECK = """
import sys
from collections import Counter
sys.path.insert(0, {scripts!r})
from _trial_common import make_client, MODE_LIVE
c = make_client(MODE_LIVE)
state = Counter()
for r in c.iter_entities("fixtures", params={{"filters": "fixtureSeasons:28083;fixtureLeagues:8", "include": "round;state", "per_page": 50}}, max_pages=9):
    f = r.raw_fields
    if (f.get("round") or {{}}).get("name") == "{gw}":
        state[(f.get("state") or {{}}).get("developer_name")] += 1
done = sum(n for k, n in state.items() if k in ("FT", "AET", "FT_PEN"))
print("GW{gw} states:", dict(state), flush=True)
sys.exit(0 if done == 10 else {code})
"""

BUILD = """
import pathlib, time, json
from football_intelligence.ingestion import live_trial as lt
from football_intelligence.features.store_v2 import build_features_v2
from football_intelligence.features.registry_v2 import ROLE_MAPPING_VERSION_V3
root = pathlib.Path({store!r})
stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
rep = lt.build_store(pathlib.Path({capture!r}), root, captured_at=stamp)
print(json.dumps({{k: rep[k] for k in ("teams", "fixtures_total", "context_row_counts")}}), flush=True)
base = lt.LiveTrialBuildHandle(root / "v1/premier-league")
build_features_v2(base, root / "context/builds-v2/live-trial", root / "features", feature_build_id="live-trial",
                  built_at=stamp, role_map_version=ROLE_MAPPING_VERSION_V3, assumption_status="live_trial_local")
"""


def sh(cmd: Sequence[object], cwd: Path, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a step; exit codes 0 and 1 are results (a check can fail honestly), anything else stops the run."""
    started = time.time()
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env={**os.environ, "PYTHONIOENCODING": "utf-8", **(extra or {})},
                       capture_output=True, text=True)
    print(f"[{round(time.time() - started)}s] {' '.join(str(c) for c in cmd)[:110]} -> {r.returncode}", flush=True)
    if r.returncode not in (0, 1):
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit(f"step failed: {cmd}")
    return r


def gameweek_finished(gw: int) -> bool:
    code = PRECHECK.format(scripts=str(PKG / "scripts"), gw=gw, code=EXIT_NOT_FINISHED)
    r = subprocess.run([sys.executable, "-c", code], cwd=PKG, capture_output=True, text=True,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(PKG)})
    print(r.stdout.strip(), flush=True)
    return r.returncode == 0


def run(tag: str, gw: int, m3_until: int = 7, *, leo_entry: str | None = None, force: bool = False,
        update: bool = True, runner: Callable = sh, finished: Callable[[int], bool] = gameweek_finished,
        pkg: Path = PKG, fi: Path = FI) -> str:
    """Returns ``already_done``, ``not_finished`` or ``done``."""
    run_dir = pkg / "trial-output" / "runs" / tag
    marker = run_dir / "DONE"
    if marker.exists() and not force:
        return "already_done"
    if update:   # keep the code current; untracked local data is untouched
        runner(["git", "fetch", "-q", "origin"], pkg.parents[1])
        runner(["git", "checkout", "-q", "--detach", "origin/main"], pkg.parents[1])
    if not finished(gw):
        return "not_finished"
    run_dir.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    live_env = {"PYTHONPATH": str(pkg)}
    runner([sys.executable, "scripts/trial_mapping.py", *ACK], pkg, live_env)
    previous = pkg / "trial-output/capture/capture.json"
    if previous.exists():
        shutil.copy(previous, run_dir / "capture.previous.json")
    runner([sys.executable, "scripts/live_capture.py", *ACK], pkg, live_env)
    capture = run_dir / "capture.json"
    shutil.copy(previous, capture)
    fi_env = {"PYTHONPATH": os.pathsep.join(str(fi.parent / n) for n in (
        "football-intelligence", "football-data-contract", "football-identity-registry", "sportmonks-client"))}
    store, out = run_dir / "store", run_dir / "out"
    shutil.rmtree(store, ignore_errors=True)
    r = runner([sys.executable, "-c", BUILD.format(store=str(store), capture=str(capture))], fi, fi_env)
    print(r.stdout[-600:])
    cmd = [sys.executable, "-m", "football_intelligence.ingestion.live_trial_checks", "--root", store,
           "--features", store / "features/builds-v2/live-trial", "--capture", capture, "--out", out,
           "--holdout-gameweek", gw, "--m3-until-gameweek", m3_until]
    if leo_entry:
        cmd += ["--leo-entry", leo_entry]
    runner(cmd, fi, fi_env)
    print(json.dumps(json.loads((out / "aggregate.json").read_text(encoding="utf-8")), indent=1)[:9000])
    marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
    return "done"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tag")
    parser.add_argument("holdout_gw", type=int)
    parser.add_argument("m3_until_gw", type=int, nargs="?", default=7)
    parser.add_argument("--leo-entry", default=None)
    parser.add_argument("--force", action="store_true", help="redo a run that already has its DONE marker")
    parser.add_argument("--no-update", action="store_true", help="do not fetch and detach to origin/main first")
    args = parser.parse_args(argv)
    result = run(args.tag, args.holdout_gw, args.m3_until_gw, leo_entry=args.leo_entry, force=args.force,
                 update=not args.no_update)
    print(f"run {args.tag}: {result}")
    return EXIT_NOT_FINISHED if result == "not_finished" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
