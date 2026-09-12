"""
Tests for T2a — zonal_weakness engine.

Covers the locked zone grid boundaries, penalty exclusion via the shared
fpl_tactical constant, relative-to-baseline math against hand-computed
deltas, the unified attacker/opportunity frame in the Spanish
verdict, not_found / missing_context statuses, and the opportunity matcher.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os

import pandas as pd
import pytest

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

    in-box/right xGA per game:  Palace 0.50/2 games = 0.25 · Villa 0.10 ·
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
        _row("Villa", "Palace", 0.86, 0.10, 0.10, match_id=1),           # in-box/right
        _row("Villa", "Palace", 0.90, 0.50, 1.00, match_id=1),           # central
        _row("Villa", "Palace", 0.75, 0.70, 0.20, match_id=1),           # edge/right
        # --- match 2: Palace concedes again (Boro shoots) + Boro concedes
        _row("Palace", "Boro", 0.90, 0.50, 1.00, match_id=2),            # central
        _row("Boro", "Palace", 0.90, 0.35, 0.10, match_id=2),            # in-box/right
        _row("Boro", "Palace", 0.90, 0.50, 1.00, match_id=2),            # central
        _row("Boro", "Palace", 0.50, 0.50, 0.30, match_id=2),            # long-range
        # --- match 3: Wolves concede
        _row("Wolves", "Boro", 0.88, 0.20, 0.10, match_id=3),            # in-box/right
        _row("Wolves", "Boro", 0.90, 0.50, 1.00, match_id=3),            # central
    ]
    return pd.DataFrame(rows)


def opportunity_store() -> pd.DataFrame:
    """Palace made very weak in in-box/right; three profiled players.

    - "Right Poacher" (Wolves): 10 in-box/right shots → operates there.
    - "Palace Own" (Palace): 10 in-box/right shots → own team, excluded.
    - "Long Ranger" (Boro): 10 long-range shots → no zone share.
    """
    rows = []
    for i in range(10):
        rows.append(_row("Palace", "Wolves", 0.90, 0.20, 0.10,
                         match_id=101, player="Right Poacher"))
        rows.append(_row("Villa", "Palace", 0.90, 0.20, 0.10,
                         match_id=102, player="Palace Own"))
        rows.append(_row("Boro", "Wolves", 0.50, 0.50, 0.05,
                         match_id=103, player="Long Ranger"))
    # one light in-box/right concession each for the other three teams
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
    assert zone_of(0.90, 0.359) == "in-box / right"
    assert zone_of(0.90, 0.36) == "in-box / central"   # boundary is central
    assert zone_of(0.90, 0.64) == "in-box / central"   # boundary is central
    assert zone_of(0.90, 0.641) == "in-box / left"


# ---------------------------------------------------------------------------
# Flank-mirror regression (THE orientation guard — do not weaken)
#
# Understat's y axis grows toward the attacker's LEFT: the low band
# (y < 0.36) is the attacker's RIGHT flank. The original T2a code had this
# mirrored, which surfaced right-wingers under "left" zones on the card.
# These tests pin the corrected handedness so it cannot silently re-invert.
# ---------------------------------------------------------------------------

def test_flank_handedness_synthetic():
    # low y = attacker's RIGHT flank; high y = attacker's LEFT.
    assert zone_of(0.90, 0.20) == "in-box / right"
    assert zone_of(0.90, 0.80) == "in-box / left"
    assert zone_of(0.75, 0.10) == "edge-of-box / right"
    assert zone_of(0.75, 0.90) == "edge-of-box / left"


_REAL_STORE = (
    zonal_weakness.shots_parquet_path(zonal_weakness.CURRENT_SEASON)
    if getattr(zonal_weakness, "_FPL_TACTICAL_AVAILABLE", False)
    else None
)


@pytest.mark.skipif(
    _REAL_STORE is None or not _REAL_STORE.exists(),
    reason="owned tactical store not present on this machine",
)
def test_known_flank_players_land_on_their_real_side():
    """Known-flank players from the REAL store pin the orientation.

    Right-siders (Saka, Salah, Bowen) must concentrate their in-box lateral
    xG on the RIGHT band; left-winger Mitoma on the LEFT. Verified
    2026-07-09: R≈0.25–0.28 vs L≤0.08 for the right-siders; Mitoma
    L=0.31 vs R=0.00. If zone_of re-inverts, this fails loudly.
    """
    shares = compute_player_zone_shares(pd.read_parquet(_REAL_STORE))

    def zone_share(fragment: str) -> dict:
        matches = [p for p in shares if fragment.lower() in p.lower()]
        assert matches, f"player {fragment!r} not found in the tactical store"
        return shares[matches[0]]["zone_share"]

    for right_sider in ("Bukayo Saka", "Mohamed Salah", "Jarrod Bowen"):
        zs = zone_share(right_sider)
        assert zs["in-box / right"] > zs["in-box / left"], (
            f"{right_sider} should shoot from the RIGHT band — orientation inverted?"
        )
    zs = zone_share("Mitoma")
    assert zs["in-box / left"] > zs["in-box / right"], (
        "Mitoma should shoot from the LEFT band — orientation inverted?"
    )


# ---------------------------------------------------------------------------
# Profiles + baseline (hand-computed)
# ---------------------------------------------------------------------------

def test_profiles_count_games_per_team():
    profiles = compute_team_zone_profiles(weakness_store())
    assert profiles["Palace"]["in-box / right"]["games"] == 2
    assert profiles["Villa"]["in-box / right"]["games"] == 1


def test_profiles_hand_computed_xga():
    profiles = compute_team_zone_profiles(weakness_store())
    assert profiles["Palace"]["in-box / right"]["xga"] == pytest_approx(0.5)
    assert profiles["Palace"]["in-box / right"]["shots"] == 2
    assert profiles["Palace"]["in-box / right"]["goals"] == 1
    assert profiles["Villa"]["edge-of-box / left"]["xga"] == pytest_approx(0.2)


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
    assert baseline["in-box / right"] == pytest_approx(0.1375)
    assert baseline["in-box / central"] == pytest_approx(1.0)
    assert baseline["edge-of-box / left"] == pytest_approx(0.05)


# ---------------------------------------------------------------------------
# get_zonal_weakness
# ---------------------------------------------------------------------------

def test_weakness_delta_and_rank():
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["status"] == "ok"
    right = next(z for z in out["zones"] if z["zone"] == "in-box / right")
    assert right["xga_per_game"] == pytest_approx(0.25)
    assert right["league_avg"] == pytest_approx(0.1375)
    assert right["delta_vs_avg"] == pytest_approx(0.1125)
    assert right["rank"] == 1


def test_weakness_relative_signal_beats_raw_totals():
    # Central dominates Palace's RAW xGA (1.0/game vs 0.25/game) but its
    # delta is 0 — the relative signal must rank in-box/right first.
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["weakest_zones"][0]["zone"] == "in-box / right"
    assert out["weakest_zones"][0]["delta_vs_avg"] > 0


def test_weakness_penalty_context_reported_separately():
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["penalty_context"]["penalty_xga"] == pytest_approx(0.7611)
    # engine rounds payload floats to 4 decimals
    assert out["penalty_context"]["penalty_xga_per_game"] == pytest_approx(0.7611 / 2, abs_=1e-4)


def test_weakness_verdict_attacker_frame():
    # Flank-mirror fix: Palace leaks in the LOW y band (y < 0.36), which is
    # the attacker's RIGHT flank. The verdict speaks the attacker frame —
    # "ataca por la derecha" — with no defender-side flip anywhere.
    out = get_zonal_weakness("Palace", store=weakness_store())
    assert out["verdict"].startswith("Ataca a Palace")
    assert "por la derecha" in out["verdict"]
    assert "dentro del área" in out["verdict"]
    assert "izquierda" not in out["verdict"]
    assert "costado" not in out["verdict"]  # old defender-frame copy is gone
    assert "débil" not in out["verdict"].lower()  # opportunity-positive


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
    assert out["weakest_zones"][0]["zone"] == "in-box / right"


# ---------------------------------------------------------------------------
# Opportunity matcher
# ---------------------------------------------------------------------------

def test_player_zone_shares_thresholds():
    shares = compute_player_zone_shares(opportunity_store())
    assert shares["Right Poacher"]["zone_share"]["in-box / right"] == pytest_approx(1.0)
    # Long Ranger has 10 shots but zero zoned xG → all shares 0
    assert all(v == 0 for v in shares["Long Ranger"]["zone_share"].values())


def test_opportunity_returns_matching_player():
    out = get_zonal_opportunity("Palace", store=opportunity_store())
    assert out["status"] == "ok"
    zones = {o["zone"]: o for o in out["opportunities"]}
    assert "in-box / right" in zones
    assert "Right Poacher" in zones["in-box / right"]["players"]
    assert zones["in-box / right"]["delta_vs_avg"] > 0


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
# T4b card enrichment — pct_over_avg / opportunity_level / fit_score
# ---------------------------------------------------------------------------

def test_card_pct_over_avg_hand_computed():
    # weakness_store: Palace in-box/right 0.25 vs baseline 0.1375
    # → (0.25 / 0.1375 − 1) × 100 = +81.8%; central all-equal → 0.0.
    out = get_zonal_opportunity("Palace", store=weakness_store())
    assert out["status"] == "ok"
    cells = {z["lateral"]: z for z in out["zones"]}
    assert list(cells) == ["left", "central", "right"]
    assert cells["right"]["pct_over_avg"] == pytest_approx(81.8, abs_=0.05)
    assert cells["central"]["pct_over_avg"] == pytest_approx(0.0)
    assert cells["left"]["pct_over_avg"] == pytest_approx(0.0)  # 0-vs-0 baseline


def test_card_opportunity_levels():
    out = get_zonal_opportunity("Palace", store=weakness_store())
    cells = {z["lateral"]: z for z in out["zones"]}
    assert cells["right"]["opportunity_level"] == "opp"        # ≥ +15%
    assert cells["central"]["opportunity_level"] == "cool"    # ≈ 0
    assert cells["left"]["opportunity_level"] == "cool"


def test_card_weakness_label_and_verdict():
    out = get_zonal_opportunity("Palace", store=weakness_store())
    assert out["weakness_label"] == "Débil dentro del área"
    # unified attacker/opportunity frame: the low-band weak zone is the
    # attacker's RIGHT flank and the verdict says "ataca por la derecha"
    # with the headline pct; opportunity framing only.
    assert out["verdict"].startswith("Ataca a Palace")
    assert "dentro del área" in out["verdict"]
    assert "por la derecha" in out["verdict"]
    assert "costado" not in out["verdict"]
    assert "+82%" in out["verdict"]
    for banned in ("compra", "vende", "ficha", "buy", "sell"):
        assert banned not in out["verdict"].lower()
    assert out["penalty_context"]["penalty_xga_per_game"] == pytest_approx(0.7611 / 2, abs_=1e-4)


def test_card_fit_score_ordering_and_normalisation():
    # Heavy Hitter (Villa): 10 in-box/right shots × 0.30 xG → share 1.0,
    # total 3.0 → raw 3.0. Right Poacher: share 1.0 × total 1.0 → raw 1.0.
    # Same zone weight for both → Heavy Hitter ranks first, fit 10.0;
    # Poacher fit = 10 × (1/3) = 3.3.
    df = opportunity_store()
    extra = [_row("Boro", "Villa", 0.90, 0.20, 0.30,
                  match_id=107, player="Heavy Hitter") for _ in range(10)]
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    out = get_zonal_opportunity("Palace", store=df)
    assert out["status"] == "ok"
    exploiters = out["exploiters"]
    assert [e["player"] for e in exploiters[:2]] == ["Heavy Hitter", "Right Poacher"]
    assert exploiters[0]["rank"] == 1 and exploiters[0]["fit_score"] == 10.0
    assert exploiters[1]["fit_score"] == pytest_approx(3.3, abs_=0.05)
    assert exploiters[0]["zone"] == "in-box / right"
    assert exploiters[0]["team"] == "Villa"


def test_card_exploiters_exclude_own_team_and_carry_identity():
    out = get_zonal_opportunity("Palace", store=opportunity_store())
    names = [e["player"] for e in out["exploiters"]]
    assert "Palace Own" not in names
    assert "Right Poacher" in names
    for e in out["exploiters"]:
        assert {"rank", "player", "team", "zone", "fit_score"} <= set(e)
        assert 0.0 <= e["fit_score"] <= 10.0


# ---------------------------------------------------------------------------
# team filter (i85) — "which of TEAM's players can exploit OPPONENT" is a
# different question from the unfiltered league-wide ranking, and must not
# be answered by silently checking whether TEAM happens to appear in that
# unfiltered top-N (found 2026-09-11: asking about Liverpool vs Fulham got
# "no Liverpool player" from a global top-5 that simply had none, which said
# nothing about whether any Liverpool player actually qualifies).
# ---------------------------------------------------------------------------

def _two_team_store() -> pd.DataFrame:
    """Same shape as test_card_fit_score_ordering_and_normalisation:
    Heavy Hitter (Villa) globally outranks Right Poacher (Wolves) --
    unfiltered exploiters[0] is Villa's player, not Wolves'."""
    df = opportunity_store()
    extra = [_row("Boro", "Villa", 0.90, 0.20, 0.30,
                  match_id=107, player="Heavy Hitter") for _ in range(10)]
    return pd.concat([df, pd.DataFrame(extra)], ignore_index=True)


def test_team_filter_restricts_exploiters_to_that_team():
    out = get_zonal_opportunity("Palace", team="Wolves", store=_two_team_store())
    assert out["status"] == "ok"
    assert [e["player"] for e in out["exploiters"]] == ["Right Poacher"]
    assert out["exploiters"][0]["fit_score"] == 10.0  # re-normalised within the filtered set
    assert out["team_filter"]["requested"] == "Wolves"
    assert out["team_filter"]["matched"] == "Wolves"


def test_team_filter_restricts_opportunities_too():
    out = get_zonal_opportunity("Palace", team="Wolves", store=_two_team_store())
    players = [p for o in out["opportunities"] for p in o["players"]]
    assert "Heavy Hitter" not in players
    assert "Right Poacher" in players


def test_no_team_filter_is_unfiltered_and_omits_team_filter_key():
    out = get_zonal_opportunity("Palace", store=_two_team_store())
    assert [e["player"] for e in out["exploiters"][:1]] == ["Heavy Hitter"]
    assert "team_filter" not in out


def test_team_filter_unresolved_yields_empty_not_unfiltered():
    """A team string that matches nothing in the store must return EMPTY
    exploiters/opportunities, never silently fall back to the unfiltered
    (league-wide) ranking -- that would misreport an unrecognised team as
    a real "no qualifying player" answer."""
    out = get_zonal_opportunity("Palace", team="Nonexistent FC", store=_two_team_store())
    assert out["status"] == "ok"
    assert out["exploiters"] == []
    assert out["opportunities"] == [] or all(o["players"] == [] for o in out["opportunities"])
    assert out["team_filter"]["requested"] == "Nonexistent FC"
    assert out["team_filter"]["matched"] is None


def test_team_filter_matching_the_opponent_itself_yields_empty():
    """Filtering to the opponent's own team is a degenerate but valid
    request -- their own players are already excluded upstream, so this
    must resolve the team and still return zero exploiters, not error."""
    out = get_zonal_opportunity("Palace", team="Palace", store=_two_team_store())
    assert out["status"] == "ok"
    assert out["exploiters"] == []
    assert out["team_filter"]["requested"] == "Palace"
    assert out["team_filter"]["matched"] == "Palace"


# ---------------------------------------------------------------------------
# Player zonal outlook (T-player)
# ---------------------------------------------------------------------------

get_player_zonal_outlook = zonal_weakness.get_player_zonal_outlook


def test_outlook_favorable_when_zones_intersect():
    # Right Poacher (Wolves) concentrates 100% of xG in in-box/right; Palace
    # concedes above average exactly there → favorable.
    out = get_player_zonal_outlook(
        "Right Poacher",
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
    assert match["zone"] == "in-box / right"
    assert match["delta_vs_avg"] > 0
    assert match["player_share"] == pytest_approx(1.0)
    assert "J24 (Palace)" in out["verdict"]


def test_outlook_neutral_and_no_data_entries():
    out = get_player_zonal_outlook(
        "Right Poacher",
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
        "Right Poacher",
        fixtures_for_team=lambda t: [{"gameweek": 1, "opponent": "Palace", "is_home": True}],
        store=opportunity_store(),
    )
    assert out["player_zones"][0]["zone"] == "in-box / right"
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
        "Right Poacher", fixtures_for_team=lambda t: [], store=pd.DataFrame()
    )
    assert out["status"] == "missing_context"
    out2 = get_player_zonal_outlook(
        "Right Poacher", fixtures_for_team=lambda t: [], store=opportunity_store()
    )
    assert out2["status"] == "missing_context"  # no upcoming fixtures


def test_outlook_verdict_no_buy_sell():
    out = get_player_zonal_outlook(
        "Right Poacher",
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


# ---------------------------------------------------------------------------
# team-scoped gates (i87) -- a resolved team filter ranks the WHOLE team,
# not just league standouts. Found 2026-09-11: with i85+i86 live, Liverpool
# scoped against Fulham returned exploiters == [] because no Liverpool
# player had 10 non-penalty shots after 3 GWs. An empty list is honest but
# useless to someone deciding between that team's wingers; the sample
# thinness must be shown per player, not used to hide the player.
# ---------------------------------------------------------------------------

def _thin_team_store() -> pd.DataFrame:
    """Two-team store where "Thin Winger" (Wolves) has only 3 non-penalty
    shots -- under the league gate (10) -- all from in-box/right, Palace's
    weak zone. "Heavy Hitter" (Villa) is the league-gate-clearing control."""
    df = _two_team_store()
    thin = [_row("Palace", "Wolves", 0.90, 0.20, 0.20,
                 match_id=108, player="Thin Winger") for _ in range(3)]
    return pd.concat([df, pd.DataFrame(thin)], ignore_index=True)


def test_league_wide_ranking_keeps_league_gates():
    """Unscoped: Thin Winger (3 shots) stays gated out, exactly as before."""
    out = get_zonal_opportunity("Palace", store=_thin_team_store())
    names = [e["player"] for e in out["exploiters"]]
    assert "Thin Winger" not in names
    assert "Heavy Hitter" in names
    assert "team_filter" not in out


def test_team_scoped_ranking_includes_thin_sample_players_and_labels_them():
    out = get_zonal_opportunity("Palace", team="Wolves", store=_thin_team_store())
    assert out["status"] == "ok"
    by_name = {e["player"]: e for e in out["exploiters"]}
    assert set(by_name) == {"Right Poacher", "Thin Winger"}   # whole team, no Villa
    # evidence is on every row
    assert by_name["Thin Winger"]["n_shots"] == 3
    assert by_name["Thin Winger"]["sample"] == "thin"
    assert by_name["Thin Winger"]["zone"] == "in-box / right"
    assert by_name["Thin Winger"]["zone_share"] == 1.0
    assert by_name["Right Poacher"]["n_shots"] == 10
    assert by_name["Right Poacher"]["sample"] == "ok"
    # and the applied gates are reported, so a consumer can tell this
    # ranking is "the team, relative to itself"
    tf = out["team_filter"]
    assert tf["matched"] == "Wolves"
    assert tf["min_shots"] == zonal_weakness.TEAM_SCOPED_MIN_PLAYER_SHOTS
    assert tf["zone_share_threshold"] == zonal_weakness.TEAM_SCOPED_ZONE_SHARE_THRESHOLD


def test_team_scoped_ranking_still_orders_by_fit():
    # Right Poacher: 10 × 0.10 xG = 1.0 total, share 1.0 → raw 1.0×w
    # Thin Winger:    3 × 0.20 xG = 0.6 total, share 1.0 → raw 0.6×w
    out = get_zonal_opportunity("Palace", team="Wolves", store=_thin_team_store())
    assert [e["player"] for e in out["exploiters"]] == ["Right Poacher", "Thin Winger"]
    assert out["exploiters"][0]["fit_score"] == 10.0
    assert out["exploiters"][1]["fit_score"] == pytest_approx(6.0, abs_=0.05)


def test_team_scoped_player_with_no_zoned_xg_is_still_excluded():
    """Relaxed gates are 'any zoned xG', not 'any shot': a long-range-only
    shooter has nothing to say about an in-box weakness."""
    df = _thin_team_store()
    lr = [_row("Boro", "Wolves", 0.50, 0.50, 0.05,
               match_id=109, player="Wolves Long Ranger") for _ in range(3)]
    df = pd.concat([df, pd.DataFrame(lr)], ignore_index=True)
    out = get_zonal_opportunity("Palace", team="Wolves", store=df)
    assert "Wolves Long Ranger" not in [e["player"] for e in out["exploiters"]]


# ---------------------------------------------------------------------------
# shot origin (i88) -- a set-piece fit is kept but LABELLED. Found 2026-09-11:
# Virgil van Dijk ranked #2 "por la izquierda" against Fulham on two corner
# headers from the left of the six-yard box, presented like a winger.
# ---------------------------------------------------------------------------

def _origin_store() -> pd.DataFrame:
    """Palace weak in-box/right. Two Wolves players operate there:
    "Corner CB" -- 3 headers from corners; "Open Winger" -- 3 open-play
    shots; "Mixed Mid" -- one of each (50%)."""
    df = opportunity_store()
    extra = []
    extra += [_row("Palace", "Wolves", 0.92, 0.30, 0.15, match_id=110,
                   player="Corner CB", situation="From Corner") for _ in range(3)]
    extra += [_row("Palace", "Wolves", 0.90, 0.20, 0.15, match_id=111,
                   player="Open Winger") for _ in range(3)]
    extra += [_row("Palace", "Wolves", 0.90, 0.20, 0.15, match_id=112, player="Mixed Mid"),
              _row("Palace", "Wolves", 0.92, 0.30, 0.15, match_id=112,
                   player="Mixed Mid", situation="Set Piece")]
    return pd.concat([df, pd.DataFrame(extra)], ignore_index=True)


def test_player_zone_shares_track_set_piece_share_per_zone():
    shares = compute_player_zone_shares(_origin_store(), min_shots=1)
    assert shares["Corner CB"]["zone_set_piece_share"]["in-box / right"] == pytest_approx(1.0)
    assert shares["Corner CB"]["zone_shots"]["in-box / right"] == 3
    assert shares["Open Winger"]["zone_set_piece_share"]["in-box / right"] == pytest_approx(0.0)
    assert shares["Mixed Mid"]["zone_set_piece_share"]["in-box / right"] == pytest_approx(0.5)
    # a zone with no xG reports 0.0, never divides by zero
    assert shares["Corner CB"]["zone_set_piece_share"]["in-box / left"] == 0.0


def test_exploiters_carry_origin_label():
    out = get_zonal_opportunity("Palace", team="Wolves", store=_origin_store())
    by = {e["player"]: e for e in out["exploiters"]}
    assert by["Corner CB"]["origin"] == "set_piece"
    assert by["Corner CB"]["set_piece_share"] == 1.0
    assert by["Corner CB"]["zone_shots"] == 3
    assert by["Open Winger"]["origin"] == "open_play"
    assert by["Mixed Mid"]["origin"] == "mixed"


def test_set_piece_fit_is_kept_not_excluded():
    """The signal is real (a CB attacking a leaky far post IS a way in); the
    fix is the label, not a filter. Corner CB and Open Winger have identical
    xG in the zone, so they tie on fit and both rank."""
    out = get_zonal_opportunity("Palace", team="Wolves", store=_origin_store())
    names = [e["player"] for e in out["exploiters"]]
    assert "Corner CB" in names and "Open Winger" in names


def test_origin_label_thresholds():
    lab = zonal_weakness._origin_label
    assert lab(1.0) == "set_piece"
    assert lab(0.6) == "set_piece"
    assert lab(0.59) == "mixed"
    assert lab(0.41) == "mixed"
    assert lab(0.4) == "open_play"
    assert lab(0.0) == "open_play"


def test_penalties_never_count_toward_origin():
    """Penalties are excluded from zonal aggregation entirely, so they can
    neither add zoned xG nor tilt a player toward set_piece."""
    df = _origin_store()
    pens = [_row("Palace", "Wolves", 0.885, 0.50, 0.7611, match_id=113,
                 player="Open Winger", situation=PENALTY_SITUATION) for _ in range(3)]
    df = pd.concat([df, pd.DataFrame(pens)], ignore_index=True)
    out = get_zonal_opportunity("Palace", team="Wolves", store=df)
    by = {e["player"]: e for e in out["exploiters"]}
    assert by["Open Winger"]["origin"] == "open_play"
    assert by["Open Winger"]["zone_shots"] == 3


# ---------------------------------------------------------------------------
# i89 (a): several teams in one scope.
# ---------------------------------------------------------------------------

def test_multi_team_filter_ranks_both_teams_together():
    out = get_zonal_opportunity("Palace", team=["Wolves", "Villa"], store=_two_team_store())
    # both teams in one table, ranked together; "Someone" (Villa, 1 shot)
    # trails under the team-scoped gates
    assert [e["player"] for e in out["exploiters"]][:2] == ["Heavy Hitter", "Right Poacher"]
    assert {e["team"] for e in out["exploiters"]} == {"Villa", "Wolves"}
    tf = out["team_filter"]
    assert tf["matched_teams"] == ["Wolves", "Villa"]   # request order, deduped
    assert tf["matched"] == "Wolves, Villa"
    assert tf["unmatched_teams"] == []


def test_multi_team_filter_partial_match_keeps_going():
    out = get_zonal_opportunity("Palace", team=["Wolves", "Nadie FC"], store=_two_team_store())
    assert [e["player"] for e in out["exploiters"]] == ["Right Poacher"]
    assert out["team_filter"]["matched_teams"] == ["Wolves"]
    assert out["team_filter"]["unmatched_teams"] == ["Nadie FC"]


def test_multi_team_filter_none_match_is_empty_not_unfiltered():
    out = get_zonal_opportunity("Palace", team=["Nadie FC", "Nobody"], store=_two_team_store())
    assert out["exploiters"] == []
    assert out["team_filter"]["matched"] is None
    assert out["team_filter"]["unmatched_teams"] == ["Nadie FC", "Nobody"]


def test_single_team_string_still_works_and_reports_lists():
    out = get_zonal_opportunity("Palace", team="Wolves", store=_two_team_store())
    assert out["team_filter"]["requested_teams"] == ["Wolves"]
    assert out["team_filter"]["matched_teams"] == ["Wolves"]


# ---------------------------------------------------------------------------
# i90 — fixture-derived scope. "¿Zonas débiles de Palace?" without a named
# team defaulted to a league-wide xG ranking, blind to the calendar (always
# surfacing the same global standouts). ``fixtures_for_team`` (same shape
# the outlook engine already takes) lets the engine scope instead to
# whoever actually plays Palace in the fixture window.
# ---------------------------------------------------------------------------

def _two_gw_fixtures(_store_team_name: str) -> list[dict]:
    """Palace's own schedule (the weak team's perspective, per contract):
    home vs Wolves in GW5, away at Villa in GW6."""
    return [
        {"gameweek": 5, "opponent": "Wolves", "is_home": True},
        {"gameweek": 6, "opponent": "Villa", "is_home": False},
    ]


class TestFixtureDerivedScope:
    def test_four_scope_resolution_values(self):
        store = _two_team_store()
        explicit = get_zonal_opportunity("Palace", team="Wolves", store=store)
        assert explicit["scope_resolution"] == "explicit"
        fixtures = get_zonal_opportunity(
            "Palace", fixtures_for_team=_two_gw_fixtures, store=store,
        )
        assert fixtures["scope_resolution"] == "fixtures"
        empty = get_zonal_opportunity(
            "Palace", fixtures_for_team=lambda _t: [], store=store,
        )
        assert empty["scope_resolution"] == "fixtures_empty_fallback"
        league = get_zonal_opportunity("Palace", store=store)
        assert league["scope_resolution"] == "league"
        # none of these should be inferred from matched_teams being empty
        # or not -- fixtures_empty_fallback and league both have it empty.
        assert empty["team_filter"]["matched_teams"] == []
        assert "team_filter" not in league

    def test_matched_teams_and_scheduled_opponents_from_calendar(self):
        out = get_zonal_opportunity(
            "Palace", fixtures_for_team=_two_gw_fixtures, store=_two_team_store(),
        )
        tf = out["team_filter"]
        assert tf["matched_teams"] == ["Wolves", "Villa"]
        assert tf["scheduled_opponents"] == ["Wolves", "Villa"]
        # derived, not asked for by name -- must not claim a user selection
        assert tf["requested_teams"] == []
        assert tf["requested"] is None
        assert tf["unmatched_teams"] == []
        assert tf["fixture_window"] == {"from_gw": 5, "to_gw": 6, "horizon": 2}

    def test_is_home_is_flipped_to_attacker_perspective(self):
        """Palace at home vs Wolves (callback) means WOLVES are away; Palace
        away at Villa means VILLA are home. Getting this backwards is the
        easiest mistake in i90 and the most visible on the card."""
        out = get_zonal_opportunity(
            "Palace", fixtures_for_team=_two_gw_fixtures, store=_two_team_store(),
        )
        by_team = {e["team"]: e for e in out["exploiters"]}
        assert by_team["Wolves"]["is_home"] is False
        assert by_team["Wolves"]["gameweek"] == 5
        assert by_team["Villa"]["is_home"] is True
        assert by_team["Villa"]["gameweek"] == 6
        fx_field = {f["team"]: f["is_home"] for f in out["team_filter"]["fixtures"]}
        assert fx_field == {"Wolves": False, "Villa": True}

    def test_double_gameweek_dedupes_opponent_keeps_first_fixture(self):
        def two_visits(_team: str) -> list[dict]:
            return [
                {"gameweek": 5, "opponent": "Wolves", "is_home": True},
                {"gameweek": 9, "opponent": "Wolves", "is_home": False},
            ]

        out = get_zonal_opportunity(
            "Palace", fixtures_for_team=two_visits, store=_two_team_store(),
        )
        tf = out["team_filter"]
        assert tf["matched_teams"] == ["Wolves"]  # one entry, not two
        wolves_rows = [e for e in out["exploiters"] if e["team"] == "Wolves"]
        assert wolves_rows[0]["gameweek"] == 5  # the first of the two
        assert wolves_rows[0]["is_home"] is False
        assert wolves_rows[0]["fixtures"] == [
            {"gameweek": 5, "is_home": False},
            {"gameweek": 9, "is_home": True},
        ]

    def test_fixture_scope_caps_at_three_even_with_one_scheduled_opponent(self):
        """i90: a fixture-derived scope always uses the per-team cap, even
        with a single scheduled opponent -- it's still "that team's
        players," not a global top-5."""
        df = opportunity_store()
        extra_players = pd.DataFrame([
            _row("Boro", "Wolves", 0.90, 0.20, 0.30 - 0.01 * i,
                 match_id=200 + i, player=f"Wolf {i}")
            for i in range(5)
        ])
        extra = pd.concat([df, extra_players], ignore_index=True)
        out = get_zonal_opportunity(
            "Palace",
            fixtures_for_team=lambda _t: [{"gameweek": 5, "opponent": "Wolves", "is_home": True}],
            store=extra,
        )
        wolves_rows = [e for e in out["exploiters"] if e["team"] == "Wolves"]
        assert len(wolves_rows) == 3
        assert out["team_filter"]["candidates_per_team"]["Wolves"] == 6  # 5 + Right Poacher

    def test_empty_window_behaves_like_league_wide(self):
        with_fx = get_zonal_opportunity(
            "Palace", fixtures_for_team=lambda _t: [], store=_two_team_store(),
        )
        league = get_zonal_opportunity("Palace", store=_two_team_store())
        assert with_fx["exploiters"] == league["exploiters"]
        assert with_fx["scope_resolution"] == "fixtures_empty_fallback"

    def test_bridge_gap_surfaces_as_unmatched_not_silent_zero_rows(self):
        """i90: unlike the explicit-team path, the fixtures path used to
        trust the callback's team name unconditionally -- a bridge gap
        (missing/mistranslated FPL->Understat code) would then silently
        yield zero candidates for that team instead of a visible signal.
        Now it resolves against the store exactly like `team` does."""
        def fixtures_with_a_ghost(_team: str) -> list[dict]:
            return [
                {"gameweek": 5, "opponent": "Wolves", "is_home": True},
                {"gameweek": 6, "opponent": "Ghost Town FC", "is_home": False},
            ]

        out = get_zonal_opportunity(
            "Palace", fixtures_for_team=fixtures_with_a_ghost, store=_two_team_store(),
        )
        tf = out["team_filter"]
        assert tf["matched_teams"] == ["Wolves"]
        assert tf["unmatched_teams"] == ["Ghost Town FC"]
        # the calendar-derived list still names BOTH -- that's the signal
        # a prod check compares against the live fixture list independently.
        assert tf["scheduled_opponents"] == ["Wolves", "Ghost Town FC"]


# ---------------------------------------------------------------------------
# i89 (c): a marginal weakness is framed as marginal. Found 2026-09-11,
# Sunderland: only zone above average was in-box/left at +1.8%; one player
# in the league cleared the gate there and the card served him like a +70%
# read. The verdict must lead with "no clear weakness", the pill must not
# say "Débil", and the payload must carry the strength so the UI can too.
# ---------------------------------------------------------------------------

def _marginal_store() -> pd.DataFrame:
    """Four teams, one game each. Every team concedes 1.00 centrally and
    "Left Man" (Someone FC) puts 3 x 0.10 on each of them from in-box/left,
    so the only asymmetry is Palace's extra 0.012 there:
    Palace 0.312 vs others 0.30 -> baseline 0.303 -> +3%: marginal."""
    rows = []
    for mid, team in enumerate(("Palace", "Villa", "Boro", "Wolves"), start=1):
        rows.append(_row(team, "Someone FC", 0.90, 0.50, 1.00, match_id=mid))  # central, equal
        rows += [_row(team, "Someone FC", 0.90, 0.80, 0.10, match_id=mid, player="Left Man")
                 for _ in range(3)]                                              # in-box/left
    rows.append(_row("Palace", "Someone FC", 0.90, 0.80, 0.012, match_id=1))    # the asymmetry
    return pd.DataFrame(rows)


def test_weakness_strength_levels():
    ws = zonal_weakness.weakness_strength
    mk = lambda pct: [{"zone": "in-box / left", "xga_per_game": 1 + pct / 100, "league_avg": 1.0,
                       "delta_vs_avg": pct / 100}]
    assert ws(mk(70)) == "clear"
    assert ws(mk(15)) == "clear"
    assert ws(mk(14.9)) == "marginal"
    assert ws(mk(1.0)) == "marginal"
    assert ws(mk(0.5)) == "none"
    assert ws([{"zone": "in-box / left", "xga_per_game": 0.5, "league_avg": 1.0,
                "delta_vs_avg": -0.5}]) == "none"
    assert ws([]) == "none"


def test_marginal_weakness_is_framed_as_marginal():
    out = get_zonal_opportunity("Palace", store=_marginal_store())
    assert out["status"] == "ok"
    assert out["weakness_strength"] == "marginal"
    assert out["weakness_label"] == "Ventaja leve dentro del área"
    v = out["verdict"]
    assert v.startswith("Palace no concede claramente por encima de la media")
    assert "por la izquierda" in v and "ventaja leve" in v
    assert not v.startswith("Ataca a")
    for banned in ("compra", "vende", "ficha"):
        assert banned not in v.lower()
    # the fit table still exists -- the read is marginal, not absent
    assert [e["player"] for e in out["exploiters"]] == ["Left Man"]


def test_clear_weakness_framing_unchanged():
    out = get_zonal_opportunity("Palace", store=weakness_store())
    assert out["weakness_strength"] == "clear"
    assert out["weakness_label"] == "Débil dentro del área"
    assert out["verdict"].startswith("Ataca a Palace")


def test_text_tool_verdict_also_marginal():
    out = get_zonal_weakness("Palace", store=_marginal_store())
    assert out["verdict"].startswith("Palace no concede claramente")
