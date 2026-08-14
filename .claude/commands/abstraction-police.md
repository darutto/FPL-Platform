# Abstraction Police

You are running an on-demand **duplicate-abstraction sweep** over the fpl-platform
monorepo. The job: find helpers/constants that have been built multiple ways across
packages (siloed feature-by-feature patches), classify true duplication vs
same-name-different-responsibility, and **flag drift between copies as latent bugs**.

This is a **read-only reporting routine**. You DETECT and REPORT — you do not edit code.
Unification is a separate, explicitly-approved step (see the audit doc / plan flow).

## Why this exists

Copies drift and break inconsistently. Concrete precedent in this repo: "current
gameweek" alone had ≥9 implementations; the same season-launch null bug was fixed in two
separate PRs (#38/#39); and unifying the scoring helpers exposed an `int(None)` crash that
only existed *because* the copies diverged. The valuable output of this sweep is not
"fewer copies" — it's **the drift, surfaced as bugs before they ship.**

## Known context (do not re-derive)

- **Canonical homes already decided** — recommend these, don't invent new ones:
  - Current/next gameweek resolver → `get_current_gameweek` in
    `packages/fpl-api-client/fpl_api_client/fpl_client.py` (`is_current → is_next → None`).
  - Scoring derivation + venue/FDR/minutes-risk → `fpl_tool_contract/scoring_core.py`
    (`_derive_scoring_inputs`, `_resolve_venue`, `_compute_effective_fdr`, `_STATUS_RISK`,
    `HOME_FDR_ADJUSTMENT`).
  - Presentation helpers shared only within grounded-assistant → `scoring_display.py`
    (`_venue_tag`, `_SET_PIECE_SHORT`, `_set_piece_advantage_phrase`, `_*_ADV_THRESHOLD`).
  - Player/team name matching → the shared matcher (see the resolver-alias consolidation).
- **Dependency order** (a shared home must sit at or below every consumer):
  `fpl-api-client ← fpl-tool-contract ← fpl-grounded-assistant`. A module in
  grounded-assistant CANNOT be imported by tool-contract (circular).
- **Always ignore** everything under `.claude/worktrees/…` — those are agent worktree
  copies, not the live tree. Work only in `packages/…`.
- **Out of scope — never flag as a dup:** `packages/fpl-api-client/python/fpl_client.py`
  (labelled "audit copy — do not modify"). TypeScript mirrors under `*/typescript/…` are a
  separate language, report separately at most.
- **Same-name ≠ duplicate.** Tool wrappers (`tool_*`), runner handlers (`*_handler`),
  renderers (`_render_*`), and card composers (`compose_*`) legitimately share a name with
  a resolver but have a different responsibility. List them as "distinct — leave," never as
  dups.
- **The signature drift bug class:** `int(x.get(key, default))` only defaults on a
  *missing* key. When the FPL API ships `key: null` (season launch), it evaluates
  `int(None)` → `TypeError` — or, inside a broad `try/except`, silently drops the record.
  The null-safe form is `raw = x.get(key); val = int(raw) if raw is not None else default`.
  Treat every `int(<map>.get(...))` as a drift/bug candidate.

## Step 1 — Sweep for candidate clusters

Grep fresh (never trust old line numbers). Cast a wide net across `packages/**/*.py`:

- **Resolver bodies:** `def .*current_gw`, `def .*current_gameweek`, `is_current`,
  `is_next`, `def _resolve_`, `def _derive_`, `def _get_`, `fixture_difficulty`,
  `def .*venue`, name/alias matchers.
- **Copy-pasted constants / dict literals:** repeated names like `_STATUS_RISK`,
  `HOME_FDR_ADJUSTMENT`, `_*_ADV_THRESHOLD`, `_SET_PIECE_*`, and any module-level dict/const
  that appears in more than one file.
- **The null-default drift signature:** `int(\s*\w+\.get\(` (esp. `fdr_map.get`,
  `strength`, per-fixture difficulty).

Group hits into clusters (one concern per cluster).

## Step 2 — Classify each cluster member

For every implementation found, record `file:line`, the function/const name, and a
one-line body summary, then tag each as:
- **canonical** (or the recommended canonical home if none exists yet),
- **true-dup** (re-implements the canonical logic — should delegate),
- **distinct-responsibility** (same/similar name, different job — leave), or
- **out-of-scope** (audit copy / other language).

## Step 3 — Diff the copies (drift = the payload)

For each true-dup cluster, compare the copies against the canonical/each other:
- **Byte-identical?** → safe to dedup, behavior-preserving.
- **Diverged?** → show the exact diff and decide: harmless (comments/param-names only) vs
  **behavioral** (different fallback, different null-handling, different return contract).
  Every behavioral divergence is a **potential latent bug** — call it out explicitly with
  the failing scenario (e.g. "pre-season, no `is_current` event → returns `None` instead
  of the `is_next` id"). Pay special attention to the null-default signature above.

## Output format

Produce / update **`DUPLICATE_RESOLVER_AUDIT.md`** at the repo root. No preamble — go
straight to the findings:

1. **Cluster summary table** — one row per cluster: concern, #true-dups, canonical home,
   drift? (yes/no), bug-suspected? (yes/no).
2. **Per cluster** — the classified inventory (canonical / true-dups with `file:line` /
   distinct-responsibility left in place / out-of-scope), and for any drift, the exact diff
   + the concrete failing scenario.
3. **🚨 Latent bugs surfaced** — a dedicated section listing every behavioral divergence as
   a bug with: file:line, failing input, wrong output, and the one-line fix. This is the
   headline output.
4. **Recommended consolidation order** — smallest-blast-radius cluster first; note which
   consumers/`__init__.py` re-exports / phase scripts import each symbol (so a dedup keeps
   compat), and which season-launch edge each cluster's regression must pin.

End with a one-line verdict: clusters found, true-dups counted, bugs suspected. Do not edit
any source file — this routine only reports.
