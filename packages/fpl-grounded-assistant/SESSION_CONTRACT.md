# FPL Grounded Assistant — HTTP Session Contract

Phase 4j: operational documentation for in-memory HTTP session lifecycle.

---

## Endpoint Reference

| Method | Path | Purpose |
|--------|------|---------|
| `POST /session` | Create a new session | Returns `session_id`, `created_at`, `expires_after_seconds` |
| `POST /session/{id}/ask` | Ask within a session | Multi-turn; resolves pronouns against previous turns |
| `GET /session/{id}` | Inspect session metadata | Returns `created_at`, `last_used_at`, `turn_count` |
| `DELETE /session/{id}` | Clear and remove session | Returns `{"status": "cleared", "session_id": ...}` |

Stateless endpoints (`POST /ask`, `GET /health`) are unaffected by session operations.

---

## TTL Behaviour

Sessions expire after **`_SESSION_TTL_SECONDS`** seconds of idle time (default: **1800 s / 30 min**).

- **Idle** is measured from `last_used_at`, which is updated after every successful
  `POST /session/{id}/ask`.
- `GET /session/{id}` does **not** update `last_used_at` and does not count as activity.
- TTL is enforced **lazily**: there is no background sweeper. Expired sessions are detected
  and removed when accessed via `POST /session/{id}/ask` or `GET /session/{id}`.
- An additional lazy sweep runs on every `POST /session`, removing all sessions whose
  `last_used_at` exceeds the TTL, before creating the new entry.
- Expired sessions return **HTTP 404** with `detail: "Session expired: <session_id>"`.
- Setting `_SESSION_TTL_SECONDS = 0` disables expiration entirely (no idle timeout).

---

## Max-Count Behaviour

A maximum of **`_SESSION_MAX_COUNT`** sessions may exist simultaneously (default: **100**).

- When the active session count is at or above the cap, `POST /session` returns
  **HTTP 429** with `detail: "Session cap reached (N). Clear idle sessions and retry."`.
- The lazy prune step runs **before** the cap check on every `POST /session`, so naturally
  expired sessions are swept first, then the cap is enforced on what remains.
- Setting `_SESSION_MAX_COUNT = 0` blocks all new sessions ("cap zero = no sessions allowed").
- After clearing one or more sessions via `DELETE /session/{id}`, `POST /session` will
  succeed again as long as the active count is below the cap.

---

## In-Memory / Non-Persistent Nature

Sessions are stored in a module-level Python dictionary (`_sessions`). Consequences:

- **Sessions do not survive server restarts.** All sessions are lost when the process exits.
- **Sessions are not shared across processes.** Each server process has an independent store.
- **There is no persistence layer.** No database, file, or external cache is involved.

This design is intentional — the session layer is lightweight and fully testable without
external dependencies.

---

## Single-Instance Assumption

The session store is a plain in-memory dict. This server is designed to run as a
**single process**.

- Do not run multiple instances behind a load balancer with sticky sessions disabled.
  Session lookups will fail if requests route to a different instance than the one where
  the session was created.
- If multi-instance or fault-tolerant sessions are needed, an external shared session store
  (Redis, Memcached) would be required. This is explicitly out of scope for the current design.

---

## `intent_hint` in Session Ask Requests (V2 Phase 1c)

`POST /session/{id}/ask` accepts an optional `intent_hint` field in the request body:

```json
{"question": "Haaland", "intent_hint": "player_fixture_run"}
```

Semantics are identical to `/ask`:
- **Deterministic router wins** — if `route(question)` succeeds, `intent_hint` is completely ignored.
  Fires only when the deterministic router returns no match for `question`.
- Allowlisted to 7 values (`captain_score`, `rank_candidates`, `compare_players`,
  `transfer_advice`, `chip_advice`, `player_fixture_run`, `differential_picks`).
- Invalid or omitted hints fall back silently — never cause errors.
- The bias is **per-turn** — it is not stored in session state and does not affect
  subsequent turns.

See `FINAL_RESPONSE_CONTRACT.md` for the full `intent_hint` semantics reference.

---

## HTTP Status Code Summary

| Status | Meaning |
|--------|---------|
| `200` | Operation succeeded. Inspect `supported`/`outcome` in body for domain result. |
| `404` | Session not found or expired. The `detail` field distinguishes the two cases. |
| `422` | Malformed request body (missing or invalid `question` field). |
| `429` | Session cap reached (`POST /session` only). Clear idle sessions and retry. |
| `503` | Bootstrap not initialised (should not occur in normal operation). |

---

## Example: Full Lifecycle

```python
from fastapi.testclient import TestClient
import fpl_server
from fpl_grounded_assistant import STANDARD_BOOTSTRAP

fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
client = TestClient(fpl_server.app)

# 1. Create session
r = client.post("/session")
session_id = r.json()["session_id"]
# r.json() = {"session_id": "...", "created_at": 1234567890.0, "expires_after_seconds": 1800}

# 2. Ask questions (multi-turn, pronouns resolved)
r1 = client.post(f"/session/{session_id}/ask", json={"question": "should I captain Haaland"})
r2 = client.post(f"/session/{session_id}/ask", json={"question": "should I captain him"})
# r2 resolves "him" to Haaland from turn 1

# 3. Inspect metadata
info = client.get(f"/session/{session_id}").json()
# {"session_id": "...", "created_at": ..., "last_used_at": ..., "turn_count": 2}

# 4. Clear
client.delete(f"/session/{session_id}")
# After this, the session_id is no longer valid -> HTTP 404
```

---

## Example: TTL Expiry and Cap

```python
# TTL expiry -- expired session returns 404
r = client.post("/session")
session_id = r.json()["session_id"]
# ... time passes (> _SESSION_TTL_SECONDS seconds of inactivity) ...
r2 = client.post(f"/session/{session_id}/ask", json={"question": "..."})
# r2.status_code == 404, r2.json()["detail"] == "Session expired: <session_id>"

# Cap -- 429 when at limit
for _ in range(100):
    client.post("/session")  # fills the store
r = client.post("/session")
# r.status_code == 429
```

---

## Deferred Capabilities

These were intentionally excluded and remain out of scope:

- Session persistence across server restarts
- Multi-instance / distributed session sharing
- Authentication or authorisation on session endpoints
- Automatic background TTL sweeping (TTL is checked lazily only)
- Per-session resolver client injection over HTTP

---

## Phase M5 — Routing Telemetry and Go/No-Go Counters

Added in M5 (2026-05-17). Operational reference for the `/healthz` endpoint
and the graduation criteria for merging `MCP_architecture` to `main`.

**Coverage scope (pre-graduation reality).** The M5 counters are populated only by `ask_v2()` and `POST /ask-orchestrated`. `POST /ask` continues to route through `respond()` and the legacy Orch-4a gate at `final_response.py:1926`; its traffic is **NOT** counted in `routing_counters`. The `graduation.ready_to_graduate` flag therefore reflects only shadow / internal / test traffic until the next branch rewires `POST /ask` to call `ask_v2()`. Treat `/healthz` as a *shadow-traffic* dashboard until that rewiring lands.

### Reading the counters: `GET /healthz`

```
GET /healthz
```

Returns two sub-dicts: `routing_counters` (raw counts) and `graduation`
(derived metrics and boolean criteria).  Counters are process-global and
cumulative since last process restart.

**Counter key meanings**

| Key | What it counts |
|-----|---------------|
| `resource` | `@resource` inputs that matched a registered resource and returned grounded rows |
| `prompt` | `/prompt` inputs (expansion, dispatch, or clarification) |
| `route` | Plain-text inputs where the deterministic `route()` succeeded on the first try |
| `classifier_rewrite` | Plain-text inputs where `route()` missed, the LLM classifier rewrote the question, and `route()` succeeded on the rewrite |
| `orchestrator` | Plain-text inputs where all deterministic paths missed AND the orchestrator returned a grounded tool call |
| `unsupported` | Inputs where no path produced a grounded answer (the reject bucket) |
| `orchestrator_attempted` | Every invocation of the orchestrator loop, regardless of grounding outcome |
| `orchestrator_grounded` | Subset of `orchestrator_attempted` that yielded a usable tool-grounded answer |
| `total_primary` | Sum of `resource + prompt + route + classifier_rewrite + orchestrator + unsupported` — one per distinct request |
| `reject_rate` | `unsupported / total_primary` |

**Why `orchestrator_attempted` != `orchestrator_grounded`**

Per Adversarial Review finding R5: the orchestrator can be called but fail to
ground (e.g. LLM chose no tool, tool errored, or tool result was unparseable).
The two counters are always distinct and never collapsed.

### Answering the three go/no-go questions

**Q1: Which branch fired?** — `routing_counters.{resource,prompt,route,classifier_rewrite,orchestrator,unsupported}`

**Q2: Why?** — The `graduation` sub-dict computes `deterministic_share`
(the fraction of inputs grounded by deterministic paths) and `reject_rate`
(the fraction fully rejected).  High `reject_rate` means deterministic surface
is missing intents; high `orchestrator_grounded_share` without high
`deterministic_share` means the LLM is doing too much.

**Q3: How often?** — `graduation.total_observations` is the total request count.

### Graduation criteria (plan §M5, line 322)

| Criterion | Target | Counter |
|-----------|--------|---------|
| Deterministic share | >= 80% | `graduation.criteria.deterministic_share_ge_80` |
| Reject rate | < 5% | `graduation.criteria.reject_rate_lt_5` |
| Orchestrator long-tail | Informational | `graduation.orchestrator_grounded_share` |

`graduation.ready_to_graduate` is `true` iff all criteria are met AND
`total_observations > 0`.  The Lead Orchestrator makes the merge decision;
`ready_to_graduate` is an input to that decision, not the decision itself.

**`classifier_rewrite` counts as deterministic** because the LLM only rewrites
the question to a canonical form — `route()` then grounds it via a deterministic
tool.  The LLM does not generate the answer.

### Example snapshot (healthy system)

```json
GET /healthz
{
  "routing_counters": {
    "resource": 120,
    "prompt": 85,
    "route": 640,
    "classifier_rewrite": 55,
    "orchestrator": 40,
    "unsupported": 30,
    "orchestrator_attempted": 52,
    "orchestrator_grounded": 40,
    "total_primary": 970,
    "reject_rate": 0.031
  },
  "graduation": {
    "deterministic_share": 0.928,
    "orchestrator_grounded_share": 0.041,
    "reject_rate": 0.031,
    "criteria": {
      "deterministic_share_ge_80": true,
      "reject_rate_lt_5": true
    },
    "ready_to_graduate": true,
    "total_observations": 970
  }
}
```

This system is ready to graduate: 92.8% deterministic share, 3.1% reject rate,
orchestrator handles 4.1% of traffic as intended long-tail.

### Schema constants

The `routing_trace` field (present on every `ask_v2()` return and on
`POST /ask-orchestrated` responses) uses the frozen schema declared in:

The synthetic `decision_kind = decision_outcome = "orchestrator_direct"` value emitted by `POST /ask-orchestrated` is **transitional**. It exists because that endpoint bypasses `decision_router` entirely. The value retires alongside the `/ask-orchestrated` route when the next branch graduates the orchestrator into `POST /ask`. See the plan's §"Risks and Tradeoffs" for the explicit 3-step graduation blueprint for the next branch.

```
packages/fpl-grounded-assistant/fpl_grounded_assistant/harness.py
  ROUTING_TRACE_REQUIRED_KEYS  — always-present keys (frozenset, 12 keys)
  ROUTING_TRACE_OPTIONAL_KEYS  — branch-conditional keys (frozenset, 5 keys)
```

A frozen-schema test pins `set(trace.keys()) >= ROUTING_TRACE_REQUIRED_KEYS`
for every branch.  See `run_phase_m5_tests.py` suite A.
