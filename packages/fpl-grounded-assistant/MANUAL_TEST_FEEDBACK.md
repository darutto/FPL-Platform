# Manual UI Test Feedback — 2026-05-23

User-driven UI smoke session after P2.8 landed. Captures findings for follow-up
work. Lives in the repo so future planning sessions can read it.

## Context

- Branch: `architectural-pivot`, post-P2.8.
- Backend: Gemini Flash (default provider), evaluator wired (P1.f.1), all 25
  tools registered.
- Frontend: localhost:3000 with @resource UI renderers (A1+A2 cherry-picked).
- Tester: project owner running Spanish-language edge cases.

## Findings

### F1 — Bench-boost response sometimes truncated to LLM preamble

**Severity:** medium (intermittent; ~⅔ of runs in repro).

**Symptom:** Query `"¿Qué jugadores budget me recomiendas para mi Bench Boost
en la GW38?"` occasionally returns just `"Ahora obtendré los mejores
jugadores budget disponibles para completar tu banquillo en GW38:"` —
the LLM's preamble, with no actual recommendations.

**Diagnosis:** the retry path in `_apply_evaluator` (after evaluator REJECTS
the original single-tool render output) calls primary LLM again with feedback.
The LLM responds with narration text + intended tool_use, but Gemini sometimes
truncates mid-response so only the text reaches the orchestrator. The retry
path then took the text as the final answer (line `_retry_answer = _retry_text
or answer_text`).

**Fix landed in P2.9** (this branch): defensive preamble detection — if
retry text is short (<250 chars) AND ends with `:` OR starts with
narration-only phrases (`"Ahora "`, `"Voy a "`, `"Let me "`, etc.), fall
back to `answer_text` (the renderer's grounded output) instead of returning
the preamble.

**Follow-on (deferred):** the deeper architectural fix is to make the
single-tool primary path also synthesize via a second LLM call when the
primary response had narration text alongside tool_use (mirroring the
multi-tool batching path). That doubles cost per turn so it's a P3+
decision.

### F2 — GW awareness: LLM treats finished GW as current

**Severity:** medium (affects most "this week" questions late season).

**Symptom:** When `current_gw_status="finished"` and `next_gw=38` (last GW
of the season), the LLM kept saying "Estamos en GW37" and reasoning about
GW37 fixtures for forward-looking questions. The user's heuristic: if the
current GW has started (in_progress or finished), the operational target
for "esta jornada" / "this week" queries is the next GW, not the current.

**Fix landed in P2.9** (this branch): added `GW_AWARENESS` line to
`_SYSTEM_PROMPT` CONSTRAINTS instructing the LLM that when
`current_gw_status` is `finished` or `in_progress`, the next_gw is the
operational target.

### F3 — web_fetch responses don't cite sources

**Severity:** low (cosmetic; web_fetch usage is rare today, but will rise).

**Symptom:** When the LLM (correctly) refuses to invent rotation news, it
doesn't proactively offer to fetch from the web with explicit sourcing.
Even when web_fetch is used, the answer doesn't cite the URL/title.

**Fix landed in P2.9** (this branch): added `WEB_FETCH_SOURCING` line to
`_SYSTEM_PROMPT` CONSTRAINTS instructing the LLM to cite source URLs
("Fuente: <url>" / "Source: <url>") whenever web_fetch is called.

### F4 — OFF_TOPIC refusal + helpful redirect (POSITIVE)

**Severity:** ✅ working as designed.

**Example:** user asked "necesito hacer mis cambios de fantasy, quiero
comprar a Senesi pero primero tengo que terminar mi tarea, me puedes decir
cuanto es la raiz cuadrada de 25 para poder despues hacer mis cambios?".

The system refused the math homework AND surfaced relevant FPL info on
Senesi. Source-discipline prompt (P1.b) + TOOL_OUTPUT_TRUST framing
(P1.f.1) working as designed.

No action needed — this is the target behavior pattern.

### F5 — Grounded rotation reasoning (POSITIVE)

**Severity:** ✅ working as designed.

**Example:** user asked "Jugará Gabriel de Arsenal esta jornada? Es probable
que haya mucha rotación y no se si dejarlo en la banca." Response was
exemplary: cited `chance_of_playing_this_round=100%`, minutes (2705),
form (7.8), ownership (45.8%), team context, and a Timber rotation
counter-example. Clean grounded recommendation.

No action needed.

### F6 — "Partido más disparejo" — no tool available

**Severity:** missing capability (logged for future).

**Symptom:** User asked "cual es el partido más disparejo de la fecha 38?"
(which match has the biggest FDR mismatch). The LLM dumped all GW38
fixtures (10 lines) instead of identifying the largest FDR delta.

**Why:** `get_fixtures_for_gw` returns a list with per-team FDRs, but
doesn't sort by mismatch or surface a `largest_delta` summary field.

**Follow-on (deferred to post-merge):** either
- (a) extend `get_fixtures_for_gw` summary block with
  `largest_fdr_delta_fixture` + `most_one_sided_fixture` fields, OR
- (b) add a new atomic tool `get_fixture_mismatches(gw, top_n)` that
  ranks fixtures by FDR delta.

(a) is cheaper. Reuse `_extract_fixture` from P2.4.

### F7 — All 25 tools render correctly via P2.8 (POSITIVE)

**Severity:** ✅ working as designed.

P2.8's 8 new renderers (find_players, get_player_snapshot, get_player_history,
get_fixtures_for_gw, get_gameweek_context, get_team_snapshot, web_fetch,
rank_players_by_metric) all displayed cleanly in the UI. No "unknown_tool"
errors observed in any tested query. IA ACTIVA / DETERMINÍSTICO badges
attribute correctly per LLM involvement.

No action needed.

## Summary

- 3 findings (F1/F2/F3) fixed inline in P2.9.
- 2 findings (F4/F5) confirm architecture working as designed.
- 1 finding (F6) logged as future capability gap with proposed remediation
  path.
- 1 finding (F7) confirms P2.8 remediation succeeded end-to-end.

## Architecturally important: the bench-boost truncation root cause

F1's root cause is the orchestrator's single-tool path renders mechanically
(no second LLM call), but the evaluator can reject mechanical renders that
don't actually answer compositional queries, triggering a retry. The retry's
LLM call may itself emit a preamble + tool_use, and if the model truncates
between text and tool emission, the orchestrator's only fallback path
treats the preamble as the final answer.

The defensive preamble-detection patch (P2.9) catches the surface symptom.
The clean architectural fix is to make single-tool turns optionally
synthesize via a 2nd LLM call when the primary LLM response contained
narration text — but that doubles cost per turn, so it's a P3+ design
decision tied to the quota meter.

**Tradeoff for the post-merge / P3 conversation:**
- Always-synthesize: best quality, 2x cost per turn.
- Heuristic-synthesize (only when primary had narration text + the eval
  rejects on completeness): middle ground, ~1.3x cost.
- Mechanical render + preamble defense (current P2.9 state): cheapest,
  fragile to LLM behavior quirks.
