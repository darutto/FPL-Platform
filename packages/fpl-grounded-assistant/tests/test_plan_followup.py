"""plan_to_sign follow-up: state survives to the next turn through the real /ask path.

Two halves:

* unit: the phrase matcher (EN + ES), the validation of the client-sent state and the
  arguments a follow-up asks the tool for;
* the fixed acceptance conversation -- the three lines that opened this track, in EN and
  in ES -- driven through ``POST /ask`` (the endpoint the chat uses for every plain turn)
  with a scripted stand-in for the model. The stand-in only chooses the tool call, as the
  model would; resolution, search, ranking, rendering, chips, the response contract and
  the follow-up route are all the real code. No network, no paid call.

The synthetic squad is the one ``test_plan_to_sign`` uses; no store values.
"""
from __future__ import annotations

import importlib
import json
import re
import socket

import pytest

from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.plan_followup import (
    followup_args,
    is_plan_followup,
    move_tap,
    sanitize_plan_state,
)
from fpl_grounded_assistant.renderer import render
from test_plan_to_sign import _bootstrap, _squad_payload

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")


# ---------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "who else can i sell from my team to get the 1.2 million i need to get jackson?",
    "who else can I sell?",
    "anyone else I could sell to raise the money",
    "what else can I sell",
    "show me other options",
    "¿a quién más puedo vender de mi equipo para conseguir el 1.2 millones que necesito para fichar a jackson?",
    "¿a quién más vendo para conseguir el dinero?",
    "quién más puedo vender",
    "¿qué otro jugador puedo vender?",
    "dame otras opciones",
])
def test_followup_phrases_match(question):
    assert is_plan_followup(question)


@pytest.mark.parametrize("question", [
    "how do i get nico jackson with my current team?",
    "who is nico jackson",
    "¿cómo ficho a jackson con mi equipo actual?",
    "¿quién es el mejor delantero?",
    "who should i captain",
    "",
    "a" * 400,
])
def test_other_questions_do_not_match(question):
    assert not is_plan_followup(question)


GOOD = {
    "target_id": 100, "moves": "hits", "shown_out_ids": [14, 13], "planned_out_ids": [14],
    "excluded_out_ids": [3], "bank_source": "user", "bank_tenths": 45, "free_transfers": 2,
    "user_sell_prices": [{"player": "13", "price": 8.0}],
}


def test_sanitize_keeps_only_the_named_valid_fields():
    state = sanitize_plan_state({**GOOD, "evil": "<script>", "shown_out_ids": [14, "x", True, 13.5, 13]})
    assert state["shown_out_ids"] == [14, 13] and "evil" not in state
    assert state["bank_tenths"] == 45 and state["free_transfers"] == 2


@pytest.mark.parametrize("bad", [
    None, "x", [], {}, {"target_id": "100", "moves": "one"}, {"target_id": True, "moves": "one"},
    {"target_id": 1, "moves": "everything"},
])
def test_sanitize_rejects_what_is_not_a_plan_state(bad):
    assert sanitize_plan_state(bad) is None


def test_bank_is_only_carried_when_it_was_the_users_own():
    state = sanitize_plan_state({**GOOD, "bank_source": "squad", "bank_tenths": 45})
    assert "bank_tenths" not in state
    assert "bank" not in followup_args(state)


def test_followup_args_exclude_everyone_already_offered_and_keep_the_users_numbers():
    args = followup_args(sanitize_plan_state(GOOD))
    assert args["target"] == "100" and args["moves"] == "hits"
    assert args["exclude_out_ids"] == [3, 13, 14]
    assert args["bank"] == 4.5 and args["free_transfers"] == 2
    assert args["sell_prices"] == [{"player": "13", "price": 8.0}]


# ---------------------------------------------------------------------------
# acceptance conversation, through POST /ask
# ---------------------------------------------------------------------------

LINES = {
    "en": (
        "how do i get nico jackson with my current team?",
        "how do i get n. jackson with my current team?",
        "who else can i sell from my team to get the 1.2 million i need to get jackson?",
    ),
    "es": (
        "¿cómo ficho a nico jackson con mi equipo actual?",
        "¿cómo ficho a n. jackson con mi equipo actual?",
        "¿a quién más puedo vender de mi equipo para conseguir el 1.2 millones que necesito para fichar a jackson?",
    ),
}
_MENTION = re.compile(r"(nico jackson|n\. jackson|n\.jackson)")


class _Script:
    """Stands in for the model: decides which tool to call, nothing else."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, question, bootstrap, *args, **kwargs):
        from fpl_tool_runner import run_tool

        self.calls.append(question)
        folded = question.lower()
        mention = _MENTION.search(folded)
        if not mention:  # the script only knows 'get Jackson' questions: anything else is a no-tool turn
            return OrchestratorResult(
                question=question, tool_chosen=None, tool_args={}, tool_output={},
                answer_text="no tool", llm_used=True, model="fake", outcome="no_tool",
            )
        call: dict = {"target": mention.group(1)}
        if "hits" in folded:
            call["moves"] = "hits"
        elif "1 transfer" in folded or "1 traspaso" in folded:
            call["moves"] = "one"
        out = run_tool("plan_to_sign", call, bootstrap)
        locale = kwargs.get("locale", "es")
        return OrchestratorResult(
            question=question, tool_chosen="plan_to_sign", tool_args=call, tool_output=out,
            answer_text=render("plan_to_sign", out, locale=locale), llm_used=True, model="fake",
            outcome="ok", tool_call_count=1,
        )


@pytest.fixture
def chat(monkeypatch):
    from fastapi.testclient import TestClient

    import fpl_server
    from fpl_grounded_assistant import harness as harness_mod
    from fpl_grounded_assistant.quota import reset_quota

    real_connect = socket.socket.connect

    def loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"this test must not touch the network: {address!r}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    for name in ("FPL_JEV_MODE", "FPL_ORCH_LOOP_ENABLED", "FPL_EVAL_DISABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(harness_mod, "_build_eval_client", lambda *a, **k: object())
    monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: _squad_payload(30))
    script = _Script()
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", script)
    fpl_server._init_bootstrap(json.loads(json.dumps(_bootstrap())))
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    client = TestClient(fpl_server.app)

    def post(question, locale, plan_state=None):
        body = {"question": question, "locale": locale}
        if plan_state is not None:
            body["plan_state"] = plan_state
        res = client.post("/ask", json=body)
        assert res.status_code == 200, res.text
        return res.json()

    yield post, script
    fpl_server._sessions.clear()
    reset_quota()


@pytest.mark.parametrize("locale", ["en", "es"])
def test_the_three_lines_that_opened_the_track(chat, locale):
    post, script = chat
    line1, line2, line3 = LINES[locale]

    # 1. "nico jackson" resolves (colloquial name) and the answer asks how many moves.
    first = post(line1, locale)
    assert first["outcome"] == "ok" and "N.Jackson" in first["final_text"]
    assert first["plan_state"] is None  # still choosing: nothing to follow up on
    chips = first["suggestions"]
    assert [c["kind"] for c in chips] == ["plan_option", "plan_option"]  # free count unknown: 1 transfer, hits

    # 2. "n. jackson" is the same player and the same step.
    second = post(line2, locale)
    assert second["final_text"] == first["final_text"]
    assert second["suggestions"] == chips

    # The user taps "use hits": a ranked plan with a state to follow up on.
    hits_chip = chips[-1]
    plan = post(hits_chip["send_text"], locale)
    state = plan["plan_state"]
    assert state and state["target_id"] == 100 and state["moves"] == "hits"
    assert state["shown_out_ids"]
    asked_before = len(script.calls)

    # 3. "who else can I sell ..." -- sent as the UI sends it: the next /ask, carrying the state.
    follow = post(line3, locale, plan_state=state)
    assert len(script.calls) == asked_before, "the follow-up must not reach the model"
    assert follow["outcome"] == "ok"
    assert "Jackson" in follow["final_text"]            # it is the plan, not a player snapshot
    assert follow["player_snapshot"] is None
    new_state = follow["plan_state"]
    assert new_state["target_id"] == 100
    new_outs = {tr_out for tr_out in new_state["shown_out_ids"]}
    assert new_outs and not (new_outs & set(state["shown_out_ids"])), "'who else' must offer new names"
    assert set(state["shown_out_ids"]) <= set(new_state["excluded_out_ids"])

    # ... and the next "who else" moves on again.
    again = post(line3, locale, plan_state=new_state)
    assert len(script.calls) == asked_before
    if again["plan_state"] is not None:
        assert not (set(again["plan_state"]["shown_out_ids"]) & (set(state["shown_out_ids"]) | new_outs))


@pytest.mark.parametrize("locale", ["en", "es"])
def test_without_the_state_the_followup_is_not_hijacked(chat, locale):
    """A "who else" with no preceding plan goes the normal route (here: the scripted model,
    which only knows Jackson questions) -- the follow-up route never fires on its own."""
    post, script = chat
    res = post(LINES[locale][2].replace("jackson", "someone"), locale)
    assert len(script.calls) == 1 and res["plan_state"] is None


def test_a_forged_state_is_dropped_not_trusted(chat):
    post, script = chat
    res = post(LINES["en"][2].replace("jackson", "someone"), "en", plan_state={"target_id": "100", "moves": "hits"})
    assert len(script.calls) == 1 and res["plan_state"] is None


# ---------------------------------------------------------------------------
# move chip taps are deterministic; the plan call owns the slot; ambiguous targets arm a picker
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question, expected", [
    ("How do I get B.Fernandes with my current team? Plan: Use hits (−4 each)", {"target": "B.Fernandes", "moves": "hits"}),
    ("¿Cómo ficho a B.Fernandes con mi equipo actual? Plan: Usar hits (−4 cada uno)", {"target": "B.Fernandes", "moves": "hits"}),
    ("How do I get N.Jackson with my current team? Plan: 1 transfer", {"target": "N.Jackson", "moves": "one"}),
    ("¿Cómo ficho a N.Jackson con mi equipo actual? Plan: 1 traspaso", {"target": "N.Jackson", "moves": "one"}),
    ("How do I get N.Jackson with my current team? Plan: Only free transfers (2)", {"target": "N.Jackson", "moves": "free", "free_transfers": 2}),
    ("¿Cómo ficho a N.Jackson con mi equipo actual? Plan: Solo traspasos gratis (3)", {"target": "N.Jackson", "moves": "free", "free_transfers": 3}),
])
def test_move_chip_text_is_recognised(question, expected):
    assert move_tap(question) == expected


@pytest.mark.parametrize("question", [
    "how do i get nico jackson with my current team?",
    "how do i get nico jackson with my current team? use hits",
    "Plan: Use hits (−4 each)",
    "who else can i sell?",
    "",
    None,
])
def test_a_users_own_wording_is_not_a_move_tap(question):
    assert move_tap(question) is None


@pytest.mark.parametrize("locale", ["en", "es"])
def test_a_move_chip_tap_makes_no_model_call(chat, locale):
    post, script = chat
    chips = post(LINES[locale][0], locale)["suggestions"]
    asked = len(script.calls)
    for chip in chips:  # every move chip: "1 transfer" and "use hits"
        plan = post(chip["send_text"], locale)
        assert len(script.calls) == asked, "a move chip tap must not reach the model"
        assert plan["outcome"] == "ok"
        assert plan["generic_card"] is not None and plan["plan_state"]
    hits = post(chips[-1]["send_text"], locale)
    assert hits["plan_state"]["moves"] == "hits"


def test_a_move_tap_for_an_unknown_target_goes_the_normal_route(chat):
    post, script = chat
    before = len(script.calls)
    post("How do I get Nobodyatall with my current team? Plan: Use hits (−4 each)", "en")
    assert len(script.calls) == before + 1


def _orch_script(monkeypatch, calls, *, chosen=0):
    """A scripted run: executes ``calls`` (name, args) for real (plan_to_sign) or as a stub (get_my_squad)."""
    from fpl_tool_runner import run_tool

    def fake(question, bootstrap, *args, **kwargs):
        trace, outputs = [], []
        for number, (name, call) in enumerate(calls, start=1):
            out = run_tool(name, call, bootstrap) if name == "plan_to_sign" else {"status": "ok", "players": []}
            outputs.append(out)
            trace.append({"round": 1, "tool_call_id": f"c{number}", "name": name, "args": call, "output": out, "success": True})
        return OrchestratorResult(
            question=question, tool_chosen=calls[chosen][0], tool_args=calls[chosen][1], tool_output=outputs[chosen],
            answer_text="prose", llm_used=True, model="fake", outcome="ok", tool_call_count=len(calls),
            tool_calls_trace=tuple(trace),
        )

    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake)


HITS = {"target": "n.jackson", "moves": "hits"}


@pytest.mark.parametrize("sequence", [
    [("get_my_squad", {}), ("plan_to_sign", HITS)],
    [("plan_to_sign", HITS), ("get_my_squad", {})],
    [("get_my_squad", {}), ("plan_to_sign", HITS), ("get_my_squad", {})],
])
def test_the_plan_call_owns_the_slot_when_get_my_squad_opens_or_closes_the_turn(chat, monkeypatch, sequence):
    post, _script = chat
    _orch_script(monkeypatch, sequence)
    res = post("how do i get nico jackson with my current team? use hits", "en")
    assert res["generic_card"] is not None, "the plan card must not be lost"
    assert res["plan_state"] and res["plan_state"]["moves"] == "hits"
    assert [c["send_text"] for c in res["suggestions"]], "the other options come back as chips"


def test_a_retry_without_moves_does_not_replace_the_plan_the_user_chose(chat, monkeypatch):
    post, _script = chat
    # primary: plan with the chosen moves; the retry (the retained payload) asked again without moves
    from fpl_tool_runner import run_tool

    def fake(question, bootstrap, *args, **kwargs):
        plan = run_tool("plan_to_sign", HITS, bootstrap)
        choose = run_tool("plan_to_sign", {"target": "n.jackson"}, bootstrap)
        assert plan["stage"] == "plan" and choose["stage"] == "choose_moves"
        return OrchestratorResult(
            question=question, tool_chosen="plan_to_sign", tool_args={"target": "n.jackson"}, tool_output=choose,
            answer_text="prose", llm_used=True, model="fake", outcome="ok", tool_call_count=1,
            retry_attempted=True,
            tool_calls_trace=({"round": 1, "tool_call_id": "c1", "name": "plan_to_sign", "args": HITS, "output": plan, "success": True},),
        )

    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake)
    res = post("how do i get nico jackson with my current team? use hits", "en")
    assert res["generic_card"] is not None and res["plan_state"]["moves"] == "hits"


def test_a_plan_call_that_only_reached_the_move_step_keeps_the_move_chips(chat, monkeypatch):
    post, _script = chat
    _orch_script(monkeypatch, [("get_my_squad", {}), ("plan_to_sign", {"target": "n.jackson"})])
    res = post("how do i get nico jackson with my current team?", "en")
    assert res["plan_state"] is None and res["generic_card"] is None
    assert res["suggestions"] and all("Plan:" in c["send_text"] for c in res["suggestions"])


CANDIDATES = [
    {"id": 100, "web_name": "N.Jackson", "team_short": "T1", "name": "Nico Jackson"},
    {"id": 101, "web_name": "M.Jackson", "team_short": "T2", "name": "Mark Jackson"},
]


@pytest.mark.parametrize("locale", ["en", "es"])
def test_an_ambiguous_plan_target_arms_a_picker_with_candidates(locale):
    from fpl_grounded_assistant.harness import _ambiguity_suggestions

    raw = {"status": "ambiguous", "query": "jackson", "candidates": CANDIDATES}
    # the user's wording cannot be re-asked (the mention is not in it): the plain question per candidate
    chips = _ambiguity_suggestions("plan_to_sign", raw, "who can i sell to sign him?", None, locale)
    assert chips and [c["label"] for c in chips] == ["N.Jackson (T1)", "M.Jackson (T2)"]
    assert all(c["kind"] == "prompt_rewrite" for c in chips)
    assert "N.Jackson T1" in chips[0]["send_text"] and len({c["send_text"] for c in chips}) == 2


def test_an_ambiguous_plan_target_re_asks_the_users_own_question():
    from fpl_grounded_assistant.harness import _ambiguity_suggestions

    raw = {"status": "ambiguous", "query": "jackson", "candidates": CANDIDATES}
    chips = _ambiguity_suggestions("plan_to_sign", raw, "who else can i sell to sign jackson?", None, "en")
    assert [c["send_text"] for c in chips] == [
        "who else can i sell to sign Nico Jackson?", "who else can i sell to sign Mark Jackson?",
    ]
