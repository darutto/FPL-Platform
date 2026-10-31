"""Per-player, per-match statistics from the provider's ``lineups.details``, as derived (FPL-keyed) rows.

Input is a finished fixture's lineup rows, each with ``details``: ``[{"type_id": ..., "data": {"value": ...}}]``.
The provider names a statistic by ``type_id``; the id -> developer name map is NOT written here: it is read from the
provider through the client (``player_stat_types`` route, ``lineups.details.type``), so a renumbering cannot
silently mislabel a column. What IS written here is which developer names we keep and what column each one fills.

Decisions a reviewer should be able to find:

* **Absent means zero, for a player with minutes.** The provider sends only non-zero statistics (measured on 60
  finished fixtures: every statistic present was non-zero in 100 % of its rows; see the trial field-coverage report).
  So a player who has ``MINUTES_PLAYED`` and no ``TOUCHES`` detail had none. A player WITHOUT minutes gets no row at
  all (an unused substitute has no match to describe).
* **Unknown is not zero.** Absent = zero holds only for a statistic whose name the type map knows. If the map has no
  id for a curated name (the provider's names were read from one fixture where it never occurred), its column is
  ``None`` in every row of the pass: a detail with that id may have been there and been dropped.
* **A rating is not a count.** An unrated appearance (a cameo of a couple of minutes) has ``rating = None``, never 0.
* **Percentages are not stored.** Accuracy is derived from the counts where it is shown.
* **Only completed fixtures**, and the caller says so: a live match's totals are partial.
* **Provider ids stay out.** Rows carry the FPL element and fixture only.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

#: provider developer name -> (column, kind). ``count`` columns are zero-filled for a player with minutes.
STAT_COLUMNS: dict[str, tuple[str, str]] = {
    "MINUTES_PLAYED": ("minutes", "count"),
    "RATING": ("rating", "value"),
    "TOUCHES": ("touches", "count"),
    "PASSES": ("passes", "count"),
    "ACCURATE_PASSES": ("accurate_passes", "count"),
    "KEY_PASSES": ("key_passes", "count"),
    "LONG_BALLS": ("long_balls", "count"),
    "THROUGH_BALLS": ("through_balls", "count"),
    "BACKWARD_PASSES": ("backward_passes", "count"),
    "PASSES_IN_FINAL_THIRD": ("passes_final_third", "count"),
    "SHOTS_TOTAL": ("shots", "count"),
    "SHOTS_ON_TARGET": ("shots_on_target", "count"),
    "DUELS_WON": ("duels_won", "count"),
    "TACKLES": ("tackles", "count"),
    "INTERCEPTIONS": ("interceptions", "count"),
    "BALL_RECOVERY": ("recoveries", "count"),
    "SUCCESSFUL_DRIBBLES": ("dribbles", "count"),
}
STARTER_TYPE_ID = 11
PLAYER_MATCH_STATS_COLUMNS = ("element", "fixture_id", "team", "observed_at", "starter",
                              *(column for column, _kind in STAT_COLUMNS.values()))
_MEASURES = tuple(c for c in PLAYER_MATCH_STATS_COLUMNS if c not in ("element", "fixture_id", "team", "observed_at"))


def type_names(rows: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """type id -> developer name, from detail rows that carry their ``type`` (the client lifts ``type_name`` out of
    ``lineups.details.type``). A conflicting pair for one id is an error: the map must be a function."""
    names: dict[int, str] = {}
    for row in rows:
        type_id, name = row.get("type_id"), row.get("type_name")
        if isinstance(type_id, int) and isinstance(name, str):
            if names.setdefault(type_id, name) != name:
                raise ValueError("one provider type id carries two names")
    return names


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def unresolved_columns(names: Mapping[int, str]) -> list[str]:
    """The curated developer names the type map does not know (their columns are written as ``None``)."""
    return sorted(set(STAT_COLUMNS) - set(names.values()))


def lineup_stats(lineup_row: Mapping[str, Any], names: Mapping[int, str]) -> dict[str, Any] | None:
    """The curated measures of one lineup row, or None when the player has no minutes (no row)."""
    known = set(names.values())
    found: dict[str, float] = {}
    for detail in lineup_row.get("details") or []:
        entry = STAT_COLUMNS.get(names.get(detail.get("type_id"), ""))
        value = _number((detail.get("data") or {}).get("value"))
        if entry is not None and value is not None:
            found[entry[0]] = value
    minutes = found.get("minutes")
    if not minutes or minutes <= 0:
        return None
    out: dict[str, Any] = {}
    for name, (column, kind) in STAT_COLUMNS.items():
        if name not in known:
            out[column] = None                        # unknown type: a dropped detail must not read as zero
        elif kind == "count":
            out[column] = int(found.get(column, 0))   # absent = zero, validated per field for players with minutes
        else:
            out[column] = found.get(column)           # a rating: unrated stays None
    out["starter"] = lineup_row.get("type_id") == STARTER_TYPE_ID
    return out


def new_information(old_rows: Iterable[Mapping[str, Any]], new_rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The new rows that add information: a re-read of a finished match (the daily pass looks back 7 days) whose
    measures equal the latest stored observation of the same (element, fixture) is dropped, so history does not
    grow by a copy per day."""
    latest: dict[tuple[Any, Any], Mapping[str, Any]] = {}
    for row in sorted(old_rows, key=lambda r: str(r["observed_at"])):
        latest[(row["element"], row["fixture_id"])] = row
    kept = []
    for row in new_rows:
        before = latest.get((row["element"], row["fixture_id"]))
        if before is None or any(before.get(c) != row.get(c) for c in _MEASURES):
            kept.append(row)
    return kept
