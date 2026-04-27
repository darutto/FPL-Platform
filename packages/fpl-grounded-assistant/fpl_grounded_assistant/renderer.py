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
# Captain score renderer  (Phase 5m)
# ---------------------------------------------------------------------------

def _render_get_captain_score(output: dict[str, Any]) -> str:
    """Render a get_captain_score raw_output dict into a human-readable string."""
    from .explainer import explain_captain  # local import — avoids circular

    status = output.get("status")
    if status == "ok":
        web_name   = output.get("web_name", "Unknown")
        team_short = output.get("team_short", "")
        score      = output.get("captain_score", 0)
        tier       = output.get("tier", "")

        tier_label = _tier_display(tier)  # e.g. "Safe", "Upside", "Differential"

        reasons = explain_captain(output)
        reasons_clause = (" " + "; ".join(reasons) + ".") if reasons else ""

        return f"{web_name} ({team_short}) — {tier_label} [{score}].{reasons_clause}"

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


# ---------------------------------------------------------------------------
# Rank captain candidates renderer  (Phase 5m)
# ---------------------------------------------------------------------------

def _render_rank_captain_candidates(output: dict[str, Any]) -> str:
    """Render a rank_captain_candidates raw_output dict into a human-readable string."""
    from .explainer import explain_captain_compact  # local import

    status = output.get("status")
    if status == "ok":
        candidates = output.get("ranked_candidates", [])
        ok_entries = [c for c in candidates if c.get("status") == "ok"]

        if not ok_entries:
            return "No captain candidates could be scored."

        lines = []
        for c in ok_entries:
            rank      = c.get("rank", "?")
            name      = c.get("web_name", "?")
            team_s    = c.get("team_short", "")
            score     = c.get("captain_score", 0)
            tier      = c.get("tier", "")
            role_sigs = c.get("role_signals", {})

            tier_s   = _tier_short(tier)             # e.g. "safe", "up", "diff"
            sp_sfx   = _set_piece_suffix(role_sigs)  # e.g. "· pen" or ""

            compact_reasons = explain_captain_compact(c)
            reason_str = "; ".join(compact_reasons) if compact_reasons else ""

            line = f"{rank}. {name} ({team_s}) [{tier_s}] {score}{(' ' + sp_sfx) if sp_sfx else ''}"
            if reason_str:
                line += f" — {reason_str}"
            lines.append(line)

        return "\n".join(lines)

    code    = output.get("code", "error")
    message = output.get("message", "Could not rank captain candidates.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Comparison renderer  (Phase 5b)
# ---------------------------------------------------------------------------

def _render_compare_players(output: dict[str, Any]) -> str:
    """Render a compare_players raw_output dict into a human-readable string."""
    status = output.get("status")
    if status == "ok":
        rec = output.get("recommendation", "")
        return rec if rec else "Comparison completed."
    if status in ("not_found", "ambiguous"):
        ep  = output.get("error_player", "")
        msg = output.get("message", f"Could not resolve player '{ep}'.")
        return msg
    code    = output.get("code", "error")
    message = output.get("message", "An unexpected comparison error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Transfer advice renderer  (Phase 6a)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chip advice renderer  (Phase 6b)
# ---------------------------------------------------------------------------

def _render_get_chip_advice(output: dict[str, Any]) -> str:
    """Render a get_chip_advice raw_output dict into a human-readable string."""
    status = output.get("status")
    if status == "ok":
        return output.get("advice_text", "Chip advice computed.")
    if status == "not_found":
        chip = output.get("chip", "unknown")
        return f"'{chip}' is not a recognised FPL chip name."
    code    = output.get("code", "error")
    message = output.get("message", "An unexpected chip advice error occurred.")
    return f"Error ({code}): {message}"


def _render_get_transfer_advice(output: dict[str, Any]) -> str:
    """Render a get_transfer_advice raw_output dict into a human-readable string."""
    status = output.get("status")
    if status == "ok":
        rec_text = output.get("recommendation_text", "")
        return rec_text if rec_text else "Transfer advice computed."
    if status in ("not_found", "ambiguous"):
        ep  = output.get("error_player", "")
        msg = output.get("message", f"Could not resolve player '{ep}'.")
        return msg
    code    = output.get("code", "error")
    message = output.get("message", "An unexpected transfer advice error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Player fixture run renderer  (Phase 7h)
# ---------------------------------------------------------------------------

def _render_get_player_fixture_run(output: dict[str, Any]) -> str:
    """Render a get_player_fixture_run raw_output dict into a human-readable string."""
    status = output.get("status")
    if status == "ok":
        web_name = output.get("web_name", "?")
        team     = output.get("team_short", "")
        position = output.get("position", "")
        horizon  = output.get("horizon", 0)
        fixtures = output.get("fixtures", [])
        gw_from  = output.get("current_gameweek")

        header_parts = [web_name]
        if team or position:
            inner = ", ".join(filter(None, [team, position]))
            header_parts.append(f"({inner})")
        gw_label = f" from GW{gw_from}" if gw_from is not None else ""
        plural   = "s" if horizon != 1 else ""
        header   = " ".join(header_parts) + f" – next {horizon} fixture{plural}{gw_label}:"

        parts: list[str] = []
        for fx in fixtures:
            venue = "H" if fx.get("is_home") else "A"
            parts.append(
                f"GW{fx['gameweek']} {fx['opponent_short']} ({venue}) FDR {fx['difficulty']}"
            )
        return header + " " + " · ".join(parts) if parts else header

    if status in ("not_found", "ambiguous"):
        return output.get("message", "Player not found.")

    if status == "missing_context":
        return output.get("message", "Fixture schedule not available.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected fixture run error occurred.")
    return f"Error ({code}): {message}"


def _render_get_differential_picks(output: dict[str, Any]) -> str:
    """Render differential picks output.  Phase 7g."""
    status = output.get("status")
    if status == "ok":
        picks    = output.get("picks", [])
        threshold = float(output.get("ownership_threshold", 15.0))
        if not picks:
            return f"No differential picks found (ownership < {threshold:.0f}%)."
        lines = [f"Top differentials (ownership < {threshold:.0f}%):"]
        for p in picks:
            cost_m = p["now_cost"] / 10.0
            # Phase 8a1: display position_score (position-aware heuristic)
            display_score = p.get("position_score", p["captain_score"])
            lines.append(
                f"  {p['rank']}. {p['web_name']} ({p['team_short']}, "
                f"{p['position']}) — score {display_score:.1f}, "
                f"{p['ownership']:.1f}% owned, £{cost_m:.1f}m"
            )
        return "\n".join(lines)

    if status == "empty":
        return output.get("message", "No differential picks found.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected differential picks error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Dispatch table and public API
# ---------------------------------------------------------------------------

_RENDERERS = {
    "resolve_player":            _render_resolve_player,
    "get_player_summary":        _render_get_player_summary,
    "get_current_gameweek":      _render_get_current_gameweek,
    "get_captain_score":         _render_get_captain_score,          # Phase 5m
    "rank_captain_candidates":   _render_rank_captain_candidates,    # Phase 5m
    "compare_players":           _render_compare_players,            # Phase 5b
    "get_transfer_advice":       _render_get_transfer_advice,        # Phase 6a
    "get_chip_advice":           _render_get_chip_advice,            # Phase 6b
    "get_player_fixture_run":    _render_get_player_fixture_run,     # Phase 7h
    "get_differential_picks":    _render_get_differential_picks,     # Phase 7g
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
    "upside":             "Upside",          # Phase 5m: was "balanced"
    "differential":       "Differential",
    "avoid":              "Avoid",            # Phase 5m: new
    "low_confidence":     "Low-confidence",
}

_TIER_SHORT: dict[str, str] = {
    "safe":               "safe",
    "upside":             "up",              # Phase 5m: was "bal"
    "differential":       "diff",
    "avoid":              "avoid",           # Phase 5m: new
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