"""The cups' own look-ahead: long, configurable, and never able to take the PL fixtures down with it."""
from __future__ import annotations

import pytest

from licensed_ingestion import fetch, recording
from licensed_ingestion.run import run_pass
from sportmonks_client.transport import TransportResponse

from test_passes import Spy, _client

ARS_LONG = f"fixtures/between/2026-10-24/2027-06-20/{recording.ARS}"
ARS_120 = f"fixtures/between/2026-10-24/2027-02-20/{recording.ARS}"
ARS_14 = f"fixtures/between/2026-10-24/2026-11-06/{recording.ARS}"
PL_WINDOWS = ["fixtures/between/2026-10-24/2026-11-06", "fixtures/between/2026-10-17/2026-10-23"]


class Refusing(Spy):
    """The recording, except that these paths are refused with a 422 (the provider rejecting the window)."""

    def __init__(self, refused: set[str]) -> None:
        super().__init__(lenient=True)
        self.refused = refused

    def request(self, method, url, *, params, timeout):
        path = url.split("/v3/football/", 1)[-1]
        if path in self.refused:
            self.paths.append(path)
            return TransportResponse(422, {}, {"message": "window refused"})
        return super().request(method, url, params=params, timeout=timeout)


def _daily(tmp_path, spy):
    client, transport = _client(spy)
    build, summary = run_pass("daily", client, recording.FEED, tmp_path, now=recording.NOW, previous=None)
    return summary, transport


@pytest.fixture(autouse=True)
def _default_window(monkeypatch):
    monkeypatch.delenv(fetch.ENV_CUP_WINDOW, raising=False)


def test_a_cup_tie_more_than_14_days_ahead_is_kept_and_nothing_else_moves(tmp_path):
    spy = Spy()
    summary, transport = _daily(tmp_path, spy)
    # 14 days saw one Carabao tie (and dropped the UCL one); the December tie only exists in the long window.
    assert summary["derive"]["cup_fixtures_kept"] == 2 and summary["derive"]["other_competitions_dropped"] == 1
    assert summary["cup_window"] == {"days": 240, "clubs": 2, "fell_back": {}}
    assert ARS_LONG in spy.paths and ARS_14 not in spy.paths
    assert spy.paths[-2:] == PL_WINDOWS  # PL fixtures and lineups still read over their own 14-day windows
    assert transport.calls == fetch.planned_count("daily", clubs=2) == 10  # same number of calls as before


def test_the_most_a_daily_pass_can_cost_with_one_extra_page_per_club_is_84():
    assert fetch.planned_count("daily") == 64 and fetch.planned_count("daily") + 20 == 84 < 120


def test_a_refused_long_window_retries_that_club_with_120_days_and_keeps_the_rest(tmp_path):
    spy = Refusing({ARS_LONG})
    summary, _ = _daily(tmp_path, spy)
    assert summary["cup_window"] == {"days": 240, "clubs": 2, "fell_back": {"ARS": 120}}
    assert ARS_120 in spy.paths and spy.paths[-2:] == PL_WINDOWS
    assert summary["rows"]["lineup_slots"] > 0


def test_a_second_refusal_falls_to_the_14_days_the_pass_always_used(tmp_path):
    spy = Refusing({ARS_LONG, ARS_120})
    summary, _ = _daily(tmp_path, spy)
    assert summary["cup_window"]["fell_back"] == {"ARS": 14}
    assert ARS_14 in spy.paths and spy.paths[-2:] == PL_WINDOWS


def test_a_refusal_of_the_last_window_is_not_swallowed(tmp_path):
    from sportmonks_client.errors import SportmonksRequestError
    spy = Refusing({ARS_LONG, ARS_120, ARS_14})
    client, _ = _client(spy)
    with pytest.raises(SportmonksRequestError):
        fetch.daily(client, recording.NOW.date())


@pytest.mark.parametrize("value,expected", [
    (None, 240), ("", 240), ("abc", 240), ("12.5", 240), ("13", 240), ("331", 240), ("-5", 240), ("0", 240),
    ("14", 14), ("120", 120), ("330", 330), (" 90 ", 90),
])
def test_cup_window_days_is_validated(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv(fetch.ENV_CUP_WINDOW, value)
    assert fetch.cup_window_days() == expected


def test_the_variable_changes_the_window_without_a_code_change(monkeypatch, tmp_path):
    monkeypatch.setenv(fetch.ENV_CUP_WINDOW, "120")
    spy = Spy(lenient=True)
    summary, _ = _daily(tmp_path, spy)
    assert ARS_120 in spy.paths and ARS_LONG not in spy.paths
    assert summary["cup_window"]["days"] == 120
