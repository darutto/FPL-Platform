"""Pure FI-6 intelligence modules; no tools, responses, orchestration, or UI."""
from .contracts import ModuleResult, ModuleStatus, UnsupportedFeatureContractError
from .expected_minutes import (
    AvailabilityInput,
    ExpectedMinutesInput,
    ExpectedMinutesResult,
    evaluate_expected_minutes,
    load_expected_minutes_input,
)
from .fixture_context import (
    FixtureContextInput,
    FixtureContextResult,
    FixturePriority,
    evaluate_fixture_context,
    load_fixture_context_input,
)
from .tactical_role import (
    FlankShare,
    RoleDistributionRow,
    RoleShare,
    RoleWindowSummary,
    TacticalRoleInput,
    TacticalRoleResult,
    evaluate_tactical_role,
    load_tactical_role_input,
)

__all__ = [
    "AvailabilityInput",
    "ExpectedMinutesInput",
    "ExpectedMinutesResult",
    "FixtureContextInput",
    "FixtureContextResult",
    "FixturePriority",
    "FlankShare",
    "ModuleResult",
    "ModuleStatus",
    "RoleDistributionRow",
    "RoleShare",
    "RoleWindowSummary",
    "TacticalRoleInput",
    "TacticalRoleResult",
    "UnsupportedFeatureContractError",
    "evaluate_expected_minutes",
    "evaluate_fixture_context",
    "evaluate_tactical_role",
    "load_expected_minutes_input",
    "load_fixture_context_input",
    "load_tactical_role_input",
]
