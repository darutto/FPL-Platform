"""Which shot source the server serves: R2 keys per source, the env switch, rollback, safe failure.

Synthetic parquet and pointer files; a fake R2 client; no network.
"""

from __future__ import annotations

import json
import shutil

import pandas as pd
import pytest

from fpl_tactical import publish
from fpl_tactical.paths import (
    latest_pointer_path,
    shots_parquet_path,
    source_pointer_path,
    source_shots_path,
)

SEASON = "2026-2027"


class FakeR2:
    """Dict-backed bucket: keys -> bytes."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.uploaded: list[str] = []

    def upload_file(self, path, bucket, key):
        self.objects[key] = open(path, "rb").read()
        self.uploaded.append(key)

    def download_file(self, bucket, key, dest):
        if key not in self.objects:
            raise FileNotFoundError(key)
        open(dest, "wb").write(self.objects[key])


@pytest.fixture
def r2(monkeypatch, tmp_tactical_root):
    fake = FakeR2()
    monkeypatch.setattr(publish, "_make_r2_client", lambda: fake)
    monkeypatch.setenv("OWNED_STORE_R2_BUCKET", "bucket")
    monkeypatch.delenv("OWNED_STORE_R2_PREFIX", raising=False)
    monkeypatch.delenv(publish.ENV_TACTICAL_SOURCE, raising=False)
    return fake


def _pair(tmp_path, name, source, rows=3, validation="ok", n_shots=None):
    d = tmp_path / name
    d.mkdir()
    pd.DataFrame({"x": [0.9] * rows}).to_parquet(d / "shots.parquet", index=False)
    ptr = {"season": SEASON, "source": source, "n_shots": rows if n_shots is None else n_shots,
           "validation": {"status": validation}}
    (d / "ptr.json").write_text(json.dumps(ptr))
    return d / "ptr.json", d / "shots.parquet"


def _put_working_strikerapi(tmp_path, **kw):
    ptr, shots = _pair(tmp_path, "w", "strikerapi", **kw)
    for src, dst in ((ptr, source_pointer_path(SEASON, "strikerapi")), (shots, source_shots_path(SEASON, "strikerapi"))):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)


UND = "tactical/2026-2027/understat_shots.parquet"
UND_PTR = "tactical/2026-2027/_tactical_latest.json"
STR = "tactical/2026-2027/strikerapi/shots.parquet"
STR_PTR = "tactical/2026-2027/strikerapi/_tactical_latest.json"


def test_strikerapi_publishes_to_its_own_keys_and_never_touches_understat(r2, tmp_path):
    _put_working_strikerapi(tmp_path)
    r2.objects[UND] = b"old understat"
    publish.publish_tactical_store_to_r2(SEASON, "strikerapi")
    assert set(r2.uploaded) == {STR, STR_PTR}
    assert r2.objects[UND] == b"old understat"


@pytest.mark.parametrize("kw", [{"validation": "failed"}, {"n_shots": 99}])
def test_an_unvalidated_or_inconsistent_store_is_not_published(r2, tmp_path, kw):
    _put_working_strikerapi(tmp_path, **kw)
    with pytest.raises(RuntimeError):
        publish.publish_tactical_store_to_r2(SEASON, "strikerapi")
    assert r2.uploaded == []


def _stock_bucket(r2, tmp_path):
    u_ptr, u_shots = _pair(tmp_path, "u", "understat via soccerdata", rows=2)
    s_ptr, s_shots = _pair(tmp_path, "s", "strikerapi", rows=5)
    r2.objects.update({UND_PTR: u_ptr.read_bytes(), UND: u_shots.read_bytes(),
                       STR_PTR: s_ptr.read_bytes(), STR: s_shots.read_bytes()})


def _serving_source():
    return json.loads(latest_pointer_path(SEASON).read_text())["source"]


def test_default_serves_understat_exactly_as_before(r2, tmp_path):
    _stock_bucket(r2, tmp_path)
    res = publish.sync_tactical_store_from_r2(SEASON)
    assert res.ok and res.source == "understat"
    assert _serving_source().startswith("understat") and len(pd.read_parquet(shots_parquet_path(SEASON))) == 2


def test_the_env_var_switches_to_strikerapi_and_back_without_a_code_change(r2, tmp_path, monkeypatch):
    _stock_bucket(r2, tmp_path)
    monkeypatch.setenv(publish.ENV_TACTICAL_SOURCE, "strikerapi")
    assert publish.sync_tactical_store_from_r2(SEASON).ok
    assert _serving_source() == "strikerapi" and len(pd.read_parquet(shots_parquet_path(SEASON))) == 5
    monkeypatch.setenv(publish.ENV_TACTICAL_SOURCE, "understat")  # rollback
    assert publish.sync_tactical_store_from_r2(SEASON).ok
    assert _serving_source().startswith("understat") and len(pd.read_parquet(shots_parquet_path(SEASON))) == 2


def test_a_bad_strikerapi_pair_leaves_the_files_already_on_the_volume(r2, tmp_path, monkeypatch):
    _stock_bucket(r2, tmp_path)
    assert publish.sync_tactical_store_from_r2(SEASON).ok  # the old Understat files are on the volume
    bad_ptr, bad_shots = _pair(tmp_path, "b", "strikerapi", rows=5, n_shots=9)
    r2.objects.update({STR_PTR: bad_ptr.read_bytes(), STR: bad_shots.read_bytes()})
    monkeypatch.setenv(publish.ENV_TACTICAL_SOURCE, "strikerapi")
    res = publish.sync_tactical_store_from_r2(SEASON)
    assert not res.ok and res.source == "strikerapi"
    assert _serving_source().startswith("understat") and len(pd.read_parquet(shots_parquet_path(SEASON))) == 2


def test_a_missing_strikerapi_object_or_an_unknown_source_changes_nothing(r2, tmp_path, monkeypatch):
    _stock_bucket(r2, tmp_path)
    assert publish.sync_tactical_store_from_r2(SEASON).ok
    del r2.objects[STR]
    monkeypatch.setenv(publish.ENV_TACTICAL_SOURCE, "strikerapi")
    assert not publish.sync_tactical_store_from_r2(SEASON).ok
    monkeypatch.setenv(publish.ENV_TACTICAL_SOURCE, "other")
    assert not publish.sync_tactical_store_from_r2(SEASON).ok
    assert _serving_source().startswith("understat")


def test_ci_restores_the_working_store_from_the_strikerapi_keys(r2, tmp_path):
    _stock_bucket(r2, tmp_path)
    assert publish.fetch_working_store_from_r2(SEASON, "strikerapi") == 2
    assert len(pd.read_parquet(source_shots_path(SEASON, "strikerapi"))) == 5
    assert not shots_parquet_path(SEASON).exists()  # never the serving paths


def test_a_server_that_already_holds_the_old_parquet_switches_and_rolls_back(r2, tmp_path, monkeypatch):
    """The prod case: the volume has the old files before this code ever runs a sync."""
    u_ptr, u_shots = _pair(tmp_path, "old", "understat via soccerdata", rows=3)
    latest_pointer_path(SEASON).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(u_ptr, latest_pointer_path(SEASON))
    shutil.copy(u_shots, shots_parquet_path(SEASON))
    monkeypatch.setenv(publish.ENV_TACTICAL_SOURCE, "strikerapi")

    assert not publish.sync_tactical_store_from_r2(SEASON).ok  # nothing published yet
    assert _serving_source().startswith("understat") and len(pd.read_parquet(shots_parquet_path(SEASON))) == 3

    _stock_bucket(r2, tmp_path)
    assert publish.sync_tactical_store_from_r2(SEASON).ok
    assert _serving_source() == "strikerapi" and len(pd.read_parquet(shots_parquet_path(SEASON))) == 5

    monkeypatch.delenv(publish.ENV_TACTICAL_SOURCE)  # rollback: removing the variable is enough
    assert publish.sync_tactical_store_from_r2(SEASON).ok
    assert _serving_source().startswith("understat") and len(pd.read_parquet(shots_parquet_path(SEASON))) == 2
    assert not source_shots_path(SEASON, "strikerapi").exists()
