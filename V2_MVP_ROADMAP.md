# V2 MVP Roadmap: Production UI Layer (Next.js + shadcn/ui)

## Context

The FPL platform backend has a stable, well-typed HTTP API and `FinalResponse` contract covering 8 intents. The goal is a production web app targeted at paying subscribers (Patreon-first, Stripe later) that:
- Displays all FPL assistant responses with rich structured UI
- Is hosted on Railway (backend) + Vercel (frontend), fully portable to Azure/AWS
- Gives full control over UI patterns: chat, slash-command routing, widgets, starter prompts
- Is Spanish-first (slash commands and UI copy in Spanish)
- Is cost-effective early-stage (~$5/month backend) and easy to scale

**Stack: Next.js (App Router) + shadcn/ui (manual component mapping).**

---

## Architecture Overview

```
packages/fpl-ui/                     ← Next.js app (App Router)
├── app/
│   ├── (auth)/login/                ← Patreon OAuth login page
│   ├── (auth)/subscribe/            ← Paywall / subscription CTA
│   ├── chat/                        ← Main chat interface (protected)
│   └── api/
│       ├── proxy/route.ts           ← Server-side proxy → fpl_server
│       └── webhooks/patreon/        ← Patreon webhook → update user tier
├── components/
│   ├── chat/
│   │   ├── ChatShell.tsx            ← Full layout container
│   │   ├── MessageList.tsx          ← Scrollable history
│   │   ├── InputBar.tsx             ← Input + slash command trigger
│   │   ├── SlashMenu.tsx            ← Dropdown of intent shortcuts (Spanish)
│   │   ├── StarterPrompts.tsx       ← Clickable example questions
│   │   └── SquadContextPanel.tsx    ← FPL team ID input → auto-fetch context
│   ├── intents/                     ← One component per FinalResponse intent
│   │   ├── CaptainCard.tsx
│   │   ├── ComparisonCard.tsx
│   │   ├── RankingTable.tsx
│   │   ├── TransferCard.tsx
│   │   ├── ChipCard.tsx
│   │   ├── FixtureRunTable.tsx
│   │   ├── DifferentialTable.tsx
│   │   └── MultiIntentView.tsx
│   └── ui/                          ← shadcn/ui primitives
├── lib/
│   ├── types.ts                     ← TypeScript port of FinalResponse contract
│   ├── api.ts                       ← Typed client (POST /ask, /session/*)
│   ├── fpl-squad.ts                 ← FPL public API: auto-fetch squad context
│   ├── slash-commands.ts            ← Configurable slash command registry
│   ├── starters.ts                  ← Configurable starter prompts
│   └── auth.ts                      ← Patreon tier checks
└── middleware.ts                     ← Edge auth guard (protect /chat)
```

---

## Squad Context: FPL Auto-Fetch

The user enters their **FPL team ID** (a number, e.g. `1234567`) once in the Squad Context panel. The app calls the FPL public API server-side:

- `GET fantasy.premierleague.com/api/entry/{team_id}/` → ITB (money in bank), free transfers
- `GET fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/` → active chip, squad

This populates `squad_context` automatically:
```json
{ "itb": 15, "chips_remaining": ["triple_captain", "bench_boost"], "free_transfers": 1 }
```

This is passed on every `/ask` request. The team ID is stored in `localStorage` (no server-side persistence needed at this stage). A "Refresh" button re-fetches.

The FPL API is public and requires no auth key — the app fetches it from the Next.js API route (avoids CORS).

---

## Auth & Subscriber Gating

**Patreon OAuth via Clerk (custom OAuth2 provider setup)**

Patreon is not natively listed in Clerk's provider catalog, but Clerk supports any OAuth2-compliant provider as a custom social connection.

Setup:
1. Create a Patreon OAuth client at `patreon.com/portal/registration/register-clients`
2. In Clerk Dashboard → "Social Connections" → "Add custom provider" → enter Patreon's OAuth2 endpoints
3. On Patreon OAuth callback: query Patreon API to check membership tier (`/api/oauth2/v2/identity?include=memberships`)
4. Store tier in Clerk user metadata: `{ subscription_tier: "patreon_member" | "free" }`
5. Patreon webhook → `POST /api/webhooks/patreon` → update Clerk user metadata when tier changes

`middleware.ts` checks `subscription_tier` on every `/chat` request.

**Note:** Custom Patreon + Clerk setup requires careful testing — allocate time for this step. Stripe can be added later as an alternate payment path using the same Clerk metadata pattern.

---

## Slash Command Intent Routing

User types `/` and a dropdown `SlashMenu` appears with intent shortcuts. Selecting one pre-fills the intent context.

**Slash commands (Spanish-first, configurable in `lib/slash-commands.ts`):**
| Command | Intent routed | Example follow-up |
|---------|--------------|-------------------|
| `/capitan` | `captain_score` / `rank_candidates` | `/capitan haaland` |
| `/comparar` | `compare_players` | `/comparar salah vs de bruyne` |
| `/transferencia` | `transfer_advice` | `/transferencia palmer por gordon` |
| `/calendarios` | `player_fixture_run` | `/calendarios mbappé` |
| `/diferenciales` | `differential_picks` | `/diferenciales menos del 10%` |
| `/chips` | `chip_advice` | `/chips triple capitan` |

The command list is configurable in `lib/slash-commands.ts` — English aliases or additional languages can be added without code changes. The slash command passes an `intent_hint` field on the request.

**`intent_hint` is already implemented (V2 Phase 1c).** `POST /ask` accepts `intent_hint` as an optional parameter. The allowlist and invariants are documented in `http_contract_fixtures.json`. The UI wires it via `lib/slash-commands.ts`.

---

## AI-Phrased vs Deterministic Display

The backend generates answers in two ways:
1. **Deterministic** (`llm_used=false`): Response text built by pure Python logic — 100% reproducible.
2. **AI-phrased** (`llm_used=true`): Text written by Claude, passed automated parity review against deterministic data.

**Display pattern:** Let `final_text` speak for itself. Show a subtle inline note at the bottom of the assistant bubble only when AI was used:
- `llm_used=true`: small muted text "Respuesta mejorada por IA"
- `llm_used=false`: nothing shown

---

## Intent Component Spec

> Note: These will be refined as implementation progresses.

| Component | Key Data | Notable UI |
|-----------|----------|------------|
| `CaptainCard` | `captain.*` | Score meter, tier badge (Safe=emerald, Upside=amber, Differential=violet, Avoid=red), set-piece tags |
| `ComparisonCard` | `comparison.*` | Two-column layout, winner highlight, margin label badge, reasons list, home/away FDR |
| `RankingTable` | `captain_ranking[]` | Sortable table, tier badge per row, rank number |
| `TransferCard` | `transfer.*` | Out→In arrow layout, score delta bar, recommendation badge, `budget_constraint`/`hit_warning` banners |
| `ChipCard` | `chip.*` | Chip icon, recommendation badge, signal metric, "chip unavailable" greyed state |
| `FixtureRunTable` | `fixture_run.*` | 5-column fixture grid, FDR colour scale, H/A tag per fixture |
| `DifferentialTable` | `differential.picks[]` | Ranked table, ownership % bar, cost display |
| `MultiIntentView` | `sub_responses[]` | Stacked cards, one per sub-response (recursive rendering) |

**FDR colour scale:** `1=#2ecc71, 2=#a8d8a8, 3=#f7f7a8, 4=#f4a262, 5=#e74c3c`

**Tier badge colours:** `safe=emerald, upside=amber, differential=violet, avoid=red, low_confidence=slate`

---

## Starter Prompts

Generic, no player names hardcoded — configurable in `lib/starters.ts`. Updated per gameweek context.
Rendered as clickable chips above the input bar; clicking populates input (user can edit before sending).

---

## Backend Deployment: Railway

**Why Railway:**
- No cold starts (always-on container) — backend loads CSV/parquet data on startup
- $5/month hobby plan covers early-stage traffic (<1000 req/day)
- Docker-based → trivially portable to Fly.io, Azure Container Apps, AWS ECS
- `fpl_server.py` is standard FastAPI — Railway auto-detects

**Portability:** A `Dockerfile` at `packages/fpl-grounded-assistant/Dockerfile` is the single deployment artifact — same image runs anywhere. No Railway-specific config.

**Cost model:**
- Railway: ~$5/month
- Vercel: free tier for early-stage frontend
- Total: ~$5/month to start

**Scaling path:** Railway → Fly.io (multi-region) → Azure Container Apps (enterprise) — same Docker image.

---

## Implementation Phases

### Phase 1 — Chat Shell (no intents, no auth) ✅ Complete
Goal: Working chat interface connected to live backend. `final_text` only.
- ~~Scaffold `packages/fpl-ui/` with `create-next-app` + shadcn/ui~~ ✅
- ~~`lib/types.ts` — TypeScript types for `FinalResponse`~~ ✅
- ~~`app/api/proxy/route.ts` — server-side proxy to Railway-hosted backend~~ ✅
- ~~`ChatShell`, `InputBar`, `MessageList`, `StarterPrompts` (generic)~~ ✅
- ~~Stateless mode only (POST /ask)~~ ✅
- `Dockerfile` + Railway deploy for backend — deferred to Phase 2.5/4

### Phase 2 — Intent Components + Session Mode + Squad Context ✅ Complete
Goal: Structured metadata rendered below `final_text`; multi-turn sessions; squad context.
- ~~CaptainCard, ComparisonCard~~ ✅
- ~~RankingTable, TransferCard, ChipCard, FixtureRunTable, DifferentialTable, MultiIntentView~~ ✅
- ~~Session toggle (stateless / session mode)~~ ✅
- ~~`SquadContextPanel`: FPL team ID input → auto-fetch ITB, chips, free transfers~~ ✅
- ~~Slash command `SlashMenu` (Spanish-first, keyboard nav, ARIA, `intent_hint` wired)~~ ✅
- 216 tests passing, clean build

### Phase 2.5 — Integration & Live Engine Connectivity
Goal: Connect the "beautiful shell" UI to a running Python backend with a live LLM engine. The UI currently has no backend to talk to; this phase is the bridge that makes the product functional end-to-end.

**Backend environment setup:**
- Create `packages/fpl-grounded-assistant/.env.template` with placeholders for `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `DEFAULT_PROVIDER`
- Default provider: **Gemini (Google)**; other providers remain warm but inactive unless their key is present and `DEFAULT_PROVIDER` is toggled
- Create `.gitignore` entry for `.env` in the backend package if not already present

**Dependency mapping (PYTHONPATH):**
- Create `packages/fpl-grounded-assistant/dev-backend.sh` — exports the full `PYTHONPATH` for all internal packages (`fpl-tool-runner`, `fpl-data-core`, `fpl-player-registry`, `fpl-captain-engine`, `fpl-api-client`, `fpl-pipeline`) and starts Uvicorn on `localhost:8000`
- No pip-install of internal packages required; script handles path resolution

**Frontend–backend bridge:**
- Verify `app/api/proxy/route.ts` correctly targets `http://localhost:8000` in dev
- Create `packages/fpl-ui/.env.local` (gitignored) with `FPL_BACKEND_URL=http://localhost:8000`
- Create `packages/fpl-ui/.env.local.template` as the checked-in reference

**LLM layer hardening (multi-provider):**
- Adjust `fpl_grounded_assistant/llm_layer.py` to support Gemini / Anthropic / OpenAI via `DEFAULT_PROVIDER` env var
- Gemini is the primary path; Anthropic and OpenAI remain functional fall-backs
- Graceful error if the selected provider's key is missing at startup

**Live data bootstrap:**
- Confirm `assemble_captain_context()` (or equivalent) successfully fetches FPL bootstrap data on server startup with the PYTHONPATH in place

**Success criterion:** A question typed in the UI receives a real grounded response from the Python engine.

### Phase 3 — Auth + Subscriber Gate + Patreon
Goal: Patreon-gated access.
- Clerk setup with custom Patreon OAuth2 provider
- `middleware.ts` protecting `/chat`
- Paywall page at `/subscribe` with Patreon link
- Patreon webhook handler to update Clerk user metadata

### Phase 4 — Hardening + Production Deploy
- `Dockerfile` for backend (Railway deploy)
- Domain + SSL on Vercel
- Environment variables secured
- Rate limiting on proxy route
- Error states for all intent components (`outcome != "ok"`)

---

## Critical Files

**Backend (existing):**
- [fpl_server.py](packages/fpl-grounded-assistant/fpl_server.py) — FastAPI app to Dockerize
- [final_response.py](packages/fpl-grounded-assistant/fpl_grounded_assistant/final_response.py) — Contract reference for TypeScript types
- [FINAL_RESPONSE_CONTRACT.md](packages/fpl-grounded-assistant/FINAL_RESPONSE_CONTRACT.md) — Rendering reference
- [conversation_fixtures.py](packages/fpl-grounded-assistant/fpl_grounded_assistant/conversation_fixtures.py) — Test fixtures for component development
- [router.py](packages/fpl-grounded-assistant/fpl_grounded_assistant/router.py) — intent_hint implementation (V2 Phase 1c, complete)

**Phase 2.5 (to create):**
- `packages/fpl-grounded-assistant/.env.template` — provider key placeholders
- `packages/fpl-grounded-assistant/dev-backend.sh` — PYTHONPATH + Uvicorn startup
- `packages/fpl-ui/.env.local.template` — frontend backend URL placeholder

**Phase 4 (to create):**
- `packages/fpl-grounded-assistant/Dockerfile`
