# i133 — "GW6 blank for 20 teams": probe

**Card:** 2-3 answers or evaluator verdicts on 2026-10-03 asserted blanks that the tools
don't return today. The first step was a probe of our own comparing payload, text and
verdict. No production code changes in this branch.

## What the probe found

1. **The claim starts in the evaluator, and only in runs where it sees TOOL DATA.**
   - It appeared in 3 runs on 10-03, all with the evaluator receiving payloads (i124 C):
     - payload gate, 15:52–16:03 UTC: n=11, n=35, n=43;
     - i132 before, 18:05: n=29;
     - i132 after, 18:19: n=13.
   - The answer text repeats it only after a retry that obeys the feedback (n=43: «GW6
     figura como blank para 20 equipos»).
   - In the two earlier runs (04:24 and 15:27 UTC) the evaluator saw no payloads, and
     there is no claim.
2. **Every turn with the claim called `get_gameweek_context`.** The evaluator names it:
   - «el contexto de jornadas, que marca a Arsenal en blanco de la GW6 a la GW10»;
   - «las alertas de blank gameweek del contexto».
3. **The wording matches one exact payload.** That payload is `blank_gw_alerts` = five
   alerts (GW6…GW10, `_ALERT_HORIZON = 5`) with `count: 20`.
   - That is what `get_gameweek_context` returns when every fixture fetch in the window
     yields an empty list (reproduced offline with `fixtures={6..10: []}` → 5 × 20).
   - The retried answer of i132-after n=13 describes that same payload on its own: «marca
     a los 20 equipos … como si no jugaran entre GW6 y GW10».
   - It uses the context's window (GW6–GW10), not the GW6–GW8 window the evaluator wrote.
     So the primary was reading data, not repeating the evaluator.
4. **Today the data is clean, and the evaluator doesn't invent blanks from it.**
   - Live probe on current main (`0949503`), using the server's startup assembly
     (`assemble_captain_context`):
     - `get_gameweek_context` → `blank_gw_alerts: []`;
     - every GW6–GW10 fetch has 10 fixtures covering 20 teams;
     - `get_chip_advice` → `gameweek_type: normal`.
   - **Live reproduction** of the two real questions (prod config, evaluator ON, R=5):
     0/10 payloads with a blank, 0/10 verdicts asserting one, 0/10 texts asserting one.
     The 3 regex hits are generic advice («guárdalo para una futura jornada doble o en
     blanco»), not claims.
   - **Evaluator replay** on the recorded payloads that carry `get_gameweek_context`,
     10× each: 20/20 approved, 0 claims. An empty `blank_gw_alerts: []` is not misread.

**Conclusion:** this is not the model misreading an empty list. During the afternoon of
10-03, `get_gameweek_context` really did report every team blank for GW6–GW10 in the
local servers, while `get_chip_advice`, reading `team_fixtures` assembled at startup,
said "normal". That contradiction is what the evaluator flagged, correctly. I could not
reproduce what made the fetch come back empty: the audit doesn't store payloads, and FPL
serves good data today.

## The code fragilities that turn an empty fetch into "everyone blank"

Verified in code, not live:
- `get_gameweek_context._build_blank_double_alerts`: `blank_teams = all_teams - playing`.
  A **fetched empty list** for a future GW yields 20 blanks. The only guard is `raw is
  None`. A gameweek where all 20 teams blank doesn't happen in the real season.
- `get_fixtures_for_gw._fixture_cache` **has no TTL** and stores whatever came back, empty
  lists included. A single bad response stays for the life of the process. This fits the
  pattern of several turns in the same run carrying it.
- `get_gameweek_context` (live fetch per GW) and `get_chip_advice` (`team_fixtures` from
  startup) **read different sources**. When one goes bad, the turn contradicts itself.

## For the reviewer (policy decisions, not gates)

- (a) Treat an empty fetch for a future GW as "no data" (`None` → skipped, as an API
  error already is) instead of "20 blanks". Possibly also a threshold: a "blank" for more
  than N teams is not trusted.
- (b) Don't cache empty lists, or give `_fixture_cache` a TTL.
- (c) Have `get_gameweek_context` use the same `team_fixtures` as the chip, so there is
  one source.
- (d) Record each call's `model_view` (or a hash plus alert counts) in the audit, so the
  next anomaly like this can be diagnosed from the audit.

## Spend

- Live probe $0.018 (estimate: primary at luna + evaluator tokens priced as input).
- Evaluator replay $0.008 (38,799 tokens).
- Total ≈ $0.026.

## Artifacts

- `field-notes/artifacts/i133-blank-claims-probe-2026-10-03.jsonl`: one line per turn,
  with every evaluator call and the `model_view` of each tool it received.
- `field-notes/artifacts/i133-evaluator-replay-2026-10-03.jsonl`: 20 judgments.
- Scripts: `scripts/probe_i133_blank_claims.py`, `scripts/replay_i133_evaluator_blank.py`.
