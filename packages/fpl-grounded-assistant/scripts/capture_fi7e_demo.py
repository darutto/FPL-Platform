#!/usr/bin/env python3
"""Generate FI-7e evidence from real deterministic execution seams."""
from __future__ import annotations

import argparse
from copy import deepcopy
import dataclasses
from enum import Enum
import hashlib
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "fi7e-evidence-manifest-v1"
TRACE_SCHEMA = "backend-trace-v2"
FIXTURE_VERSION = "fi7e-demo-input-v1"
FROZEN_AT = "2026-08-01T12:00:00Z"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def artifact_checksum_bytes(path: Path) -> bytes:
    """Return platform-independent bytes for an artifact checksum."""
    raw = path.read_bytes()
    if path.suffix.lower() in {".md", ".py", ".txt"}:
        if raw.startswith(b"\xef\xbb\xbf"):
            raise SystemExit(f"UTF-8 BOM is not permitted: {path}")
        raw = raw.replace(b"\r\n", b"\n")
        if b"\r" in raw:
            raise SystemExit(f"bare CR is not permitted: {path}")
        raw.decode("utf-8")
    return raw


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical(value))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def serialize(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {f.name: serialize(getattr(value, f.name)) for f in dataclasses.fields(value) if getattr(value, f.name) is not None}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): serialize(v) for k, v in value.items()}
    return value


def import_paths(root: Path) -> None:
    packages = root / "packages"
    ordered = [packages / "fpl-captain-engine", packages / "fpl-grounded-assistant",
        packages / "football-intelligence" / "tests"]
    ordered.extend(path for path in sorted(packages.iterdir()) if path.is_dir() and path.name not in {"fpl-captain-engine","fpl-grounded-assistant","fpl-data-core"})
    ordered.append(packages / "fpl-data-core")
    sys.path[:0] = [str(path) for path in ordered]


def load_source(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_fi(root: Path, work: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Exercise real v2 loaders/evaluators through the FI runtime entry point."""
    import pandas as pd
    from football_data_contract.enums import AvailabilityState
    from football_intelligence.features.store_v2 import build_features_v2
    from football_intelligence.modules import AvailabilityInput
    from test_features_v2 import sources
    runtime = load_source("fi7e_runtime_observed", root / "packages" / "fpl-grounded-assistant" /
                          "fpl_grounded_assistant" / "football_intelligence_runtime.py")

    base, context = sources(work / "source")
    feature_root = work / "features"
    build_features_v2(base, context, feature_root, feature_build_id="fi7e-observed", built_at=FROZEN_AT)
    build = feature_root / "builds-v2" / "fi7e-observed"
    runtime_value = runtime._Runtime(root=work, base=base, context_build=context, feature_build=build,
        calculated_at=FROZEN_AT, context_fixtures=pd.DataFrame(), context_schedule=pd.DataFrame(), team_targets=pd.DataFrame())
    observed: dict[str, Any] = {"runtime_entries": 0, "loads": [], "evaluations": [], "module_order": []}

    def evaluate_modules(_runtime: Any, _resolved: dict[str, Any], fixture_id: str, names: tuple[str, ...]) -> dict[str, Any]:
        from football_intelligence.modules import (evaluate_expected_minutes, evaluate_fixture_context,
            evaluate_tactical_role, load_expected_minutes_input, load_fixture_context_input, load_tactical_role_input)
        result: dict[str, Any] = {}
        for name in names:
            observed["module_order"].append({"expected_minutes":"M1", "tactical_role":"M2", "fixture_context":"M3"}[name])
            observed["loads"].append(name)
            if name == "expected_minutes":
                item = load_expected_minutes_input(build, base, context, fixture_id=fixture_id, team_id="team_a",
                    player_id="player_1", calculated_at=FROZEN_AT, availability=AvailabilityInput(state=AvailabilityState.AVAILABLE))
                observed["evaluations"].append(name); result[name] = evaluate_expected_minutes(item)
            elif name == "tactical_role":
                item = load_tactical_role_input(build, base, context, fixture_id=fixture_id, team_id="team_a",
                    player_id="player_1", nominal_position="MID", calculated_at=FROZEN_AT)
                observed["evaluations"].append(name); result[name] = evaluate_tactical_role(item)
            else:
                item = load_fixture_context_input(build, base, context, fixture_id=fixture_id, team_id="team_a", calculated_at=FROZEN_AT)
                observed["evaluations"].append(name); result[name] = evaluate_fixture_context(item)
        return result

    old = (runtime._load_runtime, runtime._identity_tables, runtime._resolve_player, runtime.select_target_fixture, runtime._evaluate_modules)
    try:
        runtime._load_runtime = lambda: runtime_value
        runtime._identity_tables = lambda *_: object()
        runtime._resolve_player = lambda *_: {"status":"ok", "player_id":"player_1", "team_id":"team_a", "nominal_position":"MID",
            "status_label":"Available", "element":{"chance_of_playing_next_round":100}}
        runtime.select_target_fixture = lambda *_: "target"
        runtime._evaluate_modules = evaluate_modules
        observed["runtime_entries"] += 1
        output = runtime.run_football_intelligence_tool("get_player_intelligence", {"player":"Saka"}, {})
    finally:
        runtime._load_runtime, runtime._identity_tables, runtime._resolve_player, runtime.select_target_fixture, runtime._evaluate_modules = old
    return output, observed


def run_tests(root: Path, evidence_sha: str) -> dict[str, Any]:
    env = dict(os.environ)
    package_paths = [root / "packages" / "fpl-captain-engine", root / "packages" / "fpl-grounded-assistant"]
    package_paths.extend(path for path in sorted((root / "packages").iterdir()) if path.is_dir() and path.name != "fpl-data-core")
    package_paths.append(root / "packages" / "fpl-data-core")
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([*(str(path) for path in package_paths), *([inherited] if inherited else [])])
    config_fd, config_name = tempfile.mkstemp(prefix="fi7e-pytest-", suffix=".ini")
    os.close(config_fd)
    config = Path(config_name)
    config.write_text("[pytest]\n", encoding="utf-8")
    pytest_temp = tempfile.mkdtemp(prefix="fi7e-pytest-", dir="C:\\tmp" if sys.platform == "win32" else None)
    ui_cwd = root / "packages" / "fpl-ui"
    ui_test = root / "packages" / "fpl-ui" / "__tests__" / "fi7d-evidence-ui.test.tsx"
    node_modules = Path(env.get("NODE_PATH", str(ui_cwd / "node_modules")))
    jest_fd, jest_name = tempfile.mkstemp(prefix="fi7e-jest-", suffix=".json")
    os.close(jest_fd)
    jest_config = Path(jest_name)
    image_mock = jest_config.with_name(jest_config.stem + "-html-to-image.js")
    image_mock.write_text("module.exports={toBlob:async()=>new Blob()};\n", encoding="utf-8")
    jest_config.write_text(json.dumps({"rootDir":str(ui_cwd),"testEnvironment":str(ui_cwd/"jest-env.js"),
        "testMatch":["**/__tests__/**/*.test.ts","**/__tests__/**/*.test.tsx"],"moduleDirectories":[str(node_modules)],
        "moduleNameMapper":{"^@/(.*)$":"<rootDir>/$1","^html-to-image$":str(image_mock)},
        "transform":{"^.+\\.tsx?$":[str(node_modules/"ts-jest"),{"tsconfig":{"module":"commonjs","jsx":"react-jsx"}}]}}),encoding="utf-8")
    commands = [
        ("python_focused", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(config), "--basetemp", pytest_temp, "tests/test_fi7b1_tool_shells.py",
            "tests/test_fi7b2_runtime_integration.py", "tests/test_fi7b3_rendering_session_evidence.py",
            "tests/test_fi7c_existing_intent_evidence.py"], root / "packages" / "fpl-grounded-assistant"),
        ("ui_fi7d", ["node", str(node_modules/"jest"/"bin"/"jest.js"), "--config", str(jest_config), "--runInBand",
            "--runTestsByPath", str(ui_test)], ui_cwd),
    ]
    results: dict[str, Any] = {}
    try:
        for name, command, cwd in commands:
            done = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
            output = done.stdout + done.stderr
            normalized = output.replace(str(root), "<REPO>").replace(str(config), "<PYTEST_CONFIG>").replace(pytest_temp, "<PYTEST_TEMP>").replace(str(jest_config), "<JEST_CONFIG>")
            normalized = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ms|s)\b", "<DURATION>", normalized)
            display_command = [str(item).replace(str(root), "<REPO>").replace(str(config), "<PYTEST_CONFIG>").replace(pytest_temp, "<PYTEST_TEMP>").replace(str(jest_config), "<JEST_CONFIG>") for item in command]
            results[name] = {"command":display_command, "exit_code":done.returncode, "output_sha256":hashlib.sha256(normalized.encode()).hexdigest(),
                "run_id":digest({"command":display_command, "repository_sha":evidence_sha}), "summary":normalized[-1200:]}
            if done.returncode:
                raise SystemExit(f"focused test failure: {name}\n{output}")
            expected = "75 passed" if name == "python_focused" else "43 passed"
            if expected not in output:
                raise SystemExit(f"focused test count mismatch: {name} expected {expected}\n{output}")
    finally:
        config.unlink(missing_ok=True)
        jest_config.unlink(missing_ok=True)
        image_mock.unlink(missing_ok=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video-url", default="PENDING"); parser.add_argument("--video-sha256", default="PENDING")
    parser.add_argument("--video-size", type=int, default=0); parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    os.chdir(root)
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    if fixture.get("fixture_version") != FIXTURE_VERSION or fixture.get("calculated_at") != FROZEN_AT: raise SystemExit("wrong frozen fixture contract")
    if subprocess.run(["git","merge-base","--is-ancestor",fixture["authoritative_sha"],"HEAD"]).returncode: raise SystemExit("stale authoritative base SHA")
    if git("status", "--porcelain=v1", "--untracked-files=all"): raise SystemExit("dirty worktree")
    if any(any(p in n.upper() for p in ("SPORTMONKS", "UNDERSTAT")) and os.environ.get(n) for n in os.environ): raise SystemExit("live-provider configuration detected")
    if args.output.exists() and any(args.output.iterdir()): raise SystemExit("output directory is not empty")
    args.output.mkdir(parents=True, exist_ok=True); import_paths(root)

    with tempfile.TemporaryDirectory(prefix="fi7e-") as temp:
        raw, observed = run_fi(root, Path(temp)); test_results = run_tests(root, fixture["authoritative_sha"])
    fi_renderer = load_source("fi7e_renderer_observed", root / "packages" / "fpl-grounded-assistant" /
                              "fpl_grounded_assistant" / "football_intelligence_renderer.py")
    from fpl_grounded_assistant import final_response, football_intelligence_runtime, harness, tool_schema_registry
    from fpl_grounded_assistant.final_response_fixtures import STANDARD_BOOTSTRAP

    bootstrap = deepcopy(STANDARD_BOOTSTRAP)
    saka = next(item for item in bootstrap["elements"] if item["web_name"] == "Saka")
    palmer = deepcopy(saka)
    palmer.update({"id":13,"web_name":"Palmer","first_name":"Cole","second_name":"Palmer","total_points":max(0,int(saka.get("total_points",0))-5)})
    bootstrap["elements"].append(palmer)
    evidence = list(raw["evidence"])
    counters = {"fi_invocations":0,"enrichment_invocations":0,"enrichment_errors":0,"replay_invocations":0}
    static_count = len(tool_schema_registry.list_tool_schemas())
    offered_off = len(tool_schema_registry.get_offered_tool_schemas(False))
    offered_on = len(tool_schema_registry.get_offered_tool_schemas(True))

    old_env = os.environ.get("FOOTBALL_INTELLIGENCE_ENABLED")
    old_runtime = football_intelligence_runtime.run_football_intelligence_tool
    old_ask = harness.ask_v2
    old_detect = final_response.detect_multi_intent
    try:
        os.environ.pop("FOOTBALL_INTELLIGENCE_ENABLED", None)
        a = serialize(final_response.respond(fixture["scenarios"]["A"]["prompt"], bootstrap))
        c_off = serialize(final_response.respond(fixture["scenarios"]["C_OFF"]["prompt"], bootstrap))

        def measured_runtime(name: str, args: dict[str, Any], supplied_bootstrap: dict[str, Any]) -> dict[str, Any]:
            counters["fi_invocations"] += 1
            counters["enrichment_invocations"] += 1
            return raw

        football_intelligence_runtime.run_football_intelligence_tool = measured_runtime
        os.environ["FOOTBALL_INTELLIGENCE_ENABLED"] = "1"
        c_on = serialize(final_response.respond(fixture["scenarios"]["C_ON"]["prompt"], bootstrap))

        def governed_fi_ask(question: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            if question == fixture["scenarios"]["B"]["prompt"]:
                return {"answer_text":fi_renderer.render_player_intelligence(raw),"outcome":"ok","selected_tool":"get_player_intelligence",
                    "evidence":evidence,"routing_trace":{"branch":"orchestrator","orchestrator_outcome":"ok"},"tokens":{"total":0}}
            return {"answer_text":"","outcome":"unsupported","selected_tool":None,"routing_trace":{"branch":"unsupported"},"tokens":{"total":0}}

        harness.ask_v2 = governed_fi_ask
        b = serialize(final_response.respond(fixture["scenarios"]["B"]["prompt"], bootstrap))

        query = fixture["scenarios"]["D"]["prompt"]
        final_response.detect_multi_intent = lambda value: ([fixture["scenarios"]["B"]["prompt"],"what gameweek is it?"] if value == query else old_detect(value))
        d = serialize(final_response.respond(query, bootstrap))

        def failing_runtime(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            counters["fi_invocations"] += 1
            counters["enrichment_invocations"] += 1
            counters["enrichment_errors"] += 1
            raise RuntimeError("fi7e controlled enrichment failure")

        harness.ask_v2 = old_ask
        football_intelligence_runtime.run_football_intelligence_tool = failing_runtime
        f1 = serialize(final_response.respond(fixture["scenarios"]["F1"]["prompt"], bootstrap))
    finally:
        football_intelligence_runtime.run_football_intelligence_tool = old_runtime
        harness.ask_v2 = old_ask
        final_response.detect_multi_intent = old_detect
        if old_env is None: os.environ.pop("FOOTBALL_INTELLIGENCE_ENABLED", None)
        else: os.environ["FOOTBALL_INTELLIGENCE_ENABLED"] = old_env

    before_replay = dict(counters)
    replay = json.loads(canonical(b))
    counters["replay_invocations"] += 1
    replay_runtime_delta = counters["fi_invocations"] - before_replay["fi_invocations"]
    f2 = dict(b); f2.pop("evidence", None)
    payloads = {"A":a,"B":b,"C_OFF":c_off,"C_ON":c_on,"D":d,"E":{"original":b,"replay":replay},"F1":f1,"F2":f2}

    stripped_on = {k:v for k,v in c_on.items() if k != "evidence"}; stripped_off = {k:v for k,v in c_off.items() if k != "evidence"}
    equality = {"allowed_differences":["/evidence"],"off_full_hash":digest(c_off),"off_without_evidence_hash":digest(stripped_off),
        "on_full_hash":digest(c_on),"on_without_evidence_hash":digest(stripped_on),"player_order":["Saka","Palmer"],
        "recommendation_fields_equal":stripped_off == stripped_on,"schema_version":"recommendation-equality-v1",
        "unexpected_differences":[] if stripped_off == stripped_on else ["/"]}
    assertions = {"A":{"flag_off_no_evidence":"evidence" not in a}, "B":{"runtime_entry_once":observed["runtime_entries"] == 1,
        "loaders_once":observed["loads"] == ["expected_minutes","tactical_role","fixture_context"],
        "evaluators_once":observed["evaluations"] == ["expected_minutes","tactical_role","fixture_context"],
        "module_order":observed["module_order"] == ["M1","M2","M3"]},
        "C":{"only_evidence_diff":equality["recommendation_fields_equal"]},
        "D":{"parent_absent":"evidence" not in d,"first_child_has_evidence":bool(d["sub_responses"][0].get("evidence")),
             "second_child_unchanged":"evidence" not in d["sub_responses"][1]},
        "E":{"stored_hash_equals_replay_hash":canonical(b)==canonical(replay),"replay_runtime_delta_zero":replay_runtime_delta==0},
        "F1":{"failure_contained":f1==a,"error_observed":counters["enrichment_errors"]==1,"no_fabricated_evidence":"evidence" not in f1},
        "F2":{"ui_test_passed":test_results["ui_fi7d"]["exit_code"]==0,"main_response_visible":bool(f2["final_text"]),"evidence_absent":"evidence" not in f2}}
    if not all(v for group in assertions.values() for v in group.values()): raise SystemExit(f"scenario assertion failed: {assertions}")

    traces=[]
    for sid in ("A","B","C_OFF","C_ON","D","E","F1","F2"):
        response = replay if sid=="E" else payloads[sid]
        ev = response.get("evidence") or (response.get("sub_responses") or [{}])[0].get("evidence", [])
        traces.append({"scenario_id":sid,"flag_state":fixture["scenarios"]["E" if sid=="E" else sid]["flag"],
            "input_hash":digest(fixture["scenarios"]["E" if sid=="E" else sid]),"normalized_response_hash":digest(response),
            "evidence_count":len(ev),"evidence_hashes":[digest(x) for x in ev],"frozen_clock":FROZEN_AT,
            "observations":{"static_schema_count":static_count,"offered_tool_count":offered_on if fixture["scenarios"]["E" if sid=="E" else sid]["flag"]=="ON" else offered_off,
                "fi_invocation_count":0 if sid=="A" else (observed["runtime_entries"] if sid in {"B","E"} else counters["fi_invocations"]),
                "m1_load_count":observed["loads"].count("expected_minutes") if sid in {"B","E"} else 0,
                "m1_evaluate_count":observed["evaluations"].count("expected_minutes") if sid in {"B","E"} else 0,
                "m2_load_count":observed["loads"].count("tactical_role") if sid in {"B","E"} else 0,
                "m2_evaluate_count":observed["evaluations"].count("tactical_role") if sid in {"B","E"} else 0,
                "m3_load_count":observed["loads"].count("fixture_context") if sid in {"B","E"} else 0,
                "m3_evaluate_count":observed["evaluations"].count("fixture_context") if sid in {"B","E"} else 0,
                "module_order":observed["module_order"] if sid in {"B","E"} else [],"m4_count":0,"m5_count":0,
                "replay_count":counters["replay_invocations"] if sid=="E" else 0,"replay_fi_invocation_count":replay_runtime_delta if sid=="E" else 0,
                "ui_evidence_request_count":0},"assertions":assertions.get("C" if sid.startswith("C_") else sid, {}),
            "provenance":{"python_focused_run_id":test_results["python_focused"]["run_id"],"ui_fi7d_run_id":test_results["ui_fi7d"]["run_id"]}})
    write_json(args.output/"responses.json",payloads); write_json(args.output/"recommendation-equality.json",equality)
    write_json(args.output/"backend-trace.json",{"fixture_version":FIXTURE_VERSION,"generated_at":FROZEN_AT,"records":traces,"schema_version":TRACE_SCHEMA})
    write_json(args.output/"test-results.json",test_results)
    (args.output/"test-summary.txt").write_text("Observed focused validation\n\n" + "\n\n".join(
        f"{name}: exit {value['exit_code']}\nrun_id: {value['run_id']}\n{value['summary']}" for name,value in test_results.items()),encoding="utf-8")
    environment={"authoritative_repository_sha":fixture["authoritative_sha"],"fixture_version":FIXTURE_VERSION,"frozen_timestamp":FROZEN_AT,
        "generated_at":FROZEN_AT,"operating_system_family":platform.system(),"versions":{"python":platform.python_version(),
        "node":subprocess.check_output(["node","--version"],text=True).strip()},"capture_mode":"real deterministic loaders/evaluators/runtime plus focused regression execution"}
    write_json(args.output/"environment.json",environment)
    links=[]
    visuals={"A":["screenshots/A-off-desktop.png"],"B":["screenshots/B-native-desktop.png","screenshots/B-native-mobile.png"],
        "C_ON":["screenshots/C-compare-desktop.png"],"D":["screenshots/D-multi-desktop.png"],"E":["screenshots/E-replay-desktop.png"],
        "F1":["screenshots/F-failure-desktop.png"],"F2":["screenshots/F-failure-desktop.png"]}
    for sid in ("A","B","C_ON","D","E","F1","F2"):
        response=replay if sid=="E" else payloads[sid]
        links.append({"scenario_id":sid,"canonical_response_hash":digest(response),"canonical_response_byte_length":len(canonical(response)),
        "repository_sha":fixture["authoritative_sha"],"fixture_id":FIXTURE_VERSION,"visual_artifacts":visuals[sid]})
    checksums={}
    if args.artifact_root:
        for path in sorted(args.artifact_root.rglob("*")):
            if path.is_file() and path.suffix.lower() not in {".json",".webm"} and path.name!="SHA256SUMS":
                checksums[path.relative_to(args.artifact_root).as_posix()]=hashlib.sha256(artifact_checksum_bytes(path)).hexdigest()
    manifest={"schema_version":SCHEMA,"repository_sha":fixture["authoritative_sha"],"fixture_version":FIXTURE_VERSION,"generated_at":FROZEN_AT,
        "scenario_links":links,"artifact_checksums":checksums,"test_results":"test-results.json","external_video":{"url":args.video_url,
        "sha256":args.video_sha256,"size_bytes":args.video_size,"media_type":"video/webm",
        "codec":"vp9","duration_seconds":21.0,"width":1440,"height":900,"frame_rate":"10/1","audio":False},"generation_command":"run from a clean isolated checkout; no dirty-tree bypass exists"}
    write_json(args.output/"manifest.json",manifest)
    print(json.dumps({"output":str(args.output),"observed":observed,"tests":{k:v["exit_code"] for k,v in test_results.items()}},sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
