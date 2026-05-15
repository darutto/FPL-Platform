"""
fpl_grounded_assistant.decision_router
=======================================
Phase M1 (MCP_architecture): Outer decision router.

Branches:
    `@<resource>` -> resource_registry.run_resource(canonical)
    `/<prompt>`   -> NOT WIRED IN M1 (M2 prompt registry takes this).
                     For now, returns outcome="unsupported" with a hint.
    plain text    -> pass-through to existing route() (deterministic).
    rejected      -> outcome="unsupported"

This module DOES NOT call the orchestrator or the classifier — that
wiring belongs to M3. `decide()` returns a structured dict that the
harness consumes. The outer-layer surface is intentionally tiny.
"""
from __future__ import annotations

from typing import Any

from .input_normalizer import (
    normalize,
    ResourceInput,
    PromptInput,
    TextInput,
    RejectedInput,
)
from .intent_aliases import list_resources
from .resource_registry import has_resource, run_resource
from .prompt_registry import (
    get_prompt_spec,
    validate_and_parse,
    build_expansion,
    list_prompts,
    MODE_EXPANSION,
    MODE_DISPATCH,
)


# Outcome constants used by ask_v2()
OUTCOME_OK_RESOURCE         = "ok"
OUTCOME_OK_PROMPT_DISPATCH  = "ok_prompt_dispatch"
OUTCOME_OK_PROMPT_EXPANSION = "ok_prompt_expansion"
OUTCOME_UNSUPPORTED         = "unsupported"
OUTCOME_NEEDS_CLARIFICATION = "needs_clarification"
OUTCOME_FALLTHROUGH         = "fallthrough"  # plain text — caller dispatches to route()


def _suggestions() -> list[str]:
    """Return the six canonical resource names with `@` prefix."""
    return [f"@{name}" for name in list_resources()]


def decide(question: str, bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Classify *question* via the input normalizer, then dispatch.

    Returns a dict with the following keys:

        kind          — "resource" | "prompt" | "text" | "rejected"
        outcome       — "ok" | "unsupported" | "fallthrough"
        resource      — canonical resource key (only when kind == "resource"
                        and the alias resolved)
        resource_rows — ResourceResult.to_dict() output (only when outcome=="ok")
        suggestions   — list of `@resource` strings (only when outcome=="unsupported")
        message       — short human-readable explanation (always present)
        text          — passthrough text (only when kind == "text")
    """
    norm = normalize(question)

    if isinstance(norm, RejectedInput):
        return {
            "kind":        "rejected",
            "outcome":     OUTCOME_UNSUPPORTED,
            "suggestions": _suggestions(),
            "message":     f"Input rejected ({norm.reason}). Try one of the registered resources.",
        }

    if isinstance(norm, ResourceInput):
        if norm.canonical is None or not has_resource(norm.canonical):
            return {
                "kind":         "resource",
                "outcome":      OUTCOME_UNSUPPORTED,
                "resource":     None,
                "raw_alias":    norm.raw_alias,
                "suggestions":  _suggestions(),
                "message": (
                    f"Resource '@{norm.raw_alias}' is not registered. "
                    f"Try one of: {', '.join(_suggestions())}."
                ),
            }
        result = run_resource(norm.canonical, bootstrap)
        return {
            "kind":          "resource",
            "outcome":       OUTCOME_OK_RESOURCE,
            "resource":      norm.canonical,
            "resource_rows": result.to_dict(),
            "message":       result.title,
        }

    if isinstance(norm, PromptInput):
        spec = get_prompt_spec(norm.name)
        if spec is None:
            return {
                "kind":         "prompt",
                "outcome":      OUTCOME_UNSUPPORTED,
                "prompt_name":  norm.name,
                "args_text":    norm.args_text,
                "suggestions":  [f"/{p}" for p in list_prompts()],
                "message": (
                    f"Prompt '/{norm.name}' is not registered. "
                    f"Available prompts: {', '.join('/' + p for p in list_prompts())}."
                ),
            }

        parsed = validate_and_parse(spec, norm.args_text)
        if not parsed["ok"]:
            return {
                "kind":           "prompt",
                "outcome":        OUTCOME_NEEDS_CLARIFICATION,
                "prompt_name":    spec.name,
                "args_text":      norm.args_text,
                "missing_fields": parsed["missing_fields"],
                "errors":         parsed["errors"],
                "message": (
                    f"Prompt '/{spec.name}' needs more information: "
                    f"{'; '.join(parsed['errors']) or 'missing fields'}."
                ),
            }

        if spec.mode == MODE_EXPANSION:
            canonical_text = build_expansion(spec, parsed["args"])
            return {
                "kind":           "prompt",
                "outcome":        OUTCOME_OK_PROMPT_EXPANSION,
                "prompt_name":    spec.name,
                "workflow_intent": spec.workflow_intent,
                "args":           parsed["args"],
                "canonical_text": canonical_text,
                "message":        canonical_text,
            }

        # MODE_DISPATCH — caller (ask_v2) invokes run_tool directly.
        return {
            "kind":           "prompt",
            "outcome":        OUTCOME_OK_PROMPT_DISPATCH,
            "prompt_name":    spec.name,
            "workflow_intent": spec.workflow_intent,
            "args":           parsed["args"],
            "message":        f"dispatch prompt /{spec.name}",
        }

    # TextInput — caller dispatches to existing route()
    assert isinstance(norm, TextInput)
    return {
        "kind":    "text",
        "outcome": OUTCOME_FALLTHROUGH,
        "text":    norm.text,
        "message": "fallthrough to deterministic route()",
    }
