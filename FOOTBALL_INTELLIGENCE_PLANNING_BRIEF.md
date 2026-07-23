# Football Intelligence Expansion — Planning Brief for Claude Code

**Repository:** `darutto/FPL-Platform`  
**Document purpose:** Instructions for Claude Code to inspect the existing repository and produce an implementation plan that Codex can execute.  
**Current date context:** July 2026  
**Target provider:** Sportmonks Football API  
**Trial strategy:** Build all provider-independent architecture before activating the 14-day Sportmonks trial. Activate the trial only when the codebase is ready to validate live payloads, ideally around August 10, 2026, so the trial overlaps the Premier League opening weekend on August 22, 2026.

---

## 1. Mission

Extend the existing FPL Platform into a deterministic **football intelligence platform** that can explain not only which player is recommended, but why the football context favors or weakens that player.

The platform must combine:

- Official FPL API data
- Existing Understat shot-level data and xG coordinates
- Existing historical FPL data
- A future Sportmonks Football API integration
- Derived football-intelligence features built inside this repository

The goal is not to expose raw provider data directly. The goal is to convert multiple data sources into stable, provider-neutral football concepts that can improve captaincy, transfer, differential, fixture-run, comparison, and future recommendation features.

Examples of intended intelligence:

- A right-sided attacker faces an opponent weakened at left-back.
- A defender is repeatedly deployed as a wing-back or midfielder.
- A forward is listed as a forward in FPL but plays unusually deep.
- A missing defender changes the opponent’s formation or replacement quality.
- A player’s expected minutes fall because of congestion, competition, or manager rotation.
- A team consistently creates chances down the side where the opponent concedes.
- A player’s tactical role is stable or has recently changed.
- A manager’s selection and substitution patterns affect start probability and cameo risk.

The resulting product should behave like a grounded football analyst, while preserving the repository’s existing principle:

> Interpret with the LLM, answer with the deterministic backend.

The LLM must never become the source of football truth.

---

## 2. Required Planning Outcome

Claude Code must inspect the repository and produce a detailed implementation plan. It must **not begin broad implementation until the plan is complete and approved**.

The plan must be written as a new repository document, recommended path:

```text
FOOTBALL_INTELLIGENCE_IMPLEMENTATION_PLAN.md
```

The plan must be executable by Codex in small, testable phases. Each phase must identify:

1. Purpose
2. Existing files/packages affected
3. New files/packages proposed
4. Public contracts added or changed
5. Data models and schemas
6. Deterministic algorithms or placeholder logic
7. Tests required
8. Documentation updates
9. Migration or compatibility concerns
10. Definition of done
11. Dependencies on Sportmonks trial access
12. Whether the phase can be completed before the trial

The plan should favor incremental slices that preserve all existing behavior and contracts.

---

## 3. Repository Principles That Must Be Preserved

Before planning, inspect at minimum:

- `README.md`
- `HANDOFF.md`
- `PROJECT_ROADMAP_SUMMARY.md`
- `V2_MVP_ROADMAP.md`
- `orchestrator-instructions.md`
- `PACKAGE_STATUS.md`
- `packages/fpl-grounded-assistant/FINAL_RESPONSE_CONTRACT.md`
- `packages/fpl-grounded-assistant/CONTRACT.md`
- `packages/fpl-grounded-assistant/SESSION_CONTRACT.md`
- Existing package manifests and test runners
- Existing UI intent components and TypeScript response types

Preserve these invariants unless a separately approved breaking-change plan exists:

1. The deterministic backend is authoritative.
2. The LLM may interpret, resolve references, or polish grounded output.
3. The LLM may not invent facts, scores, injuries, roles, or recommendations.
4. Existing `FinalResponse` fields remain backward compatible.
5. New metadata should be additive and bounded.
6. Existing intent behavior and current tests must remain green.
7. `respond()` must continue to return a valid response rather than raising.
8. Provider-specific data must not leak into decision logic.
9. Every recommendation-driving signal must be auditable.
10. Live API calls must be mockable and must not be required for ordinary unit tests.

---

## 4. Core Architectural Direction

The desired high-level architecture is:

```text
Official FPL API ───────────────┐
Understat ──────────────────────┤
Historical FPL ────────────────┤
Sportmonks Football API ───────┤
                               ↓
                 Canonical football data layer
                               ↓
                 Derived intelligence feature layer
                               ↓
                 Deterministic intelligence modules
                               ↓
                 Structured evidence and scores
                               ↓
                 Existing tools, intents, and responses
                               ↓
                 Existing visual cards and new evidence cards
```

Sportmonks must be treated as an external provider adapter, not as the domain model.

Bad domain coupling:

```text
recommendation uses sportmonks.formation_field directly
```

Correct direction:

```text
sportmonks.formation_field
→ normalized player_match_role
→ derived flank and formation depth
→ tactical evidence
→ recommendation module
```

The system must be designed so Sportmonks can later be replaced or supplemented by StatsBomb, Wyscout, SkillCorner, Opta, or another provider without rewriting the recommendation layer.

---

## 5. Proposed Package Boundaries to Evaluate

Claude Code must inspect the current package architecture before choosing final names. Evaluate whether the following should be new packages or extensions of existing packages:

```text
packages/
├── football-data-contract/
├── sportmonks-client/
├── football-identity-registry/
├── football-feature-engine/
└── football-intelligence/
```

The plan must justify the final package boundaries.

### 5.1 `sportmonks-client`

Responsibilities:

- Authentication and request construction
- Rate-limit handling
- Pagination
- Retries for safe idempotent requests
- Raw response persistence or cache hooks
- Provider payload models
- Fixtures
- Seasons and competitions
- Teams and squads
- Players
- Confirmed lineups
- Formations
- Detailed positions
- Substitutions
- Injuries
- Suspensions
- Coaches
- Referees
- Team and player match statistics

It must not contain FPL recommendation logic.

### 5.2 `football-data-contract`

Provider-neutral models and enums, potentially including:

- Canonical player
- Canonical team
- Canonical fixture
- Competition and season
- Player match appearance
- Player match role
- Formation
- Availability status
- Injury record
- Suspension record
- Substitution
- Match statistics
- Provider source metadata
- Confidence and provenance

### 5.3 `football-identity-registry`

Map identities across providers:

```text
canonical_player_id
fpl_element_id
understat_player_id
sportmonks_player_id
normalized_name
full_name
club
team_id
birth_date
nationality
valid_from
valid_to
match_method
match_confidence
manual_override
```

Also define canonical mappings for:

- Teams
- Fixtures
- Competitions
- Managers if needed

The existing `fpl-player-registry` must be evaluated. Do not duplicate behavior unnecessarily. The plan must state whether to extend it, wrap it, or create a broader registry above it.

### 5.4 `football-feature-engine`

Convert canonical facts into reusable derived features. It should not make final recommendations.

Example outputs:

```text
start_probability
expected_minutes
cameo_probability
rotation_risk
primary_role
role_stability
flank
flank_distribution
formation_depth
out_of_position_score
opponent_unit_disruption
fixture_congestion_index
rest_days
manager_rotation_tendency
team_formation_stability
```

### 5.5 `football-intelligence`

Deterministic modules that answer bounded football questions and return structured evidence.

Candidate modules:

```text
evaluate_player_availability
evaluate_expected_minutes
evaluate_tactical_role
evaluate_role_change
evaluate_flank_matchup
evaluate_opponent_personnel_disruption
evaluate_rotation_risk
evaluate_fixture_context
evaluate_team_defensive_stability
evaluate_player_matchup
```

The planning phase must decide which modules belong in the first release.

---

## 6. First Intelligence Modules

The initial build should prioritize modules that provide strong value using FPL plus Sportmonks, without requiring full event or tracking data.

### 6.1 Starting and Minutes Confidence

Inputs may include:

- Recent starts
- Recent minutes
- Substitution timing
- Injury and suspension status
- Fixture congestion
- Competition for places
- Manager selection history
- Confirmed or predicted lineups when available

Outputs should be provider-neutral:

```text
start_probability
expected_minutes
cameo_probability
rotation_risk
confidence
reason_codes
```

This module should eventually improve the existing minutes-risk component rather than breaking it immediately.

### 6.2 Tactical Role and Role Stability

Inputs:

- Formation
- Detailed lineup position
- Formation-grid placement
- Match appearances
- Substitutions and replacement roles
- FPL nominal position

Outputs:

```text
primary_role
role_distribution
flank
flank_distribution
formation_depth
role_stability
role_change_detected
out_of_position_score
confidence
```

Important limitation:

Sportmonks lineup coordinates represent tactical deployment or starting formation, not true average operating position. The domain language and UI must not falsely label them as average position.

Use terms such as:

- Starting role
- Tactical role
- Formation flank
- Formation depth
- Deployment history

### 6.3 Opponent Personnel Disruption

Inputs:

- Injuries
- Suspensions
- Usual starters
- Replacement players
- Formation changes
- Unit continuity

Outputs:

```text
affected_unit
affected_flank
usual_starter_missing
replacement_player
replacement_experience
formation_change_probability
unit_disruption_score
benefiting_player_ids
confidence
```

This should support explanations such as:

> The opponent’s first-choice left-back is unavailable, weakening the side this attacker normally targets.

### 6.4 Flank Matchup Intelligence

Initial version may be proxy-based because true event heatmaps may not be available.

Inputs:

- Player tactical flank
- Opponent defensive roles
- Missing defenders
- Team formation history
- Existing Understat shot locations
- Existing FPL and match outcomes
- Any provider team/player match statistics that can safely support the model

Outputs:

```text
attacker_flank
opponent_defensive_flank
flank_matchup_score
supporting_signals
limitations
confidence
```

The plan must explicitly distinguish observed facts from inferred proxies.

### 6.5 Fixture and Rotation Context

Inputs:

- Premier League schedule
- Champions League schedule
- Europa League schedule
- Conference League schedule
- FA Cup schedule
- EFL Cup schedule
- Rest days
- Travel if available
- Manager rotation history

Outputs:

```text
rest_days
congestion_index
rotation_probability
fixture_priority
late_cameo_risk
confidence
```

Recommended initial Sportmonks competition selection:

1. Premier League
2. UEFA Champions League
3. UEFA Europa League
4. UEFA Conference League
5. FA Cup
6. EFL Cup

The expected subscription configuration is the Football API Starter plan plus one additional competition, subject to final confirmation of current Sportmonks pricing and coverage.

---

## 7. Structured Evidence Contract

The platform should not merely output scores. It must retain auditable evidence.

Claude Code must design an additive structured evidence contract. A candidate shape:

```json
{
  "code": "OPPONENT_FLANK_WEAKNESS",
  "label": "Favorable flank matchup",
  "subject_type": "player",
  "subject_id": "canonical-player-id",
  "fixture_id": "canonical-fixture-id",
  "impact": 6.2,
  "confidence": 0.82,
  "direction": "positive",
  "summary": "Opponent is weakened on the side the player attacks.",
  "source_features": [
    "player_primary_flank",
    "opponent_left_back_availability",
    "opponent_unit_continuity"
  ],
  "model_version": "flank-matchup-v1",
  "calculated_at": "2026-08-22T15:00:00Z"
}
```

The final implementation plan must determine:

- Pydantic models
- TypeScript mirror types
- Allowed evidence codes
- Confidence conventions
- Impact-score conventions
- Versioning rules
- Serialization rules
- Maximum evidence items per response
- How evidence is exposed in `FinalResponse`
- How evidence appears in multi-intent responses
- How existing clients remain compatible

Preferred principle:

```text
Raw facts → derived features → evidence → recommendation
```

Every recommendation-driving reason shown to a user should be traceable to evidence.

---

## 8. Scoring Strategy

Do not turn the existing captain score into one giant universal score.

The current captain score should remain a baseline and regression target while the intelligence system develops.

Plan for bounded component scores such as:

```text
expected_output_score
minutes_confidence_score
fixture_matchup_score
tactical_opportunity_score
rotation_risk_score
squad_value_score
```

Different intents should eventually use different weighting profiles.

Illustrative only:

```text
Captaincy:
- Expected output: 35%
- Minutes confidence: 25%
- Tactical opportunity: 20%
- Fixture matchup: 15%
- Rotation risk: 5%

Transfer advice:
- Expected output: 25%
- Expected minutes: 20%
- Fixture horizon: 20%
- Role stability: 15%
- Tactical opportunity: 10%
- Price and value: 10%
```

Claude Code must not blindly adopt these percentages. The plan should define how scores will be introduced, calibrated, versioned, and tested.

---

## 9. Orchestration and Question Decomposition

The user should not be required to ask perfect analytical questions.

A vague request such as:

> Is Saka a good pick this week?

should be decomposed into bounded deterministic checks such as:

```json
{
  "intent": "player_recommendation",
  "player": "Bukayo Saka",
  "analysis_modules": [
    "availability",
    "expected_minutes",
    "tactical_role",
    "recent_output",
    "fixture_context",
    "flank_matchup",
    "opponent_personnel_disruption",
    "rotation_risk",
    "set_pieces"
  ]
}
```

The LLM may help classify or decompose the user’s request, but it may not generate the football findings.

The desired principle is:

> The LLM interprets the question. The intelligence engine investigates it. The deterministic backend decides. The LLM presents the grounded result.

The implementation plan must identify whether this requires:

- A new orchestration manifest
- Additional tool contracts
- A module registry
- New intent types
- New response metadata
- A new deterministic investigation runner
- Changes to current LLM prompts or review logic

Any changes must preserve current supported intents.

---

## 10. Data Persistence and Storage

Claude Code must inspect the current persistence strategy and propose an incremental storage model.

Candidate entities:

```text
canonical_players
canonical_teams
canonical_fixtures
canonical_competitions
canonical_seasons
provider_player_map
provider_team_map
provider_fixture_map

raw_sportmonks_fixtures
raw_sportmonks_lineups
raw_sportmonks_injuries
raw_sportmonks_suspensions
raw_sportmonks_statistics

player_match_appearances
player_match_roles
player_availability_snapshots
player_expected_minutes
team_formation_history
team_unit_availability
fixture_context

player_match_features
team_match_features
player_fixture_intelligence
intelligence_evidence
```

The plan must answer:

- Database technology for initial deployment
- Local development storage
- Production storage on Railway or a portable equivalent
- Raw JSON retention policy
- Idempotent ingestion
- Upsert keys
- Schema migration approach
- Data provenance
- Reprocessing and model-version support
- Backfill strategy
- Data deletion if licensing requires it
- Separation of raw, canonical, derived, and presentation data

Do not introduce unnecessary infrastructure before it is justified.

---

## 11. Sportmonks Trial Strategy

The 14-day trial should be used for validation, not for writing basic wrappers and folder structures.

### 11.1 Work to complete before the trial

The plan should maximize work that can be completed using mocks and documentation:

- Provider-neutral contracts
- Sportmonks client interface
- Configuration and secrets handling
- HTTP transport abstraction
- Rate-limit strategy
- Raw payload fixture format
- Mock provider payloads
- Normalization functions
- Identity crosswalk framework
- Persistence interfaces
- Ingestion orchestration
- Derived-feature contracts
- Evidence contracts
- Test runners
- Acceptance-test harness
- UI placeholder components
- Documentation

### 11.2 Recommended activation window

Target activation around **August 10, 2026**, so the trial overlaps:

- Current squads and transfers
- Preseason or pre-Gameweek information
- Opening Premier League weekend on August 22, 2026
- First full competitive lineup and match-stat payloads

### 11.3 Trial acceptance objectives

The trial should validate:

1. Competition and season identifiers
2. Premier League fixtures
3. Cross-competition fixtures for Premier League clubs
4. Team and squad completeness
5. Current player records
6. Confirmed starters and substitutes
7. Formation strings
8. Formation-grid or lineup-position fields
9. Detailed position identifiers
10. Substitution relationships and minutes
11. Injuries and suspensions
12. Coaches and manager records
13. Fixture-level team statistics
14. Player match statistics
15. Data update timing before, during, and after matches
16. Post-match corrections
17. API rate limits and pagination
18. Stable provider IDs
19. FPL identity-match rate
20. Raw-data storage and derived-data licensing

### 11.4 Trial deliverables

By the end of the trial, the implementation should demonstrate:

- A functioning Sportmonks connector
- Raw and canonical ingestion
- At least 95% automatic mapping of active Premier League FPL players, with an ambiguity queue
- Three initial intelligence modules
- One end-to-end visual example
- A documented subscription go/no-go decision

### 11.5 Questions for Sportmonks support

The implementation plan should include an operational checklist containing these questions:

1. Does the trial include complete 2025/26 Premier League fixtures, lineups, formations, substitutions, injuries, suspensions, and player/team statistics?
2. May trial responses be persisted for integration testing after the trial ends?
3. Does the Starter Football API license permit storing raw API data internally?
4. May the platform combine Sportmonks data with FPL and Understat data?
5. May the platform calculate proprietary derived scores and contextual insights?
6. May those derived insights be displayed to paying subscribers?
7. What restrictions apply to exposing raw fields or provider identifiers?
8. What are the retention rules if the subscription is cancelled?
9. Which exact competitions count toward the Starter plan?
10. Are FA Cup and EFL Cup separately selectable competitions?
11. What recent historical seasons are included without the historical-data add-on?
12. Are confirmed lineups, detailed positions, injuries, suspensions, coaches, substitutions, and match statistics included in Starter?

---

## 12. Testing Requirements

The implementation plan must preserve the repository’s current testing philosophy:

- No network required for normal unit tests
- No API key required for normal unit tests
- Provider payloads represented by checked-in sanitized fixtures
- Deterministic behavior
- Contract tests
- Regression tests
- Failure-path coverage

Tests should include:

### Provider client tests

- Authentication configuration
- Query/include construction
- Pagination
- Retry behavior
- Rate-limit handling
- Timeout behavior
- Malformed payload handling
- Empty results

### Normalization tests

- Fixtures
- Players
- Teams
- Lineups
- Formations
- Formation-grid positions
- Detailed roles
- Substitutions
- Injuries
- Suspensions
- Match statistics

### Identity tests

- Exact match
- Unicode and accent normalization
- Nicknames
- Club changes
- Duplicate names
- Name plus date of birth
- Name plus team
- Manual overrides
- Confidence thresholds
- Ambiguous review queue

### Feature tests

- Role stability
- Flank distribution
- Formation depth
- Out-of-position comparison with FPL nominal role
- Expected-minutes inputs
- Injury disruption
- Congestion
- Evidence generation

### Contract tests

- New metadata is additive
- Existing `FinalResponse` payloads remain valid
- TypeScript types match Python contracts
- Multi-intent serialization remains valid
- No provider-specific fields appear in public recommendation contracts unless deliberately documented

### Integration tests

- Raw mock payload → canonical entities
- Canonical entities → derived features
- Derived features → evidence
- Evidence → deterministic response metadata
- Response metadata → UI card rendering

---

## 13. UI Direction

The frontend is card-based. The plan should use the existing intent-component approach rather than return long unstructured prose.

Candidate reusable UI components:

```text
EvidenceChip
EvidenceList
ConfidenceBadge
TacticalRoleBadge
FlankIndicator
AvailabilityIndicator
RoleHistoryMiniChart
FixtureContextStrip
OpponentDisruptionCard
MatchupEvidenceCard
```

Example player-card evidence:

```text
Favorable flank matchup
Opponent is weakened at left-back.
Confidence: High

Stable attacking role
Started on the right in 9 of the last 10 matches.
Confidence: High

Low rotation risk
Six rest days and no midweek European fixture.
Confidence: Medium
```

The plan must define which components are included in the first implementation and which remain future work.

Do not require visual pitch heatmaps during the provider-independent phase unless they can be built from mock formation data without pretending it is true average position.

---

## 14. Observability and Auditability

The implementation plan must include:

- Provider request logging without exposing secrets
- Ingestion run IDs
- Payload timestamps
- Source timestamps where available
- Normalization warnings
- Identity-match confidence
- Feature model versions
- Evidence model versions
- Data freshness indicators
- Error and retry metrics
- Trial acceptance metrics

Debug output should make it possible to answer:

- Which provider facts caused this recommendation?
- Which derived features were calculated?
- Which model version produced the score?
- How fresh was the data?
- Which identity mapping was used?
- What confidence did the system assign?

This auditability should follow the repository’s existing resolver-debug and deterministic-response philosophy.

---

## 15. Security and Configuration

The plan must include:

- `SPORTMONKS_API_TOKEN` or equivalent environment variable
- `.env.template` update
- No token committed to Git
- Server-side API usage only
- No provider token exposed to the browser
- Request timeouts
- Controlled retries
- Rate-limit protection
- Cache strategy
- Secret rotation procedure
- Sanitized fixtures for tests

The provider adapter must fail gracefully when the API key is absent.

Existing platform behavior should continue to work without Sportmonks configured.

---

## 16. Backward Compatibility and Feature Flags

All new functionality should be introduced behind explicit capability checks or feature flags until validated.

Candidate flags:

```text
FOOTBALL_INTELLIGENCE_ENABLED
SPORTMONKS_ENABLED
TACTICAL_ROLE_ENABLED
EXPECTED_MINUTES_V2_ENABLED
OPPONENT_DISRUPTION_ENABLED
FLANK_MATCHUP_ENABLED
```

The plan must determine whether environment flags, configuration objects, or a capability registry best fits the current codebase.

Requirements:

- Existing captain, transfer, comparison, chip, differential, and fixture-run behavior must continue when all new flags are off.
- Missing provider data must degrade gracefully.
- Recommendations must never claim evidence that is absent.
- Confidence should decrease when evidence is incomplete.

---

## 17. Suggested Phase Structure

Claude Code should inspect the repository and refine this sequence rather than accept it blindly.

### Phase FI-0 — Repository audit and architecture decision

- Inspect existing contracts, packages, persistence, UI, and tests
- Identify extension points
- Produce architecture decision records
- Finalize package boundaries
- Finalize implementation roadmap

### Phase FI-1 — Provider-neutral contracts

- Canonical entities
- Availability and role models
- Evidence contract
- Python and TypeScript parity
- Contract tests

### Phase FI-2 — Identity and mapping foundation

- Cross-provider identity model
- Matching strategy
- Manual overrides
- Ambiguity queue
- Tests using existing FPL and Understat examples

### Phase FI-3 — Sportmonks client skeleton

- Configuration
- Transport abstraction
- Endpoint interfaces
- Mock payloads
- Pagination and rate-limit behavior
- No live key required

### Phase FI-4 — Raw-to-canonical ingestion

- Fixtures
- Teams
- Players
- Lineups
- Formations
- Roles
- Substitutions
- Injuries
- Suspensions
- Coaches
- Statistics

### Phase FI-5 — Feature engine v1

- Tactical role
- Flank
- Formation depth
- Role stability
- Congestion
- Availability
- Expected-minutes inputs

### Phase FI-6 — Intelligence modules v1

- Starting and minutes confidence
- Tactical role and role change
- Opponent personnel disruption
- Fixture and rotation context
- Flank matchup proxy

### Phase FI-7 — Response and UI integration

- Additive `FinalResponse` evidence
- Existing-intent integration
- Evidence cards
- Feature flags
- End-to-end mock demonstrations

### Phase FI-8 — Trial readiness gate

- Acceptance scripts
- API-key setup
- Live smoke-test commands
- Licensing checklist
- Trial dashboard
- Go/no-go criteria

### Phase FI-9 — Live trial execution

- Activate around August 10, 2026
- Pull historical/current data
- Resolve payload mismatches
- Map all current players
- Observe opening weekend
- Produce subscription recommendation

### Phase FI-10 — Post-trial calibration

- Compare predicted versus actual minutes
- Validate roles
- Adjust confidence rules
- Document limitations
- Decide which paid add-ons, if any, are justified

---

## 18. Codex Execution Rules

The plan created by Claude Code will be handed to Codex for implementation. Therefore, every phase must be concrete enough for Codex to execute without guessing architectural intent.

The plan must instruct Codex to:

1. Work on one approved phase or slice at a time.
2. Read the relevant contract and handoff documents before modifying code.
3. Preserve existing invariants and public interfaces.
4. Add tests before or alongside implementation.
5. Avoid network-dependent unit tests.
6. Use provider-neutral models outside the adapter.
7. Avoid implementing unapproved future features.
8. Document any deviation from the plan.
9. Update package status and roadmap documents after each completed slice.
10. Run the full relevant test suite and contract gate before completion.
11. Produce a concise completion report listing files changed, tests run, and remaining risks.
12. Stop and request plan revision if actual repository constraints contradict the plan.

Codex must not:

- Place Sportmonks calls inside LLM prompts
- Let the LLM infer unavailable football facts
- Expose provider credentials to the frontend
- Couple captain or transfer code directly to provider payloads
- Replace existing deterministic scoring without an approved migration
- Rename stable response fields casually
- Use lineup formation coordinates as if they were true average positions
- Add expensive infrastructure without written justification

---

## 19. Questions Claude Code Must Resolve During Planning

The implementation plan must explicitly answer these questions:

1. Which existing package should own provider-neutral football contracts?
2. Should `fpl-player-registry` be extended or wrapped by a canonical identity registry?
3. What storage system is appropriate for the current deployment stage?
4. How will raw payloads be cached and replayed?
5. How will model and feature versions be represented?
6. How will evidence be added to `FinalResponse` without breaking clients?
7. Which existing intents receive intelligence evidence first?
8. Is a new general `player_recommendation` intent needed now or later?
9. How should the orchestrator select intelligence modules?
10. Which calculations can be completed using current FPL and Understat data before the trial?
11. Which modules are blocked until live Sportmonks payloads are available?
12. How will current-season and historical data be separated?
13. How will transferred players be mapped across seasons and clubs?
14. How will incomplete or stale injury data affect confidence?
15. How will the system distinguish confirmed facts from inferred proxies?
16. What is the minimum end-to-end demonstration required before starting the trial?
17. What is the precise subscription go/no-go rubric?

---

## 20. Definition of a Successful Plan

Claude Code’s planning task is complete only when the resulting implementation plan:

- Is grounded in the actual repository structure
- Names concrete files and packages
- Preserves deterministic-backend authority
- Separates raw, canonical, derived, evidence, and presentation layers
- Includes Python and TypeScript contract impact
- Includes tests for every phase
- Includes a provider-free build path
- Includes a trial-readiness gate
- Includes live-trial acceptance criteria
- Includes licensing and data-retention questions
- Includes rollback and graceful-degradation behavior
- Can be handed directly to Codex for phased execution
- Does not assume undocumented Sportmonks fields are guaranteed
- Clearly labels uncertainties that require trial validation

---

## 21. Immediate Instruction to Claude Code

Begin by performing a repository audit. Do not implement the Sportmonks integration yet.

Produce `FOOTBALL_INTELLIGENCE_IMPLEMENTATION_PLAN.md` containing:

1. Current-state architecture map
2. Gap analysis
3. Proposed target architecture
4. Package and module decisions
5. Canonical data contracts
6. Identity strategy
7. Persistence strategy
8. Evidence contract
9. Intelligence-module definitions
10. Orchestration changes
11. UI integration plan
12. Security and configuration plan
13. Testing strategy
14. Trial-readiness checklist
15. Phased Codex execution plan
16. Risks and open questions
17. Explicit non-goals
18. Definition of done for every phase

At the top of the plan, include a short executive recommendation stating:

- What should be built before the Sportmonks trial
- What must wait for live access
- Which three intelligence modules should be demonstrated first
- What conditions must be met before activating the trial

The planning document should be detailed enough that another coding agent can implement each phase without needing to reconstruct the product vision from conversation history.
