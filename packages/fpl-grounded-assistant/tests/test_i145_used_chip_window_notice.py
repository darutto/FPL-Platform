"""i145 -- a used chip's window fields describe its NEXT window, never the spent one.

After i144 (prod replay, Wildcard played in GW5, asked in GW6) the bodies still
reasoned «quedan 14 jornadas…» -- the tool's ``window_notice`` for the window
already spent -- and one mixed windows («para cuando regrese, la ventana actual
sigue abierta hasta la GW19»). When ``chip_availability`` is ``used`` the
window fields now speak of the next window (FPL's own), or say there is none.
Available / unknown chips are unchanged. No network.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest

from fpl_grounded_assistant.chip_advisor import CHIP_ADVICE_SPEC, get_chip_advice

#: current GW in the conftest bootstrap is 28.
WINDOWS_WITH_NEXT = [{"name": "bboost", "start_event": 1, "stop_event": 28},
                     {"name": "bboost", "start_event": 29, "stop_event": 38}]
WINDOWS_LIVE = [{"name": "bboost", "start_event": 1, "stop_event": 19},
                {"name": "bboost", "start_event": 20, "stop_event": 38}]
SPENT_WINDOW_TELLS = ("gameweek(s) remain", "Active chip window: GW1-GW28", "Active chip window: GW20-GW38")


def _bs(bootstrap, windows, used=None) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
    bs["chips"] = windows
    if used is not None:
        bs["_squad_context"] = {"chips_used": used}
    return bs


def test_used_with_a_next_window_speaks_of_it(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_WITH_NEXT, used=[{"chip": "bench_boost", "event": 25}]))
    assert out["chip_availability"]["status"] == "used"
    assert out["window_status"] == "spent"
    assert out["active_window"] == {"start_event": 29, "stop_event": 38}
    assert out["gameweeks_remaining"] is None
    assert out["window_notice"] == "This chip's next window: GW29-GW38."
    assert "This chip's next window: GW29-GW38." in out["advice_text"]
    assert not any(t in out["advice_text"] for t in SPENT_WINDOW_TELLS)


def test_used_in_the_last_window_says_there_is_none(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_LIVE, used=[{"chip": "bench_boost", "event": 22}]))
    assert out["window_status"] == "spent"
    assert out["active_window"] is None and out["gameweeks_remaining"] is None
    assert out["window_notice"] == "There is no later window for this chip this season."
    assert not any(t in out["advice_text"] for t in SPENT_WINDOW_TELLS)


def test_available_chip_keeps_its_active_window(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_LIVE, used=[{"chip": "bench_boost", "event": 2}]))
    assert out["chip_availability"]["status"] == "available"
    assert out["window_status"] == "active"
    assert out["active_window"] == {"start_event": 20, "stop_event": 38}
    assert out["gameweeks_remaining"] == 11            # GW28..GW38
    assert "Active chip window: GW20-GW38; 11 gameweek(s) remain including GW28." in out["advice_text"]


def test_unknown_chip_keeps_its_active_window(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_LIVE))
    assert out["chip_availability"]["status"] == "unknown"
    assert out["window_status"] == "active" and out["gameweeks_remaining"] == 11


def test_spent_is_declared():
    enum = CHIP_ADVICE_SPEC.output_schema["properties"]["window_status"]["enum"]
    assert "spent" in enum
