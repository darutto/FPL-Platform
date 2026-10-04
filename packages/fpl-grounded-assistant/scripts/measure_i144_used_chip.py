"""i144 gate: a chip already played -- does the served answer still advise keeping it?

Leo's prod capture (2026-10-04): team 68643 played the Wildcard in GW5 and
asked in GW6. The served text opened with i137's «Ya usaste el Wildcard…» but
the body said «conservarlo te permite reaccionar…» and closed with the squad
sentence «Te falta 1 jugador del grupo favorecido…».

This replays that request the way fpl_server does: the UI's squad_context
(chips_used from FPL history + its stale per-season chips_remaining) on a
request-local copy of the bootstrap assembled at startup, ``ask_v2`` with the
linked team id, then ``to_ask_response`` with the same bootstrap. One line per
turn, read off the SERVED text:

* ``keep_advice``    -- advice to keep / save / reserve the chip;
* ``squad_sentence`` -- the i108 particular squad sentence;
* the evaluator verdicts, cost, and which provider/model ran.

Usage (paid): python scripts/measure_i144_used_chip.py OUT.jsonl REPS
              python scripts/measure_i144_used_chip.py --summary FILE [FILE ...]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
from measure_tool_routing import _configure_imports, _load_env_file, cost_usd  # noqa: E402

QUESTION = "¿Uso el Wildcard esta jornada?"
TEAM_ID = 68643
#: What the UI sends for 68643 (FPL history 2026-10-04; chips_remaining is the
#: UI's per-season count, which still lists the wildcard).
SQUAD_CONTEXT = {
    "itb": 5, "free_transfers": 1,
    "chips_remaining": ["wildcard", "free_hit"],
    "chips_used": [{"chip": "bench_boost", "event": 2}, {"chip": "triple_captain", "event": 3},
                   {"chip": "wildcard", "event": 5}],
}

#: Advice to keep / save the chip (folded text). «conservar el banquillo» etc.
#: would not fire: the verb must govern the chip or "lo".
KEEP = re.compile(
    r"\b(?:conservar|conservarlo|conservalo|guardar|guardarlo|guardalo|reservar|reservarlo|reservalo|"
    r"mantenerlo|esperar para usarlo|no lo uses todavia|dejarlo para)\b"
)
SQUAD = re.compile(r"te falta|te faltan|ya tienes el grupo favorecido|enlaza tu equipo")
#: i145: the spent window's remaining gameweeks / end (GW5 Wildcard -> GW2-GW19).
SPENT_REMAIN = re.compile(
    r"quedan \d+ jornadas|\d+ jornadas (?:restantes|por delante)|"
    r"(?:hasta|termina en|cierra en) (?:la )?gw ?19\b|gw ?2 ?(?:-|–|a) ?(?:la )?gw ?19\b|"
    r"ventana (?:actual|activa)[^.]{0,60}(?:gw ?19\b|quedan)"
)
#: i145: windows mixed -- the return described with the spent window's facts.
WINDOW_MIX = re.compile(
    r"(?:cuando|para cuando) (?:regrese|vuelva|vuelve|este disponible)[^.]{0,140}"
    r"(?:gw ?19\b|ventana actual|ventana activa|quedan \d+)"
)
#: reported apart: timing reasoning about the spent window («es pronto dentro de la ventana»).
EARLY_IN_WINDOW = re.compile(r"pronto (?:dentro de|en) (?:la|esta) ventana|inicio de la ventana")


def fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def grade(text: str) -> dict:
    f = fold(text)
    return {"keep_advice": [m.group(0) for m in KEEP.finditer(f)],
            "squad_sentence": [m.group(0) for m in SQUAD.finditer(f)],
            "spent_window_remaining": [m.group(0) for m in SPENT_REMAIN.finditer(f)],
            "window_mix": [m.group(0) for m in WINDOW_MIX.finditer(f)],
            "early_in_window": [m.group(0) for m in EARLY_IN_WINDOW.finditer(f)],
            "opens_with_used": f.startswith("ya usaste el wildcard")}


def summary(paths: list[str]) -> int:
    for p in paths:
        rows = [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:      # recomputed from the served text with the current detectors
            r.update(grade(r["final_text"]))
        n = len(rows)
        print(json.dumps({
            "arm": Path(p).name, "turns": n,
            "keep_advice_rows": sum(bool(r["keep_advice"]) for r in rows),
            "squad_sentence_rows": sum(bool(r["squad_sentence"]) for r in rows),
            "spent_window_remaining_rows": sum(bool(r["spent_window_remaining"]) for r in rows),
            "window_mix_rows": sum(bool(r["window_mix"]) for r in rows),
            "early_in_window_rows": sum(bool(r["early_in_window"]) for r in rows),
            "opens_with_used": sum(r["opens_with_used"] for r in rows),
            "rejected_rows": sum(r["rejected"] for r in rows),
            "usd_per_turn": round(sum(r["usd_cost_estimate"] for r in rows) / n, 5) if n else None,
        }))
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--summary":
        return summary(argv[1:])
    out_path, reps = Path(argv[0]), int(argv[1])
    _configure_imports()
    sys.path.insert(0, str((PACKAGE_ROOT / ".." / "fpl-pipeline").resolve()))
    sys.path.insert(0, str(PACKAGE_ROOT))
    _load_env_file(PACKAGE_ROOT / ".env")

    from fpl_pipeline import assemble_captain_context
    from fpl_grounded_assistant import harness, harness_adapter
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_server import AskRequest

    startup = assemble_captain_context()["bootstrap"]
    verdicts: list[dict] = []
    real_evaluate = orch_mod.evaluate_response

    def _recording(**kwargs):
        v = real_evaluate(**kwargs)
        verdicts.append({"approved": v.approved, "retry_feedback": v.retry_feedback})
        return v

    orch_mod.evaluate_response = _recording
    model = os.environ.get("FPL_ORCH_MODEL")
    provider = os.environ.get("FPL_ORCH_PROVIDER")
    spent = 0.0
    with out_path.open("a", encoding="utf-8") as f:
        for rep in range(reps):
            verdicts.clear()
            t0 = time.monotonic()
            turn = dict(startup)
            turn["_squad_context"] = dict(SQUAD_CONTEXT)
            v2 = harness.ask_v2(QUESTION, turn, team_id=TEAM_ID)
            req = AskRequest(question=QUESTION, squad_context=dict(SQUAD_CONTEXT), team_id=TEAM_ID)
            resp = harness_adapter.to_ask_response(v2, req, turn)
            tok = v2.get("tokens") or {}
            cost = ((cost_usd(tok.get("primary_input", 0), tok.get("primary_output", 0),
                              tok.get("primary_cache_read", 0), model=model, provider=provider) or 0.0)
                    + (cost_usd(tok.get("retry_input", 0), tok.get("retry_output", 0),
                                tok.get("retry_cache_read", 0), model=model, provider=provider) or 0.0)
                    + (cost_usd(tok.get("evaluator", 0), 0, 0, model=model, provider=provider) or 0.0))
            spent += cost
            chip_out = v2.get("raw_output") if v2.get("selected_tool") == "get_chip_advice" else None
            row = {
                "rep": rep, "question": QUESTION, "provider": provider, "model": model,
                "outcome": v2.get("outcome"), "selected_tool": v2.get("selected_tool"),
                "chip_availability": (chip_out or {}).get("chip_availability"),
                "chip_unavailable": (resp.chip or {}).get("chip_unavailable") if resp.chip else None,
                "rejected": any(not v["approved"] for v in verdicts),
                "evaluator_feedback": [v["retry_feedback"] for v in verdicts if not v["approved"]],
                "final_text": resp.final_text, **grade(resp.final_text),
                "usd_cost_estimate": round(cost, 6), "latency_s": round(time.monotonic() - t0, 1),
            }
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            print(f"r{rep}: used_lead={row['opens_with_used']} keep={bool(row['keep_advice'])} "
                  f"squad={bool(row['squad_sentence'])} rej={row['rejected']} spent~${spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
