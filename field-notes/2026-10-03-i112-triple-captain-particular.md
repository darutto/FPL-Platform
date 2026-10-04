# i112 — triple captain gets a particular part

**Decision (Leo, 2026-10-03):** yes. Triple captain follows the i108 E3 pattern: the
code writes the verdict header and the particular sentence, and the model writes the
body in between.

## What changed

- **Tool** (`chip_advisor`):
  - `signals.top_element` gives the id of the best option.
  - `squad_fit` for triple captain crosses that id against the same squad members as
    BB/WC/FH: `captain_held` / `captain_missing`.
  - Without a team there is no fit; when the team is linked but couldn't be loaded,
    `linked_squad_error`.
  - The output schema declares the new verdicts and `top_element`.
- **Composition** (`chip_two_part`):
  - Header: `**Triple Captain — jornada X.** Mejor candidato: N.`
  - If the user named another player, the header reads
    `**Triple Captain con P — jornada X.** Mejor candidato de la jornada: N.`, because
    the tool's verdict is about P.
  - Closing sentences:
    - «tu mejor candidato para el triple capitán ya está / no está en tu plantilla»;
    - without a team, «enlaza tu equipo y te digo si tu mejor candidato ya está en tu
      plantilla» (same invite rule as the other chips, worded for one candidate);
    - load failure, «no pude cargar tu plantilla».
  - `CHIP_COMPOSITION` names triple_captain.
- **Grader / measurement:**
  - TC enters the E3 denominator.
  - Part 1 asks for the candidate (or the player asked about) to be named before the
    sentence.
  - The candidate travels in a separate row field, `chip_candidate`. It is not in
    `chip_trace`, because that projection is pinned field for field to the Jev
    shadow's (`test_i116`, and `jev_router/` is off-limits).
  - Shadow rows without `chip_candidate` are graded on the label only for TC.
    Follow-up for whoever owns the shadow.

## Which "best option"

The plan says "the top of `rank_captain_candidates`". The chip already has its own top
(`_score_outfield_players`, the one its `advice_text` names), so I use that one with its
id and checked that it matches:

| bootstrap | horizon | chip top | `rank_captain_candidates` top |
|---|---|---|---|
| frozen 2026-08-18 | GW1 / GW2 | Dasilva (103) | Dasilva (103) |
| live (current GW5) | GW6 / 7 / 8 | Groß, Groß, Schade | Groß, Groß, Schade |

From #3 on the two rankings diverge (different score inputs). The #1 matches in every
case measured, and a test pins the match on the fixture bootstrap. Using the
rank_captain_candidates top would cost a second scoring pass and could name a player
the chip's body doesn't talk about.

## Gate — E3 with TC included (14 ids × R=3, luna, frozen bootstrap, base `f2dc42a`)

| arm | total | TC (cvg-09, ad-04) | rest |
|---|---|---|---|
| team 68643 | **39/39** (0 tx, 0 forbidden) | 6/6 `captain_missing` | 33/33 |
| no team | **37/39 = 94.9 %** (0 tx, 2 forbidden) | 6/6 `invite` | 31/33 |

The 2 misses without a team are cvg-01 r0/r1: `get_my_squad` → `no_team_connected` →
`tool_result_error`, so nothing gets composed. That is i111, and it fails the same way
on main without this change (29/32 to 30/33 in the i132 runs). Every TC row passes in
both arms. `captain_held` doesn't occur with team 68643 (the top, Dasilva, isn't in that
squad), so it is covered by tests only.

**Spend:** $0.19 of a declared $0.50. That includes a first E3 run ($0.095, 39/39 in both
arms) that I discarded and re-ran. Its rows used the earlier projection (candidate inside
`chip_trace`), which breaks the parity with the shadow.

## Artifacts

`field-notes/artifacts/i112-e3-{team-68643,no-team}.jsonl`. Every row carries
`answer_text_full` (the served text), `chip_trace` and `chip_candidate`. Re-grade with
`scripts/grade_i108_chip_two_parts.py`.
