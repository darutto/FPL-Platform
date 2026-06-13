"""
llm_orchestrator_core.tool_schema
==================================
Domain-neutral tool specification + per-provider wire-format serialisation.

Mirrors the ``ToolSchema`` pattern from
``fpl_grounded_assistant.tool_schema_registry`` (Phase Orch-2a) without any
domain tool definitions.  Domain packages define their own ``ToolSpec`` lists
and convert them with ``build_tools()``.

Schema format: JSON Schema draft-07 ``parameters`` objects, compatible with
the OpenAI function-calling API and the Anthropic tool_use API.  Gemini
consumers should route the result of ``build_tools(PROVIDER_GEMINI, ...)``
straight to the SDK (unsupported keys like ``additionalProperties`` are
stripped at call time by ``provider_client``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .provider_client import PROVIDER_GEMINI, PROVIDER_OPENAI


@dataclass(frozen=True)
class ToolSpec:
    """Immutable specification for one callable grounded tool.

    Attributes
    ----------
    name:
        Stable snake_case identifier, unique within the registry that the
        caller's executor dispatches on.
    description:
        Concise description for human and LLM consumers.
    parameters:
        JSON Schema (draft-07) ``object`` describing tool inputs.
    """

    name:        str
    description: str
    parameters:  dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        """Return an OpenAI function-calling tool dict."""
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters":  self.parameters,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Return an Anthropic tool_use tool dict."""
        return {
            "name":         self.name,
            "description":  self.description,
            "input_schema": self.parameters,
        }

    def to_gemini(self) -> dict[str, Any]:
        """Return a Gemini function-declaration dict.

        Intended for use inside a ``{"function_declarations": [...]}`` wrapper.
        """
        return {
            "name":        self.name,
            "description": self.description,
            "parameters":  self.parameters,
        }


def build_tools(provider: str | None, specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Return *specs* in the appropriate wire format for *provider*.

    ``None`` defaults to the Anthropic format (parity with the FPL
    orchestrator's ``_build_tools`` auto-detection contract).
    """
    if provider == PROVIDER_OPENAI:
        return [s.to_openai() for s in specs]
    if provider == PROVIDER_GEMINI:
        return [{"function_declarations": [s.to_gemini() for s in specs]}]
    return [s.to_anthropic() for s in specs]
