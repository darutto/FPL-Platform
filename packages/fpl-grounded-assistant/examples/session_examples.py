"""
FPL Grounded Assistant -- HTTP session lifecycle examples.
==========================================================
Phase 4j: session interaction examples and operational docs.
Phase 5j: structured comparison player context in session responses.
Phase 5o: structured captain score metadata in session responses.
Phase 5q: structured ranked captain metadata in session responses.
Phase 7c: structured transfer and chip metadata in session responses.
Phase 7f: deterministic transfer follow-up resolution in session flows.
Phase 7h: player fixture run structured metadata in session responses.
Phase 8a1: position-aware scoring -- GKP comparison metadata in session responses.
V2 Phase 1d: intent_hint contract example -- routing bias via session turn.

Shows how to exercise the full session lifecycle over HTTP.
Uses FastAPI ``TestClient`` for in-process execution -- no running server needed.

Flows covered
-------------
create_ask_inspect_clear     -- full lifecycle: create, 2 turns, inspect, clear
pronoun_follow_up            -- pronoun reference resolved across turns
transfer_structured          -- single-turn transfer advice; structured transfer payload (Phase 7c)
chip_structured              -- single-turn chip advice; structured chip payload (Phase 7c)
multi_intent_transfer_and_chip -- one question splits into transfer + chip sub-responses (Phase 7c)
transfer_followup            -- deterministic transfer follow-up across turns (Phase 7f)
fixture_run_structured       -- single-turn fixture run; structured fixture_run payload (Phase 7h)
fixture_run_followup         -- deterministic fixture run follow-up across turns (Phase 8d-i)
differential_followup        -- deterministic differential follow-up across turns (Phase 8d-ii)
differential_picks_structured -- single-turn differential picks; structured differential payload (Phase 7g)
position_score_gkp_comparison -- single-turn GKP vs FWD comparison; position_score
                             (Phase 8a1 position-aware heuristic)
intent_hint_session          -- single-turn with intent_hint in request body (V2 Phase 1d)

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

# Minimal bootstrap extension for differential picks session example.
_DIFFERENTIAL_BOOTSTRAP = {
    **STANDARD_BOOTSTRAP,
    "elements": STANDARD_BOOTSTRAP["elements"] + [
        {
            "id": 10, "first_name": "Cole", "second_name": "Palmer",
            "web_name": "Palmer", "team": 8, "team_code": 8, "element_type": 3,
            "status": "a", "now_cost": 60, "selected_by_percent": "3.5",
            "form": "7.0", "expected_goals": "0.40", "expected_assists": "0.50",
            "expected_goal_involvements": "0.90", "minutes": 1800,
            "penalties_order": 1, "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None,
        },
        {
            "id": 11, "first_name": "Bryan", "second_name": "Mbeumo",
            "web_name": "Mbeumo", "team": 11, "team_code": 12, "element_type": 4,
            "status": "a", "now_cost": 75, "selected_by_percent": "8.2",
            "form": "5.0", "expected_goals": "0.30", "expected_assists": "0.20",
            "expected_goal_involvements": "0.50", "minutes": 1620,
            "penalties_order": 1, "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None,
        },
    ],
    "fixture_difficulty_map": {
        **STANDARD_BOOTSTRAP["fixture_difficulty_map"],
        11: 2,
    },
}


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
    # Phase 5o: structured captain score metadata
    {
        "id": "captain_structured",
        "turns": [
            {"question": "should I captain Salah"},
        ],
        "note": (
            "Demonstrates structured captain score metadata in session ask response (Phase 5n/5o). "
            "captain.web_name='Salah', captain.team_short='LIV', captain.tier='safe', "
            "captain.role_bonus=5.0, captain.set_piece_notes=['penalty_taker_1']. "
            "Shape is identical to /ask response and CLI debug captain payloads. "
            "Non-captain turns in the same session do not include the captain key."
        ),
    },
    # Phase 5q: structured ranked captain candidates in session response
    {
        "id": "captain_ranking_structured",
        "turns": [
            {
                "question": "top captains this week",
                "candidates_list": [
                    {"query": "Salah"},
                    {"query": "Haaland"},
                    {"query": "Saka"},
                ],
            },
        ],
        "note": (
            "Demonstrates structured captain_ranking in session ask response (Phase 5p/5q). "
            "captain_ranking is a list of entries each with rank, web_name, team_short, "
            "captain_score, tier, role_bonus, set_piece_notes. "
            "Salah: rank=1, tier='safe', set_piece_notes=['penalty_taker_1']. "
            "Haaland: rank=2, tier='upside'. Saka: rank=3, tier='differential'. "
            "Shape is identical to /ask response and CLI debug captain_ranking payloads. "
            "Non-ranking turns in the same session do not include a non-null captain_ranking."
        ),
    },
    # Phase 7c: structured transfer metadata in session response
    {
        "id": "transfer_structured",
        "turns": [
            {"question": "should I sell Saka for Salah"},
        ],
        "note": (
            "Demonstrates structured transfer metadata in session ask response (Phase 7a/7c). "
            "transfer.player_out='Saka', transfer.player_in='Salah', "
            "transfer.recommendation='transfer_in' (Salah > Saka by a large margin), "
            "transfer.score_delta (float), transfer.price_delta (int), "
            "transfer.reasons (list of reason strings). "
            "Shape is identical to /ask response and CLI debug transfer payloads. "
            "Non-transfer turns in the same session do not include a non-null transfer."
        ),
    },
    # Phase 7c: structured chip metadata in session response
    {
        "id": "chip_structured",
        "turns": [
            {"question": "should I use triple captain this week"},
        ],
        "note": (
            "Demonstrates structured chip metadata in session ask response (Phase 7b/7c). "
            "chip.chip='triple_captain', chip.recommendation in "
            "{conditions_favorable, conditions_marginal, conditions_unfavorable}, "
            "chip.gw (int or null), chip.signal_value (top MID/FWD captain score, float), "
            "chip.signal_label='top captain score'. "
            "Shape is identical to /ask response and CLI debug chip payloads. "
            "Non-chip turns in the same session do not include a non-null chip."
        ),
    },
    # Phase 7c: multi-intent question splits into transfer + chip sub-responses
    {
        "id": "multi_intent_transfer_and_chip",
        "turns": [
            {"question": "should I sell Saka for Salah and should I bench boost now"},
        ],
        "note": (
            "Multi-intent question splits into transfer_advice + chip_advice sub-responses. "
            "Turn body has intent='multi_intent' and sub_responses with two entries. "
            "The transfer sub-response carries a 'transfer' dict (player_out, player_in, etc.). "
            "The chip sub-response carries a 'chip' dict (chip='bench_boost', signal_value, etc.). "
            "The top-level transfer and chip fields of the SessionAskResponse are null "
            "(metadata lives only in sub_responses for multi-intent turns). "
            "Demonstrates that transfer and chip metadata is correctly scoped "
            "to the sub-response that produced it."
        ),
    },
    # Phase 7f: deterministic transfer follow-up resolution
    {
        "id": "transfer_followup",
        "turns": [
            {"question": "should I sell Saka for Salah"},
            {"question": "what about Haaland instead?"},
        ],
        "note": (
            "Demonstrates deterministic transfer follow-up resolution (Phase 7f). "
            "Turn 1: transfer advice for Saka → Salah; outcome='ok'; "
            "transfer.player_out='Saka', transfer.player_in='Salah'. "
            "Turn 2: 'what about Haaland instead?' is deterministically rewritten to "
            "'sell Saka for Haaland' without any LLM involvement. "
            "Turn 2 outcome='ok'; transfer.player_out='Saka', transfer.player_in='Haaland'. "
            "Session inspect after turn 2 shows last_transfer={'player_out': 'Saka', "
            "'player_in': 'Haaland'} and last_resolver_source='transfer_followup'."
        ),
    },
    # Phase 7h: structured fixture run metadata in session response
    {
        "id": "fixture_run_structured",
        "bootstrap": STANDARD_BOOTSTRAP,
        "turns": [
            {"question": "Salah fixtures"},
        ],
        "note": (
            "Demonstrates structured fixture run metadata in session ask response (Phase 7h). "
            "fixture_run.web_name='Salah', fixture_run.team_short='LIV', "
            "fixture_run.position='MID', fixture_run.horizon=5, "
            "fixture_run.current_gameweek (int), "
            "fixture_run.fixtures (list of {gameweek, opponent_short, is_home, difficulty}). "
            "Shape is identical to /ask response and CLI debug fixture_run payloads. "
            "Non-fixture turns in the same session do not include a non-null fixture_run."
        ),
    },
    # Phase 7g: structured differential picks metadata in session response
    {
        "id": "differential_picks_structured",
        "bootstrap": _DIFFERENTIAL_BOOTSTRAP,
        "turns": [
            {"question": "good differentials"},
        ],
        "note": (
            "Demonstrates structured differential picks metadata in session ask response (Phase 7g). "
            "differential.ownership_threshold=15.0, differential.top_n (int), "
            "differential.picks (list of {rank, web_name, team_short, position, "
            "captain_score, ownership, now_cost}). "
            "Players filtered to status='a' and ownership < 15%. "
            "Ranked by deterministic captain score descending. "
            "Shape is identical to /ask response and CLI debug differential payloads. "
            "Non-differential turns in the same session do not include a non-null differential."
        ),
    },
    # Phase 8a1: position-aware heuristic -- GKP comparison metadata in session response
    {
        "id": "position_score_gkp_comparison",
        "bootstrap": STANDARD_BOOTSTRAP,
        "turns": [
            {"question": "compare Raya and Haaland"},
        ],
        "note": (
            "Demonstrates Phase 8a1 position-aware scoring in session ask response (Phase 8a1). "
            "comparison.player_a (Raya, GKP) and comparison.player_b (Haaland, FWD) each include: "
            "web_name, position, captain_score (canonical Layer 1), "
            "position_score (Layer 2 position-aware heuristic), role_bonus, set_piece_notes. "
            "position_score uses position-specific weight profiles over 7 normalised "
            "components (form, fixture, xgi, minutes, saves, cs, dc). "
            "GKP weights saves and clean_sheet; FWD uses canonical MID weights "
            "(transitional bridge). "
            "Canonical captain_score preserved unchanged for auditability. "
            "Shape is identical to /ask response and CLI debug comparison payloads. "
            "Non-comparison turns in the same session do not include a non-null comparison."
        ),
    },
    # Phase 8d-i: deterministic fixture run follow-up resolution
    {
        "id": "fixture_run_followup",
        "bootstrap": STANDARD_BOOTSTRAP,
        "turns": [
            {"question": "Haaland fixtures"},
            {"question": "what about Salah?"},
        ],
        "note": (
            "Demonstrates deterministic fixture run follow-up resolution (Phase 8d-i). "
            "Turn 1: 'Haaland fixtures' resolves as a fixture run question; "
            "session inspect after turn 1 shows last_fixture_run_player='Haaland'. "
            "Turn 2: 'what about Salah?' is deterministically rewritten to "
            "'Salah fixtures' without any LLM involvement; "
            "resolver_source='fixture_run_followup'. "
            "Turn 2 fixture_run.web_name='Salah'. "
            "Session inspect after turn 2 shows last_fixture_run_player='Salah' "
            "and last_resolver_source='fixture_run_followup'. "
            "Bare name pattern also supported: 'Salah?' → 'Salah fixtures' (≤3 words, "
            "no interrogative starter)."
        ),
    },
    # Phase 8d-ii: deterministic differential follow-up resolution
    {
        "id": "differential_followup",
        "bootstrap": _DIFFERENTIAL_BOOTSTRAP,
        "turns": [
            {"question": "good differentials"},
            {"question": "what about Mbeumo?"},
        ],
        "note": (
            "Demonstrates deterministic differential follow-up resolution (Phase 8d-ii). "
            "Turn 1: 'good differentials' resolves as a differential picks question; "
            "session inspect after turn 1 shows last_differential=True. "
            "Turn 2: 'what about Mbeumo?' is deterministically rewritten to "
            "'should I captain Mbeumo?' without any LLM involvement; "
            "resolver_source='differential_followup'. "
            "Turn 2 routes to captain score path (INTENT_CAPTAIN_SCORE). "
            "Session inspect after turn 2 shows last_differential=False (cleared by "
            "non-differential turn) and last_resolver_source='differential_followup'. "
            "Bare name pattern also supported: 'Mbeumo?' -> "
            "'should I captain Mbeumo?' (<=3 words, no interrogative starter)."
        ),
    },
    # V2 Phase 1d: intent_hint routing bias in session ask
    {
        "id": "intent_hint_session",
        "turns": [
            {"question": "Haaland", "intent_hint": "player_fixture_run", "debug": True},
        ],
        "note": (
            "Single-turn session with intent_hint in the request body (V2 Phase 1c/1d). "
            "Bare name 'Haaland' does not route deterministically; "
            "intent_hint='player_fixture_run' synthesises 'Haaland fixtures' "
            "and routes it via the hint path. "
            "outcome='ok', intent='player_fixture_run'. "
            "debug.classification_source='intent_hint' confirms the hint fired. "
            "The intent_hint field is forwarded from the session ask request body to "
            "ConversationSession.respond() transparently. "
            "Demonstrates that routing bias is per-turn -- it does not persist in session state."
        ),
    },
    # Phase 8b: venue-aware fixture factor -- comparison metadata in session response
    {
        "id": "venue_aware_comparison_session",
        "bootstrap": STANDARD_BOOTSTRAP,
        "turns": [
            {"question": "compare Salah and Saka"},
        ],
        "note": (
            "Phase 8b venue-aware comparison in session ask response. "
            "STANDARD_BOOTSTRAP has team_fixtures for GW28. "
            "comparison.player_a (Salah, MID) and comparison.player_b (Saka, MID) each include: "
            "is_home (True -- both home in GW28) and effective_fdr (float: 3.5 and 4.5). "
            "Layer 2 position_score uses effective_fdr for fixture component; "
            "Layer 1 captain_score still uses raw int FDR -- unchanged. "
            "When team_fixtures is absent from bootstrap, is_home=null and "
            "effective_fdr equals raw FDR (no adjustment). "
            "Shape is identical to /ask response and CLI debug comparison payloads."
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
        ask_body: dict[str, Any] = {"question": turn["question"]}
        if "candidates_list" in turn:
            ask_body["candidates_list"] = turn["candidates_list"]
        if "intent_hint" in turn:
            ask_body["intent_hint"] = turn["intent_hint"]
        if "debug" in turn:
            ask_body["debug"] = turn["debug"]
        r = client.post(
            f"/session/{session_id}/ask",
            json=ask_body,
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
