"""The mini-league EO card and the league chips: the league against the user's own squad (synthetic data, no network, no LLM)."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant import harness
from fpl_grounded_assistant import league_eo_tool as tool
from fpl_grounded_assistant.atomic_tool_cards import compose_league_eo_card, maybe_atomic_tool_card
from fpl_grounded_assistant.generic_card import GenericCardMeta
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.orch_config import LEAGUE_EO_ENABLED_ENV
from fpl_grounded_assistant.suggestions import KIND_LEAGUE_PICK, Suggestion, suggestions_to_list

TEAMS = [{"id": t, "short_name": f"T{t}"} for t in range(1, 5)]
ELEMENTS = [{"id": i, "web_name": f"P{i}", "second_name": f"Surname{i}", "team": (i % 4) + 1} for i in range(1, 21)]
BOOT = {"teams": TEAMS, "elements": ELEMENTS}


def stats(owned, eo, cap=0.0):
    return {"owned_pct": owned, "captain_pct": cap, "bench_pct": 0.0, "eo": eo}


# league: 1 and 2 are owned by most (and 2 is captained), 3 by 55 %, 4..6 by 30 %, 7..9 by 10 %, 10 by 0 %
PLAYERS = {
    "1": stats(90.0, 95.0), "2": stats(80.0, 140.0, 50.0), "3": stats(55.0, 55.0), "4": stats(30.0, 30.0),
    "5": stats(30.0, 30.0), "6": stats(30.0, 30.0), "7": stats(10.0, 10.0), "8": stats(8.0, 8.0),
    "9": stats(8.0, 8.0),
}
DATA = {"gw": 11, "league_id": 42, "league_name": "Friends", "league_size": 12, "exact": True, "approx": False,
        "n_sampled": 12, "label": "exact, n=12", "players": PLAYERS}


def squad(ids):
    return {"status": "ok", "players": [{"id": i} for i in ids]}


# -- the comparison ------------------------------------------------------------------------------------

def by_teams():
    return tool._name_index(BOOT)


def test_risks_are_the_leagues_high_owned_players_the_user_lacks_highest_eo_first():
    by_id, teams = by_teams()
    out = tool.squad_comparison(PLAYERS, squad([1, 4, 7, 11]), by_id, teams)
    assert out["squad_compared"] is True
    assert [r["player"] for r in out["risks"]] == ["P2", "P3"]  # 1 is owned by the user; 4.. are under 50 %
    assert out["risks"][0] == {"player": "P2", "team": "T3", "eo": 140.0, "owned_pct": 80.0, "captain_pct": 50.0}


def test_differentials_are_the_users_own_players_the_league_mostly_lacks_rarest_first():
    by_id, teams = by_teams()
    out = tool.squad_comparison(PLAYERS, squad([1, 4, 7, 8, 11]), by_id, teams)
    # 1 (90 %) and 4 (30 %) are not differentials; 7 (10 %), 8 (8 %) are; 11 is absent from the league (0 %)
    assert [r["player"] for r in out["differentials"]] == ["P11", "P8", "P7"]
    assert out["differentials"][0]["eo"] == 0.0 and out["differentials"][0]["owned_pct"] == 0.0


def test_each_group_is_capped_at_five():
    many = {str(i): stats(90.0, 100.0 + i) for i in range(1, 15)}
    by_id, teams = by_teams()
    risks = tool.squad_comparison(many, squad([15, 16]), by_id, teams)["risks"]
    assert len(risks) == tool.GROUP_SIZE and risks[0]["player"] == "P14"
    diffs = tool.squad_comparison({}, squad(range(1, 16)), by_id, teams)["differentials"]
    assert len(diffs) == tool.GROUP_SIZE


@pytest.mark.parametrize("sq", [None, {}, {"players": []}])
def test_without_a_squad_there_is_no_comparison(sq):
    by_id, teams = by_teams()
    assert tool.squad_comparison(PLAYERS, sq, by_id, teams) == {"squad_compared": False}


def test_the_tool_loads_the_users_squad_when_the_league_is_ready(monkeypatch):
    class Svc:
        def status(self, *a, **k):
            return {"status": "ready", "data": DATA}

    monkeypatch.setenv(LEAGUE_EO_ENABLED_ENV, "1")
    tool.set_service(Svc())
    seen = []
    monkeypatch.setattr(tool, "load_linked_squad", lambda b, gw: seen.append(gw) or squad([1, 7]))
    boot = {**BOOT, "_my_team_id": 555, "_my_league_id": 42,
            "events": [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"}, {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"}]}
    from datetime import datetime, timezone
    out = tool.get_league_eo(boot, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
    tool.set_service(None)
    assert seen == [11] and out["squad_compared"] is True
    assert [r["player"] for r in out["risks"]] == ["P2", "P3"] and [r["player"] for r in out["differentials"]] == ["P7"]


def test_a_failing_squad_fetch_still_answers_without_the_comparison(monkeypatch):
    class Svc:
        def status(self, *a, **k):
            return {"status": "ready", "data": DATA}

    monkeypatch.setenv(LEAGUE_EO_ENABLED_ENV, "1")
    tool.set_service(Svc())

    def boom(b, gw):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(tool, "load_linked_squad", boom)
    from datetime import datetime, timezone
    boot = {**BOOT, "_my_team_id": 555, "_my_league_id": 42,
            "events": [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"}, {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"}]}
    out = tool.get_league_eo(boot, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
    tool.set_service(None)
    assert out["status"] == "ok" and out["squad_compared"] is False and out["top_players"]


# -- the card ----------------------------------------------------------------------------------------------

def shaped(squad_ids=(1, 7, 11), **over):
    out = tool.shape_result(DATA, BOOT, [], squad(squad_ids))
    out.update(over)
    return out


def test_english_card_title_label_groups_and_dot_decimals():
    card = compose_league_eo_card(shaped(), "en")
    assert isinstance(card, GenericCardMeta)
    assert card.title == "EO in Friends" and card.subtitle == "exact, n=12"
    assert [c.header for c in card.columns] == ["", "Player", "League EO %", "Capt. %"]
    assert card.rows[0] == ("League has him", "P2 (T3)", "140.0", "50.0")
    assert card.rows[1] == ("League has him", "P3 (T4)", "55.0", "")
    assert [r[0] for r in card.rows[2:]] == ["Your differential"] * 2 and card.rows[2][1] == "P11 (T4)"
    assert card.rows[2][2:] == ("0.0", "")  # no captain % on a differential
    assert card.footer == "EO counts captains double."
    assert all(len(r) == len(card.columns) for r in card.rows)


def test_spanish_card_has_its_own_words_and_the_same_dots():
    card = compose_league_eo_card(shaped(), "es")
    assert card.title == "EO en Friends" and card.subtitle == "exacto, n=12"
    assert card.rows[0][0] == "La liga lo tiene" and card.rows[2][0] == "Tu diferencial"
    assert card.rows[0][2] == "140.0"  # dot decimals in Spanish too
    assert [c.header for c in card.columns][1:] == ["Jugador", "EO liga %", "Cap. %"]


def test_sampled_league_label_says_approx_with_the_size():
    en = compose_league_eo_card(shaped(exact=False, approx=True, n_sampled=100, league_size=840), "en")
    es = compose_league_eo_card(shaped(exact=False, approx=True, n_sampled=100, league_size=840), "es")
    assert en.subtitle == "approx., n=100 of 840" and es.subtitle == "aprox., n=100 de 840"


def test_without_the_squad_the_card_shows_the_top_eo():
    out = tool.shape_result(DATA, BOOT, [], None)
    card = compose_league_eo_card(out, "en")
    assert [r[0] for r in card.rows] == ["Top EO"] * 5 and card.rows[0][1] == "P2 (T3)"


@pytest.mark.parametrize("raw", [
    {"status": "ok", "stage": "needs_league", "tier": "league"},     # a question, not a table
    {"status": "computing", "eta_s": 30},
    {"status": "unavailable", "reason": "league_too_large"},
    {"status": "ok", "tier": "near"},
    {"status": "ok", "tier": "league", "top_players": [], "squad_compared": False},  # nothing to show
])
def test_no_card_unless_there_is_something_to_show(raw):
    assert compose_league_eo_card(raw, "en") is None


def test_the_card_is_registered_for_the_tool_and_never_overrides_another_card():
    assert maybe_atomic_tool_card("get_league_eo", shaped(), None, "en") is not None
    assert maybe_atomic_tool_card("get_league_eo", shaped(), object(), "en") is None


# -- the chips -------------------------------------------------------------------------------------------------

PICKER = {"status": "ok", "stage": "needs_league",
          "leagues": [{"league_id": 42, "name": "Friends", "size": 12}, {"league_id": 77, "name": "Work Mates", "size": 48}]}


def test_the_picker_becomes_one_chip_per_league_with_its_id_in_each_language():
    en = harness._league_pick_chips("get_league_eo", PICKER, "en")
    es = harness._league_pick_chips("get_league_eo", PICKER, "es")
    assert en == [
        {"label": "Friends", "send_text": "EO in Friends", "kind": "league_pick", "league_id": 42},
        {"label": "Work Mates", "send_text": "EO in Work Mates", "kind": "league_pick", "league_id": 77},
    ]
    assert es[0]["send_text"] == "EO en Friends" and es[1]["league_id"] == 77


@pytest.mark.parametrize("tool_name,raw", [
    ("get_league_eo", {"status": "ok", "tier": "league"}),
    ("get_league_eo", {"status": "ok", "stage": "needs_league", "leagues": []}),
    ("get_near_rank_eo", PICKER),
    (None, PICKER),
])
def test_no_chips_for_anything_else(tool_name, raw):
    assert harness._league_pick_chips(tool_name, raw, "en") is None


def test_suggestion_wire_shape_keeps_league_id_only_when_set():
    out = suggestions_to_list((Suggestion(label="a", send_text="b", kind=KIND_LEAGUE_PICK, league_id=5),
                               Suggestion(label="c", send_text="d")))
    assert out == [{"label": "a", "send_text": "b", "kind": "league_pick", "league_id": 5},
                   {"label": "c", "send_text": "d"}]


# -- through the harness -------------------------------------------------------------------------------------------

def _orch(raw):
    trace = ({"round": 1, "tool_call_id": "1", "name": "get_league_eo", "args": {}, "output": raw, "success": True},)
    return OrchestratorResult(question="q", tool_chosen="get_league_eo", tool_args={}, tool_output=raw,
                              answer_text="texto", llm_used=True, model="controlled", outcome="ok",
                              synthesis_turn=True, tool_call_count=1, tool_calls_trace=trace)


@pytest.fixture
def orch_on(monkeypatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)


def test_a_ready_turn_carries_the_card(monkeypatch, orch_on, bootstrap):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: _orch(shaped()))
    d = harness.ask_v2("EO en mi liga", bootstrap, orch_client=object(), team_id=555, league_id=42, locale="es")
    card = d["generic_card"]
    assert card is not None and card.title == "EO en Friends" and card.rows[0][0] == "La liga lo tiene"
    assert not d.get("player_suggestions")


def test_a_picker_turn_carries_the_chips_and_no_card(monkeypatch, orch_on, bootstrap):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: _orch(PICKER))
    d = harness.ask_v2("EO en mi liga", bootstrap, orch_client=object(), team_id=555, locale="es")
    assert d["generic_card"] is None
    assert [(c["label"], c["league_id"], c["kind"]) for c in d["player_suggestions"]] == [
        ("Friends", 42, "league_pick"), ("Work Mates", 77, "league_pick")]
    assert d["player_suggestions"][0]["send_text"] == "EO en Friends"
