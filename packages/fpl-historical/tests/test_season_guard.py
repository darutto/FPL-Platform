"""
tests/test_season_guard.py
===========================
Unit tests for fpl_historical.season_guard (the live-API season-boundary
guard added to prevent recurrence of the 2026-07-27..2026-08-31 incident:
capture() silently wrote 2026-2027 data under the 2025-2026 key every week).

No network calls — bootstrap payloads are hand-built dicts.
"""

from __future__ import annotations

import pytest

from fpl_historical.season_guard import (
    SeasonMismatchError,
    assert_season_matches,
    derive_live_season,
)


def _bootstrap_with_event_one(deadline_time: str | None) -> dict:
    events = []
    if deadline_time is not None:
        events.append({"id": 1, "deadline_time": deadline_time})
    return {"events": events}


# ---------------------------------------------------------------------------
# derive_live_season
# ---------------------------------------------------------------------------

class TestDeriveLiveSeason:

    def test_august_deadline_derives_season_starting_that_year(self):
        bootstrap = _bootstrap_with_event_one("2026-08-14T17:30:00Z")
        assert derive_live_season(bootstrap) == "2026-2027"

    def test_july_deadline_derives_season_starting_that_year(self):
        bootstrap = _bootstrap_with_event_one("2027-07-01T17:30:00Z")
        assert derive_live_season(bootstrap) == "2027-2028"

    def test_january_deadline_derives_season_starting_previous_year(self):
        # A mid-season deadline for event id=1 would be unusual, but the
        # derivation must still resolve to the season straddling that date.
        bootstrap = _bootstrap_with_event_one("2027-01-10T17:30:00Z")
        assert derive_live_season(bootstrap) == "2026-2027"

    def test_no_event_id_1_returns_none(self):
        bootstrap = {"events": [{"id": 2, "deadline_time": "2026-08-21T17:30:00Z"}]}
        assert derive_live_season(bootstrap) is None

    def test_no_events_key_returns_none(self):
        assert derive_live_season({}) is None

    def test_missing_deadline_time_returns_none(self):
        bootstrap = {"events": [{"id": 1}]}
        assert derive_live_season(bootstrap) is None

    def test_malformed_deadline_time_returns_none(self):
        bootstrap = _bootstrap_with_event_one("not-a-date")
        assert derive_live_season(bootstrap) is None


# ---------------------------------------------------------------------------
# assert_season_matches
# ---------------------------------------------------------------------------

class TestAssertSeasonMatches:

    def test_matching_season_passes_silently(self):
        bootstrap = _bootstrap_with_event_one("2025-08-15T17:30:00Z")
        assert_season_matches(bootstrap, "2025-2026")  # must not raise

    def test_mismatched_season_raises_with_actionable_message(self):
        bootstrap = _bootstrap_with_event_one("2026-08-14T17:30:00Z")
        with pytest.raises(SeasonMismatchError) as exc_info:
            assert_season_matches(bootstrap, "2025-2026")
        message = str(exc_info.value)
        assert "2026-2027" in message  # what it found
        assert "2025-2026" in message  # what was requested
        assert "--season" in message   # what to do

    def test_undeterminable_season_does_not_raise(self):
        # No event id=1 in this payload — guard cannot verify, so it must
        # not block the capture on an unrelated data-shape change.
        bootstrap = {"events": []}
        assert_season_matches(bootstrap, "2025-2026")  # must not raise
