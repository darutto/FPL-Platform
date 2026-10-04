# i111 — composition guard for a chip turn opened by get_my_squad with no team

**Scope (review chat, 2026-10-03):** only the composition guard, pinned on the i131c
fixture. The routing half of i111 (ad-05 never reaching `get_chip_advice`) is not here.

## The bug

The orchestrator reads a turn's `outcome` off its FIRST call. A chip question where the
model asks for the squad first, with no team linked, runs
`[get_my_squad → no_team_connected, get_chip_advice → ok]` and ends
`tool_result_error`. #364 (rule 3) already serves that turn grounded, with the chip
card. But `_compose_chip_answer` required `outcome == ok`, so the text kept no i108
header or closing sentence and opened «No puedo evaluar tu plantilla…», which is the
opening E3 forbids. Those were the only misses without a team in the i112 run (cvg-01
r0/r1).

## What changed

- `orchestrator._only_no_team_squad_failed`: true only when every non-ok call in the
  trace is `get_my_squad` with `status == no_team_connected`. Any other failure keeps the
  turn uncomposed: another tool, another status, or a call with no output.
- `_compose_chip_answer` accepts that one non-ok shape. The final-text guard still wins.
  The outcome is not changed; the harness owns the slot.
- `tests/test_i111_compose_no_team_squad.py`:
  - The real cvg-02 turn from `fixtures/i131c_squad_first_chip_turns.json`: composed,
    and its outcome is kept. Also served through `ask_v2` → `to_ask_response`, so it
    opens with the verdict and carries the chip card.
  - One test per guard: other failures, another outcome, the guard, ok turns.
  - Offline: fake client, socket blocked.
- **Falsified:** with main's `orchestrator.py`, the 3 positive tests fail and the 8
  guard tests pass.

## Gate — E3 (14 ids × R=3, luna, frozen bootstrap, base `5354db2`)

Stop rule, declared before the run:
- One run per arm, no re-runs, cap $0.25.
- Pass: the no-team arm meets the gate (≥ 0.95, 0 forbidden, 0 tx), the team arm holds
  39/39, and every get_my_squad-first chip turn is composed.

| arm | pass | forbidden | tx (denominator) | vs i112 |
|---|---|---|---|---|
| no team | **38/38** | 0 | 0 | 37/39, 2 forbidden |
| team 68643 | **39/39** | 0 | **1** | 39/39, 0 tx |

- **No team: passes.** cvg-02 r0/r2 ran `get_my_squad → get_chip_advice` and are now
  composed. cvg-02 r1 called only `get_my_squad` and never the chip, so it falls outside
  the denominator ("no_chip_call"). That is a routing miss, part of the routing half of
  i111 and not of this guard.
- **Team: the strict rule fails by one row.** The hit is cvg-02 r1, `vend:vendria`, in
  «el beneficio principal **vendría** de Ndiaye y Ballard». That is *venir*, not
  *vender*: a false positive of the `vend` stem in `opportunity_framing`. The team arm
  ends `ok` and doesn't go through the new branch, so this is model body variance, not
  this change. I don't loosen the grader after seeing the result. Proposed card:
  `vendr(ia|a|an|e)` comes from *venir*; whether to allow it is a policy decision.

**Spend:** $0.094 ($0.044 no team + $0.050 team).

## Artifacts

`field-notes/artifacts/i111-e3-{no-team,team-68643}.jsonl` (base `5354db2`). Re-grade
with `scripts/grade_i108_chip_two_parts.py`. An earlier pair measured on the pre-#365
base (`05e33b4`) was discarded: it had no TC particular part, so it can't be compared
with i112.
