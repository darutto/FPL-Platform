from __future__ import annotations

import dataclasses
import json
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from football_intelligence.features.store_v2 import FeatureV2ValidationError
from football_intelligence.modules import UnsupportedFeatureContractError
from fpl_grounded_assistant import football_intelligence_runtime as runtime


CALCULATED_AT = "2026-08-01T12:00:00Z"


def _runtime(
    fixtures: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> runtime._Runtime:
    return runtime._Runtime(
        root=Path("unused"),
        base=object(),
        context_build=Path("context"),
        feature_build=Path("features"),
        calculated_at=CALCULATED_AT,
        context_fixtures=pd.DataFrame(fixtures),
        context_schedule=pd.DataFrame(schedules),
        team_targets=pd.DataFrame(targets),
    )


def _fixture(fixture_id: str, *, team_id: str = "team_a") -> dict[str, str]:
    return {
        "fixture_id": fixture_id,
        "home_team_id": team_id,
        "away_team_id": "team_b",
    }


def _schedule(
    fixture_id: str,
    kickoff: str | None,
    *,
    status: str = "scheduled",
    observed_at: str = "2026-08-01T11:00:00Z",
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "observed_at_utc": observed_at,
        "scheduled_kickoff_utc": kickoff,
        "status": status,
        "competition_tier": "tier_1",
    }


def _target(fixture_id: str, team_id: str = "team_a") -> dict[str, str]:
    return {"fixture_id": fixture_id, "team_id": team_id}


def test_fixture_selection_is_strict_future_scheduled_and_deterministic() -> None:
    fixtures = [_fixture(f"fixture_{value}") for value in ("z", "b", "a", "old")]
    schedules = [
        _schedule("fixture_z", "2026-08-03T12:00:00Z"),
        _schedule("fixture_b", "2026-08-02T12:00:00Z"),
        _schedule("fixture_a", "2026-08-02T12:00:00Z"),
        _schedule("fixture_old", CALCULATED_AT),
        _schedule("fixture_a", "2026-08-04T12:00:00Z", observed_at=CALCULATED_AT),
    ]
    targets = [_target(row["fixture_id"]) for row in fixtures]

    selected = runtime.select_target_fixture(
        _runtime(list(reversed(fixtures)), list(reversed(schedules)), targets),
        "team_a",
    )

    assert selected == "fixture_a"


@pytest.mark.parametrize("status", ["live", "completed", "postponed"])
def test_fixture_selection_excludes_non_scheduled_status(status: str) -> None:
    item = _runtime(
        [_fixture("fixture_bad")],
        [_schedule("fixture_bad", "2026-08-02T12:00:00Z", status=status)],
        [_target("fixture_bad")],
    )
    assert runtime.select_target_fixture(item, "team_a") is None


@pytest.mark.parametrize(
    ("fixtures", "schedules", "targets", "message"),
    [
        (
            [_fixture("fixture_a")],
            [_schedule("fixture_a", None)],
            [_target("fixture_a")],
            "scheduled_kickoff_utc",
        ),
        (
            [_fixture("")],
            [_schedule("", "2026-08-02T12:00:00Z")],
            [_target("")],
            "missing fixture_id",
        ),
        (
            [_fixture("fixture_a"), _fixture("fixture_a")],
            [_schedule("fixture_a", "2026-08-02T12:00:00Z")],
            [_target("fixture_a")],
            "duplicate fixture_id",
        ),
        (
            [_fixture("fixture_a")],
            [_schedule("fixture_a", "2026-08-02T12:00:00Z")],
            [_target("fixture_a"), _target("fixture_a")],
            "duplicate fixture target",
        ),
    ],
)
def test_fixture_selection_rejects_invalid_records(
    fixtures: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    message: str,
) -> None:
    with pytest.raises(FeatureV2ValidationError, match=message):
        runtime.select_target_fixture(_runtime(fixtures, schedules, targets), "team_a")


def _identity_frames(*, duplicate_player: bool = False) -> dict[str, pd.DataFrame]:
    player_rows = [
        {
            "canonical_player_id": "player_a",
            "provider": "fpl",
            "provider_id": "7",
            "team_provider_id": "1",
        }
    ]
    if duplicate_player:
        player_rows.append({**player_rows[0], "canonical_player_id": "player_b"})
    return {
        "player": pd.DataFrame(player_rows),
        "team": pd.DataFrame(
            [
                {
                    "canonical_team_id": "team_a",
                    "provider": "fpl",
                    "provider_id": "1",
                }
            ]
        ),
    }


def test_player_identity_uses_resolver_and_active_crosswalk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fpl_tool_contract.tool_resolve_player",
        lambda query, bootstrap: {
            "status": "ok",
            "player_id": 7,
            "position": "MID",
            "status_label": "Available",
        },
    )
    bootstrap = {"elements": [{"id": 7, "team": 1}]}
    assert runtime._resolve_player("Saka", bootstrap, _identity_frames()) == {
        "status": "ok",
        "player_id": "player_a",
        "team_id": "team_a",
        "provider_player_id": "7",
        "provider_team_id": "1",
        "nominal_position": "MID",
        "status_label": "Available",
        "element": {"id": 7, "team": 1},
    }


@pytest.mark.parametrize("status", ["not_found", "ambiguous"])
def test_player_resolution_preserves_terminal_resolver_result(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    expected = {"status": status, "query": "Saka"}
    monkeypatch.setattr(
        "fpl_tool_contract.tool_resolve_player",
        lambda query, bootstrap: expected,
    )
    assert runtime._resolve_player("Saka", {}, _identity_frames()) is expected


def test_player_resolution_rejects_ambiguous_active_crosswalk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fpl_tool_contract.tool_resolve_player",
        lambda query, bootstrap: {
            "status": "ok",
            "player_id": 7,
            "position": "MID",
            "status_label": "Available",
        },
    )
    with pytest.raises(runtime.IdentityRuntimeValidationError, match="conflicting"):
        runtime._resolve_player(
            "Saka",
            {"elements": [{"id": 7, "team": 1}]},
            _identity_frames(duplicate_player=True),
        )


class _Status(str, Enum):
    OK = "ok"
    MISSING = "missing_context"


@dataclasses.dataclass(frozen=True)
class _Evidence:
    code: str
    impact: float = 0.0


@dataclasses.dataclass(frozen=True)
class _Result:
    status: _Status
    fixture_id: str
    reason_codes: tuple[str, ...]
    evidence: tuple[_Evidence, ...]
    confidence: float = 0.5


def _result(
    status: _Status,
    code: str,
    evidence: tuple[_Evidence, ...] = (),
) -> _Result:
    return _Result(status, "fixture_a", (code,), evidence)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((_Status.OK, _Status.OK, _Status.OK), "ok"),
        ((_Status.OK, _Status.MISSING, _Status.MISSING), "partial"),
        ((_Status.MISSING, _Status.OK, _Status.OK), "partial"),
        ((_Status.MISSING, _Status.MISSING, _Status.MISSING), "missing_context"),
    ],
)
def test_composite_status_and_mapping_order(
    statuses: tuple[_Status, _Status, _Status],
    expected: str,
) -> None:
    results = {
        "expected_minutes": _result(statuses[0], "m1"),
        "tactical_role": _result(statuses[1], "m2"),
        "fixture_context": _result(statuses[2], "m3"),
    }
    value = runtime._composite(results)
    assert value["status"] == expected
    assert tuple(value["modules"]) == (
        "expected_minutes",
        "tactical_role",
        "fixture_context",
    )
    assert value["reason_codes"] == {
        "expected_minutes": ["m1"],
        "tactical_role": ["m2"],
        "fixture_context": ["m3"],
    }


def test_evidence_exact_dedup_first_occurrence_order_and_first_eight() -> None:
    duplicate = _Evidence("same")
    results = {
        "expected_minutes": _result(
            _Status.OK,
            "m1",
            tuple([duplicate, *(_Evidence(f"m1-{i}") for i in range(5))]),
        ),
        "tactical_role": _result(
            _Status.OK,
            "m2",
            (duplicate, _Evidence("same", impact=0.1), _Evidence("m2")),
        ),
        "fixture_context": _result(
            _Status.OK,
            "m3",
            (_Evidence("m3"),),
        ),
    }
    evidence = runtime._bounded_evidence(results)
    assert len(evidence) == 8
    assert [item["code"] for item in evidence] == [
        "same",
        "m1-0",
        "m1-1",
        "m1-2",
        "m1-3",
        "m1-4",
        "same",
        "m2",
    ]
    assert evidence[0]["impact"] == 0.0
    assert evidence[6]["impact"] == 0.1


def test_composite_module_order_is_fixed_and_each_module_runs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def load(name: str) -> Any:
        calls.append(f"load-{name}")
        return name

    def evaluate(name: str) -> _Result:
        calls.append(f"evaluate-{name}")
        return _result(
            _Status.MISSING if name == "tactical_role" else _Status.OK,
            name,
        )

    monkeypatch.setattr(
        "football_intelligence.modules.load_expected_minutes_input",
        lambda *args, **kwargs: load("expected_minutes"),
    )
    monkeypatch.setattr(
        "football_intelligence.modules.load_tactical_role_input",
        lambda *args, **kwargs: load("tactical_role"),
    )
    monkeypatch.setattr(
        "football_intelligence.modules.load_fixture_context_input",
        lambda *args, **kwargs: load("fixture_context"),
    )
    monkeypatch.setattr(
        "football_intelligence.modules.evaluate_expected_minutes",
        evaluate,
    )
    monkeypatch.setattr(
        "football_intelligence.modules.evaluate_tactical_role",
        evaluate,
    )
    monkeypatch.setattr(
        "football_intelligence.modules.evaluate_fixture_context",
        evaluate,
    )
    item = _runtime([_fixture("fixture_a")], [], [])
    resolved = {
        "team_id": "team_a",
        "player_id": "player_a",
        "nominal_position": "MID",
        "status_label": "Available",
        "element": {},
    }
    results = runtime._evaluate_modules(
        item,
        resolved,
        "fixture_a",
        ("expected_minutes", "tactical_role", "fixture_context"),
    )
    assert tuple(results) == (
        "expected_minutes",
        "tactical_role",
        "fixture_context",
    )
    assert calls == [
        "load-expected_minutes",
        "evaluate-expected_minutes",
        "load-tactical_role",
        "evaluate-tactical_role",
        "load-fixture_context",
        "evaluate-fixture_context",
    ]


def test_no_eligible_fixture_returns_missing_context_without_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _runtime(
        [_fixture("fixture_a")],
        [_schedule("fixture_a", CALCULATED_AT)],
        [_target("fixture_a")],
    )
    monkeypatch.setattr(runtime, "_load_runtime", lambda: item)
    monkeypatch.setattr(runtime, "_identity_tables", lambda *args: _identity_frames())
    monkeypatch.setattr(
        runtime,
        "_resolve_player",
        lambda *args: {
            "status": "ok",
            "player_id": "player_a",
            "team_id": "team_a",
        },
    )
    monkeypatch.setattr(
        runtime,
        "_evaluate_modules",
        lambda *args: pytest.fail("modules must not be invoked"),
    )
    assert runtime.run_football_intelligence_tool(
        "get_player_intelligence",
        {"player": "Saka"},
        {},
    ) == {
        "status": "missing_context",
        "reason_codes": ["fixture_context_row_unavailable"],
        "evidence": [],
        "player_id": "player_a",
        "team_id": "team_a",
        "fixture_id": None,
    }


@pytest.mark.parametrize(
    ("tool", "module"),
    [
        ("get_expected_minutes", "expected_minutes"),
        ("get_tactical_role", "tactical_role"),
        ("get_player_intelligence", "expected_minutes"),
    ],
)
def test_player_tools_reach_governed_module_path(
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    module: str,
) -> None:
    item = _runtime(
        [_fixture("fixture_a")],
        [_schedule("fixture_a", "2026-08-02T12:00:00Z")],
        [_target("fixture_a")],
    )
    monkeypatch.setattr(runtime, "_load_runtime", lambda: item)
    monkeypatch.setattr(runtime, "_identity_tables", lambda *args: _identity_frames())
    monkeypatch.setattr(
        runtime,
        "_resolve_player",
        lambda *args: {
            "status": "ok",
            "player_id": "player_a",
            "team_id": "team_a",
        },
    )
    called: list[tuple[str, ...]] = []

    def evaluate(*args: Any) -> dict[str, _Result]:
        names = args[-1]
        called.append(names)
        return {name: _result(_Status.OK, name) for name in names}

    monkeypatch.setattr(runtime, "_evaluate_modules", evaluate)
    result = runtime.run_football_intelligence_tool(tool, {"player": "Saka"}, {})
    assert result["status"] == "ok"
    assert called[0][0] == module
    assert called == [
        (
            ("expected_minutes", "tactical_role", "fixture_context")
            if tool == "get_player_intelligence"
            else (module,)
        )
    ]


def test_typed_module_failure_aborts_composite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _runtime(
        [_fixture("fixture_a")],
        [_schedule("fixture_a", "2026-08-02T12:00:00Z")],
        [_target("fixture_a")],
    )
    monkeypatch.setattr(runtime, "_load_runtime", lambda: item)
    monkeypatch.setattr(runtime, "_identity_tables", lambda *args: _identity_frames())
    monkeypatch.setattr(
        runtime,
        "_resolve_player",
        lambda *args: {
            "status": "ok",
            "player_id": "player_a",
            "team_id": "team_a",
        },
    )
    monkeypatch.setattr(
        runtime,
        "_evaluate_modules",
        lambda *args: (_ for _ in ()).throw(
            UnsupportedFeatureContractError("unsupported_feature_contract")
        ),
    )
    with pytest.raises(UnsupportedFeatureContractError):
        runtime.run_football_intelligence_tool(
            "get_player_intelligence",
            {"player": "Saka"},
            {},
        )


def test_build_pointer_rejects_raw_unvalidated_and_escaping_builds(
    tmp_path: Path,
) -> None:
    assert (
        runtime._pointer_build(
            tmp_path,
            "_features_v2_latest.json",
            "builds-v2",
            "feature_build_id",
            {"schema_version", "build_family", "feature_build_id"},
            {
                "schema_version": 2,
                "build_family": "module-enablement-features-v2",
            },
        )
        is None
    )
    (tmp_path / "_features_v2_latest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "build_family": "module-enablement-features-v2",
                "feature_build_id": "../raw",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FeatureV2ValidationError):
        runtime._pointer_build(
            tmp_path,
            "_features_v2_latest.json",
            "builds-v2",
            "feature_build_id",
            {"schema_version", "build_family", "feature_build_id"},
            {
                "schema_version": 2,
                "build_family": "module-enablement-features-v2",
            },
        )


def test_runtime_loads_only_validated_bound_v2_builds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = tmp_path / "builds-v2" / "context-a"
    feature = tmp_path / "features" / "builds-v2" / "feature-a"
    context.mkdir(parents=True)
    feature.mkdir(parents=True)
    (tmp_path / "_football_v2_latest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "build_id": "context-a",
                "manifest": "builds-v2/context-a/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "features" / "_features_v2_latest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "build_family": "module-enablement-features-v2",
                "feature_build_id": "feature-a",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "football_intelligence.ingestion.builder_v2.validate_context_build",
        lambda path: calls.append(f"context:{path.name}")
        or {
            "entity_files": {
                "fixtures": "fixtures.parquet",
                "fixture_schedule_snapshots": "schedule.parquet",
            }
        },
    )
    monkeypatch.setattr(
        "football_intelligence.features.store_v2.validate_feature_build_v2",
        lambda path, base, context_path: calls.append(
            f"feature:{path.name}:{context_path.name}"
        )
        or {
            "built_at": CALCULATED_AT,
            "output_files": {
                "team_fixture_context_v2": "targets.parquet",
            },
        },
    )
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda path: pd.DataFrame({"source": [Path(path).name]}),
    )

    loaded = runtime._load_runtime(tmp_path)

    assert loaded is not None
    assert loaded.calculated_at == CALCULATED_AT
    assert calls == ["context:context-a", "feature:feature-a:context-a"]
    assert loaded.context_fixtures.iloc[0]["source"] == "fixtures.parquet"
    assert loaded.context_schedule.iloc[0]["source"] == "schedule.parquet"
    assert loaded.team_targets.iloc[0]["source"] == "targets.parquet"


@pytest.mark.parametrize(
    "failure",
    [
        FeatureV2ValidationError("invalid feature build"),
        UnsupportedFeatureContractError("unsupported_feature_contract"),
    ],
)
def test_runtime_propagates_invalid_or_unsupported_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
) -> None:
    context = tmp_path / "builds-v2" / "context-a"
    feature = tmp_path / "features" / "builds-v2" / "feature-a"
    context.mkdir(parents=True)
    feature.mkdir(parents=True)
    (tmp_path / "_football_v2_latest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "build_id": "context-a",
                "manifest": "builds-v2/context-a/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "features" / "_features_v2_latest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "build_family": "module-enablement-features-v2",
                "feature_build_id": "feature-a",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "football_intelligence.ingestion.builder_v2.validate_context_build",
        lambda path: {
            "entity_files": {
                "fixtures": "fixtures.parquet",
                "fixture_schedule_snapshots": "schedule.parquet",
            }
        },
    )
    monkeypatch.setattr(
        "football_intelligence.features.store_v2.validate_feature_build_v2",
        lambda *args: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(type(failure), match=str(failure)):
        runtime._load_runtime(tmp_path)


def test_serialization_is_repeated_evaluation_stable() -> None:
    results = {
        "expected_minutes": _result(_Status.OK, "m1", (_Evidence("a"),)),
        "tactical_role": _result(_Status.MISSING, "m2"),
        "fixture_context": _result(_Status.OK, "m3", (_Evidence("b"),)),
    }
    first = runtime._composite(results)
    second = runtime._composite(dict(reversed(tuple(reversed(results.items())))))
    assert json.dumps(first, separators=(",", ":")) == json.dumps(
        second,
        separators=(",", ":"),
    )
