"""FI-7b1 non-operational football-intelligence tool shells.

These handlers intentionally perform no resolution, build loading, fixture
selection, module evaluation, evidence assembly, rendering, or network work.
FI-7b2 replaces them with governed implementations.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .tool_schema_registry import FI7B_TOOL_SCHEMAS


_NOT_IMPLEMENTED_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["not_implemented"]},
        "reason_codes": {
            "type": "array",
            "items": {"type": "string", "enum": ["not_implemented"]},
        },
        "message": {"type": "string"},
    },
    "required": ["status", "reason_codes", "message"],
}


def _not_implemented_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Return the deterministic FI-7b1 non-operational result."""
    del args, bootstrap
    return {
        "status": "not_implemented",
        "reason_codes": ["not_implemented"],
        "message": "Football intelligence tool implementation is deferred to FI-7b2.",
    }


for _schema in FI7B_TOOL_SCHEMAS:
    TOOL_REGISTRY.register(
        ToolSpec(
            name=_schema.name,
            description=_schema.description,
            parameters=_schema.parameters,
            output_schema=_NOT_IMPLEMENTED_OUTPUT_SCHEMA,
        ),
        _not_implemented_handler,
    )
