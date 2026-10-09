"""Bloque 10, fase 0: does a GENERAL named-player question reach get_player_snapshot?

MEASUREMENT ONLY -- real paid calls through the shared ``run_one``
(measure_tool_routing.py: pinned openai/gpt-5.6-luna). The corpus is inline
and its SHA256 is stamped on every row. Bootstrap is the 2026-10-08 live
snapshot (field-notes/artifacts/b10-bootstrap-2026-10-08.json).

Usage (from packages/fpl-grounded-assistant):
    python scripts/measure_b10_player_general_routing.py \
        --out field-notes/artifacts/b10-phase0-routing-before.jsonl --reps 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import measure_tool_routing as base  # noqa: E402

BOOTSTRAP = base.REPO_ROOT / "field-notes" / "artifacts" / "b10-bootstrap-2026-10-08.json"
SNAP = ["get_player_snapshot"]


def _q(qid, family, question, acceptable, control=False):
    return {"id": qid, "family": family, "question": question,
            "acceptable_tools": acceptable, "control": control}


CORPUS = [
    # General named-player questions: the gate (must open the snapshot card).
    _q("g-01", "general", "Háblame de Cole Palmer", SNAP),
    _q("g-02", "general", "¿Cómo está Haaland?", SNAP),
    _q("g-03", "general", "Cuéntame sobre Bukayo Saka", SNAP),
    _q("g-04", "general", "Dame información de Bruno Fernandes", SNAP),
    _q("g-05", "general", "¿Qué tal va Erling Haaland esta temporada?", SNAP),
    # Ambiguous name: the pick wizard must survive (Cole vs Alex Palmer).
    _q("a-01", "ambiguous", "Háblame de Palmer", SNAP),
    # Recommendation questions: recorded apart, not part of the gate.
    _q("r-01", "recommendation", "¿Vale la pena fichar a Cole Palmer?", SNAP + ["get_player_zonal_outlook"]),
    _q("r-02", "recommendation", "¿Me conviene vender a Haaland?", SNAP + ["get_player_zonal_outlook"]),
    # Controls from other families: must not move.
    _q("c-01", "control_zonal", "¿Le vienen bien los próximos rivales a Cole Palmer?",
       ["get_player_zonal_outlook"], True),
    _q("c-02", "control_history", "¿Cuántos puntos hizo Haaland en las últimas 5 jornadas?",
       ["get_player_history"], True),
    _q("c-03", "control_fixtures", "¿Contra quién juega el Chelsea en las próximas 3 fechas?",
       ["get_team_schedule"], True),
    _q("c-04", "control_ranking", "¿Quiénes son los 5 delanteros con más xG por 90?",
       ["rank_players_by_metric"], True),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", default=None, help="comma-separated question ids")
    ap.add_argument("--cap-usd", type=float, default=1.5)
    a = ap.parse_args(argv)
    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    key = base.require_api_key(base.PROVIDER)
    qs = [q for q in CORPUS if not a.only or q["id"] in a.only.split(",")]
    n = len(qs) * a.reps
    est = round(n * (0.11 / 84) * 3, 3)
    sha = {
        "corpus": hashlib.sha256(json.dumps(CORPUS, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "bootstrap": hashlib.sha256(BOOTSTRAP.read_bytes()).hexdigest(),
    }
    from fpl_grounded_assistant.tool_schema_registry import get_tool_schema
    sha["snapshot_description"] = hashlib.sha256(
        get_tool_schema("get_player_snapshot").description.encode()).hexdigest()[:16]
    print(f"{len(qs)} phrases x {a.reps} = {n} calls on {base.PROVIDER}/{base.MODEL}; "
          f"est ${est} cap ${a.cap_usd}", file=sys.stderr)
    if est > a.cap_usd:
        return 2
    boot = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows, exc = [], 0
    with out.open("a", encoding="utf-8") as fh:
        for q in qs:
            for r in range(a.reps):
                o = base.run_one(q, r, boot, key)
                o["corpus_sha256"] = sha
                fh.write(json.dumps(o, ensure_ascii=False) + "\n")
                fh.flush()
                rows.append(o)
                exc += o["exception"] is not None
    print(f"DONE {len(rows)} rows, {exc} exceptions, spend {base.format_spend(rows)}", file=sys.stderr)
    return 0 if not exc else 3


if __name__ == "__main__":
    raise SystemExit(main())
