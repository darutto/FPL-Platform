"""
fpl_historical.manifest
=======================
Manifest dataclass and (de)serialisation helpers for the capture pipeline.

Public API (CONTRACT §7):
    Manifest            dataclass representing _manifest.json
    write_manifest()    serialise Manifest → _manifest.json
    read_manifest()     deserialise _manifest.json → Manifest
    sha256_bytes()      hex SHA-256 of raw bytes
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_MANIFEST_FILENAME = "_manifest.json"


@dataclass
class Manifest:
    """Structured representation of a capture run's ``_manifest.json``.

    Fields mirror CONTRACT §2 (v1) and CONTRACT §9.2 (v2) JSON shapes.

    V1 (baseline) fields — always present:
        schema_version, season, status, captured_at_utc, git_sha,
        fpl_endpoints, current_event_id, elapsed_seconds.

    V2 (incremental) optional extensions — default to None for v1 reads:
        kind        "incremental" for H2a snapshots.
        gameweek    Integer GW number for incremental captures.
        gw_state    Dict with finished/data_checked/is_current/deadline_time.
    """

    schema_version: int
    season: str
    status: Literal["complete", "complete_with_gaps", "failed"]
    captured_at_utc: str
    git_sha: str
    fpl_endpoints: dict
    current_event_id: int | None
    elapsed_seconds: float
    # V2 optional fields (default None so v1 reads parse without change)
    kind: str | None = None
    gameweek: int | None = None
    gw_state: dict | None = None


def sha256_bytes(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of *data*.

    Hash the **uncompressed** response body bytes so identical FPL API
    responses produce the same hash regardless of whether gzip was used
    in transit.
    """
    return hashlib.sha256(data).hexdigest()


def write_manifest(raw_dir: Path, m: Manifest) -> None:
    """Serialise *m* to ``<raw_dir>/_manifest.json`` (UTF-8, indent=2).

    V1 manifests (schema_version=1) are written with the same fields as
    before.  V2 manifests (schema_version=2) additionally include ``kind``,
    ``gameweek``, and ``gw_state``; ``current_event_id`` is omitted
    (not meaningful for incremental captures).  None values for optional
    fields are omitted from the output following the convention established
    by ``current_event_id`` in v1.
    """
    payload: dict = {
        "schema_version": m.schema_version,
        "season": m.season,
        "status": m.status,
        "captured_at_utc": m.captured_at_utc,
        "git_sha": m.git_sha,
        "fpl_endpoints": m.fpl_endpoints,
        "current_event_id": m.current_event_id,
        "elapsed_seconds": m.elapsed_seconds,
    }
    # V2 extensions — include only when present
    if m.kind is not None:
        payload["kind"] = m.kind
    if m.gameweek is not None:
        payload["gameweek"] = m.gameweek
    if m.gw_state is not None:
        payload["gw_state"] = m.gw_state
    manifest_path = raw_dir / _MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_manifest(raw_dir: Path) -> Manifest:
    """Deserialise ``<raw_dir>/_manifest.json`` into a :class:`Manifest`.

    Reads both schema_version=1 (v1 baseline) and schema_version=2 (v2
    incremental) manifests.  New optional fields (``kind``, ``gameweek``,
    ``gw_state``) default to ``None`` when absent, so v1 reads remain
    backward-compatible without raising.
    """
    manifest_path = raw_dir / _MANIFEST_FILENAME
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return Manifest(
        schema_version=data["schema_version"],
        season=data["season"],
        status=data["status"],
        captured_at_utc=data["captured_at_utc"],
        git_sha=data["git_sha"],
        fpl_endpoints=data["fpl_endpoints"],
        current_event_id=data.get("current_event_id"),
        elapsed_seconds=data["elapsed_seconds"],
        # V2 optional extensions — None when reading a v1 manifest
        kind=data.get("kind"),
        gameweek=data.get("gameweek"),
        gw_state=data.get("gw_state"),
    )
