# Match facts from our own data: how much of the add-on can we compute? (2026-10-17, draft, updated Wed 21 with GW8)

Aggregates, field names and examples we wrote ourselves; no provider payloads. Own-data side is the owned FPL store plus
the public FPL fixtures API; the Sportmonks side is the pre-match `matchfacts` of the five GW7 fixtures played on
18–19 Oct (read Sat 17 Oct). The GW8 comparison waits for Sportmonks to publish GW8 facts (still 0 rows on Sat 17).

## 1. What results history the repo already holds

| Source | Seasons | What | Use for facts |
|---|---|---|---|
| Owned store `fpl-historical` `parquet_merged/fixtures.parquet` + `teams.parquet` | 2019-20 → 2025-26 (7 full seasons, 2,660 matches) | home/away team, final score, kickoff time, per-fixture `stats` (goals, cards per player) | **yes**, with club codes |
| Same store, 2018-19 | 380 matches with scores, **teams table empty** | scores keyed by that season's team ids only | not usable without a team-id map (would add an 8th season) |
| Same store, 2016-17 and 2017-18 | directories exist, **0 fixtures** | nothing | no |
| FPL fixtures API (public, live) | 2026-27 | 65 played matches so far (FPL's `finished` flag lags: GW7 is partly in) | yes, same shape |
| `fpl-tactical` Understat shots | 2025-26 only | shot-level xG with minutes | partial, one season |

**Missing for facts**: Championship, cup and European results (so the provider's `all_matches` scope and anything about
a promoted club's earlier seasons: Coventry have 6 and Hull 7 league matches in our data; the other 18 clubs have 25+);
minute of each goal outside 2025-26; corners and team shots; coach tenure; referee; 2016-19 team identity.

## 2. Recomputing the Sportmonks families

I recomputed, from our own matches only, the facts for the five pre-match GW7 fixtures and compared them with
Sportmonks. Scope compared: `league_matches` (our data is league-only), `basis=team`, last N league matches
before kickoff, split all/home/away. The provider's home/away split means "of the last N matches, those played at
home / away", which is how I computed ours.

| Family | N | Comparisons (club × split) | Equal | Differ |
|---|---|---|---|---|
| Clean sheets (`LAST_N_CLEANSHEET`) | 5 | 24 | 24 | 0 |
| | 10 / 15 / 25 | 27 each | 27 each | 0 |
| Goals scored (`LAST_N_GOALS`) | 5 / 10 / 15 / 25 | 27 each | 27 each | 0 |
| Goals conceded (`LAST_N_GOALS_CONCEDED`) | 5 / 10 / 15 / 25 | 27 each | 27 each | 0 |
| Under X.5 goals (`LAST_N_GOAL_LINE`, lines 0.5–4.5) | 5 / 10 / 15 / 25 | 45 each | 45 each | 0 |
| Head-to-head clean sheets (`CLEANSHEET`, h2h) | since 2019 | 7 | 4 | 3 |
| Over/under streak (`GOAL_LINE_STREAK`, lines 0.5–3.5) | n/a | 40 over, 40 under | 21 over, 33 under | 19, 7 |

- **Clean sheets, goals scored and conceded, over/under counts in the last 5/10/15/25: 100 % agreement** (every
  comparison equal, 0 exceptions) for the clubs with full history, including both home/away splits. The comparison
  counts differ by window because the provider omits a window the club's history cannot fill (Coventry, promoted, only
  gets the 5-match window clean-sheet row; we hold 6 league matches for them, so we would stop in the same place).
- **Head-to-head: partly.** The 3 differences are all the provider counting more (older meetings than our 2019 start).
  The 4 that agree are pairs whose history is inside our window. Fix = add 2018-19 and earlier.
- **Streak (`GOAL_LINE_STREAK`): not reproduced.** The provider numbers look like counts inside a lookback of up to
  100 matches (e.g. 91 "of 100"), not the current run, so the definition is opaque. Our literal current-run version is
  fine as a fact, but it is a different number: do not claim parity.

### Families by reproducibility (my reading of the 69 base fact families; only the first row is verified)

| Tag | Families | Count |
|---|---|---|
| **Reproducible, verified** | clean sheets, goals, goals conceded, goal line (over/under counts) | 4 |
| **Reproducible, same arithmetic, not yet checked** | BTTS, draw, loss, win, historic outcomes, most recent match, total h2h matches, winning margin, plus the win/draw/loss/unbeaten/winless/BTTS streaks | ~14 |
| **Partly** | cards (yellow/red counts and streaks, from FPL fixture stats: per-player cards summed per team, ~9 families); h2h beyond 2019 | ~10 |
| **Partly, one season only** | goal timings, early/late-goal streaks, first-to-score families (need goal minutes: Understat 2025-26) | ~10 |
| **Not reproducible** | coach records (7), referee tendencies (4), match rating, missing key players, corners/shots comparisons, duels/passes/attacks/fouls, xG comparisons, team fatigue, shooting performance | ~31 |

Counts are by type name, rounded; the card families and timing families are the ones to verify next if this path is
chosen.

## 3. Wording step (LLM, with a hard number check)

Design, not built. Input to the model: one fact as structured fields, e.g. `{club, window: 10, scope: "liga",
split: "casa", matches_in_split: 5, clean_sheets: 0, goals_conceded: 8}`. The model writes one sentence in Spanish
using digits. A deterministic check then runs on every generated sentence:

1. extract every number in the sentence (digits; "ninguno/ninguna" counts as 0);
2. each must equal one of the input numbers; and each input number must appear;
3. otherwise reject and retry once, then fall back to a plain template.

I tried this check on the four examples below and on two doctored ones: the four correct sentences pass; a sentence
with "9 goles" where the input says 8 fails (`extra: 9`), and a sentence that drops the 2 fails (`missing: 2`). Known
limit: it proves the numbers are the input's numbers, not that they are attached to the right noun (swapping two input
values passes). A second check on the unit words (goles / partidos / de liga) or a structured output would close that.

**Examples (GW8 fixtures, illustrative; numbers from our data as of Sat 17 Oct, GW7 not yet complete, so they will
shift; sentences written by hand, not model output):**

- *Man United – Bournemouth:* «El Man United no ha dejado la portería a cero en ninguno de los 5 partidos en casa de
  sus últimos 10 de liga (8 goles encajados).»
- *Arsenal – Everton:* «El Arsenal ha dejado la portería a cero en 3 de los 5 partidos en casa de sus últimos 10 de
  liga.»
- *Crystal Palace – Newcastle:* «El Crystal Palace ha encajado 12 goles en los 5 partidos en casa de sus últimos 10 de
  liga.»
- *Aston Villa – Man City:* «El Man City ha dejado la portería a cero en 2 de los 4 partidos fuera de casa de sus
  últimos 10 de liga.»

## 4. Recommendation

**Drop Match Facts Basic (€29/mo) before the 25th**, unless Leo wants one of the families we cannot compute.

- What the plan's card needs ("sin portería a cero en N partidos en casa", goals scored/conceded, over/under) is
  reproducible from the store we already own with exact agreement where we checked, and comes out in Spanish with no
  translation step.
- What the add-on adds that we cannot compute: coach and referee records, goal timings before 2025-26, rating and
  duel statistics, missing-key-player facts. None is in the plan's uses, and the facts are English-only.
- The add-on's delivery is also weaker than our own: facts appear only about 2 days before kickoff (GW8 and later: 0),
  while our numbers exist for any fixture once the previous match is played.
- Caveats: the comparison covers five fixtures and one gameweek; promoted clubs (Coventry, Hull now) lack league
  history and would need a rule (show only windows we have, or omit); the provider's `N` is fixed at 5/10/15/25 while
  we can compute any N, e.g. 8. To be confirmed Wed 21 on GW8 before the decision on Fri 23.
