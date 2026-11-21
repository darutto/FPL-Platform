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
            outcome="ok",
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
    assert [c["kind"] for c in chips] == ["prompt_rewrite", "prompt_rewrite"]  # free count unknown: 1 transfer, hits

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
