from __future__ import annotations
import hashlib, json, socket
from pathlib import Path
import pandas as pd, pytest
import football_intelligence.features.engine as engine
from football_intelligence.distribution.config import RemoteStoreConfig
from football_intelligence.distribution.runtime import RuntimeBuildHandle
from football_intelligence.distribution.service import encode_pointer
from football_intelligence.ingestion.builder import build_from_fixture
from football_intelligence.features.registry import FEATURE_SPECS, FeatureSpec, validate_registry
from football_intelligence.features.store import build_features, resolve_dataset, validate_feature_build
from football_intelligence.features.cli import main as feature_cli

FIXTURE=Path(__file__).parent/"fixtures/sportmonks_replay_v1.json"

def canonical(tmp_path):
    build_from_fixture(FIXTURE,tmp_path,build_id="canonical",built_at="2026-07-01T00:00:00Z")
    mp=tmp_path/"builds/canonical/manifest.json"; mh=hashlib.sha256(mp.read_bytes()).hexdigest()
    (tmp_path/"_football_latest.json").write_bytes(encode_pointer("canonical",mh,"2026-07-01T00:00:00Z"))
    return RuntimeBuildHandle(tmp_path)

def frames():
    fixtures=pd.DataFrame([
      {"fixture_id":"f1","season_id":"s","competition_id":"c","home_team_id":"t1","away_team_id":"t2","fixture_key":"a","kickoff_utc":"2025-08-01T12:00:00Z","status":"completed","gameweek":1},
      {"fixture_id":"f2","season_id":"s","competition_id":"c","home_team_id":"t2","away_team_id":"t1","fixture_key":"b","kickoff_utc":"2025-08-08T12:00:00Z","status":"completed","gameweek":2},
      {"fixture_id":"f3","season_id":"s","competition_id":"c","home_team_id":"t1","away_team_id":"t2","fixture_key":"c","kickoff_utc":"2025-08-15T12:00:00Z","status":"scheduled","gameweek":3}])
    squads=pd.DataFrame([{"team_id":"t1","player_id":"p1","valid_from":"2025-01-01","valid_to":None}])
    lineups=pd.DataFrame([{"fixture_id":"f1","team_id":"t1","player_id":"p1","started":True,"minutes":90,"formation":"4-3-3","grid_slot":"3:2","detailed_position":"central midfield"},{"fixture_id":"f2","team_id":"t1","player_id":"p1","started":False,"minutes":20,"formation":"4-3-3","grid_slot":None,"detailed_position":"central midfield"}])
    players=pd.DataFrame([{"player_id":"p1","positions_nominal":"midfielder"}])
    return {"fixtures":fixtures,"squads":squads,"lineups":lineups,"players":players,"injuries":pd.DataFrame(columns=["player_id","recorded_at_utc","resolved_at_utc"]),"suspensions":pd.DataFrame(columns=["player_id","recorded_at_utc","ends_on"])}

def compute(monkeypatch,data):
    monkeypatch.setattr(engine,"_manifest_hash",lambda h: ({"build_id":"canonical"},"a"*64)); monkeypatch.setattr(engine,"_read",lambda h,n:data[n].copy())
    return engine.compute_features(object())

def test_registry_is_closed_provider_neutral_and_complete():
    assert len(FEATURE_SPECS)==13 and {s.name for s in FEATURE_SPECS}=={"primary_role","role_stability","flank","flank_distribution","formation_depth","out_of_position_score","start_share_last_5","mean_minutes_last_5","cameo_share_last_5","rotation_tendency","rest_days","fixture_congestion_index","availability_multiplier"}
    with pytest.raises(ValueError): validate_registry((FEATURE_SPECS[0],FEATURE_SPECS[0]))

def test_cutoff_excludes_target_and_later_and_values_are_literal(monkeypatch):
    data=frames(); result=compute(monkeypatch,data); row=result[result.fixture_id=="f3"].iloc[0]
    assert row.start_share_last_5==0.5 and row.mean_minutes_last_5==55.0 and row.cameo_share_last_5==0.5
    assert row.primary_role=="central_midfield" and row.role_stability==1.0 and row.flank=="center"
    assert row.rest_days==7.0 and row.fixture_congestion_index==2 and row.availability_multiplier==1.0

def test_target_and_future_mutations_do_not_leak(monkeypatch):
    data=frames(); baseline=compute(monkeypatch,data); target=baseline[baseline.fixture_id=="f3"].to_json()
    data["lineups"]=pd.concat([data["lineups"],pd.DataFrame([{"fixture_id":"f3","team_id":"t1","player_id":"p1","started":True,"minutes":120,"formation":"x","grid_slot":None,"detailed_position":"left wing"}])],ignore_index=True)
    assert compute(monkeypatch,data).query("fixture_id=='f3'").to_json()==target
    data["fixtures"]=pd.concat([data["fixtures"],pd.DataFrame([{"fixture_id":"f4","season_id":"s","competition_id":"c","home_team_id":"t1","away_team_id":"t2","fixture_key":"d","kickoff_utc":"2025-09-01T12:00:00Z","status":"completed","gameweek":4}])],ignore_index=True)
    assert compute(monkeypatch,data).query("fixture_id=='f3'").to_json()==target

def test_future_injury_does_not_leak_but_prior_suspension_does(monkeypatch):
    data=frames(); data["injuries"]=pd.DataFrame([{"player_id":"p1","recorded_at_utc":"2025-09-01T00:00:00Z","resolved_at_utc":None}])
    assert compute(monkeypatch,data).query("fixture_id=='f3'").iloc[0].availability_multiplier==1.0
    data["suspensions"]=pd.DataFrame([{"player_id":"p1","recorded_at_utc":"2025-08-10T00:00:00Z","ends_on":None}])
    assert compute(monkeypatch,data).query("fixture_id=='f3'").iloc[0].availability_multiplier==0.0

def test_reversed_inputs_are_deterministic(monkeypatch):
    data=frames(); first=compute(monkeypatch,data)
    reverse={k:v.iloc[::-1].reset_index(drop=True) for k,v in data.items()}
    pd.testing.assert_frame_equal(first,compute(monkeypatch,reverse))

def test_atomic_build_validate_replay_and_source_binding(tmp_path):
    handle=canonical(tmp_path/"canonical"); one=tmp_path/"one"; two=tmp_path/"two"
    a=build_features(handle,one,feature_build_id="features-v1",built_at="2026-07-01T00:00:00Z")
    b=build_features(handle,two,feature_build_id="features-v1",built_at="2026-07-01T00:00:00Z")
    assert a["content_hashes"]==b["content_hashes"] and a["parquet_byte_hashes"]==b["parquet_byte_hashes"]
    assert validate_feature_build(one/"builds/features-v1",handle)==a
    other=canonical(tmp_path/"other")
    mp=tmp_path/"other/builds/canonical/manifest.json"; value=json.loads(mp.read_text()); value["built_at"]="changed"; mp.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n")
    with pytest.raises(ValueError,match="source binding"): validate_feature_build(one/"builds/features-v1",other)

def test_failed_pointer_swap_retains_previous(tmp_path):
    handle=canonical(tmp_path/"canonical"); root=tmp_path/"features"; build_features(handle,root,feature_build_id="good",built_at="2026-07-01T00:00:00Z"); before=(root/"_features_latest.json").read_bytes()
    with pytest.raises(RuntimeError): build_features(handle,root,feature_build_id="bad",built_at="2026-07-01T00:00:00Z",fail_before_pointer=True)
    assert (root/"_features_latest.json").read_bytes()==before

@pytest.mark.parametrize("path",["../x.parquet",r"C:\x.parquet",r"\\server\x.parquet","/x.parquet","datasets/../x.parquet"])
def test_dataset_path_adversarial(path,tmp_path):
    with pytest.raises(ValueError): resolve_dataset(tmp_path,path)

def test_no_network_and_credentials_not_repr(tmp_path,monkeypatch):
    handle=canonical(tmp_path/"canonical"); monkeypatch.setattr(socket,"socket",lambda *a,**k: (_ for _ in ()).throw(AssertionError("network")))
    build_features(handle,tmp_path/"features",feature_build_id="offline",built_at="2026-07-01T00:00:00Z")
    config=RemoteStoreConfig("https://example.invalid","bucket-ok","football","access-secret","key-secret")
    assert "access-secret" not in repr(config) and "key-secret" not in repr(config)

def test_cli_build_validate_replay_and_status(tmp_path):
    canonical(tmp_path/"canonical"); root=tmp_path/"features"
    assert feature_cli(["build","--canonical-root",str(tmp_path/"canonical"),"--feature-root",str(root),"--feature-build-id","cli-v1","--built-at","2026-07-01T00:00:00Z"])==0
    build=root/"builds/cli-v1"
    assert feature_cli(["validate","--canonical-root",str(tmp_path/"canonical"),"--feature-build",str(build)])==0
    assert feature_cli(["status","--canonical-root",str(tmp_path/"canonical"),"--feature-root",str(root)])==0
    assert feature_cli(["replay","--canonical-root",str(tmp_path/"canonical"),"--source-feature-build",str(build),"--destination",str(tmp_path/"replay")])==0
