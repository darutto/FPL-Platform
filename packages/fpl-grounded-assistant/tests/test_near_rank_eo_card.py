"""The "EO near your rank" card: the same two groups against the user's squad as the league card (synthetic data, no network, no LLM)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fpl_grounded_assistant import harness
from fpl_grounded_assistant import league_eo_tool
from fpl_grounded_assistant import near_rank_eo_tool as tool
from fpl_grounded_assistant.atomic_tool_cards import compose_near_rank_eo_card, maybe_atomic_tool_card
from fpl_grounded_assistant.orch_config import NEAR_RANK_EO_ENABLED_ENV
from fpl_grounded_assistant.orchestrator import OrchestratorResult

TEAMS = [{"id": t, "short_name": f"T{t}"} for t in range(1, 5)]
ELEMENTS = [{"id": i, "web_name": f"P{i}", "second_name": f"Surname{i}", "team": (i % 4) + 1} for i in range(1, 21)]
BOOT = {"teams": TEAMS, "elements": ELEMENTS}


def stats(owned, eo, cap=0.0):
    return {"owned_pct": owned, "captain_pct": cap, "bench_pct": 0.0, "eo": eo}


PLAYERS = {
    "1": stats(90.0, 95.0), "2": stats(80.0, 140.0, 50.0), "3": stats(55.0, 55.0), "4": stats(30.0, 30.0),
    "7": stats(10.0, 10.0), "8": stats(8.0, 8.0),
}
DATA = {"gw": 11, "user_rank": 495125, "n_sampled": 125, "players": PLAYERS}


def squad(ids):
    return {"status": "ok", "players": [{"id": i} for i in ids]}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(NEAR_RANK_EO_ENABLED_ENV, raising=False)
    tool.set_service(None)
    yield
    tool.set_service(None)


def shaped(squad_ids=(1, 7, 11), **over):
    out = tool.shape_result(DATA, BOOT, [], squad(squad_ids))
    out.update(over)
    return out


# -- one comparison, shared with the league tool -----------------------------------------------------------

def test_the_comparison_is_the_one_the_league_tool_uses():
    assert league_eo_tool.squad_comparison is tool.squad_comparison
    assert league_eo_tool.GROUP_SIZE == tool.GROUP_SIZE == 5
    assert (tool.RISK_MIN_OWNED_PCT, tool.DIFFERENTIAL_MAX_OWNED_PCT) == (50.0, 20.0)


def test_the_near_result_carries_group_has_and_differentials_against_the_squad():
    out = shaped()
    assert out["squad_compared"] is True and out["tier"] == "near" and out["label"] == "approx., n=125"
    assert [r["player"] for r in out["group_has"]] == ["P2", "P3"]       # owned by >= 50 % of those near, not by the user
    assert [r["player"] for r in out["differentials"]] == ["P11", "P7"]  # the user's own, rare among them


def test_without_a_squad_there_is_no_comparison_and_the_answer_still_comes():
    out = tool.shape_result(DATA, BOOT, [], None)
    assert out["squad_compared"] is False and out["top_players"]


def test_the_tool_loads_the_squad_once_the_job_is_ready_and_survives_a_failing_fetch(monkeypatch):
    class Svc:
        def status(self, *a, **k):
            return {"status": "ready", "data": DATA}

    monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    tool.set_service(Svc())
    boot = {**BOOT, "_my_team_id": 555, "events": [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"},
                                                   {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"}]}
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    seen = []
    monkeypatch.setattr(tool, "load_linked_squad", lambda b, gw: seen.append(gw) or squad([1, 7]))
    assert tool.get_near_rank_eo(boot, now=now)["squad_compared"] is True and seen == [11]

    def boom(b, gw):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(tool, "load_linked_squad", boom)
    out = tool.get_near_rank_eo(boot, now=now)
    assert out["status"] == "ok" and out["squad_compared"] is False


# -- the card -----------------------------------------------------------------------------------------------------

def test_english_card_title_label_groups_and_dot_decimals():
    card = compose_near_rank_eo_card(shaped(), "en")
    assert card.title == "EO near your rank" and card.subtitle == "approx., n=125"
    assert [c.header for c in card.columns] == ["", "Player", "EO %", "Capt. %"]
    assert card.rows[0] == ("Near you has him", "P2 (T3)", "140.0", "50.0")
    assert card.rows[1] == ("Near you has him", "P3 (T4)", "55.0", "")
    assert [r[0] for r in card.rows[2:]] == ["Your differential"] * 2
    assert card.footer == "EO counts captains double."
    assert all(len(r) == len(card.columns) for r in card.rows)


def test_spanish_card_has_its_own_words_and_the_same_dots():
    card = compose_near_rank_eo_card(shaped(), "es")
    assert card.title == "EO cerca de tu puesto" and card.subtitle == "aprox., n=125"
    assert card.rows[0][0] == "Cerca de ti lo tienen" and card.rows[2][0] == "Tu diferencial"
    assert card.rows[0][2] == "140.0"


def test_without_the_squad_the_card_shows_the_top_eo():
    card = compose_near_rank_eo_card(tool.shape_result(DATA, BOOT, [], None), "en")
    assert [r[0] for r in card.rows] == ["Top EO"] * 5 and card.rows[0][1] == "P2 (T3)"


@pytest.mark.parametrize("raw", [
    {"status": "computing", "eta_s": 30},
    {"status": "unavailable", "reason": "no_rank"},
    {"status": "ok", "tier": "league"},
    {"status": "ok", "tier": "near", "top_players": [], "squad_compared": False},
])
def test_no_card_unless_there_is_something_to_show(raw):
    assert compose_near_rank_eo_card(raw, "en") is None


def test_the_card_is_registered_and_never_overrides_another_card():
    assert maybe_atomic_tool_card("get_near_rank_eo", shaped(), None, "es") is not None
    assert maybe_atomic_tool_card("get_near_rank_eo", shaped(), object(), "es") is None


def test_the_league_card_is_unchanged_by_the_shared_builder():
    from fpl_grounded_assistant.atomic_tool_cards import compose_league_eo_card

    data = {"gw": 11, "league_id": 42, "league_name": "Friends", "league_size": 12, "exact": True, "approx": False,
            "n_sampled": 12, "label": "exact, n=12", "players": PLAYERS}
    card = compose_league_eo_card(league_eo_tool.shape_result(data, BOOT, [], squad([1, 7, 11])), "en")
    assert card.title == "EO in Friends" and card.subtitle == "exact, n=12" and card.rows[0][0] == "League has him"
    assert [c.header for c in card.columns][2] == "League EO %"


# -- the computing state, in plain words ---------------------------------------------------------------------------

def test_computing_tells_the_model_to_say_so_plainly_and_not_to_guess(monkeypatch):
    class Svc:
        def status(self, *a, **k):
            return {"status": "computing", "eta_s": 30}

    monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    tool.set_service(Svc())
    boot = {**BOOT, "_my_team_id": 555, "events": [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"},
                                                   {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"}]}
    out = tool.get_near_rank_eo(boot, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
    assert out["status"] == "computing" and out["eta_s"] == 30
    assert "not ready yet" in out["message"] and "ask again" in out["message"] and "do not guess" in out["message"]


# -- through the harness -------------------------------------------------------------------------------------------

def _orch(raw):
    trace = ({"round": 1, "tool_call_id": "1", "name": "get_near_rank_eo", "args": {}, "output": raw, "success": True},)
    return OrchestratorResult(question="q", tool_chosen="get_near_rank_eo", tool_args={}, tool_output=raw,
                              answer_text="texto", llm_used=True, model="controlled", outcome="ok",
                              synthesis_turn=True, tool_call_count=1, tool_calls_trace=trace)


def test_a_ready_turn_carries_the_card_and_no_chips(monkeypatch, bootstrap):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: _orch(shaped()))
    d = harness.ask_v2("EO cerca de mi puesto", bootstrap, orch_client=object(), team_id=555, locale="es")
    assert d["generic_card"] is not None and d["generic_card"].title == "EO cerca de tu puesto"
    assert not d.get("player_suggestions")
