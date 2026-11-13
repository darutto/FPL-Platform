"""The player card's position verdict line, «Explorar» pill and «Zonas» team link (player_signals.py).

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
# Position line data (position_from_window): the position card's own window and count
# ---------------------------------------------------------------------------

def _m(gw: int, slot: dict | None, status: str = "started") -> dict:
    return {"gameweek": gw, "player_status": status if slot else ("bench" if status == "started" else status), "slot": slot}


def _window(*slots) -> list[dict]:
    return [_m(5 + i, s) for i, s in enumerate(slots)]


def test_role_word_count_and_gameweeks_match_the_card():
    window = _window(*[_slot("Left Midfield", "left")] * 6)
    assert ps.position_from_window(_el(10), window) == {
        "role": "winger", "starts": 6, "games": 6, "gw_from": 5, "gw_to": 10}


def test_count_is_the_cards_fpl_position_gap_over_the_window():
    from football_intelligence.position_changes import fpl_position_gap

    window = _window(_slot("Left Midfield"), _slot("Left Back"), _slot("Left Midfield"), None,
                     _slot("Left Midfield"), _slot("Left Midfield"))
    gap = fpl_position_gap(2, window)
    pos = ps.position_from_window(_el(10), window)
    assert (pos["starts"], pos["games"]) == (gap["starts"], gap["of"]) == (4, 5)
    # Bench / not-listed matches are in the window but not in the count; the span is his starts' gameweeks.
    assert (pos["gw_from"], pos["gw_to"]) == (5, 10)


def test_needs_more_than_half_on_one_line_and_a_minimum_of_starts():
    assert ps.position_from_window(_el(10), _window(*[_slot("Left Midfield")] * 2 + [_slot("Centre Back")] * 2)) is None
    assert ps.position_from_window(_el(10), _window(*[_slot("Left Midfield")] * 3 + [_slot("Centre Back")] * 2))
    assert ps.POSITION_MIN_STARTS == 3
    assert ps.position_from_window(_el(10), _window(*[_slot("Left Midfield")] * 2)) is None


def test_wing_back_in_a_back_three_is_a_defender_for_a_midfielder():
    pos = ps.position_from_window(_el(12), _window(*[_slot("Right Midfield", "right", "3-4-3")] * 4))
    assert pos == {"role": "wing_back", "starts": 4, "games": 4, "gw_from": 5, "gw_to": 8}


def test_mixed_roles_on_the_dominant_line_name_the_line():
    mixed_mid = _window(_slot("Attacking Midfield"), _slot("Central Midfield"), _slot("Central Midfield"),
                        _slot("Centre Forward"))
    assert ps.position_from_window(_el(15), mixed_mid)["line"] == "MID"
    assert "role" not in ps.position_from_window(_el(15), mixed_mid)


def test_on_line_starts_goalkeepers_and_no_data_never_give_a_line():
    assert ps.position_from_window(_el(11), _window(*[_slot("Centre Back")] * 6)) is None
    assert ps.position_from_window(_el(14), _window(*[_slot("Centre Back")] * 6)) is None
    assert ps.position_from_window(_el(10), None) is None
    assert ps.position_from_window(_el(10), []) is None


# ---------------------------------------------------------------------------
# Verdict order and cap
# ---------------------------------------------------------------------------

POS = {"role": "winger", "starts": 6, "games": 6, "gw_from": 5, "gw_to": 10}
ZONAL = {"fixtures": [{"status": "favorable", "opponent_short": "EAS"}, {"status": "favorable", "opponent_short": "WES"}]}


def _keys(element, zonal=None, position=None, bs=None):
    return [c["key"] for c in player_conclusions(element, bs or _bs(), zonal, position=position)]


def test_position_line_params_and_order():
    taker = {**_el(10), "penalties_order": 1}
    out = player_conclusions(taker, _bs(), ZONAL, position=POS)
    assert [c["key"] for c in out] == ["position", "set_pieces", "zonal"]
    assert out[0] == {"key": "position", "params": {"role": "winger", "starts": 6, "games": 6},
                      "evidence": {"gw_from": 5, "gw_to": 10}}
    no_span = player_conclusions(taker, _bs(), ZONAL, position={"role": "winger", "starts": 6, "games": 6})
    assert no_span[0]["evidence"] is None


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


def test_only_the_position_line_gets_an_explorar_pill_es():
    out = ps.signals_from_conclusions(_el(10), _concl("position", "set_pieces", "zonal"), _bs("es"))
    assert out == [{"kind": "position", "label": "Posición", "send_text": "¿En qué posición juega Quillby?"}]


def test_pill_en():
    out = ps.signals_from_conclusions(_el(10), _concl("position", "zonal"), _bs("en"))
    assert [(p["label"], p["send_text"]) for p in out] == [("Position", "What position does Quillby really play?")]


@pytest.mark.parametrize("keys,kinds", [
    (("position", "starts"), ["position"]),
    (("set_pieces", "zonal"), []),
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
    many = [{"key": k, "params": {}, "evidence": None} for k in ("points_attack", "set_pieces", "zonal")]
    assert ps.signals_from_conclusions(taker, many, _bs()) == []


def test_shared_web_name_uses_the_full_name_and_unresolvable_names_drop_the_pill():
    out = ps.signals_from_conclusions(_el(12), _concl("position"), _bs())
    assert out[0]["send_text"] == "¿En qué posición juega Luca Fenn?"
    ghost = {"id": 999, "web_name": "Ghost", "first_name": "", "second_name": "", "team": 1, "element_type": 2}
    assert ps.signals_from_conclusions(ghost, _concl("position"), _bs()) == []


# ---------------------------------------------------------------------------
# «Zonas» team link: the nearest favourable row of the card's own zonal block
# ---------------------------------------------------------------------------

def _zonal(*rows):
    return {"fixtures": [{"status": st, "opponent_short": opp} for st, opp in rows]}


def test_zone_link_names_the_nearest_favourable_rival_es_en():
    zonal = _zonal(("neutral", "WES"), ("favorable", "EAS"), ("favorable", "WES"))
    assert ps.zone_signal(_el(10), zonal, _bs("es")) == {
        "kind": "zone", "label": "Quién del NOR explota al EAS",
        "send_text": "¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?"}
    assert ps.zone_signal(_el(10), zonal, _bs("en")) == {
        "kind": "zone", "label": "Who at NOR exploits EAS",
        "send_text": "Which Northbury players can exploit Eastport's weak zones?"}


@pytest.mark.parametrize("zonal", [
    None, {}, _zonal(), _zonal(("neutral", "EAS"), ("no_data", "WES")), _zonal(("favorable", "XXX")),
    {"fixtures": "junk"},
])
def test_no_favourable_row_or_unknown_rival_no_zone_link(zonal):
    assert ps.zone_signal(_el(10), zonal, _bs()) is None


def test_zone_link_does_not_depend_on_the_verdict_line():
    # The «Zonas» section shows whatever the verdict's cap kept; so does its link.
    assert ps.zone_signal(_el(10), ZONAL, _bs()) is not None


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
            wing = f % 4 != 0  # 9 of 12 on the wing; the window keeps the club's last 6 matches
            slots.append({"fixture_id": f, "team": "NOR", "observed_at": obs, "element": 10, "starter": True,
                          "detailed_position": "Left Midfield" if wing else "Left Back",
                          "grid_slot": "3:3" if wing else "2:4", "side": "left"})
        squad = [{"team": "NOR", "element": 10, "jersey_number": 3, "observed_at": "2026-09-01T10:00:00Z"}]
        self._tables = {n: pd.DataFrame(r, columns=list(TABLES[n][0])).astype(object)
                        for n, r in (("lineup_snapshots", snaps), ("lineup_slots", slots), ("squad_membership", squad))}
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


def test_index_keeps_the_position_card_window_and_shares_the_strip_axis_read(fi_on):
    bs = {**_bs(), "fixture_index": FIX}
    handle = FakeHandle()
    window = axis_mod.position_window_for(10, bs, handle=handle, background=False)
    assert [m["gameweek"] for m in window] == [7, 8, 9, 10, 11, 12]
    # GWs 7, 9, 10, 11 on the wing, 8 and 12 at left-back: the card's «4/6 · J7–J12».
    assert ps.position_from_window(_el(10), window) == {
        "role": "winger", "starts": 4, "games": 6, "gw_from": 7, "gw_to": 12}
    axis_mod.strip_axis_for(10, bs, handle=handle, background=False)
    assert handle.reads == 3  # lineup_snapshots + lineup_slots + squad_membership, once for both uses
    assert axis_mod.position_window_for(11, bs, handle=handle, background=False) == []


def test_index_window_is_what_the_position_card_reads(fi_on):
    from football_intelligence.position_changes import analyse

    bs = {**_bs(), "fixture_index": FIX}
    handle = FakeHandle()
    window = axis_mod.position_window_for(10, bs, handle=handle, background=False)
    from fpl_grounded_assistant.position_changes_tool import fixture_index

    card = analyse(element=10, snapshots=handle.table("lineup_snapshots"), slots=handle.table("lineup_slots"),
                   sidelined=pd.DataFrame(columns=["element"]), squad_membership=handle.table("squad_membership"),
                   fixtures=fixture_index(bs), names={})
    assert [(m["gameweek"], m["player_status"], m["slot"]) for m in card["matches"]] == [
        (m["gameweek"], m["player_status"], m["slot"]) for m in window]


def test_index_not_ready_means_no_line_and_no_wait(fi_on, monkeypatch):
    started = []
    monkeypatch.setattr(axis_mod.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: started.append(kw)})())
    handle = FakeHandle()
    assert axis_mod.position_window_for(10, {**_bs(), "fixture_index": FIX}, handle=handle) is None
    assert handle.reads == 0 and len(started) == 1


def test_flag_off_reads_nothing(monkeypatch):
    monkeypatch.delenv("FOOTBALL_INTELLIGENCE_ENABLED", raising=False)
    axis_mod._reset_for_tests()
    handle = FakeHandle()
    assert axis_mod.position_window_for(10, _bs(), handle=handle, background=False) is None
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


def test_snapshot_appends_the_zonas_link_after_the_pill(snap, monkeypatch):
    monkeypatch.setattr(snap, "position_fact", lambda element, bs: POS)
    monkeypatch.setattr(snap, "_attach_zonal", lambda pd_, *a, **k: pd_.update(zonal=_zonal(("favorable", "EAS"))))
    out = snap.get_player_snapshot("Quillby", bootstrap=_bs())
    assert [s["kind"] for s in out["signals"]] == ["position", "zone"]
    assert out["signals"][1]["label"] == "Quién del NOR explota al EAS"
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
    assert wire["conclusions"] == [{"key": "position", "params": {"role": "winger", "starts": 6, "games": 6},
                                    "evidence": {"gw_from": 5, "gw_to": 10}}]
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
