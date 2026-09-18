"""i99: where does the sixth zonal turn go? Six+ turns per variant against prod,
raw responses to JSONL (field-notes/artifacts/i99-quota-cut-2026-09-17.jsonl).

Variants (identity is X-User-Id, hashed server-side; tier defaults to free):
  A  fresh user id, /ask x N                       (the condition the card measured)
  B  fresh user id, ONE session reused, /session/{id}/ask x N
  C  ONE session reused, X-User-Id rotated every turn

Usage: python scripts/measure_i99_quota_cut.py out.jsonl A 7
Costs N orchestrated turns per variant until the free cap blocks (5 by /ask, ~4 by session).
"""
import json, sys, time, uuid, requests

URL = "https://fpl-backend-production-4151.up.railway.app"
Q = "¿Qué jugadores pueden explotar la zona más débil de la defensa del Chelsea?"
OUT = sys.argv[1]
variant = sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 6

def snap():
    h = requests.get(f"{URL}/healthz", timeout=30).json()
    v = requests.get(f"{URL}/version", timeout=30).json()
    return {"version": v, "orchestrator": h.get("orchestrator"), "routing_counters": h.get("routing_counters")}

def ask(user, question, session=None):
    hdr = {"Content-Type": "application/json", "X-User-Id": user}
    path = "/ask" if session is None else f"/session/{session}/ask"
    t0 = time.time()
    r = requests.post(f"{URL}{path}", headers=hdr, json={"question": question, "debug": True}, timeout=180)
    return r.status_code, r.json(), round(time.time() - t0, 1)

def new_session(user):
    r = requests.post(f"{URL}/session", headers={"X-User-Id": user}, json={}, timeout=30)
    r.raise_for_status()
    return r.json()["session_id"]

run_id = f"i99-{variant}-{uuid.uuid4().hex[:8]}"
with open(OUT, "a", encoding="utf-8") as f:
    f.write(json.dumps({"kind": "pre", "run_id": run_id, "variant": variant, "snap": snap(), "ts": time.time()}) + "\n")
    base_user = f"{run_id}-user"
    session = None if variant == "A" else new_session(base_user)
    for i in range(1, N + 1):
        user = base_user if variant in ("A", "B") else f"{base_user}-{i}"
        status, body, dt = ask(user, Q, session)
        dbg = body.get("debug") or {}
        rec = {"kind": "turn", "run_id": run_id, "variant": variant, "i": i, "user": user, "session": session,
               "status": status, "latency_s": dt, "response": body, "ts": time.time()}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{variant} #{i}] status={status} outcome={body.get('outcome')} intent={body.get('intent')} "
              f"llm_used={body.get('llm_used')} selected_tool={dbg.get('selected_tool')!r} "
              f"branch={(dbg.get('routing_trace') or {}).get('branch')!r} "
              f"text={str(body.get('final_text',''))[:70]!r} {dt}s", flush=True)
    f.write(json.dumps({"kind": "post", "run_id": run_id, "variant": variant, "snap": snap(), "ts": time.time()}) + "\n")
