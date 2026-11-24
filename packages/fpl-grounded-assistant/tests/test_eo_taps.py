"""EO chip taps without a model, the one line under a deterministic EO card, and the «Change league» chip.

Synthetic data only. The provider boundary raises if touched (no model on a tap)."""
from __future__ import annotations

import pytest

import fpl_server  # noqa: F401  (puts the package paths on sys.path like the other EO tests)
from fpl_grounded_assistant import eo_poll, eo_taps, harness
from fpl_grounded_assistant import league_eo_tool as league_tool
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.eo_line import eo_one_line
from fpl_grounded_assistant.harness import _eo_switch_chips

import test_league_eo_tool as lt
from test_eo_poll import CARD_OK


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    import fpl_grounded_assistant.orchestrator as orch

    def boom(*a, **k):
        raise AssertionError("a chip tap must not reach the model")

    for name in ("run_orchestrator", "ask_orchestrated"):
        if hasattr(orch, name):
            monkeypatch.setattr(orch, name, boom)
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)


def _ask(question, monkeypatch, tool_results, *, team_id=555, locale="es"):
    """ask_v2 with the EO tools replaced by canned results; returns (result, calls)."""
    calls = []

    def fake_run_tool(name, args, bootstrap):
        calls.append((name, dict(args)))
        return tool_results[name]

    monkeypatch.setattr("fpl_grounded_assistant.tool_dispatch.run_tool", fake_run_tool)
    out = harness.ask_v2(question, dict(STANDARD_BOOTSTRAP), team_id=team_id, locale=locale)
    return out, calls


# -- matching: exact chip text only, both languages ------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("EO cerca de tu puesto", {"kind": "near"}),
    ("EO near your rank", {"kind": "near"}),
    ("eo near YOUR rank", {"kind": "near"}),
    ("EO top 10K", {"kind": "tier"}),
    ("Cambiar de liga", {"kind": "change"}),
    ("Change league", {"kind": "change"}),
    ("EO en Work Mates", {"kind": "league", "league_name": "Work Mates"}),
    ("EO in Work Mates", {"kind": "league", "league_name": "Work Mates"}),
    ("  EO en   Bendito Fantasy VIP ", {"kind": "league", "league_name": "Bendito Fantasy VIP"}),
])
def test_exact_chip_text_matches(text, expected):
    assert eo_taps.eo_tap(text) == expected


@pytest.mark.parametrize("text", [
    "", "EO cerca de mi puesto", "dame el EO top 10K", "EO top 10K por favor", "EO", "que EO hay en mi liga",
    "cambia de liga", "EO en", "a" * 300,
])
def test_a_users_own_phrasing_does_not_match(text):
    assert eo_taps.eo_tap(text) is None


# -- the tap through ask_v2: no model ----------------------------------------------------------------------------

def test_near_tap_returns_the_card_the_line_and_the_chips(monkeypatch):
    raw = {**CARD_OK, "main_league": {"id": 42, "name": "Friends"}}
    d, calls = _ask("EO cerca de tu puesto", monkeypatch, {"get_near_rank_eo": raw})
    assert calls == [("get_near_rank_eo", {})]
    assert d["routing_trace"]["decision_kind"] == "eo_tap" and d["outcome"] == "ok"
    assert d["generic_card"] is not None and d["answer_text"]
    assert [c["send_text"] for c in d["player_suggestions"]] == ["EO en Friends"]
    assert "pending" not in d


@pytest.mark.parametrize("tool,tap,raw,marker", [
    ("get_near_rank_eo", "EO cerca de tu puesto", {"status": "computing", "tier": "near", "eta_s": 30},
     {"tool": "get_near_rank_eo", "eta_s": 30, "poll_s": 4, "max_s": 60}),
    ("get_league_eo", "EO en Friends", {"status": "computing", "tier": "league", "eta_s": 30, "league_id": 42},
     {"tool": "get_league_eo", "league_id": 42, "eta_s": 30, "poll_s": 4, "max_s": 60}),
])
def test_a_computing_tap_carries_pending_and_the_calculating_line(monkeypatch, tool, tap, raw, marker):
    d, _ = _ask(tap, monkeypatch, {tool: raw})
    assert d["pending"] == marker and d["outcome"] == "ok"
    assert d["generic_card"] is None and d["answer_text"]


def test_league_tap_passes_the_name_and_an_unresolvable_one_falls_through(monkeypatch):
    d, calls = _ask("EO en Work Mates", monkeypatch, {"get_league_eo": {**CARD_OK, "tier": "league", "league_name": "Work Mates"}})
    assert calls == [("get_league_eo", {"league_name": "Work Mates"})]
    d, _ = _ask("EO en mi liga", monkeypatch, {"get_league_eo": {"status": "unavailable", "reason": "league_not_found"}})
    assert d["routing_trace"]["decision_kind"] != "eo_tap"  # the normal route answers


@pytest.mark.parametrize("raw", [
    {"status": "disabled", "code": "x"}, {"status": "no_team_connected"}, {"status": "unavailable", "reason": "error"},
])
def test_a_non_answer_falls_through(monkeypatch, raw):
    d, _ = _ask("EO cerca de tu puesto", monkeypatch, {"get_near_rank_eo": raw})
    assert d["routing_trace"]["decision_kind"] != "eo_tap"


def test_an_own_phrasing_never_runs_the_tool_here(monkeypatch):
    d, calls = _ask("que EO hay cerca de mi puesto", monkeypatch, {})
    assert calls == [] and d["routing_trace"]["decision_kind"] != "eo_tap"


# -- «Change league» -----------------------------------------------------------------------------------------------

def test_the_change_chip_needs_other_readable_leagues():
    with_others = league_tool.shape_result(lt.DATA, lt.BOOT, [], None, [{"league_id": 77, "name": "Work Mates", "size": 48}])
    without = league_tool.shape_result(lt.DATA, lt.BOOT, [], None, [])

    def texts(raw, locale="en"):
        return [c["send_text"] for c in (_eo_switch_chips("get_league_eo", raw, locale) or [])]

    assert "Change league" in texts(with_others)
    assert "Change league" not in texts(without)
    assert texts(with_others, "es")[-1] == "Cambiar de liga"


def test_other_leagues_come_from_the_cached_list_only():
    class Svc:
        def cached_leagues(self, entry_id):
            return [lt.L1, lt.L2, {"id": 9, "name": "Tiny", "size": 1}]

    assert [lg["league_id"] for lg in league_tool.other_eligible_leagues(Svc(), 555, 42)] == [77]  # not current, not too small
    assert league_tool.other_eligible_leagues(lt.FakeService([lt.L1, lt.L2]), 555, 42) == []  # no cache: no request, no chip


def test_the_picker_leaves_out_the_current_league_and_needs_two(monkeypatch):
    monkeypatch.setenv("FPL_LEAGUE_EO_ENABLED", "1")
    league_tool.set_service(lt.FakeService([lt.L1, lt.L2]))
    boot = lt.boot(league=42)
    raw = league_tool.league_picker(boot, now=lt.NOW)
    assert raw["stage"] == "needs_league" and [lg["league_id"] for lg in raw["leagues"]] == [77]
    league_tool.set_service(lt.FakeService([lt.L1]))
    assert league_tool.league_picker(boot, now=lt.NOW) is None  # one league: nothing to change to
    monkeypatch.delenv("FPL_LEAGUE_EO_ENABLED")
    assert league_tool.league_picker(boot, now=lt.NOW) is None  # flag off
    league_tool.set_service(None)


def test_the_change_tap_returns_the_picker_chips_without_a_model(monkeypatch):
    picker = {"status": "ok", "stage": "needs_league", "leagues": [{"league_id": 77, "name": "Work Mates", "size": 48}]}
    monkeypatch.setattr("fpl_grounded_assistant.league_eo_tool.league_picker", lambda boot, now=None: picker)
    d, _ = _ask("Cambiar de liga", monkeypatch, {})
    assert d["routing_trace"]["decision_kind"] == "eo_tap"
    assert d["answer_text"] == "¿De qué liga quieres el EO?"
    assert [(c["kind"], c["league_id"], c["send_text"]) for c in d["player_suggestions"]] == [("league_pick", 77, "EO en Work Mates")]
    monkeypatch.setattr("fpl_grounded_assistant.league_eo_tool.league_picker", lambda boot, now=None: None)
    d, _ = _ask("Cambiar de liga", monkeypatch, {})
    assert d["routing_trace"]["decision_kind"] != "eo_tap"


# -- the one line ------------------------------------------------------------------------------------------------------

ROWS = {"squad_compared": True, "group_has": [{"player": "Evanilson"}, {"player": "Second"}], "differentials": [{"player": "Ndiaye"}]}


def test_the_line_names_the_first_row_of_each_group():
    assert eo_one_line(ROWS, "es") == "Cúbrete con Evanilson; tu diferencial: Ndiaye."
    assert eo_one_line(ROWS, "en") == "Cover Evanilson; your differential: Ndiaye."
    assert eo_one_line({**ROWS, "differentials": []}, "en") == "Cover Evanilson."
    assert eo_one_line({**ROWS, "group_has": []}, "es") == "Tu diferencial: Ndiaye."
    assert eo_one_line({**ROWS, "group_has": [], "differentials": []}, "es") is None
    assert eo_one_line({"squad_compared": False, "top_players": [{"player": "X"}]}, "es") is None


def test_an_out_row_is_skipped_in_both_groups_and_a_doubtful_one_when_a_fit_follows():
    rows = {**ROWS, "group_has": [{"player": "Hurt", "availability": "out"}, {"player": "Fit"}]}
    assert eo_one_line(rows, "en") == "Cover Fit; your differential: Ndiaye."
    only_out = {**ROWS, "group_has": [{"player": "Hurt", "availability": "out"}]}
    assert eo_one_line(only_out, "en") == "Your differential: Ndiaye."  # nobody qualifies: that part is left out
    maybe_first = {**ROWS, "group_has": [{"player": "Maybe", "availability": "doubtful"}, {"player": "Fit"}]}
    assert eo_one_line(maybe_first, "en").startswith("Cover Fit")
    only_doubtful = {**ROWS, "group_has": [{"player": "Maybe", "availability": "doubtful"}]}
    assert eo_one_line(only_doubtful, "en").startswith("Cover Maybe")  # no fit alternative: the doubt stays
    out_diff = {**ROWS, "differentials": [{"player": "Hurt", "availability": "out"}, {"player": "Next"}]}
    assert eo_one_line(out_diff, "en") == "Cover Evanilson; your differential: Next."
    assert eo_one_line({**ROWS, "differentials": [{"player": "Hurt", "availability": "out"}]}, "en") == "Cover Evanilson."


def test_the_poll_uses_the_line_and_keeps_the_generic_one_without_content(monkeypatch):
    monkeypatch.setattr("fpl_grounded_assistant.near_rank_eo_tool.get_near_rank_eo", lambda boot, **k: CARD_OK)
    r = eo_poll.poll("get_near_rank_eo", 5, None, dict(STANDARD_BOOTSTRAP), "es")
    expected = eo_one_line(CARD_OK, "es")
    assert r["status"] == "ready" and r["text"] == (expected or r["text"])
    assert (expected is None) == r["text"].startswith("Listo: ")
