# i147 — a chip already played shows no favoured group (Leo: option A)

**Follow-up to i146.** With the Wildcard played in GW5 and the question in GW6, the read
still opened with «Grupo favorecido: Fulham». The body planned the GW20 return around
Fulham's next five gameweeks, which are GW6–10. The favoured group is this gameweek's
run, so it's the wrong planning input for a spent chip.

## Change (`chip_advisor`)

When `chip_availability.status == "used"`, the tool output drops
`signals.favoured_teams` and `signals.favoured_players` (`_USED_CHIP_HIDDEN_SIGNALS`).
- **Cut at the source**, so the model, the evaluator and the i108 header all go without
  it. The header keeps its verdict («**Wildcard — jornada poco favorable.**»).
- **ChipCard:** checked, and it never drew the group (only `signal_label` /
  `signal_value`, and for Triple Captain `top_player` / `evaluated_player`). No change
  needed.
- **Triple Captain:** its «Mejor candidato» is a candidate, not a group. Out of scope,
  unchanged.
- **Available and unknown:** byte-for-byte the same output (test: the only difference
  between used and available is the two keys).

## Gate

**Tests:** `tests/test_i147_used_chip_no_favoured_group.py`, 7 tests.
- Used drops the group and keeps the facts.
- The header keeps its verdict and has no group.
- Available and unknown keep the group.
- Only those two keys differ.
- Served by `/ask`: no group name; the available control keeps «Grupo favorecido».

**Mutation per guard:** 3/3 caught (filter applied, hide teams, hide players). Full
package 3127 passed locally.

**Live, Leo's case** (68643, `ask_v2` → `to_ask_response`, openai / gpt-5.6-luna, R=5;
before = main c2187d5 with i146). The group on this bootstrap is computed by the script
from the live data: ['FUL', 'Fulham']. The detector is self-checked on known
positives and negatives.

| arm | group names in the text | lead «Ya usaste el Wildcard…» | rejected | USD/turn |
|---|---|---|---|---|
| before | 5/5 | 5/5 | 1/5 | 0.00162 |
| after | **0/5** | 5/5 | 0/5 | 0.00093 |

i144–i146 detectors on both arms: keep-it advice 0/0, squad sentence 0/0, spent window
0/0, mixed 0/0, «pronto/temprana» 0/0.

The after bodies: «El Wildcard no está disponible esta jornada: ya lo usaste en la GW5 y
volverá en la GW20. Para la GW6, por tanto, planifica con transferencias normales.»

**E3 without regression** (14 ids × R=3, luna; before = main c2187d5):

| arm | no team | team 68643 |
|---|---|---|
| before | 38/38 | 39/39 |
| after | 39/39 | 39/39 |

0 tx, 0 forbidden openings, 0 exceptions. The no-team denominator varies by routing.
E3 has no used chips, so this change doesn't apply there.

**Spend:** $0.210 (live 0.0128 + E3 0.197).

## Artifacts

- `field-notes/artifacts/i147-used-chip-{before,after}.jsonl`.
- `field-notes/artifacts/i147-e3-{before,after}-{no-team,team-68643}.jsonl`.
