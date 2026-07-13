"""
fpl_tactical
============
Owned tactical (zonal shot-event) data store for the FPL platform.

This package pulls Understat shot events via soccerdata (T1a decision — see
DECISIONS.md), normalizes them into an owned parquet store, and publishes to
R2. Downstream consumers (the zonal-weakness engine in fpl-grounded-assistant)
read the parquet store only; they never scrape live.

Keep this module import-light: fpl_grounded_assistant imports the shared
constants below at request time, and soccerdata must remain a weekly-workflow
dependency only (it is imported lazily inside understat_client).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# soccerdata's SHOT_SITUATIONS map omits Understat's "Penalty", so penalties
# arrive with situation = NA and are re-labelled to this value at ingest
# (see ingest.normalize_shots). The T2 zonal engine excludes penalties from
# zonal aggregation using this same constant so the two can never drift.
PENALTY_SITUATION: str = "Penalty"
