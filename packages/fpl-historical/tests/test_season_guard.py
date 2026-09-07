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
    SeasonGuardError,
    SeasonMismatchError,
    SeasonUndeterminedError,
    assert_season_matches,
    derive_live_season,
)

# Every bootstrap shape from which a season cannot be derived. Each one of
# these used to let a capture proceed unverified.
UNDETERMINABLE_BOOTSTRAPS = {
    "events_empty": {"events": []},
    "no_events_key": {},
    "events_null": {"events": None},
    "no_event_id_1": {"events": [{"id": 2, "deadline_time": "2026-08-21T17:30:00Z"}]},
    "no_deadline_time": {"events": [{"id": 1}]},
    "malformed_deadline": {"events": [{"id": 1, "deadline_time": "not-a-date"}]},
}


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

    @pytest.mark.parametrize("shape", sorted(UNDETERMINABLE_BOOTSTRAPS))
    def test_undeterminable_season_raises(self, shape):
        """Fail CLOSED. 'Cannot verify' is a rejection, not a pass.

        Inverted deliberately: the guard used to return silently here. The
        window in which the bootstrap event list is rebuilt IS the season
        rollover, so the shapes that defeat the derivation are most likely
        to appear exactly when writing to the wrong season key is most
        destructive.
        """
        with pytest.raises(SeasonUndeterminedError):
            assert_season_matches(UNDETERMINABLE_BOOTSTRAPS[shape], "2025-2026")

    def test_undeterminable_message_is_distinguishable_from_mismatch(self):
        """A human must be able to tell the two rejections apart from the text."""
        with pytest.raises(SeasonUndeterminedError) as exc_info:
            assert_season_matches({"events": []}, "2025-2026")
        message = str(exc_info.value)
        assert "could not determine" in message      # which condition fired
        assert "2025-2026" in message                # what was requested
        assert "--allow-unverified-season" in message  # what to do

        mismatch_bootstrap = _bootstrap_with_event_one("2026-08-14T17:30:00Z")
        with pytest.raises(SeasonMismatchError) as mismatch_info:
            assert_season_matches(mismatch_bootstrap, "2025-2026")
        mismatch_message = str(mismatch_info.value)

        # The mismatch message names a season it FOUND; the undetermined one
        # cannot, and must not claim to.
        assert "2026-2027" in mismatch_message
        assert "2026-2027" not in message
        assert message != mismatch_message

    def test_undetermined_and_mismatch_are_distinct_types(self):
        """Catching one must not catch the other; both are guard rejections."""
        assert not issubclass(SeasonUndeterminedError, SeasonMismatchError)
        assert not issubclass(SeasonMismatchError, SeasonUndeterminedError)
        assert issubclass(SeasonUndeterminedError, SeasonGuardError)
        assert issubclass(SeasonMismatchError, SeasonGuardError)

    @pytest.mark.parametrize("shape", sorted(UNDETERMINABLE_BOOTSTRAPS))
    def test_valve_allows_undeterminable_season(self, shape):
        """The explicit operator valve restores the old permissive behaviour."""
        assert_season_matches(
            UNDETERMINABLE_BOOTSTRAPS[shape],
            "2025-2026",
            allow_unverified_season=True,
        )  # must not raise

    def test_valve_does_not_override_a_confirmed_mismatch(self):
        """The valve covers 'could not determine' ONLY.

        A season that was successfully derived and disagrees is always
        rejected — that is the incident itself, and it has no override.
        """
        bootstrap = _bootstrap_with_event_one("2026-08-14T17:30:00Z")  # -> 2026-2027
        with pytest.raises(SeasonMismatchError):
            assert_season_matches(
                bootstrap, "2025-2026", allow_unverified_season=True
            )

    def test_valve_defaults_to_off(self):
        """The safe behaviour is the one you get without passing anything."""
        with pytest.raises(SeasonUndeterminedError):
            assert_season_matches({"events": []}, "2025-2026")

    def test_valve_does_not_affect_the_matching_case(self):
        bootstrap = _bootstrap_with_event_one("2025-08-15T17:30:00Z")
        assert_season_matches(
            bootstrap, "2025-2026", allow_unverified_season=True
        )  # must not raise
