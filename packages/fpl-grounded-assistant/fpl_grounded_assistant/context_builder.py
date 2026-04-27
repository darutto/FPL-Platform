"""
fpl_grounded_assistant.context_builder
=======================================
Phase 9a: Orchestrator context builder.

Converts the FPL bootstrap dict into a concise, LLM-readable plain-text
summary that serves as the data context injected into the orchestrator's
system prompt.

This is the "CSV equivalent" described in the orchestration plan: the LLM
receives real FPL facts and can reason freely over them, while still being
able to call grounded tools for computed values (captain scores, comparisons,
chip advice, etc.).

Design principles
-----------------
* Pure function — no side effects, no network calls, no LLM calls.
* All data derived from the bootstrap — no hallucination source.
* Concise output — fits within a system prompt without consuming excessive tokens.
* Degrades gracefully — every section is wrapped defensively; a broken section
  does not prevent the rest from rendering.

Public API
----------
build_orchestration_context(bootstrap: dict) -> str
    Returns a plain-text data summary ready to embed in a system prompt.

build_orchestration_context_dict(bootstrap: dict) -> dict
    Returns the same data as a structured dict, suitable for testing and
    inspection without parsing the string output.

Both functions accept the same bootstrap dict produced by
``fpl_pipeline.assemble_captain_context()`` (which injects
``fixture_difficulty_map`` and ``team_fixtures``).  They also accept a raw
bootstrap dict without those injected fields — missing fields produce
abbreviated output rather than errors.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POSITION_LABELS: dict[int, str] = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}

_STATUS_LABELS: dict[str, str] = {
    "a": "available",
    "d": "doubt",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "not in squad",
}

_SEASON_PHASES: tuple[tuple[int, int, str], ...] = (
    (1,  6,  "early season (GW 1-6)"),
    (7,  28, "mid-season (GW 7-28)"),
    (29, 38, "late season (GW 29-38)"),
)

# Players shown in the top-candidates table
_TOP_N_CANDIDATES: int = 10

# GWs shown in the fixture schedule
_FIXTURE_HORIZON: int = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_current_gw(bootstrap: dict[str, Any]) -> int | None:
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            gw = event.get("id")
            return int(gw) if gw is not None else None
    return None


def _get_next_gw(bootstrap: dict[str, Any]) -> int | None:
    for event in bootstrap.get("events", []):
        if event.get("is_next"):
            gw = event.get("id")
            return int(gw) if gw is not None else None
    return None


def _season_phase(gw: int) -> str:
    for lo, hi, label in _SEASON_PHASES:
        if lo <= gw <= hi:
            return label
    return f"GW {gw}"


def _team_lookup(bootstrap: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Return {team_id: team_dict} for fast lookups."""
    return {int(t["id"]): t for t in bootstrap.get("teams", []) if "id" in t}


def _position_label(element_type: int | None) -> str:
    return _POSITION_LABELS.get(element_type or 0, "?")


def _status_label(status: str | None, chance: int | None = None) -> str:
    label = _STATUS_LABELS.get(status or "", status or "?")
    if status == "d" and chance is not None:
        label = f"doubt ({chance}% fit)"
    return label


def _fmt_cost(now_cost: int | None) -> str:
    if now_cost is None:
        return "?"
    return f"{now_cost / 10:.1f}m"


def _fmt_ownership(selected_by_percent: str | float | None) -> str:
    if selected_by_percent is None:
        return "?%"
    try:
        return f"{float(selected_by_percent):.1f}%"
    except (ValueError, TypeError):
        return str(selected_by_percent) + "%"


def _fmt_form(form: str | float | None) -> str:
    if form is None:
        return "?"
    try:
        return f"{float(form):.1f}"
    except (ValueError, TypeError):
        return str(form)


# ---------------------------------------------------------------------------
# Section builders — each returns (title, body_str, data_dict)
# ---------------------------------------------------------------------------

def _build_gameweek_section(
    bootstrap: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Current GW, next GW, season phase."""
    current_gw = _get_current_gw(bootstrap)
    next_gw = _get_next_gw(bootstrap)

    lines: list[str] = []
    data: dict[str, Any] = {
        "current_gw": current_gw,
        "next_gw": next_gw,
        "season_phase": None,
    }

    if current_gw is not None:
        phase = _season_phase(current_gw)
        data["season_phase"] = phase
        lines.append(f"Current Gameweek : GW{current_gw}")
        lines.append(f"Season Phase     : {phase}")
    else:
        lines.append("Current Gameweek : unknown")

    if next_gw is not None:
        lines.append(f"Next Gameweek    : GW{next_gw}")

    return "GAMEWEEK", "\n".join(lines), data


def _build_gw_type_section(
    bootstrap: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """DGW / BGW / normal detection for current GW."""
    try:
        from .chip_advisor import _classify_gameweek_type  # noqa: PLC0415
        gw_type, dgw_teams, dgw_count, bgw_teams, bgw_count = (
            _classify_gameweek_type(bootstrap)
        )
    except Exception:  # noqa: BLE001
        return "GAMEWEEK TYPE", "unknown (data unavailable)", {
            "gw_type": "unknown", "dgw_teams": [], "bgw_teams": []
        }

    data: dict[str, Any] = {
        "gw_type": gw_type,
        "dgw_teams": dgw_teams,
        "dgw_count": dgw_count,
        "bgw_teams": bgw_teams,
        "bgw_count": bgw_count,
    }

    if gw_type == "normal":
        line = "normal (all teams play once)"
    elif gw_type == "double":
        teams_str = ", ".join(dgw_teams) if dgw_teams else "unknown"
        line = f"DOUBLE GAMEWEEK — {dgw_count} team(s) play twice: {teams_str}"
    elif gw_type == "blank":
        teams_str = ", ".join(bgw_teams) if bgw_teams else "unknown"
        line = f"BLANK GAMEWEEK — {bgw_count} team(s) have no fixture: {teams_str}"
    elif gw_type == "mixed":
        dgw_str = ", ".join(dgw_teams) if dgw_teams else "unknown"
        bgw_str = ", ".join(bgw_teams) if bgw_teams else "unknown"
        line = (
            f"MIXED GAMEWEEK — {dgw_count} team(s) play twice ({dgw_str}); "
            f"{bgw_count} team(s) have no fixture ({bgw_str})"
        )
    else:
        line = "unknown"

    return "GAMEWEEK TYPE", line, data


def _build_players_section(
    bootstrap: dict[str, Any],
    top_n: int = _TOP_N_CANDIDATES,
) -> tuple[str, str, dict[str, Any]]:
    """
    Two sub-tables:
    1. Top candidates by form (scored MID/FWD/DEF/GKP, available, sorted by form desc)
    2. Full player list (all elements, compact one-line each)
    """
    teams = _team_lookup(bootstrap)
    fdr_map: dict[int, int] = bootstrap.get("fixture_difficulty_map", {})

    elements = bootstrap.get("elements", [])
    all_players: list[dict[str, Any]] = []

    for el in elements:
        team_id = el.get("team")
        team = teams.get(int(team_id), {}) if team_id is not None else {}
        element_type = el.get("element_type")
        status = el.get("status", "?")
        form_raw = el.get("form", "0")
        try:
            form_val = float(form_raw or 0)
        except (ValueError, TypeError):
            form_val = 0.0

        fdr = fdr_map.get(int(team_id), None) if team_id is not None else None

        all_players.append({
            "id":           el.get("id"),
            "web_name":     el.get("web_name", "Unknown"),
            "team_short":   team.get("short_name", "?"),
            "position":     _position_label(element_type),
            "element_type": element_type,
            "status":       status,
            "form":         form_val,
            "now_cost":     el.get("now_cost"),
            "ownership":    el.get("selected_by_percent"),
            "fdr":          fdr,
            "chance":       el.get("chance_of_playing_this_round"),
        })

    # Top candidates: MID/FWD available or doubt, sorted by form desc
    attackers = [
        p for p in all_players
        if p["element_type"] in (3, 4) and p["status"] in ("a", "d")
    ]
    attackers_sorted = sorted(attackers, key=lambda p: p["form"], reverse=True)[:top_n]

    header = f"{'#':<3} {'Name':<12} {'Team':>4}  {'Pos':>3}  {'Form':>5}  {'FDR':>3}  {'Own':>6}  {'Status'}"
    sep = "-" * 65
    candidate_lines: list[str] = [header, sep]
    for rank, p in enumerate(attackers_sorted, 1):
        fdr_str = str(p["fdr"]) if p["fdr"] is not None else "?"
        line = (
            f"{rank:<3} {p['web_name']:<12} {p['team_short']:>4}  "
            f"{p['position']:>3}  {p['form']:>5.1f}  {fdr_str:>3}  "
            f"{_fmt_ownership(p['ownership']):>6}  {_status_label(p['status'], p['chance'])}"
        )
        candidate_lines.append(line)

    # Full player compact list (all, including injured/unavailable)
    all_sorted = sorted(all_players, key=lambda p: p["form"], reverse=True)
    compact_lines: list[str] = []
    for p in all_sorted:
        fdr_str = str(p["fdr"]) if p["fdr"] is not None else "?"
        compact_lines.append(
            f"  {p['web_name']} ({p['team_short']}, {p['position']}, "
            f"{_fmt_cost(p['now_cost'])}, "
            f"own: {_fmt_ownership(p['ownership'])}, "
            f"form: {_fmt_form(p['form'])}, "
            f"FDR: {fdr_str}, "
            f"status: {_status_label(p['status'], p['chance'])})"
        )

    body = (
        f"Top {len(attackers_sorted)} captain candidates (MID/FWD by form, available/doubt):\n"
        + "\n".join(candidate_lines)
        + "\n\nAll players:\n"
        + "\n".join(compact_lines)
    )

    return "PLAYERS", body, {
        "top_candidates": [
            {
                "rank":      i + 1,
                "web_name":  p["web_name"],
                "team_short": p["team_short"],
                "position":  p["position"],
                "form":      p["form"],
                "fdr":       p["fdr"],
                "ownership": p["ownership"],
                "status":    p["status"],
            }
            for i, p in enumerate(attackers_sorted)
        ],
        "all_players": [
            {
                "web_name":  p["web_name"],
                "team_short": p["team_short"],
                "position":  p["position"],
                "form":      p["form"],
                "cost":      p["now_cost"],
                "ownership": p["ownership"],
                "status":    p["status"],
                "fdr":       p["fdr"],
            }
            for p in all_sorted
        ],
    }


def _build_chip_signals_section(
    bootstrap: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """
    High-level chip signals derived from bootstrap — not a replacement for
    get_chip_advice() but a quick overview so the LLM knows what data exists.
    """
    try:
        from .chip_advisor import (  # noqa: PLC0415
            _advise_triple_captain,
            _advise_bench_boost,
            _classify_gameweek_type,
            _get_current_gameweek,
        )
    except Exception:  # noqa: BLE001
        return "CHIP SIGNALS", "(unavailable)", {}

    lines: list[str] = []
    data: dict[str, Any] = {}
    current_gw = _get_current_gameweek(bootstrap)

    # Triple Captain
    try:
        tc = _advise_triple_captain(bootstrap)
        signals = tc.get("signals", {})
        top_score = signals.get("top_captain_score", "?")
        top_name = signals.get("top_player", "?")
        top_tier = signals.get("top_tier", "?")
        rec = tc.get("recommendation", "?")
        lines.append(
            f"Triple Captain : top score = {top_score} ({top_name}, {top_tier} tier)"
            f"  ->  {rec}"
        )
        data["triple_captain"] = {"recommendation": rec, "top_score": top_score, "top_player": top_name}
    except Exception:  # noqa: BLE001
        lines.append("Triple Captain : (unavailable)")
        data["triple_captain"] = None

    # Bench Boost
    try:
        bb = _advise_bench_boost(bootstrap)
        signals = bb.get("signals", {})
        avg_fdr = signals.get("average_fdr_top10", "?")
        rec = bb.get("recommendation", "?")
        lines.append(
            f"Bench Boost    : avg FDR top-10 MID/FWD = {avg_fdr}"
            f"  ->  {rec}"
        )
        data["bench_boost"] = {"recommendation": rec, "avg_fdr": avg_fdr}
    except Exception:  # noqa: BLE001
        lines.append("Bench Boost    : (unavailable)")
        data["bench_boost"] = None

    # Wildcard (timing only)
    try:
        gw = current_gw
        if gw is not None:
            from .chip_advisor import _WC_EARLY_CUTOFF, _WC_LATE_CUTOFF  # noqa: PLC0415
            if gw <= _WC_EARLY_CUTOFF:
                wc_rec = "conditions_unfavorable (too early)"
            elif gw >= _WC_LATE_CUTOFF:
                wc_rec = "conditions_unfavorable (too late)"
            else:
                wc_rec = "conditions_marginal (mid-season window)"
            lines.append(f"Wildcard       : GW{gw}  ->  {wc_rec}")
            data["wildcard"] = {"recommendation": wc_rec, "current_gw": gw}
        else:
            lines.append("Wildcard       : GW unknown")
            data["wildcard"] = None
    except Exception:  # noqa: BLE001
        lines.append("Wildcard       : (unavailable)")
        data["wildcard"] = None

    # Free Hit (DGW/BGW)
    try:
        gw_type, dgw_teams, dgw_count, bgw_teams, bgw_count = (
            _classify_gameweek_type(bootstrap)
        )
        if gw_type == "double":
            fh_rec = f"conditions_favorable (DGW — {dgw_count} teams play twice)"
        elif gw_type == "mixed":
            fh_rec = f"conditions_marginal (mixed — {dgw_count} DGW, {bgw_count} BGW teams)"
        elif gw_type == "blank":
            fh_rec = f"conditions_marginal (BGW — {bgw_count} teams without a fixture)"
        else:
            fh_rec = "conditions_unfavorable (normal GW - save for DGW/BGW)"
        lines.append(f"Free Hit       : {gw_type} gameweek  ->  {fh_rec}")
        data["free_hit"] = {"recommendation": fh_rec, "gw_type": gw_type}
    except Exception:  # noqa: BLE001
        lines.append("Free Hit       : (unavailable)")
        data["free_hit"] = None

    return "CHIP SIGNALS", "\n".join(lines), data


def _build_fixture_schedule_section(
    bootstrap: dict[str, Any],
    horizon: int = _FIXTURE_HORIZON,
) -> tuple[str, str, dict[str, Any]]:
    """Per-team fixture schedule for the next *horizon* GWs."""
    team_fixtures: dict | None = bootstrap.get("team_fixtures")
    teams = _team_lookup(bootstrap)

    if not team_fixtures:
        return "FIXTURE SCHEDULE", "(not available)", {}

    current_gw = _get_current_gw(bootstrap)
    if current_gw is None:
        return "FIXTURE SCHEDULE", "(current GW unknown)", {}

    target_gws = list(range(current_gw, current_gw + horizon))

    lines: list[str] = []
    schedule_data: dict[str, Any] = {}

    for team_id_raw, fixtures in sorted(team_fixtures.items(), key=lambda kv: int(kv[0])):
        team_id = int(team_id_raw)
        team = teams.get(team_id, {})
        short = team.get("short_name", str(team_id))

        gw_entries: list[str] = []
        team_schedule: list[dict[str, Any]] = []
        for gw in target_gws:
            gw_fixtures = [f for f in fixtures if f.get("gameweek") == gw]
            if not gw_fixtures:
                gw_entries.append(f"GW{gw}: -")
                team_schedule.append({"gw": gw, "fixtures": []})
            else:
                fx_parts: list[str] = []
                fx_dicts: list[dict[str, Any]] = []
                for fx in gw_fixtures:
                    opp_id = fx.get("opponent_team")
                    opp = teams.get(int(opp_id), {}) if opp_id is not None else {}
                    opp_short = opp.get("short_name", str(opp_id))
                    venue = "h" if fx.get("is_home") else "a"
                    diff = fx.get("difficulty", "?")
                    fx_parts.append(f"{opp_short}({venue},{diff})")
                    fx_dicts.append({
                        "opponent": opp_short,
                        "is_home": fx.get("is_home"),
                        "difficulty": diff,
                    })
                gw_entries.append(f"GW{gw}: {' + '.join(fx_parts)}")
                team_schedule.append({"gw": gw, "fixtures": fx_dicts})

        lines.append(f"  {short:>3}: {' | '.join(gw_entries)}")
        schedule_data[short] = team_schedule

    return "FIXTURE SCHEDULE (next %d GWs)" % horizon, "\n".join(lines), schedule_data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_orchestration_context_dict(
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Return the orchestration context as a structured dict.

    Suitable for testing and inspection.  All sections are populated with
    native Python types; missing or broken data produces ``None`` values
    rather than raising.

    Parameters
    ----------
    bootstrap:
        FPL bootstrap dict (with or without ``fixture_difficulty_map`` /
        ``team_fixtures`` injected by ``assemble_captain_context()``).

    Returns
    -------
    dict with keys:
        ``gameweek``        — GW info (current_gw, next_gw, season_phase)
        ``gw_type``         — DGW/BGW/normal detection
        ``players``         — top candidates + all players
        ``chip_signals``    — TC/BB/WC/FH signals
        ``fixture_schedule``— per-team schedule for next N GWs
    """
    _, _, gw_data = _build_gameweek_section(bootstrap)
    _, _, gw_type_data = _build_gw_type_section(bootstrap)
    _, _, players_data = _build_players_section(bootstrap)
    _, _, chip_data = _build_chip_signals_section(bootstrap)
    _, _, fixture_data = _build_fixture_schedule_section(bootstrap)

    return {
        "gameweek":         gw_data,
        "gw_type":          gw_type_data,
        "players":          players_data,
        "chip_signals":     chip_data,
        "fixture_schedule": fixture_data,
    }


def build_orchestration_context(
    bootstrap: dict[str, Any],
) -> str:
    """Return a plain-text FPL data summary for use in an LLM system prompt.

    All facts are derived from *bootstrap* — no network calls, no LLM calls.

    Parameters
    ----------
    bootstrap:
        FPL bootstrap dict (with or without ``fixture_difficulty_map`` /
        ``team_fixtures`` injected by ``assemble_captain_context()``).
        Missing fields produce abbreviated output rather than errors.

    Returns
    -------
    str
        A structured plain-text block, typically 30–80 lines, suitable for
        embedding in a system prompt as the factual FPL data context.

    Example output (abridged)
    -------------------------
    ::

        === FPL Data Context ===

        [GAMEWEEK]
        Current Gameweek : GW30
        Season Phase     : mid-season (GW 7–28)
        Next Gameweek    : GW31

        [GAMEWEEK TYPE]
        DOUBLE GAMEWEEK — 2 team(s) play twice: ARS, CHE

        [TOP CAPTAIN CANDIDATES]
        ...

        [CHIP SIGNALS]
        Triple Captain : top score = 82.5 (Salah, safe tier)  →  conditions_favorable
        ...

        [FIXTURE SCHEDULE (next 3 GWs)]
        ...
    """
    sections: list[str] = ["=== FPL Data Context ==="]

    gw_title, gw_body, _ = _build_gameweek_section(bootstrap)
    sections.append(f"\n[{gw_title}]\n{gw_body}")

    gwt_title, gwt_body, _ = _build_gw_type_section(bootstrap)
    sections.append(f"\n[{gwt_title}]\n{gwt_body}")

    pl_title, pl_body, _ = _build_players_section(bootstrap)
    sections.append(f"\n[{pl_title}]\n{pl_body}")

    chip_title, chip_body, _ = _build_chip_signals_section(bootstrap)
    sections.append(f"\n[{chip_title}]\n{chip_body}")

    fx_title, fx_body, _ = _build_fixture_schedule_section(bootstrap)
    sections.append(f"\n[{fx_title}]\n{fx_body}")

    return "\n".join(sections)
