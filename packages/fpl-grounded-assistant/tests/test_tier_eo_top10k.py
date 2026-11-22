"""scripts/tier_eo_top10k.py with a fake API and fake S3 (synthetic data only, no network)."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "tier_eo_top10k.py"
spec = importlib.util.spec_from_file_location("tier_eo_top10k", SCRIPT)
eo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eo)

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
BOOT = {"events": [
    {"id": 11, "deadline_time": "2026-11-01T10:00:00Z"},
    {"id": 12, "deadline_time": "2026-11-20T10:00:00Z"},
    {"id": 13, "deadline_time": "2026-12-01T10:00:00Z"},
]}
QUIET = lambda *a: None  # noqa: E731


def picks_for(*, variant: bool = False) -> dict:
    """15 synthetic picks: player 1 captained (x2), 11 starters, 4 on the bench."""
    ids = list(range(1, 16))
    if variant:
        ids[1] = 99
    return {"active_chip": None, "picks": [
        {"element": e, "position": i + 1, "multiplier": 0 if i >= 11 else (2 if i == 0 else 1), "is_captain": i == 0}
        for i, e in enumerate(ids)]}


class FakeApi:
    def __init__(self, *, fail_entries=()):
        self.urls: list[str] = []
        self.fail_entries = set(fail_entries)

    def __call__(self, url):
        self.urls.append(url)
        if "bootstrap" in url:
            return 200, BOOT, {}
        if "standings" in url:
            page = int(url.rsplit("=", 1)[1])
            # every row's `rank` is tied in pairs (as near 10K); the page order is the true order
            results = [{"rank": (page - 1) * 50 + (i // 2) * 2 + 1, "entry": 1000 + (page - 1) * 50 + i + 1,
                        "player_name": "Hidden"} for i in range(50)]
            return 200, {"standings": {"results": results}}, {}
        entry = int(url.split("/entry/")[1].split("/")[0])
        if entry in self.fail_entries:
            return 500, None, {}
        return 200, picks_for(variant=entry % 2 == 0), {}


def client(api, **kw):
    return eo.Client(api, sleep=lambda s: None, clock=lambda: 0.0, **kw)


def test_sample_ranks_are_a_stride_of_2000():
    ranks = eo.sample_ranks()
    assert len(ranks) == 2000 and ranks[0] == 5 and ranks[-1] == 10_000
    assert {eo.standings_page_for_rank(r) for r in ranks} == set(range(1, 201))


def test_gw_is_the_latest_with_a_passed_deadline():
    assert eo.current_gw(BOOT, NOW) == 12


def test_eo_maths_captain_bench_and_chips():
    samples = [eo.compact_picks(picks_for()), eo.compact_picks({**picks_for(), "active_chip": "bboost"})]
    out = eo.compute_eo(samples)
    p1, p15 = out["players"]["1"], out["players"]["15"]
    assert (p1["owned_pct"], p1["captain_pct"], p1["eo"], p1["bench_pct"]) == (100.0, 100.0, 200.0, 0.0)
    assert (p15["owned_pct"], p15["eo"], p15["bench_pct"]) == (100.0, 0.0, 100.0)
    assert out["chips"] == {"bboost_pct": 50.0}


def test_split_half_passes_on_consistent_data():
    consistent = [eo.compact_picks(picks_for(variant=i % 2 == 0)) for i in range(400)]
    assert eo.split_half_check(consistent)["ok"] is True


def test_split_half_fails_when_the_halves_disagree():
    # a tiny, very uneven sample: whichever way it is split, the halves differ a lot
    extreme = [eo.compact_picks(picks_for(variant=True)) for _ in range(5)] + \
              [eo.compact_picks(picks_for()) for _ in range(5)]
    res = eo.split_half_check(extreme, tolerance=1.0)
    assert res["ok"] is False and res["max_abs_diff"] > 1.0


def test_run_publishes_with_the_contract_and_clears_the_checkpoint(tmp_path):
    api = FakeApi()
    storage = eo.LocalStorage(tmp_path)
    assert eo.run(season="2026-2027", gw=None, storage=storage, client=client(api), now=NOW, log=QUIET) == 0
    out = storage.get("eo/2026-2027/gw12/top10k.json")
    assert out["n_sampled"] == 2000 and out["gw"] == 12 and out["basis"] == "locked"
    assert set(out["players"]["1"]) == {"owned_pct", "captain_pct", "bench_pct", "eo"}
    assert out["split_half"]["ok"] is True
    assert storage.get("eo/2026-2027/gw12/_checkpoint_top10k.json") is None
    assert "Hidden" not in json.dumps(out)
    assert sum("standings" in u for u in api.urls) == 200 and sum("/picks/" in u for u in api.urls) == 2000


def test_failed_entries_over_the_limit_publish_nothing(tmp_path):
    bad = {1000 + r for r in eo.sample_ranks()[:300]}  # 15% of the sample fails
    storage = eo.LocalStorage(tmp_path)
    code = eo.run(season="s", gw=12, storage=storage, client=client(FakeApi(fail_entries=bad)), now=NOW, log=QUIET)
    assert code == 1 and storage.get("eo/s/gw12/top10k.json") is None


def test_budget_exhaustion_saves_a_checkpoint_and_a_rerun_resumes(tmp_path):
    storage = eo.LocalStorage(tmp_path)
    assert eo.run(season="s", gw=12, storage=storage, client=client(FakeApi(), budget=300), now=NOW, log=QUIET) == 2
    saved = storage.get("eo/s/gw12/_checkpoint_top10k.json")
    assert 0 < len(saved["samples"]) < 2000
    assert "entry" not in json.dumps(saved) and "Hidden" not in json.dumps(saved)  # no ids or names kept
    api = FakeApi()
    assert eo.run(season="s", gw=12, storage=storage, client=client(api), now=NOW, log=QUIET) == 0
    assert sum("/picks/" in u for u in api.urls) == 2000 - len(saved["samples"])


def test_time_budget_stops_cleanly(tmp_path):
    ticks = iter(range(0, 10_000_000, 1000))
    storage = eo.LocalStorage(tmp_path)
    code = eo.run(season="s", gw=12, storage=storage, client=client(FakeApi()), max_seconds=500,
                  clock=lambda: next(ticks), now=NOW, log=QUIET)
    assert code == 2


def test_retry_honours_retry_after_then_gives_up():
    sleeps: list[float] = []
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        return 429, None, {"Retry-After": "7"}

    c = eo.Client(fetch, sleep=sleeps.append, clock=lambda: 0.0)
    assert c.get("u") is None and calls["n"] == 3
    assert 7.0 in sleeps


# -- the R2 writer stays inside {prefix}eo/ ----------------------------------------------

class FakeS3:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def put_object(self, Bucket, Key, **kw):
        self.calls.append(("put", Key))

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete", Key))

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Key))
        raise KeyError("NoSuchKey")


@pytest.mark.parametrize("prefix,expected", [("", "eo/"), ("pre", "pre/eo/"), ("/pre/", "pre/eo/")])
def test_r2_keys_are_confined_to_the_eo_prefix(prefix, expected):
    s3 = FakeS3()
    w = eo.R2Storage(client=s3, bucket="b", prefix=prefix)
    w.put("eo/s/gw1/top10k.json", {})
    w.delete("eo/s/gw1/_checkpoint_top10k.json")
    assert w.get("eo/s/gw1/x.json") is None
    assert len(s3.calls) == 3 and all(k.startswith(expected) for _, k in s3.calls)


@pytest.mark.parametrize("bad", [
    "seasons/2026-2027/_owned_latest.json", "tactical/s/x.parquet", "eo", "other/eo/x.json",
    "eo/../seasons/x.json", "../eo/x.json",
])
def test_r2_writer_refuses_keys_outside_eo(bad):
    s3 = FakeS3()
    w = eo.R2Storage(client=s3, bucket="b", prefix="pre")
    for op in (lambda: w.put(bad, {}), lambda: w.delete(bad), lambda: w.get(bad)):
        with pytest.raises(AssertionError):
            op()
    assert s3.calls == []


def test_r2_storage_without_env_names_fails_by_name_only(monkeypatch):
    for name in eo.R2Storage.ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError) as exc:
        eo.R2Storage()
    assert "OWNED_STORE_R2_BUCKET" in str(exc.value)


def test_tied_ranks_on_a_page_do_not_break_the_stride(tmp_path):
    api = FakeApi()
    storage = eo.LocalStorage(tmp_path)
    assert eo.run(season="s", gw=12, storage=storage, client=client(api), now=NOW, log=QUIET) == 0
    assert storage.get("eo/s/gw12/top10k.json")["n_sampled"] == 2000
    picks = [u for u in api.urls if "/picks/" in u]
    entries = sorted(int(u.split("/entry/")[1].split("/")[0]) for u in picks)
    assert entries == [1000 + r for r in eo.sample_ranks()]  # exactly every 5th position


# -- top100k ---------------------------------------------------------------------------

def test_top100k_sample_is_two_entries_on_every_second_page():
    ranks = eo.sample_ranks("top100k")
    assert len(ranks) == 2000 and len(set(ranks)) == 2000
    pages = sorted({eo.standings_page_for_rank(r) for r in ranks})
    assert pages == list(range(1, 2000, 2)) and len(pages) == 1000
    assert ranks[:4] == [13, 38, 113, 138] and ranks[-1] == 1999 * 50 - 50 + 38
    assert max(ranks) <= 100_000
    assert eo.sample_ranks("top10k")[0] == 5  # the default tier is unchanged
    with pytest.raises(ValueError):
        eo.sample_ranks("top1m")


def test_top100k_run_publishes_to_its_own_key_in_3000_requests(tmp_path):
    api = FakeApi()
    storage = eo.LocalStorage(tmp_path)
    c = client(api)
    assert eo.run(season="s", gw=12, storage=storage, client=c, tier="top100k", now=NOW, log=QUIET) == 0
    out = storage.get("eo/s/gw12/top100k.json")
    assert out["tier"] == "top100k" and out["n_sampled"] == 2000 and out["split_half"]["ok"] is True
    assert "2nd standings page" in out["sampling"]["ranks"]
    assert storage.get("eo/s/gw12/top10k.json") is None
    assert sum("standings" in u for u in api.urls) == 1000 and sum("/picks/" in u for u in api.urls) == 2000
    assert c.requests == 3000 < eo.REQUEST_BUDGET
    entries = sorted(int(u.split("/entry/")[1].split("/")[0]) for u in api.urls if "/picks/" in u)
    assert entries == [1000 + r for r in eo.sample_ranks("top100k")]


def test_top100k_checkpoints_while_running_and_resumes(tmp_path):
    storage = eo.LocalStorage(tmp_path)
    assert eo.run(season="s", gw=12, storage=storage, client=client(FakeApi(), budget=900), tier="top100k",
                  now=NOW, log=QUIET) == 2
    saved = storage.get("eo/s/gw12/_checkpoint_top100k.json")
    assert 0 < len(saved["samples"]) < 2000
    assert storage.get("eo/s/gw12/_checkpoint_top10k.json") is None  # tiers never share a checkpoint
    api = FakeApi()
    assert eo.run(season="s", gw=12, storage=storage, client=client(api), tier="top100k", now=NOW, log=QUIET) == 0
    assert sum("/picks/" in u for u in api.urls) == 2000 - len(saved["samples"])


# -- season resolution and the dry-run log ------------------------------------------------

def test_resolve_current_season_reads_the_yaml_and_the_real_registry_is_non_empty(tmp_path):
    f = tmp_path / "r.yaml"
    f.write_text('current_season: "2030-2031"\nseasons: []\n', encoding="utf-8")
    assert eo.resolve_current_season(f) == "2030-2031"
    assert eo.resolve_current_season().count("-") == 1  # the repo's own registry: e.g. 2026-2027


@pytest.mark.parametrize("body", ['current_season: ""\n', "seasons: []\n", ""])
def test_empty_or_missing_season_fails_loudly(tmp_path, body):
    f = tmp_path / "r.yaml"
    f.write_text(body, encoding="utf-8")
    with pytest.raises(SystemExit):
        eo.resolve_current_season(f)


def test_dry_run_log_says_local_only_and_never_published(tmp_path):
    lines: list[str] = []
    assert eo.run(season="s", gw=12, storage=eo.LocalStorage(tmp_path), client=client(FakeApi()), now=NOW,
                  log=lines.append) == 0
    last = lines[-1]
    assert "dry run, local only" in last and "published" not in last


def test_r2_run_log_says_published():
    class S3(FakeS3):
        def get_object(self, Bucket, Key):
            raise KeyError("NoSuchKey")

    lines: list[str] = []
    assert eo.run(season="s", gw=12, storage=eo.R2Storage(client=S3(), bucket="b", prefix=""),
                  client=client(FakeApi()), now=NOW, log=lines.append) == 0
    assert lines[-1].startswith("published eo/s/gw12/top10k.json to R2")


# -- the schedule gate ---------------------------------------------------------------------------------

SEASON = "2026-2027"
EV = BOOT["events"]  # deadlines: gw11 Nov 1, gw12 Nov 20, gw13 Dec 1 (all 2026)


def keys(*tiers, gw=12):
    return {eo.output_key(SEASON, gw, t) for t in tiers}


def test_gate_picks_the_latest_settled_gw_and_every_missing_tier_in_order():
    g = eo.gate(EV, SEASON, set(), NOW)
    assert g == {"gw": 12, "reason": "ok", "tiers": ["top10k", "top100k"]}


def test_gate_skips_published_tiers_and_does_nothing_when_all_exist():
    assert eo.gate(EV, SEASON, keys("top10k"), NOW)["tiers"] == ["top100k"]
    assert eo.gate(EV, SEASON, keys("top100k"), NOW)["tiers"] == ["top10k"]
    assert eo.gate(EV, SEASON, keys("top10k", "top100k"), NOW)["tiers"] == []


def test_gate_ignores_other_gameweeks_and_checkpoints():
    other = keys("top10k", "top100k", gw=11) | {eo.checkpoint_key(SEASON, 12, "top10k")}
    assert eo.gate(EV, SEASON, other, NOW)["tiers"] == ["top10k", "top100k"]


def test_gate_waits_thirty_minutes_after_the_deadline():
    deadline = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    just_after = deadline.replace(minute=29)
    assert eo.latest_settled_gw(EV, SEASON, just_after) == (11, "ok")
    assert eo.latest_settled_gw(EV, SEASON, deadline.replace(minute=30)) == (12, "ok")


def test_gate_has_nothing_before_the_first_deadline_or_without_events():
    early = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert eo.gate(EV, SEASON, set(), early) == {"gw": None, "reason": "no_settled_gw", "tiers": []}
    assert eo.gate([], SEASON, set(), NOW)["tiers"] == []
    assert eo.gate([{"id": 1}], SEASON, set(), NOW)["reason"] == "no_events"


def test_gate_refuses_last_seasons_events_under_a_new_season_key():
    old = [{"id": 38, "deadline_time": "2026-05-10T10:00:00Z"}, {"id": 1, "deadline_time": "2025-08-15T17:30:00Z"}]
    assert eo.gate(old, SEASON, set(), NOW) == {"gw": None, "reason": "season_mismatch", "tiers": []}
    assert eo.gate(EV, "", set(), NOW)["reason"] == "season_mismatch"


def test_scheduled_run_publishes_both_tiers_in_order_then_does_nothing(tmp_path):
    lines: list[str] = []
    storage = eo.LocalStorage(tmp_path)
    api = FakeApi()
    assert eo.run_scheduled(season=SEASON, gw=12, storage=storage, make_client=lambda: client(api), now=NOW,
                            log=lines.append) == 0
    assert storage.get(eo.output_key(SEASON, 12, "top10k")) and storage.get(eo.output_key(SEASON, 12, "top100k"))
    assert [l for l in lines if l.startswith("tier ")] == ["tier top10k: exit 0", "tier top100k: exit 0"]
    n = len(api.urls)
    lines.clear()
    assert eo.run_scheduled(season=SEASON, gw=12, storage=storage, make_client=lambda: client(api), now=NOW,
                            log=lines.append) == 0
    assert len(api.urls) == n and "nothing to do" in lines[-1]


def test_scheduled_run_only_runs_the_missing_tier(tmp_path):
    storage = eo.LocalStorage(tmp_path)
    storage.put(eo.output_key(SEASON, 12, "top10k"), {"done": True})
    api = FakeApi()
    assert eo.run_scheduled(season=SEASON, gw=12, storage=storage, make_client=lambda: client(api), now=NOW,
                            log=QUIET) == 0
    assert storage.get(eo.output_key(SEASON, 12, "top10k")) == {"done": True}
    assert storage.get(eo.output_key(SEASON, 12, "top100k"))


def test_a_failing_tier_fails_the_job_publishes_nothing_for_it_and_does_not_stop_the_next(tmp_path):
    class MissingPicks(FakeApi):  # 404 at once (a 500 would be retried and spend the budget)
        def __call__(self, url):
            if "/picks/" in url and int(url.split("/entry/")[1].split("/")[0]) - 1000 in set(eo.sample_ranks("top10k")):
                self.urls.append(url)
                return 404, None, {}
            return super().__call__(url)

    storage = eo.LocalStorage(tmp_path)
    api = MissingPicks()
    code = eo.run_scheduled(season=SEASON, gw=12, storage=storage, make_client=lambda: client(api), now=NOW,
                            log=QUIET)
    assert code == 1
    assert storage.get(eo.output_key(SEASON, 12, "top10k")) is None
    assert storage.get(eo.output_key(SEASON, 12, "top100k")) is not None


def test_a_cancelled_scheduled_run_resumes_from_its_checkpoint(tmp_path):
    storage = eo.LocalStorage(tmp_path)
    api = FakeApi()
    first = eo.run_scheduled(season=SEASON, gw=12, storage=storage,
                             make_client=lambda: client(api, budget=300), now=NOW, log=QUIET)
    assert first == 2 and storage.get(eo.checkpoint_key(SEASON, 12, "top10k"))
    resumed = FakeApi()
    assert eo.run_scheduled(season=SEASON, gw=12, storage=storage, make_client=lambda: client(resumed), now=NOW,
                            log=QUIET) == 0
    fresh = FakeApi()
    eo.run_scheduled(season=SEASON, gw=12, storage=eo.LocalStorage(tmp_path / "fresh"),
                     make_client=lambda: client(fresh), now=NOW, log=QUIET)
    assert len(resumed.urls) < len(fresh.urls)  # the requests of the cancelled run were not repeated
