"""FI-7b2 deterministic, read-only Football Intelligence runtime adapter."""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import pandas as pd


class IdentityRuntimeValidationError(ValueError):
    """The active identity crosswalk is invalid or contradictory."""


def _serialized(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _serialized(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {key: _serialized(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialized(item) for item in value]
    return value


def _missing(reason: str, **values: Any) -> dict[str, Any]:
    return {
        "status": "missing_context",
        "reason_codes": [reason],
        "evidence": [],
        **values,
    }


def _pointer_build(
    root: Path,
    pointer_name: str,
    builds_name: str,
    id_name: str,
    expected_fields: set[str],
    expected_values: dict[str, Any],
) -> Path | None:
    from football_intelligence.features.store_v2 import FeatureV2ValidationError

    pointer_path = root / pointer_name
    if not pointer_path.is_file():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureV2ValidationError(f"invalid {pointer_name} pointer") from exc
    if not isinstance(pointer, dict) or set(pointer) != expected_fields:
        raise FeatureV2ValidationError(f"invalid {pointer_name} pointer")
    if any(pointer.get(key) != value for key, value in expected_values.items()):
        raise FeatureV2ValidationError(f"unsupported {pointer_name} pointer")
    build_id = pointer.get(id_name)
    if not isinstance(build_id, str) or not build_id:
        raise FeatureV2ValidationError(f"invalid {pointer_name} build ID")
    if (
        "manifest" in pointer
        and pointer["manifest"] != f"{builds_name}/{build_id}/manifest.json"
    ):
        raise FeatureV2ValidationError(f"invalid {pointer_name} manifest binding")
    build = (root / builds_name / build_id).resolve()
    try:
        build.relative_to((root / builds_name).resolve())
    except ValueError as exc:
        raise FeatureV2ValidationError(f"{pointer_name} pointer escapes") from exc
    if not build.is_dir() or build.is_symlink():
        raise FeatureV2ValidationError(f"invalid {pointer_name} build directory")
    return build


@dataclasses.dataclass(frozen=True)
class _Runtime:
    root: Path
    base: Any
    context_build: Path
    feature_build: Path
    calculated_at: str
    context_fixtures: pd.DataFrame
    context_schedule: pd.DataFrame
    team_targets: pd.DataFrame


def _load_runtime(root: Path | None = None) -> _Runtime | None:
    """Resolve and validate one immutable FI-5b v2 runtime snapshot."""
    from football_intelligence.distribution.runtime import RuntimeBuildHandle
    from football_intelligence.features.store_v2 import validate_feature_build_v2
    from football_intelligence.ingestion.builder_v2 import validate_context_build

    selected_root = root or Path(
        os.environ.get("FPL_FOOTBALL_ROOT", "data/football")
    )
    feature_root = selected_root / "features"
    feature_build = _pointer_build(
        feature_root,
        "_features_v2_latest.json",
        "builds-v2",
        "feature_build_id",
        {"schema_version", "build_family", "feature_build_id"},
        {
            "schema_version": 2,
            "build_family": "module-enablement-features-v2",
        },
    )
    context_build = _pointer_build(
        selected_root,
        "_football_v2_latest.json",
        "builds-v2",
        "build_id",
        {"schema_version", "build_id", "manifest"},
        {"schema_version": 2},
    )
    if feature_build is None or context_build is None:
        return None

    base = RuntimeBuildHandle(selected_root)
    try:
        context_manifest = validate_context_build(context_build)
    except ValueError as exc:
        from football_intelligence.features.store_v2 import FeatureV2ValidationError

        raise FeatureV2ValidationError("invalid bound v2 context build") from exc
    feature_manifest = validate_feature_build_v2(feature_build, base, context_build)
    context_fixtures = pd.read_parquet(
        context_build / context_manifest["entity_files"]["fixtures"]
    )
    context_schedule = pd.read_parquet(
        context_build
        / context_manifest["entity_files"]["fixture_schedule_snapshots"]
    )
    team_targets = pd.read_parquet(
        feature_build
        / feature_manifest["output_files"]["team_fixture_context_v2"]
    )
    return _Runtime(
        root=selected_root,
        base=base,
        context_build=context_build,
        feature_build=feature_build,
        calculated_at=str(feature_manifest["built_at"]),
        context_fixtures=context_fixtures,
        context_schedule=context_schedule,
        team_targets=team_targets,
    )


def _active_rows(frame: pd.DataFrame, calculated_at: str) -> pd.DataFrame:
    try:
        cutoff_date = date.fromisoformat(calculated_at[:10])
        starts = frame["valid_from"].map(date.fromisoformat)
        ends = frame["valid_to"].map(
            lambda value: None if pd.isna(value) else date.fromisoformat(str(value))
        )
    except (TypeError, ValueError) as exc:
        raise IdentityRuntimeValidationError(
            "invalid identity validity interval"
        ) from exc
    if any(
        end is not None and end < start
        for start, end in zip(starts, ends, strict=True)
    ):
        raise IdentityRuntimeValidationError("invalid identity validity interval")
    return frame[
        (starts <= cutoff_date)
        & ends.map(lambda value: value is None or cutoff_date <= value)
    ]


def _identity_tables(root: Path, calculated_at: str) -> dict[str, pd.DataFrame] | None:
    from football_data_contract import ProviderIdentifier
    from football_identity_registry.store import IdentityStore, OTHER_COLUMNS

    store = IdentityStore(root / "identity")
    errors = store.verify()
    if errors:
        if all(error.startswith("missing ") for error in errors):
            return None
        raise IdentityRuntimeValidationError("; ".join(sorted(errors)))
    tables: dict[str, pd.DataFrame] = {
        "player": pd.DataFrame(
            [dataclasses.asdict(row) for row in store.read_players()]
        )
    }
    for name, columns in OTHER_COLUMNS.items():
        path = store.root / f"{name}_identity.parquet"
        frame = pd.read_parquet(path)
        if tuple(frame.columns) != columns:
            raise IdentityRuntimeValidationError(
                f"invalid {name} identity schema"
            )
        tables[name] = frame
    for frame in tables.values():
        known = {item.value for item in ProviderIdentifier}
        unknown = set(frame["provider"].astype(str)) - known
        if unknown:
            raise IdentityRuntimeValidationError("unknown identity provider")
    return {
        name: _active_rows(frame, calculated_at)
        for name, frame in tables.items()
    }


def _one_mapping(
    frame: pd.DataFrame,
    *,
    provider_id: str,
    canonical_column: str,
) -> str | None:
    selected = frame[
        (frame["provider"].astype(str) == "fpl")
        & (frame["provider_id"].astype(str) == provider_id)
    ]
    if selected.empty:
        return None
    values = tuple(sorted(set(selected[canonical_column].astype(str))))
    if len(selected) != 1 or len(values) != 1:
        raise IdentityRuntimeValidationError(
            f"conflicting active FPL mapping for {provider_id}"
        )
    return values[0]


def _resolve_player(
    query: Any,
    bootstrap: dict[str, Any],
    identities: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    from fpl_tool_contract import tool_resolve_player

    resolved = tool_resolve_player(query, bootstrap)
    if resolved["status"] != "ok":
        return resolved
    provider_player_id = str(resolved["player_id"])
    player_id = _one_mapping(
        identities["player"],
        provider_id=provider_player_id,
        canonical_column="canonical_player_id",
    )
    element = next(
        (
            item
            for item in bootstrap.get("elements", ())
            if str(item.get("id")) == provider_player_id
        ),
        None,
    )
    if element is None:
        raise IdentityRuntimeValidationError("resolved FPL player row is absent")
    provider_team_id = str(element.get("team", ""))
    team_id = _one_mapping(
        identities["team"],
        provider_id=provider_team_id,
        canonical_column="canonical_team_id",
    )
    if player_id is None or team_id is None:
        return _missing(
            "identity_context_unavailable",
            query=str(query),
        )
    player_rows = identities["player"][
        (identities["player"]["provider"].astype(str) == "fpl")
        & (identities["player"]["provider_id"].astype(str) == provider_player_id)
    ]
    scoped_team = player_rows.iloc[0]["team_provider_id"]
    if not pd.isna(scoped_team) and str(scoped_team) != provider_team_id:
        raise IdentityRuntimeValidationError(
            "player/team identity mapping contradiction"
        )
    return {
        "status": "ok",
        "player_id": player_id,
        "team_id": team_id,
        "provider_player_id": provider_player_id,
        "provider_team_id": provider_team_id,
        "nominal_position": (
            "GK" if resolved.get("position") == "GKP" else resolved.get("position")
        ),
        "status_label": resolved.get("status_label"),
        "element": element,
    }


def _resolve_team_fixture(
    team_query: Any,
    fixture_query: Any,
    bootstrap: dict[str, Any],
    identities: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    from football_data_contract import validate_canonical_id

    team_text = str(team_query).strip()
    team_id: str | None = None
    if team_text.startswith("team_"):
        try:
            validate_canonical_id("team", team_text)
        except ValueError as exc:
            raise IdentityRuntimeValidationError(
                "invalid canonical team identity"
            ) from exc
        team_id = team_text
    else:
        folded = team_text.casefold()
        matches = [
            team
            for team in bootstrap.get("teams", ())
            if folded
            in {
                str(team.get("id", "")).casefold(),
                str(team.get("name", "")).casefold(),
                str(team.get("short_name", "")).casefold(),
            }
        ]
        if not matches:
            return {"status": "not_found", "query": team_text}
        if len(matches) != 1:
            return {"status": "ambiguous", "query": team_text}
        team_id = _one_mapping(
            identities["team"],
            provider_id=str(matches[0]["id"]),
            canonical_column="canonical_team_id",
        )
    if team_id is None:
        return _missing("identity_context_unavailable")

    fixture_text = str(fixture_query).strip()
    fixture_id: str | None = None
    if fixture_text.startswith("fixture_"):
        try:
            validate_canonical_id("fixture", fixture_text)
        except ValueError as exc:
            raise IdentityRuntimeValidationError(
                "invalid canonical fixture identity"
            ) from exc
        fixture_id = fixture_text
    else:
        fixture_id = _one_mapping(
            identities["fixture"],
            provider_id=fixture_text,
            canonical_column="canonical_fixture_id",
        )
    if fixture_id is None:
        return _missing("identity_context_unavailable")
    return {"status": "ok", "team_id": team_id, "fixture_id": fixture_id}


def _parse_utc(value: Any, label: str) -> datetime:
    from football_intelligence.features.store_v2 import FeatureV2ValidationError

    if not isinstance(value, str) or not value:
        raise FeatureV2ValidationError(f"{label} must be UTC ISO")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeatureV2ValidationError(f"{label} must be UTC ISO") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise FeatureV2ValidationError(f"{label} must be UTC")
    return parsed


def select_target_fixture(runtime: _Runtime, team_id: str) -> str | None:
    """Select the earliest strict-future scheduled target, then fixture ID."""
    from football_intelligence.features.store_v2 import FeatureV2ValidationError
    from football_intelligence.ingestion.context_v2 import select_schedule

    fixtures = runtime.context_fixtures
    schedule = runtime.context_schedule
    if (
        fixtures["fixture_id"].isna().any()
        or schedule["fixture_id"].isna().any()
        or (fixtures["fixture_id"].astype(str).str.strip() == "").any()
        or (schedule["fixture_id"].astype(str).str.strip() == "").any()
    ):
        raise FeatureV2ValidationError("missing fixture_id")
    if fixtures.duplicated(["fixture_id"]).any():
        raise FeatureV2ValidationError("duplicate fixture_id")
    if runtime.team_targets.duplicated(["fixture_id", "team_id"]).any():
        raise FeatureV2ValidationError("duplicate fixture target")

    selected_schedule = select_schedule(
        tuple(schedule.astype(object).where(pd.notna(schedule), None).to_dict("records")),
        runtime.calculated_at,
    )
    known = {str(row["fixture_id"]): row for row in selected_schedule}
    target_ids = set(
        runtime.team_targets[
            runtime.team_targets["team_id"].astype(str) == team_id
        ]["fixture_id"].astype(str)
    )
    cutoff = _parse_utc(runtime.calculated_at, "calculated_at")
    candidates: list[tuple[datetime, str]] = []
    for row in fixtures.itertuples(index=False):
        fixture_id = str(row.fixture_id)
        if team_id not in (str(row.home_team_id), str(row.away_team_id)):
            continue
        selected = known.get(fixture_id)
        if selected is None or fixture_id not in target_ids:
            continue
        kickoff = _parse_utc(
            selected.get("scheduled_kickoff_utc"),
            "scheduled_kickoff_utc",
        )
        if selected.get("status") == "scheduled" and cutoff < kickoff:
            candidates.append((kickoff, fixture_id))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1] if candidates else None


def _availability(resolved: dict[str, Any]) -> Any:
    from football_data_contract import AvailabilityState
    from football_intelligence.modules import AvailabilityInput

    states = {
        "Available": AvailabilityState.AVAILABLE,
        "Doubtful": AvailabilityState.DOUBTFUL,
        "Injured": AvailabilityState.INJURED,
        "Suspended": AvailabilityState.SUSPENDED,
        "Unavailable": AvailabilityState.UNREGISTERED,
    }
    state = states.get(str(resolved.get("status_label")), AvailabilityState.UNKNOWN)
    chance = resolved["element"].get("chance_of_playing_next_round")
    chance_fraction = (
        float(chance) / 100.0
        if state is AvailabilityState.DOUBTFUL and chance is not None
        else None
    )
    return AvailabilityInput(state=state, chance_of_playing=chance_fraction)


def _evaluate_modules(
    runtime: _Runtime,
    resolved: dict[str, Any],
    fixture_id: str,
    names: tuple[str, ...],
) -> dict[str, Any]:
    from football_intelligence.modules import (
        evaluate_expected_minutes,
        evaluate_fixture_context,
        evaluate_tactical_role,
        load_expected_minutes_input,
        load_fixture_context_input,
        load_tactical_role_input,
    )

    loaders: dict[str, Callable[[], Any]] = {
        "expected_minutes": lambda: evaluate_expected_minutes(
            load_expected_minutes_input(
                runtime.feature_build,
                runtime.base,
                runtime.context_build,
                fixture_id=fixture_id,
                team_id=resolved["team_id"],
                player_id=resolved["player_id"],
                calculated_at=runtime.calculated_at,
                availability=_availability(resolved),
            )
        ),
        "tactical_role": lambda: evaluate_tactical_role(
            load_tactical_role_input(
                runtime.feature_build,
                runtime.base,
                runtime.context_build,
                fixture_id=fixture_id,
                team_id=resolved["team_id"],
                player_id=resolved["player_id"],
                nominal_position=resolved["nominal_position"],
                calculated_at=runtime.calculated_at,
            )
        ),
        "fixture_context": lambda: evaluate_fixture_context(
            load_fixture_context_input(
                runtime.feature_build,
                runtime.base,
                runtime.context_build,
                fixture_id=fixture_id,
                team_id=resolved["team_id"],
                calculated_at=runtime.calculated_at,
            )
        ),
    }
    return {name: loaders[name]() for name in names}


def _bounded_evidence(results: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results.values():
        for evidence in result.evidence:
            value = _serialized(evidence)
            key = json.dumps(value, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                selected.append(value)
            if len(selected) == 8:
                return selected
    return selected


def _single(result: Any) -> dict[str, Any]:
    value = _serialized(result)
    value["evidence"] = _bounded_evidence({"result": result})
    return value


def _composite(results: dict[str, Any]) -> dict[str, Any]:
    statuses = tuple(result.status.value for result in results.values())
    if all(status == "ok" for status in statuses):
        status = "ok"
    elif any(status == "ok" for status in statuses):
        status = "partial"
    else:
        status = "missing_context"
    return {
        "status": status,
        "fixture_id": next(iter(results.values())).fixture_id,
        "modules": {name: _serialized(result) for name, result in results.items()},
        "reason_codes": {
            name: _serialized(result.reason_codes)
            for name, result in results.items()
        },
        "evidence": _bounded_evidence(results),
    }


def run_football_intelligence_tool(
    name: str,
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Execute one FI-7b2 tool without network, retries, or mutable state."""
    runtime = _load_runtime()
    if runtime is None:
        return _missing("feature_build_unavailable")
    identities = _identity_tables(runtime.root, runtime.calculated_at)
    if identities is None:
        return _missing("identity_context_unavailable")

    if name == "get_fixture_context":
        resolved = _resolve_team_fixture(
            args["team"], args["fixture"], bootstrap, identities
        )
        if resolved["status"] != "ok":
            return resolved
        fixture_rows = runtime.context_fixtures[
            runtime.context_fixtures["fixture_id"].astype(str)
            == resolved["fixture_id"]
        ]
        if len(fixture_rows) != 1:
            if fixture_rows.empty:
                return _missing("fixture_context_row_unavailable")
            from football_intelligence.features.store_v2 import FeatureV2ValidationError
            raise FeatureV2ValidationError("duplicate fixture_id")
        fixture = fixture_rows.iloc[0]
        if resolved["team_id"] not in (
            str(fixture.home_team_id),
            str(fixture.away_team_id),
        ):
            raise IdentityRuntimeValidationError("team/fixture identity mismatch")
        module_resolved = {
            **resolved,
            "player_id": "",
            "nominal_position": None,
            "status_label": None,
            "element": {},
        }
        result = _evaluate_modules(
            runtime,
            module_resolved,
            resolved["fixture_id"],
            ("fixture_context",),
        )
        return _single(result["fixture_context"])

    resolved = _resolve_player(args["player"], bootstrap, identities)
    if resolved["status"] != "ok":
        return resolved
    fixture_id = select_target_fixture(runtime, resolved["team_id"])
    if fixture_id is None:
        return _missing(
            "fixture_context_row_unavailable",
            player_id=resolved["player_id"],
            team_id=resolved["team_id"],
            fixture_id=None,
        )
    names = {
        "get_expected_minutes": ("expected_minutes",),
        "get_tactical_role": ("tactical_role",),
        "get_player_intelligence": (
            "expected_minutes",
            "tactical_role",
            "fixture_context",
        ),
    }[name]
    results = _evaluate_modules(runtime, resolved, fixture_id, names)
    return _composite(results) if len(names) == 3 else _single(next(iter(results.values())))
