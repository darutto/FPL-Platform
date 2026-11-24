"""EO chip taps without a model.

A tap on «EO cerca de tu puesto», «EO top 10K», «EO en <liga>» or «Cambiar de liga» sends the chip's own text, which
comes from the catalogue templates the chips are built from. Matching is exact, in both languages, and nothing else
matches: a user's own phrasing keeps going to the model. A matched tap runs the same tool the model would (same flags,
same membership checks, same single-flight jobs) and returns the card, the one line and the chips, or the ``pending``
marker while it computes. Anything that is not a clean answer (flag off, no team, an unknown league name, an error)
returns ``None`` and the normal route answers.
"""
from __future__ import annotations

import re
from typing import Any

from .catalogue import t
from .locale_types import DEFAULT_LOCALE, Locale

_LOCALES = ("en", "es")
_MAX_LEN = 200
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] | None = None


def _patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for loc in _LOCALES:
        for kind, key in (("near", "near_eo.title"), ("tier", "tier_eo.title"), ("change", "league_eo.change_chip")):
            out.append((kind, re.compile("^" + re.escape(t(key, loc)) + "$", re.IGNORECASE)))
        source = re.escape(t("league_eo.chip_question", loc, league="QQNAMEQQ")).replace("QQNAMEQQ", "(?P<name>.+?)")
        out.append(("league", re.compile("^" + source + "$", re.IGNORECASE)))
    return tuple(out)


def eo_tap(question: Any) -> dict[str, Any] | None:
    """``{"kind": near|tier|league|change, "league_name"?}`` for a chip's exact text, else ``None``."""
    global _PATTERNS
    if not isinstance(question, str) or not question.strip() or len(question) > _MAX_LEN:
        return None
    if _PATTERNS is None:
        _PATTERNS = _patterns()
    text = " ".join(question.split())
    for kind, pattern in _PATTERNS:
        match = pattern.match(text)
        if match:
            tap: dict[str, Any] = {"kind": kind}
            if kind == "league":
                tap["league_name"] = match.group("name").strip()
            return tap
    return None


def run_eo_tap(tap: dict[str, Any], bootstrap: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> dict[str, Any] | None:
    """Run a matched tap. ``{tool, args, raw, text, card, chips, pending}`` or ``None`` (fall through to the model)."""
    from .atomic_tool_cards import maybe_atomic_tool_card  # noqa: PLC0415
    from .eo_poll import pending_marker  # noqa: PLC0415
    from .harness import _eo_switch_chips, _league_pick_chips  # noqa: PLC0415
    from .league_eo_tool import league_picker  # noqa: PLC0415
    from .tool_dispatch import run_tool  # noqa: PLC0415

    kind = tap["kind"]
    if kind == "change":
        tool, args = "get_league_eo", {}
        raw = league_picker(bootstrap)
        if raw is None:
            return None
    else:
        tool, args = {"near": ("get_near_rank_eo", {}), "tier": ("get_tier_eo", {}),
                      "league": ("get_league_eo", {"league_name": tap.get("league_name")})}[kind]
        raw = run_tool(tool, args, bootstrap)
    status = raw.get("status")
    if status == "computing":
        marker = pending_marker(tool, raw)
        if marker is None:
            return None  # nothing to poll for: the model words it
        return {"tool": tool, "args": args, "raw": raw, "text": t("eo_tap.computing", locale), "card": None,
                "chips": None, "pending": marker}
    if status != "ok":
        return None
    if raw.get("stage") == "needs_league":
        chips = _league_pick_chips(tool, raw, locale)
        if not chips:
            return None
        return {"tool": tool, "args": args, "raw": raw, "text": t("eo_poll.pick_league", locale), "card": None,
                "chips": chips, "pending": None}
    if raw.get("stage"):
        return None
    card = maybe_atomic_tool_card(tool, raw, None, locale)
    if card is None:
        return None
    from .eo_line import eo_one_line  # noqa: PLC0415

    text = eo_one_line(raw, locale) or t("eo_poll.ready", locale, title=card.title, gw=raw.get("gw"))
    return {"tool": tool, "args": args, "raw": raw, "text": text, "card": card,
            "chips": _eo_switch_chips(tool, raw, locale), "pending": None}
