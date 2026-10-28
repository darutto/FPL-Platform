"""
tests/test_r1_gw_report.py
==========================
R1: get_gw_report -- retrospective report of one closed gameweek.

Synthetic payloads in the shape of the real FPL API (picks / live / history).
No network, no LLM.

Suites:
    A. Registration + privacy (no team argument anywhere)
    B. Scoring: plain, double GW, autosub, Triple Captain, Bench Boost, vice armband
    C. Reconciliation (match, mismatch, no official figure)
    D. Honest degradation (open GW, no team, missing live, 404, network)
    E. Fetch path uses the picks OF THAT gameweek
    F. Stories, with and without history
    G. Renderer + card, ES/EN, no forecast language
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import requests

import fpl_grounded_assistant  # noqa: F401  (triggers tool self-registration)
from fpl_grounded_assistant import gw_report
from fpl_grounded_assistant.atomic_tool_cards import maybe_atomic_tool_card
from fpl_grounded_assistant.gw_report import build_gw_report, get_gw_report
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import TOOL_NAMES, get_offered_tool_schemas
from fpl_tool_runner import TOOL_REGISTRY

# id -> (web_name, team, element_type)
_SQUAD = {
    1: ("Raya", 1, 1), 2: ("Gabriel", 1, 2), 3: ("Gvardiol", 2, 2), 4: ("Saliba", 1, 2), 5: ("Dias", 2, 2),
    6: ("Saka", 1, 3), 7: ("Foden", 2, 3), 8: ("Odegaard", 1, 3), 9: ("Rodri", 2, 3),
    10: ("Haaland", 2, 4), 11: ("Havertz", 1, 4),
    12: ("Ortega", 2, 1), 13: ("Lewis", 2, 2), 14: ("Rice", 1, 3), 15: ("Trossard", 1, 4),
}


def _bootstrap(team_id: "int | None" = 68643, finished: tuple[int, ...] = (7, 8), data_checked: bool = True) -> dict[str, Any]:
    bs: dict[str, Any] = {
        "events": [
            {"id": g, "finished": g in finished, "data_checked": data_checked and g in finished, "is_current": g == max(finished, default=0) + 1}
            for g in range(1, 11)
        ],
        "teams": [{"id": 1, "short_name": "ARS", "name": "Arsenal"}, {"id": 2, "short_name": "MCI", "name": "Man City"}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"}, {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"}, {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {"id": i, "web_name": n, "team": tm, "element_type": et, "now_cost": 60, "status": "a", "form": "3.0", "total_points": 30}
            for i, (n, tm, et) in _SQUAD.items()
        ],
    }
    if team_id is not None:
        bs["_my_team_id"] = team_id
    return bs


def _picks(captain: int = 10, vice: int = 6, chip: "str | None" = None, subs: "list[tuple[int, int]]" = (),
           official: "int | None" = None, cost: int = 0, bench_pts: int = 0) -> dict[str, Any]:
    items = []
    for pos, eid in enumerate(range(1, 16), start=1):
        mult = 1 if (pos <= 11 or chip == "bboost") else 0
        if eid == captain:
            mult = 3 if chip == "3xc" else 2
        items.append({"element": eid, "position": pos, "multiplier": mult, "is_captain": eid == captain,
                      "is_vice_captain": eid == vice, "element_type": _SQUAD[eid][2]})
    return {
        "active_chip": chip,
        "automatic_subs": [{"entry": 68643, "element_in": i, "element_out": o, "event": 8} for i, o in subs],
        "entry_history": {"event": 8, "points": official, "event_transfers_cost": cost, "points_on_bench": bench_pts},
        "picks": items,
    }


def _live(points: "dict[int, int] | None" = None, minutes: "dict[int, int] | None" = None,
          fixtures: "dict[int, int] | None" = None) -> dict[str, Any]:
    points, minutes, fixtures = points or {}, minutes or {}, fixtures or {}
    elements = []
    for eid in _SQUAD:
        mins = minutes.get(eid, 90)
        n = fixtures.get(eid, 1 if mins > 0 or eid not in minutes else 0)
        elements.append({
            "id": eid,
            "stats": {"minutes": mins, "total_points": points.get(eid, 2 if mins else 0)},
            "explain": [{"fixture": 100 + k, "stats": []} for k in range(n)],
        })
    return {"elements": elements}


def _build(picks: dict[str, Any], live: dict[str, Any], history_points: "int | None" = None, **kw: Any) -> dict[str, Any]:
    hist = {"event": 8, "points": history_points} if history_points is not None else None
    return build_gw_report(team_id=68643, gw=8, picks=picks, history_row=hist, live=live, bootstrap=_bootstrap(), **kw)


def _row(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in report["players"] if p["web_name"] == name)


# ===========================================================================
# A. Registration + privacy
# ===========================================================================

class TestRegistrationAndPrivacy:
    def test_registered_everywhere(self):
        assert "get_gw_report" in TOOL_NAMES
        assert TOOL_REGISTRY.get("get_gw_report") is not None if hasattr(TOOL_REGISTRY, "get") else True
        assert any(s.name == "get_gw_report" for s in get_offered_tool_schemas(False))

    def test_schema_has_no_team_argument(self):
        spec = next(s for s in get_offered_tool_schemas(False) if s.name == "get_gw_report")
        assert set(spec.parameters["properties"]) == {"gameweek"}
        assert spec.parameters["additionalProperties"] is False

    def test_handler_ignores_a_team_id_in_args(self):
        seen: list[int] = []

        def fake_picks(team_id: int, gw: int) -> dict[str, Any]:
            seen.append(team_id)
            return _picks(official=30)

        with patch.object(gw_report, "get_entry_picks", fake_picks), \
                patch.object(gw_report, "get_event_live", lambda gw: _live()), \
                patch.object(gw_report, "get_entry_history", lambda t: {"current": []}), \
                patch.object(gw_report, "get_fixtures", lambda gw: []), \
                patch.object(gw_report, "get_element_summary", lambda e: {"history": []}):
            gw_report._handler({"gameweek": 8, "team_id": 999, "entry": 999}, _bootstrap(team_id=68643))
        assert seen == [68643]


# ===========================================================================
# B. Scoring
# ===========================================================================

class TestScoring:
    def test_plain_gameweek_reconciles(self):
        # 11 starters x 2 pts, captain Haaland 6 pts doubled: 10*2 + 12 = 32
        r = _build(_picks(official=32), _live({10: 6}), history_points=32)
        assert r["status"] == "ok" and r["retrospective"] is True
        assert r["reconciliation"]["computed_gross"] == 32
        assert r["reconciliation"]["reconciled"] is True
        assert _row(r, "Haaland")["multiplier"] == 2
        assert [p["role"] for p in r["players"]].count("bench") == 4

    def test_double_gameweek_uses_summed_points(self):
        # Haaland plays twice: live total (9) already sums both fixtures.
        r = _build(_picks(), _live({10: 9}, fixtures={10: 2}))
        assert _row(r, "Haaland")["fixtures"] == 2
        assert _row(r, "Haaland")["points"] == 9
        assert r["reconciliation"]["computed_gross"] == 10 * 2 + 18

    def test_autosub_brings_bench_in_and_uses_official_subs(self):
        # Havertz (11) does not play; first outfield bench (Lewis, 13) comes on.
        live = _live({13: 5}, minutes={11: 0})
        r = _build(_picks(subs=[(13, 11)], official=0), live)
        assert _row(r, "Lewis")["role"] == "autosub_in"
        assert _row(r, "Havertz")["role"] == "autosub_out"
        assert _row(r, "Havertz")["contribution"] == 0
        assert r["reconciliation"]["computed_gross"] == sum(p["contribution"] for p in r["players"])
        assert "autosub" in [s["kind"] for s in r["stories"]]
        sub = next(s for s in r["stories"] if s["kind"] == "autosub")["evidence"]
        assert sub["player_in"] == "Lewis" and sub["points_in"] == 5 and sub["player_out"] == "Havertz"

    def test_autosub_total_exact(self):
        r = _build(_picks(subs=[(13, 11)]), _live({13: 5}, minutes={11: 0}))
        # counted: ids 1-9 at 2 pts, Haaland (captain) 2 pts x2, Lewis 5; Havertz 0 and out
        assert r["reconciliation"]["computed_gross"] == 9 * 2 + 2 * 2 + 5

    def test_triple_captain(self):
        r = _build(_picks(chip="3xc"), _live({10: 7}))
        assert r["chip"] == "triple_captain"
        assert _row(r, "Haaland")["multiplier"] == 3
        assert _row(r, "Haaland")["contribution"] == 21
        cap = next(s for s in r["stories"] if s["kind"].startswith("captain"))
        assert cap["evidence"]["multiplier"] == 3

    def test_bench_boost_counts_all_fifteen_and_ignores_autosubs(self):
        live = _live({14: 8}, minutes={11: 0})
        r = _build(_picks(chip="bboost", subs=[(13, 11)]), live)
        assert r["chip"] == "bench_boost"
        assert all(p["role"] in ("starter", "bench_boost") for p in r["players"])
        assert r["auto_subs"] == []
        # 15 players: 14 x 2 minus Havertz 0, Rice 8, Haaland doubled
        assert r["reconciliation"]["computed_gross"] == sum(p["contribution"] for p in r["players"])
        assert _row(r, "Rice")["contribution"] == 8
        assert any(s["kind"] == "bench_boost" for s in r["stories"])
        assert not any(s["kind"] == "bench_points" for s in r["stories"])

    def test_vice_takes_armband_when_captain_does_not_play(self):
        live = _live({6: 7}, minutes={10: 0})
        r = _build(_picks(captain=10, vice=6, subs=[(15, 10)]), live)
        assert r["armband_moved"] is True
        assert r["effective_captain"]["web_name"] == "Saka"
        assert _row(r, "Saka")["multiplier"] == 2 and _row(r, "Saka")["contribution"] == 14
        assert _row(r, "Haaland")["contribution"] == 0

    def test_wildcard_and_free_hit_do_not_change_scoring(self):
        base = _build(_picks(), _live())["reconciliation"]["computed_gross"]
        for chip in ("wildcard", "freehit"):
            assert _build(_picks(chip=chip), _live())["reconciliation"]["computed_gross"] == base

    def test_transfer_hit_net(self):
        r = _build(_picks(official=22, cost=4), _live())
        assert r["reconciliation"]["transfer_cost"] == 4
        assert r["reconciliation"]["net"] == r["reconciliation"]["computed_gross"] - 4


# ===========================================================================
# C. Reconciliation
# ===========================================================================

class TestReconciliation:
    def test_mismatch_is_reported_not_hidden(self):
        r = _build(_picks(official=99), _live(), history_points=99)
        rec = r["reconciliation"]
        assert rec["reconciled"] is False
        assert rec["official_gross"] == 99 and rec["difference"] == rec["computed_gross"] - 99
        text = render("get_gw_report", r, locale="es")
        assert "99" in text and "no reconciliadas" in text

    def test_picks_and_history_disagreeing_is_not_reconciled(self):
        gross = _build(_picks(official=0), _live())["reconciliation"]["computed_gross"]
        r = _build(_picks(official=gross), _live(), history_points=gross + 1)
        assert r["reconciliation"]["reconciled"] is False

    def test_no_official_figure_is_unverified(self):
        r = _build(_picks(official=None), _live(), history_points=None)
        assert r["reconciliation"]["reconciled"] is False
        assert r["reconciliation"]["official_gross"] is None
        assert "unverified" in render("get_gw_report", r, locale="en")


# ===========================================================================
# D. Honest degradation
# ===========================================================================

class TestDegradation:
    def test_open_gameweek_is_missing_context(self):
        out = get_gw_report(_bootstrap(finished=(7, 8)), gameweek=9)
        assert out["status"] == "missing_context" and out["reason_codes"] == ["gw_not_finished"]
        assert "players" not in out

    def test_no_team(self):
        assert get_gw_report(_bootstrap(team_id=None))["status"] == "no_team_connected"

    def test_no_finished_gameweek(self):
        out = get_gw_report(_bootstrap(finished=()))
        assert out["reason_codes"] == ["no_finished_gameweek"]

    def test_invalid_gw(self):
        assert get_gw_report(_bootstrap(), gameweek=0)["code"] == "invalid_gw"

    def test_missing_live_row_is_missing_context(self):
        live = _live()
        live["elements"] = [e for e in live["elements"] if e["id"] != 3]
        r = _build(_picks(), live)
        assert r["status"] == "missing_context" and r["reason_codes"] == ["live_data_missing"]

    def test_incomplete_picks_is_missing_context(self):
        p = _picks()
        p["picks"] = p["picks"][:14]
        assert _build(p, _live())["reason_codes"] == ["picks_incomplete"]

    def test_unknown_team_404(self):
        resp = requests.Response()
        resp.status_code = 404
        err = requests.HTTPError(response=resp)
        with patch.object(gw_report, "get_entry_picks", side_effect=err), \
                patch.object(gw_report, "get_event_live", lambda gw: _live()):
            assert get_gw_report(_bootstrap(), gameweek=8)["status"] == "not_found"

    def test_network_error(self):
        with patch.object(gw_report, "get_entry_picks", side_effect=requests.ConnectionError("x")), \
                patch.object(gw_report, "get_event_live", lambda gw: _live()):
            out = get_gw_report(_bootstrap(), gameweek=8)
        assert out["status"] == "error" and out["code"] == "network_error"

    def test_provisional_data_flagged(self):
        r = build_gw_report(team_id=1, gw=8, picks=_picks(official=0), history_row=None, live=_live(),
                            bootstrap=_bootstrap(), data_checked=False)
        assert r["data_checked"] is False
        assert "provisional" in render("get_gw_report", r, locale="en").lower() or "verificar" in render("get_gw_report", r, locale="es")


# ===========================================================================
# E. Fetch path
# ===========================================================================

class TestFetchPath:
    def test_uses_picks_of_the_requested_gameweek_and_defaults_to_last_finished(self):
        calls: list[tuple[int, int]] = []

        def fake_picks(team_id: int, gw: int) -> dict[str, Any]:
            calls.append((team_id, gw))
            return _picks(official=32)

        live_calls: list[int] = []
        with patch.object(gw_report, "get_entry_picks", fake_picks), \
                patch.object(gw_report, "get_event_live", lambda gw: live_calls.append(gw) or _live({10: 6})), \
                patch.object(gw_report, "get_entry_history", lambda t: {"current": [{"event": 8, "points": 32}, {"event": 7, "points": 1}]}), \
                patch.object(gw_report, "get_fixtures", lambda gw: [{"team_h": 1, "team_a": 2}]), \
                patch.object(gw_report, "get_element_summary", lambda e: {"history": []}):
            r7 = get_gw_report(_bootstrap(), gameweek=7)
            rdef = get_gw_report(_bootstrap())
        assert calls == [(68643, 7), (68643, 8)]
        assert live_calls == [7, 8]
        assert rdef["gw"] == 8 and rdef["reconciliation"]["reconciled"] is True
        assert r7["gw"] == 7 and r7["reconciliation"]["official_history"] == 1


# ===========================================================================
# F. Stories
# ===========================================================================

def _hist(rows: "list[tuple[int, int, int]]") -> list[dict[str, Any]]:
    return [{"round": r, "minutes": m, "total_points": p, "fixture": r} for r, m, p in rows]


class TestStories:
    def test_captain_is_top(self):
        r = _build(_picks(), _live({10: 12}))
        s = next(s for s in r["stories"] if s["kind"] == "captain_top")
        assert s["evidence"]["captain"] == "Haaland" and s["evidence"]["contribution"] == 24

    def test_captain_gap_carries_the_difference(self):
        r = _build(_picks(), _live({10: 2, 7: 10}))
        s = next(s for s in r["stories"] if s["kind"] == "captain_gap")["evidence"]
        assert s["best"] == "Foden" and s["best_points"] == 10 and s["extra_points"] == (10 - 2) * 2

    def test_bench_points_story(self):
        r = _build(_picks(), _live({14: 9, 13: 3}))
        s = next(s for s in r["stories"] if s["kind"] == "bench_points")["evidence"]
        assert s["bench_points"] == 2 + 3 + 9 + 2 and s["best"] == "Rice" and s["best_points"] == 9

    def test_no_add_with_history_is_a_historical_comparison(self):
        hist = {7: _hist([(3, 90, 8), (4, 90, 6), (5, 90, 7), (6, 90, 9), (7, 90, 5)])}
        r = _build(_picks(), _live({7: 1}), player_histories=hist)
        s = next(s for s in r["stories"] if s["kind"] == "no_add")["evidence"]
        assert s["player"] == "Foden" and s["points"] == 1 and s["recent_n"] == 5 and s["recent_average"] == 7.0

    def test_no_add_without_history_has_no_comparison(self):
        r = _build(_picks(), _live({7: 1}))
        s = next(s for s in r["stories"] if s["kind"] == "no_add")["evidence"]
        assert "recent_average" not in s

    def test_minutes_change_story(self):
        hist = {8: _hist([(5, 90, 5), (6, 88, 4), (7, 90, 6)])}
        r = _build(_picks(), _live(minutes={8: 20}), player_histories=hist)
        s = next(s for s in r["stories"] if s["kind"] == "minutes_change")["evidence"]
        assert s["player"] == "Odegaard" and s["per_fixture"] == 20 and s["recent_average"] == 89 and s["direction"] == "down"

    def test_minutes_change_is_per_fixture_in_a_double_gameweek(self):
        hist = {8: _hist([(5, 90, 5), (6, 90, 4), (7, 90, 6)])}
        r = _build(_picks(), _live(minutes={8: 180}, fixtures={8: 2}), player_histories=hist)
        assert not any(s["kind"] == "minutes_change" for s in r["stories"])

    def test_history_after_the_gameweek_is_ignored(self):
        hist = {7: _hist([(9, 90, 20), (10, 90, 20)])}
        r = _build(_picks(), _live({7: 2}), player_histories=hist)
        s = next(s for s in r["stories"] if s["kind"] == "no_add")["evidence"]
        assert "recent_average" not in s

    def test_at_most_five_stories(self):
        hist = {8: _hist([(5, 90, 5), (6, 90, 4), (7, 90, 6)]), 7: _hist([(7, 90, 9)])}
        r = _build(_picks(subs=[(13, 11)]), _live({7: 1, 14: 9, 13: 4}, minutes={11: 0, 8: 10}), player_histories=hist)
        assert 2 <= len(r["stories"]) <= 5


# ===========================================================================
# G. Renderer + card
# ===========================================================================

_FORECAST_WORDS = ("expected points", "puntos esperados", "proyecci", "projection", "forecast for", "lo sabíamos", "we knew")


def _full_report() -> dict[str, Any]:
    hist = {7: _hist([(5, 90, 8), (6, 90, 7), (7, 90, 9)]), 8: _hist([(5, 90, 5), (6, 90, 4), (7, 90, 6)])}
    return _build(_picks(subs=[(13, 11)], official=0, cost=4), _live({7: 2, 14: 9, 13: 4}, minutes={11: 0, 8: 10}), player_histories=hist)


class TestRenderAndCard:
    @pytest.mark.parametrize("locale", ["es", "en"])
    def test_render_every_story_without_forecast_language_or_keys(self, locale):
        text = render("get_gw_report", _full_report(), locale=locale)
        assert "gw_report." not in text and "gcard." not in text
        low = text.lower()
        assert not any(w in low for w in _FORECAST_WORDS)
        for name in ("Haaland", "Lewis", "Havertz"):
            assert name in text

    def test_spanish_uses_j_and_english_uses_gw(self):
        r = _full_report()
        assert "J8" in render("get_gw_report", r, locale="es")
        assert "GW8" in render("get_gw_report", r, locale="en")

    def test_every_figure_in_stories_is_in_the_evidence(self):
        r = _full_report()
        import re
        from fpl_grounded_assistant.gw_report_text import story_text

        for s in r["stories"]:
            nums = set(re.findall(r"\d+(?:\.\d+)?", story_text(s, "en")))
            evid = {str(v) for v in _flatten(s["evidence"])} | {str(int(v)) for v in _flatten(s["evidence"]) if isinstance(v, float)}
            assert nums <= evid, (s["kind"], nums - evid)

    @pytest.mark.parametrize("locale", ["es", "en"])
    @pytest.mark.parametrize("payload", [
        {}, {"status": "error", "code": "x"}, {"status": "no_team_connected"}, {"status": "not_found"},
        {"status": "missing_context", "reason_codes": ["gw_not_finished"], "gw": 9},
        {"status": "missing_context", "reason_codes": ["no_finished_gameweek"]},
        {"status": "error", "code": "invalid_gw"},
    ])
    def test_non_ok_payloads_render(self, locale, payload):
        assert render("get_gw_report", payload, locale=locale).strip()

    def test_card_composes_for_ok_only(self):
        card = maybe_atomic_tool_card("get_gw_report", _full_report(), None, "es")
        assert card is not None and len(card.rows) == 15
        assert all(len(row) == len(card.columns) for row in card.rows)
        assert maybe_atomic_tool_card("get_gw_report", {"status": "missing_context"}, None, "es") is None

    def test_card_flags_unreconciled(self):
        card = maybe_atomic_tool_card("get_gw_report", _build(_picks(official=99), _live()), None, "en")
        assert any("match" in p.label.lower() for p in card.pills)
        assert "unreconciled" in card.hero.label

    def test_no_provider_ids_in_output(self):
        blob = repr(_full_report()).lower()
        assert "sportmonks" not in blob and "licensed" not in blob


def _flatten(v: Any) -> list[Any]:
    if isinstance(v, dict):
        return [x for i in v.values() for x in _flatten(i)]
    if isinstance(v, (list, tuple)):
        return [x for i in v for x in _flatten(i)]
    return [v]
