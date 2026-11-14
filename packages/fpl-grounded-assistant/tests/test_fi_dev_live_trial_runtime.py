"""Dev-only gate letting the chat FI tools read a local live_trial_local store.

Default stays refused. Served only with FI_DEV_ALLOW_LIVE_TRIAL_LOCAL=1 + an explicit store dir
+ no deployed-environment marker; every served result is stamped ``provenance: live_trial_local``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from football_intelligence.provenance import LiveTrialProvenanceRefused
from fpl_grounded_assistant import competition_calendar as gate
from fpl_grounded_assistant import football_intelligence_runtime as runtime

CALCULATED_AT = "2026-10-01T12:00:00Z"


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "builds-v2" / "context-a").mkdir(parents=True)
    (tmp_path / "features" / "builds-v2" / "feature-a").mkdir(parents=True)
    (tmp_path / "_football_v2_latest.json").write_text(json.dumps(
        {"schema_version": 2, "build_id": "context-a", "manifest": "builds-v2/context-a/manifest.json"}), encoding="utf-8")
    (tmp_path / "features" / "_features_v2_latest.json").write_text(json.dumps(
        {"schema_version": 2, "build_family": "module-enablement-features-v2", "feature_build_id": "feature-a"}), encoding="utf-8")
    live = {"assumption_status": "live_trial_local"}
    monkeypatch.setattr("football_intelligence.ingestion.builder_v2.validate_context_build",
                        lambda path: {"entity_files": {"fixtures": "f.parquet", "fixture_schedule_snapshots": "s.parquet"}, **live})
    monkeypatch.setattr("football_intelligence.features.store_v2.validate_feature_build_v2",
                        lambda path, base, context_path: {"built_at": CALCULATED_AT,
                                                          "output_files": {"team_fixture_context_v2": "t.parquet"}, **live})
    monkeypatch.setattr(pd, "read_parquet", lambda path: pd.DataFrame({"source": [Path(path).name]}))
    for name in (gate.ENV_ALLOW, gate.ENV_STORE, *gate.PROD_MARKERS):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_flag_unset_is_refused(store, monkeypatch):
    monkeypatch.setenv(gate.ENV_STORE, str(store))
    monkeypatch.setenv("FPL_FOOTBALL_ROOT", str(store))
    with pytest.raises(LiveTrialProvenanceRefused):
        runtime._load_runtime()


def test_flag_without_store_is_refused(store, monkeypatch):
    monkeypatch.setenv(gate.ENV_ALLOW, "1")
    monkeypatch.setenv("FPL_FOOTBALL_ROOT", str(store))
    with pytest.raises(LiveTrialProvenanceRefused):
        runtime._load_runtime()


@pytest.mark.parametrize("marker", gate.PROD_MARKERS)
def test_flag_in_prod_is_refused(store, monkeypatch, marker):
    monkeypatch.setenv(gate.ENV_ALLOW, "1")
    monkeypatch.setenv(gate.ENV_STORE, str(store))
    monkeypatch.setenv(marker, "production")
    monkeypatch.setenv("FPL_FOOTBALL_ROOT", str(store))
    assert gate.dev_live_trial_store() is None
    with pytest.raises(LiveTrialProvenanceRefused):
        runtime._load_runtime()


def test_flag_dev_and_valid_store_is_served_and_stamped(store, monkeypatch):
    monkeypatch.setenv(gate.ENV_ALLOW, "1")
    monkeypatch.setenv(gate.ENV_STORE, str(store))
    loaded = runtime._load_runtime()
    assert loaded is not None and loaded.provenance == "live_trial_local" and loaded.root == store
    monkeypatch.setattr(runtime, "_identity_tables", lambda root, at: None)
    monkeypatch.setattr(runtime, "_load_runtime", lambda: loaded)
    out = runtime.run_football_intelligence_tool("get_expected_minutes", {"player": "x"}, {})
    assert out["provenance"] == "live_trial_local"


def test_explicit_root_never_uses_the_dev_gate(store, monkeypatch):
    monkeypatch.setenv(gate.ENV_ALLOW, "1")
    monkeypatch.setenv(gate.ENV_STORE, str(store))
    with pytest.raises(LiveTrialProvenanceRefused):
        runtime._load_runtime(store)


def test_default_runtime_result_carries_no_provenance(monkeypatch):
    item = runtime._Runtime(root=Path("u"), base=object(), context_build=Path("c"), feature_build=Path("f"),
                            calculated_at=CALCULATED_AT, context_fixtures=pd.DataFrame(),
                            context_schedule=pd.DataFrame(), team_targets=pd.DataFrame())
    monkeypatch.setattr(runtime, "_load_runtime", lambda: item)
    monkeypatch.setattr(runtime, "_identity_tables", lambda root, at: None)
    assert "provenance" not in runtime.run_football_intelligence_tool("get_expected_minutes", {"player": "x"}, {})
