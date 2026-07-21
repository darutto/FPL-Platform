"""Shared, immutable contracts for deterministic FI-6 modules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from football_data_contract.evidence import EvidenceItem


class ModuleStatus(str, Enum):
    OK = "ok"
    MISSING_CONTEXT = "missing_context"
    NOT_IMPLEMENTED = "not_implemented"


class UnsupportedFeatureContractError(ValueError):
    """A caller supplied a valid-looking feature family FI-6 cannot consume."""

    code = "unsupported_feature_contract"


@dataclass(frozen=True)
class ModuleResult:
    status: ModuleStatus
    model_version: str
    feature_registry_version: str | None
    feature_build_id: str | None
    fixture_id: str
    team_id: str
    confidence: float
    reason_codes: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("module confidence must be between 0 and 1")
        if not isinstance(self.reason_codes, tuple) or not isinstance(self.evidence, tuple):
            raise TypeError("module reason_codes and evidence must be immutable tuples")
