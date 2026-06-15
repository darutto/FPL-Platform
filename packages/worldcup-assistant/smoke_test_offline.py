"""Offline smoke test for Iteration 1 — no network, no API keys required.

Run:  python smoke_test_offline.py   (from packages/worldcup-assistant)

Covers: package imports, locale_es determinism, tool-loop mechanics with an
injected provider response (Anthropic shape), tool executor error envelopes,
and server schema construction.  Live verification against worldcupapi.com
happens separately once WORLDCUP_API_KEY is set.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "llm-orchestrator-core"),
    os.path.join(_PKGS, "worldcup-api-client"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


# --- 1. Imports ------------------------------------------------------------
import llm_orchestrator_core as core  # noqa: E402
import worldcup_api_client as wcapi  # noqa: E402
from worldcup_assistant import ask_wc, locale_es  # noqa: E402
from worldcup_assistant.tools import (  # noqa: E402
    WC_TOOL_NAMES,
    WC_TOOL_SPECS,
    build_wc_tool_specs,
    execute_wc_tool,
)
import worldcup_assistant.tools as _wctools  # noqa: E402
from worldcup_assistant.context_builder import WC_SYSTEM_PROMPT  # noqa: E402

check("imports: llm_orchestrator_core / worldcup_api_client / worldcup_assistant", True)

# --- 2. No FPL contamination ------------------------------------------------
fpl_modules = [m for m in sys.modules if m.startswith("fpl_")]
check("isolation: no fpl_* modules imported", not fpl_modules, str(fpl_modules))

# --- 3. locale_es determinism -----------------------------------------------
check("locale: Ivory Coast -> Costa de Marfil",
      locale_es.localize_country("Ivory Coast") == "Costa de Marfil")
check("locale: in_progress -> En vivo",
      locale_es.localize_status("in_progress") == "En vivo")
check("locale: completed -> Finalizado",
      locale_es.localize_status("completed") == "Finalizado")
check("locale: round_of_16 -> Octavos de final",
      locale_es.localize_stage("round_of_16") == "Octavos de final")
payload = locale_es.localize_payload({
    "matches": [{"home_team": "United States", "away_team": "Ivory Coast",
                 "status": "in_progress", "stage": "group_stage",
                 "players": [{"name": "X", "position": "goalkeeper"}]}],
})
m = payload["matches"][0]
check("locale: recursive payload localization",
      m["home_team"] == "Estados Unidos"
      and m["away_team"] == "Costa de Marfil"
      and m["status"] == "En vivo"
      and m["stage"] == "Fase de grupos"
      and m["players"][0]["position"] == "Portero")
check("locale: unmapped value passes through",
      locale_es.localize_country("Atlantis") == "Atlantis")

# --- 4. Tool registry shape ---------------------------------------------------
check("tools: 13 base specs registered", len(WC_TOOL_SPECS) == 13,
      str(sorted(s.name for s in WC_TOOL_SPECS)))
check("tools: 14 specs with web_search enabled",
      len(build_wc_tool_specs(web_search_enabled=True)) == 14
      and any(s.name == "web_search" for s in build_wc_tool_specs(web_search_enabled=True)),
      str(sorted(WC_TOOL_NAMES)))
check("tools: web_search absent when disabled",
      all(s.name != "web_search" for s in build_wc_tool_specs(web_search_enabled=False)))
anthropic_tools = core.build_tools("anthropic", WC_TOOL_SPECS)
openai_tools = core.build_tools("openai", WC_TOOL_SPECS)
gemini_tools = core.build_tools("gemini", WC_TOOL_SPECS)
check("tools: anthropic wire format", all("input_schema" in t for t in anthropic_tools))
check("tools: openai wire format", all(t.get("type") == "function" for t in openai_tools))
check("tools: gemini wire format",
      len(gemini_tools) == 1 and len(gemini_tools[0]["function_declarations"]) == 13)

# --- 5. Executor error envelopes (no network) ---------------------------------
r = execute_wc_tool("get_squad", {})
check("executor: missing arg -> status=error", r.get("status") == "error", str(r))
r = execute_wc_tool("nope_tool", {})
check("executor: unknown tool -> status=error", r.get("status") == "error", str(r))

# --- 6. Tool loop with injected Anthropic-shaped responses ---------------------
_calls = {"n": 0}


def _fake_request():
    _calls["n"] += 1
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
    if _calls["n"] == 1:
        block = SimpleNamespace(
            type="tool_use", id="tu_1", name="lookup_thing", input={"q": "grupo A"},
        )
        return SimpleNamespace(content=[block], usage=usage)
    block = SimpleNamespace(type="text", text="El Grupo A lo lidera México con 4 puntos.")
    return SimpleNamespace(content=[block], usage=usage)


executed: list[tuple[str, dict]] = []


def _fake_executor(name: str, args: dict) -> dict:
    executed.append((name, args))
    return {"status": "ok", "leader": "México", "points": 4}


spec = core.ToolSpec(
    name="lookup_thing",
    description="test tool",
    parameters={"type": "object", "properties": {}},
)
result = core.run_tool_loop(
    "¿Cómo va el grupo A?",
    system_prompt="test system",
    tool_specs=[spec],
    execute_tool=_fake_executor,
    provider="anthropic",
    model="test-model",
    dynamic_context="ctx",
    no_answer_fallback="sin respuesta",
    _request_fn=_fake_request,
)
check("loop: outcome ok", result.outcome == core.LOOP_OK, result.outcome)
check("loop: final text from 2nd turn", "Grupo A" in result.final_text, result.final_text)
check("loop: tool executed once with args",
      executed == [("lookup_thing", {"q": "grupo A"})], str(executed))
check("loop: trace recorded", len(result.tool_trace) == 1
      and result.tool_trace[0].tool_output.get("leader") == "México")
check("loop: tokens accumulated", result.input_tokens == 200 and result.output_tokens == 100,
      f"in={result.input_tokens} out={result.output_tokens}")

# --- 7. Loop failure path: no client (attempts==0 contract) --------------------
saved = os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    result2 = core.run_tool_loop(
        "pregunta",
        system_prompt="s",
        tool_specs=[spec],
        execute_tool=_fake_executor,
        provider="anthropic",
        model="test-model",
        no_answer_fallback="sin datos ahora mismo",
    )
finally:
    if saved is not None:
        os.environ["ANTHROPIC_API_KEY"] = saved
check("loop: no-client failure is safe + Spanish fallback",
      result2.outcome in (core.LOOP_NO_CLIENT, core.LOOP_LLM_ERROR)
      and result2.final_text == "sin datos ahora mismo",
      f"{result2.outcome} / {result2.final_text}")

# --- 8. ask_wc wrapper with injection ------------------------------------------
# The injected _request_fn returns Anthropic-shaped responses, so pin the
# provider to anthropic for these mechanics tests (production defaults to the
# Gemini Pro gatekeeper — verified separately, not via the offline fake).
os.environ["WC_PROVIDER"] = "anthropic"
_calls["n"] = 0
wc_result = ask_wc("¿Cómo va el grupo A?", _request_fn=_fake_request)
check("ask_wc: returns WCAskResult ok",
      wc_result.outcome == core.LOOP_OK and wc_result.llm_used, wc_result.outcome)
check("ask_wc: system prompt enforces Spanish",
      "Responde SIEMPRE en español" in WC_SYSTEM_PROMPT)
check("ask_wc: system prompt has web_search routing guardrail",
      "BÚSQUEDA WEB" in WC_SYSTEM_PROMPT and "ÚLTIMO RECURSO" in WC_SYSTEM_PROMPT)

# --- 8b. web_search tool path (stubbed search_web, no network) -----------------
def _fake_search_web(query):  # noqa: ANN001, ANN202
    check("web_search: query is keyword-optimized (no raw sentence)",
          "?" not in query and len(query) < 60, repr(query))
    return {
        "results": [
            {"title": "Francia: duda de Mbappé", "snippet": "Reportes encontrados.",
             "url": "https://www.bbc.com/sport/abc123", "source": "bbc.com",
             "published": "2026-06-14"},
        ],
        "answer": "English quick-take that must never reach the UI.",
        "timestamp": "2026-06-14T00:00:00+00:00",
    }


def _fake_ws_request():  # noqa: ANN202
    _calls["n"] += 1
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)
    if _calls["n"] == 1:
        block = SimpleNamespace(
            type="tool_use", id="tu_ws", name="web_search",
            input={"query": "Mbappé lesión estado Francia"},
        )
        return SimpleNamespace(content=[block], usage=usage)
    block = SimpleNamespace(
        type="text", text="Según la prensa, Mbappé es duda; la información no está confirmada.")
    return SimpleNamespace(content=[block], usage=usage)


_orig_search = _wctools.search_web
_wctools.search_web = _fake_search_web
try:
    _calls["n"] = 0
    ws = ask_wc("¿está lesionado Mbappé?", web_search_enabled=True, _request_fn=_fake_ws_request)
    check("web_search: payload populated", ws.web_search is not None, str(ws.web_search))
    check("web_search: summary == orchestrator final_text",
          bool(ws.web_search) and ws.web_search.get("summary") == ws.final_text,
          str(ws.web_search))
    check("web_search: source url preserved through truncation",
          bool(ws.web_search) and ws.web_search["results"][0]["url"]
          == "https://www.bbc.com/sport/abc123")
    check("web_search: raw Tavily answer dropped from payload",
          bool(ws.web_search) and "answer" not in ws.web_search)
    check("web_search: NOT counted as grounded (unverified)",
          ws.grounded is False, str(ws.grounded))
finally:
    _wctools.search_web = _orig_search

# --- 9. Server schemas + session namespacing -----------------------------------
from worldcup_assistant import wc_server  # noqa: E402

sid, _ = wc_server._get_or_create_session("abc123")
check("server: session id gets wc: prefix", sid == "wc:abc123", sid)
sid2, _ = wc_server._get_or_create_session("wc:abc123")
check("server: wc: prefix not doubled", sid2 == "wc:abc123", sid2)
wc_server._clear_sessions()

resp = wc_server.AskResponse(
    final_text="t", outcome="ok", supported=True, intent="wc_info",
    review_passed=True, llm_used=True,
)
check("server: AskResponse core field contract",
      set(resp.model_dump()) >= {
          "final_text", "outcome", "supported", "intent",
          "review_passed", "llm_used", "debug", "degraded",
      })

# --- 10. Cache mechanics (worldcup_api_client, no network) ---------------------
wcapi.clear_cache()
from worldcup_api_client import wc_client as _wc  # noqa: E402

_wc._cache_put(_wc._cache_key("/standings", {"group": "A"}), {"x": 1}, 60)
check("cache: hit within TTL",
      _wc._cache_get(_wc._cache_key("/standings", {"group": "A"})) == {"x": 1})
_wc._cache_put(_wc._cache_key("/live", {}), {"y": 2}, -1)
check("cache: key (auth) excluded from cache key",
      _wc._cache_key("/p", {"key": "secret", "a": 1}) == _wc._cache_key("/p", {"a": 1}))
wcapi.clear_cache()

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("ALL CHECKS PASSED")
