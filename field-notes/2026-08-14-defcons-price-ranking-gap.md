---
title: Ranking last-season defensive contribution under a price cap required 89 live API calls, no tool
found_via: user question — "best defenders under £6.0m by defensive contribution last season" — answered outside the app
captured: 2026-08-14
relevant_to: [contracts, scoring, historical, data-quality]
status: new
---

## What prompted this

A direct manager question: rank DEF players priced under £6.0m by last season's
(2025/26) defensive contribution, to inform a transfer. Answered it by hitting
the live FPL API directly — `bootstrap-static` filtered to 183 DEF under
£6.0m, then `element-summary/{id}/` for each of the 183 to read
`history_past[season_name="2025/26"].defensive_contribution`. 89 of them had
≥900 minutes and became the ranked list.

## Findings

### 1. No tool joins last-season per-player stats with current price — severity: med

**What happens:** the two candidate tools each cover half the question and
neither can be combined into the other.

- `get_player_season_points` (`get_player_season_points.py`) resolves **one
  named player** against one season's parquet and sums `total_points`,
  `minutes`, `goals_scored`, `assists`, `clean_sheets`, `bonus`,
  `points_per_game` — a fixed column list that does **not** include
  `defensive_contribution` (`get_player_season_points.py:339-355`), and it
  takes a `query` (single player name), not a filter — there is no "rank all
  DEF" mode.
- `rank_players_by_metric` (logged in
  [2026-08-06-query-primitives-gap.md](2026-08-06-query-primitives-gap.md))
  ranks across players and has price absent from its filter vocabulary, but
  it reads the **live/current-season** bootstrap only — it has no `season`
  argument and cannot reach 2025/26 history at all.

Neither gap is new in isolation — both are already logged. What's new here is
concrete confirmation that the two documented gaps (no price filter; no
season parameter) **compound**: even fixing one leaves the question
unanswerable, because no single surface has current price, a past season, and
an arbitrary metric column all at once.

### 2. The data is already in the owned store — severity: low (this part is good news)

`CUMULATIVE_COLS` in `fpl_data_core/schemas.py:33-64` lists
`defensive_contribution` as a stored column, confirmed present since the
`ab32cc6` 2025-26 schema addition. `get_player_season_points` reads from the
same `player_gw_stats.parquet` directory and simply doesn't sum that column.
Extending it (or a sibling ranking tool) to expose `defensive_contribution`
and `defensive_contribution_per_90` is a column addition, not a new data
source — unlike category D findings elsewhere in this folder, this one isn't
a modelling project.

**Evidence of the live-pull workaround, for reproducibility:** `bootstrap-static`
→ 183 DEF elements with `now_cost < 60`; `element-summary/{id}/` per element,
`history_past` entries keyed by `season_name`. Top of the resulting list
(≥900 min, 2025/26): Andersen (FUL) 329 DC / 2882 min, Collins (BRE) 319 DC,
Van Hecke (TOT) 317 DC, Alderete (SUN) 312 DC, Richards (CRY) 311 DC.

## Fix direction

Not a new category — this is a concrete instance of Category A
("Query / filtering") from
[2026-08-07-primitive-discovery-close.md](2026-08-07-primitive-discovery-close.md),
sharpened: the query layer needs **season** as a joinable dimension alongside
price and per-90 metrics, not just "current bootstrap + price". Smallest fix:
add `min_price`/`max_price` args to a season-aware ranking tool (or extend
`get_player_season_points` into a multi-player ranking mode) and expose
`defensive_contribution[_per_90]` as a summable/rankable column — no new
capture or backfill required.

## Open questions

- Whether other 2025-26-added cumulative columns (`clearances_blocks_interceptions`,
  `tackles`, `recoveries`) have the same "stored but unsummed" status in
  `get_player_season_points` — not checked individually, but the column list
  at `get_player_season_points.py:339-355` suggests all four are absent, not
  just `defensive_contribution`.
