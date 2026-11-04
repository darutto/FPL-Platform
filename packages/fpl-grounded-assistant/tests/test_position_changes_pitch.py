"""get_position_changes: role switch + per-90 before/after + the mini-pitch card payload (ES/EN). No network, no LLM."""
from __future__ import annotations

import pandas as pd
import pytest

from football_intelligence.ingestion.licensed.store import TABLES
from football_intelligence.player_involvement import per90_by_period
from football_intelligence.position_changes import FixtureMeta, role_switch
from fpl_grounded_assistant.atomic_tool_cards import _assoc_line, compose_position_changes_card
from fpl_grounded_assistant.generic_card import generic_card_to_dict
from fpl_grounded_assistant.position_changes_tool import run_position_changes
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import GET_POSITION_CHANGES_SCHEMA

MBE = 30


def _start(gw, role, side=None):
    return {"gameweek": gw, "player_status": "started",
            "slot": {"detailed_position": role, "side": side, "grid_slot": "4:1", "formation": "4-2-3-1"}}


# --- role_switch (pure) ----------------------------------------------------------------------------------------------

def test_a_sustained_change_is_found_with_the_gameweeks_of_each_role():
    recs = [_start(g, "Right Midfield", "right") for g in range(1, 6)] + [_start(g, "Attacker") for g in range(6, 11)]
    sw = role_switch(recs)
    assert sw["from"] == {"detailed_position": "Right Midfield", "side": "right", "line": "MID"}
    assert sw["to"] == {"detailed_position": "Attacker", "side": None, "line": "FWD"}
    assert sw["since_gameweek"] == 6 and sw["held_before"] == 5 and sw["starts_after"] == 5
    assert sw["gameweeks_old_role"] == [1, 2, 3, 4, 5] and sw["gameweeks_new_role"] == [6, 7, 8, 9, 10]
    assert sw["claim_status"] == "observed"
    assert "grid_slot" not in sw["from"] and "grid_slot" not in sw["to"]  # the provider grid flips; never drawn from


def test_bench_matches_do_not_break_the_run_and_are_not_counted():
    recs = ([_start(g, "Right Midfield", "right") for g in range(1, 5)] + [_start(5, "Attacker"),
            {"gameweek": 6, "player_status": "bench", "slot": None}] + [_start(g, "Attacker") for g in (7, 8)])
    sw = role_switch(recs)
    assert sw["since_gameweek"] == 5 and sw["gameweeks_new_role"] == [5, 7, 8]


def test_no_switch_when_a_side_is_short():
    two_after = [_start(g, "Right Midfield", "right") for g in range(1, 6)] + [_start(g, "Attacker") for g in (6, 7)]
    assert role_switch(two_after) is None
    two_before = ([_start(1, "Left Back", "left"), _start(2, "Right Midfield", "right"), _start(3, "Right Midfield", "right")]
                  + [_start(g, "Attacker") for g in range(4, 8)])
    assert role_switch(two_before) is None


def test_a_blip_is_not_a_switch():
    recs = [_start(g, "Right Midfield", "right") for g in range(1, 8)] + [_start(8, "Attacker")]
    assert role_switch(recs) is None


def test_side_only_counts_when_both_sides_are_known():
    lr = [_start(g, "Centre Back", "left") for g in range(1, 4)] + [_start(g, "Centre Back", "right") for g in range(4, 7)]
    assert role_switch(lr)["to"]["side"] == "right"
    unknown = [_start(g, "Centre Back", "left") for g in range(1, 4)] + [_start(g, "Centre Back", None) for g in range(4, 7)]
    assert role_switch(unknown) is None


# --- per90_by_period (pure) ------------------------------------------------------------------------------------------

def _stat(fid, minutes=90, **kw):
    row = {c: None for c in TABLES["player_match_stats"][0]}
    row.update({"element": MBE, "fixture_id": fid, "team": "MUN", "observed_at": f"2026-11-{fid:02d}T20:00:00Z",
                "starter": True, "minutes": minutes, "touches": 50, "key_passes": 2, "shots_on_target": 1, "shots": 4,
                "passes": 30, "accurate_passes": 27, "passes_final_third": 2, "interceptions": 1})
    row.update(kw)
    return row


def _frame(rows):
    return pd.DataFrame(rows, columns=list(TABLES["player_match_stats"][0])).astype(object)


FIX = {f: FixtureMeta(f, f"2026-11-{f:02d}T15:00:00Z", "MUN", "EVE") for f in range(1, 9)}


def test_per90_pools_each_period_with_the_30_minute_rule_and_the_line_metric():
    rows = [_stat(f, touches=40) for f in (1, 2, 3)] + [_stat(4, minutes=20, touches=99)] + [_stat(f, touches=60) for f in (5, 6)]
    out = per90_by_period(element=MBE, stats=_frame(rows), fixtures=FIX, periods={"before": [1, 2, 3, 4], "after": [5, 6]},
                          line="FWD")
    assert out["metrics"] == ["touches", "key_passes", "shots_on_target", "shots"]
    assert out["before"]["matches"] == 3 and out["before"]["touches"] == 40.0  # the 20-minute match is left out
    assert out["after"] == {"matches": 2, "minutes": 180, "touches": 60.0, "key_passes": 2.0, "shots_on_target": 1.0,
                            "shots": 4.0}
    assert out["min_minutes"] == 30 and out["claim_status"] == "observed"


def test_an_unknown_count_is_unknown_and_corrections_replace_the_first_read():
    rows = [_stat(1), _stat(2, key_passes=None), _stat(1, touches=10, observed_at="2026-11-30T00:00:00Z")]
    out = per90_by_period(element=MBE, stats=_frame(rows), fixtures=FIX, periods={"all": [1, 2]}, line="MID")
    assert out["all"]["key_passes"] is None            # never read as zero
    assert out["all"]["touches"] == 30.0               # (10 + 50) over 180 minutes: the correction of fixture 1 won
    assert out["metrics"][-1] == "passes_final_third"


def test_nothing_stored_is_none():
    assert per90_by_period(element=MBE, stats=_frame([]), fixtures=FIX, periods={"all": [1]}, line="DEF") is None


# --- end to end over a synthetic store, then the card ----------------------------------------------------------------

BOOTSTRAP = {"teams": [{"id": 1, "name": "Man Utd", "short_name": "MUN"}, {"id": 2, "name": "Everton", "short_name": "EVE"}],
             "elements": [{"id": MBE, "web_name": "Mbeumo", "first_name": "Bryan", "second_name": "Mbeumo",
                           "team": 1, "element_type": 3, "status": "a"}]}
FIXTURES = [{"id": f, "event": f, "kickoff_time": f"2026-11-{f:02d}T15:00:00Z", "team_h": 1, "team_a": 2} for f in range(1, 9)]


def _store(with_stats=True):
    snaps, slots = [], []
    for fid in range(1, 9):
        obs = f"2026-11-{fid:02d}T14:00:00Z"
        role, side = ("Right Midfield", "right") if fid <= 4 else ("Attacker", None)
        snaps.append({"fixture_id": fid, "team": "MUN", "observed_at": obs, "state": "finished", "confirmed": True,
                      "formation": "4-2-3-1", "n_starters": 1, "n_bench": 0})
        slots.append({"fixture_id": fid, "team": "MUN", "observed_at": obs, "element": MBE, "starter": True,
                      "detailed_position": role, "grid_slot": "4:1" if fid % 2 else "4:3", "side": side})
    frames = {"lineup_snapshots": snaps, "lineup_slots": slots, "sidelined": [],
              "squad_membership": [{"team": "MUN", "element": MBE, "jersey_number": 19, "observed_at": "2026-11-01T05:00:00Z"}]}
    tables = {n: pd.DataFrame(rows, columns=list(TABLES[n][0])).astype(object) for n, rows in frames.items()}
    if with_stats:
        tables["player_match_stats"] = _frame([_stat(f, touches=48 if f <= 4 else 41) for f in range(1, 9)])
    return tables


class _Handle:
    def __init__(self, tables):
        self._t = tables

    def manifest(self):
        return {"built_at": "2026-11-09T05:00:00Z"}

    def table(self, name):
        if name not in self._t:
            raise KeyError(name)
        return self._t[name]


@pytest.fixture(autouse=True)
def _no_cached_fixture_list(monkeypatch):
    from fpl_grounded_assistant import position_changes_tool

    monkeypatch.setitem(position_changes_tool._fixture_cache, "rows", None)


def _run(**kw):
    return run_position_changes({"player": "Mbeumo", "matches": 8}, dict(BOOTSTRAP), handle=_Handle(_store(**kw)),
                                fetch_fixtures=lambda: FIXTURES)


def test_the_tool_returns_the_switch_and_the_per90_of_each_role():
    out = _run()
    assert out["role_switch"]["since_gameweek"] == 5
    assert out["per90_change"]["before"]["touches"] == 48.0 and out["per90_change"]["after"]["touches"] == 41.0
    assert out["per90_change"]["metrics"][-1] == "shots"


def test_a_build_without_match_statistics_keeps_the_lineup_answer():
    out = _run(with_stats=False)
    assert out["status"] == "ok" and "role_switch" in out and "per90_change" not in out


@pytest.mark.parametrize("locale,hero,pill,frm,to,table,before,after", [
    ("es", "de delantero desde J5", "Antes: Banda derecha 4/4", "J1–J4 · Banda derecha", "J5–J8 · Delantero",
     "Desde el cambio, por 90", "Antes", "Después"),
    ("en", "as attacker since GW5", "Before: Right Midfield 4/4", "GW1–4 · Right Midfield", "GW5–8 · Attacker",
     "Since the change, per 90", "Before", "Since"),
])
def test_the_card_carries_the_pitch_in_the_request_language(locale, hero, pill, frm, to, table, before, after):
    card = compose_position_changes_card(_run(), locale)
    assert (card.hero.value, card.hero.label) == ("4/4", hero)
    assert pill not in [p.label for p in card.pills]  # the pitch says it: no "Before: ..." pill
    pp = card.position_pitch
    assert pp["kind"] == "switch" and pp["claim_status"] == "observed"
    assert pp["from"] == {"detailed_position": "Right Midfield", "side": "right", "line": "MID"}
    assert pp["to"] == {"detailed_position": "Attacker", "side": None, "line": "FWD"}
    assert (pp["labels"]["from"], pp["labels"]["to"], pp["labels"]["table"]) == (frm, to, table)
    assert (pp["labels"]["before"], pp["labels"]["after"]) == (before, after)
    assert pp["rows"][0] == {"metric": "touches", "label": "Toques" if locale == "es" else "Touches",
                             "before": 48.0, "after": 41.0}
    assert pp["note"] == ("4 y 4 partidos con 30+ min" if locale == "es" else "4 and 4 matches with 30+ min")
    assert "grid_slot" not in str(pp)


def test_the_hero_role_is_the_pitch_role():
    for locale in ("es", "en"):
        card = compose_position_changes_card(_run(), locale)
        assert card.position_pitch["labels"]["to"].split(" · ")[1].lower() in card.hero.label


def test_the_per_match_table_is_off_when_the_pitch_says_it_all():
    card = compose_position_changes_card(_run(), "es")
    assert card.rows == () and card.columns == ()


def test_the_per_match_table_comes_back_for_what_the_pitch_cannot_say_without_the_change_note():
    out = _run()
    out["matches"][5]["fpl_out"] = {"reason": "knee", "since": "2026-11-20", "claim_status": "observed", "source": "fpl"}
    for locale, changed in (("es", "Empezó en otra casilla"), ("en", "Started in a different slot")):
        card = compose_position_changes_card(out, locale)
        assert len(card.rows) == 8 and len(card.columns) == 4
        flat = " ".join(r[3] for r in card.rows)
        assert ("baja" in flat or "out" in flat) and changed not in flat


def test_associations_alone_do_not_bring_the_table_back_they_become_one_line_under_the_pitch_table():
    out = _run()
    out["matches"][5]["associations"] = [{"teammate": {"player_id": 99, "web_name": "Synthetic"}}]
    gw = out["matches"][5]["gameweek"]
    for locale, line in (("es", f"En J{gw} coincidió con la ausencia de Synthetic"),
                         ("en", f"In GW{gw}, coincided with the absence of Synthetic")):
        card = compose_position_changes_card(out, locale)
        assert card.rows == () and card.columns == ()
        assert card.position_pitch["associations"] == line


def _assoc_matches(*per_match, hidden=()):
    return [{"gameweek": gw, "associations": [{"teammate": {"web_name": n}} for n in names],
             **({"associations_more": hidden[i]} if i < len(hidden) else {})}
            for i, (gw, names) in enumerate(per_match)]


def test_the_association_line_dedupes_names_and_names_only_the_matches_that_have_them():
    ms = _assoc_matches((6, ["Aa", "Bb"]), (7, ["Aa", "Cc"]), (8, ["Bb"]), (9, []), (10, []))
    assert _assoc_line(ms, "es") == "En J6–J8 coincidió con ausencias de Aa, Bb y Cc"
    assert _assoc_line(ms, "en") == "In GW6–8, coincided with the absence of Aa, Bb and Cc"


def test_the_association_line_never_spans_a_match_without_one():
    ms = _assoc_matches((6, ["Aa"]), (7, []), (8, ["Bb"]))
    assert _assoc_line(ms, "es") == "En J6, J8 coincidió con ausencias de Aa y Bb"


def test_the_association_line_caps_the_names_and_is_honest_about_hidden_ones():
    ms = _assoc_matches((6, ["Aa", "Bb"]), (7, ["Cc", "Dd"]), (8, ["Ee"]))
    assert _assoc_line(ms, "es") == "En J6–J8 coincidió con ausencias de Aa, Bb, Cc y 2 más"
    assert _assoc_line(ms, "en") == "In GW6–8, coincided with the absence of Aa, Bb, Cc and 2 more"
    capped_hidden = _assoc_matches((6, ["Aa", "Bb"]), (7, ["Cc", "Dd"]), hidden=(0, 3))
    assert _assoc_line(capped_hidden, "es").endswith("Aa, Bb, Cc y al menos 1 más")
    only_hidden = _assoc_matches((6, ["Aa", "Bb"]), hidden=(4,))
    assert _assoc_line(only_hidden, "en") == "In GW6, coincided with the absence of Aa, Bb and others"
    assert _assoc_line(_assoc_matches((6, []), (7, [])), "es") is None


def test_a_card_without_a_pitch_keeps_the_associations_in_its_table():
    out = _run()
    out.pop("role_switch"); out.pop("fpl_position_gap", None); out.pop("per90_change", None)
    out["matches"][5]["associations"] = [{"teammate": {"player_id": 99, "web_name": "Synthetic"}}]
    card = compose_position_changes_card(out, "en")
    assert card.position_pitch is None and len(card.rows) == 8
    assert "Synthetic" in " ".join(r[3] for r in card.rows)


def _switch_with_gap_raw():
    ms = [{"gameweek": g, "player_status": "started", "lineup_status": "confirmed",
           "slot": {"detailed_position": "Attacker" if g > 2 else "Right Midfield", "side": "right" if g <= 2 else None}}
          for g in (1, 2, 3, 4)]
    return {"status": "ok", "player": {"web_name": "Synthetic", "player_id": 1}, "matches": ms,
            "role_switch": {"from": {"detailed_position": "Right Midfield", "side": "right", "line": "MID"},
                            "to": {"detailed_position": "Attacker", "side": None, "line": "FWD"}, "since_gameweek": 3,
                            "held_before": 2, "starts_before": 2, "starts_after": 2,
                            "gameweeks_old_role": [1, 2], "gameweeks_new_role": [3, 4]},
            "fpl_position_gap": {"fpl_position": "MID", "played_line": "FWD", "detailed_position": "Attacker", "side": None,
                                 "starts": 2, "of": 4}}


@pytest.mark.parametrize("locale,fpl", [("es", "FPL: MED"), ("en", "FPL: MID")])
def test_the_fpl_pill_stays_when_the_pitch_does_not_show_the_fpl_position(locale, fpl):
    card = compose_position_changes_card(_switch_with_gap_raw(), locale)
    labels = [p.label for p in card.pills]
    assert card.position_pitch["kind"] == "switch" and fpl in labels
    assert not any(l.startswith(("Antes", "Before", "Misma casilla", "Same slot")) for l in labels)


def test_the_payload_travels_on_the_wire_and_is_null_elsewhere():
    wire = generic_card_to_dict(compose_position_changes_card(_run(), "es"))
    assert wire["position_pitch"]["kind"] == "switch" and wire["involvement_compare"] is None


def test_the_text_says_the_switch_without_a_cause():
    for locale, line in (("es", "Desde la J5 empieza de delantero (4 de 4); antes, banda derecha (4 de 4)."),
                         ("en", "Since GW5 they have started as attacker (4 of 4); before, right midfield (4 of 4).")):
        text = render("get_position_changes", _run(), locale)
        assert line in text
        assert "porque" not in text and "because" not in text


def test_the_description_allows_observed_wording_and_forbids_a_cause():
    d = GET_POSITION_CHANGES_SCHEMA.description
    assert "role_switch (observed)" in d and "per90_change (observed" in d
    assert "never say the change caused them ('por el cambio', 'because of the move')" in d
    assert "since GW7 they have started as a forward" in d  # gender-neutral EN
