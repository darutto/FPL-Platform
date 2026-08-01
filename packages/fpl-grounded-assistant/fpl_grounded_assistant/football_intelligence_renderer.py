"""Deterministic text rendering for Football Intelligence tool results."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


FI_TOOL_NAMES = frozenset(
    {
        "get_expected_minutes",
        "get_tactical_role",
        "get_fixture_context",
        "get_player_intelligence",
    }
)


def _value(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return str(value)


def _lines(output: dict[str, Any], fields: tuple[tuple[str, str], ...]) -> list[str]:
    rendered = [f"Status: {_value(output.get('status'))}"]
    rendered.extend(f"{label}: {_value(output.get(key))}" for label, key in fields)
    reasons = output.get("reason_codes")
    if reasons:
        rendered.append(f"Reasons: {', '.join(str(reason) for reason in reasons)}")
    return rendered


def render_expected_minutes(output: dict[str, Any]) -> str:
    return "\n".join(
        _lines(
            output,
            (
                ("Expected minutes", "expected_minutes"),
                ("Start probability", "start_probability"),
                ("Cameo probability", "cameo_probability"),
                ("Rotation risk", "rotation_risk"),
                ("Minutes risk v2", "minutes_risk_v2"),
                ("Confidence", "confidence"),
            ),
        )
    )


def render_tactical_role(output: dict[str, Any]) -> str:
    return "\n".join(
        _lines(
            output,
            (
                ("Primary role", "primary_role"),
                ("Role distribution", "role_distribution"),
                ("Primary flank", "primary_flank"),
                ("Flank distribution", "flank_distribution"),
                ("Formation depth", "formation_depth"),
                ("Role stability", "role_stability"),
                ("Role change detected", "role_change_detected"),
                ("Out-of-position score", "out_of_position_score"),
                ("Confidence", "confidence"),
            ),
        )
    )


def render_fixture_context(output: dict[str, Any]) -> str:
    return "\n".join(
        _lines(
            output,
            (
                ("Fixture priority", "fixture_priority"),
                ("Congestion index", "congestion_index"),
                ("Weighted trailing congestion 21d", "weighted_trailing_congestion_21d"),
                ("Weighted leading congestion 21d", "weighted_leading_congestion_21d"),
                ("Previous rest days", "previous_rest_days"),
                ("Next rest days", "next_rest_days"),
                ("Competition tier", "target_competition_tier"),
                ("Competition stage", "target_competition_stage"),
                ("League position band", "league_position_band"),
                ("Confidence", "confidence"),
            ),
        )
    )


def render_player_intelligence(output: dict[str, Any]) -> str:
    modules = output.get("modules")
    if not isinstance(modules, dict):
        modules = {}
    reasons = output.get("reason_codes")
    sections: tuple[tuple[str, str, Callable[[dict[str, Any]], str]], ...] = (
        ("Expected minutes", "expected_minutes", render_expected_minutes),
        ("Tactical role", "tactical_role", render_tactical_role),
        ("Fixture context", "fixture_context", render_fixture_context),
    )
    rendered = [f"Status: {_value(output.get('status'))}"]
    for title, module_name, renderer in sections:
        module = modules.get(module_name)
        if isinstance(module, dict):
            module_output = module
        else:
            module_reasons = reasons.get(module_name) if isinstance(reasons, dict) else None
            module_output = {"status": "missing_context"}
            if module_reasons:
                module_output["reason_codes"] = module_reasons
        rendered.extend(("", title, renderer(module_output)))
    return "\n".join(rendered)
