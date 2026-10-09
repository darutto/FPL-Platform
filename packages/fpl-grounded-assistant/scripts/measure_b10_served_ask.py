"""Bloque 10: read the SERVED /ask for «háblame de X» with the zonal section on and off.

MEASUREMENT ONLY -- real paid calls (openai/gpt-5.6-luna pinned, like
measure_tool_routing) through the in-process FastAPI app, so what is recorded
is the response a client receives, not a tool output. Two arms per question:

  off  the composition is replaced by a no-op (the pre-Bloque-10 snapshot)
  on   the code as it ships

It also times ``get_player_snapshot`` itself, with NO model call, cold and
warm (store cache + fixtures cache), which is where the added latency lives.

Environment honesty: the local store is the 2025-26 parquet, copied under the
CURRENT_SEASON key with its own pointer, so the provenance stamp reads
«stale_season» -- the point of rows recorded here is plumbing and shape, not
this season's zonal numbers. The bootstrap is the live one (the same
``assemble_captain_context`` the server runs at start) and the fixture state
comes from one real ``/fixtures/`` request.

Usage (from packages/fpl-grounded-assistant):
    python scripts/measure_b10_served_ask.py --out <jsonl> --reps 3 --cap-usd 1.0 \
        --store-parquet <path to a understat_shots.parquet>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import measure_tool_routing as base  # noqa: E402

QUESTIONS = [
    ("served-palmer", "Háblame de Cole Palmer"),
    ("served-haaland", "¿Cómo está Haaland?"),
    ("served-no-profile", "Háblame de Robert Sánchez"),
    ("served-ambiguous", "Háblame de Palmer"),
]


def _stage_store(parquet: Path) -> str:
    """A tactical root holding *parquet* under the CURRENT_SEASON key."""
    from fpl_tactical.paths import CURRENT_SEASON  # noqa: PLC0415

    root = Path(tempfile.mkdtemp(prefix="b10-store-"))
    d = root / "seasons" / CURRENT_SEASON
    d.mkdir(parents=True)
    shutil.copy(parquet, d / "understat_shots.parquet")
    src_ptr = parquet.parent / "_tactical_latest.json"
    if src_ptr.exists():
        shutil.copy(src_ptr, d / "_tactical_latest.json")
    os.environ["FPL_TACTICAL_ROOT"] = str(root)
    return str(root)


def _tool_latency(bootstrap: dict[str, Any], ids: list[int]) -> dict[str, Any]:
    from fpl_grounded_assistant import player_snapshot_zonal as pz  # noqa: PLC0415
    from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot  # noqa: PLC0415

    def one(pid: int) -> float:
        t0 = time.perf_counter()
        get_player_snapshot(pid, bootstrap)
        return (time.perf_counter() - t0) * 1000

    out: dict[str, Any] = {}
    pz.reset_caches()
    out["cold_first_call_ms"] = round(one(ids[0]), 1)            # store + fixtures
    out["warm_ms"] = [round(one(pid), 1) for pid in ids * 3]
    out["warm_median_ms"] = round(statistics.median(out["warm_ms"]), 1)
    pz.reset_caches()
    out["cold_again_ms"] = round(one(ids[0]), 1)
    # fixtures cache only (store still warm after the line above)
    pz._fixtures_cache.update(at=None, data=None)
    out["store_warm_fixtures_cold_ms"] = round(one(ids[0]), 1)
    real = pz.compose_player_zonal
    pz.compose_player_zonal = lambda el, bs: pz.ComposeResult(zonal=None, reason="off")
    try:
        import importlib  # noqa: PLC0415
        gps = importlib.import_module("fpl_grounded_assistant.get_player_snapshot")
        gps.compose_player_zonal = pz.compose_player_zonal
        out["without_zonal_ms"] = [round(one(pid), 1) for pid in ids * 3]
        out["without_zonal_median_ms"] = round(statistics.median(out["without_zonal_ms"]), 1)
    finally:
        pz.compose_player_zonal = real
        gps.compose_player_zonal = real
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--cap-usd", type=float, default=1.0)
    ap.add_argument("--store-parquet", required=True)
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    api_key = base.require_api_key(base.PROVIDER)
    os.environ["FPL_ORCH_ENABLED"] = "1"
    os.environ["FPL_ORCH_PROVIDER"] = base.PROVIDER
    os.environ["FPL_ORCH_MODEL"] = base.MODEL
    os.environ["DEFAULT_PROVIDER"] = base.PROVIDER
    os.environ[base.API_KEY_ENV_BY_PROVIDER[base.PROVIDER]] = api_key
    os.environ["FPL_EVAL_DISABLED"] = "1"
    os.environ.pop("REDIS_URL", None)
    root = _stage_store(Path(args.store_parquet))

    n = len(QUESTIONS) * args.reps * 2
    est = round(n * (0.11 / 84) * 3, 3)
    print(f"{n} /ask calls on {base.PROVIDER}/{base.MODEL}; est ${est} cap ${args.cap_usd}",
          file=sys.stderr)
    if est > args.cap_usd:
        return 2

    import fpl_server  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415
    import importlib  # noqa: PLC0415
    gps = importlib.import_module("fpl_grounded_assistant.get_player_snapshot")
    from fpl_grounded_assistant.orch_config import get_orch_model, get_orch_provider  # noqa: PLC0415
    from fpl_pipeline import assemble_captain_context  # noqa: PLC0415

    resolved = {"provider": get_orch_provider(), "model": get_orch_model(get_orch_provider())}
    assert resolved == {"provider": base.PROVIDER, "model": base.MODEL}, resolved

    bootstrap = assemble_captain_context()["bootstrap"]
    fpl_server._init_bootstrap(bootstrap)
    fpl_server._init_classifier_client(None)
    fpl_server.write_audit_entry = lambda entry: None  # type: ignore[assignment]
    client = TestClient(fpl_server.app)

    palmer = next(e["id"] for e in bootstrap["elements"]
                  if e["first_name"] == "Cole" and e["second_name"] == "Palmer")
    haaland = next(e["id"] for e in bootstrap["elements"] if e["second_name"] == "Haaland")
    tool_latency = _tool_latency(bootstrap, [palmer, haaland])

    real_attach = gps._attach_zonal
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    spend = 0.0
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": {
            "measurement": "b10-served-ask", "provider": base.PROVIDER, "model": base.MODEL,
            "reps": args.reps, "cap_usd": args.cap_usd, "estimate_usd": est,
            "store_parquet": args.store_parquet, "tactical_root": root,
            "tool_latency": tool_latency, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }}, ensure_ascii=False) + "\n")
        for qid, question in QUESTIONS:
            for rep in range(args.reps):
                for arm in ("off", "on"):
                    gps._attach_zonal = (lambda *a, **k: None) if arm == "off" else real_attach
                    t0 = time.monotonic()
                    try:
                        resp = client.post("/ask", json={"question": question, "debug": True},
                                           headers={"X-User-Id": f"b10-{uuid.uuid4().hex[:10]}"})
                        body, exc = resp.json(), (None if resp.status_code == 200 else f"http {resp.status_code}")
                    except Exception as e:  # noqa: BLE001
                        body, exc = {}, f"{type(e).__name__}: {e}"
                    ms = round((time.monotonic() - t0) * 1000)
                    rt = (body.get("debug") or {}).get("routing_trace") or {}
                    ps = body.get("player_snapshot") or {}
                    fh.write(json.dumps({
                        "question_id": qid, "question": question, "arm": arm, "rep": rep,
                        "latency_ms": ms, "exception": exc, "intent": body.get("intent"),
                        "outcome": body.get("outcome"), "tool_sequence": rt.get("tool_sequence"),
                        "final_text": body.get("final_text"),
                        "player_snapshot_present": bool(ps),
                        "zonal": ps.get("zonal") if ps else None,
                        "n_cards": sum(1 for k in ("player_snapshot", "zonal_opportunity", "fixture_outlook",
                                                   "generic_card", "team_schedule", "player_form")
                                       if body.get(k)),
                        "suggestions": body.get("suggestions"),
                        "raw": body,
                    }, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(f"  {qid:18} r{rep} {arm:3} {ms:6d} ms seq={rt.get('tool_sequence')} "
                          f"zonal={'yes' if ps.get('zonal') else 'no'}", file=sys.stderr)
    gps._attach_zonal = real_attach
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
