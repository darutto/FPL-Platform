"""Bounded FI-7c evidence enrichment for existing recommendation intents.

This module owns eligibility, player extraction, identity preference/fallback,
request-local execution caching, and deterministic evidence aggregation.  It
does not render text or mutate recommendation results.
"""
from __future__ import annotations

import json
from typing import Any


ELIGIBLE_TOOLS: frozenset[str] = frozenset(
    {"get_captain_score", "compare_players", "get_transfer_advice"}
)


def _valid_evidence_item(item: dict[str, Any]) -> bool:
    """Validate the governed wire value without modifying it."""
    try:
        from football_data_contract import (
            EvidenceDirection,
            EvidenceItem,
            SignalBasis,
            SubjectType,
        )

        EvidenceItem(
            code=item["code"],
            label=item["label"],
            subject_type=SubjectType(item["subject_type"]),
            subject_id=item["subject_id"],
            fixture_id=item.get("fixture_id"),
            impact=item["impact"],
            direction=EvidenceDirection(item["direction"]),
            confidence=item["confidence"],
            basis=SignalBasis(item["basis"]),
            summary=item["summary"],
            source_features=tuple(item["source_features"]),
            model_version=item["model_version"],
            calculated_at=item["calculated_at"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _player_values(tool_name: str, raw_output: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if tool_name == "get_captain_score":
        return (raw_output,)
    if tool_name == "compare_players":
        return tuple(
            value for value in (raw_output.get("player_a"), raw_output.get("player_b"))
            if isinstance(value, dict)
        )
    if tool_name == "get_transfer_advice":
        return tuple(
            value for value in (raw_output.get("player_out"), raw_output.get("player_in"))
            if isinstance(value, dict)
        )
    return ()


def _provider_player_id(
    player: dict[str, Any],
    bootstrap: dict[str, Any],
) -> str | None:
    """Prefer a result-owned FPL ID, otherwise use the existing resolver."""
    value = player.get("player_id", player.get("id"))
    if value is not None and str(value).strip():
        return str(value)

    query = player.get("web_name")
    if not isinstance(query, str) or not query.strip():
        return None

    from fpl_tool_contract import tool_resolve_player

    resolved = tool_resolve_player(query, bootstrap)
    if resolved.get("status") != "ok" or resolved.get("player_id") is None:
        return None
    return str(resolved["player_id"])


def _enrich_existing_intent_evidence(
    tool_name: str | None,
    raw_output: dict[str, Any],
    bootstrap: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Return one finalized evidence bundle for an eligible successful result.

    Failures are contained per player.  The existing recommendation remains
    authoritative; zero usable evidence is represented by ``None``.
    """
    if tool_name not in ELIGIBLE_TOOLS or raw_output.get("status") != "ok":
        return None

    actual_bootstrap = (
        bootstrap["bootstrap"]
        if "elements" not in bootstrap and isinstance(bootstrap.get("bootstrap"), dict)
        else bootstrap
    )

    players = _player_values(tool_name, raw_output)
    if not players:
        return None

    # Lazy import keeps the flag-OFF request path free of FI runtime imports.
    from .football_intelligence_runtime import run_football_intelligence_tool

    cache: dict[str, list[dict[str, Any]] | None] = {}
    ordered: list[dict[str, Any]] = []
    for player in players:
        try:
            provider_id = _provider_player_id(player, actual_bootstrap)
            if provider_id is None:
                continue
            if provider_id not in cache:
                # Mark before execution so an exception cannot trigger a retry
                # when the same canonical player appears again in this request.
                cache[provider_id] = None
                result = run_football_intelligence_tool(
                    "get_player_intelligence",
                    {"player": provider_id},
                    actual_bootstrap,
                )
                evidence = result.get("evidence")
                cache[provider_id] = (
                    evidence
                    if isinstance(evidence, list)
                    and all(
                        isinstance(item, dict) and _valid_evidence_item(item)
                        for item in evidence
                    )
                    else None
                )
            bundle = cache[provider_id]
            if bundle:
                ordered.extend(bundle)
        except Exception:  # noqa: BLE001 - enrichment must not replace success
            continue

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ordered:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            selected.append(item)
        if len(selected) == 8:
            break
    return selected or None


def enrich_existing_intent_evidence(
    tool_name: str | None,
    raw_output: dict[str, Any],
    bootstrap: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Fail-closed public boundary for existing-intent enrichment."""
    try:
        return _enrich_existing_intent_evidence(tool_name, raw_output, bootstrap)
    except Exception:  # noqa: BLE001 - never replace a successful recommendation
        return None
