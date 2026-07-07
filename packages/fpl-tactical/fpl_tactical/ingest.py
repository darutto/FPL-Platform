"""
fpl_tactical.ingest
===================
Normalize soccerdata Understat frames into the owned ``understat_shots``
schema and run a season ingest end-to-end (fetch → normalize → parquet +
provenance pointer).

Normalization is a pure function (:func:`normalize_shots`) so tests exercise
it against canned soccerdata-shaped frames with no network.

Penalty re-label guard
----------------------
soccerdata's ``SHOT_SITUATIONS`` map omits Understat's ``"Penalty"``, so
penalties arrive with ``situation = NA``. Every NA row is checked against the
penalty-spot signature (x≈0.885, y≈0.5, xG≈0.76 — verified across all 92
NA rows of 2025/26, see DECISIONS.md) and re-labelled to
``PENALTY_SITUATION``. An NA row OFF the signature means soccerdata's
situation mapping changed upstream — ingest fails loudly rather than store
mislabelled rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from fpl_tactical import PENALTY_SITUATION
from fpl_tactical.paths import CURRENT_SEASON
from fpl_tactical.understat_client import SOURCE_NAME, UnderstatClient
from fpl_tactical import store

# Penalty-spot signature (Understat pins all penalties to one coordinate/xG)
_PEN_X, _PEN_Y, _PEN_XG = 0.885, 0.5, 0.761
_PEN_TOL_XY, _PEN_TOL_XG = 0.02, 0.03

# Owned schema column order (CONTRACT)
SHOT_COLUMNS: list[str] = [
    "season",
    "match_id",
    "date",
    "shooting_team",
    "conceding_team",
    "player",
    "is_home_shot",
    "minute",
    "x",
    "y",
    "xg",
    "situation",
    "shot_type",
    "result",
]


class IngestError(RuntimeError):
    """Raised when ingest must fail loudly (schema drift, bad source data)."""


def _relabel_penalties(df: pd.DataFrame) -> pd.DataFrame:
    """Re-label NA-situation rows to PENALTY_SITUATION, guarding the signature.

    Raises :class:`IngestError` if any NA-situation row is off the
    penalty-spot signature — that means soccerdata's SHOT_SITUATIONS mapping
    changed and blind re-labelling would corrupt the store.
    """
    na_mask = df["situation"].isna()
    if not na_mask.any():
        return df
    na_rows = df[na_mask]
    off_signature = na_rows[
        (na_rows["x"].sub(_PEN_X).abs() > _PEN_TOL_XY)
        | (na_rows["y"].sub(_PEN_Y).abs() > _PEN_TOL_XY)
        | (na_rows["xg"].sub(_PEN_XG).abs() > _PEN_TOL_XG)
    ]
    if len(off_signature):
        sample = off_signature[["match_id", "player", "x", "y", "xg"]].head(5)
        raise IngestError(
            f"{len(off_signature)} NA-situation rows are OFF the penalty "
            f"signature (x≈{_PEN_X}, y≈{_PEN_Y}, xG≈{_PEN_XG}) — soccerdata's "
            f"situation mapping likely changed upstream. Sample:\n{sample}"
        )
    df = df.copy()
    df.loc[na_mask, "situation"] = PENALTY_SITUATION
    return df


def normalize_shots(
    shots: pd.DataFrame, schedule: pd.DataFrame, season: str
) -> pd.DataFrame:
    """Turn raw soccerdata frames into the owned ``understat_shots`` schema.

    Pure — no network, no filesystem. Situation/result strings are stored
    verbatim as soccerdata normalizes them ("Open Play", "Missed Shot", …),
    except the penalty re-label documented in the module docstring.

    - ``match_id`` is soccerdata's ``game_id`` (the Understat match id).
    - ``conceding_team`` / ``is_home_shot`` derive from a schedule join on
      ``game_id`` so T2's defensive aggregation is a trivial group-by.
    """
    required_shot_cols = {
        "game_id", "team", "player", "minute",
        "location_x", "location_y", "xg", "situation", "body_part", "result",
    }
    missing = required_shot_cols - set(shots.columns)
    if missing:
        raise IngestError(f"shots frame is missing expected columns: {sorted(missing)}")

    sched = schedule[["game_id", "date", "home_team", "away_team"]]
    merged = shots.merge(sched, on="game_id", how="left", suffixes=("", "_sched"))
    unmatched = merged["home_team"].isna()
    if unmatched.any():
        raise IngestError(
            f"{int(unmatched.sum())} shots have a game_id absent from the schedule"
        )

    is_home = merged["team"] == merged["home_team"]
    is_away = merged["team"] == merged["away_team"]
    orphan = ~(is_home | is_away)
    if orphan.any():
        raise IngestError(
            f"{int(orphan.sum())} shots have a team matching neither home nor "
            f"away side of their game — team-name normalization drift?"
        )

    out = pd.DataFrame(
        {
            "season": season,
            "match_id": merged["game_id"].astype("int64"),
            "date": pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "shooting_team": merged["team"].astype(str),
            "conceding_team": merged["away_team"].where(is_home, merged["home_team"]).astype(str),
            "player": merged["player"].astype(str),
            "is_home_shot": is_home,
            "minute": merged["minute"].astype("int64"),
            "x": merged["location_x"].astype("float64"),
            "y": merged["location_y"].astype("float64"),
            "xg": merged["xg"].astype("float64"),
            "situation": merged["situation"],
            "shot_type": merged["body_part"],
            "result": merged["result"],
        }
    )
    out = _relabel_penalties(out)
    # Plain-string dtype for the object columns soccerdata delivers as
    # pandas extension ("string[python]") types, keeping parquet simple.
    for col in ("situation", "shot_type", "result"):
        out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out[SHOT_COLUMNS]


def ingest_season(
    season: str = CURRENT_SEASON, client: UnderstatClient | None = None
) -> dict:
    """Fetch, normalize and store one season. Returns the provenance pointer.

    Idempotent: re-running replaces the season's parquet atomically and
    refreshes ``_tactical_latest.json``.
    """
    client = client or UnderstatClient()
    shots_raw, schedule = client.fetch_raw(season)
    normalized = normalize_shots(shots_raw, schedule, season)
    store.write_shots(normalized, season)
    pointer = {
        "season": season,
        "ingested_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE_NAME,
        "source_version": client.source_version(),
        "n_matches": int(normalized["match_id"].nunique()),
        "n_shots": int(len(normalized)),
    }
    store.write_pointer(pointer, season)
    return pointer
