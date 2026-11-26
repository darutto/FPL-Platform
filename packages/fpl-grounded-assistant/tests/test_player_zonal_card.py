"""
The card of a focused zonal question (get_player_zonal_outlook).

«dime las oportunidades zonales de X» must bring the same «Zonas» block the
player card draws, composed by the same code, over both HTTP routes, and the
model must read the same rows the card shows.

The tool runs for real on a synthetic store (invented numbers) written to a tmp
parquet with its pointer; only the orchestrator's model is stubbed. No network,
no provider. The serialized /ask bodies are also the UI tests' fixtures
(``UPDATE_PLAYER_ZONAL_FIXTURES=1 pytest tests/test_player_zonal_card.py``).
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest
from fastapi.testclient import TestClient

import test_player_snapshot_zonal as base  # synthetic store, bootstrap and calendar builders

import fpl_server
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant import player_snapshot_zonal as pz
from fpl_grounded_assistant import zonal_weakness as zw
from fpl_grounded_assistant.final_response import _extract_structured_meta
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY
from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult
from fpl_grounded_assistant.quota import reset_quota
from fpl_grounded_assistant.renderer import render
from fpl_tool_runner import run_tool

TOOL = "get_player_zonal_outlook"
INTENT = "player_zonal_outlook"
PALMER = 10
QUESTION = "dime las oportunidades en zona ofensiva de Palmer"
UI_FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fpl-ui" / "__tests__" / "fixtures" / "player-zonal"


def _events(last_finished: int) -> list[dict]:
    out = []
    for gw in range(1, 13):
        day = 14 + 7 * (gw - 1)
        month = 8 + (day - 1) // 31
        out.append({
            "id": gw, "deadline_time": f"2026-{month:02d}-{(day - 1) % 31 + 1:02d}T17:30:00Z",
            "finished": gw <= last_finished, "is_current": gw == last_finished,
            "is_next": gw == last_finished + 1,
        })
    return out


def _bootstrap(calendar=None, *, last_finished: int = 5, locale: str | None = None) -> dict:
    base._FID[0] = 100  # same fixture ids on every build: the UI fixtures are compared
    boot = base.make_bootstrap(calendar() if calendar else None)
    boot["events"] = _events(last_finished)
    # The engine's own schedule (the card's pending calendar is `_gw_fixtures`).
    boot["team_fixtures"] = {
        base.CHE: [{"gameweek": last_finished + 1, "opponent_team": base.ARS, "is_home": True, "difficulty": 3}],
        base.BOU: [{"gameweek": last_finished + 1, "opponent_team": base.ARS, "is_home": True, "difficulty": 3}],
    }
    if locale:
        boot[BOOTSTRAP_LOCALE_KEY] = locale
    return boot


@pytest.fixture(autouse=True)
def _store(monkeypatch, tmp_path):
    """One synthetic parquet read by the engine AND the card composer. Its newest
    shot is dated in GW5, so ``last_finished`` sets how old the data is."""
    rows = base.store_df()
    rows["date"] = "2026-09-11T20:00:00"
    path = tmp_path / "understat_shots.parquet"
    rows.to_parquet(path, index=False)
    (tmp_path / "_tactical_latest.json").write_text(json.dumps({
        "season": zw.CURRENT_SEASON, "n_matches": 380, "n_shots": len(rows),
        "ingested_at": "2026-09-12T06:00:00Z",
    }))
    monkeypatch.setattr(zw, "shots_parquet_path", lambda *a, **k: path)
    monkeypatch.setattr(zw, "latest_pointer_path", lambda *a, **k: path.parent / "_tactical_latest.json")
    pz.reset_caches()
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", path)
    monkeypatch.setattr(pz, "_FETCH_ALL_FIXTURES", lambda: pytest.fail("network"))
    yield
    pz.reset_caches()


def _run(player="Palmer", boot=None, **args) -> dict:
    return run_tool(TOOL, {"player": player, **args}, boot or _bootstrap())


def _card(raw: dict):
    return _extract_structured_meta(INTENT, raw, "ok")["player_zonal"]


# --- one shape -------------------------------------------------------------------


@pytest.mark.parametrize("locale", [None, "en"])
def test_the_card_block_is_the_snapshot_cards_block(locale):
    boot = _bootstrap(locale=locale)
    raw = _run(boot=boot)
    assert raw["status"] == "ok"
    snapshot = get_player_snapshot(PALMER, boot)
    assert raw["card"]["zonal"] == snapshot["player"]["zonal"]
    assert raw["card"]["signals"] == [s for s in snapshot.get("signals", []) if s["kind"] == "zone"]
    assert raw["card"]["signals"], "a favourable row carries the zone link"
    assert (raw["card"]["web_name"], raw["card"]["team_short"], raw["card"]["position"]) == ("Palmer", "CHE", "MID")
    meta = _card(raw)
    snap_meta = _extract_structured_meta("player_snapshot", snapshot, "ok")["player_snapshot"]
    assert meta.zonal == snap_meta.zonal


def test_the_horizon_sets_the_window_of_the_same_block():
    raw = _run(horizon=1)
    assert raw["card"]["zonal"]["window"] == {"gw_from": 6, "gw_to": 6}
    assert [f["gameweek"] for f in raw["outlook"]] == [6]
    five = _run(horizon=5)
    assert five["card"]["zonal"]["window"] == {"gw_from": 6, "gw_to": 10}
    assert [f["gameweek"] for f in five["outlook"]] == [6, 7, 8, 9]


# --- HTTP: both routes, and the model reads what the card shows -------------------


def _orch_result(raw: dict, args: dict) -> OrchestratorResult:
    trace = ({"round": 1, "tool_call_id": "c0", "name": TOOL, "args": args, "output": raw, "success": True},)
    return OrchestratorResult(
        question=QUESTION, tool_chosen=TOOL, tool_args=args, tool_output=raw,
        answer_text="Lectura del cruce.", llm_used=True, model="stub-model", outcome=OUTCOME_OK,
        primary_input_tokens=10, primary_output_tokens=5, total_tokens=15,
        tool_call_count=1, tool_calls_trace=trace, synthesis_turn=True,
    )


def _serve(monkeypatch, raw: dict, boot: dict) -> tuple[dict, dict]:
    result = _orch_result(raw, {"player": "Palmer"})
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    fpl_server._init_bootstrap(boot)
    fpl_server._sessions.clear()
    reset_quota()
    try:
        client = TestClient(fpl_server.app)
        ask = client.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-pz-ask"})
        sid = client.post("/session").json()["session_id"]
        sess = client.post(f"/session/{sid}/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-pz-sess"})
        assert (ask.status_code, sess.status_code) == (200, 200)
        return ask.json(), sess.json()
    finally:
        fpl_server._sessions.clear()
        reset_quota()


def _model_view(raw: dict) -> dict:
    """The tool payload as it is serialised to the model."""
    return json.loads(json.dumps(orch_mod._truncate_tool_output(raw, tool_name=TOOL)))


def _assert_model_reads_the_card(raw: dict, body: dict) -> None:
    seen, card = _model_view(raw), body["player_zonal"]["zonal"]
    assert "card" not in seen
    assert seen["outlook"] == card["fixtures"]
    assert seen["player_zones"] == card["zones"]
    assert seen["verdict"] == card["verdict"]
    assert seen["verdict_kind"] == card["verdict_kind"]
    stamp = seen["data_provenance"]
    assert {k: stamp[k] for k in card["data_provenance"]} == card["data_provenance"]


def _fixture(name: str, body: dict) -> None:
    """The /ask fields the UI renders, pinned as the jest tests' input."""
    wire = {k: body[k] for k in ("final_text", "outcome", "intent", "player_zonal")}
    path = UI_FIXTURES / f"{name}.json"
    if os.environ.get("UPDATE_PLAYER_ZONAL_FIXTURES"):
        UI_FIXTURES.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(wire, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert path.exists(), f"missing {path.name}: run UPDATE_PLAYER_ZONAL_FIXTURES=1"
    assert json.loads(path.read_text(encoding="utf-8")) == wire


def _no_favourable():
    return base.cal(base.fx(6, base.CHE, base.BOU), base.fx(7, base.EVE, base.CHE),
                    base.fx(8, base.CHE, base.IPS))


@pytest.mark.parametrize("name,calendar,last_finished,kind", [
    ("favourable", None, 5, "favorable"),
    ("no-favourable", _no_favourable, 5, "neutral"),
    ("profile-only", None, 9, "profile"),  # newest shot GW5, GW9 finished: 4 behind
])
def test_both_routes_serve_the_card_and_the_model_reads_the_same_facts(
    monkeypatch, name, calendar, last_finished, kind,
):
    boot = _bootstrap(calendar, last_finished=last_finished)
    raw = _run(boot=boot)
    ask, sess = _serve(monkeypatch, raw, boot)
    assert ask["intent"] == INTENT == sess["intent"]
    assert ask["player_zonal"] is not None
    assert ask["player_zonal"] == sess["player_zonal"]
    assert ask["player_zonal"]["zonal"]["verdict_kind"] == kind
    assert ask["player_zonal"]["zonal"]["zones"]
    _assert_model_reads_the_card(raw, ask)
    _fixture(name, ask)


def test_old_data_gives_the_model_nothing_present_tense_to_say(monkeypatch):
    boot = _bootstrap(last_finished=9)
    raw = _run(boot=boot)
    ask, _ = _serve(monkeypatch, raw, boot)
    seen = _model_view(raw)
    assert ask["player_zonal"]["zonal"]["fixtures"] == [] == seen["outlook"]
    assert seen["verdict"] == "" and seen["verdict_kind"] == "profile"
    assert seen["data_provenance"]["past_tense"] is True
    assert ask["player_zonal"]["signals"] == []
    dumped = json.dumps(seen)
    for rival in ("Bournemouth", "Everton", "Spurs", "BOU", "EVE", "TOT"):
        assert rival not in dumped


def test_the_card_rows_replace_the_engines_own_calendar():
    """The engine's schedule here lists ARS at home; the card (pending matches
    only) does not, and neither may the model or the text fallback."""
    raw = _run()
    assert [f["opponent_short"] for f in raw["outlook"]] == ["BOU", "EVE", "TOT"]
    assert "Arsenal" not in json.dumps(_model_view(raw))
    assert "Spurs" in render(TOOL, raw)


# --- edges: text, never an empty card --------------------------------------------


@pytest.mark.parametrize("player,boot_kw,status", [
    ("Nobody Atall", {}, "not_found"),
    ("Twin", {}, "ambiguous"),
    ("Nine Shots", {}, "not_found"),  # no shot profile stored (under the shot floor)
])
def test_no_profile_is_a_text_answer_without_a_card(player, boot_kw, status):
    raw = _run(player, boot=_bootstrap(**boot_kw))
    assert raw["status"] == status
    assert "card" not in raw and _card(raw) is None
    assert render(TOOL, raw)


@pytest.mark.parametrize("calendar", [
    lambda: base.cal(base.fx(6, base.CHE, base.BOU, "unknown")),
    lambda: base.cal(base.fx(5, base.CHE, base.BOU, "done")),
])
def test_an_unprovable_calendar_keeps_the_text_answer(calendar):
    raw = _run(boot=_bootstrap(calendar))
    assert raw["status"] == "ok" and "card" not in raw
    assert _card(raw) is None
    assert render(TOOL, raw)


def test_an_unprovable_identity_keeps_the_text_answer():
    raw = _run("Sam Transfer")  # store club is not the element's club
    assert raw["status"] == "ok" and "card" not in raw


def test_a_card_failure_does_not_cost_the_answer(monkeypatch):
    monkeypatch.setattr(pz, "element_for_store_player", lambda *a: 1 / 0)
    raw = _run()
    assert raw["status"] == "ok" and "card" not in raw and raw["outlook"]


def test_a_card_without_zones_is_not_served():
    raw = _run()
    raw["card"]["zonal"] = {**raw["card"]["zonal"], "zones": []}
    assert _card(raw) is None


# --- follow-up and prompt --------------------------------------------------------


def test_a_follow_up_keeps_the_player(monkeypatch):
    from fpl_grounded_assistant.conversation_state import ConversationState
    from types import SimpleNamespace

    state = ConversationState()
    state.update_from_response(SimpleNamespace(outcome="ok", intent=INTENT), "Palmer")
    assert state.last_player_query == "Palmer"


def test_the_prompt_says_what_the_card_already_shows():
    rule = orch_mod._SYSTEM_PROMPT.split("CARD_NO_RESTATE:", 1)[1].split("CHIP_NAMES", 1)[0]
    assert "get_player_zonal_outlook:" in rule
