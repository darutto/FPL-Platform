#!/usr/bin/env python3
"""
backtest_fixture_difficulty.py
================================
Whole-population evaluation harness for Track D's fixture-difficulty model
(roadmap ML0, scoped to the fixture engine).

Why this exists
---------------
We had been validating the attack/defence difficulty bands by hand-picking a
handful of fixtures and eyeballing predicted band vs a single match's actual
goals. That is a measurement artifact factory:
  * actual goals in ONE match is a Poisson draw (variance ~= mean) — it can't
    tell you whether a *rate* prediction was good;
  * a hand-picked sample can't separate signal from noise;
  * "better/worse" means nothing without a benchmark.

This harness fixes all three: it scores every team-fixture in the season
(~760) against team-aggregated **xG** (a far lower-variance signal than goals)
for FOUR models on a benchmark ladder, and reports a **calibration table per
axis** — the direct test of whether a predicted band means anything.

Models (benchmark ladder)
-------------------------
  naive     constant band 3 (floor — no fixture information at all)
  fpl_fdr   FPL's own FDR (team_h/a_difficulty). Single-axis: same number for
            attack and defence — a limitation this harness makes visible.
  static    our committed end-of-season strength snapshot (what /fixtures shows)
  rolling   our Step-2 walk-forward decaying model (compute_rolling_strength),
            banded using ONLY matches before each fixture's own GW. The static
            snapshot has a mild end-of-season lookahead edge rolling does not —
            so a rolling win here is a strong result.

No band logic is duplicated: bands come from the real engine
(fixture_outlook.build_axis_thresholds / _fixture_band).

Transfer-proofing
-----------------
players.parquet stores each player's END-OF-SEASON club, so aggregating xG by
that roster mis-attributes any player who changed clubs mid-season. We instead
reconstruct each player's actual per-GW team from match facts (opponent_team +
was_home joined to fixtures.parquet) — immune to transfers.

Usage
-----
    python packages/fpl-grounded-assistant/scripts/backtest_fixture_difficulty.py
    python .../backtest_fixture_difficulty.py --season 2025-2026 --out report.md
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import math
import os
import sys

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGES = os.path.dirname(os.path.dirname(_HERE))

# Load the real banding engine directly from its file (bypass the heavy
# fpl_grounded_assistant/__init__.py chain), mirroring the export script.
_ENGINE_PATH = os.path.join(
    _PACKAGES, "fpl-grounded-assistant", "fpl_grounded_assistant", "fixture_outlook.py"
)
_spec = _ilu.spec_from_file_location("fixture_outlook", _ENGINE_PATH)
fixture_outlook = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(fixture_outlook)

# fpl-historical is a sibling package (not pip-installed).
sys.path.insert(0, os.path.join(_PACKAGES, "fpl-historical"))
from fpl_historical.rolling_strength import (  # noqa: E402
    STRENGTH_FIELDS,
    compute_rolling_strength,
)

SEASON_DEFAULT = "2025-2026"

# Axis -> (predicted-band column, xG outcome column, "higher-outcome-when-easy"
# direction). For attack, an EASY fixture (low band) should yield HIGH xg_for.
# For defence, an EASY fixture (low band) should yield LOW xg_against.
_AXIS_TARGET = {"attack": "xg_for", "defence": "xg_against"}


# ---------------------------------------------------------------------------
# Layer 1 — data prep
# ---------------------------------------------------------------------------

def _data_root(season: str) -> str:
    return os.path.join(
        _PACKAGES, "fpl-historical", "data", "historical", "seasons", season, "parquet_merged"
    )


def load_frames(season: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = _data_root(season)
    gw = pd.read_parquet(os.path.join(root, "player_gw_stats.parquet"))
    fixtures = pd.read_parquet(os.path.join(root, "fixtures.parquet"))
    teams = pd.read_parquet(os.path.join(root, "teams.parquet"))
    return gw, fixtures, teams


def build_team_fixture_outcomes(gw: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """One row per team-fixture with xg_for/against and goals_for/against.

    Team attribution is reconstructed from match facts (event_id,
    opponent_team, was_home) joined to fixtures.parquet — NOT from a static
    roster — so mid-season transfers can't mis-attribute a player's xG.
    """
    gw = gw.copy()
    gw["expected_goals"] = pd.to_numeric(gw["expected_goals"], errors="coerce").fillna(0.0)

    # Sum each team-fixture's own xG. Keying on opponent+venue (not the
    # player's roster team) is the transfer-proof grain.
    grp = (
        gw.groupby(["event_id", "opponent_team", "was_home"], as_index=False)["expected_goals"]
        .sum()
        .rename(columns={"expected_goals": "xg_for"})
    )

    # Label each group with its real team_id via the fixtures table.
    fx = fixtures[["event_id", "team_h", "team_a", "team_h_score", "team_a_score"]].drop_duplicates()
    home = fx.rename(columns={"team_a": "opponent_team", "team_h": "team_id"}).assign(was_home=True)
    home["goals_for"] = home["team_h_score"]
    home["goals_against"] = home["team_a_score"]
    away = fx.rename(columns={"team_h": "opponent_team", "team_a": "team_id"}).assign(was_home=False)
    away["goals_for"] = away["team_a_score"]
    away["goals_against"] = away["team_h_score"]
    label = pd.concat(
        [
            home[["event_id", "opponent_team", "was_home", "team_id", "goals_for", "goals_against"]],
            away[["event_id", "opponent_team", "was_home", "team_id", "goals_for", "goals_against"]],
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["event_id", "opponent_team", "was_home"])

    out = grp.merge(label, on=["event_id", "opponent_team", "was_home"], how="inner")

    # xg_against = the opponent's xg_for in the same fixture. Pair each row to
    # its mirror (same event, teams swapped, venue flipped).
    mirror = out[["event_id", "team_id", "was_home", "xg_for"]].rename(
        columns={"team_id": "opponent_team", "xg_for": "xg_against", "was_home": "_opp_home"}
    )
    mirror["was_home"] = ~mirror["_opp_home"]
    out = out.merge(
        mirror[["event_id", "opponent_team", "was_home", "xg_against"]],
        on=["event_id", "opponent_team", "was_home"],
        how="left",
    )
    return out


# ---------------------------------------------------------------------------
# Layer 2 — predictions per model
# ---------------------------------------------------------------------------

def _bootstrap_from_strengths(teams_df: pd.DataFrame, strengths: dict | None) -> dict:
    """Bootstrap-shaped dict for the engine. strengths=None uses the raw
    end-of-season snapshot; otherwise a per-team override (rolling model)."""
    teams = []
    for _, row in teams_df.iterrows():
        tid = int(row["team_id"])
        if strengths is not None:
            fields = strengths[tid]
        else:
            fields = {f: float(row[f]) for f in STRENGTH_FIELDS}
        teams.append({"id": tid, **fields})
    return {"teams": teams}


def _absolute_axis_thresholds(bootstrap: dict, axis: str) -> list[float] | None:
    """Equal-WIDTH thresholds over the observed strength range (the absolute
    alternative to the engine's equal-COUNT quintiles). Splits [min, max] into
    5 equal value-bands, so a clustered middle stays in band 3 and only
    genuinely extreme opponents reach 1/5 — the FDR-like concentration the
    ML0 harness suggested quintiles were destroying."""
    hf = fixture_outlook._STRENGTH_FIELDS[(axis, True)]
    af = fixture_outlook._STRENGTH_FIELDS[(axis, False)]
    pool: list[int] = []
    for team in bootstrap.get("teams", []):
        for f in (hf, af):
            v = fixture_outlook._strength_value(team, f)
            if v is not None:
                pool.append(v)
    if len(pool) < 5:
        return None
    lo, hi = min(pool), max(pool)
    if hi == lo:
        return None
    span = hi - lo
    return [lo + span * q for q in (0.2, 0.4, 0.6, 0.8)]


def _band_all(
    outcomes: pd.DataFrame, bootstrap: dict, axis: str, bucketing: str = "quintile"
) -> list[int]:
    """Band every team-fixture row on `axis` using the engine internals.

    bucketing="quintile" (default) uses the production engine's equal-count
    thresholds; "absolute" uses equal-width bins (the experiment)."""
    teams_by_id = fixture_outlook._teams_by_id(bootstrap)
    thresholds = (
        _absolute_axis_thresholds(bootstrap, axis)
        if bucketing == "absolute"
        else fixture_outlook.build_axis_thresholds(bootstrap, axis)
    )
    bands = []
    for _, r in outcomes.iterrows():
        fixture = {
            "opponent_team": int(r["opponent_team"]),
            "is_home": bool(r["was_home"]),
            "difficulty": None,  # force strength path; no per-fixture FDR here
        }
        bands.append(fixture_outlook._fixture_band(fixture, axis, teams_by_id, thresholds))
    return bands


def predict_bands(
    outcomes: pd.DataFrame, fixtures: pd.DataFrame, teams: pd.DataFrame, season: str
) -> dict[str, pd.DataFrame]:
    """Return {model_name: outcomes + attack_band/defence_band columns}."""
    models: dict[str, pd.DataFrame] = {}

    # naive — constant band 3
    naive = outcomes.copy()
    naive["attack_band"] = 3
    naive["defence_band"] = 3
    models["naive"] = naive

    # fpl_fdr — FPL's own single-axis FDR from the fixtures table
    fdr = outcomes.copy()
    # sort_index avoids pandas' lexsort-depth warning on the MultiIndex .loc.
    fdr_home = fixtures.set_index(["event_id", "team_h"])["team_h_difficulty"].sort_index()
    fdr_away = fixtures.set_index(["event_id", "team_a"])["team_a_difficulty"].sort_index()

    def _fdr(row):
        key = (row["event_id"], row["team_id"])
        src = fdr_home if row["was_home"] else fdr_away
        try:
            return int(src.loc[key]) if not isinstance(src.loc[key], pd.Series) else int(src.loc[key].iloc[0])
        except KeyError:
            return 3

    fdr_vals = fdr.apply(_fdr, axis=1)
    fdr["attack_band"] = fdr_vals
    fdr["defence_band"] = fdr_vals  # single-axis: identical both axes
    models["fpl_fdr"] = fdr

    # static — committed end-of-season snapshot, engine's quintile bucketing
    boot_static = _bootstrap_from_strengths(teams, None)
    for bucketing, label in (("quintile", "static"), ("absolute", "static_abs")):
        m = outcomes.copy()
        m["attack_band"] = _band_all(m, boot_static, "attack", bucketing)
        m["defence_band"] = _band_all(m, boot_static, "defence", bucketing)
        models[label] = m

    # Walk-forward rolling strengths, computed once per GW and shared by the
    # rolling models AND the FDR+form overlay below.
    gws = sorted(outcomes["event_id"].unique())
    rolling_by_gw = {int(g): compute_rolling_strength(season, int(g)) for g in gws}

    # rolling — walk-forward, per GW, only prior matches; both bucketings
    for bucketing, label in (("quintile", "rolling"), ("absolute", "rolling_abs")):
        m = outcomes.copy()
        m["attack_band"] = 3
        m["defence_band"] = 3
        for gw in gws:
            boot = _bootstrap_from_strengths(teams, rolling_by_gw[int(gw)])
            mask = m["event_id"] == gw
            sub = m[mask]
            m.loc[mask, "attack_band"] = _band_all(sub, boot, "attack", bucketing)
            m.loc[mask, "defence_band"] = _band_all(sub, boot, "defence", bucketing)
        models[label] = m

    # fdr_form — the overlay: anchor on FPL's FDR (the strongest base signal),
    # refine it within-band with the opponent's WALK-FORWARD rolling form on the
    # relevant side. Both signals oriented "high = harder", blended in rank
    # space (FDR is discrete 1-5; form breaks its ties). Continuous score drives
    # skill; a quantile bucketing gives comparable 1-5 bands for calibration.
    models["fdr_form"] = _overlay_model(outcomes, fdr_vals, teams, rolling_by_gw)

    return models


# Overlay blend weights (rank space). FDR is the strong base; form refines.
_W_FDR = 0.6
_W_FORM = 0.4


def _overlay_model(
    outcomes: pd.DataFrame,
    fdr_vals: pd.Series,
    teams: pd.DataFrame,
    rolling_by_gw: dict[int, dict],
) -> pd.DataFrame:
    m = outcomes.copy()
    fdr_rank = fdr_vals.rank(pct=True).to_numpy()

    for axis in ("attack", "defence"):
        # Opponent's rolling strength on the side that governs this axis, as of
        # each fixture's own GW (walk-forward). attack difficulty reads opp
        # DEFENCE quality; defence difficulty reads opp ATTACK quality.
        form = []
        for _, r in m.iterrows():
            field = fixture_outlook._STRENGTH_FIELDS[(axis, not bool(r["was_home"]))]
            opp = int(r["opponent_team"])
            strengths = rolling_by_gw.get(int(r["event_id"]), {})
            form.append(strengths.get(opp, {}).get(field, 1200.0))
        form_rank = pd.Series(form, index=m.index).rank(pct=True).to_numpy()

        score = _W_FDR * fdr_rank + _W_FORM * form_rank
        m[f"{axis}_score"] = score
        m[f"{axis}_band"] = pd.qcut(score, 5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype(int)
    return m


# ---------------------------------------------------------------------------
# Layer 3 — scoring
# ---------------------------------------------------------------------------

def _rank(xs: list[float]) -> list[float]:
    """Fractional ranks (ties share the average rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation (Pearson on ranks). 0.0 if degenerate."""
    if len(a) < 3:
        return 0.0
    ra, rb = _rank(a), _rank(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    va = math.sqrt(sum((r - ma) ** 2 for r in ra))
    vb = math.sqrt(sum((r - mb) ** 2 for r in rb))
    if va == 0 or vb == 0:
        return 0.0
    return cov / (va * vb)


def skill_correlation(df: pd.DataFrame, axis: str) -> float:
    """Signed so POSITIVE always means 'difficulty tracks outcome correctly'.

    attack: easy(low band) should give high xg_for  -> flip sign of corr
    defence: easy(low band) should give low xg_against -> keep sign

    Band-based for a uniform, apples-to-apples leaderboard (all models scored
    on their 1-5 output — also what a 5-band ticker would ship). Pass
    use_score=True to score a model's continuous `{axis}_score` instead (the
    overlay's signal ceiling, reported separately).
    """
    return _skill(df, axis, use_score=False)


def _skill(df: pd.DataFrame, axis: str, *, use_score: bool) -> float:
    col = f"{axis}_score" if (use_score and f"{axis}_score" in df.columns) else f"{axis}_band"
    corr = spearman(df[col].tolist(), df[_AXIS_TARGET[axis]].tolist())
    return -corr if axis == "attack" else corr


def calibration_table(df: pd.DataFrame, axis: str) -> pd.DataFrame:
    """Mean xG + goals per predicted band (the primary diagnostic)."""
    target = _AXIS_TARGET[axis]
    goals_col = "goals_for" if axis == "attack" else "goals_against"
    g = df.groupby(f"{axis}_band").agg(
        n=(target, "size"),
        mean_xg=(target, "mean"),
        mean_goals=(goals_col, "mean"),
    )
    return g


def band_spread(df: pd.DataFrame, axis: str) -> float:
    """Signed separation between the easy band and the hard band, oriented so
    POSITIVE = correctly discriminating.

    attack:  xg_for(band1) - xg_for(band5)     (easy should out-score hard)
    defence: xg_against(band5) - xg_against(band1) (hard should concede more)
    """
    cal = calibration_table(df, axis)
    target_means = cal["mean_xg"]
    if 1 not in target_means.index or 5 not in target_means.index:
        return float("nan")
    if axis == "attack":
        return float(target_means.loc[1] - target_means.loc[5])
    return float(target_means.loc[5] - target_means.loc[1])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt_calibration(df: pd.DataFrame, axis: str) -> str:
    cal = calibration_table(df, axis)
    lines = ["| band | n | mean xG | mean goals |", "|---|---|---|---|"]
    for band, row in cal.iterrows():
        lines.append(f"| {band} | {int(row['n'])} | {row['mean_xg']:.2f} | {row['mean_goals']:.2f} |")
    return "\n".join(lines)


def build_report(season: str, outcomes: pd.DataFrame, models: dict[str, pd.DataFrame]) -> str:
    n_tf = len(outcomes)
    lines: list[str] = []
    lines.append(f"# Fixture-difficulty evaluation — {season}\n")
    lines.append(f"Population: **{n_tf} team-fixtures** scored against team-aggregated xG.\n")

    # Descriptive: understand the data
    lines.append("## Data shape (descriptive)\n")
    home = outcomes[outcomes["was_home"]]
    away = outcomes[~outcomes["was_home"]]
    lines.append(
        f"- League mean xG-for per team-fixture: **{outcomes['xg_for'].mean():.2f}** "
        f"(std {outcomes['xg_for'].std():.2f})"
    )
    lines.append(
        f"- Home xG-for **{home['xg_for'].mean():.2f}** vs away **{away['xg_for'].mean():.2f}** "
        f"(home advantage = {home['xg_for'].mean() - away['xg_for'].mean():+.2f} xG)"
    )
    lines.append(
        f"- xG-for vs actual goals-for correlation (sanity): "
        f"{spearman(outcomes['xg_for'].tolist(), outcomes['goals_for'].tolist()):.3f}\n"
    )

    # Leaderboard
    lines.append("## Leaderboard — skill correlation (higher = better; 0 = no signal)\n")
    lines.append("| model | attack skill | defence skill | attack spread (xG) | defence spread (xG) |")
    lines.append("|---|---|---|---|---|")
    for name, df in models.items():
        a_sk = skill_correlation(df, "attack")
        d_sk = skill_correlation(df, "defence")
        a_sp = band_spread(df, "attack")
        d_sp = band_spread(df, "defence")
        lines.append(f"| {name} | {a_sk:+.3f} | {d_sk:+.3f} | {a_sp:+.2f} | {d_sp:+.2f} |")
    lines.append("")

    # Overlay's continuous-score skill — its refinement ceiling before the
    # 5-band quantization the leaderboard above applies uniformly.
    if "fdr_form" in models:
        ov = models["fdr_form"]
        lines.append(
            "_fdr_form continuous-score skill (pre-banding): "
            f"attack {_skill(ov, 'attack', use_score=True):+.3f}, "
            f"defence {_skill(ov, 'defence', use_score=True):+.3f}_\n"
        )

    # Calibration tables per model per axis
    for name, df in models.items():
        if name == "naive":
            continue  # single band, no calibration curve
        lines.append(f"## Calibration — {name}\n")
        lines.append("**Attack** (easy band should show HIGHER xG-for):\n")
        lines.append(_fmt_calibration(df, "attack") + "\n")
        lines.append("**Defence** (easy band should show LOWER xG-against):\n")
        lines.append(_fmt_calibration(df, "defence") + "\n")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=SEASON_DEFAULT)
    parser.add_argument("--out", default=None, help="Optional path to write the markdown report.")
    args = parser.parse_args()

    gw, fixtures, teams = load_frames(args.season)
    outcomes = build_team_fixture_outcomes(gw, fixtures)
    models = predict_bands(outcomes, fixtures, teams, args.season)
    report = build_report(args.season, outcomes, models)

    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n[wrote {args.out}]")


if __name__ == "__main__":
    main()
