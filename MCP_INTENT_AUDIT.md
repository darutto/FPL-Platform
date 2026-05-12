# MCP_INTENT_AUDIT.md

Phase M0 — Intent Audit and Capability Mapping
Branch: `MCP_architecture`
Author: Intent Audit Agent (read-only inspection; no code changes)
Date: 2026-05-11

---

## 1. Context

The deterministic FPL assistant is feature-complete: the validation harness reports **106/106 PASS** across CLI, HTTP, and session surfaces (`packages/fpl-grounded-assistant/validation_report.md` line 7; `validation_results.json:2-5`). The product weakness is not the deterministic core — it is the fragility of the input boundary (`router.py`) when users phrase questions outside known templates, especially in Spanish.

The MCP_architecture branch adds an outer interaction layer (Normalizer → DecisionRouter → `@`-Resources / `/`-Prompts / `route()` / orchestrator fallback) on top of today's deterministic pipeline. This audit is the M0 gate: **M1 cannot start without Lead approval of this document**. Its job is to (a) inventory every supported intent backwards from the existing capability surface, (b) assign each intent to a primary surface using the four rules in the plan, and (c) confirm or adjust the proposed six-resource M1 set.

## 2. Methodology

Read-only inspection of the following files (line citations used throughout):

- `packages/fpl-grounded-assistant/fpl_grounded_assistant/dispatcher.py` — `INTENT_*` constants (lines 72–90), `SUPPORTED_INTENTS` frozenset (92–110), `_HINT_CANONICAL_TEMPLATES` / `INTENT_HINT_ALLOWLIST` (127–138), `_TOOL_TO_INTENT` (158–176), `INTENT_MANIFEST` (183–316).
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/router.py` — full file (1755 lines). Key tables: `_CHIP_KEYWORDS` (113–126), `_CHIP_ADVISORY_PHRASES` (129–175), `_SPANISH_NAME_PREFIXES` (185–189), `_TRANSFER_PREFIXES` (207–215), `_COMPARE_PREFIXES` (223–233), `_RANK_PREFIXES` (258–286), `_CAPTAIN_SCORE_PREFIXES` (297–316), `_SUMMARY_PREFIXES` (318–366) including Spanish injury-check phrases, `_RESOLVE_PREFIXES` (368–385), `_PLAYER_FORM_*` (436–475), `_INJURY_LIST_KEYWORDS` (490–509), `_PRICE_CHANGES_KEYWORDS` (516–546), `_TEAM_CALENDAR_*` (557–621), `_POSITION_*` (629–699), `_TEAM_SCHEDULE_*` (707–762), `_FIXTURE_RUN_*` (794–823), `_TRANSFER_SUGGESTION_*` (859–907), `_DIFFERENTIAL_KEYWORDS` (916–937), `_GAMEWEEK_KEYWORDS` (940–952). Dispatch order in `route()`: 1623–1755 (chip → position_fixture_run → team_calendar → team_schedule → gameweek → rank → compare → transfer → transfer_suggestion → fixture_run → differential → price_changes → injury_list → player_form → captain_score → summary → resolve).
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/intent_classifier.py` — classifier system prompt (94–266), 0.7 confidence threshold (53). Classifier allowlist covers 14 intents (every intent except `multi_intent`, `position_fixture_run`, and the chip/transfer/etc. intents that lack their own block are absent — see line items below).
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/tool_schema_registry.py` — only the **original 10 tool schemas** are registered (`_ALL_SCHEMAS` lines 380–391); the seven Phase-2.6 tools (`get_player_form`, `get_injury_list`, `get_price_changes`, `get_team_fixture_calendar`, `get_team_schedule`, `get_position_fixture_run`, `get_transfer_suggestion`) are **not** in the schema registry.
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/injury_list.py` — bootstrap source for `@injuries` (full file). Uses `el.get("status")` and `chance_of_playing_this_round`; **does not currently read `news_added`**.
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/price_changes.py` — uses `cost_change_event` (line 105) and exposes it on each entry.
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/differential_picks.py` — uses `selected_by_percent` (line 201).
- `packages/fpl-grounded-assistant/validation_report.md` and `validation_results.json` — 106 scenarios listed (header line 7); per-scenario rows lines 13–115.
- `packages/fpl-ui/lib/slash-commands.ts` — six Spanish slash commands `/capitan`, `/comparar`, `/transferencia`, `/calendarios`, `/diferenciales`, `/chips` (lines 35–72).
- `packages/fpl-ui/lib/types.ts` — `INTENT_HINT_ALLOWLIST` (lines 104–112), `SUPPORTED_INTENT_VALUES` (65–77) — UI lists only the original 10 intents + `multi_intent`; the seven Phase-2.6 intents (`player_form`, `injury_list`, `price_changes`, `team_fixture_calendar`, `team_schedule`, `position_fixture_run`, `transfer_suggestion`) are **not exposed to the UI type system**.

Evidence sources for the stability column: (a) coverage in the 106-scenario corpus (e.g. `player_form` has 9 dedicated scenarios; `differential_picks` has 4 incl. error-outcome scenarios; `position_fixture_run` has 3; `team_schedule` has 3), (b) breadth of Spanish phrasings already in router prefix tables, (c) presence in the classifier prompt allowlist, (d) presence in `INTENT_MANIFEST`.

---

## 3. Intent Inventory

The agent definition (`.claude/agents/intent-audit-agent.md` line 27 referencing project memory) and the user request name **18 supported intents**. The current code has **17** in `SUPPORTED_INTENTS` (`dispatcher.py:92-110`) plus `INTENT_MULTI_INTENT` declared at line 80 but **not** added to the frozenset. `INTENT_MULTI_INTENT` is, however, a legitimate response intent value (UI `SUPPORTED_INTENT_VALUES` includes `'multi_intent'` at `types.ts:76`) and `multi_intent.py` exists. So functionally there are 18 intents the system can return.

Three drifts from project memory to flag immediately:

- **`INTENT_MULTI_INTENT` missing from `SUPPORTED_INTENTS` frozenset.** Constant declared (`dispatcher.py:80`) but excluded from the frozenset. Likely intentional (multi-intent is composed of sub-intents and dispatched via a separate path) but worth confirming before any new code keys off `SUPPORTED_INTENTS`.
- **`INTENT_MANIFEST` is stale.** It carries only the original 10 intents (`dispatcher.py:183-316`); the seven Phase-2.6 intents are absent from the manifest dict. New code that relies on `INTENT_MANIFEST` to enumerate "what the system supports" will under-count by 7.
- **`tool_schema_registry._ALL_SCHEMAS` only carries the original 10 tools** (`tool_schema_registry.py:380-391`). The seven Phase-2.6 tools (`get_player_form`, `get_injury_list`, `get_price_changes`, `get_team_fixture_calendar`, `get_team_schedule`, `get_position_fixture_run`, `get_transfer_suggestion`) are absent. **Material consequence for M3:** `ask_orchestrated()` can therefore only call the original 10 tools today — the LLM orchestrator surface is missing the seven newer intents. M3 wiring must either extend the schema registry or accept this gap.

| # | Intent | Tool | Stability | Spanish coverage | Frequency hypothesis | User job | Best surface | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | `captain_score` | `get_captain_score` | green | good (`router.py:308-316` Spanish prefixes; multiple Spanish corpus scenarios e.g. `spanish_captain_score_named`, `clarification_captain_score_medium`) | **high** | "¿Debo capitanear a X?" | **`/prompt` (`/capitan`)** primary; `text+route()` secondary | Single-arg workflow. Already shipped as slash command. `intent_hint` allowlisted. |
| 2 | `rank_candidates` | `rank_captain_candidates` | green | good (`_RANK_PREFIXES` 274–286 covers `quién debería capitanear`, `ranking de capitanes`, `capitán para esta semana`) | high | "¿A quién capitaneo esta semana?" | **`text+route()`** primary; `/clasificacion` prompt secondary (plan M2) | Zero-arg in the natural flow (dispatcher auto-builds candidates list `dispatcher.py:374-391`). No need to gate as `/prompt`. Resource form (e.g. `@top_captains`) is tempting but excluded from M1 scope — could land in a later phase. |
| 3 | `current_gameweek` | `get_current_gameweek` | green | partial — English only (`_GAMEWEEK_KEYWORDS` 940–952 has no Spanish variants; classifier prompt provides Spanish coverage at 171–174) | low | "¿En qué jornada estamos?" | **`text+route()`** | Trivial, deterministic, no args. Not worth promoting to a resource or prompt. Spanish coverage relies on classifier fallback. |
| 4 | `player_summary` | `get_player_summary` | green | good (`_SUMMARY_PREFIXES` 342–366 has rich Spanish: `dame un resumen de`, `precio de`, `está lesionado`, `está disponible`, `puede jugar`) | high | "Háblame de X" / "¿Está disponible X?" / "Precio de X" | **`text+route()`** primary | Could later get a `/jugador {name}` prompt but **not in M2 scope** (not in the 7 slash commands listed in the plan). Single-arg with rich free-text phrasings — route works well. |
| 5 | `player_resolve` | `resolve_player` | green | partial — no dedicated Spanish prefixes; relies on `find`, `who is`, `lookup`, etc. | low | "¿Quién es X?" | **`text+route()`** | Lowest-product-value intent (mostly a debugging surface). Do not promote. |
| 6 | `compare_players` | `compare_players` | green | good (`_COMPARE_PREFIXES` 223–233 `compara`, `comparame`; `_COMPARE_CONNECTORS` 235–244 `y`, `e`, `contra`, `con`) | high | "¿X o Y?" | **`/prompt` (`/comparar`)** primary; `text+route()` secondary | Two-arg workflow with `a != b` validation. Already a slash command. |
| 7 | `transfer_advice` | `get_transfer_advice` | green | partial — English prefixes (`_TRANSFER_PREFIXES` 207–215 all English); Spanish coverage in classifier prompt (148–151) but not in router. `_TRANSFER_CONNECTORS` is English (`for`, `with`, `and bring in`) | high | "¿Vendo X por Y?" | **`/prompt` (`/transferencia`)** primary; `text+route()` secondary | **Spanish fragility hot spot.** Phrases like "véndele Salah por Palmer" or "cambio Bruno por Foden" do not route deterministically and depend on classifier rewrite. Flagged in Section 7. |
| 8 | `chip_advice` | `get_chip_advice` | green | good (rich Spanish in both `_CHIP_KEYWORDS` 116–117 — `triple capitán`/`triple capitan` — and `_CHIP_ADVISORY_PHRASES` 149–175 including `debería usar`, `vale la pena`, `ya usé`, `es buen momento`, `usar mi`) | medium | "¿Activo el TC esta jornada?" | **`/prompt` (`/chips`)** primary; `text+route()` secondary | Enum-bounded arg (`{tc, wc, bb, fh}`) makes it a textbook prompt. Already a slash command. |
| 9 | `player_fixture_run` | `get_player_fixture_run` | green | **poor** — `_FIXTURE_RUN_PREFIXES`/`_FIXTURE_RUN_SUFFIXES` are English only (`router.py:794-823`); no Spanish coverage in router. Classifier prompt has English-only examples (178–181). | high | "Calendario de X" / "Próximos partidos de X" | **`/prompt` (`/calendarios`)** primary; `text+route()` secondary | **Spanish fragility hot spot.** Slash command surface masks this gap; bare-text Spanish (`calendario de Haaland`, `próximos 5 de Saka`) will miss. Flagged in Section 7. |
| 10 | `differential_picks` | `get_differential_picks` | green | partial (English keywords only `_DIFFERENTIAL_KEYWORDS` 916–937; word `diferenciales` reaches via slash command label, not router) | medium | "Diferenciales esta semana" | **`/prompt` (`/diferenciales`)** primary; **`@differentials` resource** secondary (per plan M1 optional list line 207) | Zero/optional-arg in natural use; could plausibly also be a resource. Plan defers `@differentials` past M1 (optional addition once table contract is set). |
| 11 | `player_form` | `get_player_form` | **yellow** | good (rich Spanish in `_PLAYER_FORM_*` 436–475 including accent-insensitive matching; 9 dedicated corpus scenarios) | medium | "¿Cómo ha estado X en las últimas N?" | **`text+route()`** primary | Not in `INTENT_MANIFEST`, not in `tool_schema_registry`, not in UI `SUPPORTED_INTENT_VALUES`. **Stability marked yellow not because routing is fragile — it's actually well-tested (9 corpus scenarios) — but because the intent is invisible to downstream layers** (manifest/UI/orch). Routing itself is strong. No prompt for it in the plan's M2 set. |
| 12 | `injury_list` | `get_injury_list` | yellow | good (`_INJURY_LIST_KEYWORDS` 490–509 has 12 Spanish phrases) | high | "¿Quién está en duda esta jornada?" | **`@injuries` resource** primary; `text+route()` secondary | Zero-arg, read-only, list-form — canonical resource shape. **Confirmed for M1.** Same manifest/schema-registry/UI-types gap as `player_form`. |
| 13 | `price_changes` | `get_price_changes` | yellow | good (`_PRICE_CHANGES_KEYWORDS` 516–546 has 20+ Spanish/English phrases) | medium | "¿Quién subió/bajó de precio?" | **`text+route()`** primary; **`@prices` resource** secondary (plan's optional addition line 206) | Zero-arg, list-form — also a natural `@resource`. Plan marks `@prices` as an "optional addition once table contract is set" — keep secondary for now. |
| 14 | `team_fixture_calendar` | `get_team_fixture_calendar` | yellow | good (`_TEAM_CALENDAR_*` 557–621 has rich Spanish: `mejor calendario`, `peor calendario`, etc.) | medium | "¿Qué equipos tienen mejor/peor calendario?" | **`text+route()`** | Has a horizon arg but auto-extracts; not a typical prompt workflow. Could theoretically become an `@top_fixtures` resource but plan defers. |
| 15 | `team_schedule` | `get_team_schedule` | yellow | good (Spanish prefixes 707–713 `calendario del`, `partidos del`, `fixtures del`; full team alias table 720–751) | medium | "Calendario del Arsenal" | **`text+route()`** | Entity-style (a team is an entity). Plan explicitly excludes entity resources from M1 (line 191). Already routes well in both languages. |
| 16 | `position_fixture_run` | `get_position_fixture_run` | yellow | good (`_POSITION_WORDS` 629–649 covers both languages; `_POSITION_CALENDAR_PREFIXES` 651–678 mixes both) | low | "¿Qué defensas tienen mejor calendario?" | **`text+route()`** | Niche query shape; routing already handles it. Not a candidate for prompt or resource. |
| 17 | `transfer_suggestion` | `get_transfer_suggestion` | yellow | good (rich Spanish: `a quién fichar`, `jugadores del {team}`, `dame mediocampistas de chelsea baratos`, `precio menor a`, `no más de`; `_TRANSFER_SUGGESTION_PREFIXES` 877–896, `_SPANISH_IMPERATIVE_LEADS` 907, `_BUY_SUFFIXES` 859–874) | medium | "¿A quién fichar como MID?" / "Delanteros baratos del Liverpool" | **`text+route()`** primary | Multi-arg (position, team, price, horizon) — looks like a prompt candidate, but the natural-language phrasings are so well-tested in the corpus (12 dedicated scenarios `transfer_suggestion_*`) that text routing is the better primary. Could become a `/fichar` prompt later. |
| 18 | `multi_intent` | n/a (sub-dispatcher) | green | n/a — depends on sub-intent coverage | low | "¿Qué jornada es y qué tal Salah?" | **`text+route()`** (sub-dispatches into other intents) | Cannot be a resource or prompt — it's a composition surface. Excluded from `SUPPORTED_INTENTS` frozenset (see drift note above). 3 corpus scenarios. |

Legend recap:
- green = present in INTENT_MANIFEST, tool_schema_registry, UI types, and well-tested.
- yellow = well-tested in router/corpus but **invisible to one or more downstream layers** (manifest/orch schema/UI types). Routing is not the problem; surface visibility is.
- red = not present in this audit.

**Note on "yellow" semantics (added post-Adversarial Review, 2026-05-11):** In conventional reading, "yellow" implies *routing fragility*. In this audit it specifically means **downstream-surface invisibility** — the deterministic route is strong (corpus-validated), but one or more of `INTENT_MANIFEST` / `tool_schema_registry._ALL_SCHEMAS` / `packages/fpl-ui/lib/types.ts::SUPPORTED_INTENT_VALUES` does not list the intent. The user-facing route works today; the **orchestrator and any manifest-iterating downstream consumer** will under-count or fail to dispatch. The blockers for resolving this at M3 are tracked in `MCP_M3_BLOCKERS.md`.

---

## 4. User-Job Clusters

The clusters below mirror the plan's example clusters (line 267) and are derived from the 18 intents:

### Cluster A — "Quién está caliente / quién no juega" (who's hot, who's out)
- Intents: `injury_list`, `player_form`, `price_changes`, `differential_picks`, `player_summary` (injury-check phrasings).
- Candidate surfaces: `@injuries`, `@top_form`, `@top_points`, `@top_minutes`, `@top_xg`, `@popular` (M1 six) + `@prices` (optional).
- Why: read-only, ranked/list shape; mid-week status checks.

### Cluster B — "Capitanía esta semana" (captaincy)
- Intents: `captain_score`, `rank_candidates`.
- Candidate surfaces: `/capitan {player}` prompt (single-arg), plus `text+route()` for "top captains this week" (`rank_candidates`). `@top_points`/`@top_form` complement.
- Notes: chip-related TC discussions land in `chip_advice` (Cluster F), not here.

### Cluster C — "Comparativas" (head-to-head)
- Intents: `compare_players`.
- Candidate surfaces: `/comparar {a} {b}` prompt; `text+route()` for "X vs Y".

### Cluster D — "Movimientos de mercado" (transfers)
- Intents: `transfer_advice`, `transfer_suggestion`.
- Candidate surfaces: `/transferencia {out} {in}` prompt for the sell-X-for-Y workflow; `text+route()` for buy-target ranking (`transfer_suggestion`) because its natural Spanish phrasings are richer than a prompt can capture.

### Cluster E — "Calendarios y dificultad" (fixtures and difficulty)
- Intents: `player_fixture_run`, `team_fixture_calendar`, `team_schedule`, `position_fixture_run`.
- Candidate surfaces: `/calendarios {player} [horizon]` prompt (direct dispatch per plan line 174) covers the player view; team/position views remain `text+route()`. Plan mentions a possible `@top_fixtures` resource later (line 270).

### Cluster F — "Chips"
- Intents: `chip_advice`.
- Candidate surfaces: `/chips {chip}` prompt with enum validation. No resource counterpart (chip advice is contextual, not list-shaped — plan line 272).

### Cluster G — "Diferenciales"
- Intents: `differential_picks`.
- Candidate surfaces: `/diferenciales [threshold] [top_n]` prompt (direct dispatch); secondary `@differentials` resource later.

### Cluster H — "Identidad y meta" (identity, meta)
- Intents: `current_gameweek`, `player_resolve`, `player_summary`.
- Candidate surfaces: pure `text+route()`. Trivial, no promotion needed.

### Cluster I — Composite
- Intents: `multi_intent`.
- Surface: `text+route()` (sub-dispatches). Cannot be promoted to a single prompt/resource.

---

## 5. Surface-Assignment Table (decision artifact)

This is the audit's decision output. Surface rules from plan lines 276–280 applied per intent.

| Intent | Primary surface | Secondary surfaces | Rationale |
|---|---|---|---|
| `captain_score` | `/prompt` (`/capitan`) | `text+route()` | Single required arg `player`, common workflow, already shipped. Rule: prompt = stable deterministic intent with required args. |
| `rank_candidates` | `text+route()` | `/prompt` (`/clasificacion` from plan M2) | Zero-arg in practice (auto candidates). Router phrasings are robust. Prompt only needed for optional `n`. |
| `current_gameweek` | `text+route()` | — | Argument-free, low-frequency, trivial route. Not list-shaped — not a resource candidate. |
| `player_summary` | `text+route()` | — | Rich free-text phrasings; not a clean prompt fit (the arg is just a name). |
| `player_resolve` | `text+route()` | — | Low product value; mostly a debug surface. |
| `compare_players` | `/prompt` (`/comparar`) | `text+route()` | Two required args with `a != b` validation. Already shipped. |
| `transfer_advice` | `/prompt` (`/transferencia`) | `text+route()` | Two required args with `out != in` validation. Spanish router coverage is partial — prompt path bypasses that risk. |
| `chip_advice` | `/prompt` (`/chips`) | `text+route()` | Enum-bounded arg. Already shipped. |
| `player_fixture_run` | `/prompt` (`/calendarios`) | `text+route()` | Required player arg + optional horizon. **Direct-dispatch prompt** (plan line 174) — text expansion would lose the integer horizon. Spanish router coverage is poor; prompt is the safer primary. |
| `differential_picks` | `/prompt` (`/diferenciales`) | `@differentials` resource (deferred per plan) | Zero/optional args, but direct-dispatch lets `threshold`/`top_n` carry typed. |
| `player_form` | `text+route()` | — | Router coverage is excellent (Spanish + accent-insensitive). No prompt in plan M2 set. Could become `/forma {player} {n}` later. |
| `injury_list` | **`@resource` (`@injuries`)** | `text+route()` | Read-only, zero-arg, list output. Textbook resource. **M1.** |
| `price_changes` | `text+route()` | `@prices` resource (plan optional addition) | Resource shape is correct, but plan explicitly defers to "once the table contract is set". |
| `team_fixture_calendar` | `text+route()` | — | Has a horizon arg; not list-shaped enough to be a clean argument-free resource. |
| `team_schedule` | `text+route()` | — | Entity-style (team name = entity). Plan excludes entity resources from M1 (line 191). |
| `position_fixture_run` | `text+route()` | — | Niche, fully covered by router. |
| `transfer_suggestion` | `text+route()` | — | Multi-arg but natural phrasings are so well-tested (12 corpus scenarios) that the router is the better primary. Promoting to a prompt would lose Spanish ergonomics. |
| `multi_intent` | `text+route()` | — | Cannot be promoted; composition only. |

**Orchestrator-only intents:** None. Every supported intent has a deterministic primary surface. The `text→orchestrator` path stays a strict fallback for open prose that misses both `route()` and `classify_intent_llm()` — consistent with plan line 280.

---

## 6. M1 Resource-Set Verdict

Proposed M1 resources (plan lines 194–203): `@injuries`, `@top_form`, `@top_xg`, `@top_points`, `@top_minutes`, `@popular`.

| Shortcut | Verdict | Bootstrap field(s) | Notes / open questions |
|---|---|---|---|
| `@injuries` | **Confirmed, with a caveat** | `element.status` (`!= "a"`), `element.chance_of_playing_this_round`; **recency field UNCONFIRMED** | See subsection below. |
| `@top_form` | **Confirmed** | `element.form` (string-float in bootstrap; cast as in `dispatcher.py:390`) | Reuses `player_form` rank semantics. Thin wrapper. |
| `@top_xg` | **Confirmed** | `element.expected_goal_involvements` (and/or `expected_goal_involvements_per_90`) | Plan says "per 90"; M1 must pick one (raw vs per_90). Recommend `expected_goal_involvements_per_90` because raw values privilege high-minute players. |
| `@top_points` | **Confirmed** | `element.total_points` | Simple sort. |
| `@top_minutes` | **Confirmed** | `element.minutes` | Simple sort. Useful as a starter signal. |
| `@popular` | **Confirmed** | `element.selected_by_percent` (string-float, see `differential_picks.py:201`) | Already a known bootstrap field. |

### `@injuries` recency-field investigation

Plan line 198 calls out the open question: which bootstrap field is authoritative for "most recent status change". Searched the codebase (`Grep` `news_added|news_added_str`) — **the field is not referenced anywhere in the current code**. `injury_list.get_injury_list()` does not order by recency; it groups by status only (`injury_list.py:108-129`).

Per public FPL API behavior (not currently relied on in our code), each `bootstrap.elements[i]` typically carries:
- `news` (string): the latest news blurb, e.g. "Knock - 75% chance of playing".
- `news_added` (ISO-8601 string or null): timestamp of when that news was added.
- `chance_of_playing_this_round` / `chance_of_playing_next_round` (int or null).
- `cost_change_event` (signed int, tenths of £) — **not a status-change signal**; it's a price-change signal and would be wrong for `@injuries`.

**Recommendation:**
1. Sort by `news_added` (ISO-8601 lexicographic = chronological) descending when present.
2. Tie-break / fallback by `chance_of_playing_this_round` ascending (lower chance first).
3. Last-resort fallback: preserve element-update order (the input list order from the bootstrap).

**Action required before M1 can implement `@injuries` recency:** the M1 Resource Surface Agent must verify against a live bootstrap snapshot that `news_added` is consistently present on injured/doubtful elements. If it is not (e.g. tour-stale snapshots, FPL pre-season), the fallback must remain robust. `cost_change_event` is explicitly **not** the right field for "most recent status change" — flag in plan if anyone proposes it.

### Adjustments proposed: **none** to the six-resource list itself.

The plan's six are well-chosen against the surface-selection rules: all are read-only, all are argument-free, all are stable list/dashboard shapes over bootstrap fields that are demonstrably present in current code paths (`form`, `total_points`, `minutes`, `selected_by_percent`, `status`). The only adjustment requested is the `news_added` confirmation step above before `@injuries` ships.

One nice-to-add I considered but recommend deferring per the plan's own discipline (plan lines 206–208): `@prices` and `@differentials` are natural members of the same shape and reuse existing tools (`get_price_changes`, `get_differential_picks`) — but they are explicitly "optional additions once the table contract is set" and adding them in M1 would widen scope.

---

## 7. Ambiguity Hot Spots & Spanish Fragility

Concrete failure-prone phrasings, drawn from inspection of router prefix tables and the corpus. Each item names the function or table that would need to extend.

### High risk (no deterministic route today; depends on classifier)

1. **Spanish transfer-advice prose.**
   - Examples: "véndele Salah por Palmer", "cambio Bruno por Foden", "doy de baja a Saka por Palmer", "saco a Bruno por Foden".
   - Today: `_TRANSFER_PREFIXES` and `_TRANSFER_CONNECTORS` (`router.py:207-221`) are English-only. Spanish phrasings fall through to classifier rewrite.
   - Fix vector: extend `_TRANSFER_PREFIXES` with Spanish (e.g. `"vendo"`, `"saco a"`, `"doy de baja"`, `"cambio"`) and `_TRANSFER_CONNECTORS` with `" por "`, `" por el "`. **Owner: M4 (Spanish Hardening Agent).**

2. **Spanish player-fixture-run prose.**
   - Examples: "calendario de Haaland", "próximos 5 de Saka", "qué partidos tiene Salah", "siguientes partidos de Palmer".
   - Today: `_FIXTURE_RUN_PREFIXES` / `_FIXTURE_RUN_SUFFIXES` (`router.py:794-823`) are English-only.
   - Fix vector: extend with Spanish prefixes `"calendario de"`, `"próximos partidos de"`, `"siguientes partidos de"`. **Owner: M4.** Note: bare "Haaland fixtures" works in English; bare "Haaland partidos" does not.

3. **`team_schedule` vs `player_fixture_run` collision in Spanish.**
   - Phrase: "calendario de Arsenal" routes via `_TEAM_SCHEDULE_SPANISH_PREFIXES` (line 707 `"calendario del "` requires `del`, not `de`). "calendario de Arsenal" (without contraction) may fall through.
   - Fix vector: add `"calendario de "` to Spanish prefixes, but then guard against `"calendario de Haaland"` mis-routing to team_schedule. Disambiguator: check `_extract_team_token` first; if it matches a known team alias, route to team_schedule; otherwise route to player_fixture_run.

### Medium risk

4. **`compare_players` bare-connector guard.**
   - Current guard: `_BARE_CONN_MAX_WORDS = 3` (`router.py:1604`). Drops "quien capito entre Semenyo y Cherki" (4 tokens before `y`) into the classifier path. Conservative but correct — calling out so M4 knows not to relax it casually.

5. **`current_gameweek` in Spanish.**
   - No Spanish phrasings in `_GAMEWEEK_KEYWORDS` (`router.py:940-952`). "¿qué jornada es?" / "¿en qué GW estamos?" depend on classifier.
   - Low product impact — fix is one row in a table.

6. **`differential_picks` Spanish keyword.**
   - `_DIFFERENTIAL_KEYWORDS` (`router.py:916-937`) has no Spanish synonym for `diferenciales`. The `/diferenciales` slash command works because the UI strips the command prefix, but bare-text "diferenciales esta semana" misses the router. Fix vector: add `"diferenciales"` and `"diferenciales esta semana"` to `_DIFFERENTIAL_KEYWORDS`.

### Low risk (already handled but worth recording)

7. **`chip_advice` requires both a chip keyword AND an advisory phrase.** This is correct (`_try_route_chip` `router.py:1149-1179`) — prevents false matches like "I used the wildcard last week" — but worth re-checking the Spanish advisory list in M4 to ensure no common idiom is missing.

8. **Spanish accusative "a" before player names.** Already handled (`_strip_spanish_name_prefix` `router.py:192-204`; `_SPANISH_NAME_PREFIXES` 185–189). Good defensive design — keep.

### Manifest / schema-registry visibility gap (not Spanish, but ambiguity-adjacent)

9. **The seven Phase-2.6 tools are absent from `tool_schema_registry`** (`tool_schema_registry.py:380-391`). If M3 wires the orchestrator without first extending the registry, the orchestrator can call only 10 of the 17 tools — silently. **Not in M0 scope to fix; flag for Lead Orchestrator's attention during M3 planning.**

---

## 8. Confidence and Uncertainty

| Section | Confidence | Notes |
|---|---|---|
| Intent inventory completeness | **High** | Cross-checked dispatcher constants, `_TOOL_TO_INTENT`, router `_try_route_*`, corpus scenarios, classifier prompt. 18 intents accounted for. |
| Stability assessments | **High** for green; **Medium** for yellow | "Yellow" reflects manifest/schema-registry visibility gap, not routing fragility. Routing for player_form / injury_list / price_changes / team_* / position_* / transfer_suggestion is well-tested in the 106-scenario corpus. |
| Spanish coverage assessments | **Medium-High** | Based on prefix-table inspection plus corpus pass status. No live re-run of the corpus was performed in this audit (read-only); claims trust the 106/106 PASS report. |
| Frequency hypotheses | **Low-Medium** | These are best-guess product priorities, not measured. No telemetry exists yet. The M5 telemetry phase should validate. |
| Surface assignments | **High** | The four surface-selection rules from the plan map cleanly onto the intent shapes. The only judgment call is `transfer_suggestion`: I chose `text+route()` primary because Spanish phrasings are too varied for a clean prompt arg schema; an alternate Lead view would be to promote it to `/fichar` later. |
| M1 resource verdict | **High** for five of six; **Medium** for `@injuries` recency field | `news_added` is not currently read in the codebase. Recommendation in Section 6 is to verify against a live bootstrap before M1 ships. |
| Ambiguity hot spots | **High** | Drawn directly from prefix-table inspection. The hot spots are concrete and actionable. |

### What I could not determine

- **Whether `news_added` is populated on every flagged element of a live bootstrap.** The code does not read it today; I cannot verify presence without a live snapshot. **Next check:** M1 implementer should fetch one live `bootstrap-static` payload and grep for `news_added` populated vs null on `status != "a"` elements. If sparsely populated, use the `chance_of_playing_this_round` fallback as primary instead.
- **Live frequency distribution across intents.** Frequency hypotheses are not validated against usage data; only M5 telemetry will close that.
- **Whether the original 10 vs Phase-2.6 split was an intentional staging or accidental drift** (manifest/schema-registry/UI types all carry only the original 10). Flagged in Section 9.

---

## 9. Out-of-Scope Notes (flagged, not implemented)

These are observations that emerged during the audit but are not M0/M1 work. Recording them so they are not lost:

1. **`INTENT_MANIFEST` is stale by 7 intents.** Anyone iterating over it to enumerate "what we support" will under-count. Either (a) extend the manifest with the 7 Phase-2.6 intents, or (b) replace `INTENT_MANIFEST` consumers with `SUPPORTED_INTENTS` + `_TOOL_TO_INTENT`. **Not M0/M1 work** — flag for a docs/manifest cleanup phase.

2. **`tool_schema_registry._ALL_SCHEMAS` is stale by 7 tools.** This **directly affects M3**: the orchestrator can only call 10 of the 17 backend tools today. M3 wiring must either extend the registry (preferred — keeps the orchestrator strong) or document the gap and accept the orchestrator as covering only the original 10. **Surfacing to Lead Orchestrator for M3 planning.**

3. **`packages/fpl-ui/lib/types.ts` `SUPPORTED_INTENT_VALUES` lists only 11 intents** (the original 10 + `multi_intent`). The 7 Phase-2.6 intent values are not part of the UI's `Intent` union. Any new UI surface for `@injuries` etc. (M1 deliverable: `GET /resources`) must check whether the response shape returns one of those 7 intent strings and either extend the UI type or use a separate intent-free `resource_rows` shape. The plan's `ResourceResult` design (plan line 213) implicitly avoids this by giving resources their own shape — confirming that's correct.

4. **`INTENT_MULTI_INTENT` declared but not in `SUPPORTED_INTENTS` frozenset.** Most likely intentional, but worth a one-line comment in `dispatcher.py:80` clarifying the omission. Not M0/M1 work.

5. **`differential_picks` returns `outcome="error"` in two corpus scenarios** (`differential_picks_direct`, `differential_picks_low_ownership` — `validation_report.md:39-40`). Both are expected error-outcome assertions, but it's worth noting that a "resource-style" M1 should sort that `error` outcome carefully if `@differentials` is ever added (a resource shape should not produce `outcome=error` from a bootstrap that has data).

6. **Slash command `/clasificacion` is in the plan (line 177) but not in `slash-commands.ts` (lines 35-72).** M2 will add it. Not M0 work, but worth tracking — it's the only prompt in M2 that has no current UI counterpart.

---

## 10. Primary-Surface Summary (decision artifact, condensed)

This is the table the Lead Orchestrator needs for M1/M2 scoping. Every supported intent has a primary surface from `{@resource, /prompt, text+route(), text→orchestrator}`.

| Intent | Primary surface |
|---|---|
| `captain_score` | `/prompt` (`/capitan`) |
| `rank_candidates` | `text+route()` |
| `current_gameweek` | `text+route()` |
| `player_summary` | `text+route()` |
| `player_resolve` | `text+route()` |
| `compare_players` | `/prompt` (`/comparar`) |
| `transfer_advice` | `/prompt` (`/transferencia`) |
| `chip_advice` | `/prompt` (`/chips`) |
| `player_fixture_run` | `/prompt` (`/calendarios`) |
| `differential_picks` | `/prompt` (`/diferenciales`) |
| `player_form` | `text+route()` |
| `injury_list` | **`@resource` (`@injuries`)** |
| `price_changes` | `text+route()` (+ deferred `@prices`) |
| `team_fixture_calendar` | `text+route()` |
| `team_schedule` | `text+route()` |
| `position_fixture_run` | `text+route()` |
| `transfer_suggestion` | `text+route()` |
| `multi_intent` | `text+route()` (composition) |

`text→orchestrator` is the strict fallback exit for all of the above when both `route()` and `classify_intent_llm()` miss. It is never the primary surface for any intent.

The five `@resource` M1 deliverables that are **not** the primary surface for any intent but are nevertheless approved in this audit because they package strengths of the bootstrap data layer: `@top_form`, `@top_xg`, `@top_points`, `@top_minutes`, `@popular`. They serve user-job Cluster A directly without competing with any intent's primary surface.

---

End of audit.
