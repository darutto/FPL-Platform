"""
fpl_grounded_assistant.renderer
================================
Converts raw ``fpl_tool_runner.run_tool()`` output into safe, human-readable
answer text.

Rules
-----
* ``"ok"`` results: produce a concise factual sentence from the returned fields.
* ``"ambiguous"`` results: **never leak player-specific data**; always ask the
  user to disambiguate using full name or ID.
* ``"not_found"`` results: acknowledge gracefully; suggest alternatives.
* ``"error"`` results: surface the error code without exposing internals.

Known gaps (to address before true LLM integration)
----------------------------------------------------
- No multi-sentence narrative; currently one-line per result
- No conditional phrasing for injury/suspension status beyond label lookup
- No captain-score or differential commentary (awaits Phase 2 scoring layer)
- Ownership rendering is basic ("X% ownership") — no "popular pick" framing
"""
from __future__ import annotations

from typing import Any

# Map tool status → label for use in answer text
_STATUS_DISPLAY = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
}

# ---------------------------------------------------------------------------
# Per-tool renderers
# ---------------------------------------------------------------------------

def _render_resolve_player(output: dict[str, Any]) -> str:
    status = output.get("status")
    if status == "ok":
        name       = output.get("name", output.get("web_name", "Unknown"))
        web_name   = output.get("web_name", "")
        team       = output.get("team", "")
        team_short = output.get("team_short", "")
        position   = output.get("position", "")
        status_lbl = output.get("status_label", "")
        via        = output.get("resolved_via", "")

        display = f"{web_name} ({name})" if name != web_name else web_name
        return (
            f"{display} plays for {team} ({team_short}) "
            f"as a {position}. Status: {status_lbl}."
            + (f" [Resolved via: {via}]" if via else "")
        )

    if status == "ambiguous":
        query = output.get("query", "that name")
        return (
            f"Multiple players share the name '{query}'. "
            f"Please use a full name or player ID to disambiguate "
            f"(e.g. 'Who is Adam Johnson?' or 'Who is player 6?')."
        )

    if status == "not_found":
        query = output.get("query", "that player")
        return (
            f"No player found matching '{query}'. "
            f"Check the spelling or try a full name / player ID."
        )

    # error or unexpected
    code    = output.get("code", "unknown")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


def _render_get_player_summary(output: dict[str, Any]) -> str:
    status = output.get("status")
    if status == "ok":
        name       = output.get("name", output.get("web_name", "Unknown"))
        web_name   = output.get("web_name", "")
        team       = output.get("team", "")
        team_short = output.get("team_short", "")
        position   = output.get("position", "")
        status_lbl = output.get("status_label", "")
        cost_m     = output.get("cost_m", "?")
        ownership  = output.get("selected_by_percent", "?")

        display = f"{web_name} ({name})" if name != web_name else web_name
        return (
            f"{display} | {team} ({team_short}) | {position} | "
            f"£{cost_m}m | {ownership}% ownership | Status: {status_lbl}."
        )

    if status == "ambiguous":
        query = output.get("query", "that name")
        return (
            f"Multiple players share the name '{query}'. "
            f"Please use a full name or player ID to disambiguate."
        )

    if status == "not_found":
        query = output.get("query", "that player")
        return (
            f"No player found matching '{query}'. "
            f"Check the spelling or try a full name / player ID."
        )

    code    = output.get("code", "unknown")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


def _render_get_current_gameweek(output: dict[str, Any]) -> str:
    status = output.get("status")
    if status == "ok":
        gw = output.get("gameweek", "?")
        return f"The current Premier League Fantasy gameweek is GW{gw}."

    if status == "not_found":
        return (
            "The current gameweek could not be determined from the available data. "
            "The season may be on a break or between gameweeks."
        )

    code    = output.get("code", "unknown")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Dispatch table and public API
# ---------------------------------------------------------------------------

_RENDERERS = {
    "resolve_player":      _render_resolve_player,
    "get_player_summary":  _render_get_player_summary,
    "get_current_gameweek": _render_get_current_gameweek,
}


def render(tool_name: str, raw_output: dict[str, Any]) -> str:
    """
    Convert *raw_output* from ``run_tool(tool_name, ...)`` into a safe,
    human-readable answer string.

    Parameters
    ----------
    tool_name:
        The name of the tool that produced *raw_output* (used to select
        the appropriate renderer).
    raw_output:
        The dict returned by ``fpl_tool_runner.run_tool()``.

    Returns
    -------
    str
        A natural-language sentence suitable for display to a user.
    """
    renderer = _RENDERERS.get(tool_name)
    if renderer is None:
        code    = raw_output.get("code", "unknown_tool")
        message = raw_output.get("message", f"No renderer for tool '{tool_name}'.")
        return f"Error ({code}): {message}"

    return renderer(raw_output)


# ---------------------------------------------------------------------------
# Phase 2i: Tier and set-piece display helpers
# ---------------------------------------------------------------------------

_TIER_LABEL: dict[str, str] = {
    "safe":               "Safe",
    "balanced":           "Balanced",
    "differential":       "Differential",
    "low_confidence":     "Low-confidence",
}

_TIER_SHORT: dict[str, str] = {
    "safe":               "safe",
    "balanced":           "bal",
    "differential":       "diff",
    "low_confidence":     "low",
}

_SET_PIECE_LABEL: dict[str, str] = {
    "penalty_taker_1":    "penalty taker",
    "penalty_taker_2":    "2nd penalty taker",
    "freekick_taker_1":   "free-kick taker",
    "freekick_taker_2":   "2nd free-kick taker",
}

_SET_PIECE_SHORT: dict[str, str] = {
    "penalty_taker_1":    "pen",
    "penalty_taker_2":    "pen2",
    "freekick_taker_1":   "fk",
    "freekick_taker_2":   "fk2",
}


def _tier_display(tier: str) -> str:
    """Return full tier label for display."""
    return _TIER_LABEL.get(tier, tier)


def _tier_short(tier: str) -> str:
    """Return short tier label for bracket display."""
    return _TIER_SHORT.get(tier, tier)


def _set_piece_clause(role_signals: dict[str, Any]) -> str:
    """Build a descriptive clause from role_signals set-piece notes.

    Returns empty string if no set-piece notes are present.

    Examples:
        ""                            # no set-piece roles
        "penalty taker"               # single role
        "penalty taker, free-kick"    # multiple roles
    """
    notes = role_signals.get("set_piece_notes", [])
    if not notes:
        return ""

    labels = [_SET_PIECE_LABEL.get(note, note) for note in notes]
    return ", ".join(labels)


def _set_piece_suffix(role_signals: dict[str, Any]) -> str:
    """Build a brief suffix from role_signals set-piece notes.

    Returns empty string if no set-piece notes are present.

    Examples:
        ""        # no set-piece roles
        "· pen"   # penalty taker
        "· pen, fk"  # multiple roles
    """
    clause = _set_piece_clause(role_signals)
    if not clause:
        return ""
    return f"· {clause}"