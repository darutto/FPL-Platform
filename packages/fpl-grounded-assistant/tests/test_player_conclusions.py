"""The player card's verdict: 0-3 structured conclusions, each rule at its threshold, priority and the cap.

Every player and number here is invented. No network, no provider, no LLM.
"""
from __future__ import annotations

from fpl_grounded_assistant import player_conclusions as pc
from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.player_conclusions import player_conclusions, top_pct
from fpl_grounded_assistant.renderer import render

GKP, DEF, MID, FWD = 1, 2, 3, 4


def _el(pid: int, etype: int, **kw):
    base = {
        "id": pid, "web_name": f"P{pid}", "first_name": "Syn", "second_name": f"Player{pid}", "team": 1,
        "element_type": etype, "status": "a", "minutes": 900, "starts": 3,
        "expected_goal_involvements_per_90": 0.0, "defensive_contribution_per_90": 0.0,
        "clean_sheets_per_90": 0.0,
        "penalties_order": None, "direct_freekicks_order": None, "corners_and_indirect_freekicks_order": None,
    }
    base.update(kw)
    return base


def _pool(etype: int, field: str, start_id: int = 1000, n: int = 20):
    """n pool players with values 0.01..0.20 on *field*: rank k of 20 sits at percentile 5*(k-1)."""
    return [_el(start_id + i, etype, **{field: round(0.01 * (i + 1), 2)}) for i in range(n)]


def _bootstrap(elements, finished: int = 10):
    return {
        "teams": [{"id": 1, "name": "Synth FC", "short_name": "SYN"}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"}, {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"}, {"id": 4, "singular_name_short": "FWD"},
        ],
        "events": [{"id": i, "finished": i <= finished} for i in range(1, 39)],
        "elements": elements,
    }


# -- points source ----------------------------------------------------------

def test_mid_attack_fires_at_80th_percentile_and_not_below():
    pool = _pool(MID, "expected_goal_involvements_per_90")
    # 0.17 beats 16 of 21 (incl. himself, not strictly below) -> 16/21 = 76.2 -> no.
    below = _el(1, MID, expected_goal_involvements_per_90=0.165)
    # 0.175 beats 17 of 21 -> 80.95 -> fires, top 19 -> rounded to 20.
    at = _el(2, MID, expected_goal_involvements_per_90=0.175)
    assert player_conclusions(below, _bootstrap(pool + [below])) == []
    out = player_conclusions(at, _bootstrap(pool + [at]))
    assert out == [{
        "key": "points_attack", "params": {"position": "MID"},
        "evidence": {"metric": "xgi_per_90", "top_pct": 20, "position": "MID"},
    }]


def test_def_attack_fwd_attack_and_gkp_clean_sheets():
    d = _el(1, DEF, expected_goal_involvements_per_90=0.5)
    f = _el(2, FWD, expected_goal_involvements_per_90=0.5)
    g = _el(3, GKP, clean_sheets_per_90=0.5)
    boot = _bootstrap(
        _pool(DEF, "expected_goal_involvements_per_90", 1000) + _pool(FWD, "expected_goal_involvements_per_90", 2000)
        + _pool(GKP, "clean_sheets_per_90", 3000) + [d, f, g]
    )
    assert player_conclusions(d, boot)[0]["key"] == "points_attack"
    assert player_conclusions(d, boot)[0]["params"] == {"position": "DEF"}
    assert player_conclusions(f, boot)[0]["evidence"] == {"metric": "xgi_per_90", "top_pct": 5, "position": "FWD"}
    assert player_conclusions(g, boot)[0]["key"] == "points_clean_sheets"


def test_fwd_has_no_defence_line_and_gkp_no_attack_line():
    f = _el(1, FWD, defensive_contribution_per_90=9.0)
    g = _el(2, GKP, expected_goal_involvements_per_90=0.9)
    boot = _bootstrap(_pool(FWD, "defensive_contribution_per_90", 1000) + _pool(GKP, "expected_goal_involvements_per_90", 2000) + [f, g])
    assert player_conclusions(f, boot) == []
    assert player_conclusions(g, boot) == []


def test_when_two_points_lines_fire_only_the_higher_percentile_shows():
    # DEF: attack at ~p81, defence at the top of the pool -> only defence.
    pool = [
        _el(1000 + i, DEF, expected_goal_involvements_per_90=0.01 * (i + 1), defensive_contribution_per_90=0.1 * (i + 1))
        for i in range(20)
    ]
    p = _el(1, DEF, expected_goal_involvements_per_90=0.175, defensive_contribution_per_90=9.0)
    out = player_conclusions(p, _bootstrap(pool + [p]))
    assert [c["key"] for c in out] == ["points_defence"]
    assert out[0]["evidence"] == {"metric": "dc_per_90", "top_pct": 5, "position": "DEF"}


def test_pool_and_player_need_450_minutes():
    pool = _pool(MID, "expected_goal_involvements_per_90")
    short = _el(1, MID, minutes=449, expected_goal_involvements_per_90=9.0)
    assert player_conclusions(short, _bootstrap(pool + [short])) == []
    # Cameo players with huge per-90s don't enter the pool: he still tops it.
    cameos = [_el(3000 + i, MID, minutes=30, expected_goal_involvements_per_90=5.0) for i in range(50)]
    p = _el(2, MID, expected_goal_involvements_per_90=0.5)
    assert player_conclusions(p, _bootstrap(pool + cameos + [p]))[0]["evidence"]["top_pct"] == 5


def test_top_pct_rounds_to_5_and_never_below_5():
    assert top_pct(99.9) == 5
    assert top_pct(92.0) == 10
    assert top_pct(80.0) == 20
    assert top_pct(87.6) == 10


# -- set pieces ---------------------------------------------------------------

def test_set_pieces_names_only_first_choice_pieces():
    p = _el(1, MID, penalties_order=1, direct_freekicks_order=2, corners_and_indirect_freekicks_order=1)
    out = player_conclusions(p, _bootstrap([p]))
    assert out == [{"key": "set_pieces", "params": {"pieces": ["penalties", "corners"]}, "evidence": None}]
    all3 = _el(2, MID, penalties_order=1, direct_freekicks_order=1, corners_and_indirect_freekicks_order=1)
    assert player_conclusions(all3, _bootstrap([all3]))[0]["params"]["pieces"] == ["penalties", "free_kicks", "corners"]
    second = _el(3, MID, penalties_order=2)
    assert player_conclusions(second, _bootstrap([second])) == []


# -- starts -------------------------------------------------------------------

def test_starts_fires_at_80_percent_of_finished_gameweeks():
    eight = _el(1, MID, starts=8)
    seven = _el(2, MID, starts=7)
    assert player_conclusions(eight, _bootstrap([eight], finished=10)) == [
        {"key": "starts", "params": {"starts": 8, "games": 10}, "evidence": None}
    ]
    assert player_conclusions(seven, _bootstrap([seven], finished=10)) == []


def test_starts_suppressed_when_not_available():
    for status in ("d", "i", "s", "u"):
        p = _el(1, MID, starts=10, status=status)
        assert player_conclusions(p, _bootstrap([p], finished=10)) == [], status


def test_starts_needs_enough_finished_gameweeks_and_is_capped():
    p = _el(1, MID, starts=4)
    assert player_conclusions(p, _bootstrap([p], finished=pc.MIN_FINISHED_GWS - 1)) == []
    dgw = _el(2, MID, starts=11)
    assert player_conclusions(dgw, _bootstrap([dgw], finished=10))[0]["params"] == {"starts": 10, "games": 10}


# -- zonal --------------------------------------------------------------------

def _zonal(*statuses):
    return {"fixtures": [
        {"gameweek": 11 + i, "opponent_short": opp, "status": st}
        for i, (opp, st) in enumerate(statuses)
    ]}


def test_zonal_lists_favourable_opponents_only():
    p = _el(1, MID)
    z = _zonal(("AAA", "favorable"), ("BBB", "neutral"), ("CCC", "favorable"))
    assert player_conclusions(p, _bootstrap([p]), z) == [
        {"key": "zonal", "params": {"opponents": ["AAA", "CCC"]}, "evidence": None}
    ]
    assert player_conclusions(p, _bootstrap([p]), _zonal(("AAA", "neutral"), ("BBB", "no_data"))) == []
    assert player_conclusions(p, _bootstrap([p]), None) == []


# -- priority + cap -----------------------------------------------------------

def test_cap_3_in_priority_order():
    pool = _pool(MID, "expected_goal_involvements_per_90")
    p = _el(1, MID, expected_goal_involvements_per_90=0.9, penalties_order=1, starts=10)
    keys = [c["key"] for c in player_conclusions(p, _bootstrap(pool + [p]), _zonal(("AAA", "favorable")))]
    assert keys == ["points_attack", "set_pieces", "zonal"]  # starts dropped by the cap
    q = _el(2, MID, penalties_order=1, starts=10)
    keys = [c["key"] for c in player_conclusions(q, _bootstrap(pool + [q]), _zonal(("AAA", "favorable")))]
    assert keys == ["set_pieces", "zonal", "starts"]


def test_malformed_values_drop_only_that_line():
    p = _el(1, MID, expected_goal_involvements_per_90="n/a", penalties_order=1, starts=None)
    assert [c["key"] for c in player_conclusions(p, _bootstrap([p]))] == ["set_pieces"]


# -- snapshot payload + render ------------------------------------------------

def test_snapshot_payload_carries_conclusions_and_renders_no_text():
    pool = _pool(MID, "expected_goal_involvements_per_90")
    p = _el(1, MID, web_name="Synthguy", second_name="Synthguy", expected_goal_involvements_per_90=0.9)
    raw = get_player_snapshot("Synthguy", _bootstrap(pool + [p]))
    assert raw["status"] == "ok"
    assert raw["player"]["conclusions"][0]["key"] == "points_attack"
    meta = _extract_player_snapshot_meta(raw)
    assert meta is not None and meta.conclusions[0].key == "points_attack"
    assert meta.conclusions[0].evidence == {"metric": "xgi_per_90", "top_pct": 5, "position": "MID"}
    # The old dump is gone: the card + the conclusions carry it now.
    assert render("get_player_snapshot", raw) == ""
    assert render("get_player_snapshot", raw, locale="en") == ""


def test_snapshot_payload_has_no_conclusions_key_when_nothing_fires():
    p = _el(1, MID, web_name="Quietguy", second_name="Quietguy", starts=1)
    raw = get_player_snapshot("Quietguy", _bootstrap([p]))
    assert raw["status"] == "ok"
    assert "conclusions" not in raw["player"]
    meta = _extract_player_snapshot_meta(raw)
    assert meta is not None and meta.conclusions == ()


def test_meta_drops_unknown_or_malformed_conclusions():
    p = _el(1, MID, web_name="Oddguy", second_name="Oddguy")
    raw = get_player_snapshot("Oddguy", _bootstrap([p]))
    raw["player"]["conclusions"] = [
        {"key": "made_up", "params": {}},
        {"key": "starts", "params": "nope"},
        {"key": "set_pieces", "params": {"pieces": ["penalties"]}, "evidence": None},
    ]
    meta = _extract_player_snapshot_meta(raw)
    assert [c.key for c in meta.conclusions] == ["set_pieces"]


def test_not_found_and_ambiguous_text_unchanged():
    a = _el(1, MID, web_name="Twin", second_name="Twin")
    b = _el(2, MID, web_name="Twin", second_name="Twin")
    boot = _bootstrap([a, b])
    amb = get_player_snapshot("Twin", boot)
    assert amb["status"] == "ambiguous"
    assert render("get_player_snapshot", amb).startswith("Múltiples jugadores coinciden con 'twin'")
    nf = get_player_snapshot("Nobodyatall", boot)
    assert render("get_player_snapshot", nf) == "No player matching 'nobodyatall'."
