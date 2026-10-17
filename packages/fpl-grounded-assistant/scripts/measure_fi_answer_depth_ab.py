"""FI answer-depth A/B (2026-10-18): the same chat, same model, same questions, FPL-only vs FPL+Sportmonks.

MEASUREMENT ONLY -- real paid calls (openai/gpt-5.6-luna pinned for the orchestrator AND the
reference resolver) through the in-process FastAPI app (no server, no port). Nothing here
calls Sportmonks: arm B only READS an already-built local trial store.

Arms
  A  FPL only: FOOTBALL_INTELLIGENCE_ENABLED off, the chat as it runs today.
  B  FPL + Sportmonks: FOOTBALL_INTELLIGENCE_ENABLED on, FPL_FOOTBALL_ROOT at a local
     store, plus the two dev flags owned by ``competition_calendar`` (ENV_ALLOW / ENV_CAPTURE).
     Those flags gate only GET /fixtures/competitions; the FI tools' runtime refuses a
     ``live_trial_local`` store regardless (football_intelligence_runtime._load_runtime).
     Before any paid call, arm B runs a preflight that loads the FI runtime exactly as the
     assistant does. If the runtime refuses the store or cannot load it, the arm is NOT run:
     a blocker file is written and the script exits 3. No guard is bypassed here.

Subcommands
  run      --arm A|B --out-dir DIR [--store DIR] [--capture FILE] [--team-id N] [--cap-usd X]
  freeze   --out-dir DIR            seals answers_<arm>.jsonl into frozen.json + frozen.sha256
  blind    --out-dir DIR            one HTML page per question (Respuesta X / Y, random order),
                                    key in blind_key.json (needs both arms)
  outcomes --out-dir DIR --gw 7     after the matches: pulls FPL /event/7/live + /fixtures and
                                    writes outcomes_gw7.json + a grading sheet with an empty
                                    verdict per Q1-Q10 (the right/wrong call stays human)

Outputs belong in a git-ignored folder (the FI-9 trial-output). The answers of arm B may
contain Sportmonks-derived facts: never commit them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import logging
import os
import random
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import measure_tool_routing as base  # noqa: E402

TEAM_ID_DEFAULT = 68643

#: (id, question, needs_team_id, checkable_by_monday, swap note or None)
QUESTIONS: list[tuple[str, str, bool, bool, str | None]] = [
    ("q01", "¿Bruno Fernandes será titular mañana contra el Leeds?", False, True, None),
    ("q02", "¿Saka juega mañana contra el Nottingham Forest?", False, True, None),
    ("q03", "¿Qué defensa del Arsenal me conviene para el partido contra el Forest?", False, True, None),
    ("q04", "¿El Brighton dejará la portería a cero contra el Crystal Palace?", False, True, None),
    ("q05", "¿Quién tiene más opciones de marcar en el Bournemouth–Sunderland?", False, True, None),
    ("q06", "¿Con qué laterales saldrá el Arsenal en Nottingham?", False, True, None),
    ("q07", "¿Hay algún jugador del Leeds o del Man United que esté jugando en una posición distinta a la de FPL?", False, True, None),
    ("q08", "¿Qué atacante del Arsenal puede aprovechar mejor la defensa del Forest?", False, True, None),
    ("q09", "¿El Tottenham va a rotar el lunes contra el Coventry?", False, True, None),
    ("q10", "¿Qué jugador del Sunderland es un buen diferencial para mañana?", False, True, None),
    ("q11", "¿Es buena idea comprar a Cole Palmer para la jornada 8?", False, False, None),
    ("q12", "¿Haaland o Szoboszlai de capitán en la jornada 8?", False, False,
     "Salah is not in the 2026-10-17 FPL bootstrap; swapped for Liverpool's most-selected MID (Szoboszlai, 21.4%)"),
    ("q13", "¿Qué portero barato tiene más opciones de portería a cero en las próximas 3 jornadas?", False, False, None),
    ("q14", "¿Qué defensas de menos de 5 millones juegan más arriba de lo que dice su posición?", False, False, None),
    ("q15", "Con mi equipo (68643), ¿a quién vendo esta semana?", True, False, None),
]

FI_ENV = "FOOTBALL_INTELLIGENCE_ENABLED"


def _dev_env_names() -> tuple[str, str]:
    """The two dev-flag names, read from their one owner (a test keeps the literal there only)."""
    from fpl_grounded_assistant.competition_calendar import ENV_ALLOW, ENV_CAPTURE  # noqa: PLC0415

    return ENV_ALLOW, ENV_CAPTURE


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pin_env(arm: str, store: str | None, capture: str | None) -> None:
    # Loads OPENAI_API_KEY from the main checkout's .env too (never printed); pins win.
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    main_env = Path(os.environ.get("FPL_AB_ENV_FILE", ""))
    if main_env.is_file():
        base._load_env_file(main_env)
    os.environ["FPL_ORCH_ENABLED"] = "1"
    os.environ["FPL_ORCH_PROVIDER"] = base.PROVIDER
    os.environ["FPL_ORCH_MODEL"] = base.MODEL
    os.environ["DEFAULT_PROVIDER"] = base.PROVIDER
    os.environ["FPL_RESOLVER_PROVIDER"] = base.PROVIDER
    os.environ["FPL_RESOLVER_MODEL"] = base.MODEL
    os.environ.pop("REDIS_URL", None)
    dev_allow, dev_capture = _dev_env_names()
    if arm == "A":
        os.environ[FI_ENV] = "0"
        for k in (dev_allow, dev_capture, "FPL_FOOTBALL_ROOT"):
            os.environ.pop(k, None)
    else:
        os.environ[FI_ENV] = "1"
        os.environ[dev_allow] = "1"
        if capture:
            os.environ[dev_capture] = capture
        if store:
            os.environ["FPL_FOOTBALL_ROOT"] = store


def _preflight_b() -> dict[str, Any]:
    """Load the FI runtime the way the assistant does. No bypass: report what it says."""
    from fpl_grounded_assistant.football_intelligence_runtime import _load_runtime  # noqa: PLC0415

    try:
        runtime = _load_runtime()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:400]}
    if runtime is None:
        return {"ok": False, "error_type": "None",
                "error": "runtime returned None (pointer files absent at FPL_FOOTBALL_ROOT): "
                         "tools answer missing_context/feature_build_unavailable"}
    return {"ok": True, "calculated_at": runtime.calculated_at}


class _EventCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        ev = getattr(record, "fpl_event", None)
        if isinstance(ev, dict) and str(ev.get("event", "")).startswith("provider_call"):
            self.events.append(dict(ev))


def cmd_run(args: argparse.Namespace) -> int:
    base._configure_imports()
    _pin_env(args.arm, args.store, args.capture)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.arm == "B":
        pre = _preflight_b()
        (out_dir / "arm_b_preflight.json").write_text(json.dumps(
            {"at": _utc(), "store": args.store, "capture_set": bool(args.capture), **pre},
            ensure_ascii=False, indent=2), encoding="utf-8")
        if not pre["ok"]:
            print(f"arm B blocked: {pre['error_type']}: {pre['error']}", file=sys.stderr)
            return 3

    base.require_api_key(base.PROVIDER)
    est = round(len(QUESTIONS) * 0.01, 3)
    print(f"{len(QUESTIONS)} /ask calls on {base.PROVIDER}/{base.MODEL}; est ${est} cap ${args.cap_usd}",
          file=sys.stderr)
    if est > args.cap_usd:
        return 2

    import fpl_server  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from fpl_grounded_assistant import orchestrator as orch  # noqa: PLC0415
    from fpl_grounded_assistant.orch_config import (  # noqa: PLC0415
        get_orch_model, get_orch_provider, is_football_intelligence_enabled)
    from fpl_pipeline import assemble_captain_context  # noqa: PLC0415

    configured = {"provider": get_orch_provider(), "model": get_orch_model(get_orch_provider()),
                  "fi_enabled": is_football_intelligence_enabled()}
    assert configured["fi_enabled"] == (args.arm == "B"), configured

    bootstrap = assemble_captain_context()["bootstrap"]
    fpl_server._init_bootstrap(bootstrap)
    fpl_server._init_classifier_client(None)
    audits: list[Any] = []
    fpl_server.write_audit_entry = lambda entry: audits.append(entry)  # type: ignore[assignment]
    tool_log: list[dict[str, Any]] = []
    real_run_tool = orch.run_tool

    def recording_run_tool(name: str, targs: dict[str, Any], bs: dict[str, Any]) -> dict[str, Any]:
        out = real_run_tool(name, targs, bs)
        tool_log.append({"name": name, "args": targs, "output": out})
        return out

    orch.run_tool = recording_run_tool  # type: ignore[assignment]
    cap = _EventCapture()
    logging.getLogger().addHandler(cap)
    logging.getLogger().setLevel(logging.INFO)
    client = TestClient(fpl_server.app)

    out = out_dir / f"answers_{args.arm}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": {
            "measurement": "fi-answer-depth-ab", "arm": args.arm, "configured": configured,
            "started_at": _utc(), "fpl_current_event": next(
                (e["id"] for e in bootstrap.get("events", ()) if e.get("is_current")), None),
        }}, ensure_ascii=False, default=str) + "\n")
        for qid, question, needs_team, _chk, swap in QUESTIONS:
            audits.clear(); tool_log.clear(); cap.events.clear()
            payload: dict[str, Any] = {"question": question, "debug": True}
            if needs_team:
                payload["team_id"] = args.team_id
            t0 = time.monotonic()
            try:
                resp = client.post("/ask", json=payload, headers={"X-User-Id": f"ab-{uuid.uuid4().hex[:10]}"})
                body, exc = resp.json(), (None if resp.status_code == 200 else f"http {resp.status_code}")
            except Exception as e:  # noqa: BLE001
                body, exc = {}, f"{type(e).__name__}: {e}"
            ms = round((time.monotonic() - t0) * 1000)
            rt = (body.get("debug") or {}).get("routing_trace") or {}
            audit = audits[-1] if audits else None
            row = {
                "question_id": qid, "question": question, "arm": args.arm, "swap": swap,
                "team_id": args.team_id if needs_team else None, "asked_at": _utc(), "latency_ms": ms,
                "exception": exc, "outcome": body.get("outcome"), "intent": body.get("intent"),
                "final_text": body.get("final_text"),
                "tool_sequence": rt.get("tool_sequence"),
                "tools_called": [t["name"] for t in tool_log],
                "fi_tools_called": [t["name"] for t in tool_log if t["name"] in _fi_tool_names()],
                # model actually used: from the audit line (orchestrator result) and provider events
                "trace_provider": getattr(audit, "provider", None),
                "trace_model": getattr(audit, "model", None),
                "provider_events": [{"provider": e.get("provider"), "model": e.get("model"),
                                     "event": e.get("event")} for e in cap.events],
                "usd_cost_estimate": getattr(audit, "usd_cost_estimate", None),
                "tool_outputs": tool_log[:],
                "raw": body,
            }
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            print(f"  {qid} {ms:6d} ms model={row['trace_model']} tools={row['tools_called']}", file=sys.stderr)
    orch.run_tool = real_run_tool  # type: ignore[assignment]
    return 0


def _fi_tool_names() -> set[str]:
    from fpl_grounded_assistant.tool_schema_registry import FI7B_TOOL_SCHEMAS  # noqa: PLC0415

    return {s.name for s in FI7B_TOOL_SCHEMAS}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_freeze(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    arms = {}
    for arm in ("A", "B"):
        p = out_dir / f"answers_{arm}.jsonl"
        if p.is_file():
            arms[arm] = {"file": p.name, "sha256": _sha256(p),
                         "rows": [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]}
    blocker = out_dir / "arm_b_preflight.json"
    frozen = {"frozen_at": _utc(), "deadline": "2026-10-18T12:30:00Z",
              "arms_present": sorted(arms),
              "arm_b_preflight": json.loads(blocker.read_text(encoding="utf-8")) if blocker.is_file() else None,
              "answers": {a: [{k: r.get(k) for k in ("question_id", "question", "swap", "asked_at", "final_text",
                                                      "tools_called", "fi_tools_called", "trace_provider",
                                                      "trace_model", "outcome")}
                              for r in v["rows"] if "_header" not in r] for a, v in arms.items()},
              "source_sha256": {a: v["sha256"] for a, v in arms.items()}}
    fp = out_dir / "frozen.json"
    fp.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = _sha256(fp)
    (out_dir / "frozen.sha256").write_text(f"{digest}  frozen.json\n", encoding="utf-8")
    print(f"frozen_at={frozen['frozen_at']} sha256={digest}")
    return 0


def cmd_blind(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    frozen = json.loads((out_dir / "frozen.json").read_text(encoding="utf-8"))
    if sorted(frozen["answers"]) != ["A", "B"]:
        print("blind pages need both arms; only " + ",".join(frozen["answers"]) + " present", file=sys.stderr)
        return 3
    rng = random.Random(args.seed)
    by = {a: {r["question_id"]: r for r in rows} for a, rows in frozen["answers"].items()}
    pages = out_dir / "blind"
    pages.mkdir(exist_ok=True)
    key: dict[str, dict[str, str]] = {}
    for qid, question, *_ in QUESTIONS:
        order = ["A", "B"]
        rng.shuffle(order)
        key[qid] = {"X": order[0], "Y": order[1]}
        blocks = "".join(
            f"<section><h2>Respuesta {lab}</h2><div class=a>{html.escape(by[arm][qid]['final_text'] or '')}</div></section>"
            for lab, arm in zip(("X", "Y"), order))
        (pages / f"{qid}.html").write_text(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Pregunta {qid}</title><style>body{{font:16px/1.5 system-ui;margin:16px;max-width:900px;background:#fff;color:#111}}"
            ".a{white-space:pre-wrap;border:1px solid #ccc;padding:12px;border-radius:8px}</style>"
            f"<h1>{html.escape(question)}</h1>{blocks}<p>¿Cuál es mejor: X o Y?</p>", encoding="utf-8")
    (out_dir / "blind_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"{len(key)} pages in {pages}; key in blind_key.json")
    return 0


def cmd_outcomes(args: argparse.Namespace) -> int:
    """After the matches: FPL live data per player + a blank verdict sheet for Q1-Q10."""
    h = {"User-Agent": "Mozilla/5.0"}

    def get(url: str) -> Any:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read())

    out_dir = Path(args.out_dir)
    bs = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    live = get(f"https://fantasy.premierleague.com/api/event/{args.gw}/live/")
    fixtures = [f for f in get("https://fantasy.premierleague.com/api/fixtures/") if f["event"] == args.gw]
    teams = {t["id"]: t["short_name"] for t in bs["teams"]}
    els = {e["id"]: e for e in bs["elements"]}
    players = [{"web_name": els[p["id"]]["web_name"], "team": teams[els[p["id"]]["team"]],
                **{k: p["stats"][k] for k in ("minutes", "starts", "goals_scored", "assists", "clean_sheets",
                                               "goals_conceded", "total_points", "defensive_contribution")
                   if k in p["stats"]}}
               for p in live["elements"] if p["id"] in els and p["stats"].get("minutes", 0) > 0]
    res = {"pulled_at": _utc(), "gw": args.gw,
           "fixtures": [{"home": teams[f["team_h"]], "away": teams[f["team_a"]], "score": [f["team_h_score"], f["team_a_score"]],
                         "finished": f["finished"]} for f in fixtures],
           "players": players}
    (out_dir / f"outcomes_gw{args.gw}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    sheet = {qid: {"question": q, "verdict_A": None, "verdict_B": None, "evidence": ""}
             for qid, q, _t, chk, _s in QUESTIONS if chk}
    (out_dir / f"grading_gw{args.gw}.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"outcomes_gw{args.gw}.json + grading_gw{args.gw}.json written ({len(players)} players with minutes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", choices=("A", "B"), required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--store")
    r.add_argument("--capture")
    r.add_argument("--team-id", type=int, default=TEAM_ID_DEFAULT)
    r.add_argument("--cap-usd", type=float, default=1.0)
    for name in ("freeze", "blind"):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", required=True)
        if name == "blind":
            p.add_argument("--seed", type=int, default=None)
    o = sub.add_parser("outcomes")
    o.add_argument("--out-dir", required=True)
    o.add_argument("--gw", type=int, default=7)
    args = ap.parse_args(argv)
    return {"run": cmd_run, "freeze": cmd_freeze, "blind": cmd_blind, "outcomes": cmd_outcomes}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
