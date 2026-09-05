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

try:
    from .formatting import format_metric_value
except ImportError:  # standalone load (test_renderer_zonal bypasses the package)
    from formatting import format_metric_value  # type: ignore[no-redef]

try:
    from .locale_types import Locale, DEFAULT_LOCALE
except ImportError:  # standalone load (test_renderer_zonal bypasses the package)
    from locale_types import Locale, DEFAULT_LOCALE  # type: ignore[no-redef]

try:
    from .catalogue import t
except ImportError:  # standalone load (test_renderer_zonal bypasses the package)
    from catalogue import t  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# status_label: shared by resolve_player and get_player_summary.  F2.
# ---------------------------------------------------------------------------
# The renderer never receives the raw single-char status code -- by the
# time output["status_label"] reaches here it is already the English word
# ("Available"/"Doubtful"/"Injured"/"Suspended"/"Unavailable"), produced
# upstream by fpl_query_tools._STATUS_LABELS -- so this maps that English
# value straight to a catalogue key. Same unmapped-fallback shape as
# _localized_difficulty_label: a raw English word in Spanish output is a
# visible, debuggable regression; a blank field is not.

_STATUS_LABEL_KEYS = {
    "Available":   "status_label.available",
    "Doubtful":    "status_label.doubtful",
    "Injured":     "status_label.injured",
    "Suspended":   "status_label.suspended",
    "Unavailable": "status_label.unavailable",
}


def _localized_status_label(value: str, locale: Locale) -> str:
    key = _STATUS_LABEL_KEYS.get(value)
    if key is None:
        return value
    return t(key, locale)


# ---------------------------------------------------------------------------
# Per-tool renderers
# ---------------------------------------------------------------------------

def _render_resolve_player(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a resolve_player raw_output dict into a human-readable string.
    F2: localized.
    """
    status = output.get("status")
    if status == "ok":
        name       = output.get("name", output.get("web_name", "Unknown"))
        web_name   = output.get("web_name", "")
        team       = output.get("team", "")
        team_short = output.get("team_short", "")
        position   = output.get("position", "")
        status_lbl = _localized_status_label(output.get("status_label", ""), locale)
        via        = output.get("resolved_via", "")

        if name != web_name:
            result = t(
                "resolve_player.summary_named", locale,
                web_name=web_name, name=name, team=team, team_short=team_short,
                position=position, status_lbl=status_lbl,
            )
        else:
            result = t(
                "resolve_player.summary_unnamed", locale,
                web_name=web_name, team=team, team_short=team_short,
                position=position, status_lbl=status_lbl,
            )
        if via:
            result += t("resolve_player.resolved_via_suffix", locale, via=via)
        return result

    if status == "ambiguous":
        query = output.get("query", "that name")
        return t("resolve_player.ambiguous", locale, query=query)

    if status == "not_found":
        query = output.get("query", "that player")
        return t("resolve_player.not_found", locale, query=query)

    # error or unexpected
    code    = output.get("code", "unknown")
    message = output.get("message", t("resolve_player.error_fallback", locale))
    return f"Error ({code}): {message}"


def _render_get_player_summary(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a get_player_summary raw_output dict into a human-readable
    string. F2: localized.
    """
    status = output.get("status")
    if status == "ok":
        name       = output.get("name", output.get("web_name", "Unknown"))
        web_name   = output.get("web_name", "")
        team       = output.get("team", "")
        team_short = output.get("team_short", "")
        position   = output.get("position", "")
        status_lbl = _localized_status_label(output.get("status_label", ""), locale)
        cost_m     = output.get("cost_m", "?")
        ownership  = output.get("selected_by_percent", "?")

        display = f"{web_name} ({name})" if name != web_name else web_name
        base = t(
            "player_summary.line", locale,
            display=display, team=team, team_short=team_short, position=position,
            cost_m=cost_m, ownership=ownership, status_lbl=status_lbl,
        )
        # Phase 2.6d Story 2.2: append season totals when available
        extras: list[str] = []
        total_pts = output.get("total_points")
        form_val  = output.get("form")
        minutes   = output.get("minutes")
        if total_pts is not None:
            extras.append(t("player_summary.extra_total_pts", locale, total_pts=total_pts))
        if form_val is not None:
            extras.append(t("player_summary.extra_form", locale, form_val=form_val))
        if minutes is not None:
            extras.append(t("player_summary.extra_mins", locale, minutes=minutes))
        if extras:
            return base + " " + " | ".join(extras) + "."
        return base

    if status == "ambiguous":
        query = output.get("query", "that name")
        return t("player_summary.ambiguous", locale, query=query)

    if status == "not_found":
        query = output.get("query", "that player")
        return t("player_summary.not_found_fallback", locale, query=query)

    code    = output.get("code", "unknown")
    message = output.get("message", t("player_summary.error_fallback", locale))
    return f"Error ({code}): {message}"


def _render_get_current_gameweek(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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

def _captain_time_notice(output: dict[str, Any], locale: Locale) -> str:
    context = output.get("time_context") or {}
    if not context:
        return ""
    if locale != "es":
        return str(context.get("notice") or "")

    start = context.get("evaluated_gameweek")
    end = context.get("gameweek_to")
    source = context.get("source")
    if start is None:
        return "No se pudo determinar la jornada actual."
    if end is None or end == start:
        label = "jornada actual" if source == "current" else "jornada solicitada"
        return f"Evaluado para la {label} GW{start}."
    label = "ventana actual" if source == "current" else "ventana solicitada"
    return f"Evaluado para la {label} GW{start}-GW{end}."

def _render_get_captain_score(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a get_captain_score raw_output dict into a human-readable string.
    F2: localized.
    """
    from .explainer import explain_captain  # local import — avoids circular

    status = output.get("status")
    if status == "ok":
        web_name   = output.get("web_name", "Unknown")
        team_short = output.get("team_short", "")
        score      = output.get("captain_score", 0)
        tier       = output.get("tier", "")

        tier_label = _tier_display(tier, locale)  # e.g. "Safe"/"Segura"

        reasons = explain_captain(output, locale=locale)
        reasons_clause = (" " + "; ".join(reasons) + ".") if reasons else ""

        notice = _captain_time_notice(output, locale)
        prefix = f"{notice}\n" if notice else ""
        return f"{prefix}{web_name} ({team_short}) — {tier_label} [{score}].{reasons_clause}"

    if status == "ambiguous":
        query = output.get("query", "that name")
        return t("captain_score.ambiguous", locale, query=query)

    if status == "not_found":
        query = output.get("query", "that player")
        return t("captain_score.not_found_fallback", locale, query=query)

    code    = output.get("code", "unknown")
    message = output.get("message", t("captain_score.error_fallback", locale))
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Rank captain candidates renderer  (Phase 5m)
# ---------------------------------------------------------------------------

def _render_rank_captain_candidates(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a rank_captain_candidates raw_output dict into a human-readable
    string. F2: localized.
    """
    from .captain_factors import contradiction_note, factor_phrases  # local import
    from .explainer import explain_captain_compact  # local import

    status = output.get("status")
    if status == "ok":
        candidates = output.get("ranked_candidates", [])
        ok_entries = [c for c in candidates if c.get("status") == "ok"]

        if not ok_entries:
            return t("rank_captain.none", locale)

        def _line(c: dict[str, Any], *, mark_owned: bool = False) -> str:
            rank      = c.get("rank", "?")
            name      = c.get("web_name", "?")
            team_s    = c.get("team_short", "")
            score     = c.get("captain_score", 0)
            tier      = c.get("tier", "")
            role_sigs = c.get("role_signals", {})

            tier_s   = _tier_short(tier, locale)             # e.g. "safe"/"seg"
            sp_sfx   = _set_piece_suffix(role_sigs, locale)  # e.g. "· penalty taker" or ""

            compact_reasons = explain_captain_compact(c, locale=locale)
            reason_str = "; ".join(compact_reasons) if compact_reasons else ""
            # Minutes and penalties travel beside the score, never inside it.
            factors = factor_phrases(c, locale=locale)
            factor_str = " · ".join(factors) if factors else ""

            # Position is shown because the pool is open to every position: a
            # keeper and a forward are otherwise the same row.
            pos_s = c.get("position", "")
            where = f"{team_s}, {pos_s}" if pos_s else team_s
            line = f"{rank}. {name} ({where}) [{tier_s}] {score}{(' ' + sp_sfx) if sp_sfx else ''}"
            if mark_owned and c.get("owned"):
                line += " · tu plantilla" if locale == "es" else " · your squad"
            if reason_str:
                line += f" — {reason_str}"
            if factor_str:
                line += f" ({factor_str})"
            return line

        notice = _captain_time_notice(output, locale)
        pool_source = output.get("pool_source")
        if locale == "es":
            pool_notice = (
                "Origen del pool: derivado del bootstrap."
                if pool_source == "derived"
                else "Origen del pool: candidatos indicados por el usuario."
                if pool_source == "caller"
                else ""
            )
        else:
            pool_notice = (
                "Pool source: derived from bootstrap."
                if pool_source == "derived"
                else "Pool source: caller-supplied candidates."
                if pool_source == "caller"
                else ""
            )
        header = [value for value in (notice, pool_notice) if value]
        if pool_source != "derived":
            return "\n".join(header + [_line(c) for c in ok_entries])

        from fpl_tool_contract.tools import DERIVED_CAPTAIN_POOL_LIMIT

        by_id = {
            int(c["player_id"]): c
            for c in ok_entries
            if c.get("player_id") is not None
        }
        # The tool names which rows each list shows. Deriving that again here is
        # how the card and the text end up disagreeing.
        presentation = output.get("presentation") or {}

        def _shown(key, fallback):
            ids = presentation.get(key)
            if not ids:
                return fallback
            return [by_id[i] for i in ids if i in by_id]

        def _hipster_line(key):
            """One extra lightly-owned name, or an honest line saying there is none."""
            pick = presentation.get(key) or {}
            player_id = pick.get("player_id")
            if player_id is None:
                return (
                    "Sin hipster: nadie de poca propiedad llega al minimo."
                    if locale == "es"
                    else "No hipster: nobody lightly owned clears the bar."
                )
            entry = by_id.get(int(player_id))
            if entry is None:
                return None
            share_value = pick.get("selected_by_percent")
            if share_value is None:
                share = ""
            elif locale == "es":
                share = f" - {share_value:.1f}% de propiedad"
            else:
                share = f" - owned by {share_value:.1f}%"
            return f"Hipster: {_line(entry)}{share}"

        global_entries = _shown("global_top", [
            c for c in ok_entries
            if int(c.get("rank", 0) or 0) <= DERIVED_CAPTAIN_POOL_LIMIT
        ])
        owned_entries = _shown(
            "owned_top", [c for c in ok_entries if c.get("owned")]
        )
        squad_source = output.get("squad_source", "not_connected")

        body: list[str] = []
        if squad_source == "connected":
            body.append(
                "A) Candidatos de tu plantilla:"
                if locale == "es"
                else "A) Candidates from your squad:"
            )
            if owned_entries:
                body.extend(_line(c) for c in owned_entries)
                owned_hipster = _hipster_line("owned_hipster")
                if owned_hipster:
                    body.append(owned_hipster)
            else:
                body.append(
                    "No hay candidatos disponibles en tu plantilla."
                    if locale == "es"
                    else "There are no available candidates in your squad."
                )
        elif squad_source == "unavailable":
            body.append(
                "No pude cargar tu plantilla; te muestro solo el ranking global."
                if locale == "es"
                else "I could not load your squad, so I am showing only the global ranking."
            )
        else:
            body.append(
                "No hay equipo conectado; te muestro solo el ranking global."
                if locale == "es"
                else "No team is connected, so I am showing only the global ranking."
            )

        excluded = output.get("squad_excluded") or []
        if excluded:
            reason_labels = {
                "unavailable": "no disponible" if locale == "es" else "unavailable",
                "unresolved": "sin resolver" if locale == "es" else "unresolved",
            }
            excluded_text = ", ".join(
                f"{entry.get('web_name', '?')} "
                f"({reason_labels.get(entry.get('reason'), entry.get('reason', '?'))})"
                for entry in excluded
            )
            body.append(
                f"No evaluados para capitanía: {excluded_text}."
                if locale == "es"
                else f"Not evaluated for captaincy: {excluded_text}."
            )

        body.append("B) Mejores candidatos globales:" if locale == "es" else "B) Best global candidates:")
        body.extend(_line(c, mark_owned=True) for c in global_entries)
        global_hipster = _hipster_line("global_hipster")
        if global_hipster:
            body.append(global_hipster)

        # A note only where the ranking would mislead — a row without one means
        # there is no surprise in it, which stops being true if we annotate
        # everything.
        #
        # The note has to reach the reader, so a short list must not cut the row
        # it was written for: a player who plays every minute and takes the
        # penalties, sunk below players who do neither, is named even when he
        # falls outside the shown five.
        shown_ids = {e.get("player_id") for e in global_entries + owned_entries}
        for entry in ok_entries:
            note = contradiction_note(
                entry,
                [e for e in ok_entries if int(e.get("rank", 0) or 0) < int(entry.get("rank", 0) or 0)],
                locale=locale,
            )
            if not note:
                continue
            if entry.get("player_id") not in shown_ids:
                body.append(f"Conviene saber: {_line(entry)}")
            body.append(f"Sobre {entry.get('web_name', '?')}: {note}")
        return "\n".join(header + body)

    code    = output.get("code", "error")
    message = output.get("message", t("rank_captain.error_fallback", locale))
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Comparison renderer  (Phase 5b)
# ---------------------------------------------------------------------------

def _render_compare_players(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a compare_players raw_output dict into a human-readable string.
    F1: localized.

    The "ok" status is almost entirely tier-2: ``output["recommendation"]``
    is a finished sentence built by comparison.py, not this renderer, and it
    stays in whatever language it was built in (currently always English)
    regardless of *locale* — the three fallback strings below are the only
    text this renderer actually owns.
    """
    status = output.get("status")
    if status == "ok":
        rec = output.get("recommendation", "")
        return rec if rec else t("compare_players.ok_fallback", locale)
    if status in ("not_found", "ambiguous"):
        ep  = output.get("error_player", "")
        msg = output.get("message", t("compare_players.not_found_fallback", locale, player=ep))
        return msg
    code    = output.get("code", "error")
    message = output.get("message", t("compare_players.error_fallback", locale))
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Transfer advice renderer  (Phase 6a)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chip advice renderer  (Phase 6b)
# ---------------------------------------------------------------------------

def _render_get_chip_advice(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a get_chip_advice raw_output dict into a human-readable string."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status == "ok":
        return output.get("advice_text", "Chip advice computed.")
    if status == "not_found":
        chip = output.get("chip", "unknown")
        return f"'{chip}' is not a recognised FPL chip name."
    code    = output.get("code", "error")
    message = output.get("message", "An unexpected chip advice error occurred.")
    return f"Error ({code}): {message}"


def _render_get_transfer_advice(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a get_transfer_advice raw_output dict into a human-readable string."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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
# difficulty_label: shared by get_player_fixture_run and
# get_transfer_suggestion (Phase 7h / 2.6h).  F1 commit 3.
# ---------------------------------------------------------------------------
# The same closed 3-value enum in both tools, with matching thresholds:
# transfer_suggestion.py's _difficulty_label() and player_fixture_run.py's
# FDR-context builder. An adjective the renderer drops into a sentence
# ("una racha {label}"), not a cross-referenced identifier -- see the
# translation rule in catalogue.py's module docstring.

_DIFFICULTY_LABEL_KEYS = {
    "easy":     "difficulty_label.easy",
    "moderate": "difficulty_label.moderate",
    "hard":     "difficulty_label.hard",
}


def _localized_difficulty_label(value: str, locale: Locale) -> str:
    """Translate a tool-computed difficulty_label.

    The enum is closed today (easy/moderate/hard), but the thresholds that
    produce it live in the tool, not here -- if a fourth band is ever added
    there without a matching catalogue entry, fall back to the raw token
    rather than rendering silently blank. A raw English word appearing in
    Spanish output is a visible, debuggable regression; an empty string in
    its place is not.
    """
    key = _DIFFICULTY_LABEL_KEYS.get(value)
    if key is None:
        return value
    return t(key, locale)


# ---------------------------------------------------------------------------
# Player fixture run renderer  (Phase 7h)
# ---------------------------------------------------------------------------

def _render_get_player_fixture_run(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a get_player_fixture_run raw_output dict into a human-readable
    string.  F1: localized.

    ``GW{n}`` stays ``GW{n}`` in both locales — matching the convention
    already established elsewhere in this module (see
    ``_render_get_gameweek_context``'s "Jornada actual: GW{n}") — as does
    the per-fixture ``FDR``/venue-letter line, which is codes, not prose.
    ``difficulty_label`` (``ctx["difficulty_label"]``) *is* translated (F1
    commit 3) via ``_localized_difficulty_label`` — it is an adjective
    ("una racha fácil"), not a cross-referenced identifier like the codes
    above.
    """
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
        gw_clause = (
            t("player_fixture_run.gw_from_clause", locale, gw=gw_from)
            if gw_from is not None else ""
        )
        plural = "s" if horizon != 1 else ""
        header = " ".join(header_parts) + t(
            "player_fixture_run.header_suffix", locale,
            horizon=horizon, plural=plural, gw_clause=gw_clause,
        )

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
            raw_label = ctx.get("difficulty_label", "")
            label = _localized_difficulty_label(raw_label, locale)
            g_from = ctx.get("gw_from")
            g_to   = ctx.get("gw_to")
            gw_range = f"GW{g_from}-GW{g_to}" if g_from and g_to else ""
            fdr_gw_clause = (
                t("player_fixture_run.fdr_context_gw_clause", locale, gw_range=gw_range)
                if gw_range else ""
            )
            article = "an" if raw_label[:1] in "aeiou" else "a"  # EN-only agreement; on the raw (English) word
            result += t(
                "player_fixture_run.fdr_context", locale,
                team=team, article=article, label=label,
                gw_clause=fdr_gw_clause, avg=f"{avg:.1f}",
            )

        return result

    if status in ("not_found", "ambiguous"):
        return output.get("message", t("player_fixture_run.not_found_fallback", locale))

    if status == "missing_context":
        return output.get("message", t("player_fixture_run.missing_context_fallback", locale))

    code    = output.get("code", "error")
    message = output.get("message", t("player_fixture_run.error_fallback", locale))
    return f"Error ({code}): {message}"


def _render_get_differential_picks(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render differential picks output.  Phase 7g."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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

def _render_get_player_form(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_player_form output."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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
# Player season-points renderer
# ---------------------------------------------------------------------------

def _render_get_player_season_points(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_player_season_points output."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status == "ok":
        season = output.get("season", "?")
        player = output.get("player", {})
        web_name = player.get("web_name", "?")
        team = player.get("team_short", "")
        pos = player.get("position", "")
        summary = output.get("summary", {})

        total_pts = summary.get("total_points", 0)
        gws = summary.get("gws_played", 0)
        ppg = summary.get("points_per_game", 0.0)
        goals = summary.get("total_goals", 0)
        assists = summary.get("total_assists", 0)
        clean_sheets = summary.get("total_clean_sheets", 0)
        bonus = summary.get("total_bonus", 0)
        minutes = summary.get("total_minutes", 0)

        return (
            f"{web_name} ({team}, {pos}) — {season}: {total_pts} points "
            f"across {gws} gameweek(s) played ({ppg} pts/game). "
            f"{goals}g {assists}a {clean_sheets}cs {bonus}bps {minutes}mins."
        )

    if status == "ambiguous":
        query = output.get("query", "that player")
        return f"Multiple players share the name '{query}'. Please use a full name or player ID to disambiguate."

    if status == "not_found":
        query = output.get("query", "that player")
        return output.get("message", f"No player found matching '{query}'.")

    code = output.get("code", "error")
    message = output.get("message", "An unexpected error occurred looking up season points.")
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Injury list renderer  (Phase 2.6d Story 2.3)
# ---------------------------------------------------------------------------

def _render_get_injury_list(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_injury_list output. F2: localized.

    ``other`` groups both suspended and unavailable players under one
    composite header (see injury_list.py's bucketing), so this is 3 header
    phrases, not the 5-value status vocabulary — per-player ``web_name``/
    ``team_short``/``position`` stay raw codes/names as elsewhere.
    """
    status = output.get("status")
    if status == "ok":
        injured  = output.get("injured", [])
        doubtful = output.get("doubtful", [])
        other    = output.get("other", [])
        total    = output.get("total", 0)

        if total == 0:
            return t("injury_list.none", locale)

        parts: list[str] = []
        if injured:
            names = ", ".join(f"{p['web_name']} ({p['team_short']}, {p['position']})" for p in injured)
            parts.append(t("injury_list.injured_header", locale, names=names))
        if doubtful:
            doubt_strs: list[str] = []
            for p in doubtful:
                chance = p.get("chance_of_playing")
                s = f"{p['web_name']} ({p['team_short']}, {p['position']})"
                if chance is not None:
                    s += f" {chance}%"
                doubt_strs.append(s)
            parts.append(t("injury_list.doubtful_header", locale, names=", ".join(doubt_strs)))
        if other:
            names = ", ".join(f"{p['web_name']} ({p['team_short']})" for p in other)
            parts.append(t("injury_list.suspended_header", locale, names=names))

        return " | ".join(parts) + "."

    code    = output.get("code", "error")
    message = output.get("message", t("injury_list.error_fallback", locale))
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Price changes renderer  (Phase 2.6d Story 2.4)
# ---------------------------------------------------------------------------

def _render_get_price_changes(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_price_changes output."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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

def _render_get_team_fixture_calendar(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_team_fixture_calendar output."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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

_TRANSFER_SUGGESTION_POSITION_KEYS = {
    "GKP": "position_noun.GKP",
    "DEF": "position_noun.DEF",
    "MID": "position_noun.MID",
    "FWD": "position_noun.FWD",
    "ALL": "position_noun.ALL",
}


def _render_get_transfer_suggestion(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_transfer_suggestion output.  Phase 2.6h.  F1: localized.

    ``position_noun`` is built by this renderer from the raw ``position``
    code (a closed enum: GKP/DEF/MID/FWD/ALL), *not* from the payload's own
    ``position_label`` field — that field is tier-2 (built by
    transfer_suggestion.py) and stays English regardless of locale;
    reusing it here would silently defeat the whole point of this change.
    ``difficulty_label`` per pick *is* translated (F1 commit 3) via
    ``_localized_difficulty_label`` — see that function's docstring.
    """
    status = output.get("status")

    if status == "ok":
        position_code = output.get("position", "ALL")
        position_noun = t(
            _TRANSFER_SUGGESTION_POSITION_KEYS.get(position_code, "position_noun.ALL"), locale,
        )
        team_short = output.get("team_short")
        max_price  = output.get("max_price")
        horizon    = output.get("horizon", 5)
        picks      = output.get("picks", [])

        # Phase 2.6i: prefix with club name when a team filter was applied
        team_prefix = f"{team_short} " if team_short else ""

        price_clause = ""
        if max_price is not None:
            try:
                price_clause = t("transfer_suggestion.price_clause", locale, max_price=f"{float(max_price):.1f}")
            except (TypeError, ValueError):
                pass
        header = t(
            "transfer_suggestion.header", locale,
            team_prefix=team_prefix, position_noun=position_noun,
            price_clause=price_clause, horizon=horizon,
        )
        if not picks:
            return header + t("transfer_suggestion.no_picks_suffix", locale)

        lines = [header]
        for p in picks:
            rank   = p.get("rank", "?")
            name   = p.get("web_name", "?")
            team   = p.get("team_short", "?")
            pos    = p.get("position", "?")
            cost_m = p.get("now_cost_m", 0.0)
            form   = p.get("form", 0.0)
            avg    = p.get("avg_fdr", 0.0)
            label  = _localized_difficulty_label(p.get("difficulty_label", ""), locale)
            own    = p.get("ownership", 0.0)
            lines.append(t(
                "transfer_suggestion.pick_line", locale,
                rank=rank, name=name, team=team, pos=pos,
                cost_m=f"{cost_m:.1f}", form=f"{form:.1f}", avg_fdr=f"{avg:.1f}",
                label=label, own=f"{own:.1f}",
            ))
        return "\n".join(lines)

    if status == "empty":
        return output.get("message", t("transfer_suggestion.empty_fallback", locale))

    if status == "not_found":
        team_query = output.get("team_query", "that team")
        return t("transfer_suggestion.not_found", locale, team_query=team_query)

    if status == "missing_context":
        return output.get("message", t("transfer_suggestion.missing_context_fallback", locale))

    code    = output.get("code", "error")
    message = output.get("message", t("transfer_suggestion.error_fallback", locale))
    return f"Error ({code}): {message}"


def _render_get_position_fixture_run(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_position_fixture_run output."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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

def _render_get_team_schedule(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_team_schedule output."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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

    if status == "ambiguous":
        query      = output.get("team_query", "")
        candidates = output.get("candidates", [])
        shorts     = [c.get("short_name", "?") for c in candidates]
        return (
            f"Multiple teams match '{query}': {', '.join(shorts)}. "
            "Please specify which one."
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

def _render_find_players(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render find_players raw_output.  P2.1."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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


def _render_get_player_snapshot(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_player_snapshot raw_output.  P2.2.  F1: localized.

    ``news`` is FPL's own third-party API text (tier-3) and is passed
    through verbatim in both locales — only the "News:"/"Noticias:" label
    around it is this renderer's own prose.
    """
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
        news      = p.get("news", "") or ""  # tier-3: third-party, verbatim
        chance    = p.get("chance_of_playing_this_round")

        lines = [
            f"**{name}** ({team}, {pos})",
            t("player_snapshot.price_line", locale, cost=f"{cost:.1f}", own=f"{own:.1f}", status_lbl=status_lbl),
            t("player_snapshot.points_line", locale, pts=pts, ppg=f"{ppg:.1f}", form=form),
            f"  xG: {xg:.2f} | xA: {xa:.2f} | xGI: {xgi:.2f} | ICT: {ict:.1f}",
            t("player_snapshot.minutes_line", locale, mins=mins),
        ]
        if chance is not None:
            lines.append(t("player_snapshot.chance_line", locale, chance=chance))
        if news:
            lines.append(t("player_snapshot.news_line", locale, news=news))
        return "\n".join(lines)

    if status == "ambiguous":
        query      = output.get("query", "")
        candidates = output.get("candidates", [])
        lines = [t("player_snapshot.ambiguous_header", locale, query=query)]
        for c in candidates:
            name  = c.get("web_name", "?")
            team  = c.get("team_short", "?")
            pos   = c.get("position", "?")
            rank  = c.get("match_rank", "?")
            lines.append(t("player_snapshot.candidate_line", locale, name=name, team=team, pos=pos, rank=rank))
        return "\n".join(lines)

    if status == "not_found":
        return output.get("message", t("player_snapshot.not_found_fallback", locale))

    code    = output.get("code", "error")
    message = output.get("message", t("player_snapshot.error_fallback", locale))
    return f"Error ({code}): {message}"


def _render_get_player_history(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_player_history raw_output.  P2.3."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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


def _render_get_fixtures_for_gw(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_fixtures_for_gw raw_output.  P2.4."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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


def _render_get_gameweek_context(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_gameweek_context raw_output.  P2.5."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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


def _render_get_team_snapshot(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_team_snapshot raw_output.  P2.6."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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


#: Chip codes stay in their FPL-app-native English display form regardless of
#: locale -- the FPL app itself has no Spanish UI, so a Spanish-speaking user
#: needs this exact label to find the chip in their own app. Same rule as
#: web_name / position codes in catalogue.py: cross-referenced against another
#: system, so it does not translate with the sentence around it.
_CHIP_DISPLAY_LABEL: dict[str, str] = {
    "wildcard":       "Wildcard",
    "triple_captain": "Triple Captain",
    "bench_boost":    "Bench Boost",
    "free_hit":       "Free Hit",
}


def _render_get_my_squad(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_my_squad raw_output.  i39.

    Every status this tool can return is handled explicitly with catalogue
    text (never the tool's own hardcoded-Spanish ``message`` field) so the
    deterministic render honors *locale* even though the tool itself does
    not carry a locale parameter -- same tier boundary as every other F1
    renderer (catalogue.py's "Tier boundary" note).
    """
    status = output.get("status")

    if status == "ok":
        gw       = output.get("gw", "?")
        players  = output.get("players", [])
        summary  = output.get("summary", {})
        chip_raw = summary.get("active_chip")

        chip_clause = ""
        if chip_raw:
            chip_label = _CHIP_DISPLAY_LABEL.get(chip_raw, chip_raw)
            chip_clause = t("my_squad.chip_clause", locale, chip_label=chip_label)

        lines = [t("my_squad.header", locale, gw=gw, chip_clause=chip_clause)]
        if output.get("gw_clamped"):
            lines.append(t(
                "my_squad.gw_clamped_note", locale,
                requested_gw=output.get("requested_gw", "?"), gw=gw,
            ))

        starters = [p for p in players if p.get("is_starter")]
        bench    = [p for p in players if not p.get("is_starter")]

        def _player_line(p: dict[str, Any]) -> str:
            name       = p.get("web_name", "?")
            team       = p.get("team_short", "?")
            pos        = p.get("position", "?")
            cost       = p.get("now_cost", 0) / 10.0
            status_lbl = _localized_status_label(p.get("status", ""), locale)
            form       = p.get("form", 0.0)
            captain_tag = ""
            if p.get("is_captain"):
                captain_tag = " (C)"
            elif p.get("is_vice_captain"):
                captain_tag = " (VC)"
            return t(
                "my_squad.player_line", locale,
                name=name, team=team, pos=pos, cost=f"{cost:.1f}",
                status_lbl=status_lbl, form=form, captain_tag=captain_tag,
            )

        if starters:
            lines.append(t("my_squad.starters_header", locale))
            lines.extend(_player_line(p) for p in starters)
        if bench:
            lines.append(t("my_squad.bench_header", locale))
            lines.extend(_player_line(p) for p in bench)

        bank_m = (summary.get("bank") or 0) / 10.0
        lines.append(t(
            "my_squad.summary_line", locale,
            gw=gw,
            gw_points=summary.get("gw_points", "?"),
            total_points=summary.get("total_points", "?"),
            bank=f"{bank_m:.1f}",
        ))
        return "\n".join(lines)

    if status == "no_team_connected":
        return t("my_squad.no_team_connected", locale)

    if status == "not_found":
        team_id = output.get("team_id", "?")
        return t("my_squad.team_not_found", locale, team_id=team_id)

    if status == "error" and output.get("code") == "network_error":
        return t("my_squad.network_error", locale)

    if status == "error" and output.get("code") == "invalid_gw":
        return t("my_squad.invalid_gw", locale, min_gw=1, max_gw=38)

    code    = output.get("code", "error")
    message = output.get("message", t("my_squad.error_fallback", locale))
    return f"Error ({code}): {message}"


def _render_search_web(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render search_web raw_output as a Spanish prose summary.

    Unlike worldcup_assistant's web_search, FPL's single-tool orchestrator
    path renders deterministically without a second LLM round-trip to phrase
    the answer (only the multi-tool batching path gets a second call). So
    this builds a templated summary from the result snippets rather than
    LLM-synthesized prose. The WebSearchCard still renders each cited result
    individually, so the real content is always visible regardless of how
    this summary reads.
    """
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status != "ok":
        code    = output.get("code", "error")
        message = output.get("message", "No se pudo completar la búsqueda web.")
        return f"Error ({code}): {message}"

    results = output.get("results") or []
    if not results:
        return "No encontré resultados relevantes para esa búsqueda."

    lines = ["Esto encontré en la web:"]
    for r in results[:3]:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        source = r.get("source", "")
        lines.append(f"- {title}: {snippet} ({source})".strip())
    return "\n".join(lines)


def _render_web_fetch(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render web_fetch raw_output.  P2.7."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
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


def _rank_is_inverted(metric: str, order: "str | None") -> bool:
    """True when the caller flipped the metric's natural ranking direction.

    ``order`` is absent on payloads produced before it existed, and equals the
    natural direction for an ordinary ranking — both read as not inverted.
    """
    if order is None:
        return False
    try:  # local import — renderer is also importable flat, without the package
        from .rank_players_by_metric import natural_order
    except ImportError:  # pragma: no cover - flat-import fallback
        from rank_players_by_metric import natural_order  # type: ignore[no-redef]

    return order != natural_order(metric)


def _render_rank_players_by_metric(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render rank_players_by_metric raw_output.  P2.8."""
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status == "ok":
        metric    = output.get("metric", "?")
        ranked    = output.get("ranked", [])
        pos_flt   = output.get("position_filter")
        min_mins  = output.get("min_minutes_filter", 0)
        order     = output.get("order")

        filter_parts: list[str] = []
        if pos_flt:
            filter_parts.append(f"posición: {pos_flt}")
        if min_mins > 0:
            filter_parts.append(f"min. minutos: {min_mins}")
        filter_str = f" [{', '.join(filter_parts)}]" if filter_parts else ""

        if not ranked:
            return f"Sin jugadores para la métrica '{metric}'{filter_str}."

        # An inverted ranking must not be titled "Top": that is exactly how a
        # cheapest-first list got read back as the most expensive players.
        if _rank_is_inverted(metric, order):
            extreme = "menor" if order == "asc" else "mayor"
            header = (
                f"Los {len(ranked)} jugadores con {extreme} "
                f"{metric}{filter_str}:"
            )
        else:
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
            val_str = format_metric_value(val)
            lines.append(
                f"  {str(rank).rjust(3)} | {name.ljust(13)} | {team.ljust(6)} | {pos.ljust(3)} | {val_str}"
            )
        return "\n".join(lines)

    if status == "invalid_argument":
        return output.get("message", "Métrica no reconocida.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_zonal_weakness(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_zonal_weakness raw_output.  T-zonal.

    Weakness/opportunity read only — the verdict comes from the engine and
    is already Spanish and buy/sell-free; this renderer only formats it.
    """
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status == "ok":
        team    = output.get("team", "?")
        verdict = output.get("verdict", "")
        weakest = output.get("weakest_zones", [])
        pen     = output.get("penalty_context", {})

        lines = [verdict or f"Lectura zonal de {team}:"]
        if weakest:
            lines.append("Zonas más débiles (xGA/partido vs media de la liga):")
            for z in weakest:
                zone  = z.get("zone", "?")
                xga   = z.get("xga_per_game", 0.0)
                avg   = z.get("league_avg", 0.0)
                delta = z.get("delta_vs_avg", 0.0)
                rank  = z.get("rank")
                rank_str = f" | nº{rank} de la liga" if rank else ""
                lines.append(
                    f"  {zone}: {xga:.3f} (media {avg:.3f}, {delta:+.3f}{rank_str})"
                )
        pen_pg = pen.get("penalty_xga_per_game")
        if pen_pg is not None:
            lines.append(
                f"Contexto penaltis (excluidos de las zonas): {pen_pg:.3f} xGA/partido."
            )
        return "\n".join(lines)

    if status == "not_found":
        team = output.get("team", "?")
        return output.get(
            "message", f"Sin datos zonales para '{team}' en el almacén táctico."
        )

    if status == "missing_context":
        return output.get(
            "message", "Datos tácticos (zonales) no disponibles en este despliegue."
        )

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_zonal_opportunity(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_zonal_opportunity raw_output.  T-zonal.

    Opportunity signal only — lists players whose shot profile concentrates
    in the opponent's above-average weak zones. Never buy/sell framing.
    """
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status == "ok":
        opponent      = output.get("opponent", "?")
        opportunities = output.get("opportunities", [])
        if not opportunities:
            return (
                f"{opponent} no concede por encima de la media de la liga en "
                f"ninguna zona del área — sin oportunidad zonal destacada."
            )
        lines = [f"Oportunidad zonal contra {opponent}:"]
        for opp in opportunities:
            zone    = opp.get("zone", "?")
            delta   = opp.get("delta_vs_avg", 0.0)
            players = opp.get("players", [])
            players_str = ", ".join(players) if players else "sin jugadores destacados"
            lines.append(f"  {zone} ({delta:+.3f} vs media): {players_str}")
        return "\n".join(lines)

    if status == "not_found":
        opponent = output.get("opponent", "?")
        return output.get(
            "message", f"Sin datos zonales para '{opponent}' en el almacén táctico."
        )

    if status == "missing_context":
        return output.get(
            "message", "Datos tácticos (zonales) no disponibles en este despliegue."
        )

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_player_zonal_outlook(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_player_zonal_outlook raw_output.  T-player.

    Opportunity-framed per-fixture matchup read — never buy/sell framing.
    """
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    if status == "ok":
        player  = output.get("player", "?")
        team    = output.get("team", "?")
        verdict = output.get("verdict", "")
        zones   = output.get("player_zones", [])
        outlook = output.get("outlook", [])

        lines = [verdict or f"Cruce zonal de {player} ({team}):"]
        if zones:
            zones_str = ", ".join(
                f"{z.get('zone', '?')} ({z.get('share', 0.0) * 100:.0f}% de su xG)"
                for z in zones
            )
            lines.append(f"Zonas de {player}: {zones_str}.")
        for e in outlook:
            gw    = e.get("gameweek", "?")
            opp   = e.get("opponent", "?")
            venue = "casa" if e.get("is_home") else "fuera"
            e_status = e.get("status")
            if e_status == "favorable":
                matches_str = "; ".join(
                    f"{m.get('zone', '?')} (rival {m.get('delta_vs_avg', 0.0):+.3f} "
                    f"vs media, {m.get('player_share', 0.0) * 100:.0f}% del xG de {player})"
                    for m in e.get("matches", [])
                )
                lines.append(f"  J{gw} vs {opp} ({venue}): favorable — {matches_str}")
            elif e_status == "no_data":
                lines.append(f"  J{gw} vs {opp} ({venue}): sin datos zonales del rival")
            else:
                lines.append(f"  J{gw} vs {opp} ({venue}): sin cruce destacado")
        return "\n".join(lines)

    if status == "not_found":
        player = output.get("player", "?")
        return output.get(
            "message",
            f"Sin perfil de tiro para '{player}' en el almacén táctico.",
        )

    if status == "ambiguous":
        player     = output.get("player", "?")
        candidates = output.get("candidates", [])
        return (
            f"Varios jugadores coinciden con '{player}': {', '.join(candidates)}. "
            "Por favor especifica."
        )

    if status == "missing_context":
        return output.get(
            "message", "Datos tácticos o calendario no disponibles en este despliegue."
        )

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_get_fixture_outlook(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render get_fixture_outlook raw_output.  Track D / FI2.

    Schedule-only read (bands + runs + verdict) — never buy/sell framing.
    Single team when ``series`` is present; all-teams grid otherwise.
    """
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")
    axis_label = "ofensivo" if output.get("axis") == "attack" else "de portería a cero"

    if status == "ok":
        series = output.get("series")
        if series is not None:
            # Single-team outlook: verdict + per-GW band line.
            team_name = output.get("team_name", "?")
            lines = [output.get("verdict") or f"Calendario {axis_label} del {team_name}:"]
            for gw in series:
                fixtures = gw.get("fixtures", [])
                if not fixtures:
                    lines.append(f"  J{gw.get('gameweek', '?')}: descansa (sin partido)")
                    continue
                matchup = " y ".join(
                    f"{f.get('opponent_short', '?')} ({'casa' if f.get('is_home') else 'fuera'})"
                    for f in fixtures
                )
                dgw = " — doble jornada" if gw.get("is_dgw") else ""
                lines.append(
                    f"  J{gw.get('gameweek', '?')}: {matchup}, dificultad {gw.get('band', '?')}/5{dgw}"
                )
            return "\n".join(lines)

        # All teams, easiest-first: compact ranking with average band.
        teams = output.get("teams", [])
        horizon = output.get("horizon", "?")
        lines = [f"Calendario {axis_label} (próximas {horizon} jornadas, más fácil primero):"]
        for t in teams:
            avg = t.get("avg_band")
            avg_str = f"{avg:.2f}" if isinstance(avg, (int, float)) else "?"
            lines.append(f"  {t.get('team_short', '?')} — dificultad media {avg_str}/5")
        return "\n".join(lines)

    if status == "not_found":
        team_query = output.get("team_query", "?")
        return output.get("message", f"No encontré ningún equipo que coincida con '{team_query}'.")

    if status == "missing_context":
        return output.get("message", "Calendario de partidos no disponible ahora mismo.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_build_squad(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render build_squad raw_output.  S1.

    Prints the totals the solver computed, in the solver's own units. Nothing
    here re-adds a column: the whole point of the tool is that the arithmetic
    happens once, in one place.
    """
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    status = output.get("status")

    if status == "ok":
        squad     = output.get("squad", [])
        formation = output.get("formation")
        xi_ids    = {entry.get("id") for entry in output.get("starting_xi", [])}

        lines = [
            f"Equipo de {output.get('squad_size', len(squad))} jugadores "
            f"por {output.get('objective', '?')} "
            f"(base: {output.get('ranking_basis', '?')}):"
        ]
        lines.append("  Pos | Jugador          | Club | Precio | Valor  | XI")
        lines.append("  ----|------------------|------|--------|--------|----")
        for entry in squad:
            pos   = str(entry.get("position", "?")).ljust(3)
            name  = str(entry.get("web_name", "?"))[:16].ljust(16)
            club  = str(entry.get("team_short", "?")).ljust(4)
            price = f"{entry.get('price', 0.0):.1f}m".rjust(6)
            value = str(entry.get("objective_value", "?")).rjust(6)
            mark  = "XI" if entry.get("id") in xi_ids else "banca"
            if entry.get("locked"):
                mark += " *"
            lines.append(f"  {pos} | {name} | {club} | {price} | {value} | {mark}")

        lines.append(
            f"  Coste total: {output.get('total_cost', 0.0)}m de "
            f"{output.get('budget', 0.0)}m — queda {output.get('remaining', 0.0)}m."
        )
        clubs = output.get("club_counts") or {}
        if clubs:
            lines.append(
                "  Por club: "
                + ", ".join(f"{club} {count}" for club, count in clubs.items())
                + f" (máximo permitido {3})."
            )
        if formation:
            lines.append(f"  Alineación: {formation} (más portero).")
        for warning in output.get("warnings", []):
            lines.append(f"  Aviso: {warning}")
        return "\n".join(lines)

    if status == "infeasible":
        return output.get("message", "No existe ningún equipo legal con esas restricciones.")

    if status == "ambiguous":
        candidates = ", ".join(
            str(candidate.get("web_name", "?")) for candidate in output.get("candidates", [])
        )
        message = output.get("message", "Varios jugadores coinciden.")
        return f"{message} Candidatos: {candidates}." if candidates else message

    if status == "not_found":
        return output.get("message", "No encontré a ese jugador.")

    if status == "invalid_argument":
        return output.get("message", "Argumentos no válidos para armar el equipo.")

    code    = output.get("code", "error")
    message = output.get("message", "Error inesperado.")
    return f"Error ({code}): {message}"


def _render_select_players(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Render select_players_within_budget raw_output.  S2.  F1: localized.

    Prints the solver's totals in the solver's own units. Nothing here re-adds
    a column: the arithmetic happens once, in squad_solver, and this is a view
    of it. The completability line is the point of the tool, so it is stated
    rather than implied.

    ``position``, ``objective``, and ``ranking_basis`` are raw identifiers
    (a position code, a metric name, a provenance tag) and are never
    translated. When the tool populates its own ``message`` (as
    squad_solver's infeasibility path always does, in English), that
    payload text wins over the renderer's own fallback regardless of
    *locale* \u2014 a known tier-2 leak, not something this renderer can fix.
    """
    status = output.get("status")

    if status == "ok":
        selection  = output.get("selection", [])
        completion = output.get("completion") or {}
        position   = output.get("position", "?")

        lines = [t(
            "select_players.header", locale,
            count=output.get("count", len(selection)), position=position,
            objective=output.get("objective", "?"), ranking_basis=output.get("ranking_basis", "?"),
        )]
        lines.append(t("select_players.column_header", locale))
        lines.append("  -----------------|------|--------|-------")
        for entry in selection:
            name  = str(entry.get("web_name", "?"))[:16].ljust(16)
            club  = str(entry.get("team_short", "?")).ljust(4)
            price = f"{entry.get('price', 0.0):.1f}m".rjust(6)
            value = str(entry.get("objective_value", "?")).rjust(6)
            lines.append(f"  {name} | {club} | {price} | {value}")

        locked = output.get("locked_players") or []
        if locked:
            entries = ", ".join(
                f"{entry.get('web_name', '?')} ({entry.get('price', 0.0)}m)"
                for entry in locked
            )
            lines.append(t(
                "select_players.locked_line", locale,
                entries=entries, locked_cost=output.get("locked_cost", 0.0),
            ))

        lines.append(t(
            "select_players.selection_cost_line", locale,
            selection_cost=output.get("selection_cost", 0.0), budget=output.get("budget", 0.0),
            remaining=output.get("remaining", 0.0), slots_left=completion.get("slots_left", "?"),
        ))
        if completion.get("exists"):
            lines.append(t(
                "select_players.fits_line", locale,
                cheapest_fill_cost=completion.get("cheapest_fill_cost", 0.0),
                witness_total_cost=completion.get("witness_total_cost", 0.0),
            ))
            clubs = completion.get("witness_club_counts") or {}
            if clubs:
                entries = ", ".join(f"{club} {count}" for club, count in clubs.items())
                lines.append(t("select_players.clubs_line", locale, entries=entries))
        for warning in output.get("warnings", []):
            lines.append(t("select_players.warning_line", locale, warning=warning))
        return "\n".join(lines)

    if status == "infeasible":
        lines = [output.get("message", t("select_players.infeasible_fallback", locale))]
        affordable = output.get("affordable") or {}
        best = affordable.get("best_by_objective") or {}
        for entry in best.get("players", []):
            lines.append(t(
                "select_players.fits_entry_line", locale,
                name=entry.get("web_name", "?"), team=entry.get("team_short", "?"),
                price=entry.get("price", 0.0),
            ))
        return "\n".join(lines)

    if status == "ambiguous":
        candidates = ", ".join(
            str(candidate.get("web_name", "?")) for candidate in output.get("candidates", [])
        )
        message = output.get("message", t("select_players.ambiguous_fallback", locale))
        return (
            t("select_players.ambiguous_candidates_suffix", locale, message=message, candidates=candidates)
            if candidates else message
        )

    if status == "not_found":
        return output.get("message", t("select_players.not_found_fallback", locale))

    if status == "invalid_argument":
        return output.get("message", t("select_players.invalid_argument_fallback", locale))

    code    = output.get("code", "error")
    message = output.get("message", t("select_players.error_fallback", locale))
    return f"Error ({code}): {message}"


# ---------------------------------------------------------------------------
# Dispatch table and public API
# ---------------------------------------------------------------------------

def _render_expected_minutes_v2(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    from .football_intelligence_renderer import render_expected_minutes
    return render_expected_minutes(output)


def _render_tactical_role_v2(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    from .football_intelligence_renderer import render_tactical_role
    return render_tactical_role(output)


def _render_fixture_context_v2(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    from .football_intelligence_renderer import render_fixture_context
    return render_fixture_context(output)


def _render_player_intelligence_v2(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    del locale  # F1 commit 1: mechanical signature only, not yet honored.
    from .football_intelligence_renderer import render_player_intelligence
    return render_player_intelligence(output)

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
    "get_player_season_points":     _render_get_player_season_points,
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
    "get_my_squad":             _render_get_my_squad,            # i39
    "web_fetch":                _render_web_fetch,               # P2.7
    "rank_players_by_metric":   _render_rank_players_by_metric,  # P2.8
    "build_squad":              _render_build_squad,             # S1
    "select_players_within_budget": _render_select_players,      # S2
    "search_web":               _render_search_web,              # web search parity
    # T-zonal atomic tools
    "get_zonal_weakness":       _render_get_zonal_weakness,      # T-zonal
    "get_zonal_opportunity":    _render_get_zonal_opportunity,   # T-zonal
    "get_player_zonal_outlook": _render_get_player_zonal_outlook,  # T-player
    "get_fixture_outlook":      _render_get_fixture_outlook,     # Track D / FI2
    "get_expected_minutes":     _render_expected_minutes_v2,     # FI-7b3
    "get_tactical_role":        _render_tactical_role_v2,        # FI-7b3
    "get_fixture_context":      _render_fixture_context_v2,      # FI-7b3
    "get_player_intelligence":  _render_player_intelligence_v2,  # FI-7b3
}


def render(tool_name: str, raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
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
    locale:
        Language-track F1: forwarded to every sub-renderer, all 38 of which
        now share this signature. Renderers outside F1's scoped set still
        ignore it (``del locale``) and produce their historical text
        regardless of *locale* — see the F1 report for exactly which five
        renderers honor it.

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

    return renderer(raw_output, locale)


# ---------------------------------------------------------------------------
# Phase 2i: Tier and set-piece display helpers
# ---------------------------------------------------------------------------
# _TIER_LABEL / _SET_PIECE_LABEL below are the domain-vocabulary tables: they
# enumerate the valid codes and their canonical English text, and stay
# English-only -- _tier_display/_tier_short/_set_piece_clause route through
# the catalogue for the actual localized text (F2). _SET_PIECE_SHORT used to
# sit here too but was dead: nothing in this module ever called it (the live
# "· {clause}" suffix has always used the full label via _SET_PIECE_LABEL,
# despite _set_piece_suffix's stale docstring claiming "· pen" -- see the F2
# report). Deleted rather than translated, same as _STATUS_DISPLAY.

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

_TIER_LABEL_KEYS = {
    "safe":            "tier_label.safe",
    "upside":          "tier_label.upside",
    "differential":    "tier_label.differential",
    "avoid":           "tier_label.avoid",
    "low_confidence":  "tier_label.low_confidence",
}

_TIER_SHORT_KEYS = {
    "safe":            "tier_short.safe",
    "upside":          "tier_short.upside",
    "differential":    "tier_short.differential",
    "avoid":           "tier_short.avoid",
    "low_confidence":  "tier_short.low_confidence",
}

_SET_PIECE_LABEL_KEYS = {
    "penalty_taker_1":   "set_piece_label.penalty_taker_1",
    "penalty_taker_2":   "set_piece_label.penalty_taker_2",
    "freekick_taker_1":  "set_piece_label.freekick_taker_1",
    "freekick_taker_2":  "set_piece_label.freekick_taker_2",
}


def _tier_display(tier: str, locale: Locale = DEFAULT_LOCALE) -> str:
    """Return full tier label for display, localized. Unmapped tier codes
    fall back to the raw token (same shape as _localized_difficulty_label).
    """
    key = _TIER_LABEL_KEYS.get(tier)
    if key is None:
        return _TIER_LABEL.get(tier, tier)
    return t(key, locale)


def _tier_short(tier: str, locale: Locale = DEFAULT_LOCALE) -> str:
    """Return short tier label for bracket display, localized."""
    key = _TIER_SHORT_KEYS.get(tier)
    if key is None:
        return _TIER_SHORT.get(tier, tier)
    return t(key, locale)


def _set_piece_clause(role_signals: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Build a descriptive clause from role_signals set-piece notes.

    Returns empty string if no set-piece notes are present.

    Examples:
        ""                            # no set-piece roles
        "penalty taker"               # single role
        "penalty taker, free-kick taker"    # multiple roles
    """
    notes = role_signals.get("set_piece_notes", [])
    if not notes:
        return ""

    labels = []
    for note in notes:
        key = _SET_PIECE_LABEL_KEYS.get(note)
        labels.append(t(key, locale) if key is not None else _SET_PIECE_LABEL.get(note, note))
    return ", ".join(labels)


def _set_piece_suffix(role_signals: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    """Build a brief suffix from role_signals set-piece notes.

    Returns empty string if no set-piece notes are present.

    Examples:
        ""                  # no set-piece roles
        "· penalty taker"   # single role
        "· penalty taker, free-kick taker"  # multiple roles
    """
    clause = _set_piece_clause(role_signals, locale)
    if not clause:
        return ""
    return f"· {clause}"
