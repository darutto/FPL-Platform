# FI-9 criterion (f) — rolling origin, gameweek by gameweek (2026-10-13)

Aggregate only: counts and rates, no names, no ids. Local output: `trial-output/runs/rolling-origin/` (names in
`detail.json`, not committed). Produced by `python -m football_intelligence.ingestion.rolling_origin RUN_DIR OUT_DIR` (packages/football-intelligence) from the frozen `gw6-final` capture and store:
**no new request**, and the whole evaluation (all five gameweeks, three modules) takes **10 s** because the feature
build (936 s, once) already cuts history strictly before each fixture's kickoff, so it serves every gameweek. Modules
unchanged. GW7 joins on Monday 19 Oct with `gw7-final`; the script takes `--gws 2 3 4 5 6 7` on that run.

For each k = 2…6, GWk is predicted from history strictly before each fixture's kickoff. **GW1 has no history before
it, so there is no base and nothing to predict: the series starts at GW2.** The GW6 row is identical to
[2026-10-12-gw6-final.md](2026-10-12-gw6-final.md) (checked). The "all" row pools the five gameweeks (it is not an
average of rates).

Reading the M2 columns: *Differ* = where module and baseline predict different roles, how often the baseline / the
module / neither is right; *Role changes* = players whose role differs from their last start: how many, in how many
the module had flagged a change beforehand (`role_change`), in how many it predicted the new role.

## M2 — role and flank against "same position as his last start"

| GW | Starters | Answers (abstains) | Like-for-like n | Role module | Role base | Flank module | Flank base | Differ: base / module / neither | Role changes: n / detected / new role predicted |
|---|---|---|---|---|---|---|---|---|---|
| 2 | 220 | 0 (220) | 0 | — | — | — | — | 0 / 0 / 0 | 0 / 0 / 0 |
| 3 | 220 | 0 (220) | 0 | — | — | — | — | 0 / 0 / 0 | 0 / 0 / 0 |
| 4 | 220 | 143 (77) | 143 | 132/143 = 92.3 % | 137/143 = 95.8 % | 43/47 = 91.5 % | 43/47 = 91.5 % | 5 / 0 / 0 | 6 / 0 / 0 |
| 5 | 220 | 157 (63) | 157 | 147/157 = 93.6 % | 149/157 = 94.9 % | 44/50 = 88.0 % | 45/50 = 90.0 % | 4 / 2 / 0 | 8 / 0 / 2 |
| 6 | 220 | 168 (52) | 168 | 153/168 = 91.1 % | 157/168 = 93.5 % | 41/54 = 75.9 % | 43/54 = 79.6 % | 7 / 3 / 0 | 11 / 1 / 3 |
| all | 1100 | 468 (632) | 468 | 432/468 = 92.3 % | 443/468 = 94.7 % | 128/151 = 84.8 % | 131/151 = 86.8 % | 16 / 5 / 0 | 25 / 1 / 5 |

## M1 — start probability and expected minutes

| GW | Evaluated | Answers (coverage) | Brier module | Brier constant | Brier raw share | MAE minutes (n) | Predicted start, did not / predicted no start, did |
|---|---|---|---|---|---|---|---|
| 2 | 495 | 216 (44 %) | 0.132 | 0.133 | 0.157 | 15.8 (195) | 34 / 0 |
| 3 | 529 | 253 (48 %) | 0.134 | 0.166 | 0.138 | 19.6 (223) | 20 / 0 |
| 4 | 529 | 273 (52 %) | 0.142 | 0.191 | 0.147 | 19.4 (229) | 19 / 0 |
| 5 | 529 | 290 (55 %) | 0.166 | 0.211 | 0.175 | 19.1 (232) | 22 / 0 |
| 6 | 529 | 308 (58 %) | 0.164 | 0.225 | 0.168 | 20.8 (248) | 16 / 2 |
| all | 2611 | 1340 (51 %) | 0.149 | 0.193 | 0.158 | 19.1 (1127) | 111 / 2 |

## M3 — agreement with the calendar

| GW | Team-fixtures | Trailing | Leading | Previous rest | Next rest | Module ok |
|---|---|---|---|---|---|---|
| 2 | 20 | 20/20 = 100.0 % | 20/20 = 100.0 % | 20/20 | 20/20 | 20 |
| 3 | 20 | 20/20 = 100.0 % | 20/20 = 100.0 % | 20/20 | 20/20 | 20 |
| 4 | 20 | 20/20 = 100.0 % | 20/20 = 100.0 % | 20/20 | 20/20 | 20 |
| 5 | 20 | 20/20 = 100.0 % | 20/20 = 100.0 % | 20/20 | 20/20 | 20 |
| 6 | 20 | 20/20 = 100.0 % | 20/20 = 100.0 % | 20/20 | 20/20 | 20 |
| all | 100 | 100/100 = 100.0 % | 100/100 = 100.0 % | 100/100 | 100/100 | 100 |

## What the series says

- **M2 cannot answer before GW4.** It needs at least 3 mapped starts: 220 of 220 starters abstain in GW2 and GW3,
  then abstentions fall 77 → 63 → 52 (GW4 → GW6), i.e. coverage 65 % → 71 % → 76 %. The baseline already answers for
  182 of 220 starters in GW2. M2's coverage keeps growing with the season but never reaches the baseline's.
- **M2 does not beat the baseline in any gameweek**: role 92.3 / 93.6 / 91.1 % against 95.8 / 94.9 / 93.5 %; pooled
  92.3 % against 94.7 %. Flank: equal in GW4, 2 points under in GW5, 3.7 under in GW6. Where they differ the baseline
  is right 16 times and the module 5 (neither 0). The earlier single-gameweek result was not an accident of GW6.
- **Role changes are where M2 could add value, and the sample is small:** 25 changes in three gameweeks; the module
  flagged one beforehand and predicted the new role in five. No claim either way.
- **M1 beats the constant from GW3 on**, and the margin widens (Brier 0.134 vs 0.166 in GW3, 0.164 vs 0.225 in GW6;
  pooled 0.149 vs 0.193). In GW2 it is a tie (0.132 vs 0.133). It is also better than the raw weighted share in every
  gameweek (pooled 0.149 vs 0.158). The constant is the *in-sample* base rate of each gameweek, a generous
  reference, so the margin is conservative. Coverage rises 44 % → 58 % with history. The large misses are almost all
  "predicted to start, did not" (111 of 113), as before.
- **M3 agrees with the calendar in every row** (100 / 100 team-fixtures, all four checks). It computes a calendar
  recomputed from the same capture, so this validates the arithmetic, not the usefulness.

## Limits

One season, five gameweeks; baseline and modules share the same Sportmonks fields; the baseline is one rule among
many (not tuned); M1 has no baseline stronger than the constant and the raw share yet ("started last match" is
the one to add under FI-10); the early gameweeks are partly an abstention story, not an accuracy story. Not
measured: value to a user. Not changed: the modules (M2 frozen during the trial).
