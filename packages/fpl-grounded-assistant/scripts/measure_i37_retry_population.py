"""i37: how many prod turns reach the evaluator-retry bare-render path?

Ten mixed canonical questions by /ask against prod, one rep each, rotating
X-User-Id every 5 turns (free cap, i99). Records per turn: retry_attempted,
synthesis_turn, tool_sequence, selected_tool, tokens (if exposed), and
whether the final_text is a bare render (retry_attempted and not synthesis_turn
with a tool executed). Raw responses to JSONL.
"""
import json, sys, time, uuid, requests
URL = "https://fpl-backend-production-4151.up.railway.app"
QS = [
    "¿A quién capitaneo esta jornada?",
    "¿Quién es mejor capitán, Haaland o Salah?",
    "¿Qué tal pinta el calendario del Arsenal en las próximas 5 jornadas?",
    "Dame el resumen de Bruno Fernandes",
    "¿Qué jugadores pueden explotar la zona más débil de la defensa del Chelsea?",
    "¿Quiénes son los 5 máximos goleadores de la temporada?",
    "¿Qué defensas baratos tienen buen calendario?",
    "¿Cómo está el Liverpool defensivamente?",
    "¿Qué zonas débiles tiene el Tottenham?",
    "Compara a Palmer con Saka",
]
out = sys.argv[1]
tag = sys.argv[2] if len(sys.argv) > 2 else "pre"
run = f"i37-{tag}-{uuid.uuid4().hex[:6]}"
with open(out, "a", encoding="utf-8") as f:
    v = requests.get(f"{URL}/version", timeout=30).json()
    f.write(json.dumps({"kind": "pre", "run_id": run, "version": v, "ts": time.time()}) + "\n")
    for i, q in enumerate(QS, 1):
        user = f"{run}-u{(i - 1) // 5}"
        t0 = time.time()
        r = requests.post(f"{URL}/ask", headers={"X-User-Id": user}, json={"question": q, "debug": True}, timeout=180)
        body = r.json(); dbg = body.get("debug") or {}; rt = dbg.get("routing_trace") or {}
        bare = bool(rt.get("retry_attempted")) and rt.get("synthesis_turn") is False and bool(rt.get("tool_sequence"))
        rec = {"kind": "turn", "run_id": run, "i": i, "question": q, "user": user, "status": r.status_code,
               "latency_s": round(time.time() - t0, 1), "response": body, "ts": time.time(),
               "summary": {"outcome": body.get("outcome"), "selected_tool": dbg.get("selected_tool"),
                           "retry_attempted": rt.get("retry_attempted"), "synthesis_turn": rt.get("synthesis_turn"),
                           "tool_sequence": rt.get("tool_sequence"), "bare_retry_render": bare,
                           "verdict": rt.get("evaluator_verdict")}}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"#{i} {q[:45]!r:48} outcome={body.get('outcome')} tool={dbg.get('selected_tool')} retry={rt.get('retry_attempted')} synth={rt.get('synthesis_turn')} bare={bare} {rec['latency_s']}s", flush=True)
