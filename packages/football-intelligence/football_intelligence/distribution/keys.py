"""The sole grammar for canonical remote object keys."""
from __future__ import annotations

from football_intelligence.ingestion.builder import validate_build_id

POINTER_NAME = "_football_latest.json"
REPORT_PATHS = ("reports/build_report.json", "reports/quarantine.json", "reports/warnings.json")


def pointer_key(prefix: str) -> str:
    return f"{prefix}/{POINTER_NAME}"


def manifest_key(prefix: str, build_id: str) -> str:
    return f"{prefix}/builds/{validate_build_id(build_id)}/manifest.json"


def artifact_key(prefix: str, build_id: str, relative: str) -> str:
    governed = validate_build_id(build_id)
    valid = relative in REPORT_PATHS or (
        relative.startswith("canonical/") and relative.endswith(".parquet")
        and relative.count("/") == 1 and relative[10:-8].replace("_", "a").isalnum()
    )
    if not valid or "\\" in relative or ".." in relative:
        raise ValueError("remote artifact path is not governed")
    return f"{prefix}/builds/{governed}/{relative}"
