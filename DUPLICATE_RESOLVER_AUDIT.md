# Duplicate Resolver / Abstraction Audit

> First pass of the **Abstraction Police** routine (`/abstraction-police`), 2026-07-24.
> Read-only report. Consolidation is tracked as PR A (Cluster A) then PR B (Cluster B);
> see the approved plan `consolidate-duplicate-resolvers-vectorized-hummingbird.md`.
> Paths are the live tree under `packages/…`; all `.claude/worktrees/…` copies ignored.
>
> **Line references re-verified 2026-08-13** against main at the PR A rebase. Every
> finding below still holds; what moved was line numbers (preseason reweight `b3e8842`
> shifted `comparison.py` / `transfer_advisor.py` / `differential_picks.py` by ~+5) and
> one path (the api-client audit copy moved to `audit-reference/`). Cluster-A line
> numbers are stated **post-PR-A**, i.e. as the tree reads once this PR merges.

## Cluster summary

| Cluster | Concern | #true-dups | Canonical home | Drift? | Bug suspected? |
|---|---|---|---|---|---|
| A | current/next gameweek resolver | 6 | `fpl_api_client.get_current_gameweek` | **yes** | **yes** (dropped `is_next`) — ✅ fixed by PR A |
| B | scoring inputs / venue / minutes-risk / set-piece | 3 impls + 1 inline | new `scoring_core.py` + `scoring_display.py` | **yes** | **yes** (`int(None)` on null FDR) — ⏳ open, PR B |

---

## Cluster A — current/next gameweek resolver

**Canonical:** `get_current_gameweek(bootstrap=None)` —
`packages/fpl-api-client/fpl_api_client/fpl_client.py:165`. Fallback
`is_current → is_next → None`.

### True duplicates (delegate to canonical)

Each re-implements the loop with **`is_current` only** — no `is_next` fallback:

| file:line | name |
|---|---|
| `packages/fpl-grounded-assistant/fpl_grounded_assistant/context_builder.py:80` | `_get_current_gw` |
| `packages/fpl-grounded-assistant/fpl_grounded_assistant/chip_advisor.py:122` | `_get_current_gameweek` |
| `packages/fpl-grounded-assistant/fpl_grounded_assistant/fixture_outlook.py:79` | `_get_current_gameweek` |
| `packages/fpl-grounded-assistant/fpl_grounded_assistant/player_fixture_run.py:113` | `_get_current_gameweek` |
| `packages/fpl-grounded-assistant/fpl_grounded_assistant/team_fixture_calendar.py:100` | `_get_current_gameweek` |
| `packages/fpl-grounded-assistant/fpl_grounded_assistant/transfer_suggestion.py:148` | `_get_current_gameweek` |

### Already delegating (leave)

`comparison.py:214`, `differential_picks.py:101`, `transfer_advisor.py:187` (call canonical,
per #38); `fpl-query-tools/fpl_query_tools/queries.py:181`
`get_current_gameweek_from_bootstrap` (thin wrapper).

### Distinct responsibility — reviewed, kept

- `get_team_snapshot.py:108` `_current_gw_from_events(events)` — **different contract**:
  takes an events list, never returns `None`, falls back
  `is_current → most-recent finished → earliest → 1`. Snapshot indexing needs a guaranteed
  int + historical fallback; delegating would change the contract.
- `get_gameweek_context.py` `_find_current_event` / `_find_next_event` / `_event_status` —
  richer GW-context builder (deadline/status/blank alerts), not the simple resolver.
- Tool/render plumbing (same/similar name, different job): `tool_get_current_gameweek`
  (tool-contract `tools.py:631`), `_get_current_gameweek_handler` (`runner.py:206`),
  `_render_get_current_gameweek` (`renderer.py:129`), `compose_current_gameweek`
  (`generic_card.py:372`).

### Out of scope

`packages/fpl-api-client/audit-reference/fpl_client.py:136` (labelled "audit copy — do not
modify"; main relocated it from `python/` to `audit-reference/` after this audit was written).
TypeScript mirrors: `fpl-api-client/typescript/src/fplClient.ts:104`, `fpl-ui`
`fpl-squad/[teamId]/route.ts:107` — separate language.

---

## Cluster B — scoring inputs / venue / minutes-risk / set-piece

Two parallel twins — `comparison.py` and `transfer_advisor.py`
(`packages/fpl-grounded-assistant/fpl_grounded_assistant/`) — plus a third copy in
`packages/fpl-tool-contract/fpl_tool_contract/tools.py`. Cross-imports: the two twins share
**nothing** directly; each carries a private copy of every helper below.

| Helper | comparison.py | transfer_advisor.py | tools.py | Status |
|---|---|---|---|---|
| `_STATUS_RISK` | :93 | :87 | :73 | identical |
| `_*_ADV_THRESHOLD` (×4) | :107-116 | :101-110 | — | values identical, comments differ |
| `_SET_PIECE_SHORT` | :131 | :128 | — | identical |
| `_venue_tag` | :139 | :162 | — | identical |
| `_set_piece_advantage_phrase` | :148 | :136 | — | logic identical, param names/docstring differ |
| `HOME_FDR_ADJUSTMENT` | :211 | :184 | — | value identical, comments differ |
| `_get_current_gw` | :214 | :187 | — | identical (both delegate to canonical) |
| `_resolve_venue` | :226 | :199 | — | identical |
| `_compute_effective_fdr` | :244 | :217 | — | identical |
| `_derive_scoring_inputs` | :260 | :233 | `_..._from_element` :82 | **DIVERGED** — see bugs |

**Canonical homes (dependency-safe):**
- `fpl_tool_contract/scoring_core.py` (new) — cross-layer: `_STATUS_RISK`,
  `HOME_FDR_ADJUSTMENT`, `_resolve_venue`, `_compute_effective_fdr`, `_derive_scoring_inputs`
  (null-safe, `fdr_map: Mapping[int, int | None]`).
- `fpl_grounded_assistant/scoring_display.py` (new) — grounded-assistant-only presentation:
  `_venue_tag`, `_SET_PIECE_SHORT`, `_set_piece_advantage_phrase`, the four
  `_*_ADV_THRESHOLD`.
- File-local, **not** shared: comparison's `_MARGIN_NARROW`/`_MARGIN_CLEAR`,
  transfer_advisor's `_TRANSFER_THRESHOLD_STRONG`.

### External importers (a dedup must preserve these — use compat re-exports)

- `fpl_grounded_assistant/__init__.py:212-229` re-exports the comparison thresholds,
  `_set_piece_advantage_phrase`, and `_TRANSFER_THRESHOLD_STRONG`.
- Production consumers of `_derive_scoring_inputs`: `chip_advisor.py:68` (calls at :226),
  `differential_picks.py:73` (calls at :230).
- Phase scripts / diagnostics importing these private symbols: `run_phase5h_tests.py`
  (:78/:84/:90/:112), `run_phase5i_tests.py:539`, `run_phase8a1_tests.py:198`,
  `run_phase8a1_overpromotion_triage.py:54`, `run_gkp_weight_sensitivity.py:85`.

---

## 🚨 Latent bugs surfaced

Both are the **null-default drift signature**: `int(<map>.get(key, default))` only defaults
on a *missing* key, but the FPL API ships `key: null` at season launch → `int(None)`.

### Bug 1 — Cluster A: six resolvers drop the `is_next` fallback ✅ FIXED BY PR A

> Status: **fixed in this PR**. Described below as found, on the pre-PR-A tree.
> Regression pin: `tests/test_current_gameweek_delegation.py` (25 cases).

- **Where:** the six true-dups above (context_builder, chip_advisor, fixture_outlook,
  player_fixture_run, team_fixture_calendar, transfer_suggestion).
- **Failing input:** pre-season / season launch — no event has `is_current`, GW1 is
  `is_next`.
- **Wrong output:** returns `None` instead of the GW1 id → downstream GW selection and the
  home/away ±0.5 venue adjustment silently no-op (the exact bug #38 fixed in three other
  files).
- **Fix:** replace each body with delegation to canonical
  `get_current_gameweek(bootstrap)`.

### Bug 2 — Cluster B: `int(None)` on present-but-null FDR ⏳ STILL OPEN

> Status: **still present on main** as of 2026-08-13; awaits PR B.

`comparison.py:306-307` is null-safe (`_raw_fdr = fdr_map.get(team_id); … if _raw_fdr is not
None else 3`). Three other sites are not:

| file:line | context | symptom |
|---|---|---|
| `transfer_advisor.py:263` | inside `_derive_scoring_inputs` | **crashes** with `TypeError` (unguarded); `differential_picks.py` inherits it via its :73 import |
| `tools.py:106` | inside `_derive_scoring_inputs_from_element` | **crashes** with `TypeError` |
| `chip_advisor.py:245` | **inline** `"fdr": int(fdr_map.get(el.get("team"), 3))` inside `_score_outfield_players`'s `try/except` (:225) | **silent** — the null-FDR player is dropped from the scored list, no error surfaced |

- **Failing input:** season launch, a team whose `fixture_difficulty_map` value is present
  but `null`.
- **Fix:** delegate all derivation to the null-safe `scoring_core._derive_scoring_inputs`
  (yields `fixture_difficulty = 3`); at `chip_advisor.py:243` reuse the already-computed
  `inputs["fixture_difficulty"]` instead of recomputing.
- **Grep invariant after fix:** `int(\s*\w+\.get(` over `fixture_difficulty_map` /
  `fdr_map` returns **zero** hits.

---

## Recommended consolidation order

1. **Cluster A (PR A)** — smallest blast radius. Delegate the six resolvers; regression pins
   the season-launch edge (no `is_current`, one `is_next` → returns the `is_next` id) and
   the precedence edge (both present → `is_current` wins).
2. **Cluster B (PR B)** — extract `scoring_core.py` + `scoring_display.py`; migrate
   `chip_advisor` (import **and** the inline :243 site), `differential_picks`, `tools.py`;
   keep `comparison.py` / `transfer_advisor.py` as compat re-export shims so `__init__.py`
   and the phase scripts keep resolving. Regressions: null-FDR → 3 at helper level, plus
   **public-path** tests (transfer advice returns the pick; differential returns the ranked
   player; **chip triple-captain path retains the null-FDR candidate** — not merely "no
   `TypeError`", since the broad `try/except` already hides the crash).

**Verdict:** 2 clusters, 9 true duplicates (6 + 3), 1 inline drift site, **2 latent
season-launch bugs** suspected — one crashing, one silent.
