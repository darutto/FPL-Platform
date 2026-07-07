# FPL Platform — Tactical Assistant Roadmap (External Football Intelligence)

**Last updated:** 2026-07-02 — rewritten after a live proof-of-concept validated the zonal-weakness engine against real 2025/26 Understat data. Supersedes the earlier Phases 9–13 spec, which pointed at event-data tooling (VAEP/PPDA/pitch-control) heavier than the actual product needs.

**Goal:** Extend the FPL platform from a points-retrieval tool into a tactical assistant by injecting **positional-opportunity intelligence** — "which defenses leak chances from which pitch zones, and which attackers operate there" (the Ghono_FF "zonal weakness" analysis) — on top of the existing FPL data and the Track D fixture engine.

---

## What the PoC established (2026-07-02)

A stdlib-only pull of **live 2025/26 Understat shot data** (all 380 matches) produced a differentiated, actionable flank-weakness ranking — with **no event data, no VAEP/PPDA, no paid feed**. This is a **shot-map join**, not a possession-model project. Three findings are now load-bearing constraints on this roadmap:

1. **Relative, not absolute.** Every defense concedes ~1.16 in-box central xGA/game — central always dominates raw totals. The signal is **deviation from the league baseline per zone**, computed team-vs-league-mean. Absolute zone counts are useless.
2. **Raw scraping is already broken.** Understat no longer embeds `datesData`/`shotsData` in HTML (what the `understatapi` package assumes). It moved to **gzip'd AJAX JSON endpoints**: `getLeagueData/{league}/{season}` and `getMatchData/{id}` (headers `X-Requested-With: XMLHttpRequest` + Referer; gzip body). A hand-rolled scraper *will* break again → depend on a maintained library, not our own scraper.
3. **This is zone-of-finish, not buildup-flank.** Understat gives *where the shot was taken*. That already supports "target attackers who finish from Palace's weak side." True "plays the right channel" attribution needs touch/position data → FotMob/Sofascore (Tier 2).

---

## Data-source strategy

**Library:** [`soccerdata`](https://github.com/probberechts/soccerdata) (v1.9.0, actively maintained; one Pandas API over Understat + FBref + FotMob + Sofascore with matching IDs). It absorbs the scraper churn we hit in the PoC and collapses the old "normalization layer" phase to near-zero. **Not** raw `understatapi` / hand-rolled scrapers.

**Ownership:** every external pull lands in the **owned parquet/R2 store** (the Track A principle — independent of any third-party cadence/quality/schema). Refresh on a weekly cron (a full-league Understat pass is ~380 requests, ~2–3 min); serve queries from the store, never scrape live per request. A source breaking degrades tomorrow's refresh, never a live answer.

**Tiers (ship independently, in order):**

| Tier | Source (via soccerdata) | Unlocks | Live EPL? |
| :--- | :--- | :--- | :--- |
| **Tier 1** | Understat shots (x/y, xG, situation, result) | Zone-of-**finish** weakness + attacker finish-zone profile. The Ghono core. | ✅ current season, free |
| **Tier 2** | FotMob / Sofascore (heatmaps, avg position, touches) | Buildup-**flank** attribution — "plays the right channel." | ✅ current season, free-ish (ToS/anti-bot risk) |
| **Tier 0** | StatsBomb Open Data (full events) | **Offline** model validation only (calibrate/backtest the zonal model). | ❌ historical, non-EPL-current |

**Honest cost:** data is $0 but **not zero-effort** — scraping carries ToS/rate-limit/breakage risk (the maintenance cost the old roadmap's "Free" column hid). Mitigated by soccerdata + weekly owned-store refresh. Same lesson as the WC data-source evaluation: free tiers exclude the live season, so live depth = owned pull, not a hosted API.

---

## Phase T1 — Owned tactical-data ingest (foundation)

**Goal:** get Understat shot data into the owned store, reliably and idempotently, without touching `fpl-data-core`.

| Slice | Title | Description |
| :--- | :--- | :--- |
| **T1a** | soccerdata ingest | Wrap `soccerdata`'s Understat reader; pull season shot events (x/y, xG, `situation`, `result`, player, team, h/a). Idempotent per-match. |
| **T1b** | Owned-store landing | Persist to parquet + publish to R2 (`fpl-owned` bucket), mirroring Track A's `player_gw_stats` pattern. Provenance-stamped, `season` column. |
| **T1c** | Weekly refresh | GitHub Actions cron (align with Track A's `0 6 * * 1`): pull → merge → publish. Degrades gracefully if the source shape changes. |

**Outputs:** `understat_shots` owned table; a `TacticalStore` reader used by everything below.

---

## Phase T2 — Zonal Weakness Engine (the Ghono core)

**Goal:** turn shots into a **relative** per-team, per-zone defensive-weakness signal, and a per-player attacking-zone profile, then join them into an opportunity signal. Deterministic, no LLM.

| Slice | Title | Description |
| :--- | :--- | :--- |
| **T2a** | Zonal concession model | Per team, bucket **conceded** shots into a pitch grid (depth × lateral; in-box / edge, left / central / right), sum xGA per zone per game. |
| **T2b** | Relative baseline | Compute league mean per zone; a team's weakness in a zone = its xGA/game **minus** league mean. This is the signal (per the PoC finding). Exclude penalties. |
| **T2c** | Player shooting profile | Per player, bucket **own** shots by zone → where he generates xG. Tier-1 proxy for "where he operates." |
| **T2d** | Opportunity matcher | Join: attacker whose finish-zone overlaps an opponent's above-baseline weak zone → structured `zonal_opportunity` signal (team, zone, delta-vs-avg, matching players). **Schedule/opportunity language only — no buy/sell** (mirrors the Track D invariant). |

**Outputs:** `get_zonal_weakness(team)` and `get_zonal_opportunity(opponent, position?)` — surfaced as orchestrator tools (LLM-callable, zero recalibration risk, exactly like Track D's `get_fixture_outlook`).

---

## Phase T3 — Buildup-flank attribution (Tier 2)

**Goal:** upgrade "where he finishes" to "where he plays" so the literal "right-channel player" query works.

| Slice | Title | Description |
| :--- | :--- | :--- |
| **T3a** | Position/heatmap ingest | Add FotMob (or Sofascore) via soccerdata → per-player average position / touch zones, landed in the owned store. |
| **T3b** | Channel profile | Replace/augment the T2c finish-zone proxy with a touch-based channel profile (left / central / right operating zone). |
| **T3c** | Attribution merge | Feed richer operating-zone into the T2d matcher; keep Tier-1 as fallback when Tier-2 data is missing. |

---

## Phase T4 — Surfacing (chat + browse)

**Goal:** expose the engine the same two ways Track D does — orchestrator tool for chat, and visual cards — reusing the intent→renderer pipeline.

| Slice | Title | Description |
| :--- | :--- | :--- |
| **T4a** | Tool reach | Register T2/T3 tools in `tool_schema_registry` so any "who should I target against X" question reaches them via the orchestrator. |
| **T4b** | Zonal card | A `zonal_weakness` intent + card: pitch-grid heat overlay (weak zones vs baseline) + matched attacker chips. Bendito Fantasy design, mobile-first. |
| **T4c** | Track D tie-in | Feed the opportunity signal into the fixture engine as a **matchup modifier** — this is the old "Tactical FDR" (former 13a), now folded into Track D / FI6 rather than a separate track. Additive tiebreaker first; scoring-input replacement gated on Track B, same as FI3b. |

---

## Deferred / separate (do NOT schedule as "free live" work)

- **Offline research backlog (needs full event data → StatsBomb Open, historical only):** VAEP, xT, PPDA, pitch-control zones. Valuable for *calibrating* the zonal model under Track B, but they **cannot** run on the live EPL season from free sources. Keep them explicitly labeled as offline model research, not in-season intelligence.
- **Set-piece & aerial mismatch engine (former Phase 11):** a genuinely different data problem (height, marking systems, dead-ball concession). Later track; not part of the zonal-opportunity core.
- **Linear solver / squad optimizer (former 13b, PuLP):** unrelated to external data — belongs in its own optimization track, not here.

---

## Priority & sequencing

1. **T1 → T2** deliver the validated Ghono core on free Understat data with no UI and no recalibration risk (tool-only reach). This is the whole payoff of the PoC — build it first.
2. **T4a/T4b** make it visible in chat.
3. **T3** (Tier 2) adds true flank attribution once T2 proves useful.
4. **T4c** feeds it into Track D (additive), with scoring-input replacement gated on Track B.
5. Everything under "Deferred" waits — no free live source supports it.

**Costs:** Data $0 (owned pulls, weekly cron) with maintenance risk absorbed by soccerdata. Compute low (standard Railway/Vercel). LLM cost only at the T4 explainer layer, same as today.
