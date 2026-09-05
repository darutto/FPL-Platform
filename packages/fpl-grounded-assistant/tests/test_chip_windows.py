"""Contract tests for bootstrap-driven chip windows."""
from __future__ import annotations

import copy

from fpl_grounded_assistant.chip_advisor import get_chip_advice


def _window(name: str, start: int, stop: int) -> dict:
    return {
        "name": name,
        "start_event": start,
        "stop_event": stop,
    }


def test_triple_captain_exposes_active_window_and_inclusive_remaining(bootstrap):
    bs = copy.deepcopy(bootstrap)
    bs["chips"] = [_window("3xc", 24, 32)]

    result = get_chip_advice("triple_captain", bs)

    assert result["window_status"] == "active"
    assert result["active_window"] == {"start_event": 24, "stop_event": 32}
    assert result["gameweeks_remaining"] == 5
    assert "5 gameweek(s) remain including GW28" in result["advice_text"]


def test_wildcard_gw29_is_not_late_when_active_window_has_time_left(bootstrap):
    bs = copy.deepcopy(bootstrap)
    bs["events"] = [
        {"id": 29, "is_current": True, "is_next": False, "finished": False},
    ]
    bs["chips"] = [_window("wildcard", 20, 38)]

    result = get_chip_advice("wildcard", bs)

    assert result["window_status"] == "active"
    assert result["gameweeks_remaining"] == 10
    assert result["recommendation"] == "conditions_marginal"
    assert "late in the" not in result["advice_text"]


def test_missing_chip_data_degrades_explicitly_without_assumed_window(bootstrap):
    result = get_chip_advice("triple_captain", bootstrap)

    assert result["window_status"] == "unavailable"
    assert result["active_window"] is None
    assert result["gameweeks_remaining"] is None
    assert "expiry could not be determined" in result["advice_text"]


def test_malformed_matching_window_degrades_explicitly(bootstrap):
    bs = copy.deepcopy(bootstrap)
    bs["chips"] = [_window("bboost", 30, 12)]

    result = get_chip_advice("bench_boost", bs)

    assert result["window_status"] == "unavailable"
    assert result["active_window"] is None
    assert result["gameweeks_remaining"] is None


def test_known_but_inactive_window_is_not_reported_as_active(bootstrap):
    bs = copy.deepcopy(bootstrap)
    bs["chips"] = [_window("freehit", 4, 12)]

    result = get_chip_advice("free_hit", bs)

    assert result["window_status"] == "inactive"
    assert result["active_window"] is None
    assert result["gameweeks_remaining"] == 0
