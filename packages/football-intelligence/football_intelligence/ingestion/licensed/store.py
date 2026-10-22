"""Licensed matchday store, step 2: derived tables -> an immutable build, and its distribution family.

A build is ``datasets/<table>.parquet`` + ``reports/derive_report.json`` + ``manifest.json``, stamped
``licensed_starter`` with the licensed normalizer and source kind (``provenance``). It is published and synced
by the shared ``distribution`` path through :data:`LICENSED_V1`: own prefix (``football-licensed``), own pointer
name, and only this store's files are governed. Decisions a reviewer should be able to find:

* **History is kept.** The snapshot tables (lineups, slots, sidelined, squads) of a new build are the previous
  build's rows plus this pass's, de-duplicated on their full key, so the latest build holds the whole season
  (PROD_INGESTION.md, open question 3). The crosswalk and the cup snapshots are replaced: they are state, not
  history.
* **The validator rebuilds nothing and trusts nothing:** exact manifest fields, the licensed binding, exactly
  the governed files, byte hashes and row counts.
* **The crosswalk table is the only one with provider ids.** It is stored in the private bucket (the licence
  allows storing); it is never logged and never served.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from football_intelligence.distribution.family import BuildFamily
from football_intelligence.provenance import LICENSED_NORMALIZER, LICENSED_SOURCE_KIND, LICENSED_STARTER

from .derive import DerivedTables

MANIFEST_SCHEMA_VERSION = 1
BUILD_FAMILY = "licensed-matchday-v1"
POINTER_NAME = "_football_licensed_latest.json"
PREFIX_SEGMENT = "football-licensed"
REPORT_PATH = "reports/derive_report.json"
#: Table -> (columns, the key a row is unique on). Snapshot tables accumulate; the others are replaced.
TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "lineup_snapshots": (("fixture_id", "team", "observed_at", "state", "confirmed", "formation", "n_starters", "n_bench"),
                         ("fixture_id", "team", "observed_at")),
    "lineup_slots": (("fixture_id", "team", "observed_at", "element", "starter", "detailed_position", "grid_slot", "side"),
                     ("fixture_id", "team", "observed_at", "element")),
    "sidelined": (("element", "team", "category", "start_date", "end_date", "games_missed", "completed", "observed_at"),
                  ("element", "category", "start_date", "observed_at")),
    "squad_membership": (("team", "element", "jersey_number", "observed_at"), ("team", "element", "observed_at")),
    "crosswalk": (("sportmonks_player_id", "element"), ("sportmonks_player_id",)),
    "cup_snapshots": (("competition", "season", "source", "fetched_at", "complete_as_of", "postponed", "unmapped_count"),
                      ("competition",)),
    "cup_records": (("competition", "season", "club", "opponent", "opponent_code", "kickoff_utc", "venue", "status",
                     "source", "fetched_at", "gameweek"), ("competition", "club", "kickoff_utc")),
}
HISTORY_TABLES = ("lineup_snapshots", "lineup_slots", "sidelined", "squad_membership")
MANIFEST_FIELDS = {"schema_version", "build_family", "build_id", "built_at", "assumption_status", "normalizer_versions",
                   "source", "files", "row_counts"}
_BUILD_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class LicensedStoreError(ValueError):
    """A licensed build is not in the governed shape."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _governed(relative: str) -> bool:
    return relative == REPORT_PATH or relative in {f"datasets/{name}.parquet" for name in TABLES}


def _frame(name: str, rows) -> pd.DataFrame:
    columns, key = TABLES[name]
    frame = pd.DataFrame(list(rows), columns=list(columns)).astype(object)
    return frame.drop_duplicates(subset=list(key), keep="last").sort_values(list(key), kind="stable").reset_index(drop=True)


def _rows(tables: DerivedTables, crosswalk: Mapping[int, int]) -> dict[str, list[dict[str, Any]]]:
    cups = [{"competition": c.competition, "season": c.season, "source": c.source, "fetched_at": c.fetched_at,
             "complete_as_of": c.complete_as_of, "postponed": c.postponed, "unmapped_count": len(c.unmapped)}
            for c in tables.cup_snapshots]
    return {"lineup_snapshots": list(tables.lineup_snapshots), "lineup_slots": list(tables.lineup_slots),
            "sidelined": list(tables.sidelined), "squad_membership": list(tables.squad_membership),
            "crosswalk": [{"sportmonks_player_id": k, "element": v} for k, v in sorted(crosswalk.items())],
            "cup_snapshots": cups, "cup_records": [asdict(r) for c in tables.cup_snapshots for r in c.records]}


def write_build(tables: DerivedTables, crosswalk: Mapping[int, int], destination: Path, *, build_id: str,
                built_at: str, previous: Path | None = None) -> Path:
    """Write one immutable build under ``destination/builds/<build_id>``; ``previous`` is the last build, whose
    history tables are carried forward."""
    if not isinstance(build_id, str) or _BUILD_ID.fullmatch(build_id) is None:
        raise LicensedStoreError("build_id must match [a-z0-9]+(?:-[a-z0-9]+)*")
    rows = _rows(tables, crosswalk)
    if previous is not None:
        validate_build(previous)
        for name in HISTORY_TABLES:
            old = pd.read_parquet(previous / f"datasets/{name}.parquet").astype(object)
            rows[name] = [*old.where(pd.notna(old), None).to_dict("records"), *rows[name]]
    final = destination / "builds" / build_id
    if final.exists():
        raise FileExistsError(f"build already exists: {build_id}")
    staging = destination / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f"{build_id}-", dir=staging))
    try:
        (stage / "datasets").mkdir()
        (stage / "reports").mkdir()
        files: dict[str, str] = {}
        counts: dict[str, int] = {}
        for name in TABLES:
            frame = _frame(name, rows[name])
            path = stage / f"datasets/{name}.parquet"
            frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
            files[f"datasets/{name}.parquet"] = _sha(path.read_bytes())
            counts[name] = len(frame)
        report = (json.dumps(asdict(tables.report), indent=2, sort_keys=True) + "\n").encode()
        (stage / REPORT_PATH).write_bytes(report)
        files[REPORT_PATH] = _sha(report)
        manifest = {"schema_version": MANIFEST_SCHEMA_VERSION, "build_family": BUILD_FAMILY, "build_id": build_id,
                    "built_at": built_at, "assumption_status": LICENSED_STARTER,
                    "normalizer_versions": {"licensed_adapter": LICENSED_NORMALIZER},
                    "source": {"source_kind": LICENSED_SOURCE_KIND}, "files": dict(sorted(files.items())),
                    "row_counts": counts}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_build(stage)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage, final)
        return final
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def validate_build(build: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LicensedStoreError("licensed manifest is unreadable") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise LicensedStoreError("licensed manifest fields are not governed")
    if (manifest["schema_version"] != MANIFEST_SCHEMA_VERSION or manifest["build_family"] != BUILD_FAMILY
            or not isinstance(manifest["build_id"], str) or _BUILD_ID.fullmatch(manifest["build_id"]) is None):
        raise LicensedStoreError("licensed manifest version, family or build id is unsupported")
    if (manifest["assumption_status"] != LICENSED_STARTER
            or manifest["normalizer_versions"] != {"licensed_adapter": LICENSED_NORMALIZER}
            or manifest["source"] != {"source_kind": LICENSED_SOURCE_KIND}):
        raise LicensedStoreError("unsupported licensed binding")
    expected = {REPORT_PATH, *(f"datasets/{name}.parquet" for name in TABLES)}
    if set(manifest["files"]) != expected or set(manifest["row_counts"]) != set(TABLES):
        raise LicensedStoreError("licensed file registry mismatch")
    for relative, digest in manifest["files"].items():
        path = (build / relative).resolve()
        path.relative_to(build.resolve())
        if _sha(path.read_bytes()) != digest:
            raise LicensedStoreError("licensed file hash mismatch")
    for name, (columns, _key) in TABLES.items():
        frame = pd.read_parquet(build / f"datasets/{name}.parquet")
        if tuple(frame.columns) != columns or len(frame) != manifest["row_counts"][name]:
            raise LicensedStoreError(f"licensed table {name} does not match its manifest")
    return manifest


LICENSED_V1 = BuildFamily(
    name=BUILD_FAMILY, manifest_schema_version=MANIFEST_SCHEMA_VERSION, pointer_name=POINTER_NAME,
    validate=validate_build, artifact_paths=lambda manifest: tuple(sorted(manifest["files"])),
    expected_hash=lambda manifest, relative: manifest["files"][relative], governed_path=_governed,
    prefix_segment=PREFIX_SEGMENT,
)
