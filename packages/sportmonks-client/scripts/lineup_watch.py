"""Watch every Premier League fixture of a date window and log when lineups change (provisional -> confirmed).

usage: python scripts/lineup_watch.py START_UTC END_UTC OUT.ndjson [FIRST_POLL_UTC]
One request per poll (fixtures/between with lineups, formations, state) for all fixtures of the window.
Cadence: every 5 minutes while any not-yet-started fixture kicks off within the next 4 hours (or started
less than 10 minutes ago); every 20 minutes otherwise. Stops 15 minutes after the last kickoff and writes
``OUT.ndjson.done``, which ``ensure_watcher.py`` reads as "finished, do not relaunch".
Needs ``SPORTMONKS_API_TOKEN`` in the environment. Local only: the output carries player ids and is never
committed (``trial-output/`` is gitignored). Launch it through ``ensure_watcher.py``.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportmonks_client.client import SportmonksClient  # noqa: E402
from sportmonks_client.errors import SportmonksError  # noqa: E402

FMT = "%Y-%m-%dT%H:%M:%SZ"


def _parse(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)


def main(argv: list[str]) -> int:
    start, end, out = argv[0], argv[1], argv[2]
    first = dt.datetime.strptime(argv[3], FMT).replace(tzinfo=dt.timezone.utc) if len(argv) > 3 else None
    client = SportmonksClient()
    kickoffs: dict[int, tuple[dt.datetime, str]] = {}
    while first and dt.datetime.now(dt.timezone.utc) < first:
        time.sleep(60)
    while True:
        rows: list[dict] = []
        try:
            page = 1
            while True:
                body = client._request(
                    f"fixtures/between/{start[:10]}/{end[:10]}",
                    {"filters": "fixtureLeagues:8", "include": "lineups.detailedPosition;formations;state",
                     "per_page": 50, "page": page}).body
                rows += body["data"]
                if not (body.get("pagination") or {}).get("has_more"):
                    break
                page += 1
        except SportmonksError as exc:
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).strftime(FMT),
                                     "error": str(exc)[:80]}) + "\n")
            time.sleep(300)
            continue
        # Stamped when the answer is in hand, never before the request: a machine that sleeps mid-request
        # would otherwise label an after-the-match answer with a before-the-match time.
        now = dt.datetime.now(dt.timezone.utc)
        with open(out, "a", encoding="utf-8") as fh:
            for d in rows:
                kickoff = _parse(d["starting_at"])
                kickoffs[d["id"]] = (kickoff, d["state"]["developer_name"])
                starters = sorted([l["team_id"], l["player_id"], l["formation_field"]]
                                  for l in d["lineups"] if l["type_id"] == 11)
                fh.write(json.dumps({
                    "at": now.strftime(FMT), "fixture_id": d["id"], "name": d["name"],
                    "kickoff": kickoff.strftime(FMT),
                    "minutes_to_kickoff": round((kickoff - now).total_seconds() / 60),
                    "state": d["state"]["developer_name"],
                    "lineup_rows": len(d["lineups"]), "starters": len(starters),
                    "bench": sum(1 for l in d["lineups"] if l["type_id"] != 11),
                    "starters_list": starters, "row_ids": sorted(l["id"] for l in d["lineups"]),
                    "formations": sorted([f["participant_id"], f["formation"]] for f in d["formations"]),
                }) + "\n")
        pending = [k for k, _ in kickoffs.values()]
        if not pending or now > max(pending) + dt.timedelta(minutes=15):
            break
        soon = any(-10 <= (k - now).total_seconds() / 60 <= 240 for k, _ in kickoffs.values())
        time.sleep(300 if soon else 1200)
    Path(out + ".done").write_text("finished", encoding="utf-8")
    print("watch finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
