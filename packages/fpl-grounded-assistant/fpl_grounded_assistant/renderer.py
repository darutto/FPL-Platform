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
        base = (
            f"{display} | {team} ({team_short}) | {position} | "
            f"£{cost_m}m | {ownership}% ownership | Status: {status_lbl}."
        )
        # Phase 2.6d Story 2.2: append season totals when available
        extras: list[str] = []
        total_pts = output.get("total_points")
        form_val  = output.get("form")
        minutes   = output.get("minutes")
        if total_pts is not None:
            extras.append(f"Total pts: {total_pts}")
        if form_val is not None:
            extras.append(f"Form: {form_val}")
        if minutes is not None:
            extras.append(f"Mins: {minutes}")
        if extras:
            return base + " " + " | ".join(extras) + "."
        return base

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
        result = header + " " + " · ".join(parts) if parts else header

        # Phase 2.6f: append team FDR context line when available
        ctx = output.get("team_fdr_context")
        if ctx and parts:
            avg   = ctx.get("avg_fdr", 0.0)
            label = ctx.get("difficulty_label", "")
            g_from = ctx.get("gw_from")
            g_to   = ctx.get("gw_to")
            gw_range = f"GW{g_from}-GW{g_to}" if g_from and g_to else ""
            gw_clause = f" over {gw_range}" if gw_range else ""
            article   = "an" if label[0] in "aeiou" else "a"
            result += f" | {team} have {article} {label} run{gw_clause}, avg FDR {avg:.1f}."

        return result

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
# Player form renderer  (Phase 2.6d Story 2.1)
# ---------------------------------------------------------------------------

def _render_get_player_form(output: dict[str, Any]) -> str:
    """Render get_player_form output."""
    status = output.get("status")
    if status == "ok":
        web_name  = output.get("web_name", "?")
        team      = output.get("team_short", "")
        pos       = output.get("position", "")
        n         = output.get("n_games", 0)
        history   = output.get("history", [])

        header = f"{web_name} ({team}, {pos}) — last {n} gameweek(s):"
        if not history:
            return header + " No history available."

        lines = [header]
        for entry in history:
            gw    = entry.get("gameweek", "?")
            mins  = entry.get("minutes", 0)
            g     = entry.get("goals_scored", 0)
            a     = entry.get("assists", 0)
            bonus = entry.get("bonus", 0)
            pts   = entry.get("total_points", 0)
            lines.append(
                f"  GW{gw}: {pts}pts  {g}g {a}a {bonus}bps  {mins}mins"
            )
        return "\n".join(lines)

    if status in ("not_found", "ambiguous"):
        query = output.get("query", "that player")
        return f"No player found matching '{query}'."

    if status == "missing_context":
        return output.get("message", "Player match history unavailable.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected player form error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Injury list renderer  (Phase 2.6d Story 2.3)
# ---------------------------------------------------------------------------

def _render_get_injury_list(output: dict[str, Any]) -> str:
    """Render get_injury_list output."""
    status = output.get("status")
    if status == "ok":
        injured  = output.get("injured", [])
        doubtful = output.get("doubtful", [])
        other    = output.get("other", [])
        total    = output.get("total", 0)

        if total == 0:
            return "No injury concerns in the current bootstrap."

        parts: list[str] = []
        if injured:
            names = ", ".join(f"{p['web_name']} ({p['team_short']}, {p['position']})" for p in injured)
            parts.append(f"Injured: {names}")
        if doubtful:
            doubt_strs: list[str] = []
            for p in doubtful:
                chance = p.get("chance_of_playing")
                s = f"{p['web_name']} ({p['team_short']}, {p['position']})"
                if chance is not None:
                    s += f" {chance}%"
                doubt_strs.append(s)
            parts.append(f"Doubtful: {', '.join(doubt_strs)}")
        if other:
            names = ", ".join(f"{p['web_name']} ({p['team_short']})" for p in other)
            parts.append(f"Suspended/unavailable: {names}")

        return " | ".join(parts) + "."

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected injury list error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Price changes renderer  (Phase 2.6d Story 2.4)
# ---------------------------------------------------------------------------

def _render_get_price_changes(output: dict[str, Any]) -> str:
    """Render get_price_changes output."""
    status = output.get("status")
    if status == "ok":
        risers  = output.get("risers", [])
        fallers = output.get("fallers", [])

        if not risers and not fallers:
            return "No price changes in the current gameweek."

        parts: list[str] = []
        if risers:
            riser_strs = [
                f"{p['web_name']} ({p['team_short']}, {p['position']}) +£{abs(p['cost_change_event'] / 10.0):.1f}m"
                for p in risers
            ]
            parts.append("Risers: " + ", ".join(riser_strs))
        if fallers:
            faller_strs = [
                f"{p['web_name']} ({p['team_short']}, {p['position']}) -£{abs(p['cost_change_event'] / 10.0):.1f}m"
                for p in fallers
            ]
            parts.append("Fallers: " + ", ".join(faller_strs))

        return " | ".join(parts) + "."

    if status == "empty":
        return output.get("message", "No price-change data available.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected price changes error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Team fixture calendar renderer  (Phase 2.6e)
# ---------------------------------------------------------------------------

def _render_get_team_fixture_calendar(output: dict[str, Any]) -> str:
    """Render get_team_fixture_calendar output."""
    status = output.get("status")
    if status == "ok":
        mode    = output.get("mode", "easiest")
        horizon = output.get("horizon", 5)
        gw      = output.get("current_gameweek")
        teams   = output.get("teams", [])

        mode_label = "easiest" if mode == "easiest" else "hardest"
        gw_label   = f" from GW{gw}" if gw is not None else ""
        header     = (
            f"Teams ranked by {mode_label} fixtures "
            f"(next {horizon} GWs{gw_label}):"
        )

        if not teams:
            return header + " No data available."

        lines = [header]
        for t in teams:
            rank  = t.get("rank", "?")
            short = t.get("team_short", "?")
            name  = t.get("team_name", "?")
            avg   = t.get("avg_fdr", 0.0)
            count = t.get("fixture_count", 0)

            # DGW/BGW label  (Phase 2.6e.2)
            label_parts: list[str] = []
            dgw_gws = t.get("dgw_gameweeks", [])
            bgw_gws = t.get("bgw_gameweeks", [])
            if dgw_gws:
                label_parts.append("DGW:" + ",".join(f"GW{g}" for g in dgw_gws))
            if bgw_gws:
                label_parts.append("BGW:" + ",".join(f"GW{g}" for g in bgw_gws))
            label_str = (" [" + " ".join(label_parts) + "]") if label_parts else ""

            # Compact per-fixture summary
            fxs   = t.get("fixtures", [])
            fx_str = " ".join(
                f"GW{f['gameweek']}({f['opponent_short']}{'H' if f['is_home'] else 'A'}"
                f"/{f['difficulty']})"
                for f in fxs
            )
            lines.append(
                f"  {rank}. {short} ({name}) avg {avg:.1f} "
                f"[{count} fix]{label_str} — {fx_str}"
            )
        return "\n".join(lines)

    if status == "missing_context":
        return output.get("message", "Fixture schedule data not available.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Position fixture run renderer  (Phase 2.6e.4)
# ---------------------------------------------------------------------------

def _render_get_transfer_suggestion(output: dict[str, Any]) -> str:
    """Render get_transfer_suggestion output.  Phase 2.6h."""
    status = output.get("status")

    if status == "ok":
        pos_label  = output.get("position_label", output.get("position", "?"))
        team_short = output.get("team_short")
        max_price  = output.get("max_price")
        horizon    = output.get("horizon", 5)
        picks      = output.get("picks", [])

        # Phase 2.6i: prefix with club name when a team filter was applied
        team_prefix = f"{team_short} " if team_short else ""

        price_clause = ""
        if max_price is not None:
            try:
                price_clause = f" under £{float(max_price):.1f}m"
            except (TypeError, ValueError):
                pass
        header = (
            f"Top transfer targets — {team_prefix}{pos_label}{price_clause} "
            f"(next {horizon} GWs):"
        )
        if not picks:
            return header + " None found."

        lines = [header]
        for p in picks:
            rank   = p.get("rank", "?")
            name   = p.get("web_name", "?")
            team   = p.get("team_short", "?")
            pos    = p.get("position", "?")
            cost_m = p.get("now_cost_m", 0.0)
            form   = p.get("form", 0.0)
            avg    = p.get("avg_fdr", 0.0)
            label  = p.get("difficulty_label", "")
            own    = p.get("ownership", 0.0)
            lines.append(
                f"  {rank}. {name} ({team}, {pos}) "
                f"£{cost_m:.1f}m | form {form:.1f} | avg FDR {avg:.1f} ({label}) | {own:.1f}% owned"
            )
        return "\n".join(lines)

    if status == "empty":
        return output.get("message", "No transfer targets found matching the criteria.")

    if status == "not_found":
        team_query = output.get("team_query", "that team")
        return (
            f"No club matching '{team_query}' was found in the current fixture data. "
            "Check the spelling or try a common abbreviation (e.g. 'Liverpool', 'LIV', 'Spurs')."
        )

    if status == "missing_context":
        return output.get("message", "Player data not available.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


def _render_get_position_fixture_run(output: dict[str, Any]) -> str:
    """Render get_position_fixture_run output."""
    status = output.get("status")
    if status == "ok":
        pos_label = output.get("position_label", output.get("position", "?"))
        mode      = output.get("mode", "easiest")
        horizon   = output.get("horizon", 5)
        gw        = output.get("current_gameweek")
        teams     = output.get("teams", [])
        mode_word = "easiest" if mode == "easiest" else "hardest"
        gw_label  = f" from GW{gw}" if gw is not None else ""
        header    = (
            f"Teams ranked by {mode_word} fixtures for {pos_label} "
            f"(next {horizon} GWs{gw_label}):"
        )
        if not teams:
            return header + " No data available."
        lines = [header]
        for t in teams:
            rank  = t.get("rank", "?")
            short = t.get("team_short", "?")
            name  = t.get("team_name", "?")
            avg   = t.get("avg_fdr", 0.0)
            count = t.get("fixture_count", 0)
            label_parts: list[str] = []
            dgw_gws = t.get("dgw_gameweeks", [])
            bgw_gws = t.get("bgw_gameweeks", [])
            if dgw_gws:
                label_parts.append("DGW:" + ",".join(f"GW{g}" for g in dgw_gws))
            if bgw_gws:
                label_parts.append("BGW:" + ",".join(f"GW{g}" for g in bgw_gws))
            label_str = (" [" + " ".join(label_parts) + "]") if label_parts else ""
            fxs    = t.get("fixtures", [])
            fx_str = " ".join(
                f"GW{f['gameweek']}({f['opponent_short']}{'H' if f['is_home'] else 'A'}"
                f"/{f['difficulty']})"
                for f in fxs
            )
            lines.append(
                f"  {rank}. {short} ({name}) avg {avg:.1f} "
                f"[{count} fix]{label_str} — {fx_str}"
            )
        return "\n".join(lines)
    if status == "invalid_position":
        return output.get("message", "Unknown position.")
    if status == "missing_context":
        return output.get("message", "Fixture schedule data not available.")
    code    = output.get("code", "error")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Single-team fixture schedule renderer  (Phase 2.6e.3)
# ---------------------------------------------------------------------------

def _render_get_team_schedule(output: dict[str, Any]) -> str:
    """Render get_team_schedule output."""
    status = output.get("status")
    if status == "ok":
        short   = output.get("team_short", "?")
        name    = output.get("team_name", "?")
        horizon = output.get("horizon", 5)
        gw      = output.get("current_gameweek")
        count   = output.get("fixture_count", 0)
        avg     = output.get("avg_fdr", 0.0)

        gw_label = f" from GW{gw}" if gw is not None else ""
        header   = f"{name} ({short}) fixtures (next {horizon} GWs{gw_label}):"

        label_parts: list[str] = []
        dgw_gws = output.get("dgw_gameweeks", [])
        bgw_gws = output.get("bgw_gameweeks", [])
        if dgw_gws:
            label_parts.append("DGW:" + ",".join(f"GW{g}" for g in dgw_gws))
        if bgw_gws:
            label_parts.append("BGW:" + ",".join(f"GW{g}" for g in bgw_gws))
        label_str = (" [" + " ".join(label_parts) + "]") if label_parts else ""

        fxs = output.get("fixtures", [])
        if not fxs:
            return header + " No upcoming fixtures."

        fx_str = " ".join(
            f"GW{f['gameweek']}({f['opponent_short']}{'H' if f['is_home'] else 'A'}"
            f"/{f['difficulty']})"
            for f in fxs
        )
        return (
            f"{header}\n"
            f"  avg FDR {avg:.1f} [{count} fixtures]{label_str}\n"
            f"  {fx_str}"
        )

    if status == "not_found":
        return output.get("message", "Team not found.")

    if status == "missing_context":
        return output.get("message", "Fixture schedule data not available.")

    code    = output.get("code", "error")
    message = output.get("message", "An unexpected error occurred.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# P2 atomic tool renderers  (P2.8 Gap B fix)
# ---------------------------------------------------------------------------

def _render_find_players(output: dict[str, Any]) -> str:
    """Render find_players raw_output.  P2.1."""
    status = output.get("status")
    if status == "ok":
        matches = output.get("matches", [])
        query   = output.get("query", "")
        if not matches:
            return f"No players found matching '{query}'."

        header = f"Jugadores encontrados para '{query}':"
        lines = [header]
        for m in matches:
            name      = m.get("web_name", "?")
            team      = m.get("team_short", "?")
            pos       = m.get("position", "?")
            cost      = m.get("now_cost", 0) / 10.0
            form      = m.get("form", 0.0)
            pts       = m.get("total_points", 0)
            mins      = m.get("minutes_played_season", 0)
            lines.append(
                f"  - {name} ({team}, {pos}) — £{cost:.1f}m | "
                f"Forma {form} | {pts}pts | Mins {mins}"
            )
        return "\n".join(lines)

    if status == "not_found":
        query = output.get("query", "")
        return f"No se encontró ningún jugador que coincida con '{query}'."

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_player_snapshot(output: dict[str, Any]) -> str:
    """Render get_player_snapshot raw_output.  P2.2."""
    status = output.get("status")
    if status == "ok":
        p = output.get("player", {})
        name      = p.get("web_name", "?")
        team      = p.get("team_short", "?")
        pos       = p.get("position", "?")
        cost      = p.get("now_cost", 0) / 10.0
        own       = p.get("selected_by_percent", 0.0)
        status_lbl = p.get("status", "?")
        form      = p.get("form", 0.0)
        pts       = p.get("total_points", 0)
        ppg       = p.get("points_per_game", 0.0)
        xg        = p.get("expected_goals", 0.0)
        xa        = p.get("expected_assists", 0.0)
        xgi       = p.get("expected_goal_involvements", 0.0)
        ict       = p.get("ict_index", 0.0)
        mins      = p.get("minutes_played_season", 0)
        news      = p.get("news", "") or ""
        chance    = p.get("chance_of_playing_this_round")

        lines = [
            f"**{name}** ({team}, {pos})",
            f"  Precio: £{cost:.1f}m | Propiedad: {own:.1f}% | Estado: {status_lbl}",
            f"  Pts totales: {pts} | PPG: {ppg:.1f} | Forma: {form}",
            f"  xG: {xg:.2f} | xA: {xa:.2f} | xGI: {xgi:.2f} | ICT: {ict:.1f}",
            f"  Minutos: {mins}",
        ]
        if chance is not None:
            lines.append(f"  Prob. de jugar: {chance}%")
        if news:
            lines.append(f"  Noticias: {news}")
        return "\n".join(lines)

    if status == "ambiguous":
        query      = output.get("query", "")
        candidates = output.get("candidates", [])
        lines = [f"Múltiples jugadores coinciden con '{query}' — por favor especifica:"]
        for c in candidates:
            name  = c.get("web_name", "?")
            team  = c.get("team_short", "?")
            pos   = c.get("position", "?")
            rank  = c.get("match_rank", "?")
            lines.append(f"  - {name} ({team}, {pos}) [rank {rank}]")
        return "\n".join(lines)

    if status == "not_found":
        return output.get("message", "Jugador no encontrado.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_player_history(output: dict[str, Any]) -> str:
    """Render get_player_history raw_output.  P2.3."""
    status = output.get("status")
    if status == "ok":
        p       = output.get("player", {})
        name    = p.get("web_name", "?")
        team    = p.get("team_short", "?")
        pos     = p.get("position", "?")
        n       = output.get("last_n_gws", 0)
        history = output.get("history", [])
        summary = output.get("summary", {})

        header = f"{name} ({team}, {pos}) — últimas {n} jornada(s):"
        if not history:
            return header + " Sin historial disponible."

        lines = [header]
        # Table header
        lines.append("  GW  | Rival | Mins | Pts | G | A  | xG   | xA")
        lines.append("  ----|-------|------|-----|---|----|----- |-----")
        for h in history:
            gw   = h.get("round", "?")
            opp  = h.get("opponent_team_short", "?")
            mins = h.get("minutes", 0)
            pts  = h.get("total_points", 0)
            g    = h.get("goals_scored", 0)
            a    = h.get("assists", 0)
            xg   = h.get("expected_goals", 0.0)
            xa   = h.get("expected_assists", 0.0)
            lines.append(
                f"  {str(gw).rjust(3)} | {opp.ljust(5)} | {str(mins).rjust(4)} | "
                f"{str(pts).rjust(3)} | {g} | {str(a).rjust(2)} | "
                f"{xg:.2f} | {xa:.2f}"
            )
        # Summary line
        tot_pts = summary.get("total_points", 0)
        avg_frm = summary.get("avg_form", 0.0)
        tot_xgi = summary.get("total_xgi", 0.0)
        lines.append(
            f"\n  Resumen: {tot_pts}pts totales | Forma media: {avg_frm:.1f} | xGI total: {tot_xgi:.2f}"
        )
        return "\n".join(lines)

    if status == "ambiguous":
        return output.get("message", "Múltiples jugadores coinciden — especifica el nombre.")

    if status == "not_found":
        return output.get("message", "Jugador no encontrado.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_fixtures_for_gw(output: dict[str, Any]) -> str:
    """Render get_fixtures_for_gw raw_output.  P2.4."""
    status = output.get("status")
    if status == "ok":
        gw        = output.get("gw", "?")
        is_blank  = output.get("is_blank", False)
        is_double = output.get("is_double", False)
        fixtures  = output.get("fixtures", [])
        summary   = output.get("summary", {})

        alerts: list[str] = []
        if is_blank:
            alerts.append("⚠ Jornada en blanco (algún equipo sin partido)")
        if is_double:
            dgw_teams = summary.get("double_gw_teams", [])
            alerts.append(
                "⚠ Jornada doble — equipos con 2 partidos: " + ", ".join(dgw_teams)
            )

        lines = [f"Partidos GW{gw}:"]
        if alerts:
            lines += ["  " + a for a in alerts]

        for fx in fixtures:
            home   = fx.get("home_team_short", "?")
            away   = fx.get("away_team_short", "?")
            ko     = fx.get("kickoff_time") or "TBC"
            h_fdr  = fx.get("home_fdr", "?")
            a_fdr  = fx.get("away_fdr", "?")
            lines.append(
                f"  GW{gw}: {home} vs {away} (kickoff: {ko}) | "
                f"FDR local {h_fdr}, FDR visit {a_fdr}"
            )

        if not fixtures:
            lines.append("  Sin partidos para esta jornada.")

        bgw = summary.get("blank_gw_teams", [])
        if bgw:
            lines.append(f"  Equipos sin partido (BGW): {', '.join(bgw)}")

        return "\n".join(lines)

    if status == "invalid_argument":
        return output.get("message", "Número de jornada fuera de rango (1-38).")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_gameweek_context(output: dict[str, Any]) -> str:
    """Render get_gameweek_context raw_output.  P2.5."""
    status = output.get("status")
    if status == "ok":
        curr_gw    = output.get("current_gw", "?")
        curr_st    = output.get("current_gw_status", "?")
        next_gw    = output.get("next_gw")
        next_dl    = output.get("next_gw_deadline")
        is_over    = output.get("is_season_over", False)
        blank_al   = output.get("blank_gw_alerts", [])
        double_al  = output.get("double_gw_alerts", [])

        if is_over:
            return "La temporada ha finalizado."

        next_str = "N/A"
        if next_gw is not None:
            next_str = f"GW{next_gw}"
            if next_dl:
                next_str += f" (deadline: {next_dl})"

        lines = [
            f"Jornada actual: GW{curr_gw} ({curr_st}). Próxima jornada: {next_str}."
        ]

        for alert in blank_al:
            gw    = alert.get("gw", "?")
            teams = ", ".join(alert.get("blank_teams", []))
            lines.append(f"  • BGW{gw}: equipos sin partido — {teams}")

        for alert in double_al:
            gw    = alert.get("gw", "?")
            teams = ", ".join(alert.get("double_teams", []))
            lines.append(f"  • DGW{gw}: equipos con doble partido — {teams}")

        return "\n".join(lines)

    code    = output.get("code", "error")
    message = output.get("message", "Error obteniendo contexto de jornada.")
    return f"Error ({code}): {message}"


def _render_get_team_snapshot(output: dict[str, Any]) -> str:
    """Render get_team_snapshot raw_output.  P2.6."""
    status = output.get("status")
    if status == "ok":
        team      = output.get("team", {})
        short     = team.get("short_name", "?")
        name      = team.get("name", "?")
        fixtures  = output.get("upcoming_fixtures", [])
        players   = output.get("top_players", [])
        summary   = output.get("summary", {})

        avg_fdr   = summary.get("avg_fdr_next_5", 0.0)
        easy_run  = summary.get("is_easy_run", False)
        top_sc    = summary.get("top_scorer_web_name", "?")
        top_frm   = summary.get("top_form_web_name", "?")

        run_label = "fácil" if easy_run else ("dura" if summary.get("is_hard_run") else "media")

        lines = [f"**{name} ({short})** — racha {run_label} (FDR medio: {avg_fdr:.1f})"]

        # Upcoming fixtures table
        if fixtures:
            lines.append("  Próximos partidos:")
            for fx in fixtures:
                gw       = fx.get("gw", "?")
                opp      = fx.get("opponent_short", "?")
                is_home  = fx.get("is_home", True)
                fdr      = fx.get("fdr", "?")
                venue    = "L" if is_home else "V"
                lines.append(f"    GW{gw}: {opp} ({venue}) FDR {fdr}")

        # Top players table
        if players:
            lines.append("  Mejores jugadores (por puntos):")
            for p in players:
                pname = p.get("web_name", "?")
                pos   = p.get("position", "?")
                pts   = p.get("total_points", 0)
                form  = p.get("form", 0.0)
                cost  = p.get("now_cost", 0) / 10.0
                lines.append(f"    {pname} ({pos}) — {pts}pts | forma {form} | £{cost:.1f}m")

        lines.append(
            f"  Máximo goleador: {top_sc} | Mejor forma: {top_frm}"
        )
        return "\n".join(lines)

    if status == "ambiguous":
        query      = output.get("query", "")
        candidates = output.get("candidates", [])
        shorts     = [c.get("short_name", "?") for c in candidates]
        return (
            f"Múltiples equipos coinciden con '{query}': {', '.join(shorts)}. "
            "Por favor especifica."
        )

    if status == "not_found":
        return output.get("message", "Equipo no encontrado.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_web_fetch(output: dict[str, Any]) -> str:
    """Render web_fetch raw_output.  P2.7."""
    status = output.get("status")
    if status == "ok":
        url      = output.get("url", "?")
        length   = output.get("content_length", 0)
        excerpt  = output.get("text_excerpt", "")
        trunc    = output.get("truncated", False)
        trunc_note = " (truncado)" if trunc else ""
        return (
            f"Obtenido {url} ({length} bytes{trunc_note}).\n{excerpt}"
        )

    if status == "refused":
        return output.get("message", "URL rechazada por la lista de dominios permitidos.")

    code    = output.get("code", "error")
    message = output.get("message", "Error al obtener la URL.")
    http_st = output.get("http_status")
    suffix  = f" (HTTP {http_st})" if http_st else ""
    return f"Error ({code}): {message}{suffix}"


def _render_rank_players_by_metric(output: dict[str, Any]) -> str:
    """Render rank_players_by_metric raw_output.  P2.8."""
    status = output.get("status")
    if status == "ok":
        metric    = output.get("metric", "?")
        ranked    = output.get("ranked", [])
        pos_flt   = output.get("position_filter")
        min_mins  = output.get("min_minutes_filter", 0)

        filter_parts: list[str] = []
        if pos_flt:
            filter_parts.append(f"posición: {pos_flt}")
        if min_mins > 0:
            filter_parts.append(f"min. minutos: {min_mins}")
        filter_str = f" [{', '.join(filter_parts)}]" if filter_parts else ""

        if not ranked:
            return f"Sin jugadores para la métrica '{metric}'{filter_str}."

        header = f"Top {len(ranked)} jugadores por {metric}{filter_str}:"
        lines = [header]
        # Table header
        lines.append("  #  | Jugador       | Equipo | Pos | Valor métrica")
        lines.append("  ---|---------------|--------|-----|---------------")
        for entry in ranked:
            rank  = entry.get("rank", "?")
            name  = entry.get("web_name", "?")
            team  = entry.get("team_short", "?")
            pos   = entry.get("position", "?")
            val   = entry.get("metric_value", 0.0)
            # Format float sensibly
            if isinstance(val, float) and val == int(val) and abs(val) < 1e6:
                val_str = str(int(val))
            else:
                val_str = f"{val:.2f}"
            lines.append(
                f"  {str(rank).rjust(3)} | {name.ljust(13)} | {team.ljust(6)} | {pos.ljust(3)} | {val_str}"
            )
        return "\n".join(lines)

    if status == "invalid_argument":
        return output.get("message", "Métrica no reconocida.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
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
    "get_player_form":              _render_get_player_form,            # Phase 2.6d
    "get_injury_list":              _render_get_injury_list,            # Phase 2.6d
    "get_price_changes":            _render_get_price_changes,          # Phase 2.6d
    "get_team_fixture_calendar":    _render_get_team_fixture_calendar,  # Phase 2.6e
    "get_team_schedule":            _render_get_team_schedule,           # Phase 2.6e.3
    "get_position_fixture_run":     _render_get_position_fixture_run,    # Phase 2.6e.4
    "get_transfer_suggestion":      _render_get_transfer_suggestion,     # Phase 2.6h
    # P2 atomic tools (P2.8 Gap B fix)
    "find_players":             _render_find_players,            # P2.1
    "get_player_snapshot":      _render_get_player_snapshot,     # P2.2
    "get_player_history":       _render_get_player_history,      # P2.3
    "get_fixtures_for_gw":      _render_get_fixtures_for_gw,     # P2.4
    "get_gameweek_context":     _render_get_gameweek_context,    # P2.5
    "get_team_snapshot":        _render_get_team_snapshot,       # P2.6
    "web_fetch":                _render_web_fetch,               # P2.7
    "rank_players_by_metric":   _render_rank_players_by_metric,  # P2.8
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