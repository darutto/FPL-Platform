# FPL Platform

A grounded Fantasy Premier League assistant. Deterministic FPL logic drives all answers; an optional LLM layer polishes the prose. The LLM is subordinate to the backend — it never invents stats.

## What it does

- Answers captain, transfer, chip, and fixture questions with real FPL data
- Supports multi-turn sessions with pronoun resolution (English + Spanish)
- Exposes a stable HTTP API for stateless and session-based flows
- Optionally wraps answers with Claude or Gemini for natural-language polish

## Packages

| Package | Language | Purpose |
|---|---|---|
| `fpl-grounded-assistant` | Python | Core platform — HTTP server, session management, intent routing, LLM integration |
| `fpl-pipeline` | Python | Assembles FPL context: bootstrap + fixtures + FDR in one call |
| `fpl-tool-runner` | Python | `ToolRegistry` dispatcher for in-process tool execution |
| `fpl-tool-contract` | Python | Defines the 5 structured tools (`resolve_player`, `player_summary`, `current_gameweek`, `captain_score`, `rank_candidates`) |
| `fpl-captain-engine` | Python + TS | Captaincy scoring formula (form, xGI/90, fixture difficulty, minutes risk) |
| `fpl-data-core` | Python | Season registry, rolling analytics (xGI/90), position schemas |
| `fpl-api-client` | Python | FPL bootstrap + fixtures HTTP client |
| `fpl-player-registry` | Python | Player identity and nickname resolution (KDB, Salah, etc.) |
| `fpl-query-tools` | Python | Composition layer bridging registry and bootstrap |
| `fpl-ui` | Next.js + TS | Web frontend — Spanish-first slash commands, Patreon-gated |
| `fpl-charts` | TypeScript | Brand color and risk-level theme constants |

## Tech stack

**Backend:** Python 3.13, FastAPI, Pydantic v2, Pandas, Anthropic SDK (optional), Google Generativeai (optional)

**Frontend:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, shadcn/ui

**Infrastructure:** Docker, Railway (backend), Vercel (frontend)

## Running the backend

```bash
# Docker
docker build -t fpl-backend:local -f packages/fpl-grounded-assistant/Dockerfile .
docker run --rm -p 8000:8000 \
  -e DEFAULT_PROVIDER=anthropic \
  -e ANTHROPIC_API_KEY=<key> \
  fpl-backend:local
```

Or with the dev script:

```bash
packages/fpl-grounded-assistant/dev-backend.sh
```

The server exposes `/ask` (stateless) and `/session/*` (multi-turn) endpoints.

## Running the frontend

```bash
cd packages/fpl-ui
npm install
npm run dev   # http://localhost:3000
```

## Tests

The test suite is self-contained — no pytest, no network calls, no API key required:

```bash
cd packages/fpl-grounded-assistant
PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\
../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\
../fpl-api-client:../fpl-pipeline:. python run_phase3d_tests.py
```

Contract drift gate (run by CI):

```bash
bash scripts/run_contract_gate.sh
```

## Documentation

| File | Contents |
|---|---|
| [HANDOFF.md](HANDOFF.md) | Full architectural handoff — phases, invariants, public API |
| [PROJECT_ROADMAP_SUMMARY.md](PROJECT_ROADMAP_SUMMARY.md) | Phase history from 0 through V2 |
| [FINAL_RESPONSE_CONTRACT.md](FINAL_RESPONSE_CONTRACT.md) | Stable `respond()` / `FinalResponse` caller contract |
| [CONTRACT.md](CONTRACT.md) | Adapter layer contract |
| [SESSION_CONTRACT.md](SESSION_CONTRACT.md) | Multi-turn session lifecycle |
| [PACKAGE_STATUS.md](PACKAGE_STATUS.md) | Status table for all packages |
| [orchestrator-instructions.md](orchestrator-instructions.md) | Core design principles |
