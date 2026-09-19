"""i102 prod check: a /fixtures cell tap returns the calendar card over HTTP.

Rebuilds the cell phrase the UI sends (same builder as verify_i93_composed_prod)
for the LIVE fixture of (team, current+lead), sends it by POST /ask and, with a
fresh session, by POST /session/{id}/ask, and asserts from the JSON bodies:

* ``fixture_outlook`` is non-null on BOTH routes (pre-i102 backends: null on
  both -- the field did not exist);
* it names the asked team and carries a non-empty ``series``;
* the two routes serve the same payload.

Usage:
    python scripts/verify_i102_fixture_outlook_prod.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --user-id i102-verify-$(date +%Y%m%d%H%M) --team Arsenal --lead 1

Exit 0 when every check holds; 1 otherwise. Costs 2 orchestrated turns (one
per route) on a free-tier id (5/day by /ask, ~4 by session -- i99).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_i93_composed_prod import live_cell  # noqa: E402


def _post(url: str, path: str, user_id: str, question: str) -> dict:
    resp = requests.post(f"{url.rstrip('/')}{path}",
                         headers={"Content-Type": "application/json", "X-User-Id": user_id},
                         json={"question": question, "debug": True}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--team", default="Arsenal")
    ap.add_argument("--lead", type=int, default=1)
    ap.add_argument("--jsonl", default=None, help="append the raw bodies here")
    a = ap.parse_args()

    cell = live_cell(a.team, a.lead, top_n=3)
    print(f"cell: {cell['team']} GW{cell['gw']} (current {cell['current_gw']})\n  {cell['question']}")
    version = requests.get(f"{a.url.rstrip('/')}/version", timeout=30).json()
    print(f"prod /version: {version}")

    ask = _post(a.url, "/ask", a.user_id, cell["question"])
    sid = requests.post(f"{a.url.rstrip('/')}/session", headers={"X-User-Id": a.user_id}, json={}, timeout=30).json()["session_id"]
    sess = _post(a.url, f"/session/{sid}/ask", a.user_id, cell["question"])
    if a.jsonl:
        with open(a.jsonl, "a", encoding="utf-8") as fh:
            for route, body in (("/ask", ask), ("/session", sess)):
                fh.write(json.dumps({"route": route, "version": version, "cell": cell, "response": body}, ensure_ascii=False) + "\n")

    ok = True
    for route, body in (("/ask", ask), ("/session/{id}/ask", sess)):
        fo = body.get("fixture_outlook")
        teams = [t.get("team_short") for t in ((fo or {}).get("teams") or [])]
        series_len = len(((fo or {}).get("teams") or [{}])[0].get("series") or []) if fo else 0
        line = (f"{route}: intent={body.get('intent')!r} selected_tool={(body.get('debug') or {}).get('selected_tool')!r} "
                f"fixture_outlook={'present' if fo else 'NULL'} teams={teams} series_len={series_len}")
        good = bool(fo) and bool(teams) and series_len > 0
        print(("  OK   " if good else "  FAIL ") + line)
        ok &= good
    same = ask.get("fixture_outlook") == sess.get("fixture_outlook")
    print(("  OK   " if same else "  FAIL ") + f"both routes serve the same fixture_outlook payload: {same}")
    ok &= same
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
