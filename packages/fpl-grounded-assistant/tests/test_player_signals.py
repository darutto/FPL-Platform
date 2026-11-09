"""Player-card signals (player_signals.py). Synthetic data only: invented
players, clubs and lineups; no value from the licensed store."""
from __future__ import annotations

import copy

import pytest

from fpl_grounded_assistant import player_signals as ps
from fpl_grounded_assistant.final_response import PlayerSignal, _extract_player_signals
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY

_TEAMS = [
    {"id": 1, "name": "Northbury", "short_name": "NOR"},
    {"id": 2, "name": "Eastport", "short_name": "EAS"},
    {"id": 3, "name": "Westvale", "short_name": "WES"},
]
_ELEMENTS = [
    {"id": 10, "first_name": "Tomas", "second_name": "Quillby", "web_name": "Quillby",
     "team": 1, "element_type": 4, "status": "a"},
    {"id": 11, "first_name": "Ana", "second_name": "Brekker", "web_name": "Brekker",
     "team": 1, "element_type": 2, "status": "a"},
    # two players share a web_name: the question must use the full name
    {"id": 12, "first_name": "Luca", "second_name": "Fenn", "web_name": "Fenn",
     "team": 2, "element_type": 3, "status": "a"},
    {"id": 13, "first_name": "Mats", "second_name": "Fenn", "web_name": "Fenn",
     "team": 3, "element_type": 3, "status": "a"},
    {"id": 14, "first_name": "Ola", "second_name": "Keeper", "web_name": "Keeper",
     "team": 2, "element_type": 1, "status": "a"},
]
_BOOTSTRAP = {
    "elements": _ELEMENTS,
    "teams": _TEAMS,
    "element_types": [{"id": i, "singular_name_short": s} for i, s in
                      ((1, "GKP"), (2, "DEF"), (3, "MID"), (4, "FWD"))],
}


def _bs(locale: str = "es") -> dict:
    out = copy.deepcopy(_BOOTSTRAP)
    out[BOOTSTRAP_LOCALE_KEY] = locale
    return out


def _el(pid: int) -> dict:
    return next(e for e in _ELEMENTS if e["id"] == pid)


def _start(role: str, side: str | None = None, formation: str = "4-3-3") -> dict:
    return {"player_status": "started",
            "slot": {"detailed_position": role, "side": side, "formation": formation, "grid_slot": "1:1"}}


def _bench() -> dict:
    return {"player_status": "bench", "slot": None}


def _changes(*matches: dict) -> dict:
    return {"status": "ok", "matches": list(matches)}


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

def test_position_two_of_four_off_line_shows_role_and_counts():
    ch = _changes(_start("Centre Forward"), _start("Left Midfield", "left"), _bench(),
                  _start("Centre Forward"), _start("Left Midfield", "left"))
    es = ps.position_signal(_el(10), ch, "Quillby", "es")
    en = ps.position_signal(_el(10), ch, "Quillby", "en")
    assert es == {"kind": "position", "label": "Extremo 2 de 4",
                  "send_text": "¿En qué posición juega Quillby?"}
    assert en["label"] == "Winger 2 of 4"
    assert en["send_text"] == "What position does Quillby really play?"


def test_position_needs_half_of_the_starts():
    ch = _changes(_start("Centre Forward"), _start("Centre Forward"),
                  _start("Left Midfield", "left"), _start("Centre Forward"))
    assert ps.position_signal(_el(10), ch, "Quillby", "es") is None


def test_position_needs_minimum_starts():
    ch = _changes(_start("Left Midfield"), _start("Left Midfield"), _bench(), _bench())
    assert ps.POSITION_MIN_STARTS == 3
    assert ps.position_signal(_el(10), ch, "Quillby", "es") is None


def test_position_reads_only_the_latest_starts():
    old_off = [_start("Left Midfield")] * 4
    recent_on = [_start("Centre Forward")] * ps.POSITION_RECENT_STARTS
    assert ps.position_signal(_el(10), _changes(*old_off, *recent_on), "Quillby", "es") is None


def test_wing_back_in_back_three_is_a_defender_line_for_a_midfielder():
    ch = _changes(*[_start("Right Midfield", "right", "3-4-3")] * 3)
    sig = ps.position_signal(_el(12), ch, "Luca Fenn", "es")
    assert sig is not None and sig["label"] == "Carrilero 3 de 3"


def test_mixed_roles_on_one_line_fall_back_to_the_line_word():
    ch = _changes(_start("Attacking Midfield"), _start("Central Midfield"), _start("Centre Forward"))
    assert ps.position_signal(_el(10), ch, "Quillby", "es")["label"] == "Medio 2 de 3"
    assert ps.position_signal(_el(10), ch, "Quillby", "en")["label"] == "Midfielder 2 of 3"


def test_on_line_starts_and_goalkeepers_never_signal():
    on_line = _changes(*[_start("Centre Back")] * 4)
    assert ps.position_signal(_el(11), on_line, "Brekker", "es") is None
    gk = _changes(*[_start("Centre Back")] * 4)
    assert ps.position_signal(_el(14), gk, "Keeper", "es") is None


def test_position_ignores_missing_or_failed_changes():
    for ch in (None, {"status": "missing_context"}, {"status": "ok"}, {"status": "ok", "matches": "x"}):
        assert ps.position_signal(_el(10), ch, "Quillby", "es") is None


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------

def _zonal(*fixtures: dict, gw_from: int = 11) -> dict:
    return {"window": {"gw_from": gw_from, "gw_to": gw_from + 2}, "fixtures": list(fixtures)}


def _fx(gw: int, opp: str, status: str = "favorable", zone: str = "in-box / left", delta: float = 0.1) -> dict:
    return {"gameweek": gw, "opponent": opp, "opponent_short": opp, "status": status,
            "matches": [{"zone": zone, "delta_vs_avg": delta, "player_share": 0.4}] if status == "favorable" else []}


def test_zone_takes_the_nearest_favourable_rival():
    z = _zonal(_fx(11, "WES", status="neutral"), _fx(12, "EAS"), _fx(13, "WES"))
    es = ps.zone_signal(_el(10), z, _bs("es"), "es")
    en = ps.zone_signal(_el(10), z, _bs("en"), "en")
    assert es == {"kind": "zone", "label": "Banda débil EAS",
                  "send_text": "¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?"}
    assert en["label"] == "EAS weak flank"
    assert en["send_text"] == "Which Northbury players can exploit Eastport's weak zones?"


def test_zone_central_label_and_strongest_match():
    fx = _fx(11, "EAS")
    fx["matches"] = [{"zone": "in-box / left", "delta_vs_avg": 0.05, "player_share": 0.3},
                     {"zone": "in-box / central", "delta_vs_avg": 0.2, "player_share": 0.5}]
    assert ps.zone_signal(_el(10), _zonal(fx), _bs(), "es")["label"] == "Centro débil EAS"
    assert ps.zone_signal(_el(10), _zonal(fx), _bs(), "en")["label"] == "EAS weak centre"


def test_zone_absent_without_a_favourable_rival_in_the_window():
    assert ps.zone_signal(_el(10), None, _bs(), "es") is None
    assert ps.zone_signal(_el(10), _zonal(_fx(11, "EAS", "neutral"), _fx(12, "WES", "no_data")), _bs(), "es") is None
    beyond = _fx(11 + ps.ZONE_WINDOW_GWS, "EAS")
    assert ps.zone_signal(_el(10), _zonal(beyond), _bs(), "es") is None


# ---------------------------------------------------------------------------
# Whole row
# ---------------------------------------------------------------------------

_TWO_OF_FOUR = _changes(_start("Left Midfield"), _start("Centre Forward"),
                        _start("Left Midfield"), _start("Centre Forward"))


def test_row_order_is_position_then_zone_and_capped():
    player = {"zonal": _zonal(_fx(11, "EAS"))}
    out = ps.build_player_signals(_el(10), player, _bs(), position_changes=lambda e, b: _TWO_OF_FOUR)
    assert [s["kind"] for s in out] == ["position", "zone"]
    assert len(out) <= ps.MAX_SIGNALS == 3


@pytest.mark.parametrize("changes,zonal,kinds", [
    (_TWO_OF_FOUR, None, ["position"]),
    (None, _zonal(_fx(11, "EAS")), ["zone"]),
    (None, None, []),
])
def test_row_one_or_zero_signals(changes, zonal, kinds):
    out = ps.build_player_signals(_el(10), {"zonal": zonal}, _bs(), position_changes=lambda e, b: changes)
    assert [s["kind"] for s in out] == kinds


def test_a_failing_lookup_drops_only_that_signal():
    def boom(e, b):
        raise RuntimeError("store down")
    out = ps.build_player_signals(_el(10), {"zonal": _zonal(_fx(11, "EAS"))}, _bs(), position_changes=boom)
    assert [s["kind"] for s in out] == ["zone"]


def test_shared_web_name_uses_the_full_name_in_the_question():
    ch = _changes(*[_start("Centre Forward")] * 3)
    out = ps.build_player_signals(_el(12), {}, _bs(), position_changes=lambda e, b: ch)
    assert out[0]["send_text"] == "¿En qué posición juega Luca Fenn?"


def test_position_is_not_looked_up_when_the_tool_is_not_offered(monkeypatch):
    monkeypatch.delenv("FOOTBALL_INTELLIGENCE_ENABLED", raising=False)
    import fpl_grounded_assistant.position_changes_tool as pct

    def never(*a, **k):
        raise AssertionError("licensed store read with the FI flag off")
    monkeypatch.setattr(pct, "run_position_changes", never)
    assert ps._position_changes(_el(10), _bs()) is None


# ---------------------------------------------------------------------------
# Wiring: snapshot output, model view, meta, wire
# ---------------------------------------------------------------------------

def test_snapshot_carries_signals_top_level_and_only_when_present(monkeypatch):
    from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot

    monkeypatch.setattr(ps, "_position_changes", lambda e, b: _TWO_OF_FOUR)
    out = get_player_snapshot("Quillby", bootstrap=_bs())
    assert out["status"] == "ok"
    assert out["signals"][0]["label"] == "Extremo 2 de 4"
    assert "signals" not in out["player"]

    assert "signals" not in get_player_snapshot("Quillby", bootstrap=_bs(), signals=False)
    monkeypatch.setattr(ps, "_position_changes", lambda e, b: None)
    assert "signals" not in get_player_snapshot("Quillby", bootstrap=_bs())


def test_signals_are_hidden_from_the_model():
    from fpl_grounded_assistant.orchestrator import _truncate_tool_output

    raw = {"status": "ok", "player": {"id": 10}, "signals": [{"kind": "zone", "label": "x", "send_text": "y"}]}
    assert "signals" not in _truncate_tool_output(raw, max_items=10, tool_name="get_player_snapshot")


def test_meta_extraction_drops_malformed_signals():
    raw = [
        {"kind": "position", "label": "Extremo 2 de 4", "send_text": "q1"},
        {"kind": "fixtures", "label": "x", "send_text": "q"},  # not a kind of this version
        {"kind": "zone", "label": "", "send_text": "q"},
        "junk",
        {"kind": "zone", "label": "Banda débil EAS", "send_text": "q2"},
    ]
    assert _extract_player_signals(raw) == (
        PlayerSignal("position", "Extremo 2 de 4", "q1"),
    )
    assert _extract_player_signals(None) == ()


def test_serializer_puts_signals_on_the_wire(monkeypatch):
    from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
    from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
    from fpl_server import _player_snapshot_meta_dict

    monkeypatch.setattr(ps, "_position_changes", lambda e, b: _TWO_OF_FOUR)
    meta = _extract_player_snapshot_meta(get_player_snapshot("Quillby", bootstrap=_bs()), "es")
    wire = _player_snapshot_meta_dict(meta)
    assert wire["signals"] == [{"kind": "position", "label": "Extremo 2 de 4",
                                "send_text": "¿En qué posición juega Quillby?"}]
    monkeypatch.setattr(ps, "_position_changes", lambda e, b: None)
    meta = _extract_player_snapshot_meta(get_player_snapshot("Quillby", bootstrap=_bs()), "es")
    assert _player_snapshot_meta_dict(meta)["signals"] == []


# ---------------------------------------------------------------------------
# Routing: a tapped question must leave the snapshot fast path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("locale,name", [("es", "Quillby"), ("en", "Quillby"), ("es", "Luca Fenn")])
def test_pill_questions_are_not_answered_by_the_snapshot_fast_path(locale, name):
    """The snapshot fast path answering would just show the same card again.
    The questions must reach the orchestrator, whose tool descriptions claim them."""
    from fpl_grounded_assistant.catalogue import t
    from fpl_grounded_assistant.player_lookup import classify_player_lookup

    questions = [
        t("signals.position.ask", locale, player=name),
        t("signals.zone.ask", locale, team="Northbury", opp="Eastport"),
    ]
    for q in questions:
        assert not classify_player_lookup(q, _bs(locale)).terminal, q


def test_pill_questions_match_the_target_tool_descriptions():
    """The phrasings are the ones the tool descriptions already claim."""
    from fpl_grounded_assistant.tool_schema_registry import (
        GET_POSITION_CHANGES_SCHEMA,
        GET_ZONAL_OPPORTUNITY_SCHEMA,
    )

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
