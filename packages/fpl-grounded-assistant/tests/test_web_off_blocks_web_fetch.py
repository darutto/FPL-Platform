"""The web toggle OFF blocks web_fetch as well as search_web (server-side).

Base behaviour (eb35eee4): with the toggle off, ``web_fetch`` was still in the
base registry, so it was offered to the model on every turn (``/ask`` without the
toggle, and every ``/session`` turn, which has no toggle at all) and the server
executed it when named. Every test below that asserts the fix fails on the base.

Fake Anthropic-shaped client, ``run_tool`` replaced by a spy for the execution
tests, no network, no paid call.
"""
from __future__ import annotations

import copy
import os
import sys
from types import SimpleNamespace as NS

import pytest

from conftest import BOOTSTRAP

from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import (
    _SYSTEM_PROMPT,
    _build_tools,
    ask_orchestrated,
    static_system_prompt,
)
from fpl_grounded_assistant.tool_schema_registry import (
    SEARCH_WEB_SCHEMA,
    WEB_FETCH_SCHEMA,
    get_offered_tool_names,
    get_offered_tool_schemas,
)

PROVIDERS = ["anthropic", "openai", "gemini"]


def _names(tools, provider):
    if provider == "gemini":
        return {d["name"] for group in tools for d in group["function_declarations"]}
    if provider == "openai":
        return {t["name"] if "name" in t else t["function"]["name"] for t in tools}
    return {t["name"] for t in tools}


# ---------------------------------------------------------------------------
# 1. What is offered, and what the server will run: one rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_off_offers_neither_web_tool(provider):
    names = _names(_build_tools(provider, web_search_enabled=False, football_intelligence_enabled=False), provider)
    assert "web_fetch" not in names and "search_web" not in names


@pytest.mark.parametrize("provider", PROVIDERS)
def test_on_offers_both_web_tools(provider):
    names = _names(_build_tools(provider, web_search_enabled=True, football_intelligence_enabled=False), provider)
    assert {"web_fetch", "search_web"} <= names


def test_the_executable_names_follow_the_same_rule():
    off = get_offered_tool_names(False, web_search_enabled=False)
    on = get_offered_tool_names(False, web_search_enabled=True)
    assert "web_fetch" not in off and "search_web" not in off
    assert {"web_fetch", "search_web"} <= on
    # the toggle changes the web tools and nothing else
    assert on - off == {"web_fetch", "search_web"}


def test_default_is_off_the_toggle_absent_means_no_web():
    assert "web_fetch" not in get_offered_tool_names(False)
    assert "web_fetch" not in {n for n in _names(_build_tools(None, football_intelligence_enabled=False), "anthropic")}


def test_toggle_on_tool_list_is_unchanged():
    # The toggle-on list is the base set plus search_web, in that order: what it was before.
    on = [t["name"] for t in _build_tools("anthropic", web_search_enabled=True, football_intelligence_enabled=False)]
    base = [s.name for s in get_offered_tool_schemas(False)]
    assert on == [*base, SEARCH_WEB_SCHEMA.name] and WEB_FETCH_SCHEMA.name in base


# ---------------------------------------------------------------------------
# 2. The prompt: toggle-on bytes untouched, toggle-off says the web is off
# ---------------------------------------------------------------------------

def test_toggle_on_prompt_is_byte_identical():
    assert static_system_prompt("es") == _SYSTEM_PROMPT
    assert static_system_prompt("es", web_enabled=True) == _SYSTEM_PROMPT
    assert static_system_prompt("en", web_enabled=True) == static_system_prompt("en")


@pytest.mark.parametrize("locale", ["es", "en"])
def test_toggle_off_prompt_overrides_the_fetch_instructions_and_says_what_to_tell_the_user(locale):
    on = static_system_prompt(locale, web_enabled=True)
    off = static_system_prompt(locale, web_enabled=False)
    assert off.startswith(on) and len(off) > len(on)
    tail = off[len(on):]
    assert "WEB_OFF" in tail and "ignore every line above that tells you to fetch" in tail
    assert "No puedo consultar la web ahora." in tail and "I can't check the web right now." in tail
    assert "Never claim you checked a page" in tail


def test_the_base_prompt_still_names_web_fetch_so_the_override_is_what_makes_it_safe():
    # Documents why the override exists: the pinned base prompt tells the model to use web_fetch.
    assert "USE web_fetch" in _SYSTEM_PROMPT and "offer to web_fetch" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 3. Execution: naming a tool that was not offered runs nothing
# ---------------------------------------------------------------------------

def _usage():
    return NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)


def _tool_use(name, args, cid="t1"):
    return NS(content=[NS(type="tool_use", id=cid, name=name, input=args)], stop_reason="tool_use", usage=_usage())


def _text(text):
    return NS(content=[NS(type="text", text=text)] if text else [], stop_reason="end_turn", usage=_usage())


class _Client:
    def __init__(self, *responses, default=None):
        self.messages = self
        self.queue = list(responses)
        self.default = default if default is not None else _text("Resumen.")
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.queue.pop(0) if self.queue else self.default


FETCH = ("web_fetch", {"url": "https://www.bbc.com/sport/football/12345"})
SEARCH = ("search_web", {"query": "noticias del Arsenal"})


@pytest.fixture(params=["legacy", "loop"])
def flow(request, monkeypatch):
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    if request.param == "loop":
        monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    else:
        monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    return request.param


@pytest.fixture
def run_spy(monkeypatch):
    ran = []

    def _spy(name, args, bootstrap):
        ran.append(name)
        if name in ("web_fetch", "search_web"):
            return {"status": "ok", "url": args.get("url"), "text": "synthetic page", "results": []}
        return {"status": "ok"}

    monkeypatch.setattr(orch_mod, "run_tool", _spy)
    return ran


def _ask(client, **kw):
    return ask_orchestrated(
        "¿ya fue campeón el City?", copy.deepcopy(BOOTSTRAP), client=client, provider="anthropic",
        _eval_client=kw.pop("eval_client", None), **kw,
    )


@pytest.mark.parametrize("tool", [FETCH, SEARCH], ids=["web_fetch", "search_web"])
def test_a_web_tool_named_with_the_toggle_off_is_never_executed(flow, run_spy, tool):
    client = _Client(_tool_use(*tool), _text("No hay datos."))
    result = _ask(client, web_search_enabled=False)
    assert tool[0] not in run_spy
    # The legacy flow ends on the unknown tool itself; the loop records it in the trace.
    trace = [e for e in result.tool_calls_trace if e["name"] == tool[0]]
    assert result.outcome == "unknown_tool" or (trace and all(e["output"].get("code") == "unknown_tool" for e in trace))


def test_the_provider_is_never_offered_a_web_tool_with_the_toggle_off(flow, run_spy):
    client = _Client(_tool_use(*FETCH), _text("No hay datos."))
    _ask(client, web_search_enabled=False)
    for call in client.calls:
        offered = {t["name"] for t in call["tools"]}
        assert "web_fetch" not in offered and "search_web" not in offered
        assert "WEB_OFF" in str(call["system"])


def test_an_extra_round_naming_web_fetch_runs_nothing(flow, run_spy):
    # Round 1 answers with a real tool; the synthesis then asks for web_fetch (a no-text response with a tool call).
    client = _Client(_tool_use("get_injury_list", {}), _tool_use(*FETCH), _text("Resumen."), default=_text("Resumen."))
    _ask(client, web_search_enabled=False)
    assert "web_fetch" not in run_spy


def test_an_evaluator_retry_naming_web_fetch_runs_nothing(flow, run_spy, monkeypatch):
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    verdict = EvaluatorVerdict(approved=False, grounded=False, complete=False, safe=True,
                               retry_feedback="Verifica la noticia.", tokens_used=5)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kw: verdict)
    client = _Client(
        _tool_use("get_injury_list", {}), _text("Lista."),
        _tool_use(*FETCH, cid="t2"), _text("Confirmado."),
        default=_text("Confirmado."),
    )
    _ask(client, web_search_enabled=False, eval_client=object())
    assert "web_fetch" not in run_spy


def test_toggle_on_still_runs_both_web_tools(flow, run_spy):
    client = _Client(_tool_use(*FETCH), _text("Fuente: https://www.bbc.com/sport/football/12345"))
    result = _ask(client, web_search_enabled=True)
    assert "web_fetch" in run_spy
    assert result.tool_chosen == "web_fetch" and result.tool_output["status"] == "ok"
    offered = {t["name"] for t in client.calls[0]["tools"]}
    assert {"web_fetch", "search_web"} <= offered
    assert "WEB_OFF" not in str(client.calls[0]["system"])


# ---------------------------------------------------------------------------
# 4. The routes: /ask (toggle) and /session (no toggle, so always off)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [_PKG] + [
    os.path.join(_PKGS, p) for p in (
        "fpl-api-client", "fpl-data-core", "fpl-player-registry", "fpl-query-tools",
        "fpl-tool-contract", "fpl-tool-runner", "fpl-captain-engine",
    )
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fastapi.testclient import TestClient  # noqa: E402

import fpl_server  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402


@pytest.fixture
def server(monkeypatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def seen(monkeypatch):
    """Route the real orchestrator to a fake model that names web_fetch; record what it was offered."""
    state = {"offered": [], "ran": [], "client": None}
    real = orch_mod.ask_orchestrated

    def _wrapped(question, bootstrap, **kw):
        client = _Client(_tool_use(*FETCH), default=_text("No puedo confirmarlo."))
        state["client"] = client
        kw["client"] = client
        kw["provider"] = "anthropic"
        kw.pop("api_key", None)
        kw["_eval_client"] = None
        out = real(question, bootstrap, **kw)
        state["offered"] = [{t["name"] for t in c["tools"]} for c in client.calls]
        return out

    def _spy(name, args, bootstrap):
        state["ran"].append(name)
        return {"status": "ok", "text": "synthetic page"}

    monkeypatch.setattr(orch_mod, "ask_orchestrated", _wrapped)
    monkeypatch.setattr(orch_mod, "run_tool", _spy)
    return state


Q = "¿Ya fue campeón el City?"


def test_ask_without_the_toggle_offers_and_runs_no_web_tool(server, seen):
    r = server.post("/ask", json={"question": Q}, headers={"X-User-Id": "w-off", "X-User-Tier": "patreon_plus"})
    assert r.status_code == 200
    assert seen["offered"] and all("web_fetch" not in o and "search_web" not in o for o in seen["offered"])
    assert "web_fetch" not in seen["ran"]


def test_ask_with_the_toggle_and_an_eligible_tier_still_offers_both(server, seen):
    r = server.post("/ask", json={"question": Q, "web_search_requested": True},
                    headers={"X-User-Id": "w-on", "X-User-Tier": "patreon_plus"})
    assert r.status_code == 200
    assert seen["offered"] and all({"web_fetch", "search_web"} <= o for o in seen["offered"])
    assert "web_fetch" in seen["ran"]


def test_ask_toggle_with_an_ineligible_tier_makes_no_model_call(server, seen):
    r = server.post("/ask", json={"question": Q, "web_search_requested": True}, headers={"X-User-Id": "w-free"})
    assert r.json()["outcome"] == "feature_gated"
    assert seen["client"] is None and seen["ran"] == []


def test_session_has_no_toggle_so_it_offers_and_runs_no_web_tool(server, seen):
    sid = server.post("/session").json()["session_id"]
    r = server.post(f"/session/{sid}/ask", json={"question": Q}, headers={"X-User-Id": "w-sess", "X-User-Tier": "patreon_plus"})
    assert r.status_code == 200
    assert seen["offered"] and all("web_fetch" not in o and "search_web" not in o for o in seen["offered"])
    assert "web_fetch" not in seen["ran"]
