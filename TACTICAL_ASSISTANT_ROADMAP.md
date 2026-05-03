# FPL Platform — Tactical Assistant Roadmap (Phases 9–13)

**Goal:** Transition the FPL platform from a points-retrieval tool to a high-level tactical assistant by injecting advanced footballing intelligence into the deterministic backend [cite: 34, 35].

---

## Phase 9 — Tactical Data Foundation & Normalization
**Goal:** Build the infrastructure for non-FPL data sources without disrupting existing `fpl-data-core` structures [cite: 37].

| Slice | Title | Description | Source | Cost |
| :--- | :--- | :--- | :--- | :--- |
| **9a** | understat-client | Implement a context-managed wrapper for `understatapi` to pull xG and shot locations [cite: 39, 15, 16]. | understatapi (GitHub) | Free |
| **9b** | Standardization Layer | Use `kloppy` or `floodlight` to normalize Understat and Opta-style JSON into a unified internal `TacticalFrame` [cite: 41, 15]. | kloppy / floodlight | Free |
| **9c** | Ben Crellin Logic | Integrate scheduling intelligence (BGW/DGW) into `fpl-api-client` via FPL fixture metadata [cite: 42, 16]. | FPL API / Manual Registry | Free |
| **9d** | Tactical Pipeline | New `fpl-pipeline` entry point: `assemble_tactical_context(player_id)` combining FPL + Understat data [cite: 44]. | Internal Logic | — |

**Key Outputs:** `TacticalFrame` schema, `understat-client` integration [cite: 45].

---

## Phase 10 — Defensive Structural Analysis ("Weak Zones")
**Goal:** Identify defensive flaws to suggest attackers capable of exploiting specific structural failures [cite: 45].

| Slice | Title | Description | Source | Cost |
| :--- | :--- | :--- | :--- | :--- |
| **10a** | "Last-Resort" Metrics | Calculate blocks, clearances, and saves. High volume indicates a "pinned back" defense ($-0.96$ correlation with success) [cite: 47, 48, 18, 19]. | FPL API / Understat | Free |
| **10b** | Spatial Breach Mapping | Use `mplsoccer` to generate heatmaps identifying high xG concessions on specific flanks (e.g., "Weak Right Flank") [cite: 49, 50, 19]. | mplsoccer (Python) | Free |
| **10c** | Pressing Pulse (PPDA) | Calculate Passes Per Defensive Action (PPDA) to identify teams that struggle under high pressure [cite: 51, 20]. | Understat Event Data | Free |
| **10d** | Weak Zone Resolver | Map "Weak Zone" tags (e.g., `ZONE_LEFT_FLANK`) to player positions in `fpl-player-registry` [cite: 53]. | Internal Logic | — |

**Key Outputs:** `DefenseWeaknessMeta` object, PPDA scores per team [cite: 54].

---

## Phase 11 — Set-Piece & Aerial Mismatch Engine
**Goal:** Predict goals from dead-ball situations using physical and historical performance data [cite: 54, 55].

| Slice | Title | Description | Source | Cost |
| :--- | :--- | :--- | :--- | :--- |
| **11a** | Aerial Logit Model | Implement $P(A) = \frac{e^{logit}}{1 + e^{logit}}$ using height and historical win rates to predict mismatches [cite: 56, 57, 22, 23]. | FBRef (Scraped) | Free |
| **11b** | Set-Piece Vulnerability | Track "Indirect Set-Piece Concession"—chances conceded within 5 seconds of a dead ball [cite: 58, 23]. | StatsBomb Open Data [cite: 59, 15] | Free |
| **11c** | Marking Identifier | Identify rival marking systems (Zonal vs. Man-to-Man) to suggest "Danger Men" who exploit gaps [cite: 60, 24]. | Manual Tagging / LLM Analysis | Free |

**Key Outputs:** `AerialMismatchResult`, `SetPieceVulnerability` score [cite: 62].

---

## Phase 12 — Value Attribution (The "Hidden Gem" Layer)
**Goal:** Use advanced metrics to find players with high underlying performance who haven't yet returned FPL points [cite: 62].

| Slice | Title | Description | Source | Cost |
| :--- | :--- | :--- | :--- | :--- |
| **12a** | Expected Threat (xT) | Implement xT to value ball progression and identify players "due" for an assist [cite: 64, 65, 27, 28]. | kloppy / Open Repos | Free |
| **12b** | VAEP Framework | Implement Valuing Actions by Estimating Probabilities to measure how actions change score probability [cite: 66, 26]. | socceraction (GitHub) | Free |
| **12c** | Pitch Control Zones | Synthesize event data to find "Spatial Control Zones" where rivals typically concede control [cite: 67, 68, 28, 29]. | Event Data Analysis | Free |

**Key Outputs:** `HiddenGemMeta` (xT vs. actual returns), `VAEP_Score` per player [cite: 70].

---

## Phase 13 — Tactical FDR & Solver Integration
**Goal:** Replace static difficulty ratings with dynamic, matchup-based logic and a team optimizer [cite: 71, 72].

| Slice | Title | Description | Source | Cost |
| :--- | :--- | :--- | :--- | :--- |
| **13a** | Tactical FDR | Develop a dynamic score where "Hard" fixtures become "Easy" if a player's strengths match an opponent's weak zones [cite: 73, 74, 30, 31]. | Internal Logic | — |
| **13b** | Linear Solver (PuLP) | Use Integer Linear Programming to maximize expected points within budget and team constraints [cite: 75, 76, 31]. | PuLP library | Free |
| **13c** | Tactical Explainer | Update the LLM layer to provide the "why" behind recommendations (e.g., specific aerial win rate gaps) [cite: 77, 32]. | LLM (Gemini/OpenAI) | Variable |

**Key Outputs:** `TacticalFDRResult`, `OptimizedSquad` (via `POST /solve`) [cite: 79].

---

## Priority & Cost Summary

* **Top Priority:** Phases 9 and 10 [cite: 79]. These are foundational; without Understat data and spatial mapping, the "Weak Zone" logic cannot be built [cite: 80].
* **Data Sources:** Prioritize **Understat** (via `understatapi`) and **StatsBomb Open Data** for historical modeling, as they are the gold standards for free tactical data [cite: 81, 82, 15].
* **Estimated Costs:**
    * **Data:** $0 (utilizing open-source libraries and public APIs) [cite: 83].
    * **Computation:** Low (standard Python backends on Railway/Vercel are sufficient) [cite: 84].
    * **LLM:** Token costs for the Phase 13c "Tactical Explainer" will be the primary recurring cost [cite: 85].
