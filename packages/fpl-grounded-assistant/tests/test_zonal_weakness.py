"""
Tests for T2a — zonal_weakness engine.

Covers the locked zone grid boundaries, penalty exclusion via the shared
fpl_tactical constant, relative-to-baseline math against hand-computed
deltas, the attacker-frame → defender-frame orientation flip in the Spanish
verdict, not_found / missing_context statuses, and the opportunity matcher.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os

import pandas as pd

# Load zonal_weakness directly from its file, bypassing
# fpl_grounded_assistant/__init__.py (which pulls the dispatcher/harness graph
# and a stale captain-engine path) — repo test convention.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_MOD_PATH = _os.path.join(
    _os.path.dirname(_HERE), "fpl_grounded_assistant", "zonal_weakness.py"
)
_spec = _ilu.spec_from_file_location("zonal_weakness", _MOD_PATH)
zonal_weakness = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(zonal_weakness)

zone_of = zonal_weakness.zone_of
compute_team_zone_profiles = zonal_weakness.compute_team_zone_profiles
compute_league_baseline = zonal_weakness.compute_league_baseline
compute_player_zone_shares = zonal_weakness.compute_player_zone_shares
get_zonal_weakness = zonal_weakness.get_zonal_weakness
get_zonal_opportunity = zonal_weakness.get_zonal_opportunity
PENALTY_SITUATION = zonal_weakness.PENALTY_SITUATION


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _row(
    conceding, shooting, x, y, xg,
    *, match_id=1, player="Someone", situation="Open Play", result="Saved Shot",
    date="2025-09-01T15:00:00",
):
    return {
        "season": "2025-2026", "match_id": match_id, "date": date,
        "shooting_team": shooting, "conceding_team": conceding,
        "player": player, "is_home_shot": True, "minute": 10,
        "x": x, "y": y, "xg": xg, "situation": situation,
        "shot_type": "Right Foot", "result": result,
    }


def weakness_store() -> pd.DataFrame:
    """4 teams, hand-computed profile.

    in-box/left xGA per game:  Palace 0.50/2 games = 0.25 · Villa 0.10 ·
    Boro 0.10 · Wolves 0.10  → baseline 0.1375, Palace delta +0.1125.
    in-box/central: 1.00/game for everyone → baseline 1.0, all deltas 0.
    edge-of-box/right: Villa 0.20, rest 0 → baseline 0.05, Villa +0.15.
    Palace also concedes one penalty (xG 0.7611) — context only.
    """
    rows = [
        # --- match 1: Palace concedes (Villa shoots) + Villa concedes (Palace shoots)
        _row("Palace", "Villa", 0.90, 0.20, 0.30, match_id=1, result="Goal"),
        _row("Palace", "Villa", 0.85, 0.30, 0.20, match_id=1),
        _row("Palace", "Villa", 0.90, 0.50, 1.00, match_id=1),           # central
        _row("Palace", "Villa", 0.885, 0.50, 0.7611, match_id=1,
             situation=PENALTY_SITUATION, result="Goal"),                # penalty
        _row("Villa", "Palace", 0.86, 0.10, 0.10, match_id=1),           # in-box/left
        _row("Villa", "Palace", 0.90, 0.50, 1.00, match_id=1),           # central
        _row("Villa", "Palace", 0.75, 0.70, 0.20, match_id=1),           # edge/right
        # --- match 2: Palace concedes again (Boro shoots) + Boro concedes
        _row("Palace", "Boro", 0.90, 0.50, 1.00, match_id=2),            # central
        _row("Boro", "Palace", 0.90, 0.35, 0.10, match_id=2),            # in-box/left
        _row("Boro", "Palace", 0.90, 0.50, 1.00, match_id=2),            # central
        _row("Boro", "Palace", 0.50, 0.50, 0.30, match_id=2),            # long-range
        # --- match 3: Wolves concede
        _row("Wolves", "Boro", 0.88, 0.20, 0.10, match_id=3),            # in-box/left
        _row("Wolves", "Boro", 0.90, 0.50, 1.00, match_id=3),            # central
    ]
    return pd.DataFrame(rows)


def opportunity_store() -> pd.DataFrame:
    """Palace made very weak in in-box/left; three profiled players.

    - "Left Poacher" (Wolves): 10 in-box/left shots → operates there.
    - "Palace Own" (Palace): 10 in-box/left shots → own team, excluded.
    - "Long Ranger" (Boro): 10 long-range shots → no zone share.
    """
    rows = []
    for i in range(10):
        rows.append(_row("Palace", "Wolves", 0.90, 0.20, 0.10,
                         match_id=101, player="Left Poacher"))
        rows.append(_row("Villa", "Palace", 0.90, 0.20, 0.10,
                         match_id=102, player="Palace Own"))
        rows.append(_row("Boro", "Wolves", 0.50, 0.50, 0.05,
                         match_id=103, player="Long Ranger"))
    # one light in-box/left concession each for the other three teams
    rows.append(_row("Villa", "Boro", 0.90, 0.20, 0.10, match_id=104))
    rows.append(_row("Boro", "Villa", 0.90, 0.20, 0.10, match_id=105))
    rows.append(_row("Wolves", "Villa", 0.90, 0.20, 0.10, match_id=106))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Zone grid (locked thresholds)
# ---------------------------------------------------------------------------

def test_zone_in_box_boundary():
    assert zone_of(0.84, 0.5) == "in-box / central"
    assert zone_of(0.99, 0.5) == "in-box / central"


def test_zone_edge_of_box_band():
    assert zone_of(0.70, 0.5) == "edge-of-box / central"
    assert zone_of(0.839, 0.5) == "edge-of-box / central"


def test_zone_long_range_ignored():
    assert zone_of(0.699, 0.5) is None
    assert zone_of(0.20, 0.1) is None


def test_zone_lateral_boundaries():
    assert zone_of(0.90, 0.359) == "in-box / left"
    assert zone_of(0.90, 0.36) == "in-box / central"   # boundary is central
    assert zone_of(0.90, 0.64) == "in-box / central"   # boundary is central
    assert zone_of(0.90, 0.641) == "in-box / right"


# ---------------------------------------------------------------------------
# Profiles + baseline (hand-computed)
# ---------------------------------------------------------------------------

def test_profiles_count_games_per_team():
    profiles = compute_team_zone_profiles(weakness_store())
    assert profiles["Palace"]["in-box / left"]["games"] == 2
    assert profiles["Villa"]["in-box / left"]["games"] == 1


def test_profiles_hand_computed_xga():
    profiles = compute_team_zone_profiles(weakness_store())
    assert profiles["Palace"]["in-box / left"]["xga"] == pytest_approx(0.5)
    assert profiles["Palace"]["in-box / left"]["shots"] == 2
    assert profiles["Palace"]["in-box / left"]["goals"] == 1
    assert profiles["Villa"]["edge-of-box / right"]["xga"] == pytest_approx(0.2)


def test_profiles_exclude_penalties_from_zones():
    profiles = compute_team_zone_profiles(weakness_store())
    # Palace's central xGA is 2×1.0 — the 0.7611 penalty must NOT be in it
    assert profiles["Palace"]["in-box / central"]["xga"] == pytest_approx(2.0)


def test_profiles_ignore_long_range():
    profiles = compute_team_zone_profiles(weakness_store())
    total_boro = sum(cell["xga"] for cell in profiles["Boro"].values())
    assert total_boro == pytest_approx(1.1)  # 0.30 long-range shot excluded


def test_league_baseline_hand_computed():
    profiles = compute_team_zone_profiles(weakness_store())
    baseline = compute_league_baseline(profiles)
    assert baseline["in-box / left"] == pytest_approx(0.1375)
    assert baseline["in-box / central"] == pytest_approx(1.0)
    assert baseline["edge-of-box / right"] == pytest_approx(0.05)


# ---------------------------------------------------------------------------
# get_zonal_weakness
# ---------------------------------------------------------------------------

def test_weakness_delta_and_rank():
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["status"] == "ok"
    left = next(z for z in out["zones"] if z["zone"] == "in-box / left")
    assert left["xga_per_game"] == pytest_approx(0.25)
    assert left["league_avg"] == pytest_approx(0.1375)
    assert left["delta_vs_avg"] == pytest_approx(0.1125)
    assert left["rank"] == 1


def test_weakness_relative_signal_beats_raw_totals():
    # Central dominates Palace's RAW xGA (1.0/game vs 0.25/game) but its
    # delta is 0 — the relative signal must rank in-box/left first.
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["weakest_zones"][0]["zone"] == "in-box / left"
    assert out["weakest_zones"][0]["delta_vs_avg"] > 0


def test_weakness_penalty_context_reported_separately():
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["penalty_context"]["penalty_xga"] == pytest_approx(0.7611)
    # engine rounds payload floats to 4 decimals
    assert out["penalty_context"]["penalty_xga_per_game"] == pytest_approx(0.7611 / 2, abs_=1e-4)


def test_weakness_verdict_orientation_flip():
    # Palace leaks in the attacker's-LEFT band → that is Palace's own RIGHT
    # side, and the Spanish verdict must say so.
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert "su costado derecho" in out["verdict"]
    assert "dentro del área" in out["verdict"]
    assert "izquierdo" not in out["verdict"]


def test_weakness_verdict_no_buy_sell_language():
    for team in ("Palace", "Villa", "Wolves"):
        verdict = get_zonal_weakness(team, store=weakness_store())["verdict"].lower()
        for banned in ("ficha", "vende", "compra", "transfer", "capitán"):
            assert banned not in verdict


def test_weakness_verdict_when_not_above_average():
    # Wolves are below/at average everywhere → verdict says exactly that.
    out = get_zonal_weakness("Wolves", store=weakness_store())
    assert all(z["delta_vs_avg"] <= 0 for z in out["weakest_zones"])
    assert "no concede por encima de la media" in out["verdict"]


def test_weakness_team_match_is_case_insensitive():
    out = get_zonal_weakness("  palace ", store=weakness_store())
    assert out["status"] == "ok"
    assert out["team"] == "Palace"


def test_weakness_not_found():
    out = get_zonal_weakness("Real Madrid", store=weakness_store())
    assert out["status"] == "not_found"
    assert out["team"] == "Real Madrid"


def test_weakness_missing_context_empty_store():
    assert get_zonal_weakness("Palace", store=pd.DataFrame())["status"] == "missing_context"


def test_weakness_missing_context_absent_path(tmp_path):
    out = get_zonal_weakness("Palace", store=tmp_path / "nope.parquet")
    assert out["status"] == "missing_context"


def test_weakness_reads_parquet_from_injected_path(tmp_path):
    path = tmp_path / "understat_shots.parquet"
    weakness_store().to_parquet(path, index=False)
    out = get_zonal_weakness("Palace", store=path)
    assert out["status"] == "ok"
    assert out["weakest_zones"][0]["zone"] == "in-box / left"


# ---------------------------------------------------------------------------
# Opportunity matcher
# ---------------------------------------------------------------------------

def test_player_zone_shares_thresholds():
    shares = compute_player_zone_shares(opportunity_store())
    assert shares["Left Poacher"]["zone_share"]["in-box / left"] == pytest_approx(1.0)
    # Long Ranger has 10 shots but zero zoned xG → all shares 0
    assert all(v == 0 for v in shares["Long Ranger"]["zone_share"].values())


def test_opportunity_returns_matching_player():
    out = get_zonal_opportunity("Palace", store=opportunity_store())
    assert out["status"] == "ok"
    zones = {o["zone"]: o for o in out["opportunities"]}
    assert "in-box / left" in zones
    assert "Left Poacher" in zones["in-box / left"]["players"]
    assert zones["in-box / left"]["delta_vs_avg"] > 0


def test_opportunity_excludes_own_team_and_unmatched_players():
    out = get_zonal_opportunity("Palace", store=opportunity_store())
    players = [p for o in out["opportunities"] for p in o["players"]]
    assert "Palace Own" not in players   # plays for Palace itself
    assert "Long Ranger" not in players  # no zone concentration


def test_opportunity_only_positive_delta_zones():
    out = get_zonal_opportunity("Palace", store=opportunity_store())
    assert all(o["delta_vs_avg"] > 0 for o in out["opportunities"])


def test_opportunity_statuses_propagate():
    assert get_zonal_opportunity("Nadie FC", store=opportunity_store())["status"] == "not_found"
    assert get_zonal_opportunity("Palace", store=pd.DataFrame())["status"] == "missing_context"


# ---------------------------------------------------------------------------
# Player zonal outlook (T-player)
# ---------------------------------------------------------------------------

get_player_zonal_outlook = zonal_weakness.get_player_zonal_outlook


def test_outlook_favorable_when_zones_intersect():
    # Left Poacher (Wolves) concentrates 100% of xG in in-box/left; Palace
    # concedes above average exactly there → favorable.
    out = get_player_zonal_outlook(
        "Left Poacher",
        fixtures_for_team=lambda t: [
            {"gameweek": 24, "opponent": "Palace", "is_home": True},
        ],
        store=opportunity_store(),
    )
    assert out["status"] == "ok"
    assert out["team"] == "Wolves"
    entry = out["outlook"][0]
    assert entry["opponent"] == "Palace"
    assert entry["status"] == "favorable"
    match = entry["matches"][0]
    assert match["zone"] == "in-box / left"
    assert match["delta_vs_avg"] > 0
    assert match["player_share"] == pytest_approx(1.0)
    assert "J24 (Palace)" in out["verdict"]


def test_outlook_neutral_and_no_data_entries():
    out = get_player_zonal_outlook(
        "Left Poacher",
        fixtures_for_team=lambda t: [
            {"gameweek": 25, "opponent": "Boro", "is_home": False},
            {"gameweek": 26, "opponent": "Ghost Town FC", "is_home": True},
        ],
        store=opportunity_store(),
    )
    assert out["status"] == "ok"
    statuses = {e["gameweek"]: e["status"] for e in out["outlook"]}
    assert statuses[25] == "neutral"   # Boro concedes below avg in the player's zone
    assert statuses[26] == "no_data"   # unknown team in the store
    assert "Sin cruce zonal destacado" in out["verdict"]


def test_outlook_player_zones_reported():
    out = get_player_zonal_outlook(
        "Left Poacher",
        fixtures_for_team=lambda t: [{"gameweek": 1, "opponent": "Palace", "is_home": True}],
        store=opportunity_store(),
    )
    assert out["player_zones"][0]["zone"] == "in-box / left"
    assert out["player_zones"][0]["share"] == pytest_approx(1.0)


def test_outlook_player_not_found():
    out = get_player_zonal_outlook(
        "Nobody", fixtures_for_team=lambda t: [], store=opportunity_store()
    )
    assert out["status"] == "not_found"


def test_outlook_player_ambiguous():
    # "o" substring-matches several profiled players
    out = get_player_zonal_outlook(
        "o", fixtures_for_team=lambda t: [], store=opportunity_store()
    )
    assert out["status"] == "ambiguous"
    assert 2 <= len(out["candidates"]) <= 5


def test_outlook_missing_context_paths():
    out = get_player_zonal_outlook(
        "Left Poacher", fixtures_for_team=lambda t: [], store=pd.DataFrame()
    )
    assert out["status"] == "missing_context"
    out2 = get_player_zonal_outlook(
        "Left Poacher", fixtures_for_team=lambda t: [], store=opportunity_store()
    )
    assert out2["status"] == "missing_context"  # no upcoming fixtures


def test_outlook_verdict_no_buy_sell():
    out = get_player_zonal_outlook(
        "Left Poacher",
        fixtures_for_team=lambda t: [{"gameweek": 1, "opponent": "Palace", "is_home": True}],
        store=opportunity_store(),
    )
    verdict = out["verdict"].lower()
    for banned in ("ficha", "vende", "compra", "transfer", "capitán"):
        assert banned not in verdict


# ---------------------------------------------------------------------------
# Shared-constant contract
# ---------------------------------------------------------------------------

def test_penalty_constant_is_shared_with_fpl_tactical():
    import importlib
    fpl_tactical = importlib.import_module("fpl_tactical")
    assert PENALTY_SITUATION == fpl_tactical.PENALTY_SITUATION
    assert PENALTY_SITUATION is not None


# ---------------------------------------------------------------------------
# tiny approx helper (avoid importing pytest.approx everywhere)
# ---------------------------------------------------------------------------

def pytest_approx(value, rel=1e-9, abs_=1e-9):
    import pytest
    return pytest.approx(value, rel=rel, abs=abs_)
