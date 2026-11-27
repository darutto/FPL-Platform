"""Query layer PR 6: the ``query`` door, its result contract and every projection of it.

No network, no paid call: the model is a script, the tools are the real ones, and the gameweek data is the
synthetic league (``query_golden``) sent through the real ``GwLiveCache``.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant import query_tool
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.query_contract import STATES, project
from fpl_grounded_assistant.query_door_text import (OVERRIDE_BLOCK, PROMPT_REPLACEMENTS, QUERY_DESCRIPTION,
                                                    QUERY_PARAMETERS, SCHEMA_EDITS)
from fpl_grounded_assistant.quota import reset_quota
from fpl_grounded_assistant.tool_schema_registry import get_offered_tool_names, get_tool_schema

from test_query_engine_over_gw_cache import served

FREEZE = json.loads((Path(__file__).parent / "fixtures" / "query_door_freeze.json").read_text(encoding="utf-8"))
RANK = "rank_players_by_metric"


# ------------------------------------------------------------------------------------------------ the freeze

def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def test_the_tool_on_the_wire_is_the_frozen_one_byte_for_byte(monkeypatch):
    monkeypatch.setenv("FPL_QUERY_LAYER", "1")
    wire = get_tool_schema("query").to_openai()
    assert wire == FREEZE["query_tool_wire"]
    assert json.dumps(wire, ensure_ascii=False) == json.dumps(FREEZE["query_tool_wire"], ensure_ascii=False)
    assert _sha(wire) == FREEZE["query_tool_wire_sha256_16"]
    assert (QUERY_DESCRIPTION, QUERY_PARAMETERS) == (wire["description"], wire["parameters"])


def test_the_prompt_and_description_edits_are_the_frozen_ones():
    assert OVERRIDE_BLOCK == FREEZE["override_block"]
    assert [list(r) for r in PROMPT_REPLACEMENTS] == FREEZE["prompt_replacements"]
    assert {k: list(v) for k, v in SCHEMA_EDITS.items()} == FREEZE["schema_edits"]
    assert orch_mod._WEB_OFF_LINE == FREEZE["web_off_line"]


@pytest.mark.parametrize("loop", ["0", "1"])
@pytest.mark.parametrize("locale", ["es", "en"])
def test_with_the_door_on_the_prompt_points_only_at_query(monkeypatch, locale, loop):
    monkeypatch.setenv("FPL_ORCH_LOOP_PROMPT_ENABLED", loop)
    monkeypatch.delenv("FPL_QUERY_LAYER", raising=False)
    off = orch_mod.static_system_prompt(locale, web_enabled=False)
    monkeypatch.setenv("FPL_QUERY_LAYER", "1")
    on = orch_mod.static_system_prompt(locale, web_enabled=False)
    assert RANK in off and RANK not in on
    assert OVERRIDE_BLOCK in on and "call query FIRST and as the ONLY tool" in on


@pytest.mark.parametrize("web", [False, True])
@pytest.mark.parametrize("fi", [False, True])
def test_with_the_door_on_the_ranking_is_withdrawn_and_query_offered_last(monkeypatch, fi, web):
    monkeypatch.delenv("FPL_QUERY_LAYER", raising=False)
    off = orch_mod._build_tools("openai", web_search_enabled=web, football_intelligence_enabled=fi)
    assert RANK in [t["name"] for t in off] and "query" not in [t["name"] for t in off]
    assert "query" not in get_offered_tool_names(fi, web_search_enabled=web)
    monkeypatch.setenv("FPL_QUERY_LAYER", "1")
    on = orch_mod._build_tools("openai", web_search_enabled=web, football_intelligence_enabled=fi)
    names = [t["name"] for t in on]
    assert RANK not in names and "query" in names
    assert [n for n in names if n not in ("query", "search_web")] == [
        t["name"] for t in off if t["name"] not in (RANK, "search_web")]
    assert RANK not in get_offered_tool_names(fi, web_search_enabled=web)
    changed = {t["name"] for t in on if t["name"] != "query"
               and t != next(o for o in off if o["name"] == t["name"])}
    assert changed == set(SCHEMA_EDITS)
    assert not [t["name"] for t in on if t["name"] != "query" and RANK in t["description"]]


# ------------------------------------------------------------------------------------------ a scripted model

def _usage():
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


def calls(*tools):
    """One model response asking for these (name, args) tools."""
    return NS(content=[NS(type="tool_use", id=f"tu_{i}", name=n, input=a) for i, (n, a) in enumerate(tools, 1)],
              stop_reason="tool_use", usage=_usage())


def says(text="MODEL PROSE"):
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=_usage())


class Script:
    def __init__(self, *responses) -> None:
        self.messages, self.queue, self.extra = self, list(responses), 0

    def create(self, **_kwargs):
        if not self.queue:
            # counted, not only raised: the provider layer turns a raise into a failed call and carries on
            self.extra += 1
            raise AssertionError("a model call after the query door had answered")
        return self.queue.pop(0)


def v(value, quote="x"):
    return {"value": value, "quote": quote}


def ne(kind, quote):
    return {"kind": kind, "quote": quote}


#: state -> (what the user types, the model's query arguments)
CASES = {
    "complete": ("Most points in the last 5",
                 {"metric": v("total_points"), "match_set": [{"pred": "last_n", "value": 5, "quote": "last 5"}]}),
    "needs_clarification": ("Team goals without Subject",
                            {"metric": v("team_goals"),
                             "match_set": [{"pred": "player_absent", "value": "Subject", "quote": "Subject"}]}),
    "unsupported_constraint": ("Most points at home",
                               {"metric": v("total_points"),
                                "match_set": [{"pred": "venue", "value": "home", "quote": "at home"}]}),
    "data_unavailable": ("Most points from GW7 to GW10",
                         {"metric": v("total_points"),
                          "match_set": [{"pred": "gw_range", "value": [7, 10], "quote": "GW7 to GW10"}]}),
}
EXPECTED = {   # outcome, supported, review_passed, clarification_asked
    "complete": ("ok", True, True, False),
    "needs_clarification": ("needs_clarification", False, True, True),
    "unsupported_constraint": ("unsupported_constraint", False, False, False),
    "data_unavailable": ("data_unavailable", True, True, False),
}
OTHER = ("get_current_gameweek", {})

#: route -> the model's responses; the query call is always the last thing it is asked for
ROUTES = {
    "plain": lambda q: (calls(("query", q)),),
    "two_tools": lambda q: (calls(OTHER, ("query", q)),),
    "extra_round": lambda q: (calls(OTHER), calls(("query", q))),
    "evaluator_retry": lambda q: (calls(OTHER), says(), calls(("query", q))),
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"must not touch the network: {address!r}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    for name in ("FPL_JEV_MODE", "FPL_ORCH_LOOP_ENABLED", "FPL_ORCH_LOOP_PROMPT_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setenv("FPL_QUERY_LAYER", "1")


@pytest.fixture
def server(monkeypatch):
    bootstrap, cache = served()
    bootstrap["element_types"] = [{"id": i, "singular_name_short": s}
                                  for i, s in enumerate(("GKP", "DEF", "MID", "FWD"), start=1)]
    for element in bootstrap["elements"]:
        element.setdefault("status", "a")
    monkeypatch.setattr(query_tool, "default_cache", lambda: cache)
    monkeypatch.setattr(query_tool, "_today", lambda _bootstrap: dt.date(2026, 10, 10))
    fpl_server._init_bootstrap(bootstrap)
    fpl_server._sessions.clear()
    reset_quota()
    audit: list = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", audit.append)
    client = TestClient(fpl_server.app)
    client.audit = audit
    yield client
    fpl_server._sessions.clear()
    reset_quota()


def ask(server, monkeypatch, question, script, surface="ask", route="plain", locale="en", user=None):
    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: script)
    if route == "evaluator_retry":
        from fpl_grounded_assistant import harness

        monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
        monkeypatch.setattr(harness, "_build_eval_client", lambda *a, **k: object())
        monkeypatch.setattr(orch_mod, "evaluate_response", lambda **_k: EvaluatorVerdict(
            approved=False, grounded=False, complete=False, safe=True, off_topic_score=0.0,
            retry_feedback="answer it", tokens_used=7))
    headers = {"X-User-Id": user or f"u-{surface}-{route}-{locale}-{abs(hash(question))}"}
    path = "/ask"
    if surface == "session":
        path = f"/session/{server.post('/session').json()['session_id']}/ask"
    response = server.post(path, json={"question": question, "locale": locale}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# -------------------------------------------------------------------------------------- the contract matrix

@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("surface", ["ask", "session"])
@pytest.mark.parametrize("state", STATES)
def test_contract_matrix(server, monkeypatch, state, surface, route):
    question, args = CASES[state]
    script = Script(*ROUTES[route](args))
    body = ask(server, monkeypatch, question, script, surface, route)
    block = body["query"]

    assert block["state"] == state, block
    assert (body["outcome"], body["supported"], body["review_passed"], body["clarification_asked"]) == EXPECTED[state]
    assert body["intent"] == "query" and body["llm_used"] is False
    assert (len(script.queue), script.extra) == (0, 0)             # and none asked for after the door answered
    assert "MODEL PROSE" not in json.dumps(body)
    # the reading line is the first line of the text, and the block's
    assert body["final_text"].splitlines()[0] == "Showing: " + block["reading"]["text"]
    if state == "complete":
        assert block["table"]["rows"] and block["message"] is None
        assert all(len(row) == len(block["table"]["columns"]) for row in block["table"]["rows"])
        assert not any(p["braked"] for p in block["reading"]["parts"])
    else:
        assert block["table"] is None and block["comparison"] is None and block["notes"] == []
        assert block["message"] and body["final_text"].splitlines()[1:] == [block["message"]]
        assert any(p["braked"] for p in block["reading"]["parts"])
        for element in fpl_server._bootstrap["elements"]:
            if element["web_name"] != "SubjectAld":
                assert element["web_name"] not in body["final_text"]
    for slot in ("generic_card", "comparison", "captain", "differential", "player_snapshot", "table_conclusions",
                 "web_search", "resource_rows"):
        assert body.get(slot) is None, slot


@pytest.mark.parametrize("surface", ["ask", "session"])
def test_query_keeps_the_slot_when_a_later_tool_of_the_round_crashes(server, monkeypatch, surface):
    real = orch_mod.run_tool

    def crash_on_the_other(name, args, bootstrap):
        if name == OTHER[0]:
            raise RuntimeError("boom")
        return real(name, args, bootstrap)

    monkeypatch.setattr(orch_mod, "run_tool", crash_on_the_other)
    script = Script(calls(("query", CASES["complete"][1]), OTHER))
    body = ask(server, monkeypatch, CASES["complete"][0], script, surface)
    assert (body["outcome"], body["query"]["state"], script.extra) == ("ok", "complete", 0)


@pytest.mark.parametrize("surface", ["ask", "session"])
def test_spanish_answer_and_its_clarify_chips(server, monkeypatch, surface):
    question = "Goles del equipo sin Subject"
    body = ask(server, monkeypatch, question, Script(calls(("query", CASES["needs_clarification"][1]))),
               surface, locale="es")
    assert body["final_text"].startswith("Muestro: ")
    assert body["query"]["message"] == "¿A qué jugador te refieres con «Subject»?"
    chips = body["query"]["chips"]
    assert chips and all(set(c) == {"label", "spec"} for c in chips)


def test_a_chip_spec_runs_and_settles_the_name(server):
    bootstrap = fpl_server._bootstrap
    first = query_tool.answer_call(CASES["needs_clarification"][1], {**bootstrap, "_question": "Subject"})
    chip = first["query"]["chips"][0]
    from fpl_grounded_assistant.query_spec import parse_spec

    second = query_tool.run_spec(parse_spec(chip["spec"]), bootstrap, "es")
    assert second["query"]["state"] in ("complete", "data_unavailable")


def test_the_comparison_block(server, monkeypatch):
    args = {"metric": v("team_goals"), "shape": v("comparison"), "operator": v("per_match"),
            "filters": [{"field": "club", "op": "eq", "value": "Alder Town", "quote": "Alder Town"}],
            "match_set": [{"pred": "player_played_60", "value": "SubjectAld", "quote": "SubjectAld"}],
            "compare_to": [{"pred": "player_absent", "value": "SubjectAld", "quote": "SubjectAld"}]}
    body = ask(server, monkeypatch, "Alder Town goals with and without SubjectAld", Script(calls(("query", args))))
    block = body["query"]
    assert block["state"] == "complete", block
    assert block["table"] is None
    comparison = block["comparison"]
    assert [s["n"] for s in comparison["sides"]] == [4, 3] and comparison["mixed"] == [{"gameweek": 7, "minutes": 13}]
    assert comparison["sides"][0]["value_text"] == comparison["sides"][0]["per_match_text"] == "1.50"
    assert comparison["small_sample"] is True and any("Small sample" in n for n in block["notes"])
    assert len(body["final_text"].splitlines()) == 1 + 2 + len(block["notes"])


# ------------------------------------------------------------------------------------- refusals without a spec

@pytest.mark.parametrize("args,state,reason,reading", [
    ({"metric": v("total_points"), "colour": "blue"}, "needs_clarification", "invalid_spec", False),
    ({"metric": v("corners_taken")}, "needs_clarification", "invalid_spec", False),
    ({"metric": v("total_points"), "top_n": v(5.0)}, "needs_clarification", "invalid_spec", False),
    ({"not_expressible": [ne("month", "in October")]}, "unsupported_constraint", "month", True),
    ({"ambiguous": [{"quote": "lately"}]}, "needs_clarification", "ambiguous_phrase", False),
])
def test_a_call_with_nothing_to_run_is_still_an_honest_state(server, monkeypatch, args, state, reason, reading):
    body = ask(server, monkeypatch, "points in October lately", Script(calls(("query", args))))
    block = body["query"]
    assert (block["state"], block["reason"], block["reading"] is not None) == (state, reason, reading)
    assert block["table"] is None and block["spec"] is None and block["message"]


def test_a_brake_reads_the_typed_text_not_the_models_spec(server, monkeypatch):
    # the model dropped "at the time": B1 brakes it
    body = ask(server, monkeypatch, "Most points by players under 10% owned at the time",
               Script(calls(("query", {"metric": v("total_points"), "filters": [
                   {"field": "owned_now", "op": "lt", "value": 10, "quote": "under 10% owned"}]}))))
    assert (body["query"]["state"], body["query"]["reason"]) == ("unsupported_constraint", "ownership_then")
    assert body["query"]["chips"] and "today's ownership" in body["query"]["message"]


def test_a_source_that_fails_is_data_unavailable_and_no_other_tool_answers(server, monkeypatch):
    def boom():
        raise RuntimeError("no source")

    monkeypatch.setattr(query_tool, "default_cache", boom)
    script = Script(calls(("query", CASES["complete"][1])))
    body = ask(server, monkeypatch, CASES["complete"][0], script)
    assert (body["outcome"], body["query"]["reason"], body["query"]["table"]) == (
        "data_unavailable", "internal_error", None)


def test_the_withdrawn_ranking_cannot_be_run_by_name(server, monkeypatch):
    body = ask(server, monkeypatch, "top scorers", Script(calls((RANK, {"metric": "goals_scored"})), says("sorry")))
    assert body.get("query") is None and body["outcome"] != "ok"
    assert body.get("generic_card") is None


# ------------------------------------------------------------------------------------------------------ audit

@pytest.mark.parametrize("surface", ["ask", "session"])
def test_the_audit_line_keeps_enums_and_no_quote_of_the_user(server, monkeypatch, surface):
    secret = "zebra words"
    args = {"metric": v("total_points", secret), "not_expressible": [ne("opponent", secret)]}
    ask(server, monkeypatch, f"points {secret}", Script(calls(OTHER, ("query", args))), surface)
    entry = server.audit[-1]
    (call,) = [c for c in entry.tool_calls if c["name"] == "query"]
    assert call["args"] == {} and call["output_status"] == "unsupported_constraint"
    assert call["query"] == {"state": "unsupported_constraint", "reason": "opponent", "brake": "B3"}
    assert secret not in json.dumps(entry.tool_calls)
    assert entry.outcome == "unsupported_constraint" and entry.intent == "query"


# ------------------------------------------------------------------------------------------ the one projection

def test_the_projection_covers_every_state_and_reads_an_unknown_one_as_unsupported():
    for state in STATES:
        p = project({"state": state})
        assert (p["outcome"], p["supported"], p["review_passed"], p["clarification_asked"]) == EXPECTED[state]
    assert project({"state": "new_thing"}) == project({"state": "unsupported_constraint"})


def test_multi_intent_sub_calls_get_the_typed_message(monkeypatch):
    from fpl_grounded_assistant import final_response as fr

    seen = []
    real = fr.respond

    def spy(user_message, bootstrap, **kwargs):
        if kwargs.get("_multi_intent_depth"):
            seen.append(kwargs.get("_raw_question"))
            raise _Stop()
        return real(user_message, bootstrap, **kwargs)

    class _Stop(Exception):
        pass

    monkeypatch.setattr(fr, "respond", spy)
    monkeypatch.setattr(fr, "detect_multi_intent", lambda _m: ["a", "b"])
    with pytest.raises(_Stop):
        real("typed whole message", {}, _raw_question="what was typed")
    assert seen == ["what was typed"]


# -------------------------------------------------------------------------------------------------- door off

OFF_FIXTURE = Path(__file__).parent / "fixtures" / "query_door_off_responses.json"
OFF_TURNS = {
    "ranking": ("top scorers", lambda: Script(calls((RANK, {"metric": "goals_scored", "top_n": 3})),
                                              says("Three names."))),
    "gameweek": ("what gameweek is it", lambda: Script(calls(OTHER), says("It is that one."))),
    "no_tool": ("hello there", lambda: Script(says("Ask me about FPL."))),
}


def door_off_responses(server, monkeypatch) -> dict:
    monkeypatch.delenv("FPL_QUERY_LAYER", raising=False)
    out = {}
    for name, (question, script) in OFF_TURNS.items():
        for surface in ("ask", "session"):
            body = ask(server, monkeypatch, question, script(), surface, user=f"off-{name}-{surface}")
            body.pop("session_id", None)
            out[f"{surface}:{name}"] = body
    return out


def test_door_off_serves_what_was_served_before_the_door(server, monkeypatch):
    """The fixture was captured by running this same function on the commit before the door."""
    expected = json.loads(OFF_FIXTURE.read_text(encoding="utf-8"))
    got = door_off_responses(server, monkeypatch)
    assert all("query" not in body for body in got.values())
    assert json.dumps(got, sort_keys=False, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)


# --------------------------------------------------------------------- the serialized bodies the UI builds from

BODIES_FIXTURE = Path(__file__).parent / "fixtures" / "query_response_bodies.json"

_WITH_WITHOUT = {
    "metric": v("team_goals"), "shape": v("comparison"), "operator": v("per_match"),
    "filters": [{"field": "club", "op": "eq", "value": "Alder Town", "quote": "Alder Town"}],
    "match_set": [{"pred": "player_played_60", "value": "SubjectAld", "quote": "SubjectAld"}],
    "compare_to": [{"pred": "player_absent", "value": "SubjectAld", "quote": "SubjectAld"}]}
_OWNED_THEN = {"metric": v("total_points"),
               "filters": [{"field": "owned_now", "op": "lt", "value": 10, "quote": "under 10% owned"}]}

#: name -> (locale, what the user typed, the model's arguments, SubjectAld joins after GW1)
BODIES = {
    "complete_list_es": ("es", "Más puntos en las últimas 5", CASES["complete"][1], False),
    "complete_list_en": ("en", CASES["complete"][0], CASES["complete"][1], False),
    "complete_comparison_before_join": ("en", "Alder Town goals with and without SubjectAld", _WITH_WITHOUT, True),
    "needs_clarification": ("es", "Goles del equipo sin Subject", CASES["needs_clarification"][1], False),
    "unsupported_constraint": ("en", "Most points by players under 10% owned at the time", _OWNED_THEN, False),
    "data_unavailable": ("es", "Más puntos de la J7 a la J10", CASES["data_unavailable"][1], False),
    "unreadable_call": ("es", "puntos", {"metric": v("corners_taken")}, False),
}


def response_bodies(server, monkeypatch) -> dict:
    """The /ask body of each case, from the synthetic league."""
    out = {}
    for name, (locale, question, args, late_join) in BODIES.items():
        subject = next(e for e in fpl_server._bootstrap["elements"] if e["id"] == 106)
        monkeypatch.setitem(subject, "team_join_date", "2026-08-20" if late_join else "2025-07-01")
        out[name] = ask(server, monkeypatch, question, Script(calls(("query", args))), locale=locale,
                        user=f"body-{name}")
    return out


def test_the_committed_bodies_are_what_the_server_serves(server, monkeypatch):
    got = response_bodies(server, monkeypatch)
    if os.environ.get("FPL_REWRITE_QUERY_BODIES"):
        BODIES_FIXTURE.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                  newline="\n")
    assert got == json.loads(BODIES_FIXTURE.read_text(encoding="utf-8"))
    assert {b["query"]["state"] for b in got.values()} == set(STATES)
    comparison = got["complete_comparison_before_join"]["query"]["comparison"]
    assert comparison["before_join"] == [1] and [s["n"] for s in comparison["sides"]] == [3, 3]
