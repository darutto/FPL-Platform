"""i125(a) -- a captain answer's top N is the tool's top N, defenders included.

Baseline (prod /ask, 2026-10-02, R=5 per arm, top 3 graded against the
card's own list by scripts/grade_i125a_captain_list.py): 2/5 with a linked
team, 0/5 without -- the model dropped Tarkowski (DEF, ranked 2nd).

Decision (Leo): respect the ranking. The numbered list is composed from the
tool output (captain_list.py) and prepended; the model writes the
commentary. The list is the CARD's list -- presentation.owned_top with a
squad connected, global_top without -- so prose and card cannot disagree.

Fixtures are two real prod rank_captain_candidates outputs (team / no team)
and the model's real text for them. Fake Anthropic-shaped client, tools
served from fixtures, evaluator off -- no network, no paid call.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.captain_list import (
    DEFAULT_TOP,
    captain_list,
    captain_list_rule,
    compose_captain_answer,
    last_captain_output,
    presented_entries,
    requested_top,
)
from fpl_grounded_assistant.orchestrator import _LOOP_SYSTEM_PROMPT, _SYSTEM_PROMPT, ask_orchestrated

from conftest import BOOTSTRAP

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "i125a_captain_outputs_2026-10-02.json").read_text(encoding="utf-8")
)
QUESTION = "¿A quién capitaneo esta jornada? Dame un top 3 numerado."
TEAM = FIXTURE["team"]["tool_output"]
NOTEAM = FIXTURE["noteam"]["tool_output"]
UI_FIXTURE = Path(__file__).resolve().parents[2] / "fpl-ui" / "__tests__" / "fixtures" / "i125a-captain-ask.json"

_spec = importlib.util.spec_from_file_location(
    "_i125a_grader", Path(__file__).resolve().parents[1] / "scripts" / "grade_i125a_captain_list.py")
grader = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = grader
_spec.loader.exec_module(grader)


def _names(text: str) -> list[str]:
    return [line.split("**")[1] for line in text.splitlines() if line[:1].isdigit() and "**" in line]


# ---------------------------------------------------------------------------
# A. the list is the card's list, in the card's order
# ---------------------------------------------------------------------------

def test_team_list_is_owned_top_with_the_defender_second():
    text = captain_list(TEAM, QUESTION)
    assert _names(text) == ["Groß", "Tarkowski", "Haaland"]
    assert "2. **Tarkowski** (EVE, DEF) — 67,6" in text
    assert "de tu plantilla" in text and "GW6" in text


def test_no_team_list_is_global_top():
    assert _names(captain_list(NOTEAM, QUESTION)) == ["Groß", "Tarkowski", "Barnes"]


def test_list_ids_are_exactly_the_presentation_ids():
    for out, key in ((TEAM, "owned_top"), (NOTEAM, "global_top")):
        ids = [c["player_id"] for c in presented_entries(out)]
        assert ids == out["presentation"][key]


@pytest.mark.parametrize("question, expected", [
    ("¿A quién capitaneo? Dame un top 3", 3),
    ("top5 capitanes", 5),
    ("dame 5 opciones de capitán", 5),
    ("los tres mejores capitanes", 3),
    ("top-10 capitanes", 10),
    ("¿A quién capitaneo esta jornada?", None),
])
def test_requested_top(question, expected):
    assert requested_top(question) == expected


def test_n_defaults_and_is_cut_to_the_list():
    assert len(_names(captain_list(NOTEAM, "¿a quién capitaneo?"))) == DEFAULT_TOP
    assert len(_names(captain_list(TEAM, "dame un top 10"))) == len(TEAM["presentation"]["owned_top"])


def test_no_presentation_ids_means_no_list():
    bare = {**NOTEAM, "presentation": {}}
    assert captain_list(bare, QUESTION) is None
    assert compose_captain_answer("cuerpo", bare, QUESTION) == "cuerpo"
    assert captain_list({**NOTEAM, "status": "error"}, QUESTION) is None


def test_last_captain_output_reads_the_trace():
    trace = [{"name": "rank_captain_candidates", "output": {"status": "error"}},
             {"name": "rank_captain_candidates", "output": NOTEAM},
             {"name": "get_current_gameweek", "output": {"status": "ok"}}]
    assert last_captain_output(trace) is NOTEAM
    assert last_captain_output([]) is None


# ---------------------------------------------------------------------------
# B. the gate's grader: the real model texts fail, the composed answer passes
# ---------------------------------------------------------------------------

def _graded(output: dict, text: str) -> dict:
    by_id = [{"player_id": c["player_id"], "web_name": c["web_name"]} for c in output["ranked_candidates"]]
    body = {"final_text": text, "captain_ranking": by_id, "presentation": output["presentation"],
            "squad_source": output["squad_source"]}
    return grader.grade(body, 3)


@pytest.mark.parametrize("arm", ["team", "noteam"])
def test_real_model_text_misses_and_composed_answer_matches(arm):
    out, text = FIXTURE[arm]["tool_output"], FIXTURE[arm]["model_text"]
    assert _graded(out, text)["match"] is False          # the baseline defect, on the real text
    assert _graded(out, compose_captain_answer(text, out, QUESTION))["match"] is True


# ---------------------------------------------------------------------------
# C. end to end through ask_orchestrated
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i125(a) tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")


def _usage() -> NS:
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


class _Client:
    def __init__(self, *responses: NS) -> None:
        self.messages = self
        self.queue = list(responses)

    def create(self, **_kwargs):
        return self.queue.pop(0) if self.queue else NS(content=[], usage=_usage())


def _tool(cid: str = "c1") -> NS:
    return NS(content=[NS(type="tool_use", id=cid, name="rank_captain_candidates", input={"gameweek": 6})],
              usage=_usage())


def _text(text: str) -> NS:
    return NS(content=[NS(type="text", text=text)], usage=_usage())


def _serve(monkeypatch, output: dict) -> None:
    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: json.loads(json.dumps(output)))


COMMENT = "Groß llega con forma 10,7 y lanza penaltis; Tarkowski suma por portería a cero."


def test_answer_opens_with_the_list_and_keeps_the_model_commentary(monkeypatch):
    _serve(monkeypatch, TEAM)
    r = ask_orchestrated(QUESTION, BOOTSTRAP, client=_Client(_tool(), _text(COMMENT)))
    assert r.answer_text.startswith("**Tus mejores opciones de capitán")
    assert _names(r.answer_text) == ["Groß", "Tarkowski", "Haaland"]
    assert r.answer_text.endswith(COMMENT)
    assert r.synthesis_turn is True                    # the body is still the model's


def test_no_list_when_the_guard_replaced_the_text(monkeypatch):
    _serve(monkeypatch, NOTEAM)
    html = "<!DOCTYPE html><html><body>" + "<p>x</p>" * 80 + "</body></html>"
    r = ask_orchestrated(QUESTION, BOOTSTRAP, client=_Client(_tool(), _text(html)))
    assert r.final_text_guard_reason is not None
    assert "Groß" not in r.answer_text


def test_no_list_when_the_tool_did_not_come_back_ok(monkeypatch):
    _serve(monkeypatch, {"status": "error", "code": "x", "message": "boom"})
    r = ask_orchestrated(QUESTION, BOOTSTRAP, client=_Client(_tool(), _text("No pude rankear.")))
    assert "opciones de capitán" not in r.answer_text


def test_the_rule_is_in_both_system_prompts():
    rule = captain_list_rule()
    assert rule in _SYSTEM_PROMPT and rule in _LOOP_SYSTEM_PROMPT
    assert "defender or goalkeeper" in rule and "Do NOT write your own numbered" in rule


# ---------------------------------------------------------------------------
# D. card and text name the same list -- read off the HTTP body; the UI test
#    renders RankingTable from the same body (fpl-ui i125a-captain-list).
# ---------------------------------------------------------------------------

@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    import fpl_server
    from fpl_grounded_assistant.quota import reset_quota

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    fpl_server._init_bootstrap(json.loads(json.dumps(BOOTSTRAP)))
    reset_quota()
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    reset_quota()


def _ask(server, monkeypatch, output: dict, user: str) -> dict:
    _serve(monkeypatch, output)
    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: _Client(_tool(), _text(COMMENT)))
    return server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": user}).json()


def _card_primary_names(body: dict) -> list[str]:
    """What RankingTable paints first: owned_top when connected, else global_top."""
    by_id = {e["player_id"]: e["web_name"] for e in body["captain_ranking"]}
    key = "owned_top" if body["squad_source"] == "connected" else "global_top"
    return [by_id[i] for i in body["presentation"][key]]


@pytest.mark.parametrize("arm", ["team", "noteam"])
def test_http_text_list_is_the_card_list(server, monkeypatch, arm):
    body = _ask(server, monkeypatch, FIXTURE[arm]["tool_output"], f"u-i125a-{arm}")
    assert body["intent"] == "rank_candidates"
    card = _card_primary_names(body)
    assert _names(body["final_text"]) == card[:3]
    assert grader.grade(body, 3)["match"] is True


def test_ui_fixture_is_what_post_ask_serves(server, monkeypatch):
    pinned = json.loads(UI_FIXTURE.read_text(encoding="utf-8"))
    for arm in ("team", "noteam"):
        body = _ask(server, monkeypatch, FIXTURE[arm]["tool_output"], f"u-i125a-pin-{arm}")
        for key in ("final_text", "intent", "outcome", "captain_ranking", "presentation", "squad_source"):
            assert pinned[arm][key] == body[key], (arm, key)


def test_requested_n_beyond_the_default_is_honoured():
    assert _names(captain_list(NOTEAM, "dame un top 5 de capitanes")) == [
        "Groß", "Tarkowski", "Barnes", "Schade", "Haaland"]


def test_compose_skips_a_turn_that_did_not_end_ok():
    from fpl_grounded_assistant.orchestrator import OrchestratorResult, _compose_captain_answer

    r = OrchestratorResult(
        question=QUESTION, tool_chosen="get_player_form", tool_args={}, tool_output={"status": "ambiguous"},
        answer_text="¿Qué Martínez?", llm_used=True, model="m", outcome="tool_result_error",
        tool_calls_trace=({"name": "rank_captain_candidates", "output": NOTEAM},),
    )
    assert _compose_captain_answer(r, QUESTION).answer_text == "¿Qué Martínez?"
    ok = OrchestratorResult(
        question=QUESTION, tool_chosen="rank_captain_candidates", tool_args={}, tool_output=NOTEAM,
        answer_text="cuerpo", llm_used=True, model="m", outcome="ok",
        tool_calls_trace=({"name": "rank_captain_candidates", "output": NOTEAM},),
    )
    assert _compose_captain_answer(ok, QUESTION).answer_text.endswith("cuerpo")
    assert _compose_captain_answer(ok, QUESTION).answer_text != "cuerpo"
