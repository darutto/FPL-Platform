# Tool-routing confusion matrix

Measures which tool the model picks across 90 labelled Spanish questions, and
where it confuses tool-family boundaries. Independent of PR #160 (which fixed
the raw-dump *consequence*, not the routing *cause*) — this task changes no
product code, only adds a measurement harness and this report.

## Pinned configuration

- Provider/model: `openai` / `gpt-5.6-luna` (pinned in the script, not read
  from env, so a stray `FPL_ORCH_MODEL` can't silently change what was
  measured)
- Bootstrap: `field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`
  (frozen, sha256 `4cbb9fa1…ee849`, captured 2026-08-19T02:43:43Z)
- Call path: `ask_orchestrated()` directly, not the HTTP surface
- Evaluator: disabled (`_eval_client=None`) — this measures the PRIMARY
  routing decision only; the evaluator's optional retry can substitute a
  different tool and would have muddied exactly the signal being measured
- max_tokens=1024, temperature=None, top_p=None (gpt-5.6-luna rejects both
  sampling params with HTTP 400 — confirmed in an earlier PR, reproduced here)
- Repetitions: 5 per question
- Corpus: 90 questions, 450 calls, 0 harness exceptions
- **Actual cost: $0.9357** (script-computed from `primary_input_tokens` /
  `primary_output_tokens` / `primary_cache_read_tokens` at gpt-5.6-luna's
  published per-1M rates: input $0.20, output $1.20, cache_read $0.02).
  Higher than the task brief's back-of-envelope $0.66 because every
  observation here executes at least one tool (that's the point of the
  corpus), whereas the $0.00066/turn figure it was extrapolated from mixed in
  turns that called no tool at all and paid for no synthesis call.
- Suite collection count after adding the harness + 33 new tests:
  **1307 passed, 1 skipped** (baseline on this branch: 1274 passed, 1
  skipped — exactly +33, nothing else moved)

Raw observations: `field-notes/artifacts/tool-routing-observations-2026-08-23.jsonl`
(450 lines, one JSON object per call, written to disk immediately after each
call returns — before any aggregate was computed).
Computed matrix/hit-rates: `field-notes/artifacts/tool-routing-matrix-2026-08-23.json`.
Corpus + harness: `packages/fpl-grounded-assistant/scripts/{tool_routing_corpus,measure_tool_routing,analyze_tool_routing}.py`.

## Corpus and how the acceptable sets were defended

90 questions across the 7 required families (team_fixtures, player_views,
captaincy, squad_building, advice, gameweek_state, chip_vs_gameweek), split
47 unambiguous controls / 43 genuinely ambiguous questions. Each entry
carries a `note` field stating *why* its acceptable set is what it is,
grounded in the actual tool schema text (e.g. `get_chip_advice`'s own
description names the "bench boost from scratch" scenario and says to call
`build_squad` first — so any question shaped like that accepts both tools by
construction, not by guess). Where no defensible set could be produced the
question was dropped rather than included with a guessed set.

`get_player_zonal_outlook` / `get_zonal_opportunity` / `get_zonal_weakness`
never appear in any acceptable set and never appeared in the observed
results either — consistent with them being environment-broken in every
worktree (`packages/fpl-tactical/data/` is gitignored), not something this
run needed to exclude after the fact.

## Confusion matrix (first tool picked, by expected family)

| expected family    | correct-family tools (counts)                                                   | leaked to                                                                 |
|---------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| team_fixtures (70)   | get_team_snapshot 15, get_team_schedule 27, get_team_fixture_calendar 5, get_fixture_outlook 16 | get_position_fixture_run 7 |
| player_views (70)    | get_player_snapshot 26, get_player_form 22, get_player_history 12, get_player_fixture_run 5 | get_injury_list 5 |
| captaincy (60)       | get_captain_score 15, compare_players 15, rank_captain_candidates 22             | get_gameweek_context 8 |
| squad_building (70)  | build_squad 21, get_transfer_suggestion 15, rank_players_by_metric 15, select_players_within_budget 5 | get_gameweek_context 4, (no_tool) 10 |
| advice (60)          | get_transfer_advice 13, get_differential_picks 20, get_chip_advice 17           | get_gameweek_context 7, compare_players 2, (no_tool) 1 |
| gameweek_state (60)  | get_gameweek_context 28, get_current_gameweek 2, get_fixtures_for_gw 15          | web_fetch 5, (no_tool) 10 |
| chip_vs_gameweek (60)| get_chip_advice 23, build_squad 10                                               | get_gameweek_context 17, (no_tool) 10 |

Full per-question hit rates are in the matrix JSON; the ones that matter are
named below.

## The headline finding: get_gameweek_context is a general "temporal-anchor" attractor, not a narrow chip-advice confusion

The task brief framed this as a `get_chip_advice` vs `get_gameweek_context`
boundary. That boundary is real, but it is a special case of something
bigger: **`get_gameweek_context` gets picked first whenever a DECISION
question anchors itself to a specific or current gameweek** — "esta fecha",
"esta semana", "la fecha 2", "el próximo fin de semana" — regardless of what
kind of decision it is:

- captaincy: `cp-06` ("...esta semana o mejor otro?") 2/5 hit, `cp-07`
  ("...esta fecha...") 3/5 hit, `cp-11` ("...esta fecha...") 4/5 hit
- advice: `ad-04` ("...este fin de semana...") 2/5 hit, `ad-05` ("...esta
  semana...") **0/5 hit** — every single rep picked `get_gameweek_context`
  or nothing, never the two advice tools actually being asked about
- squad_building: `sb-14` ("...próximas 5 fechas...") 1/5 hit
- chip_vs_gameweek (below): the same pattern, just concentrated

Meanwhile `team_fixtures` questions use "fechas" *more* than any other
family (`"las próximas 5 fechas"` appears in half of them) and had **zero**
`get_gameweek_context` leakage. The difference isn't the word "fecha" — it's
a decision question anchoring itself to a specific gameweek. A pure
fixture-horizon question doesn't trigger it; a captain/chip/transfer
decision that happens to name a gameweek does.

**Likely mechanism** (grounded in the actual schema text, not speculation):
`get_gameweek_context`'s description ends with *"Use before reasoning about
next GW"* — a broad, generic invitation that fires on any GW mention.
`get_chip_advice`'s description never mentions gameweek numbers at all, and
neither do `get_captain_score` or `get_transfer_advice`. One tool actively
solicits itself into any GW-adjacent turn; none of the tools it competes
with defend their territory the way `get_chip_advice`'s description already
does against `build_squad` ("it does NOT build or price a squad... call
build_squad for the squad... then this tool for the chip verdict"). That
asymmetry — one generic invitation, several silent specifics — is the
actual shape of the bug, and it explains why the fix belongs in prompt/schema
text, not in tool count.

## The pinned case

> "evalúa mi equipo y qué tan buena idea es el bench boost en la fecha 2"

hit_rate_first = **0.6** (3/5), tools seen: `get_gameweek_context` ×2,
`get_chip_advice` ×3. hit_rate_any = **1.0** — even on the 2 reps where
`get_gameweek_context` went first, the SAME turn also called
`get_chip_advice` afterward (a multi-tool turn; this exists on `main`
independent of PR #160). This is a materially better ratio than the task
brief's documented 5/6-wrong baseline. Two honest possible reasons, not
adjudicated here: n=5 vs n=6 is small-sample noise in both directions, or
the original observation was made against the live `/ask` HTTP path with
different session/context framing than a bare `ask_orchestrated()` call.
Either way, the boundary is real and reproduced — it just isn't as
lopsided as the single historical run suggested, and the corpus around it
(`cvg-01` through `cvg-12`) gives a much steadier read: **33/60 (55%)**
hit-first across the whole bucket, 43/60 (72%) hit-any.

Two paraphrases isolate the variable cleanly: `cvg-04` and `cvg-05` drop the
"evaluate my squad" clause and keep only chip+GW-number — they still miss
(0.4 and 0.8 respectively, both worse than the plain chip-only controls at
1.0), confirming the GW-number mention alone, not the squad-evaluation
framing, is doing most of the pulling.

## Two other, distinct failure modes (not "wrong tool")

**No tool called at all.** `gw-05` ("¿Qué gameweek es la actual?") and
`gw-09` ("...sin nada más") both went 0/5 on `get_current_gameweek` — but
every rep answered in prose with no tool call, and that prose is very likely
*correct*: `build_orchestration_context()` injects `Current Gameweek: GWx` /
`Next Gameweek: GWx` into every system prompt unconditionally (see
`context_builder.py::_build_gameweek_section`). The model already has the
answer before the turn starts. That's not routing confusion — see the
surface-pruning verdict below, where this becomes the one concrete pruning
candidate. Separately, `cvg-02` and `sb-02`/`sb-13` also went to `(no_tool)`
5/5, but for a different, more defensible reason: they ask the model to
"evaluate my squad" or fit a budget with no actual squad/budget number
supplied, and there is no "look up my current team" tool in the 28-tool
surface — declining to call a tool it doesn't have is arguably the right
call, not a miss, though it does mean those three questions were not a clean
test of anything and should be read with that caveat rather than counted at
face value.

**Off-catalogue surface-word attractor.** `gw-04` ("¿...cuándo cierra el
mercado de fichajes?") picked `web_fetch` 5/5 — clean, specific, and
genuinely concerning: "mercado de fichajes" (transfer market) reads to the
model as a news-search trigger, not an FPL-deadline question. This is the
single cleanest wrong-tool signal in the whole corpus (100% wrong, same
wrong tool every time) and worth naming specifically as the worst offender
that isn't the known chip/gameweek boundary.

## Corpus mistakes found post-hoc (owned, not buried)

Two more "misses" turned out to be my labelling gaps, not model confusion,
found by reading what the model actually called:

- `tf-08` and `tf-12` both say "en defensa" / "para la defensa" intending
  the FDR *axis* (clean-sheet difficulty), but that phrase is equally valid
  Spanish for "for defenders" (the *position*) — and `get_position_fixture_run`
  exists to do exactly that. The model picked it consistently (7/10 combined
  reps). This is a real, defensible third reading I didn't credit; had it
  been in the acceptable set both questions would read as clean hits.
- `pv-10` ("¿Está disponible Rodri...o sigue lesionado?") went 5/5 to
  `get_injury_list`, which does answer an availability question (it lists
  exactly the non-`'a'`-status players) — a legitimate alternate strategy to
  the profile lookup I had in mind, not a wrong pick.
- `gw-01` and `gw-05` are the same underlying question ("what GW is it,
  bare") that I inconsistently labelled control vs. ambiguous — `gw-01`'s
  0.4 "miss" is really the identical over-answering behaviour `gw-05` was
  correctly scored as ambiguous for.

Net effect: the raw control mean (83.8%) understates how clean the controls
actually are. Excluding these four labelling defects (not model failures),
effective control adherence is closer to **~90%**, with `gw-04`'s web_fetch
pick standing alone as the one real, unambiguous control failure.

## Did the controls hold?

Mostly yes. Of 47 controls, 5 scored 0% hit-rate; of those, 3 are corpus
labelling defects (above) and 1 (`gw-09`) is a defensible no-tool response.
Only **`gw-04` is a genuine, clean control failure** — a specific and
fixable one (the "mercado de fichajes" phrase), not evidence of something
structurally worse. That the controls survive this well is itself useful:
it means the ambiguous-question misses documented above really are boundary
confusion, not the model failing at things it should trivially get right.

## Surface-pruning verdict

**This evidence does not support pruning the 28-tool surface broadly.**
Every tool in the registry got picked correctly at least once when a
question's phrasing genuinely matched it, including the narrowest ones
(`rank_captain_candidates`, `select_players_within_budget`,
`get_differential_picks`, `get_position_fixture_run` all hit 100% on their
own controls). Nothing showed zero legitimate use.

**It does support one narrow, specific deletion candidate: `get_current_gameweek`.**
Its entire payload — current GW number, next GW number — is unconditionally
present in every system prompt already (`context_builder.py`,
`_build_gameweek_section`), independent of any tool call. The two questions
built to need exactly that tool (`gw-01`/`gw-05`, `gw-09`) show the model
already answering correctly from context alone, without calling it, in the
majority of reps. Removing it would not remove a capability — the model
already has the information — it would just stop offering a redundant
6,300-token-surface entry whose entire answer duplicates always-on context.
`get_gameweek_context` is NOT the same case: its blank/double-GW alerts
cover a 5-GW forward window the injected context does not (which only
covers the *current* GW's type), so it stays.

What would settle this further: re-run this same corpus (or just the
`gameweek_state` + `chip_vs_gameweek` buckets) with `get_current_gameweek`
removed from the offered tool list, and confirm the two bare-GW questions
still resolve correctly from context with no regression elsewhere. That is
a cheap, single-tool experiment, not a reason to defer a verdict on the
other 27.

## What this does NOT do

No prompt text, schema description, or tool was changed. The
`get_gameweek_context` "Use before reasoning about next GW" asymmetry
identified above is the mechanism, not a fix — arguing and shipping that fix
belongs in its own PR, argued from this matrix, not bundled with it.
