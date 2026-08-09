"""
Preseason score reweighting + minutes-floor shrinkage — tests.

Covers the fix for two related bugs, both documented against a live
2026-27 bootstrap in field-notes/2026-08-05-preseason-gaps.md:

  #2  `form` is 0 for every player before GW1, but carries 30-40% of
      `position_score`'s weight, silently compressing every score toward a
      ~60/100 ceiling and flattening the distance between very different
      players (e.g. Haaland vs Konsa).
  #3  Per-90 rates feeding the score have no minutes floor, so a player
      with a handful of minutes (Dasilva, 2 min, xgi/90=3.60) can outrank
      established starters.

A first design (spread form's weight proportionally across everything) was
shown to be a per-position constant multiplier when form==0 for everyone —
it cannot re-rank anything. The validated fix instead routes most of form's
freed weight to `xgi` (the one component carrying real per-player signal),
protects `saves` (GKP's 2026-03-28 overpromotion calibration) and, for GKP
specifically, never boosts `xgi` (structurally zero — no attacking output;
boosting it would cap every keeper near 72/100). See position_score.py's
`redistribute_preseason_weights` docstring for the full rationale.

All fixed numbers below were captured against the live bootstrap on
2026-08-09 (see conversation / plan for the full decomposition) and are
used here as realistic, reproducible inputs — not live network calls.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.position_score import (
    MINUTES_SHRINKAGE_K,
    XGI_BOOST_SHARE,
    POSITION_PROFILES,
    PositionWeights,
    compute_position_score,
    redistribute_preseason_weights,
    shrink_rate_by_minutes,
)
from fpl_grounded_assistant.transfer_advisor import _derive_scoring_inputs
from fpl_api_client import is_form_informative
from fpl_captain_engine import calculate_captain_score


# ---------------------------------------------------------------------------
# shrink_rate_by_minutes (finding #3 — always on, not preseason-gated)
# ---------------------------------------------------------------------------

class TestShrinkRateByMinutes:
    def test_zero_minutes_is_zero(self):
        assert shrink_rate_by_minutes(3.60, 0) == 0.0

    def test_dasilva_case_drops_about_two_orders_of_magnitude(self):
        # 2 minutes played, one lucky involvement -- the exact case that
        # ranked #1 MID/FWD in the whole game pre-shrinkage.
        shrunk = shrink_rate_by_minutes(3.60, 2)
        assert shrunk == pytest.approx(0.01593, abs=1e-4)
        assert shrunk < 3.60 / 100  # at least two orders of magnitude down

    def test_established_starter_is_only_mildly_damped(self):
        # Haaland: 2953 minutes, real xgi/90 -- well past the trust
        # threshold, should survive shrinkage mostly intact.
        shrunk = shrink_rate_by_minutes(0.8586, 2953)
        assert shrunk == pytest.approx(0.7451, abs=1e-3)
        assert shrunk > 0.8586 * 0.7

    def test_monotonic_in_minutes(self):
        vals = [shrink_rate_by_minutes(1.0, m) for m in (0, 90, 450, 2000, 5000)]
        assert all(v2 > v1 for v1, v2 in zip(vals, vals[1:]))

    def test_default_k_is_450(self):
        assert MINUTES_SHRINKAGE_K == 450.0


# ---------------------------------------------------------------------------
# redistribute_preseason_weights (finding #2)
# ---------------------------------------------------------------------------

class TestRedistributePreseasonWeights:
    """Split by whether the base profile's xgi is zero — a single assertion
    parametrized blindly over all 4 profiles is exactly what would have
    pinned the GKP routing bug (boosting a structurally-zero xgi weight,
    capping every keeper near 72/100) in place instead of catching it.
    """

    @pytest.mark.parametrize("pos", ["DEF", "MID", "FWD"])
    def test_xgi_positions_get_the_boost_and_still_sum_to_one(self, pos):
        profile = POSITION_PROFILES[pos]
        r = redistribute_preseason_weights(profile)
        total = r.form + r.fixture + r.xgi + r.minutes + r.saves + r.clean_sheet + r.dc
        assert total == pytest.approx(1.0, abs=0.001)
        assert r.form == 0.0
        assert r.saves == profile.saves  # protected, byte-identical
        assert r.xgi == pytest.approx(
            profile.xgi + profile.form * XGI_BOOST_SHARE, abs=1e-9
        )

    def test_gkp_xgi_stays_exactly_zero(self):
        profile = POSITION_PROFILES["GKP"]
        assert profile.xgi == 0.0  # the precondition this test exists to catch drifting
        r = redistribute_preseason_weights(profile)
        total = r.form + r.fixture + r.xgi + r.minutes + r.saves + r.clean_sheet + r.dc
        assert total == pytest.approx(1.0, abs=0.001)
        assert r.form == 0.0
        assert r.xgi == 0.0  # explicit, by name -- not just "sums to 1.0"
        assert r.saves == profile.saves == 0.15  # protected, untouched

    def test_gkp_freed_weight_lands_on_fixture_minutes_and_clean_sheet(self):
        profile = POSITION_PROFILES["GKP"]
        r = redistribute_preseason_weights(profile)
        assert r.fixture > profile.fixture
        assert r.minutes > profile.minutes
        assert r.clean_sheet > profile.clean_sheet

    def test_a_profile_with_no_form_weight_is_a_no_op(self):
        # Defensive: no current profile has form == 0, but the function must
        # not divide by zero or misbehave if one ever does.
        zero_form = PositionWeights(
            form=0.0, fixture=0.5, xgi=0.3, minutes=0.2,
            saves=0.0, clean_sheet=0.0, dc=0.0,
        )
        assert redistribute_preseason_weights(zero_form) == zero_form


# ---------------------------------------------------------------------------
# weights_override_label (position_profile must not leak "custom"/"Unknown")
# ---------------------------------------------------------------------------

class TestWeightsOverrideLabel:
    def test_label_reports_the_real_position_when_provided(self):
        result = compute_position_score(
            "DEF", form=0, fixture_difficulty=3, xgi_per_90=0.5, minutes_risk=0,
            saves_per_90=0, clean_sheets_per_90=0.3,
            weights_override=POSITION_PROFILES["DEF"],
            weights_override_label="DEF",
        )
        assert result.position_profile == "DEF"

    def test_existing_callers_without_a_label_keep_custom(self):
        # Sensitivity-analysis scripts already pass weights_override with no
        # label -- must be unaffected (additive, not a behavior change).
        result = compute_position_score(
            "DEF", form=0, fixture_difficulty=3, xgi_per_90=0.5, minutes_risk=0,
            saves_per_90=0, clean_sheets_per_90=0.3,
            weights_override=POSITION_PROFILES["DEF"],
        )
        assert result.position_profile == "custom"


# ---------------------------------------------------------------------------
# is_form_informative (population-wide gate, not per-player)
# ---------------------------------------------------------------------------

class TestIsFormInformative:
    def test_empty_bootstrap_defaults_to_informative(self):
        # Missing/incomplete data: don't guess, assume the normal formula.
        assert is_form_informative({}) is True
        assert is_form_informative({"elements": []}) is True

    def test_all_zero_form_is_not_informative(self):
        assert is_form_informative({"elements": [{"form": "0"} for _ in range(50)]}) is False

    def test_a_single_out_of_form_player_does_not_flip_the_gate(self):
        # One legitimately out-of-form player mid-season must never read as
        # "the season hasn't started" -- population-wide, not per-player.
        elements = [{"form": "5.0"} for _ in range(49)] + [{"form": "0"}]
        assert is_form_informative({"elements": elements}) is True

    def test_below_threshold_fraction_is_not_informative(self):
        # 1 of 50 = 2%, below the 5% threshold.
        elements = [{"form": "5.0"}] + [{"form": "0"} for _ in range(49)]
        assert is_form_informative({"elements": elements}) is False

    def test_above_threshold_fraction_is_informative(self):
        # 5 of 50 = 10%, above the 5% threshold.
        elements = [{"form": "5.0"} for _ in range(5)] + [{"form": "0"} for _ in range(45)]
        assert is_form_informative({"elements": elements}) is True


# ---------------------------------------------------------------------------
# Integration: the validated Haaland-vs-Konsa gap, plus a second pair and a
# GKP pair, using real per-90/minutes captured live on 2026-08-09.
# ---------------------------------------------------------------------------

class TestPreseasonSeparationWidensViaXgi:
    """Reproduces the decomposition that validated this fix, directly
    through compute_position_score, so a future change to the weight
    tables or shrinkage constant that quietly re-flattens the score gets
    caught here rather than only being noticed by eye in `/comparar`.
    """

    def _score(self, pos, xgi_per_90, minutes, cs_per_90=0.0, dc_per_90=0.0, redistribute=False):
        shrunk_xgi = shrink_rate_by_minutes(xgi_per_90, minutes)
        shrunk_cs = shrink_rate_by_minutes(cs_per_90, minutes)
        shrunk_dc = shrink_rate_by_minutes(dc_per_90, minutes)
        weights_override = None
        label = None
        if redistribute:
            profile = POSITION_PROFILES[pos]
            weights_override = redistribute_preseason_weights(profile)
            label = pos
        return compute_position_score(
            pos, form=0.0, fixture_difficulty=3.0,
            xgi_per_90=shrunk_xgi, minutes_risk=0.0,
            saves_per_90=0.0, clean_sheets_per_90=shrunk_cs, dc_per_90=shrunk_dc,
            weights_override=weights_override, weights_override_label=label,
        )

    def test_haaland_vs_konsa_gap_widens_via_xgi_specifically(self):
        # Captured live 2026-08-09: Haaland (FWD) minutes=2953, xgi/90=0.8586,
        # cs/90=0.40, dc/90=3.17; Konsa (DEF) minutes=3035, xgi/90=0.0552,
        # cs/90=0.27, dc/90=5.81.
        haaland_before = self._score("FWD", 0.8586, 2953, cs_per_90=0.40, dc_per_90=3.17)
        konsa_before   = self._score("DEF", 0.0552, 3035, cs_per_90=0.27, dc_per_90=5.81)
        gap_before = haaland_before.position_score - konsa_before.position_score

        haaland_after = self._score("FWD", 0.8586, 2953, cs_per_90=0.40, dc_per_90=3.17, redistribute=True)
        konsa_after   = self._score("DEF", 0.0552, 3035, cs_per_90=0.27, dc_per_90=5.81, redistribute=True)
        gap_after = haaland_after.position_score - konsa_after.position_score

        assert gap_after > gap_before
        # Specifically via xgi, not just a uniform rescale of the total.
        xgi_gap_before = haaland_before.weighted["xgi"] - konsa_before.weighted["xgi"]
        xgi_gap_after = haaland_after.weighted["xgi"] - konsa_after.weighted["xgi"]
        assert xgi_gap_after > xgi_gap_before

    def test_second_pair_different_position_combination_rice_vs_konsa(self):
        # Rice (MID) minutes=3093, xgi/90=0.3047, cs/90=0.52, dc/90=10.94 vs
        # the same Konsa (DEF) as above -- validates XGI_BOOST_SHARE isn't
        # tuned to a single observation.
        rice_before  = self._score("MID", 0.3047, 3093, cs_per_90=0.52, dc_per_90=10.94)
        konsa_before = self._score("DEF", 0.0552, 3035, cs_per_90=0.27, dc_per_90=5.81)
        gap_before = rice_before.position_score - konsa_before.position_score

        rice_after  = self._score("MID", 0.3047, 3093, cs_per_90=0.52, dc_per_90=10.94, redistribute=True)
        konsa_after = self._score("DEF", 0.0552, 3035, cs_per_90=0.27, dc_per_90=5.81, redistribute=True)
        gap_after = rice_after.position_score - konsa_after.position_score

        assert gap_after > gap_before

    def test_gkp_pair_separation_stays_compressed_but_saves_and_cs_still_differentiate(self):
        # Alisson: minutes=2340, xgi/90=0.0012, saves/90=2.19, cs/90=0.31.
        # Sánchez: minutes=3040, xgi/90=0.0012, saves/90=2.90, cs/90=0.27.
        # This is the honest limitation documented in
        # redistribute_preseason_weights: GKP xgi is never boosted, so this
        # pair's separation should be much smaller than an outfield pair's
        # -- but not zero, since saves/clean_sheet still carry real signal.
        def gkp_score(minutes, saves_per_90, cs_per_90, redistribute):
            shrunk_saves = shrink_rate_by_minutes(saves_per_90, minutes)
            shrunk_cs = shrink_rate_by_minutes(cs_per_90, minutes)
            weights_override = None
            label = None
            if redistribute:
                weights_override = redistribute_preseason_weights(POSITION_PROFILES["GKP"])
                label = "GKP"
            return compute_position_score(
                "GKP", form=0.0, fixture_difficulty=3.0,
                xgi_per_90=0.0, minutes_risk=0.0,
                saves_per_90=shrunk_saves, clean_sheets_per_90=shrunk_cs, dc_per_90=0.0,
                weights_override=weights_override, weights_override_label=label,
            )

        alisson_after = gkp_score(2340, 2.19, 0.31, redistribute=True)
        sanchez_after = gkp_score(3040, 2.90, 0.27, redistribute=True)

        assert alisson_after.position_profile == "GKP"
        assert alisson_after.weighted["xgi"] == 0.0
        assert sanchez_after.weighted["xgi"] == 0.0
        # Real, if modest, separation from saves/clean_sheet -- not a flat tie.
        assert alisson_after.position_score != sanchez_after.position_score


# ---------------------------------------------------------------------------
# Layer-1 non-leak pin — the blocking issue from plan review: shrinking
# xgi_per_90 in place would silently change calculate_captain_score
# (/capitan, chip advice) too. This fails the moment anyone shrinks
# xgi_per_90 in place instead of alongside it.
# ---------------------------------------------------------------------------

class TestLayerOneDoesNotSeeTheShrinkage:
    def test_derive_scoring_inputs_keeps_xgi_per_90_raw(self):
        # A constructed element with real minutes (unlike the shared
        # conftest fixture, which has no "minutes" field and would make
        # this pin trivially vacuous at xgi_per_90 == 0 either way).
        element = {
            "form": "8.0",
            "minutes": 900,
            "expected_goal_involvements": "9.0",  # -> xgi_per_90 = 0.9
            "status": "a",
            "team": 1,
        }
        inputs = _derive_scoring_inputs(element, fdr_map={1: 3})

        raw_expected = 9.0 / (900 / 90.0)
        assert inputs["xgi_per_90"] == pytest.approx(raw_expected, abs=1e-6)
        assert inputs["xgi_per_90"] == pytest.approx(0.9, abs=1e-6)

        # The shrunk variant exists alongside it and is genuinely different
        # at this sample size -- proving the two keys aren't aliases.
        assert inputs["xgi_per_90_shrunk"] < inputs["xgi_per_90"]
        assert inputs["xgi_per_90_shrunk"] == pytest.approx(
            shrink_rate_by_minutes(raw_expected, 900), abs=1e-6
        )

    def test_captain_score_computed_from_the_raw_value_matches_a_hand_expectation(self):
        element = {
            "form": "8.0",
            "minutes": 900,
            "expected_goal_involvements": "9.0",
            "status": "a",
            "team": 1,
        }
        inputs = _derive_scoring_inputs(element, fdr_map={1: 3})

        score = calculate_captain_score(
            inputs["form"],
            inputs["fixture_difficulty"],
            inputs["xgi_per_90"],  # raw -- captain_score must never see xgi_per_90_shrunk
            inputs["minutes_risk"],
        )

        # Hand-computed from the same raw inputs (form=8.0, fdr=3, xgi/90=0.9,
        # minutes_risk=0.0): 0.4*80 + 0.3*60 + 0.2*45 + 0.1*100 = 32+18+9+10 = 69.0
        assert score == pytest.approx(69.0, abs=1e-6)
