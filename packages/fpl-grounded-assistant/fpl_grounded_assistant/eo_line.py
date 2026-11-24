"""The one line under a deterministic EO card: what to cover and what is the user's own differential.

Built from the card's own groups (the tool output the card is built from), names only and no numbers, with
positive wording. No model wrote it. A row flagged ``availability == "out"`` is skipped in BOTH groups (an out player is
neither cover nor a differential), a ``"doubtful"`` one is skipped when a fit row follows; a missing field means "fit".
"""
from __future__ import annotations

from typing import Any

from .catalogue import t
from .locale_types import DEFAULT_LOCALE, Locale


def _first_name(items: Any) -> str | None:
    """The first row's name that is not out; a doubtful row is passed over when a fit one follows."""
    named = [i for i in items or [] if isinstance(i, dict) and i.get("player") and i.get("availability") != "out"]
    fit = [i for i in named if i.get("availability") != "doubtful"]
    pick = (fit or named)[:1]
    return str(pick[0]["player"]) if pick else None


def eo_one_line(raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str | None:
    """"Cover X; your differential: Y." (either part left out when its group has nobody), or ``None`` when neither
    group has a usable first row (the caller keeps its generic "Ready" line)."""
    if not raw_output.get("squad_compared"):
        return None
    cover = _first_name(raw_output.get("group_has"))
    diff = _first_name(raw_output.get("differentials"))
    if cover and diff:
        return t("eo_line.both", locale, cover=cover, diff=diff)
    if cover:
        return t("eo_line.cover", locale, cover=cover)
    if diff:
        return t("eo_line.diff", locale, diff=diff)
    return None
