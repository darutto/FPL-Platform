"""Build families: what differs between the kinds of build that ``publish_build`` / ``sync_build`` move.

The pointer protocol, the pointer race guard, bounded reads, hash checks, the sync lock and the refusal of
trial data are shared and live in ``service.py``; a family supplies only what its own build looks like:
its manifest version, how to validate a build directory, which files it publishes and their hashes, which
relative paths are governed, its pointer's name, and the prefix it owns. ``CANONICAL_V1`` is the canonical
store exactly as it was before families existed, and the default everywhere.

Prefixes keep families apart (``keys.RESERVED_PREFIX_SEGMENTS``): a family that owns a segment may only
use a prefix ending in it, and the canonical family refuses any prefix ending in a reserved segment. Each
family also has its own pointer name, so even a misrouted read cannot pick up another family's pointer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from football_intelligence.ingestion.builder import MANIFEST_SCHEMA_VERSION

from .errors import DistributionError, RemoteValidationError
from .keys import POINTER_NAME, RESERVED_PREFIX_SEGMENTS, is_canonical_artifact_path


class FamilyPrefixError(DistributionError):
    """A family was asked to publish or sync under a prefix it does not own."""


@dataclass(frozen=True)
class BuildFamily:
    name: str
    manifest_schema_version: int
    pointer_name: str
    validate: Callable[[Path], dict[str, Any]]
    artifact_paths: Callable[[Mapping[str, Any]], tuple[str, ...]]
    expected_hash: Callable[[Mapping[str, Any], str], str]
    governed_path: Callable[[str], bool]
    #: The reserved last prefix segment this family owns; None for the canonical family.
    prefix_segment: str | None = None

    def __post_init__(self) -> None:
        if self.prefix_segment is not None and self.prefix_segment not in RESERVED_PREFIX_SEGMENTS:
            raise ValueError("a family's prefix segment must be reserved in keys.RESERVED_PREFIX_SEGMENTS")

    def check_prefix(self, prefix: str) -> None:
        last = prefix.rstrip("/").rsplit("/", 1)[-1]
        if self.prefix_segment is None:
            if last in RESERVED_PREFIX_SEGMENTS:
                raise FamilyPrefixError(f"prefix is reserved for another build family ({self.name} refused)")
        elif last != self.prefix_segment:
            raise FamilyPrefixError(f"the {self.name} family publishes only under a prefix ending in {self.prefix_segment!r}")


def _canonical_validate(build_dir: Path) -> dict[str, Any]:
    # Looked up on ``service`` at call time: ``service.validate_build`` was the patch point before families
    # existed (test_distribution's pre-activation test), and the canonical family keeps it.
    from . import service
    return service.validate_build(build_dir)


def _canonical_artifact_paths(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    entities = manifest.get("entity_files")
    reports = manifest.get("report_files")
    if not isinstance(entities, dict) or not isinstance(reports, dict):
        raise RemoteValidationError("manifest artifact registries are missing")
    return tuple(sorted([*entities.values(), *reports.values()]))


def _canonical_expected_hash(manifest: Mapping[str, Any], relative: str) -> str:
    for name, path in manifest["entity_files"].items():
        if path == relative:
            return manifest["parquet_byte_hashes"][name]
    for name, path in manifest["report_files"].items():
        if path == relative:
            return manifest["report_byte_hashes"][name]
    raise RemoteValidationError("manifest references an ungoverned artifact")


CANONICAL_V1 = BuildFamily(
    name="canonical-v1", manifest_schema_version=MANIFEST_SCHEMA_VERSION, pointer_name=POINTER_NAME,
    validate=_canonical_validate, artifact_paths=_canonical_artifact_paths, expected_hash=_canonical_expected_hash,
    governed_path=is_canonical_artifact_path,
)
