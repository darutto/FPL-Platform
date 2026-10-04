# i144 — the model writes knowing the chip is spent

**Seen 2026-10-04 in prod** (Leo; team 68643 played the Wildcard in GW5 and asked in
GW6):
- i137's lead was right.
- The body under «Para planificar…» had been written without knowing the chip was spent:
  «quedan 14 jornadas…, conservarlo te permite reaccionar».
- It closed with the squad sentence «Te falta 1 jugador del grupo favorecido…».

## Change

**(a) The decision reaches the model, made in one place.**
- New module `chip_availability.py`. It holds i140's window helpers, moved verbatim
  from `final_response`, plus `decide_chip_availability()`: window rule → fallback to
  `chips_remaining` (logged) → `unknown`.
- Both `final_response._apply_squad_overrides` (the hard block and i137's lead) and
  `chip_advisor.get_chip_advice` call it. `final_response` keeps the private names as
  aliases.
- The chip tool output carries
  `chip_availability: {status: available|used|unknown, used_gw, returns_gw}`, declared
  in the schema. It is also said once in `advice_text`:
  - **used:** «already played this chip in GW5… comes back in GW20. Read this gameweek
    only as planning…; do not advise keeping, saving or playing it now»;
  - **unknown (no team):** «Whether the user still has this chip is unknown (no team
    linked): do not say it is available» — explicit, as review asked after i142;
  - **available:** «The user still has this chip in the current window».
- It replaces the old notes «whether you still have this chip available is not known to
  this system» and «which wildcard you still hold», which invited «el sistema no
  puede…».
- Prompt rule CHIP_AVAILABILITY: a used chip's read is planning for when it returns;
  unknown means never claim it is available.

**(b)** `compose_chip_answer` drops the particular squad sentence when the status is
`used`. The general header stays.

## Gate

**Tests:** `tests/test_i144_chip_availability_before_synthesis.py`, 14 tests.
- The tool output for used (with and without a return), available (used in the other
  window), unknown, and the fallback.
- Compose: the squad sentence is dropped when used and kept when available.
- Served by `/ask` (`ask_v2` → `to_ask_response`): used means i137's lead, the header
  kept and no squad sentence; available is unchanged.
- **The tool and the served block agree** in 5 scenarios (one decision).
- The i137/i140/i108/captaincy tests were adapted to the new wording, with the same
  intent.

**Mutation per guard:** 10/11 caught. The survivor was an early `if not squad_context`
return that is equivalent: the path below already gives `unknown`. I removed it.

**Live, Leo's scenario** (68643 linked, UI `squad_context` with
`chips_used` WC GW5 / BB GW2 / TC GW3 and its stale `chips_remaining`; «¿Uso el Wildcard
esta jornada?»; served by `ask_v2` → `to_ask_response`; openai / gpt-5.6-luna; R=5 per
arm; before = main bf9b63b):

| arm | opens «Ya usaste el Wildcard…» | advice to keep/save | squad sentence | rejected | USD/turn |
|---|---|---|---|---|---|
| before | 5/5 | 2/5 | 5/5 | 1/5 | 0.00119 |
| after | 5/5 | **0/5** | **0/5** | 0/5 | 0.00158 |

- All after bodies say it was used in GW5 and comes back in GW20.
- **Residue, not fixed here (proposal):** several after bodies still reason with «quedan
  14 jornadas en la ventana actual», which comes from the tool's `window_notice` for
  the window already spent. r4 mixes windows: «Para cuando regrese, la ventana actual
  sigue abierta hasta la GW19». Dropping that notice when the status is `used` is a
  small follow-up.
- **Discarded run, declared:** the first pair of runs went to **gemini-2.5-pro**
  because the local `.env` sets that provider. It showed 2/5 «unknown tool ''»,
  English bodies and cost 0 (no pricing). I re-ran forcing
  `FPL_ORCH_PROVIDER=openai FPL_ORCH_MODEL=gpt-5.6-luna`. The discarded JSONL is not
  committed.
- The live after arm ran on the pre-rebase base (without i143's rules). The E3 below
  runs on the rebased code.

**E3 without regression** (14 ids × R=3, luna, before = main 22f4721 with i143, after =
this branch rebased; same i108 grader):

| arm | no team | team 68643 | tx | forbidden |
|---|---|---|---|---|
| before | 38/38 | 39/39 | 0 | 0 |
| after | **38/38** | **39/39** | 0 | 0 |

0 exceptions in 168 turns.

## Spend

i144 live $0.0139 + E3 $0.197 (before 0.095, after 0.102) = **$0.211**.

## Artifacts

- `field-notes/artifacts/i144-used-chip-{before,after}.jsonl` (`--summary` recomputes
  from the served text).
- `field-notes/artifacts/i144-e3-{before,after}-{no-team,team-68643}.jsonl`.
