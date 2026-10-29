"""R1: deterministic wording for ``get_gw_report`` (text renderer and card).

Every figure comes from the tool output (``evidence`` of each story, the
reconciliation block, the player rows); this module only formats it through
the ES/EN catalogue. Nothing here computes a number.
"""
from __future__ import annotations

from typing import Any

from .catalogue import t
from .generic_card import Column, GenericCardMeta, HeroStat, Pill
from .locale_types import DEFAULT_LOCALE, Locale

_CHIP_LABEL = {
    "wildcard": "Wildcard",
    "triple_captain": "Triple Captain",
    "bench_boost": "Bench Boost",
    "free_hit": "Free Hit",
}

_STATUS_KEYS = {
    "no_team_connected": "gw_report.no_team_connected",
    "not_found": "gw_report.team_not_found",
}


def _chip_clause(chip: "str | None", locale: Locale) -> str:
    return t("my_squad.chip_clause", locale, chip_label=_CHIP_LABEL.get(chip or "", chip)) if chip else ""


def _tags(p: dict[str, Any], locale: Locale) -> str:
    out = ""
    if p.get("is_effective_captain"):
        out += t("gw_report.tag_captain", locale, mult=p.get("multiplier", 2))
    elif p.get("is_vice_captain") and p.get("role") != "bench":
        out += t("gw_report.tag_vice", locale)
    if p.get("role") == "autosub_in":
        out += t("gw_report.tag_sub_in", locale)
    elif p.get("role") == "autosub_out":
        out += t("gw_report.tag_sub_out", locale)
    return out


def story_text(story: dict[str, Any], locale: Locale) -> str:
    kind, ev = story.get("kind"), story.get("evidence") or {}
    if kind == "captain_top":
        tied = ev.get("tied_with") or []
        return t(
            "gw_report.story.captain_top", locale,
            captain=ev["captain"], captain_points=ev["captain_points"],
            multiplier=ev["multiplier"], contribution=ev["contribution"],
            tied=t("gw_report.story.captain_top_tied", locale, names=", ".join(tied)) if tied else "",
        )
    if kind == "captain_gap":
        return t(
            "gw_report.story.captain_gap", locale,
            captain=ev["captain"], captain_points=ev["captain_points"],
            multiplier=ev["multiplier"], unit="pt" if ev["captain_points"] == 1 else "pts",
            best=ev["best"], best_points=ev["best_points"],
        )
    if kind == "autosub":
        key = "gw_report.story.autosub_no_fixture" if ev.get("out_team_fixtures") == 0 else "gw_report.story.autosub_not_played"
        return t(
            "gw_report.story.autosub", locale,
            player_in=ev["player_in"], player_out=ev["player_out"], points_in=ev["points_in"],
            reason=t(key, locale, player_out=ev["player_out"]),
        )
    if kind in ("bench_points", "bench_boost"):
        return t(f"gw_report.story.{kind}", locale,
                 bench_points=ev["bench_points"], best=ev["best"], best_points=ev["best_points"])
    if kind == "no_add":
        comparison = (
            t("gw_report.story.no_add_comparison", locale, n=ev["recent_n"], avg=ev["recent_average"])
            if "recent_average" in ev else ""
        )
        return t("gw_report.story.no_add", locale, player=ev["player"], minutes=ev["minutes"],
                 points=ev["points"], comparison=comparison)
    if kind == "minutes_change":
        return t("gw_report.story.minutes_change", locale, player=ev["player"],
                 per_fixture=ev["per_fixture"], avg=ev["recent_average"], n=ev["recent_n"])
    return ""


def _points_line(output: dict[str, Any], locale: Locale) -> str:
    rec = output.get("reconciliation") or {}
    if rec.get("reconciled"):
        cost = rec.get("transfer_cost") or 0
        hit = t("gw_report.points_hit_clause", locale, cost=cost, net=rec.get("net")) if cost else ""
        return t("gw_report.points_ok", locale, gross=rec.get("computed_gross"), hit_clause=hit)
    if rec.get("official_gross") is None:
        return t("gw_report.points_unverified", locale, computed=rec.get("computed_gross"))
    return t("gw_report.points_mismatch", locale, computed=rec.get("computed_gross"),
             official=rec.get("official_gross"), diff=rec.get("difference"))


def render_gw_report(output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str:
    status = output.get("status")
    if status == "ok":
        gw = output.get("gw", "?")
        players = output.get("players") or []
        lines = [
            t("gw_report.header", locale, gw=gw, chip_clause=_chip_clause(output.get("chip"), locale)),
            _points_line(output, locale),
        ]
        if not output.get("data_checked", True):
            lines.append(t("gw_report.provisional_note", locale))
        if output.get("armband_moved") and output.get("captain") and output.get("vice_captain"):
            lines.append(t("gw_report.armband_moved", locale, vice=output["vice_captain"]["web_name"],
                           captain=output["captain"]["web_name"]))

        def line(p: dict[str, Any]) -> str:
            return t("gw_report.player_line", locale, name=p["web_name"], team=p["team_short"], pos=p["position"],
                     points=p["points"], minutes=p["minutes"], tags=_tags(p, locale))

        xi = [p for p in players if p["role"] in ("starter", "autosub_in", "bench_boost")]
        out_of_xi = [p for p in players if p["role"] in ("autosub_out", "bench")]
        lines.append(t("gw_report.xi_header", locale))
        lines.extend(line(p) for p in xi)
        if out_of_xi:
            lines.append(t("gw_report.bench_header", locale))
            lines.extend(line(p) for p in out_of_xi)
        stories = [s for s in (story_text(s, locale) for s in output.get("stories") or []) if s]
        if stories:
            lines.append(t("gw_report.stories_header", locale))
            lines.extend(f"- {s}" for s in stories)
        lines.append(t("gw_report.footer", locale))
        return "\n".join(lines)

    if status == "missing_context":
        reason = (output.get("reason_codes") or [""])[0]
        if reason == "gw_not_finished":
            return t("gw_report.gw_not_finished", locale, gw=output.get("gw", "?"))
        if reason == "no_finished_gameweek":
            return t("gw_report.no_finished_gw", locale)
        return t("gw_report.incomplete", locale, gw=output.get("gw", "?"))
    if status in _STATUS_KEYS:
        return t(_STATUS_KEYS[status], locale)
    if output.get("code") == "invalid_gw":
        return t("gw_report.invalid_gw", locale, min_gw=output.get("min_gw", 1), max_gw=output.get("max_gw", 38))
    return t("gw_report.network_error", locale)


_ROLE_KEY = {
    "starter": "role_xi", "bench_boost": "role_xi", "autosub_in": "role_sub_in",
    "autosub_out": "role_sub_out", "bench": "role_bench",
}


def compose_gw_report_card(raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> "GenericCardMeta | None":
    """Card for an ``ok`` report: hero = points, rows = the 15 picks. ``None`` otherwise (prose stays)."""
    if raw_output.get("status") != "ok" or not raw_output.get("players"):
        return None
    rec = raw_output.get("reconciliation") or {}
    reconciled = bool(rec.get("reconciled"))
    columns = (
        Column(header=t("gcard.gw_report.col_player", locale), align="left", kind="text"),
        Column(header=t("gcard.gw_report.col_role", locale), align="left", kind="text"),
        Column(header=t("gcard.gw_report.col_min", locale), align="right", kind="mono"),
        Column(header=t("gcard.gw_report.col_pts", locale), align="right", kind="mono"),
    )
    rows = []
    for p in raw_output["players"]:
        role = t(f"gcard.gw_report.{_ROLE_KEY.get(p['role'], 'role_xi')}", locale)
        name = p["web_name"]
        if p.get("is_effective_captain"):
            name += " (C)"
        elif p.get("is_vice_captain") and p["role"] != "bench":
            name += " (VC)"
        pts = f"{p['points']}" + (f" ×{p['multiplier']}" if p.get("multiplier", 1) > 1 else "")
        rows.append((name, role, str(p["minutes"]), pts))
    pills = [Pill(
        label=t("gcard.gw_report.pill_reconciled" if reconciled else "gcard.gw_report.pill_unreconciled", locale),
        tone="good" if reconciled else "warn",
    )]
    if raw_output.get("chip"):
        pills.append(Pill(label=_CHIP_LABEL.get(raw_output["chip"], raw_output["chip"]), tone="neutral"))
    if rec.get("transfer_cost"):
        pills.append(Pill(label=t("gcard.gw_report.pill_hit", locale, cost=rec["transfer_cost"]), tone="neutral"))
    if not raw_output.get("data_checked", True):
        pills.append(Pill(label=t("gcard.gw_report.pill_provisional", locale), tone="warn"))
    return GenericCardMeta(
        accent="turquoise",
        title=t("gcard.gw_report.title", locale, gw=raw_output.get("gw", "?")),
        subtitle=t("gcard.gw_report.subtitle", locale),
        hero=HeroStat(
            value=str(rec.get("computed_gross")),
            label=t("gcard.gw_report.hero_ok" if reconciled else "gcard.gw_report.hero_unreconciled", locale),
            tone=None,
        ),
        pills=tuple(pills), columns=columns, rows=tuple(rows),
        footer=t("gw_report.footer", locale),
    )
