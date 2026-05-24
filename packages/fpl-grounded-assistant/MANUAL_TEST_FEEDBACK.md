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

### F8 — GW phrasing imperfect (present tense should use next_gw)

**Severity:** low (cosmetic but confusing).

**Symptom:** Query "quienes son los principales blancos de rotación para
arsenal en el siguiente partido ahora que ya ganaron la premier?" Response
said "Estamos en **GW37** (la jornada ya terminó) y queda **solo GW38**".
The user expected "Estamos en GW38" since GW37 is over.

**Fix landed in P2.10** (this branch): tightened GW_AWARENESS constraint
to explicitly say "when current_gw_status==finished, refer to next_gw in
PRESENT TENSE ('estamos en GW<next>' / 'we are in GW<next>'), not to the
finished GW. The finished GW is the past; next_gw IS the now."

### F9 — Counter-assertion from training data; web_fetch not triggered

**Severity:** medium — undermines reliability on football-news queries.

**Symptom:** Same Arsenal-rotation query. User asserted "ahora que ya
ganaron la premier" (now that they've won the league). System response:
"Basándome en los datos, debo aclarar un punto importante: **Arsenal no
ha ganado la Premier League aún**." This is the LLM contradicting the
user with prior-knowledge inference, when it should:
1. Acknowledge it lacks current league standings locally.
2. USE web_fetch to verify the user's claim.
3. Adjust its rotation analysis based on confirmed reality.

The system also didn't call web_fetch despite FOOTBALL_NEWS classification
fitting the query (rotation policy in context of league position).

**Root cause:** prompt said "web_fetch only for whitelisted football/FPL
domains" — that's a CONSTRAINT (restrictive). It didn't say "USE web_fetch
when FOOTBALL_NEWS classification fires" (a DIRECTIVE). LLM read it as
"be careful with web_fetch" → never used it.

**Fix landed in P2.10** (this branch):
- New `SOURCE → TOOL MAPPING` section in `_SYSTEM_PROMPT` explicitly mapping
  FOOTBALL_NEWS → "USE web_fetch (do not infer from prior knowledge)".
- New language: "When the user asserts external facts (championship
  clinched, manager change, rotation policy, transfer news), web_fetch a
  relevant page (premierleague.com/news, bbc.com/sport/football,
  theathletic.com/football). NEVER assert counter-claims from training
  data; if unsure, fetch."
- Tweaked ungroundable-claim fallback: "Then offer to web_fetch."

**Follow-on (deferred):** the LLM still needs to construct a fetch URL.
For "Arsenal won the league?" it might fetch
`https://www.bbc.com/sport/football` (homepage) or
`https://www.premierleague.com/news`. If the LLM's URL doesn't match the
allowlist, it gets refused. A future tool `search_football_news(query)`
that returns ranked candidate URLs from allowlisted domains would make
this more robust. Logged as a future capability.

## Summary

- 5 findings (F1/F2/F3/F8/F9) fixed inline (P2.9 then P2.10).
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

---

## Adversarial Remediation Notes (P3.f — 2026-05-23)

Implemented in response to P3 Adversarial Architecture Reviewer CONDITIONAL verdict.
Four mandatory findings addressed in `fpl_server.py` and `audit.py`.

### F1 — Session path is cost-blind (HIGH)

**Decision: option (b) + (c).**

`ConversationSession.respond()` does not surface token counts (graduation debt).
Session turns are recorded as `tokens=0`, which means cost estimates for session
turns will always be 0 in the audit log — a real blind-spot for Patreon Basic
users (30 msgs/day × complex orchestrator turn could be 600K tokens vs the nominal
500K daily cap).

Two mitigations applied:

1. **`logger.warning` per session turn** (`fpl_server.py`, inside `session_ask`
   after `entry.session.respond()` returns). Production observability: the warning
   fires on every session turn and includes user_id and tier. Operators can grep
   for `"session turn recorded with tokens=0"` to estimate blast radius.

2. **`FPL_SESSION_ENABLED` env flag** (default `"true"` for backwards compat).
   Set `FPL_SESSION_ENABLED=false` to disable both `POST /session` and
   `POST /session/{id}/ask`; both return HTTP 503 with a descriptive message.
   This gives operators a kill-switch without breaking existing callers by default.

### F2 — Deterministic surface gated by quota (HIGH)

Questions starting with `@` (resource branch) or `/` (prompt branch) are
deterministic — they burn zero LLM tokens and should never be blocked by quota.

**Fix:** at the server boundary in both `POST /ask` and `POST /session/{id}/ask`,
`check_quota()` is skipped entirely when the question (after lstrip) starts with
`@` or `/`. `record_turn(tokens=0)` and `write_audit_entry` still fire, so usage
is observable, but quota-exhausted users can always access `@resource` and
`/prompt` turns.

Implementation: `_is_deterministic_prefix` flag computed before `check_quota`;
`_quota_check = check_quota(...) if not _is_deterministic_prefix else None`;
gate condition changed to `if _quota_check is not None and not _quota_check.allowed`.

### F5 — `audit.py` comment misleading (MEDIUM)

The `AuditEntry.user_id` field was documented as "anonymized" but stored raw header
values verbatim.

**Fix:** added `hash_user_id(raw_id: str) -> str` in `audit.py`:
- SHA-256 of the raw id, truncated to 16 hex chars (8 bytes entropy).
- `"anonymous"` and empty string return `"anonymous"` unchanged.
- Wired into `_extract_user_context()` in `fpl_server.py`: raw `X-User-Id` header
  is hashed once at intake; the hashed value is used as the quota counter key AND
  stored in the audit log. Raw value never persists.
- `AuditEntry.user_id` field comment updated to: `# hashed (sha256 first 16 hex
  chars), or "anonymous"`.

**Privacy vs anti-abuse tradeoff (documented):** the quota counter keys by
hashed user_id. If a user changes their `X-User-Id` (e.g. logs out/in with a
different value), the hashed id changes and they get a fresh quota bucket. This
is intentional: privacy (raw PII never stored) takes priority over perfect
anti-abuse (id pinning). Document if this becomes a concern as the platform scales.

### F8 — Silent audit write failures (LOW)


Four `except Exception: pass` sites in `fpl_server.py` swallowed audit write
failures silently.

**Fix:** changed all four sites to `except Exception as _exc:` with
`_LOG.exception("audit write failed: %s", _exc)`. The `except` still continues
(audit failure must never crash the endpoint), but production now has an observable
signal via the ERROR log level.

---

## Off-topic Defense Layers (P4)

Implemented in `architectural-pivot` branch, P4 sprint. Adds Layer D to the
existing three-layer off-topic stack and tightens the evaluator SAFE axis.

### Four-layer stack

| Layer | What it does | Where it lives |
|-------|-------------|----------------|
| A | `web_fetch` URL allowlist (11 domains) + SSRF guard | `fpl_grounded_assistant/web_fetch.py` (P2.7, commit `1044c58`) |
| B | `SOURCE_SELECTION_PROMPT` classifies queries as `OFF_TOPIC` and refuses | `fpl_grounded_assistant/llm_layer.py`, `_SYSTEM_PROMPT` (P1.b, commit `5f3dd13`) |
| C | `TOOL_OUTPUT_TRUST` defensive framing in `_SYSTEM_PROMPT` | `fpl_grounded_assistant/llm_layer.py` (P1.f.1, commit `00a1607`) |
| D | Heuristic keyword-ratio detector + evaluator SAFE-axis tightening | `fpl_grounded_assistant/off_topic.py` + `evaluator.py` (P4, this sprint) |

### Layer D: off_topic.py

`packages/fpl-grounded-assistant/fpl_grounded_assistant/off_topic.py`

Two pure functions, no LLM call, no I/O:

- `is_off_topic_response(text, *, threshold=0.5) → (bool, float, dict)`:
  Counts keyword hits from two disjoint sets (_FPL_TOPIC_KEYWORDS and
  _OFF_TOPIC_KEYWORDS). Score = off_topic_hits / (off_topic_hits + fpl_hits + 1).
  If score >= threshold → flagged. Returns (is_off_topic, score, diagnostic_counts).

- `contains_off_topic_solution(text) → bool`:
  Stricter check for the "refuse-but-answer" failure mode: True only when
  the response contains a refusal phrase AND an off-topic keyword AND an
  answer pattern (e.g. "the answer is", "= "). Catches LLM slip where it
  correctly refuses but also provides the answer anyway.

### Layer D: evaluator SAFE-axis tightening

`packages/fpl-grounded-assistant/fpl_grounded_assistant/evaluator.py`

Three changes:

1. `_EVALUATOR_SYSTEM_PROMPT` SAFE axis now explicitly documents the OFF-TOPIC
   rule with examples (recipes, math, weather, programming help, politics, etc.)
   and instructs the judge to flag SAFE=false with a specific refusal-redirect
   feedback message.

2. `EvaluatorVerdict` gains an additive `off_topic_score: float = 0.0` field.
   No existing field changed. Frozen dataclass — always reconstructed.

3. `evaluate_response()` runs `is_off_topic_response(primary_response)` AFTER
   the LLM verdict. If LLM judged SAFE=true BUT heuristic score > 0.7
   (high confidence), the verdict is overridden to SAFE=false with feedback:
   "Heuristic flagged off-topic content. Refuse off-topic; stay within FPL/football."
   The heuristic is a SAFETY NET only — the LLM's SOURCE_SELECTION (Layer B)
   is the primary classifier.

### Design constraints

- No false positives on legitimate FPL terms ("captain", "bench boost",
  "differential", etc. are all in `_FPL_TOPIC_KEYWORDS` — they increase the
  on-topic signal, never the off-topic signal).
- No new dependencies — stdlib only.
- Heuristic does NOT affect the fail-open path (client=None returns
  `_FAIL_OPEN` before any heuristic call).
- `EvaluatorVerdict` change is strictly additive.
