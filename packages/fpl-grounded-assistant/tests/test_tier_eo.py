"""The top-10K EO reader, tool, card, chips and /healthz block (synthetic data, no network, no LLM)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from fpl_grounded_assistant import harness, league_eo_tool, near_rank_eo_tool, orchestrator, tier_eo_reader, tier_eo_tool
from fpl_grounded_assistant.atomic_tool_cards import compose_tier_eo_card, maybe_atomic_tool_card
from fpl_grounded_assistant.orch_config import TIER_EO_ENABLED_ENV
from fpl_grounded_assistant.tool_schema_registry import TIER_EO_SCHEMA, get_offered_tool_names

SEASON = "2026-2027"
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
EVENTS = [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"}, {"id": 11, "deadline_time": "2026-11-01T10:00:00Z"},
          {"id": 12, "deadline_time": "2026-11-20T10:00:00Z"}, {"id": 13, "deadline_time": "2026-12-01T10:00:00Z"}]
TEAMS = [{"id": 1, "short_name": "T1"}]
ELEMENTS = [{"id": i, "web_name": f"P{i}", "second_name": f"S{i}", "team": 1} for i in range(1, 8)]
BOOT = {"teams": TEAMS, "elements": ELEMENTS, "events": EVENTS}


def stats(owned, eo, cap=0.0):
    return {"owned_pct": owned, "captain_pct": cap, "bench_pct": 0.0, "eo": eo}


PLAYERS = {"1": stats(90.0, 95.0), "2": stats(80.0, 140.0, 50.0), "3": stats(55.0, 55.0), "7": stats(10.0, 10.0)}


def doc(gw=12, season=SEASON, tier="top10k"):
    return {"schema_version": 1, "season": season, "gw": gw, "tier": tier, "n_sampled": 2000, "players": PLAYERS}


class Store:
    """A fake R2: key -> bytes, recording the GETs."""

    def __init__(self, files=None, boom=False):
        self.files, self.gets, self.boom = files or {}, [], boom

    def __call__(self, key):
        self.gets.append(key)
        if self.boom:
            raise RuntimeError("synthetic outage")
        return self.files.get(key)


def put(store, gw, prefix="", **kw):
    store.files[tier_eo_reader.object_key(prefix, SEASON, gw, "top10k")] = json.dumps(doc(gw, **kw)).encode()


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(TIER_EO_ENABLED_ENV, raising=False)
    tier_eo_reader.set_reader(None)
    monkeypatch.setattr(tier_eo_tool, "load_linked_squad", lambda b, gw: None)  # never the FPL API
    yield
    tier_eo_reader.set_reader(None)


def reader(store, clock=None, prefix=""):
    r = tier_eo_reader.TierEOReader(fetch=store, prefix=lambda: prefix, clock=clock or Clock())
    tier_eo_reader.set_reader(r)
    return r


def on(monkeypatch):
    monkeypatch.setenv(TIER_EO_ENABLED_ENV, "1")


# -- the reader ----------------------------------------------------------------------------------------------

def test_the_key_is_exactly_prefix_eo_season_gw_tier_and_nothing_else_is_buildable():
    assert tier_eo_reader.object_key("pre/", SEASON, 12, "top10k") == "pre/eo/2026-2027/gw12/top10k.json"
    for bad in [("", "../x", 12, "top10k"), ("", SEASON, 0, "top10k"), ("", SEASON, True, "top10k"),
                ("", SEASON, 12, "../top10k"), ("", SEASON, 12, "top100k")]:
        with pytest.raises(ValueError):
            tier_eo_reader.object_key(*bad)


def test_read_returns_the_file_and_caches_hits_and_misses_separately():
    store, clock = Store(), Clock()
    put(store, 12)
    r = reader(store, clock)
    assert r.read(SEASON, 12)["gw"] == 12 and r.read(SEASON, 12)["gw"] == 12 and len(store.gets) == 1
    assert r.read(SEASON, 13) is None and r.read(SEASON, 13) is None and len(store.gets) == 2
    clock.t += tier_eo_reader.MISS_TTL_S + 1                  # a miss is retried after its short TTL ...
    put(store, 13)
    assert r.read(SEASON, 13)["gw"] == 13 and len(store.gets) == 3
    clock.t += tier_eo_reader.MISS_TTL_S + 1                  # ... while a hit is still cached
    assert r.read(SEASON, 12) and len(store.gets) == 3


def test_the_prefix_is_applied_to_the_key():
    store = Store()
    put(store, 12, prefix="p/")
    assert reader(store, prefix="p/").read(SEASON, 12) is not None
    assert reader(Store(), prefix="").read(SEASON, 12) is None


@pytest.mark.parametrize("body", [
    b"not json",
    json.dumps({"players": []}).encode(),
    json.dumps(doc(11)).encode(),                              # a file that says another gameweek
    json.dumps(doc(12, season="2025-2026")).encode(),
])
def test_a_malformed_or_mislabelled_file_is_not_found(body):
    assert reader(Store({"eo/2026-2027/gw12/top10k.json": body})).read(SEASON, 12) is None


def test_a_storage_failure_is_not_found_and_never_raises():
    assert reader(Store(boom=True)).read(SEASON, 12) is None


def test_latest_goes_back_at_most_one_gameweek():
    store = Store()
    put(store, 11)
    assert reader(store).latest(SEASON, 12)["gw"] == 11        # one back: fine
    far = Store()
    put(far, 10)
    assert reader(far).latest(SEASON, 12) is None              # two back: unavailable
    put(far, 12)
    assert reader(far).latest(SEASON, 12)["gw"] == 12          # the requested one wins


# -- the tool ------------------------------------------------------------------------------------------------

def test_flag_off_is_disabled_and_reads_nothing():
    store = Store()
    reader(store)
    assert tier_eo_tool.get_tier_eo(BOOT, now=NOW)["status"] == "disabled" and store.gets == []


def test_ready_answer_names_the_gameweek_of_the_file_and_marks_older_picks(monkeypatch):
    on(monkeypatch)
    store = Store()
    put(store, 12)
    reader(store)
    out = tier_eo_tool.get_tier_eo(BOOT, now=NOW)
    assert out["status"] == "ok" and out["tier"] == "top10k" and out["gw"] == 12 and not out["picks_from_older_gw"]
    assert out["label"] == "sample, n=2000" and out["top_players"][0]["player"] == "P2"
    older = Store()
    put(older, 11)
    reader(older)
    out = tier_eo_tool.get_tier_eo(BOOT, now=NOW)
    assert out["gw"] == 11 and out["requested_gw"] == 12 and out["picks_from_older_gw"] is True
    assert "GW 11 picks" in out["note"] and "not published yet" in out["note"]


def test_nothing_published_or_too_old_is_unavailable_without_numbers(monkeypatch):
    on(monkeypatch)
    reader(Store())
    out = tier_eo_tool.get_tier_eo(BOOT, now=NOW)
    assert out["status"] == "unavailable" and out["reason"] == "not_published_yet" and "top_players" not in out
    assert tier_eo_tool.get_tier_eo({**BOOT, "events": []}, now=NOW)["reason"] == "no_gameweek"


def test_it_needs_no_team_and_compares_the_squad_when_there_is_one(monkeypatch):
    on(monkeypatch)
    store = Store()
    put(store, 12)
    reader(store)
    assert tier_eo_tool.get_tier_eo(BOOT, now=NOW)["squad_compared"] is False
    monkeypatch.setattr(tier_eo_tool, "load_linked_squad", lambda b, gw: {"status": "ok", "players": [{"id": 1}, {"id": 7}]})
    out = tier_eo_tool.get_tier_eo({**BOOT, "_my_team_id": 5}, now=NOW)
    assert out["squad_compared"] and [r["player"] for r in out["group_has"]] == ["P2", "P3"]
    assert all(r["user_owns"] is False for r in out["group_has"]) and [r["player"] for r in out["differentials"]] == ["P7"]

    def boom(b, gw):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(tier_eo_tool, "load_linked_squad", boom)
    assert tier_eo_tool.get_tier_eo({**BOOT, "_my_team_id": 5}, now=NOW)["squad_compared"] is False


def test_the_note_carries_the_wording_rules(monkeypatch):
    on(monkeypatch)
    store = Store()
    put(store, 12)
    reader(store)
    note = tier_eo_tool.get_tier_eo(BOOT, now=NOW)["note"]
    assert "Top 10K has him" in note and "El top 10K lo tiene" in note and "AT MOST 2 short conclusions" in note
    assert "NEVER use threat words" in note


def test_the_tool_is_opt_in_and_its_text_is_one_text(monkeypatch):
    assert "get_tier_eo" not in get_offered_tool_names(False)
    assert "get_tier_eo" in get_offered_tool_names(False, tier_eo_enabled=True)
    assert "get_tier_eo" not in str(orchestrator._build_tools(None, football_intelligence_enabled=False))
    on(monkeypatch)
    assert "get_tier_eo" in str(orchestrator._build_tools(None, football_intelligence_enabled=False))
    assert tier_eo_tool.TIER_EO_SPEC.description is TIER_EO_SCHEMA.description
    assert "top 10K" in TIER_EO_SCHEMA.description and "get_near_rank_eo" in TIER_EO_SCHEMA.description


# -- the card --------------------------------------------------------------------------------------------------

def shaped(squad=None, gw=12):
    return tier_eo_tool.shape_result(doc(gw), BOOT, [], squad, 12)


def test_the_card_says_which_gameweek_the_picks_are_from_in_both_languages():
    en = compose_tier_eo_card(shaped(), "en")
    assert en.title == "EO top 10K" and en.subtitle == "Top 10K · GW 12 picks · sample n=2000"
    assert compose_tier_eo_card(shaped(), "es").subtitle == "Top 10K · picks de la GW 12 · muestra n=2000"
    assert compose_tier_eo_card(shaped(gw=11), "es").subtitle == "Top 10K · picks de la GW 11 · muestra n=2000"


def test_the_card_uses_the_same_two_groups_and_tones():
    from fpl_grounded_assistant.generic_card import generic_card_to_dict

    card = compose_tier_eo_card(shaped({"status": "ok", "players": [{"id": 1}, {"id": 7}]}), "en")
    assert card.rows[0][0] == "Top 10K has him" and card.rows[-1][0] == "Your differential"
    assert generic_card_to_dict(card)["badge_tones"] == {"Top 10K has him": "neutral", "Top EO": "neutral",
                                                         "Your differential": "good"}
    assert compose_tier_eo_card({"status": "unavailable"}, "en") is None
    assert maybe_atomic_tool_card("get_tier_eo", shaped(), None, "en") is not None


# -- the chips ---------------------------------------------------------------------------------------------------

def chips(tool, raw, locale="es"):
    return [c["send_text"] for c in (harness._eo_switch_chips(tool, raw, locale) or [])]


def test_the_top_10k_chip_appears_under_the_other_cards_only_when_the_reader_is_on(monkeypatch):
    league = league_eo_tool.shape_result({"gw": 1, "league_id": 7, "league_name": "L", "league_size": 5, "exact": True,
                                          "approx": False, "n_sampled": 5, "label": "exact, n=5", "players": PLAYERS},
                                         BOOT, [], None)
    near_data = {"gw": 1, "user_rank": 9, "n_sampled": 5, "players": PLAYERS, "leagues": [{"id": 8, "name": "Work"}]}
    near = near_rank_eo_tool.shape_result(near_data, {**BOOT, "_my_league_id": 8}, [], None)
    no_league = near_rank_eo_tool.shape_result(near_data, BOOT, [], None)
    assert chips("get_league_eo", league) == ["EO cerca de tu puesto"]            # flag off: unchanged
    assert chips("get_near_rank_eo", near) == ["EO en Work"]
    on(monkeypatch)
    assert chips("get_league_eo", league) == ["EO cerca de tu puesto", "EO top 10K"]
    assert chips("get_near_rank_eo", near) == ["EO en Work", "EO top 10K"]
    assert chips("get_near_rank_eo", no_league) == ["EO top 10K"]
    assert chips("get_tier_eo", shaped()) == ["EO cerca de tu puesto"]            # back to the personal view
    assert chips("get_tier_eo", {"status": "unavailable"}) == []


# -- /healthz ----------------------------------------------------------------------------------------------------

def test_healthz_reports_the_flag_and_the_latest_gw_found_and_nothing_secret(monkeypatch):
    import fpl_server
    from fastapi.testclient import TestClient

    events = [{"id": i, "deadline_time": f"2026-0{i}-01T00:00:00Z"} for i in range(1, 10)]
    fpl_server._init_bootstrap({**BOOT, "events": events})
    client = TestClient(fpl_server.app)
    assert client.get("/healthz").json()["tier_eo"] == {"enabled": False, "latest_gw_found": None}
    on(monkeypatch)
    monkeypatch.setattr(tier_eo_tool, "_season", lambda b: SEASON)
    store = Store()
    store.files[tier_eo_reader.object_key("SECRET-PREFIX/", SEASON, 9, "top10k")] = json.dumps(doc(9)).encode()
    r = reader(store, prefix="SECRET-PREFIX/")
    assert client.get("/healthz").json()["tier_eo"] == {"enabled": True, "latest_gw_found": None}  # cold cache: no GET
    assert store.gets == []
    assert r.latest(SEASON, 9) is not None                                                       # a turn read it
    assert client.get("/healthz").json()["tier_eo"] == {"enabled": True, "latest_gw_found": 9}
    assert "SECRET" not in client.get("/healthz").text
    reader(Store())
    assert client.get("/healthz").json()["tier_eo"] == {"enabled": True, "latest_gw_found": None}


# -- R2 client timeouts, fail-soft, and /healthz never waiting on R2 -------------------------------------------------

def test_the_reader_client_has_its_own_short_timeouts(monkeypatch):
    from fpl_grounded_assistant import owned_store_sync as sync

    cfg = tier_eo_reader._client_config()
    assert (cfg.connect_timeout, cfg.read_timeout) == (3, 5)
    assert cfg.retries == {"max_attempts": 2, "mode": "standard"}
    seen = {}
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: seen.update(k) or object())
    for name in (sync.ENV_R2_ENDPOINT, sync.ENV_R2_BUCKET, sync.ENV_R2_ACCESS_KEY_ID, sync.ENV_R2_SECRET_ACCESS_KEY):
        monkeypatch.setenv(name, "x")
    tier_eo_reader._make_client()
    assert seen["config"].read_timeout == 5 and seen["region_name"] == "auto"
    sync_seen = {}
    monkeypatch.setattr(boto3, "client", lambda *a, **k: sync_seen.update(k) or object())
    sync._make_r2_client()
    assert "config" not in sync_seen                      # the startup sync keeps boto3's defaults


def test_a_timeout_is_not_found_and_cached_as_a_miss():
    class Timeout(Exception):
        pass

    calls = []

    def fetch(key):
        calls.append(key)
        raise Timeout("Read timeout on endpoint URL")

    clock = Clock()
    r = tier_eo_reader.TierEOReader(fetch=fetch, prefix=lambda: "", clock=clock)
    assert r.read(SEASON, 12) is None
    n = len(calls)
    assert r.read(SEASON, 12) is None and len(calls) == n          # cached miss: no second GET
    clock.t += tier_eo_reader.MISS_TTL_S + 1
    r.read(SEASON, 12)
    assert len(calls) == n + 1                                      # retried after MISS_TTL_S


def test_the_r2_fetch_uses_the_reader_client(monkeypatch):
    from fpl_grounded_assistant import owned_store_sync as sync

    class Client:
        def get_object(self, **kw):
            raise TimeoutError("read timeout")

    monkeypatch.setattr(tier_eo_reader, "_get_client", lambda: Client())
    monkeypatch.setenv(sync.ENV_R2_BUCKET, "b")
    r = tier_eo_reader.TierEOReader(prefix=lambda: "")           # default fetch = _r2_fetch
    assert r.read(SEASON, 12) is None


def test_latest_cached_never_fetches():
    store = Store()
    put(store, 12)
    r = tier_eo_reader.TierEOReader(fetch=store, prefix=lambda: "", clock=Clock())
    assert r.latest_cached(SEASON, 12) is None and store.gets == []
    assert r.latest(SEASON, 12) is not None
    n = len(store.gets)
    assert r.latest_cached(SEASON, 12)["gw"] == 12 and r.latest_cached(SEASON, 13)["gw"] == 12  # one gw back
    assert len(store.gets) == n
