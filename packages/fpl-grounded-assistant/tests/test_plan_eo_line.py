"""The EO line on the plan_to_sign card: cover (near / top 10K), no exposure, the reserved slot, cache-only reads.

Synthetic ids and numbers only. No network, no model, no real R2: the near-rank service and the top 10K reader are
real objects over fakes that RECORD every call, so "no tap starts a job or does a GET" is checked, not assumed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import importlib

from fpl_grounded_assistant import eo_warm, near_rank_eo_tool, plan_eo, tier_eo_reader
from fpl_grounded_assistant.atomic_tool_cards import compose_plan_to_sign_card
from fpl_grounded_assistant.near_rank_eo import NearRankEOService
from fpl_grounded_assistant.orch_config import NEAR_RANK_EO_ENABLED_ENV, TIER_EO_ENABLED_ENV
from fpl_grounded_assistant.plan_card import MAX_CONCLUSIONS, plan_conclusions
from test_plan_card import _option, _raw
from test_plan_to_sign import _bootstrap, _squad_payload

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")

SEASON = "2026-2027"
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
EVENTS = [{"id": 11, "deadline_time": "2026-11-01T10:00:00Z"}, {"id": 12, "deadline_time": "2099-01-01T10:00:00Z"}]
GW = 11
TEAM = 7_000_001


def stats(owned):
    return {"owned_pct": owned, "captain_pct": 0.0, "bench_pct": 0.0, "eo": owned}


def top(pid, name, why="only_way"):
    return {"id": pid, "web_name": name, "reasons": ["price"], "why": why}


def eo_raw(near_target=None, top_target=None, sold=None, options=None, top_sold=None, **extra):
    """A plan raw output carrying the ``ownership`` block ``plan_eo.read`` would attach.

    Every player the options sell gets 0 in each reference unless ``sold`` / ``top_sold`` say otherwise.
    """
    raw = _raw(*(options or [_option("Isak", tops=[top(13, "Isak")])]), **extra)
    ids = {s["id"] for o in raw["options"] for s in o["sold"]}
    own = {}
    if near_target is not None or sold is not None:
        near_sold = {str(i): 0 for i in ids}
        near_sold.update({str(k): v for k, v in (sold or {}).items()})
        own["near_rank_owned_pct"] = {"target": near_target if near_target is not None else 0, "sold": near_sold}
    if top_target is not None:
        top_sold_d = {str(i): 0 for i in ids}
        top_sold_d.update({str(k): v for k, v in (top_sold or {}).items()})
        own["top10k_owned_pct"] = {"target": top_target, "sold": top_sold_d}
    if own:
        raw["ownership"] = own
    return raw


# -- cover lines ------------------------------------------------------------------------------------------------

def test_cover_with_near_and_top():
    assert plan_conclusions(eo_raw(30, 45, sold={13: 5}), "es")[-1] == (
        "N.Jackson: lo tiene el 30 % cerca de tu puesto y el 45 % del top 10K: ficharlo te cubre.")
    assert plan_conclusions(eo_raw(30, 45, sold={13: 5}), "en")[-1] == (
        "N.Jackson: 30% near your rank and 45% of the top 10K have him; signing him covers you.")


def test_cover_with_near_only_when_the_top_10k_is_not_cached():
    assert plan_conclusions(eo_raw(25, None, sold={13: 5}), "en")[-1] == (
        "N.Jackson: 25% near your rank have him; signing him covers you.")


def test_top_10k_is_the_aspirational_line_when_near_is_not_material_or_missing():
    # near known but low, top 10K high
    assert plan_conclusions(eo_raw(24, 40, sold={13: 5}), "es")[-1] == (
        "N.Jackson: lo tiene el 40 % del top 10K: ficharlo te acerca a ellos.")
    # no near-rank data at all (no team or not computed): top 10K only
    raw = eo_raw(None, 55)
    assert "near_rank_owned_pct" not in raw["ownership"]
    assert plan_conclusions(raw, "en")[-1] == "N.Jackson: 55% of the top 10K have him; signing him moves you toward them."


@pytest.mark.parametrize("near,top_pct", [(24, 39), (10, 20), (0, 0)])
def test_between_the_thresholds_there_is_no_line(near, top_pct):
    assert plan_conclusions(eo_raw(near, top_pct, sold={13: 50}), "en") == plan_conclusions(_raw(_option("Isak", tops=[top(13, "Isak")])), "en")


# -- no exposure ------------------------------------------------------------------------------------------------

def test_no_exposure_names_the_premium_that_is_sold():
    raw = eo_raw(5, None, sold={13: 10})
    assert plan_conclusions(raw, "es")[-1] == "Vender a Isak no te expone: casi nadie cerca de tu puesto lo tiene."
    assert plan_conclusions(raw, "en")[-1] == "Selling Isak doesn't expose you: almost nobody near your rank has him."


@pytest.mark.parametrize("sold_pct", [11, 50])
def test_no_exposure_needs_the_premium_to_be_rare(sold_pct):
    assert plan_conclusions(eo_raw(5, None, sold={13: sold_pct}), "en") == plan_conclusions(_raw(_option("Isak", tops=[top(13, "Isak")])), "en")


def test_no_exposure_is_only_about_premiums_not_any_sold_player():
    raw = eo_raw(5, None, sold={13: 0}, options=[_option("Isak", tops=[])])
    assert plan_conclusions(raw, "en") == plan_conclusions(_raw(_option("Isak", tops=[])), "en")


def test_when_the_option_sells_several_premiums_the_line_names_the_rarest_one():
    option = _option("Isak", tops=[top(13, "Isak"), top(14, "Haaland"), top(15, "Salah")])
    option["sold"] += [{"id": 14, "web_name": "Haaland", "hard_fixtures": 0, "availability": None, "set_pieces": 0},
                       {"id": 15, "web_name": "Salah", "hard_fixtures": 0, "availability": None, "set_pieces": 0}]
    line = plan_conclusions(eo_raw(5, None, {13: 9, 14: 2, 15: 6}, [option]), "en")[-1]
    assert line == "Selling Haaland doesn't expose you: almost nobody near your rank has him."
    tie = plan_conclusions(eo_raw(5, None, {13: 4, 14: 4, 15: 20}, [option]), "en")[-1]
    assert "Isak" in tie                                   # a tie: the lowest id, never ambiguous
    only_one_rare = plan_conclusions(eo_raw(5, None, {13: 20, 14: 20, 15: 3}, [option]), "en")[-1]
    assert "Salah" in only_one_rare


def test_cover_wins_over_no_exposure_and_there_is_one_eo_line():
    lines = plan_conclusions(eo_raw(30, 45, sold={13: 1}), "en")
    assert sum("have him" in ln or "expose" in ln for ln in lines) == 1 and "covers you" in lines[-1]


# -- the reserved slot --------------------------------------------------------------------------------------------

def _three_others(raw_extra=None):
    """Three conclusions that are not about availability: a hard run, few starts and 'every way sells a top'."""
    sold = [
        {"id": 13, "web_name": "Isak", "hard_fixtures": 3, "availability": None, "set_pieces": 0},
        {"id": 14, "web_name": "Haaland", "hard_fixtures": 0, "availability": "rotation", "set_pieces": 0},
        {"id": 15, "web_name": "Salah", "hard_fixtures": 4, "availability": None, "set_pieces": 0},
    ]
    return _option("Isak", tops=[top(13, "Isak")], sold=sold)


def test_the_eo_line_takes_a_reserved_slot_when_the_others_would_fill_the_cap():
    option = _three_others()
    base = plan_conclusions(_raw(option), "en")
    assert len(base) == MAX_CONCLUSIONS
    lines = plan_conclusions(eo_raw(30, 45, sold={13: 5}, options=[option]), "en")
    assert len(lines) == MAX_CONCLUSIONS
    assert lines[:2] == base[:2] and "covers you" in lines[2]


def test_the_eo_line_yields_to_a_sold_player_who_is_out_or_doubtful():
    out = _option("Isak", tops=[top(13, "Isak", "unavailable")], status="i", chance=0)
    out["sold"] = [{"id": 13, "web_name": "Isak", "hard_fixtures": 3, "availability": "unavailable", "set_pieces": 0},
                   {"id": 14, "web_name": "Haaland", "hard_fixtures": 3, "availability": "rotation", "set_pieces": 0},
                   {"id": 15, "web_name": "Salah", "hard_fixtures": 4, "availability": None, "set_pieces": 0}]
    base = plan_conclusions(_raw(out), "en")
    assert len(base) == MAX_CONCLUSIONS and "lists him as out" in base[0]
    assert plan_conclusions(eo_raw(30, 45, sold={13: 5}, options=[out]), "en") == base      # cap full: the EO line is dropped
    roomy = _option("Isak", tops=[], status="i", chance=0)
    roomy["sold"] = [{"id": 13, "web_name": "Isak", "hard_fixtures": 0, "availability": "unavailable", "set_pieces": 0}]
    lines = plan_conclusions(eo_raw(30, 45, sold={13: 5}, options=[roomy]), "en")
    assert len(lines) == 2 and "lists him as out" in lines[0] and "covers you" in lines[1]  # room: it is shown


def test_a_doubtful_sold_player_also_wins_the_slot():
    doubt = _option("Isak", tops=[top(13, "Isak", "unavailable")], status="d", chance=50)
    doubt["sold"] = [{"id": 13, "web_name": "Isak", "hard_fixtures": 3, "availability": "doubt", "set_pieces": 0},
                     {"id": 14, "web_name": "Haaland", "hard_fixtures": 3, "availability": "rotation", "set_pieces": 0},
                     {"id": 15, "web_name": "Salah", "hard_fixtures": 4, "availability": None, "set_pieces": 0}]
    base = plan_conclusions(_raw(doubt), "en")
    assert plan_conclusions(eo_raw(30, 45, sold={13: 5}, options=[doubt]), "en") == base


# -- byte-identical without data ----------------------------------------------------------------------------------

def test_without_eo_data_the_conclusions_and_the_card_are_identical_to_today():
    option = _three_others()
    plain = _raw(option)
    for eo in ({}, None):
        with_key = {**plain, "ownership": eo}
        for locale in ("es", "en"):
            assert plan_conclusions(with_key, locale) == plan_conclusions(plain, locale)
            card_a, card_b = compose_plan_to_sign_card(plain, locale), compose_plan_to_sign_card(with_key, locale)
            assert card_a == card_b and repr(card_a) == repr(card_b)


# -- plan_eo.read: cache-only -------------------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append(args)


class Store:
    def __init__(self, files=None):
        self.files, self.gets = files or {}, []

    def __call__(self, key):
        self.gets.append(key)
        return self.files.get(key)


@pytest.fixture
def stack(monkeypatch):
    for name in (NEAR_RANK_EO_ENABLED_ENV, TIER_EO_ENABLED_ENV):
        monkeypatch.delenv(name, raising=False)
    rec = Recorder()

    def no_net(*a, **k):
        raise AssertionError("a tap must not reach the FPL API")

    svc = NearRankEOService(fetch=no_net, executor=rec)
    near_rank_eo_tool.set_service(svc)
    store = Store()
    reader = tier_eo_reader.TierEOReader(fetch=store, prefix=lambda: "", clock=lambda: 1000.0)
    tier_eo_reader.set_reader(reader)
    monkeypatch.setattr(near_rank_eo_tool, "_season", lambda b: SEASON)
    yield NS(svc=svc, rec=rec, store=store, reader=reader, monkeypatch=monkeypatch)
    near_rank_eo_tool.set_service(None)
    tier_eo_reader.set_reader(None)


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


BOOT = {"events": EVENTS, "_my_team_id": TEAM}


def put_near(svc, players):
    svc._store((SEASON, GW, TEAM), {"status": "ready", "data": {"players": players}}, 10 ** 12)


def put_top(store, players, gw=GW):
    store.files[tier_eo_reader.object_key("", SEASON, gw, "top10k")] = json.dumps(
        {"season": SEASON, "gw": gw, "tier": "top10k", "n_sampled": 2000, "players": players}).encode()


def test_flags_off_reads_nothing(stack):
    put_near(stack.svc, {"100": stats(40.0)})
    assert plan_eo.read(BOOT, 100, {13}, NOW) is None
    assert stack.store.gets == [] and stack.rec.jobs == []


def test_near_rank_is_a_cache_peek_a_cold_service_starts_no_job(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    assert plan_eo.read(BOOT, 100, {13}, NOW) is None
    assert stack.rec.jobs == [] and stack.svc.started == 0


def test_a_computing_job_gives_no_number_and_is_not_started_again(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    stack.svc.status(SEASON, GW, TEAM)                       # the warm path started it
    started = stack.svc.started
    assert plan_eo.read(BOOT, 100, {13}, NOW) is None and stack.svc.started == started


def test_a_ready_near_rank_gives_rounded_numbers_and_absent_means_zero(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    put_near(stack.svc, {"100": stats(30.4), "13": stats(3.6)})
    got = plan_eo.read(BOOT, 100, {13, 14}, NOW)
    assert got == {"near_rank_owned_pct": {"target": 30, "sold": {"13": 4, "14": 0}}}


def test_the_top_10k_is_read_from_the_cache_only_never_fetched(stack):
    stack.monkeypatch.setenv(TIER_EO_ENABLED_ENV, "1")
    put_top(stack.store, {"100": stats(45.0)})
    assert plan_eo.read(BOOT, 100, {13}, NOW) is None        # cold: no GET on a tap
    assert stack.store.gets == []
    stack.reader.latest(SEASON, GW)                          # the warm path's pre-read
    n = len(stack.store.gets)
    assert plan_eo.read(BOOT, 100, {13}, NOW) == {"top10k_owned_pct": {"target": 45, "sold": {"13": 0}}}
    assert len(stack.store.gets) == n


def test_no_team_means_no_near_numbers_but_the_top_10k_still_reads(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    stack.monkeypatch.setenv(TIER_EO_ENABLED_ENV, "1")
    put_near(stack.svc, {"100": stats(40.0)})
    put_top(stack.store, {"100": stats(50.0)})
    stack.reader.latest(SEASON, GW)
    assert plan_eo.read({"events": EVENTS}, 100, {13}, NOW) == {"top10k_owned_pct": {"target": 50, "sold": {"13": 0}}}


def test_a_failure_gives_none(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")

    class Boom:
        def peek(self, *a):
            raise RuntimeError("boom")

    near_rank_eo_tool.set_service(Boom())
    assert plan_eo.read(BOOT, 100, {13}, NOW) is None


# -- end to end through plan_to_sign --------------------------------------------------------------------------------

def _plan(monkeypatch, boot_extra):
    monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: _squad_payload(30))
    boot = {**_bootstrap(), **boot_extra}
    return pts.plan_to_sign(target="N.Jackson", moves="one", bootstrap=boot)


def test_plan_to_sign_carries_eo_only_when_there_are_numbers(stack):
    mp = stack.monkeypatch
    off = _plan(mp, {"events": EVENTS, "_my_team_id": TEAM})
    assert off["stage"] == "plan" and "ownership" not in off  # flags off: the output is today's
    mp.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    assert "ownership" not in _plan(mp, {"events": EVENTS, "_my_team_id": TEAM})   # nothing cached
    put_near(stack.svc, {"100": stats(31.0)})
    res = _plan(mp, {"events": EVENTS, "_my_team_id": TEAM})
    near = res["ownership"]["near_rank_owned_pct"]
    assert near["target"] == 31 and set(near["sold"]) <= {str(i) for i in range(1, 16)}
    assert stack.rec.jobs == [] and stack.svc.started == 0   # reading started nothing
    assert any("covers you" in ln or "te cubre" in ln for ln in plan_conclusions(res, "en") + plan_conclusions(res, "es"))


# -- warm path pre-reads the top 10K ------------------------------------------------------------------------------

def test_warm_prefetches_the_top_10k_off_the_request_and_at_most_once_a_minute(stack):
    mp = stack.monkeypatch
    mp.setenv(TIER_EO_ENABLED_ENV, "1")
    put_top(stack.store, {"100": stats(45.0)})
    eo_warm.reset()
    eo_warm._PREFETCH_AT[0] = float("-inf")
    spawned = []
    mp.setattr(eo_warm, "_spawn", lambda fn: spawned.append(fn))
    eo_warm.warm(BOOT, TEAM, None, user_key="u1", now=NOW)
    assert len(spawned) == 1 and stack.store.gets == []      # the request itself did no GET
    eo_warm.warm(BOOT, TEAM, None, user_key="u1", now=NOW)
    assert len(spawned) == 1                                 # throttled
    spawned[0]()                                             # the worker thread runs
    assert stack.store.gets and plan_eo.read(BOOT, 100, set(), NOW) == {"top10k_owned_pct": {"target": 45, "sold": {}}}
    eo_warm._PREFETCH_AT[0] = float("-inf")
    eo_warm.warm(BOOT, TEAM, None, user_key="u1", now=NOW)
    assert len(spawned) == 1                                 # cached now: nothing to pre-read


def test_warm_does_not_prefetch_when_the_tier_flag_is_off(stack):
    spawned = []
    stack.monkeypatch.setattr(eo_warm, "_spawn", lambda fn: spawned.append(fn))
    eo_warm._PREFETCH_AT[0] = float("-inf")
    eo_warm.warm(BOOT, TEAM, None, user_key="u1", now=NOW)
    assert spawned == []


# -- review: net exposure, per hero option, missing is not zero, the model view ----------------------------------------

def test_a_cover_line_needs_every_sold_player_to_be_owned_less_than_the_target():
    # sell a 50 % player to buy a 30 % one: signing him does not cover (it was shown before this change)
    assert plan_conclusions(eo_raw(30, None, sold={13: 50}), "en") == plan_conclusions(_raw(_option("Isak", tops=[top(13, "Isak")])), "en")
    # owned exactly as much is not "less" either
    assert "covers" not in " ".join(plan_conclusions(eo_raw(30, None, sold={13: 30}), "en"))
    assert "covers" in " ".join(plan_conclusions(eo_raw(30, None, sold={13: 29}), "en"))


def test_the_combined_copy_needs_both_references_to_hold_and_falls_back_to_the_one_that_does():
    both = plan_conclusions(eo_raw(30, 45, sold={13: 5}, top_sold={13: 5}), "en")[-1]
    assert "30% near your rank and 45% of the top 10K" in both
    only_near = plan_conclusions(eo_raw(30, 45, sold={13: 5}, top_sold={13: 60}), "en")[-1]       # top fails
    assert only_near == "N.Jackson: 30% near your rank have him; signing him covers you."
    only_top = plan_conclusions(eo_raw(30, 45, sold={13: 50}, top_sold={13: 5}), "en")[-1]        # near fails
    assert only_top == "N.Jackson: 45% of the top 10K have him; signing him moves you toward them."
    neither = plan_conclusions(eo_raw(30, 45, sold={13: 50}, top_sold={13: 60}), "en")
    assert neither == plan_conclusions(_raw(_option("Isak", tops=[top(13, "Isak")])), "en")


def test_the_net_exposure_is_checked_on_the_hero_option_and_follows_focus():
    covered = _option("Isak", tops=[top(13, "Isak")])                     # sells a 5 % player
    exposed = _option("Haaland", tops=[top(14, "Haaland")])
    exposed["transfers"][0]["out"]["id"] = 14
    exposed["sold"] = [{"id": 14, "web_name": "Haaland", "hard_fixtures": 0, "availability": None, "set_pieces": 0}]
    raw = eo_raw(30, None, sold={13: 5, 14: 60}, options=[covered, exposed])
    assert "covers" in plan_conclusions({**raw, "focus": 1}, "en")[-1]
    assert "covers" not in " ".join(plan_conclusions({**raw, "focus": 2}, "en"))


def test_no_exposure_is_not_shown_when_the_option_also_sells_someone_widely_owned():
    option = _option("Isak", tops=[top(13, "Isak")])
    option["sold"] += [{"id": 14, "web_name": "Haaland", "hard_fixtures": 0, "availability": None, "set_pieces": 0}]
    base = plan_conclusions(_raw(option), "en")
    assert plan_conclusions(eo_raw(5, None, {13: 4, 14: 60}, [option]), "en") == base          # the plan does expose
    assert plan_conclusions(eo_raw(5, None, {13: 4, 14: 25}, [option]), "en") == base          # at the cover bar
    assert "expose" in plan_conclusions(eo_raw(5, None, {13: 4, 14: 24}, [option]), "en")[-1]  # below it: fine


def test_an_unknown_number_makes_no_claim():
    option = _option("Isak", tops=[top(13, "Isak")])
    option["sold"] += [{"id": 14, "web_name": "Haaland", "hard_fixtures": 0, "availability": None, "set_pieces": 0}]
    base = plan_conclusions(_raw(option), "en")
    assert plan_conclusions(eo_raw(5, None, {13: 4, 14: None}, [option]), "en") == base        # no exposure: unknown sale
    assert plan_conclusions(eo_raw(5, None, {13: None, 14: 3}, [option]), "en") == base
    assert plan_conclusions(eo_raw(40, None, {13: 5, 14: None}, [option]), "en") == base       # cover: unknown sale


def test_a_row_without_a_valid_owned_pct_is_none_and_an_absent_player_is_zero():
    for bad in (None, "x", -3, 120, True, {}):
        assert plan_eo._pct({"13": {"owned_pct": bad}}, 13) is None
    assert plan_eo._pct({"13": "not a row"}, 13) is None
    assert plan_eo._pct({}, 13) == 0                                  # absent from the sample: nobody has him
    assert plan_eo._pct({"13": stats(0.4)}, 13) == 0 and plan_eo._pct({"13": stats(10.6)}, 13) == 11


def test_read_keeps_unusable_rows_as_none_and_drops_a_reference_with_a_bad_target(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    stack.monkeypatch.setenv(TIER_EO_ENABLED_ENV, "1")
    put_near(stack.svc, {"100": stats(40.0), "13": {"captain_pct": 1.0}, "14": stats(2.0)})   # 13: row without owned_pct
    put_top(stack.store, {"100": {"owned_pct": "bad"}})                                       # bad TARGET row
    stack.reader.latest(SEASON, GW)
    got = plan_eo.read(BOOT, 100, {13, 14, 15}, NOW)
    assert got == {"near_rank_owned_pct": {"target": 40, "sold": {"13": None, "14": 2, "15": 0}}}


def test_a_players_table_that_is_not_a_dict_is_no_data(stack):
    stack.monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    stack.svc._store((SEASON, GW, TEAM), {"status": "ready", "data": {"players": ["x"]}}, 10 ** 12)
    assert plan_eo.read(BOOT, 100, {13}, NOW) is None


def test_the_ownership_block_is_named_plainly_and_does_not_reach_the_model(stack):
    from fpl_grounded_assistant.orchestrator import _truncate_tool_output

    mp = stack.monkeypatch
    mp.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    put_near(stack.svc, {"100": stats(31.0)})
    res = _plan(mp, {"events": EVENTS, "_my_team_id": TEAM})
    assert "eo" not in res and set(res["ownership"]) == {"near_rank_owned_pct"}       # explicit name, not "eo"
    seen = json.dumps(_truncate_tool_output(res, tool_name="plan_to_sign"))             # what the model is sent
    assert "ownership" not in seen and "owned_pct" not in seen and '"eo"' not in seen
    assert "ownership" in res and res["stage"] == "plan"                                # the real output keeps it
