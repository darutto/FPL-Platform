"""Provider references and traceability metadata for canonical records."""
from dataclasses import dataclass
from datetime import datetime

from .enums import ProviderIdentifier


def _require_utc_iso(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field_name} must be UTC")


@dataclass(frozen=True)
class ProviderRef:
    provider: ProviderIdentifier
    provider_id: str
    valid_from: str
    valid_to: str | None = None


@dataclass(frozen=True)
class Provenance:
    source_provider: ProviderIdentifier
    ingested_at: str
    source_timestamp: str | None
    ingestion_run_id: str
    model_version: str | None = None

    def __post_init__(self) -> None:
        _require_utc_iso(self.ingested_at, "ingested_at")
        if self.source_timestamp is not None:
            _require_utc_iso(self.source_timestamp, "source_timestamp")
