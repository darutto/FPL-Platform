"""
FPL Grounded Assistant -- HTTP session lifecycle examples.
==========================================================
Phase 4j: session interaction examples and operational docs.
Phase 5j: structured comparison player context in session responses.

Shows how to exercise the full session lifecycle over HTTP.
Uses FastAPI ``TestClient`` for in-process execution -- no running server needed.

Flows covered
-------------
create_ask_inspect_clear  -- full lifecycle: create, 2 turns, inspect, clear
pronoun_follow_up         -- pronoun reference resolved across turns

Edge cases covered
------------------
session_not_found         -- ask/get on missing session_id -> HTTP 404
clear_missing_session     -- DELETE on non-existent session -> HTTP 404
ttl_expiry                -- idle-expired session -> HTTP 404 on ask
cap_reached               -- POST /session at max count -> HTTP 429

Key session HTTP contract
-------------------------
POST   /session               -- create session; returns session_id
POST   /session/{id}/ask      -- multi-turn question; returns SessionAskResponse
GET    /session/{id}          -- inspect metadata: created_at, last_used_at, turn_count
DELETE /session/{id}          -- clear session; returns {"status": "cleared", ...}

HTTP status codes
-----------------
200   Request processed (inspect supported/outcome in body for domain result)
404   session_id not found or expired
422   Malformed request body
429   Session cap reached (POST /session only)
503   Bootstrap not initialised

Operational behaviour
---------------------
- Sessions are in-memory only -- not persisted across server restarts
- Sessions expire after _SESSION_TTL_SECONDS seconds of idle time (default 1800s)
- Maximum _SESSION_MAX_COUNT sessions allowed at once (default 100)
- Expired sessions are removed lazily on access or pruned on POST /session
- This server is not designed for multi-instance / shared-memory deployments

To call a live server instead of using TestClient, replace ``make_session_client()``
with a ``requests.Session`` pointed at your server URL::

    import requests
    s = requests.Session()
    r = s.post("http://localhost:8000/session")
    session_id = r.json()["session_id"]

Run directly::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python examples/session_examples.py

Or import from a test runner::

    from examples.session_examples import (
        SESSION_FLOWS, SESSION_EDGE_CASES,
        run_session_flow, run_edge_case, make_session_client,
    )
"""
from __future__ import annotations

import time
from typing import Any

import fpl_server
from fastapi.testclient import TestClient
from fpl_grounded_assistant import STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def make_session_client() -> TestClient:
    """Return a TestClient with STANDARD_BOOTSTRAP pre-injected and sessions cleared.

    In production, replace with ``requests.Session`` pointed at your server URL.
    """
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._clear_sessions()
    return TestClient(fpl_server.app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Session flow definitions
# ---------------------------------------------------------------------------

SESSION_FLOWS: list[dict[str, Any]] = [
    {
        "id": "create_ask_inspect_clear",
        "turns": [
            {"question": "should I captain Haaland"},
            {"question": "what is the current gameweek"},
        ],
        "note": (
            "Full session lifecycle: create -> ask turn 1 -> ask turn 2 -> "
            "inspect (turn_count=2) -> clear -> verify 404 after clear. "
            "Demonstrates explicit session lifecycle management."
        ),
    },
    {
        "id": "pronoun_follow_up",
        "turns": [
            {"question": "should I captain Haaland"},
            {"question": "should I captain him"},
        ],
        "note": (
            "Pronoun follow-up resolved via ConversationSession. "
            "Turn 2 'him' refers to Haaland from turn 1. "
            "Both turns return supported=True, outcome='ok'."
        ),
    },
    # Phase 5e: comparison session flows
    {
        "id": "comparison_direct",
        "turns": [
            {"question": "compare Haaland and Salah"},
        ],
        "note": (
            "Single-turn player comparison over HTTP session. "
            "outcome='ok', intent='compare_players'. "
            "final_text includes explanation-enriched recommendation with "
            "winner, margin label, and Advantages clause (Phase 5d). "
            "Response body includes comparison.player_a and comparison.player_b "
            "with web_name, position, captain_score, role_bonus, set_piece_notes "
            "(Phase 5i/5j)."
        ),
    },
    {
        "id": "comparison_followup",
        "turns": [
            {"question": "compare Haaland and Salah"},
            {"question": "And Saka?"},
        ],
        "note": (
            "Comparison follow-up resolved via ConversationSession. "
            "Turn 1: compare Haaland vs Salah, sets last_comparison state. "
            "Turn 2: 'And Saka?' resolves to 'compare Haaland and Saka' deterministically. "
            "Both turns return outcome='ok', intent='compare_players'. "
            "Both turns expose identical comparison structure with player_a/b context "
            "(Phase 5i/5j parity)."
        ),
    },
    # Phase 5j: structured comparison player context
    {
        "id": "comparison_structured",
        "turns": [
            {"question": "compare Haaland and Saka"},
        ],
        "note": (
            "Demonstrates structured comparison player context in session response body. "
            "comparison.player_a: web_name='Haaland', position='FWD', "
            "role_bonus=5.0, set_piece_notes=['penalty_taker_1']. "
            "comparison.player_b: web_name='Saka', position='MID', "
            "role_bonus=0.5, set_piece_notes=['freekick_taker_2']. "
            "comparison.reasons includes 'set-piece advantage (pen vs fk2)' (Phase 5h)."
        ),
    },
]


# ---------------------------------------------------------------------------
# Session edge case definitions
# ---------------------------------------------------------------------------

SESSION_EDGE_CASES: list[dict[str, Any]] = [
    {
        "id": "session_not_found",
        "note": (
            "POST /session/{id}/ask and GET /session/{id} with an unknown session_id "
            "both return HTTP 404. The session_id must be created first via POST /session."
        ),
    },
    {
        "id": "clear_missing_session",
        "note": (
            "DELETE /session/{id} on a non-existent session returns HTTP 404. "
            "Idempotent double-clear: first call 200, second call 404."
        ),
    },
    {
        "id": "ttl_expiry",
        "note": (
            "Session idle past _SESSION_TTL_SECONDS is treated as expired. "
            "POST /session/{id}/ask on an expired session returns HTTP 404 with 'expired'. "
            "GET /session/{id} on the same session also returns HTTP 404."
        ),
    },
    {
        "id": "cap_reached",
        "note": (
            "POST /session when _SESSION_MAX_COUNT sessions already exist returns HTTP 429. "
            "After clearing one session, POST /session succeeds again."
        ),
    },
]


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def run_session_flow(flow: dict[str, Any], client: TestClient) -> dict[str, Any]:
    """Run a full session flow and return a result summary.

    Steps:
    1. POST /session -- create
    2. POST /session/{id}/ask for each turn
    3. GET /session/{id} -- inspect after all turns
    4. DELETE /session/{id} -- clear
    5. GET /session/{id} -- verify 404 after clear

    Parameters
    ----------
    flow:
        One entry from ``SESSION_FLOWS``.
    client:
        TestClient (or requests.Session) to use for HTTP calls.

    Returns
    -------
    dict with keys: flow_id, session_id, create_status, turns (list),
    inspect_status, inspect_body, clear_status, after_clear_status.
    """
    create_resp = client.post("/session")
    if create_resp.status_code != 200:
        return {"flow_id": flow["id"], "error": f"create failed: {create_resp.status_code}"}

    session_id = create_resp.json()["session_id"]

    turn_results: list[dict[str, Any]] = []
    for turn in flow["turns"]:
        r = client.post(
            f"/session/{session_id}/ask",
            json={"question": turn["question"]},
        )
        body = r.json() if r.status_code == 200 else {}
        turn_results.append({"status": r.status_code, "body": body})

    inspect_resp = client.get(f"/session/{session_id}")
    inspect_body = inspect_resp.json() if inspect_resp.status_code == 200 else {}

    clear_resp = client.delete(f"/session/{session_id}")

    after_clear_resp = client.get(f"/session/{session_id}")

    return {
        "flow_id": flow["id"],
        "session_id": session_id,
        "create_status": create_resp.status_code,
        "create_body": create_resp.json(),
        "turns": turn_results,
        "inspect_status": inspect_resp.status_code,
        "inspect_body": inspect_body,
        "clear_status": clear_resp.status_code,
        "after_clear_status": after_clear_resp.status_code,
    }


def run_edge_case(edge_case: dict[str, Any], client: TestClient) -> dict[str, Any]:
    """Run a single edge case and return a result summary.

    For ``ttl_expiry`` and ``cap_reached``, modifies ``fpl_server`` config
    and always restores it on exit via try/finally.

    Parameters
    ----------
    edge_case:
        One entry from ``SESSION_EDGE_CASES``.
    client:
        TestClient (or requests.Session) to use for HTTP calls.

    Returns
    -------
    dict with edge_id and scenario-specific status/body keys.
    """
    eid = edge_case["id"]

    if eid == "session_not_found":
        fake_id = "00000000-0000-0000-0000-000000000000"
        ask_resp = client.post(
            f"/session/{fake_id}/ask",
            json={"question": "should I captain Haaland"},
        )
        get_resp = client.get(f"/session/{fake_id}")
        return {
            "edge_id": eid,
            "ask_status": ask_resp.status_code,
            "ask_detail": ask_resp.json().get("detail", ""),
            "get_status": get_resp.status_code,
            "get_detail": get_resp.json().get("detail", ""),
        }

    if eid == "clear_missing_session":
        fake_id = "00000000-0000-0000-0000-000000000001"
        del_resp = client.delete(f"/session/{fake_id}")
        return {
            "edge_id": eid,
            "delete_status": del_resp.status_code,
            "delete_detail": del_resp.json().get("detail", ""),
        }

    if eid == "ttl_expiry":
        orig_ttl = fpl_server._SESSION_TTL_SECONDS
        fpl_server._SESSION_TTL_SECONDS = 60  # type: ignore[assignment]
        try:
            cr = client.post("/session")
            sid = cr.json()["session_id"]
            # Simulate expiry: push last_used_at 9999 seconds into the past
            fpl_server._sessions[sid].last_used_at = time.time() - 9999
            ask_resp = client.post(
                f"/session/{sid}/ask",
                json={"question": "should I captain Haaland"},
            )
            get_resp = client.get(f"/session/{sid}")
        finally:
            fpl_server._SESSION_TTL_SECONDS = orig_ttl  # type: ignore[assignment]
        return {
            "edge_id": eid,
            "ask_status": ask_resp.status_code,
            "ask_detail": ask_resp.json().get("detail", "") if ask_resp.status_code != 200 else "",
            "get_status": get_resp.status_code,
        }

    if eid == "cap_reached":
        orig_cap = fpl_server._SESSION_MAX_COUNT
        fpl_server._clear_sessions()
        fpl_server._SESSION_MAX_COUNT = 2  # type: ignore[assignment]
        try:
            r1 = client.post("/session")
            r2 = client.post("/session")
            r3 = client.post("/session")  # should 429
            # clear one and retry
            if r1.status_code == 200:
                client.delete(f"/session/{r1.json()['session_id']}")
            r4 = client.post("/session")  # should succeed now
        finally:
            fpl_server._SESSION_MAX_COUNT = orig_cap  # type: ignore[assignment]
            fpl_server._clear_sessions()
        return {
            "edge_id": eid,
            "create_1_status": r1.status_code,
            "create_2_status": r2.status_code,
            "create_3_status": r3.status_code,
            "create_3_detail": r3.json().get("detail", "") if r3.status_code == 429 else "",
            "create_after_clear_status": r4.status_code,
        }

    return {"edge_id": eid, "error": f"unknown edge case: {eid}"}


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("FPL HTTP Session Lifecycle Examples\n")
    client = make_session_client()

    print("Session flows\n" + "-" * 40)
    for flow in SESSION_FLOWS:
        result = run_session_flow(flow, client)
        turns_ok = all(t["status"] == 200 for t in result.get("turns", []))
        lifecycle_ok = (
            result.get("create_status") == 200
            and result.get("inspect_status") == 200
            and result.get("clear_status") == 200
            and result.get("after_clear_status") == 404
        )
        label = "PASS" if (turns_ok and lifecycle_ok) else "FAIL"
        print(f"[{label}] {flow['id']}")
        print(f"       {flow['note']}")
        ib = result.get("inspect_body", {})
        if ib:
            print(f"       turn_count={ib.get('turn_count', '?')}  "
                  f"create_status={result.get('create_status')}  "
                  f"clear_status={result.get('clear_status')}  "
                  f"after_clear_status={result.get('after_clear_status')}")
        print()

    print("Edge cases\n" + "-" * 40)
    for ec in SESSION_EDGE_CASES:
        fpl_server._clear_sessions()
        result = run_edge_case(ec, client)
        print(f"[INFO] {ec['id']}")
        print(f"       {ec['note']}")
        print(f"       result: {result}")
        print()
