"""The player card's position verdict line and «Explorar» pills (player_signals.py).

Synthetic data only: invented players, clubs and lineups; no value from the licensed store. No network, no provider.
"""
from __future__ import annotations

import copy
import sys

import pandas as pd
import pytest

from fpl_grounded_assistant import player_signals as ps
from fpl_grounded_assistant import player_strip_axis as axis_mod
from fpl_grounded_assistant.final_response import PlayerSignal, _extract_player_signals, _extract_player_snapshot_meta
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY
from fpl_grounded_assistant.player_conclusions import player_conclusions

_TEAMS = [
    {"id": 1, "name": "Northbury", "short_name": "NOR"},
    {"id": 2, "name": "Eastport", "short_name": "EAS"},
    {"id": 3, "name": "Westvale", "short_name": "WES"},
]
_ELEMENTS = [
    {"id": 10, "first_name": "Tomas", "second_name": "Quillby", "web_name": "Quillby",
     "team": 1, "element_type": 2, "status": "a"},
    {"id": 11, "first_name": "Ana", "second_name": "Brekker", "web_name": "Brekker",
     "team": 1, "element_type": 2, "status": "a"},
    # two players share a web_name: the question must use the full name
    {"id": 12, "first_name": "Luca", "second_name": "Fenn", "web_name": "Fenn",
     "team": 2, "element_type": 3, "status": "a"},
    {"id": 13, "first_name": "Mats", "second_name": "Fenn", "web_name": "Fenn",
     "team": 3, "element_type": 3, "status": "a"},
    {"id": 14, "first_name": "Ola", "second_name": "Keeper", "web_name": "Keeper",
     "team": 2, "element_type": 1, "status": "a"},
    {"id": 15, "first_name": "Ivo", "second_name": "Strand", "web_name": "Strand",
     "team": 1, "element_type": 4, "status": "a"},
]
_BOOTSTRAP = {
    "elements": _ELEMENTS,
    "teams": _TEAMS,
    "events": [],
    "element_types": [{"id": i, "singular_name_short": s} for i, s in
                      ((1, "GKP"), (2, "DEF"), (3, "MID"), (4, "FWD"))],
}


def _bs(locale: str = "es") -> dict:
    out = copy.deepcopy(_BOOTSTRAP)
    out[BOOTSTRAP_LOCALE_KEY] = locale
    return out


def _el(pid: int) -> dict:
    return next(e for e in _ELEMENTS if e["id"] == pid)


def _slot(role: str, side: str | None = None, formation: str = "4-3-3") -> dict:
    return {"detailed_position": role, "side": side, "formation": formation, "grid_slot": "1:1"}


# ---------------------------------------------------------------------------
# Position line data (position_from_starts)
# ---------------------------------------------------------------------------

def test_role_word_when_off_line_starts_agree():
    starts = [_slot("Left Midfield", "left")] * 7 + [_slot("Left Back", "left")] * 3
    assert ps.position_from_starts(_el(10), starts) == {"role": "winger", "starts": 7, "games": 10}


def test_reads_only_the_latest_window():
    old_off = [_slot("Left Midfield")] * 6
    recent_on = [_slot("Left Back")] * ps.POSITION_RECENT_STARTS
    assert ps.POSITION_RECENT_STARTS == 10
    assert ps.position_from_starts(_el(10), old_off + recent_on) is None


def test_needs_half_and_a_minimum_of_starts():
    assert ps.position_from_starts(_el(10), [_slot("Left Midfield")] * 4 + [_slot("Centre Back")] * 5) is None
    assert ps.position_from_starts(_el(10), [_slot("Left Midfield")] * 5 + [_slot("Centre Back")] * 5) is not None
    assert ps.POSITION_MIN_STARTS == 3
    assert ps.position_from_starts(_el(10), [_slot("Left Midfield")] * 2) is None


def test_wing_back_in_a_back_three_is_a_defender_for_a_midfielder():
    pos = ps.position_from_starts(_el(12), [_slot("Right Midfield", "right", "3-4-3")] * 4)
    assert pos == {"role": "wing_back", "starts": 4, "games": 4}


def test_mixed_roles_on_one_line_name_the_line_and_mixed_lines_name_nothing():
    mixed_mid = [_slot("Attacking Midfield"), _slot("Central Midfield"), _slot("Centre Forward")]
    assert ps.position_from_starts(_el(15), mixed_mid) == {"line": "MID", "starts": 2, "games": 3}
    mixed_lines = [_slot("Left Midfield"), _slot("Centre Forward"), _slot("Centre Back"), _slot("Centre Back")]
    assert ps.position_from_starts(_el(12), mixed_lines) is None  # MID listed: one FWD start, two DEF starts


def test_on_line_starts_goalkeepers_and_no_data_never_give_a_line():
    assert ps.position_from_starts(_el(11), [_slot("Centre Back")] * 6) is None
    assert ps.position_from_starts(_el(14), [_slot("Centre Back")] * 6) is None
    assert ps.position_from_starts(_el(10), None) is None
    assert ps.position_from_starts(_el(10), []) is None


# ---------------------------------------------------------------------------
# Verdict order and cap
# ---------------------------------------------------------------------------

POS = {"role": "winger", "starts": 7, "games": 10}
ZONAL = {"fixtures": [{"status": "favorable", "opponent_short": "EAS"}, {"status": "favorable", "opponent_short": "WES"}]}


def _keys(element, zonal=None, position=None, bs=None):
    return [c["key"] for c in player_conclusions(element, bs or _bs(), zonal, position=position)]


def test_position_line_params_and_order():
    taker = {**_el(10), "penalties_order": 1}
    out = player_conclusions(taker, _bs(), ZONAL, position=POS)
    assert [c["key"] for c in out] == ["position", "set_pieces", "zonal"]
    assert out[0] == {"key": "position", "params": {"role": "winger", "starts": 7, "games": 10}, "evidence": None}


def test_without_position_the_verdict_is_unchanged():
    taker = {**_el(10), "penalties_order": 1}
    assert _keys(taker, ZONAL) == ["set_pieces", "zonal"]
    assert _keys(taker, ZONAL, position={"role": "winger", "starts": 0, "games": 10}) == ["set_pieces", "zonal"]
    assert _keys(taker, ZONAL, position={"starts": 3, "games": 4}) == ["set_pieces", "zonal"]


def test_cap_of_three_pushes_zonal_out_after_position():
    taker = {**_el(10), "penalties_order": 1}
    bs = _bs()
    # A points-source line too: make him the top attacking defender of a synthetic pool.
    pool = [{**e, "minutes": 900, "expected_goal_involvements_per_90": "0.05"} for e in bs["elements"]]
    taker = {**taker, "minutes": 900, "expected_goal_involvements_per_90": "0.9"}
    bs["elements"] = [taker if e["id"] == 10 else e for e in pool] + [
        {"id": 100 + i, "element_type": 2, "minutes": 900, "expected_goal_involvements_per_90": "0.05", "team": 3}
        for i in range(8)]
    assert _keys(taker, ZONAL, POS, bs) == ["points_attack", "position", "set_pieces"]


# ---------------------------------------------------------------------------
# Pills follow the emitted lines
# ---------------------------------------------------------------------------

def _concl(*keys):
    return [{"key": k, "params": {"opponents": ["EAS", "WES"]} if k == "zonal" else {}, "evidence": None} for k in keys]


def test_one_pill_per_emitted_line_in_verdict_order_es():
    out = ps.signals_from_conclusions(_el(10), _concl("position", "set_pieces", "zonal"), _bs("es"))
    assert out == [
        {"kind": "position", "label": "Posición", "send_text": "¿En qué posición juega Quillby?"},
        {"kind": "zone", "label": "Zonas",
         "send_text": "¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?"},
    ]


def test_pills_en():
    out = ps.signals_from_conclusions(_el(10), _concl("position", "zonal"), _bs("en"))
    assert [(p["label"], p["send_text"]) for p in out] == [
        ("Position", "What position does Quillby really play?"),
        ("Zones", "Which Northbury players can exploit Eastport's weak zones?"),
    ]


@pytest.mark.parametrize("keys,kinds", [
    (("position", "starts"), ["position"]),
    (("set_pieces", "zonal"), ["zone"]),
    (("points_attack", "starts"), []),
    ((), []),
])
def test_no_line_no_pill(keys, kinds):
    assert [p["kind"] for p in ps.signals_from_conclusions(_el(10), _concl(*keys), _bs())] == kinds


def test_a_line_cut_by_the_cap_gets_no_pill():
    taker = {**_el(10), "penalties_order": 1, "minutes": 900, "expected_goal_involvements_per_90": "0.9"}
    bs = _bs()
    bs["elements"] = [taker if e["id"] == 10 else e for e in bs["elements"]] + [
        {"id": 100 + i, "element_type": 2, "minutes": 900, "expected_goal_involvements_per_90": "0.05", "team": 3}
        for i in range(8)]
    emitted = player_conclusions(taker, bs, ZONAL, position=POS)
    assert [c["key"] for c in emitted] == ["points_attack", "position", "set_pieces"]
    # The pill's name check runs against the card's normal bootstrap.
    assert [p["kind"] for p in ps.signals_from_conclusions(taker, emitted, _bs())] == ["position"]


def test_shared_web_name_uses_the_full_name_and_unresolvable_names_drop_the_pill():
    out = ps.signals_from_conclusions(_el(12), _concl("position"), _bs())
    assert out[0]["send_text"] == "¿En qué posición juega Luca Fenn?"
    ghost = {"id": 999, "web_name": "Ghost", "first_name": "", "second_name": "", "team": 1, "element_type": 2}
    assert ps.signals_from_conclusions(ghost, _concl("position", "zonal"), _bs())[0]["kind"] == "zone"


def test_unknown_rival_drops_only_the_zone_pill():
    bad = [{"key": "zonal", "params": {"opponents": ["XXX"]}, "evidence": None}]
    assert ps.signals_from_conclusions(_el(10), _concl("position") + bad, _bs()) == [
        ps.signals_from_conclusions(_el(10), _concl("position"), _bs())[0]]


# ---------------------------------------------------------------------------
# The lineup index (shared with the strip axis): one read per build, never on the card's path
# ---------------------------------------------------------------------------

FIX = [{"id": f, "event": f, "kickoff_time": f"2026-10-{f:02d}T15:00:00Z", "team_h": 1, "team_a": 2} for f in range(1, 13)]


class FakeHandle:
    def __init__(self, build_id="b-1"):
        from football_intelligence.ingestion.licensed.store import TABLES

        snaps, slots = [], []
        for f in range(1, 13):
            obs = f"2026-10-{f:02d}T10:00:00Z"
            snaps.append({"fixture_id": f, "team": "NOR", "observed_at": obs, "state": "finished", "confirmed": True,
                          "formation": "4-2-3-1", "n_starters": 1, "n_bench": 0})
            wing = f % 4 != 0  # 9 of 12 on the wing; the window keeps the last 10
            slots.append({"fixture_id": f, "team": "NOR", "observed_at": obs, "element": 10, "starter": True,
                          "detailed_position": "Left Midfield" if wing else "Left Back",
                          "grid_slot": "3:3" if wing else "2:4", "side": "left"})
        self._tables = {n: pd.DataFrame(r, columns=list(TABLES[n][0])).astype(object)
                        for n, r in (("lineup_snapshots", snaps), ("lineup_slots", slots))}
        self._build_id, self.reads = build_id, 0

    def build_id(self):
        return self._build_id

    def table(self, name):
        self.reads += 1
        return self._tables[name]


@pytest.fixture
def fi_on(monkeypatch):
    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "1")
    axis_mod._reset_for_tests()
    yield
    axis_mod._reset_for_tests()


def test_index_keeps_the_last_ten_starts_and_shares_the_strip_axis_read(fi_on):
    bs = {**_bs(), "fixture_index": FIX}
    handle = FakeHandle()
    starts = axis_mod.recent_starts_for(10, bs, handle=handle, background=False)
    assert len(starts) == 10
    assert ps.position_from_starts(_el(10), starts) == {"role": "winger", "starts": 7, "games": 10}
    axis_mod.strip_axis_for(10, bs, handle=handle, background=False)
    assert handle.reads == 2  # lineup_snapshots + lineup_slots, once for both uses
    assert axis_mod.recent_starts_for(11, bs, handle=handle, background=False) == []


def test_index_not_ready_means_no_line_and_no_wait(fi_on, monkeypatch):
    started = []
    monkeypatch.setattr(axis_mod.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: started.append(kw)})())
    handle = FakeHandle()
    assert axis_mod.recent_starts_for(10, {**_bs(), "fixture_index": FIX}, handle=handle) is None
    assert handle.reads == 0 and len(started) == 1


def test_flag_off_reads_nothing(monkeypatch):
    monkeypatch.delenv("FOOTBALL_INTELLIGENCE_ENABLED", raising=False)
    axis_mod._reset_for_tests()
    handle = FakeHandle()
    assert axis_mod.recent_starts_for(10, _bs(), handle=handle, background=False) is None
    assert handle.reads == 0
    assert ps.position_fact(_el(10), _bs()) is None


# ---------------------------------------------------------------------------
# Wiring: snapshot output, model view, meta, wire
# ---------------------------------------------------------------------------

@pytest.fixture
def snap(monkeypatch):
    mod = sys.modules["fpl_grounded_assistant.get_player_snapshot"]
    monkeypatch.setattr(mod, "strip_axis_for", lambda element, bs: None)
    monkeypatch.setattr(mod, "_attach_zonal", lambda *a, **k: None)
    return mod


def test_snapshot_carries_the_line_and_its_pill(snap, monkeypatch):
    monkeypatch.setattr(snap, "position_fact", lambda element, bs: POS)
    out = snap.get_player_snapshot("Quillby", bootstrap=_bs())
    assert [c["key"] for c in out["player"]["conclusions"]] == ["position"]
    assert out["signals"] == [{"kind": "position", "label": "Posición", "send_text": "¿En qué posición juega Quillby?"}]
    assert "signals" not in out["player"]
    # build_squad's path: the line stays, no pills
    assert "signals" not in snap.get_player_snapshot("Quillby", bootstrap=_bs(), signals=False)


def test_snapshot_without_lines_has_no_pills(snap, monkeypatch):
    monkeypatch.setattr(snap, "position_fact", lambda element, bs: None)
    out = snap.get_player_snapshot("Quillby", bootstrap=_bs())
    assert "signals" not in out and "conclusions" not in out["player"]


def test_signals_are_hidden_from_the_model():
    from fpl_grounded_assistant.orchestrator import _truncate_tool_output

    raw = {"status": "ok", "player": {"id": 10}, "signals": [{"kind": "zone", "label": "x", "send_text": "y"}]}
    assert "signals" not in _truncate_tool_output(raw, max_items=10, tool_name="get_player_snapshot")


def test_meta_extraction_drops_malformed_signals_and_keeps_the_position_line():
    raw = [
        {"kind": "position", "label": "Posición", "send_text": "q1"},
        {"kind": "fixtures", "label": "x", "send_text": "q"},
        {"kind": "zone", "label": "", "send_text": "q"},
        "junk",
    ]
    assert _extract_player_signals(raw) == (PlayerSignal("position", "Posición", "q1"),)
    assert _extract_player_signals(None) == ()
    out = {"status": "ok", "player": {"id": 1, "web_name": "X", "fixtures": [],
                                      "conclusions": [{"key": "position", "params": POS, "evidence": None}]}}
    assert _extract_player_snapshot_meta(out).conclusions[0].key == "position"


def test_serializer_puts_lines_and_pills_on_the_wire(snap, monkeypatch):
    from fpl_server import _player_snapshot_meta_dict

    monkeypatch.setattr(snap, "position_fact", lambda element, bs: POS)
    wire = _player_snapshot_meta_dict(_extract_player_snapshot_meta(snap.get_player_snapshot("Quillby", bootstrap=_bs()), "es"))
    assert wire["conclusions"] == [{"key": "position", "params": POS, "evidence": None}]
    assert wire["signals"] == [{"kind": "position", "label": "Posición", "send_text": "¿En qué posición juega Quillby?"}]


# ---------------------------------------------------------------------------
# Routing: a tapped question must leave the snapshot fast path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("locale,name", [("es", "Quillby"), ("en", "Quillby"), ("es", "Luca Fenn")])
def test_pill_questions_are_not_answered_by_the_snapshot_fast_path(locale, name):
    from fpl_grounded_assistant.catalogue import t
    from fpl_grounded_assistant.player_lookup import classify_player_lookup

    for q in (t("signals.position.ask", locale, player=name),
              t("signals.zone.ask", locale, team="Northbury", opp="Eastport")):
        assert not classify_player_lookup(q, _bs(locale)).terminal, q


def test_pill_questions_match_the_target_tool_descriptions():
    from fpl_grounded_assistant.tool_schema_registry import GET_POSITION_CHANGES_SCHEMA, GET_ZONAL_OPPORTUNITY_SCHEMA

    pos = GET_POSITION_CHANGES_SCHEMA.description.lower()
    assert "en que posicion juega x" in pos and "what position does x really play" in pos
    zon = GET_ZONAL_OPPORTUNITY_SCHEMA.description.lower()
    assert "which players" in zon and "exploit" in zon and "weak zones" in zon


def test_zone_question_scopes_the_card_to_his_club():
    from fpl_grounded_assistant.catalogue import t
    from fpl_grounded_assistant.zonal_weakness_tool import infer_subject_teams

    for locale in ("es", "en"):
        q = t("signals.zone.ask", locale, team="Northbury", opp="Eastport")
        assert infer_subject_teams(q, "Eastport", _bs(locale)) == ["NOR"]
