"""The differential line on the plan_to_sign card: few own the target and the existing signals back him.

Display conditions, not predictors (the low-ownership backtest showed no predictive edge): these tests pin the
FACTS the line may state and the wording that must never become a forecast. Synthetic data only, no network.
"""
from __future__ import annotations

import json

import pytest

from fpl_grounded_assistant import plan_eo
from fpl_grounded_assistant.near_rank_eo import NearRankEOService  # noqa: F401  (stack fixture dependency)
from fpl_grounded_assistant.orch_config import NEAR_RANK_EO_ENABLED_ENV
from fpl_grounded_assistant.plan_card import MAX_CONCLUSIONS, plan_conclusions
from test_plan_card import _option, _raw
from test_plan_eo_line import (  # noqa: F401  (fixtures and helpers shared with the cover / no-exposure tests)
    BOOT, EVENTS, NOW, TEAM, _plan, _three_others, eo_raw, put_near, stack, stats, top,
)

GOOD = {"nailed": True, "fixtures": True, "xgi_top": True}


def diff_raw(near=None, top_pct=None, signals=GOOD, **kw):
    """A plan raw with ownership numbers and the target's display conditions.

    The default option sells no premium, so the no-exposure line cannot fire unless a test asks for it.
    """
    kw.setdefault("options", [_option("Isak", tops=[])])
    raw = eo_raw(near, top_pct, **kw)
    if "ownership" not in raw:
        raw["ownership"] = {}
    if signals is not None:
        raw["ownership"]["target_signals"] = dict(signals)
    return raw


def last(raw, locale="es"):
    return plan_conclusions(raw, locale)[-1]


def base(option=None):
    return plan_conclusions(_raw(option or _option("Isak", tops=[])), "en")


# -- the line -------------------------------------------------------------------------------------------------------

def test_few_own_him_near_your_rank_and_the_signals_hold():
    raw = diff_raw(5)
    assert last(raw, "es") == ("N.Jackson: solo lo tiene el 5 % cerca de tu puesto: si puntúa, subes frente a casi todos ellos. "
                               "Titular habitual y calendario favorable.")
    assert last(raw, "en") == ("N.Jackson: only 5% near your rank have him: if he scores, you gain on almost all of them. "
                               "Regular starter with a favourable run.")


def test_the_top_10k_is_the_reference_only_when_near_rank_has_no_data():
    raw = diff_raw(None, 8)
    assert "near_rank_owned_pct" not in raw["ownership"]
    assert last(raw, "es") == ("N.Jackson: solo lo tiene el 8 % del top 10K: si puntúa, subes frente a casi todo el top 10K. "
                               "Titular habitual y calendario favorable.")
    assert last(raw, "en") == ("N.Jackson: only 8% of the top 10K have him: if he scores, you gain on almost the whole top 10K. "
                               "Regular starter with a favourable run.")


def test_a_near_rank_number_that_is_not_low_is_not_overridden_by_a_low_top_10k():
    assert plan_conclusions(diff_raw(12, 3), "en") == base()


@pytest.mark.parametrize("pct,shown", [(0, True), (1, True), (10, True), (11, False)])
def test_the_low_ownership_bar(pct, shown):
    assert (plan_conclusions(diff_raw(pct), "en") != base()) is shown


def test_below_one_percent_reads_less_than_one_never_zero():
    near = diff_raw(0)
    assert last(near, "es").startswith("N.Jackson: lo tiene menos del 1 % cerca de tu puesto: si puntúa")
    assert last(near, "en").startswith("N.Jackson: less than 1% near your rank have him: if he scores")
    topr = diff_raw(None, 0)
    assert last(topr, "es").startswith("N.Jackson: lo tiene menos del 1 % del top 10K: si puntúa")
    assert last(topr, "en").startswith("N.Jackson: less than 1% of the top 10K have him: if he scores")
    for raw in (near, topr):
        for locale in ("es", "en"):
            assert "0 %" not in last(raw, locale) and "0%" not in last(raw, locale)


# -- every display condition is needed; missing means no line -----------------------------------------------------------

@pytest.mark.parametrize("failing", ["nailed", "fixtures", "xgi_top"])
def test_one_failing_signal_means_no_line(failing):
    assert plan_conclusions(diff_raw(5, signals={**GOOD, failing: False}), "en") == base()


@pytest.mark.parametrize("signals", [None, {}, {"nailed": True}, {"nailed": True, "fixtures": True},
                                     {"nailed": True, "fixtures": True, "xgi_top": None}])
def test_missing_signals_mean_no_line(signals):
    assert plan_conclusions(diff_raw(5, signals=signals), "en") == base()


def test_no_ownership_numbers_mean_no_line():
    raw = _raw(_option("Isak", tops=[]))
    raw["ownership"] = {"target_signals": dict(GOOD)}
    assert plan_conclusions(raw, "en") == base()


# -- the wording is facts, never a forecast, and never wider than the reference ------------------------------------------

@pytest.mark.parametrize("raw", [diff_raw(5), diff_raw(None, 8), diff_raw(0), diff_raw(None, 0)])
def test_the_copy_never_forecasts_and_the_everyone_claim_names_its_reference(raw):
    en, es = last(raw, "en"), last(raw, "es")
    for word in ("will", "going to", "great", "bargain", "recommend", "sure", "expected"):
        assert word not in en.lower()
    for word in ("seguro", "recomend", "va a ", "ganga", "esperamos"):
        assert word not in es.lower()
    assert "almost everyone" not in en and "casi todos." not in es                     # never the unqualified claim
    assert ("of them" in en or "the whole top 10K" in en)
    assert ("ellos" in es or "todo el top 10K" in es)
    if "top 10K" in en.split(":")[1]:
        assert "the whole top 10K" in en and "todo el top 10K" in es                    # top 10K reference: top 10K, not everyone


# -- order, slot -------------------------------------------------------------------------------------------------------

def test_cover_comes_first_then_the_differential_then_no_exposure():
    # near 5 %, top 10K 45 %, selling a premium nobody near owns: the top-10K cover line wins
    raw = diff_raw(5, 45, sold={13: 4}, top_sold={13: 5}, options=[_option("Isak", tops=[top(13, "Isak")])])
    assert "moves you toward them" in last(raw, "en")
    # without a cover (top 10K low) the differential beats no-exposure
    raw = diff_raw(5, 20, sold={13: 4}, top_sold={13: 5}, options=[_option("Isak", tops=[top(13, "Isak")])])
    assert "if he scores" in last(raw, "en") and "expose" not in " ".join(plan_conclusions(raw, "en"))
    # with the signals failing the no-exposure line is still there
    raw = diff_raw(5, 20, signals={**GOOD, "xgi_top": False}, sold={13: 4}, options=[_option("Isak", tops=[top(13, "Isak")])])
    assert "expose" in last(raw, "en")


def test_the_differential_line_is_one_line_and_has_the_reserved_slot():
    option = _three_others()
    others = plan_conclusions(_raw(option), "en")
    assert len(others) == MAX_CONCLUSIONS
    lines = plan_conclusions(diff_raw(5, options=[option]), "en")
    assert len(lines) == MAX_CONCLUSIONS and lines[:2] == others[:2] and "if he scores" in lines[2]


def test_it_yields_to_an_unavailable_sold_player():
    out = _option("Isak", tops=[top(13, "Isak", "unavailable")], status="i", chance=0)
    out["sold"] = [{"id": 13, "web_name": "Isak", "hard_fixtures": 3, "availability": "unavailable", "set_pieces": 0},
                   {"id": 14, "web_name": "Haaland", "hard_fixtures": 3, "availability": "rotation", "set_pieces": 0},
                   {"id": 15, "web_name": "Salah", "hard_fixtures": 4, "availability": None, "set_pieces": 0}]
    full = plan_conclusions(_raw(out), "en")
    assert plan_conclusions(diff_raw(5, options=[out]), "en") == full


# -- the display conditions come from the existing PlanSignals ------------------------------------------------------------

class Sig:
    def __init__(self, tier=2, games=5, band=2.5, hard=0, reasons=("xgi",), boom=False):
        self.tier, self.games, self.band, self.hard, self.reasons, self.boom = tier, games, band, hard, list(reasons), boom

    def availability(self, pid):
        if self.boom:
            raise RuntimeError("boom")
        return {"tier": self.tier, "reason": None}

    def fixtures(self, pid):
        return {"games": self.games, "avg_band": self.band, "hard": self.hard}

    def top(self, pid):
        return {"is_top": bool(self.reasons), "reasons": self.reasons}


def test_target_signals_all_good():
    assert plan_eo.target_signals(Sig(), 100) == GOOD


@pytest.mark.parametrize("kw,failing", [
    ({"tier": 1}, "nailed"),                       # doubtful or a rotation risk
    ({"tier": 0}, "nailed"),                       # unavailable
    ({"games": 2}, "fixtures"), ({"band": None}, "fixtures"), ({"band": 3.01}, "fixtures"), ({"hard": 2}, "fixtures"),
    ({"reasons": ()}, "xgi_top"), ({"reasons": ("price", "owned")}, "xgi_top"),
])
def test_target_signals_each_condition(kw, failing):
    got = plan_eo.target_signals(Sig(**kw), 100)
    assert got[failing] is False and sum(got.values()) == 2


def test_target_signals_boundaries_are_inclusive():
    assert plan_eo.target_signals(Sig(games=3, band=3.0, hard=1), 100)["fixtures"] is True


def test_a_failing_signal_source_is_all_false():
    assert plan_eo.target_signals(Sig(boom=True), 100) == {"nailed": False, "fixtures": False, "xgi_top": False}


def test_plan_to_sign_attaches_the_conditions_with_the_numbers_and_hides_them_from_the_model(stack):
    from fpl_grounded_assistant.orchestrator import _truncate_tool_output

    mp = stack.monkeypatch
    mp.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    put_near(stack.svc, {"100": stats(4.0)})
    res = _plan(mp, {"events": EVENTS, "_my_team_id": TEAM})
    signals = res["ownership"]["target_signals"]
    assert set(signals) == {"nailed", "fixtures", "xgi_top"} and all(isinstance(v, bool) for v in signals.values())
    assert signals["xgi_top"] is False                       # no finished gameweeks: early season, no xGI cut-off
    assert "target_signals" not in json.dumps(_truncate_tool_output(res, tool_name="plan_to_sign"))
    # no numbers cached: no ownership block at all, so no signals either (the card is today's)
    assert "ownership" not in _plan(mp, {"events": EVENTS, "_my_team_id": TEAM + 1})
