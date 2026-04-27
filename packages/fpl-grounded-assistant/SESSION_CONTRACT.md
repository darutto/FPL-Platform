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
