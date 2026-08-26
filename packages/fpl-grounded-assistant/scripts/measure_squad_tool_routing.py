"""i39 follow-up (board card i40 partition): verify that ``get_my_squad``
(PR #167, merged) actually gets picked for Group A -- the 21 of 31 no-tool
turns from the 2026-08-23 routing measurement that depend on the user's own
squad, previously served by no tool at all.

MEASUREMENT ONLY. No product code is edited or imported for mutation -- this
reuses measure_tool_routing.run_one() (and its cost/tool-sequence helpers)
completely unchanged, calling ask_orchestrated() exactly the way the original
routing measurement already does.

The one addition: a "team connected" condition. ask_orchestrated() itself has
no team_id parameter -- the real injection site is harness.ask_v2(team_id=...),
which builds a *shallow copy* of the bootstrap with bootstrap["_my_team_id"]
set (see get_my_squad.py's docstring). This script reproduces that one
mutation directly on a copy of the frozen bootstrap, because the existing
routing harness calls ask_orchestrated() directly and bypasses ask_v2()
entirely (same as the original 2026-08-23 measurement did) -- going through
ask_v2()/decision_router would pull in routing/prompt branches that have
nothing to do with what is being measured here. get_my_squad only ever reads
bootstrap.get("_my_team_id"); it does not care how that key was set, so this
is faithful to what a real connected-team request looks like from the tool's
point of view.

Caveat worth stating up front (also in the field note): get_my_squad's live
fetch (fpl_api_client.get_entry_picks) hits the real FPL API regardless of the
bootstrap being a frozen 2026-08-18 snapshot. The frozen bootstrap's
_current_gw_from_events() resolves to GW1 (no event has is_current=True in a
pre-season freeze, so it falls back to the earliest event id) -- and GW1 has
long since finished on the live API, so the fetch succeeds and returns GW1's
real historical picks for whatever team id is injected. A "fecha 2/3" question
still resolves against the frozen GW1, then get_my_squad's own future-gw
clamp (gw > current_gw) pulls any explicit gw=2/3 the model passes back down
to GW1 too -- so no request in this run should ever 404 on gw mismatch alone.
team_id=1 (a long-lived, always-public low FPL entry id) is used for the
"connected" condition; verified live before this run that it returns 15 picks
for gw=1, and that an obviously-bad id (999999999) 404s as expected (used
separately for the failure-mode check, not in the main sweep).

Usage (from packages/fpl-grounded-assistant, same import setup as
measure_tool_routing.py):

    python scripts/measure_squad_tool_routing.py \
        --out field-notes/artifacts/squad-tool-routing-observations-2026-08-26.jsonl \
        --reps 5
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402  (path insert must precede this)

#: The connected-team id used for every "team_connected" condition call.
#: Live-verified before this run: returns 15 real picks for gw=1, is a
#: long-lived low FPL entry id (unlikely to ever be deleted).
TEAM_ID = 1

#: Group A -- previously-no-tool turns that depend on the user's own squad
#: (get_my_squad should now serve them). Numbers in the comment are the
#: no-tool count out of 5 reps from the 2026-08-23 measurement.
GROUP_A_IDS = [
    "sb-02",   # 5/5
    "sb-13",   # 5/5
    "cvg-02",  # 5/5
    "cvg-11",  # 2/5
    "cvg-12",  # 2/5
    "cvg-03",  # 1/5
    "ad-05",   # 1/5
]

#: Group B -- control. Must stay put; these are the real i40 (model answers
#: from memory although get_current_gameweek exists) and have nothing to do
#: with get_my_squad.
GROUP_B_IDS = ["gw-05", "gw-09"]

#: Ad-hoc negative controls: no personal reference at all, verbatim from the
#: measurement task. Not in tool_routing_corpus.py (that corpus predates
#: get_my_squad), so declared here in the same shape run_one() expects.
NEGATIVE_CONTROLS: list[dict[str, Any]] = [
    {
        "id": "neg-defensas", "family": "negative_control", "control": False,
        "question": "¿Qué defensas baratos hay?",
        "acceptable_tools": ["get_transfer_suggestion", "rank_players_by_metric"],
    },
    {
        "id": "neg-comparar", "family": "negative_control", "control": False,
        "question": "Compara Haaland y Salah",
        "acceptable_tools": ["compare_players", "rank_captain_candidates"],
    },
    {
        "id": "neg-jornada", "family": "negative_control", "control": False,
        "question": "¿Cuál es la jornada actual?",
        "acceptable_tools": ["get_current_gameweek", "get_gameweek_context"],
    },
]

CONDITIONS = ["team_connected", "no_team"]


def _questions_by_id(ids: list[str]) -> list[dict[str, Any]]:
    from tool_routing_corpus import CORPUS

    by_id = {q["id"]: q for q in CORPUS}
    missing = [qid for qid in ids if qid not in by_id]
    if missing:
        raise SystemExit(f"question ids not found in tool_routing_corpus.CORPUS: {missing}")
    return [by_id[qid] for qid in ids]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--out", required=True)
    parser.add_argument("--log-file", default=None, help="path to write provider-event log lines to (for provider confirmation)")
    args = parser.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")

    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set (checked env + .env); aborting before any paid call.", file=sys.stderr)
        return 2

    log_path = Path(args.log_file) if args.log_file else Path(args.out).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    logging.getLogger("fpl_grounded_assistant").addHandler(file_handler)
    logging.getLogger("fpl_grounded_assistant").setLevel(logging.INFO)

    questions = _questions_by_id(GROUP_A_IDS + GROUP_B_IDS) + NEGATIVE_CONTROLS

    raw_bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    bootstrap_no_team = raw_bootstrap
    bootstrap_team_connected = dict(raw_bootstrap)
    bootstrap_team_connected["_my_team_id"] = TEAM_ID
    assert "_my_team_id" not in bootstrap_no_team, "no-team bootstrap must stay untouched"

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_calls = len(questions) * len(CONDITIONS) * args.reps
    print(
        f"Running {len(questions)} questions x {len(CONDITIONS)} conditions x {args.reps} reps "
        f"= {total_calls} calls against {base.PROVIDER}/{base.MODEL}. Appending to {out_path}",
        file=sys.stderr,
    )

    n_done = 0
    n_exceptions = 0
    total_cost = 0.0
    with out_path.open("a", encoding="utf-8") as fh:
        for condition in CONDITIONS:
            bootstrap = bootstrap_team_connected if condition == "team_connected" else bootstrap_no_team
            for q in questions:
                for rep in range(args.reps):
                    obs = base.run_one(q, rep, bootstrap, api_key)
                    obs["condition"] = condition
                    obs["team_id"] = TEAM_ID if condition == "team_connected" else None
                    fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                    fh.flush()
                    n_done += 1
                    if obs["exception"] is not None:
                        n_exceptions += 1
                    total_cost += obs["cost_usd"]
                    if n_done % 25 == 0 or n_done == total_calls:
                        print(
                            f"  {n_done}/{total_calls} done, {n_exceptions} exceptions so far, "
                            f"${total_cost:.4f} so far",
                            file=sys.stderr,
                        )

    print(
        f"DONE. {n_done} observations written, {n_exceptions} exceptions, total cost ${total_cost:.4f}",
        file=sys.stderr,
    )
    return 0 if n_exceptions == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
