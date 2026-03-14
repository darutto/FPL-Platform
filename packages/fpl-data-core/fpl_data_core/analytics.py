"""
fpl_data_core.analytics
========================
Rolling performance metrics for FPL players. Tier A — fully owned.

This is the canonical home for compute_rolling_xgi_per_90(), promoted from
stat_calculator.py where it was co-located with the Tier C discrete-stat
functions (now scheduled for retirement).

Source: captaincy-showdown/src/utils/performanceEnricher.ts::buildAggMap
        (lines 32-93) — Python equivalent of the TypeScript rolling aggregation.
        Also present in: fpl-data-core/python/stat_calculator.py (reference copy).
"""

from __future__ import annotations

import pandas as pd


def compute_rolling_xgi_per_90(
    playermatchstats_df: pd.DataFrame,
    player_id: int,
    lookback: int = 3,
) -> float:
    """Compute rolling xGI/90 for a player over the last N matches.

    Filters the DataFrame to rows where player_id matches, takes the
    most recent `lookback` rows (tail), sums xg + xa and total minutes,
    then normalises to a per-90-minute rate.

    Args:
        playermatchstats_df: DataFrame with columns:
                             - player_id  (int)
                             - xg         (float) expected goals
                             - xa         (float) expected assists
                             - minutes_played (int/float)
        player_id:           FPL player ID to look up.
        lookback:            Number of most-recent matches to include (default 3).

    Returns:
        xGI per 90 minutes as a float. Returns 0.0 if:
        - No rows exist for the player.
        - Total minutes across the lookback window is zero or negative.

    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'player_id': [1, 1, 1],
        ...     'xg': [0.5, 0.5, 0.5],
        ...     'xa': [0.3, 0.3, 0.3],
        ...     'minutes_played': [90, 90, 90],
        ... })
        >>> compute_rolling_xgi_per_90(df, player_id=1, lookback=3)
        0.8  # (1.5 + 0.9) / 270 * 90
    """
    player_rows = playermatchstats_df[
        playermatchstats_df["player_id"] == player_id
    ].tail(lookback)

    if player_rows.empty:
        return 0.0

    total_xg = player_rows["xg"].sum() if "xg" in player_rows.columns else 0.0
    total_xa = player_rows["xa"].sum() if "xa" in player_rows.columns else 0.0
    total_minutes = (
        player_rows["minutes_played"].sum()
        if "minutes_played" in player_rows.columns
        else 0.0
    )

    if total_minutes <= 0:
        return 0.0

    return float((total_xg + total_xa) / total_minutes * 90)


