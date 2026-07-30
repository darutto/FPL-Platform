"""FI-7b Football Intelligence tools.

Registration remains import-light.  FI-7b2 runtime dependencies are imported
only after a flag-enabled dispatcher has selected one of these tools.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .tool_schema_registry import FI7B_TOOL_SCHEMAS


_FI_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ok", "partial", "missing_context", "ambiguous", "not_found"],
        },
    },
    "required": ["status"],
}


def _football_intelligence_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch to the lazy, deterministic FI-7b2 runtime adapter."""
    from .football_intelligence_runtime import run_football_intelligence_tool

    name = str(args.pop("_fi_tool_name"))
    return run_football_intelligence_tool(name, args, bootstrap)


def _handler_for(name: str):
    def handler(args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
        return _football_intelligence_handler(
            {**args, "_fi_tool_name": name},
            bootstrap,
        )

    return handler


for _schema in FI7B_TOOL_SCHEMAS:
    TOOL_REGISTRY.register(
        ToolSpec(
            name=_schema.name,
            description=_schema.description,
            parameters=_schema.parameters,
            output_schema=_FI_OUTPUT_SCHEMA,
        ),
        _handler_for(_schema.name),
    )
