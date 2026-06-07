"""
fpl_historical.vaastav_import
=============================
One-shot seed importer: vaastav/Fantasy-Premier-League community CSV
snapshots → our owned parquet schema (Track A H6).

This module is **never** invoked by the deployed runtime. It is an
operator-driven, local-only tool for seeding prior-season data that the
live FPL API no longer serves (the API only returns the current season).

Public API:
    ImportResult            frozen dataclass describing one season's import
    import_season(season, source_path, target_root=None) -> ImportResult
    VAASTAV_REPO_URL        the upstream repo URL
    VAASTAV_PINNED_SHA      the commit SHA the importer was developed against

Pinned commit (Decision 1, H6 §4)
----------------------------------
We pin to a specific vaastav commit rather than tracking a moving branch
HEAD, because the community repo's CSV layout has changed over time and
can change again without notice. Pinning makes re-imports deterministic:
clone, checkout the SHA, import — same bytes in, same parquet out.

    VAASTAV_PINNED_SHA = "81980c1d597a1eab8764e3f5189b3a6f20939da8"

This SHA was the tip of the vaastav `master` branch at clone time during
this session's recon (commit dated 2026-04-20, message "docs: add caveat
about xP scraping timing and potential lookahead (#222)"). It is REAL and
was verified to exist by cloning the repo locally and inspecting
`git log -1`.

>>> CAVEAT FOR THE OPERATOR <<<
This module cannot make live network calls, so the SHA above could not be
re-verified at the moment you run the importer — vaastav may have moved
since. Before a real import, the operator SHOULD:
    1. `git clone --depth=1 https://github.com/vaastav/Fantasy-Premier-League`
    2. `git log -1 --format=%H` inside the clone and compare against the
       constant below; update the constant if it has drifted materially
       (e.g. if the season you need post-dates this SHA — this SHA's tree
       only contains seasons through 2022-23; later seasons such as
       2023-2024 / 2024-2025 require a newer commit).
    3. `git checkout <SHA>` to pin the working tree before pointing
       `--source` at it.

Directory naming caveat (discovered during this session's clone)
-----------------------------------------------------------------
vaastav stores seasons as `data/<YYYY-YY>/` (e.g. `data/2024-25/`), NOT
`data/<YYYY-YYYY>/` as our internal season keys use (e.g. `2024-2025`).
This importer accepts OUR season key format (`YYYY-YYYY`, matching
`CURRENT_SEASON` and `season_dir()`) and derives the vaastav-local
directory name by truncating the second year to two digits
(`2024-2025` -> `2024-25`). See `_vaastav_dir_name()`.

Schema mapping
--------------
See plan §6 (canonical mapping tables). Implemented faithfully below, with
two adaptations discovered while building real fixtures against vaastav's
actual CSV headers (verified via local clone, commit 81980c1d):

  * `expected_goals` / `expected_assists` are vaastav's real per-GW column
    names for what the plan shorthands as "xG, xA". `xP` is a distinct,
    separate column. All three are optional (Decision 4: null-fill when
    absent, e.g. for older seasons that predate xG/xA tracking).
  * `was_home` arrives from CSV as the literal strings `"True"` / `"False"`
    (csv module yields strings, not bools). We coerce to a real boolean.

Idempotency (Decision 8 / §8)
-----------------------------
`import_season` overwrites the season's `parquet_merged/` directory and
`_owned_latest.json` pointer in place — no merge-with-existing logic.
Re-running for the same season is safe and produces byte-equivalent output
(modulo the `merged_at` / `captured_at` timestamps, which reflect import
time).

ML / nulls caveat
-----------------
Older vaastav seasons lack `xP`, `expected_goals`, `expected_assists`, and
related columns entirely. Any downstream ML/Track-2 code that consumes
`player_gw_stats.parquet` across multiple seasons MUST handle nulls in
these columns (or filter by `season`) — they are not uniformly available.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from fpl_historical.paths import historical_root, merged_parquet_dir, owned_latest_pointer_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module constants (Decision 1)
# ---------------------------------------------------------------------------

VAASTAV_REPO_URL = "https://github.com/vaastav/Fantasy-Premier-League"

# See the module docstring "Pinned commit" section for full provenance and
# the operator caveat about re-verifying this before a real import.
VAASTAV_PINNED_SHA = "81980c1d597a1eab8764e3f5189b3a6f20939da8"

_SOURCE_LABEL = f"vaastav@{VAASTAV_PINNED_SHA}"

# vaastav directory names use YYYY-YY (two-digit second year); ours use
# YYYY-YYYY. e.g. "2024-2025" -> "2024-25".
_SEASON_KEY_RE = re.compile(r"^(\d{4})-(\d{4})$")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _resolve_source_label(source_path: Path) -> str:
    """Return ``vaastav@<sha>`` stamped with the clone's *actual* HEAD SHA.

    Reads the real commit from the ``source_path`` git clone so the
    provenance recorded in ``_owned_latest.json`` reflects what was
    genuinely imported, not the module's developed-against
    ``VAASTAV_PINNED_SHA``. Falls back to the pinned constant (suffixed
    ``-unverified``) if the source is not a resolvable git clone — e.g. a
    plain directory, or git not on PATH — so a non-git source still produces
    an honest, clearly-flagged label rather than a misleading exact SHA.

    The SHA is only stamped when ``source_path`` is *itself* the root of a
    git repository. ``git rev-parse`` otherwise walks up the directory tree
    and would report an unrelated ancestor repo's commit (e.g. this
    monorepo's HEAD when the source is a temp dir nested inside it), which
    would be actively misleading provenance.
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(source_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if top.returncode != 0:
            return f"vaastav@{VAASTAV_PINNED_SHA}-unverified"
        toplevel = Path(top.stdout.strip()).resolve()
        if toplevel != Path(source_path).resolve():
            return f"vaastav@{VAASTAV_PINNED_SHA}-unverified"

        head = subprocess.run(
            ["git", "-C", str(source_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        sha = head.stdout.strip()
        if head.returncode == 0 and _SHA_RE.match(sha):
            return f"vaastav@{sha}"
    except (OSError, subprocess.SubprocessError):
        pass
    return f"vaastav@{VAASTAV_PINNED_SHA}-unverified"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImportResult:
    """Outcome of importing one season from vaastav CSVs."""

    ok: bool
    season: str
    row_counts: dict[str, int] = field(default_factory=dict)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vaastav_dir_name(season: str) -> str:
    """Convert our season key (``YYYY-YYYY``) to vaastav's (``YYYY-YY``).

    e.g. ``"2024-2025"`` -> ``"2024-25"``.
    """
    m = _SEASON_KEY_RE.match(season)
    if not m:
        # Fall back to the season string verbatim — lets callers pass an
        # already-vaastav-shaped key if they need to.
        return season
    return f"{m.group(1)}-{m.group(2)[2:]}"


#: Encoding fallback chain. vaastav's older seasons (pre-2019-20) store CSVs
#: in legacy Windows/latin-1 encoding (e.g. 0xe9 = "é"), not UTF-8. Try UTF-8
#: first (correct for modern seasons), then cp1252, then latin-1 — latin-1
#: maps every byte so it never raises and is the guaranteed-terminal fallback.
_CSV_ENCODINGS = ("utf-8", "cp1252", "latin-1")


def _read_csv(path: Path) -> pd.DataFrame:
    """Read a CSV into a DataFrame, returning an empty frame if absent.

    Tries a chain of encodings (see ``_CSV_ENCODINGS``) so that both modern
    UTF-8 seasons and older latin-1 seasons load. Raises only if every
    encoding fails (latin-1 cannot, so this is effectively never).
    """
    if not path.exists():
        return pd.DataFrame()
    last_err: UnicodeDecodeError | None = None
    for enc in _CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise last_err  # pragma: no cover - latin-1 never raises


def _coerce_bool(series: pd.Series) -> pd.Series:
    """Coerce a column of `"True"`/`"False"` strings (or real bools) to bool."""
    def _conv(v):
        if isinstance(v, bool):
            return v
        if pd.isna(v):
            return False
        s = str(v).strip().lower()
        return s in ("true", "1", "yes")

    return series.map(_conv)


def _select_with_drift_tracking(
    df: pd.DataFrame,
    column_map: dict[str, str | None],
    *,
    table_name: str,
    missing_columns: dict[str, list[str]],
) -> pd.DataFrame:
    """Build an output DataFrame per *column_map* (out_col -> source_col).

    If ``source_col`` is ``None`` the column is injected later by the
    caller (e.g. ``season``, computed columns). If ``source_col`` is a
    string but absent from *df*, the output column is filled with null,
    a WARNING is logged, and the gap is recorded in *missing_columns*
    (Decision 4 — non-fatal schema drift).
    """
    out: dict[str, object] = {}
    n = len(df)
    drifted: list[str] = []
    for out_col, src_col in column_map.items():
        if src_col is None:
            continue
        if src_col in df.columns:
            out[out_col] = df[src_col]
        else:
            out[out_col] = pd.Series([None] * n, dtype="object")
            drifted.append(out_col)

    if drifted:
        missing_columns[table_name] = drifted
        logger.warning(
            "missing_columns table=%s cols=%s", table_name, drifted,
        )

    if out:
        return pd.DataFrame(out)
    return pd.DataFrame(index=df.index)


def _write_parquet_atomic(df: pd.DataFrame, dest: Path) -> None:
    """Write *df* to *dest* via a .parquet.tmp file, then os.replace (atomic)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, str(tmp))
    os.replace(str(tmp), str(dest))


# ---------------------------------------------------------------------------
# Per-table builders (pure functions of the loaded source frames)
# ---------------------------------------------------------------------------

def _build_players_df(
    players_raw: pd.DataFrame, season: str, missing_columns: dict[str, list[str]]
) -> pd.DataFrame:
    column_map: dict[str, str | None] = {
        "season": None,  # injected
        "player_id": "id",
        "web_name": "web_name",
        "first_name": "first_name",
        "second_name": "second_name",
        "team_id": "team",
        "element_type": "element_type",
        "now_cost": "now_cost",
        "total_points": "total_points",
        "selected_by_percent": "selected_by_percent",
    }
    out = _select_with_drift_tracking(
        players_raw, column_map, table_name="players", missing_columns=missing_columns
    )
    out.insert(0, "season", season)
    if "selected_by_percent" in out.columns:
        out["selected_by_percent"] = pd.to_numeric(
            out["selected_by_percent"], errors="coerce"
        )
    for int_col in ("player_id", "team_id", "element_type", "now_cost", "total_points"):
        if int_col in out.columns:
            out[int_col] = pd.to_numeric(out[int_col], errors="coerce").astype("Int64")
    return out


def _build_teams_df(
    teams_raw: pd.DataFrame, season: str, missing_columns: dict[str, list[str]]
) -> pd.DataFrame:
    column_map: dict[str, str | None] = {
        "season": None,
        "team_id": "id",
        "name": "name",
        "short_name": "short_name",
        "strength": "strength",
        "strength_overall_home": "strength_overall_home",
        "strength_overall_away": "strength_overall_away",
        "strength_attack_home": "strength_attack_home",
        "strength_attack_away": "strength_attack_away",
        "strength_defence_home": "strength_defence_home",
        "strength_defence_away": "strength_defence_away",
    }
    out = _select_with_drift_tracking(
        teams_raw, column_map, table_name="teams", missing_columns=missing_columns
    )
    out.insert(0, "season", season)
    for int_col in ("team_id", "strength"):
        if int_col in out.columns:
            out[int_col] = pd.to_numeric(out[int_col], errors="coerce").astype("Int64")
    return out


def _build_fixtures_df(
    fixtures_raw: pd.DataFrame, season: str, missing_columns: dict[str, list[str]]
) -> pd.DataFrame:
    column_map: dict[str, str | None] = {
        "season": None,
        "fixture_id": "id",
        "event_id": "event",
        "team_h": "team_h",
        "team_a": "team_a",
        "team_h_score": "team_h_score",
        "team_a_score": "team_a_score",
        "kickoff_time": "kickoff_time",
    }
    out = _select_with_drift_tracking(
        fixtures_raw, column_map, table_name="fixtures", missing_columns=missing_columns
    )
    out.insert(0, "season", season)
    # Historical seasons are final — every fixture is finished.
    out["finished"] = True
    for int_col in ("fixture_id", "event_id", "team_h", "team_a", "team_h_score", "team_a_score"):
        if int_col in out.columns:
            out[int_col] = pd.to_numeric(out[int_col], errors="coerce").astype("Int64")
    return out


def _build_events_df(fixtures_raw: pd.DataFrame, season: str) -> pd.DataFrame:
    """Reconstruct events from fixtures (§6: group by event, min kickoff_time)."""
    if fixtures_raw.empty or "event" not in fixtures_raw.columns:
        return pd.DataFrame(
            columns=["season", "event_id", "name", "deadline_time", "finished", "data_checked"]
        )

    df = fixtures_raw.copy()
    df["event"] = pd.to_numeric(df["event"], errors="coerce")
    df = df.dropna(subset=["event"])
    df["event"] = df["event"].astype("int64")

    if "finished" in df.columns:
        finished_series = _coerce_bool(df["finished"])
    else:
        finished_series = pd.Series([True] * len(df), index=df.index)
    df["_finished_bool"] = finished_series

    rows: list[dict] = []
    for event_id, grp in df.groupby("event", sort=True):
        deadline = grp["kickoff_time"].min() if "kickoff_time" in grp.columns else None
        all_finished = bool(grp["_finished_bool"].all())
        rows.append(
            {
                "season": season,
                "event_id": int(event_id),
                "name": f"Gameweek {int(event_id)}",
                "deadline_time": deadline,
                "finished": all_finished,
                "data_checked": True,
            }
        )

    return pd.DataFrame(rows)


def _build_player_gw_stats_df(
    source_path: Path,
    season: str,
    vaastav_dir: str,
    captured_at: str,
    missing_columns: dict[str, list[str]],
) -> pd.DataFrame:
    gws_dir = source_path / "data" / vaastav_dir / "gws"

    column_map: dict[str, str | None] = {
        "season": None,
        "player_id": "element",
        "event_id": None,  # from filename
        "total_points": "total_points",
        "minutes": "minutes",
        "goals_scored": "goals_scored",
        "assists": "assists",
        "clean_sheets": "clean_sheets",
        "goals_conceded": "goals_conceded",
        "saves": "saves",
        "bonus": "bonus",
        "bps": "bps",
        "value": "value",
        "was_home": "was_home",
        "xP": "xP",
        "expected_goals": "expected_goals",
        "expected_assists": "expected_assists",
        "expected_goal_involvements": "expected_goal_involvements",
        "expected_goals_conceded": "expected_goals_conceded",
    }

    if not gws_dir.exists():
        return pd.DataFrame(columns=list(column_map.keys()) + ["captured_at", "source", "source_captured_at"])

    gw_files = sorted(
        gws_dir.glob("gw*.csv"),
        key=lambda p: int(re.match(r"gw(\d+)\.csv", p.name).group(1))
        if re.match(r"gw(\d+)\.csv", p.name)
        else 0,
    )

    frames: list[pd.DataFrame] = []
    drifted_union: set[str] = set()

    for gw_file in gw_files:
        m = re.match(r"gw(\d+)\.csv", gw_file.name)
        if not m:
            continue
        event_id = int(m.group(1))

        raw = _read_csv(gw_file)
        if raw.empty:
            continue

        # Track drift per-file but only report the union once for the table.
        local_missing: dict[str, list[str]] = {}
        out = _select_with_drift_tracking(
            raw, column_map, table_name="player_gw_stats", missing_columns=local_missing
        )
        drifted_union.update(local_missing.get("player_gw_stats", []))

        out.insert(0, "season", season)
        out["event_id"] = event_id

        if "was_home" in out.columns:
            out["was_home"] = _coerce_bool(out["was_home"])

        out["captured_at"] = captured_at
        out["source"] = "vaastav"
        out["source_captured_at"] = captured_at

        frames.append(out)

    if drifted_union:
        sorted_drift = sorted(drifted_union)
        missing_columns["player_gw_stats"] = sorted_drift
        logger.warning(
            "missing_columns table=player_gw_stats cols=%s", sorted_drift,
        )

    if not frames:
        return pd.DataFrame(
            columns=list(column_map.keys()) + ["captured_at", "source", "source_captured_at"]
        )

    combined = pd.concat(frames, ignore_index=True)

    for int_col in ("player_id", "event_id", "total_points", "minutes", "goals_scored",
                    "assists", "clean_sheets", "goals_conceded", "saves", "bonus", "bps", "value"):
        if int_col in combined.columns:
            combined[int_col] = pd.to_numeric(combined[int_col], errors="coerce").astype("Int64")
    for float_col in ("xP", "expected_goals", "expected_assists",
                      "expected_goal_involvements", "expected_goals_conceded"):
        if float_col in combined.columns:
            combined[float_col] = pd.to_numeric(combined[float_col], errors="coerce")

    return combined


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_season(
    season: str,
    source_path: Path,
    target_root: Path | None = None,
) -> ImportResult:
    """Import one season's vaastav CSV snapshot into our parquet schema.

    Parameters
    ----------
    season:
        Our season key, e.g. ``"2024-2025"``.
    source_path:
        Path to a local clone of the vaastav repo (containing ``data/``).
    target_root:
        Override for the historical store root. Defaults to
        ``historical_root()``.

    Returns
    -------
    ImportResult
        ``ok=True`` with row counts and any recorded schema drift on
        success; ``ok=False`` with ``error`` set on failure. Never raises
        for expected per-season issues (missing optional columns); raises
        only propagate from truly unexpected I/O errors are caught and
        turned into a failed ``ImportResult`` so a multi-season batch can
        continue past one bad season.
    """
    source_path = Path(source_path)
    vaastav_dir = _vaastav_dir_name(season)
    season_data_dir = source_path / "data" / vaastav_dir

    missing_columns: dict[str, list[str]] = {}

    try:
        if not season_data_dir.exists():
            return ImportResult(
                ok=False,
                season=season,
                error=(
                    f"vaastav season directory not found: {season_data_dir} "
                    f"(derived vaastav dir name '{vaastav_dir}' from season key '{season}')"
                ),
            )

        captured_at = _utcnow_iso()

        players_raw = _read_csv(season_data_dir / "players_raw.csv")
        teams_raw = _read_csv(season_data_dir / "teams.csv")
        fixtures_raw = _read_csv(season_data_dir / "fixtures.csv")

        players_df = _build_players_df(players_raw, season, missing_columns)
        teams_df = _build_teams_df(teams_raw, season, missing_columns)
        fixtures_df = _build_fixtures_df(fixtures_raw, season, missing_columns)
        events_df = _build_events_df(fixtures_raw, season)
        gw_df = _build_player_gw_stats_df(
            source_path, season, vaastav_dir, captured_at, missing_columns
        )

        if target_root is not None:
            out_dir = Path(target_root) / "seasons" / season / "parquet_merged"
            pointer_path = Path(target_root) / "seasons" / season / "_owned_latest.json"
        else:
            out_dir = merged_parquet_dir(season)
            pointer_path = owned_latest_pointer_path(season)

        tables = {
            "players": players_df,
            "teams": teams_df,
            "events": events_df,
            "fixtures": fixtures_df,
            "player_gw_stats": gw_df,
        }

        # Idempotent overwrite (Decision 8): write fresh files; no
        # concat-with-existing. _write_parquet_atomic replaces in place.
        for name, df in tables.items():
            _write_parquet_atomic(df, out_dir / f"{name}.parquet")

        row_counts = {name: len(df) for name, df in tables.items()}

        pointer = {
            "season": season,
            "merged_at": captured_at,
            "source": _resolve_source_label(source_path),
            "row_counts": row_counts,
        }

        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(pointer, indent=2).encode("utf-8")
        tmp_path = pointer_path.with_suffix(".json.tmp")
        tmp_path.write_bytes(payload)
        os.replace(str(tmp_path), str(pointer_path))

        return ImportResult(
            ok=True,
            season=season,
            row_counts=row_counts,
            missing_columns=missing_columns,
            error=None,
        )

    except Exception as exc:  # pragma: no cover - defensive; keeps batch alive
        logger.exception("vaastav import failed season=%s", season)
        return ImportResult(
            ok=False,
            season=season,
            row_counts={},
            missing_columns=missing_columns,
            error=str(exc),
        )
