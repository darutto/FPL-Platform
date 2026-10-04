"""
fpl_grounded_assistant.chip_availability
========================================
Is the user's chip still playable in the gameweek being asked about? Decided
ONCE, here, and read by both places that need it:

* ``chip_advisor.get_chip_advice`` (i144) -- puts the decision in the tool
  output (``chip_availability``) so the model writes its read KNOWING the chip
  is spent and comes back later, instead of advising to "keep it";
* ``final_response._apply_squad_overrides`` (i137/i140) -- the hard block and
  the «Ya usaste el … en la GWn. Vuelves a tenerlo desde la GWm.» lead.

FPL 2026-27 gives every chip one use per window (GW1/2-19, GW20-38), read off
``bootstrap["chips"]``. The user's uses come from ``squad_context.chips_used``
(the UI's projection of their FPL history). When either is missing the
decision falls back to the UI's ``chips_remaining`` and logs why; with no
squad context at all it is ``unknown`` -- never "available" by default.

Moved verbatim from final_response (i137/i140); the private names there are
kept as aliases.
"""
from __future__ import annotations

import logging
from typing import Any

#: The bootstrap's chip codes for each backend chip name (chip_advisor's map).
CHIP_API_NAME: dict[str, str] = {
    "triple_captain": "3xc", "wildcard": "wildcard", "bench_boost": "bboost", "free_hit": "freehit",
}

STATUS_AVAILABLE = "available"
STATUS_USED = "used"
STATUS_UNKNOWN = "unknown"

_LOG = logging.getLogger(__name__)


def chip_used_gw(chip_name: str, chips_used: Any) -> "int | None":
    """The latest gameweek the user played *chip_name*, from squad_context.chips_used.

    ``chips_used`` is ``[{"chip": "triple_captain", "event": 3}, ...]``.
    Anything malformed or absent reads as unknown -- never guessed.
    """
    if not isinstance(chips_used, list):
        return None
    events = []
    for entry in chips_used:
        if not isinstance(entry, dict) or entry.get("chip") != chip_name:
            continue
        try:
            event = int(entry.get("event"))
        except (TypeError, ValueError):
            continue
        if 1 <= event <= 38:
            events.append(event)
    return max(events) if events else None


def chip_windows(chip_name: str, bootstrap: "dict[str, Any] | None") -> "list[tuple[int, int]] | None":
    """FPL's own windows for *chip_name*, ``[(start_event, stop_event), ...]``.

    Read off ``bootstrap["chips"]``. ``None`` when absent, empty or any entry
    for this chip is malformed -- a partial list is not trusted.
    """
    raw = (bootstrap or {}).get("chips")
    api_name = CHIP_API_NAME.get(chip_name)
    if not isinstance(raw, list) or api_name is None:
        return None
    windows = []
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("name") != api_name:
            continue
        try:
            windows.append((int(entry["start_event"]), int(entry["stop_event"])))
        except (KeyError, TypeError, ValueError):
            return None
    return windows or None


def chip_return_gw(chip_name: str, used_gw: int, bootstrap: "dict[str, Any] | None") -> "int | None":
    """Start of the chip's next window after the one *used_gw* falls in.

    ``None`` when the windows are absent or malformed, or the used window is
    the last.
    """
    windows = chip_windows(chip_name, bootstrap)
    if windows is None:
        return None
    used_window = next(((s, t) for s, t in windows if s <= used_gw <= t), None)
    if used_window is None:
        return None
    later = sorted(s for s, _ in windows if s > used_window[1])
    return later[0] if later else None


def target_gw(gw: Any, bootstrap: "dict[str, Any] | None") -> "int | None":
    """The gameweek the chip would be played in.

    The advice's own evaluated *gw* (what the user asked about), else FPL's
    next gameweek, else its current one. ``None`` when none is known.
    """
    try:
        value = int(gw) if gw is not None else None
    except (TypeError, ValueError):
        value = None
    if value is not None and 1 <= value <= 38:
        return value
    events = (bootstrap or {}).get("events")
    if isinstance(events, list):
        for flag in ("is_next", "is_current"):
            for ev in events:
                if isinstance(ev, dict) and ev.get(flag):
                    try:
                        return int(ev["id"])
                    except (KeyError, TypeError, ValueError):
                        return None
    return None


def chip_window_availability(
    chip_name: str,
    squad_context: "dict[str, Any]",
    bootstrap: "dict[str, Any] | None",
    target: "int | None",
) -> "tuple[bool | None, int | None, str | None]":
    """i140: is the chip still playable in the window that holds *target*?

    Returns ``(available, used_gw_in_window, fallback_reason)``.
    ``available is None`` means "cannot decide by window" and the reason says why.
    """
    chips_used = squad_context.get("chips_used")
    if not isinstance(chips_used, list):
        return None, None, "no_chips_used"
    windows = chip_windows(chip_name, bootstrap)
    if windows is None:
        return None, None, "no_windows"
    if target is None:
        return None, None, "no_target_gw"
    window = next(((s, t) for s, t in windows if s <= target <= t), None)
    if window is None:
        return None, None, "target_outside_windows"
    uses = []
    for entry in chips_used:
        if not isinstance(entry, dict) or entry.get("chip") != chip_name:
            continue
        try:
            event = int(entry.get("event"))
        except (TypeError, ValueError):
            event = 0
        if not 1 <= event <= 38:
            # A use of THIS chip whose gameweek is unreadable: cannot say
            # which window it spent, so do not decide -- fall back.
            return None, None, "malformed_chips_used"
        if window[0] <= event <= window[1]:
            uses.append(event)
    if uses:
        return False, max(uses), None
    return True, None, None


def decide_chip_availability(
    chip_name: str,
    squad_context: "dict[str, Any] | None",
    bootstrap: "dict[str, Any] | None",
    gw: Any,
) -> dict[str, Any]:
    """The one decision both the tool and the response layer use.

    Returns ``{"status": "available"|"used"|"unknown", "used_gw", "returns_gw",
    "decided_by": "window"|"chips_remaining"|None}``. ``used_gw`` is the use
    inside the target window when decided by window, else the latest use.
    """
    squad = squad_context or {}
    # No squad context at all reads as unknown below: no chips_used for the
    # window rule and no chips_remaining to fall back on.
    out: dict[str, Any] = {"status": STATUS_UNKNOWN, "used_gw": None, "returns_gw": None,
                           "decided_by": None}
    available, used_in_window, fallback = chip_window_availability(
        chip_name, squad, bootstrap, target_gw(gw, bootstrap),
    )
    if available is not None:
        out["decided_by"] = "window"
    else:
        remaining = squad.get("chips_remaining")
        if remaining is None:
            return out
        _LOG.info("chip_availability_fallback chip=%s reason=%s", chip_name, fallback)
        available = chip_name in remaining
        out["decided_by"] = "chips_remaining"
    if available:
        out["status"] = STATUS_AVAILABLE
        return out
    out["status"] = STATUS_USED
    out["used_gw"] = used_in_window if used_in_window is not None else chip_used_gw(
        chip_name, squad.get("chips_used"))
    if out["used_gw"] is not None:
        out["returns_gw"] = chip_return_gw(chip_name, out["used_gw"], bootstrap)
    return out
