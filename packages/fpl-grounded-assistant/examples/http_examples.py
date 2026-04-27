"""
FPL Grounded Assistant — HTTP integration examples.
====================================================
Phase 4d: external integration examples and client fixtures.
Phase 5j: structured comparison payload exposure in HTTP body.
Phase 5o: structured captain payload exposure in HTTP body.
Phase 5q: structured ranked captain payload exposure in HTTP body.
Phase 7c: structured transfer and chip payload exposure in HTTP body.
Phase 8a1: position-aware scoring — GKP comparison structured payload in HTTP body.
V2 Phase 1d: intent_hint contract examples — valid hint, deterministic-wins, invalid hint.

Shows how to call ``POST /ask`` and ``GET /health`` for each supported scenario.
Uses FastAPI ``TestClient`` for in-process execution — no running server needed.

To call a live server instead, replace ``make_client()`` / ``TestClient`` with
``requests.Session`` pointed at your server URL::

    import requests
    session = requests.Session()
    resp = session.post("http://localhost:8000/ask",
                        json={"question": "should I captain Haaland"})
    body = resp.json()

Scenarios covered
-----------------
supported_ok               -- captain score for a known player
supported_ambiguous        -- player name matches multiple entries
supported_not_found        -- supported intent, player not in registry
supported_missing_arguments -- ranking intent without candidates_list
unsupported_intent         -- question outside the supported intent set
malformed_request          -- missing required 'question' field → HTTP 422
service_not_ready          -- bootstrap not initialised → HTTP 503
comparison_structured        -- direct comparison showing player_a/b context (Phase 5i/5j)
captain_structured           -- direct captain score showing structured captain payload (Phase 5n/5o)
captain_ranking_structured   -- ranked captain query showing structured captain_ranking payload (Phase 5p/5q)
transfer_structured          -- transfer advice showing structured transfer payload (Phase 7a/7c)
chip_structured              -- chip advice showing structured chip payload (Phase 7b/7c)
fixture_run_structured       -- player fixture run showing structured fixture_run payload (Phase 7h)
differential_picks_structured -- differential picks showing structured differential payload (Phase 7g)
position_score_gkp_comparison -- GKP vs FWD comparison showing position_score
                              (Phase 8a1 position-aware heuristic)
intent_hint_valid             -- bare name + valid hint routes via hint (V2 Phase 1d)
intent_hint_no_change         -- routable question + hint; deterministic route wins (V2 Phase 1d)
intent_hint_invalid_safe      -- bare name + invalid hint; safe unsupported_intent (V2 Phase 1d)

Key HTTP status contract
-------------------------
- HTTP 200  -- request was processed (inspect ``supported`` / ``outcome`` in body)
- HTTP 422  -- malformed request (missing or invalid ``question`` field)
- HTTP 503  -- service not ready (bootstrap not yet initialised)

Domain outcomes are always carried in the JSON body, never in the HTTP status.

Run directly::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python examples/http_examples.py

Or import from a test runner::

    from examples.http_examples import HTTP_SCENARIOS, HTTP_EDGE_CASES, run_http_scenario
"""
from __future__ import annotations

from typing import Any

import fpl_server
from fastapi.testclient import TestClient
from fpl_grounded_assistant import STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP

# Minimal bootstrap extension for differential picks HTTP example.
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
# Client factory helpers
# ---------------------------------------------------------------------------

def make_client(bootstrap: dict[str, Any]) -> TestClient:
    """Return a TestClient with *bootstrap* pre-injected.

    Injects the bootstrap before creating the TestClient so the lifespan
    ``if _bootstrap is None`` guard skips the live ``assemble_captain_context()``
    fetch.

    In production, replace with ``requests.Session`` pointed at your server URL.
    """
    fpl_server._init_bootstrap(bootstrap)
    return TestClient(fpl_server.app, raise_server_exceptions=True)


def make_uninitialised_client() -> TestClient:
    """Return a TestClient with the bootstrap cleared — triggers HTTP 503 on /ask.

    Used only for the ``service_not_ready`` scenario.  Call ``make_client()``
    immediately after to restore a valid state for subsequent requests.
    """
    fpl_server._bootstrap = None  # type: ignore[assignment]
    return TestClient(fpl_server.app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

HTTP_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "supported_ok",
        "payload": {"question": "should I captain Haaland"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Captain score for a known player. HTTP 200. "
            "supported=True, outcome='ok' in JSON body."
        ),
    },
    {
        "id": "supported_ambiguous",
        "payload": {"question": "who is Doe"},
        "bootstrap": AMBIGUOUS_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ambiguous",
        "note": (
            "Ambiguous player name. HTTP 200. "
            "supported=True, outcome='ambiguous' — inspect body for detail."
        ),
    },
    {
        "id": "supported_not_found",
        "payload": {"question": "should I captain xyznotaplayer999"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "not_found",
        "note": (
            "Player not found. HTTP 200. "
            "supported=True, outcome='not_found' — inspect body for detail."
        ),
    },
    {
        "id": "supported_missing_arguments",
        "payload": {"question": "top captains this week"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "missing_arguments",
        "note": (
            "Ranking intent without candidates. HTTP 200. "
            "supported=True, outcome='missing_arguments' — inspect body."
        ),
    },
    {
        "id": "unsupported_intent",
        "payload": {"question": "Is Haaland fit to play?"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": False,
        "expected_outcome": "unsupported_intent",
        "note": (
            "Out-of-scope question. HTTP 200 (transport OK). "
            "supported=False, outcome='unsupported_intent' in JSON body. "
            "Domain outcome is in the body, not the HTTP status code."
        ),
    },
    # Phase 5e: comparison exposure
    {
        "id": "comparison_direct",
        "payload": {"question": "compare Haaland and Salah"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Direct player comparison. HTTP 200. "
            "supported=True, outcome='ok'. "
            "final_text includes explanation-enriched recommendation: "
            "winner, margin label, and Advantages clause (Phase 5d)."
        ),
    },
    {
        "id": "comparison_not_found",
        "payload": {"question": "compare Haaland and NoSuchPlayer99"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "not_found",
        "note": (
            "Comparison where second player is not in registry. HTTP 200. "
            "supported=True, outcome='not_found'. "
            "final_text explains the player was not found."
        ),
    },
    # Phase 5j: structured comparison player context in HTTP body
    {
        "id": "comparison_structured",
        "payload": {"question": "compare Haaland and Saka"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Direct comparison exposing structured player context (Phase 5i/5j). "
            "JSON body includes comparison.player_a and comparison.player_b, each with: "
            "web_name, position, captain_score, role_bonus, set_piece_notes. "
            "Haaland: position=FWD, role_bonus=5.0, set_piece_notes=['penalty_taker_1']. "
            "Saka: position=MID, role_bonus=0.5, set_piece_notes=['freekick_taker_2']."
        ),
    },
    # Phase 5o: structured captain score metadata in HTTP body
    {
        "id": "captain_structured",
        "payload": {"question": "should I captain Salah"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Direct captain score query exposing structured captain metadata (Phase 5n/5o). "
            "JSON body includes captain.web_name='Salah', captain.team_short='LIV', "
            "captain.captain_score (≈60.58), captain.tier='safe', "
            "captain.role_bonus=5.0, captain.set_piece_notes=['penalty_taker_1']. "
            "Non-captain turns (e.g. comparison) do not include the captain key. "
            "Shape is identical to CLI debug and session ask captain payloads."
        ),
    },
    # Phase 5q: structured ranked captain candidates in HTTP body
    {
        "id": "captain_ranking_structured",
        "payload": {
            "question": "top captains this week",
            "candidates_list": [
                {"query": "Salah"},
                {"query": "Haaland"},
                {"query": "Saka"},
            ],
        },
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Ranked captain query exposing structured captain_ranking payload (Phase 5p/5q). "
            "JSON body includes captain_ranking as a list of entries each with: "
            "rank, web_name, team_short, captain_score, tier, role_bonus, set_piece_notes. "
            "Salah: rank=1, tier='safe', role_bonus=5.0, set_piece_notes=['penalty_taker_1']. "
            "Haaland: rank=2, tier='upside', set_piece_notes=['penalty_taker_1']. "
            "Saka: rank=3, tier='differential', set_piece_notes=['freekick_taker_2']. "
            "Non-ranking turns have captain_ranking=null in the response body. "
            "Shape is identical to CLI debug and session ask captain_ranking payloads."
        ),
    },
    # Phase 7c: structured transfer metadata in HTTP body
    {
        "id": "transfer_structured",
        "payload": {"question": "should I sell Saka for Salah"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Transfer advice query exposing structured transfer metadata (Phase 7a/7c). "
            "JSON body includes transfer.player_out='Saka', transfer.player_in='Salah', "
            "transfer.recommendation='transfer_in' (Salah > Saka by a large margin), "
            "transfer.score_delta (float), transfer.price_delta (int), "
            "transfer.reasons (list of reason strings). "
            "Non-transfer turns have transfer=null in the response body. "
            "Shape is identical to CLI debug and session ask transfer payloads."
        ),
    },
    # Phase 7c: structured chip metadata in HTTP body
    {
        "id": "chip_structured",
        "payload": {"question": "should I use triple captain this week"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Chip advice query exposing structured chip metadata (Phase 7b/7c). "
            "JSON body includes chip.chip='triple_captain', chip.recommendation "
            "in {conditions_favorable, conditions_marginal, conditions_unfavorable}, "
            "chip.gw (int or null), chip.signal_value (top MID/FWD captain score, float), "
            "chip.signal_label='top captain score'. "
            "Non-chip turns have chip=null in the response body. "
            "Shape is identical to CLI debug and session ask chip payloads."
        ),
    },
    {
        "id": "fixture_run_structured",
        "payload": {"question": "Salah fixtures"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Player fixture run query exposing structured fixture_run metadata (Phase 7h). "
            "JSON body includes fixture_run.web_name, fixture_run.team_short, "
            "fixture_run.position, fixture_run.horizon (int), "
            "fixture_run.current_gameweek (int), and fixture_run.fixtures (list of "
            "{gameweek, opponent_short, is_home, difficulty}). "
            "Non-fixture turns have fixture_run=null in the response body. "
            "Shape is identical to CLI debug and session ask fixture_run payloads."
        ),
    },
    {
        "id": "differential_picks_structured",
        "payload": {"question": "good differentials"},
        "bootstrap": _DIFFERENTIAL_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Differential picks query exposing structured differential metadata (Phase 7g). "
            "JSON body includes differential.ownership_threshold (15.0), "
            "differential.top_n (int), and differential.picks (list of "
            "{rank, web_name, team_short, position, captain_score, ownership, now_cost}). "
            "Players are filtered to status='a' and ownership < 15%. "
            "Ranked by deterministic captain score descending. "
            "Non-differential turns have differential=null in the response body. "
            "Shape is identical to CLI debug and session ask differential payloads."
        ),
    },
    # Phase 8a1: position-aware heuristic — GKP comparison structured payload in HTTP body
    {
        "id": "position_score_gkp_comparison",
        "payload": {"question": "compare Raya and Haaland"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "GKP vs FWD comparison exposing Phase 8a1 position-aware scoring (Phase 8a1). "
            "JSON body includes comparison.player_a (Raya, GKP) and comparison.player_b "
            "(Haaland, FWD), each with: web_name, position, captain_score (canonical Layer 1), "
            "position_score (Layer 2 position-aware heuristic), role_bonus, set_piece_notes. "
            "position_score uses position-specific weight profiles over 7 normalised "
            "components (form, fixture, xgi, minutes, saves, cs, dc). "
            "GKP weights saves and clean_sheet; FWD uses canonical MID weights "
            "(transitional bridge). "
            "Canonical captain_score preserved unchanged for auditability. "
            "Non-comparison turns have comparison=null in the response body. "
            "Shape is identical to CLI debug and session ask comparison payloads."
        ),
    },
    # Phase 8b: venue-aware fixture factor — comparison structured payload in HTTP body
    {
        "id": "venue_aware_comparison_structured",
        "payload": {"question": "compare Salah and Saka"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Phase 8b venue-aware comparison in HTTP response body. "
            "STANDARD_BOOTSTRAP has team_fixtures for GW28. "
            "comparison.player_a (Salah, MID) and comparison.player_b (Saka, MID): "
            "each exposes is_home (True — both are home GW28) and "
            "effective_fdr (float: Salah=3.5, Saka=4.5) in the response JSON. "
            "Layer 2 position_score uses effective_fdr; "
            "Layer 1 captain_score still uses raw int FDR. "
            "comparison_reasons includes venue-tagged FDR phrase: "
            "'easier fixture (FDR 4H vs 5H)'. "
            "Shape is identical to CLI debug and session ask comparison payloads. "
            "Non-comparison turns have comparison=null."
        ),
    },
    # V2 Phase 1d: intent_hint contract examples
    {
        "id": "intent_hint_valid",
        "payload": {"question": "Haaland", "intent_hint": "captain_score", "debug": True},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "Bare name 'Haaland' does not route deterministically; "
            "intent_hint='captain_score' synthesises 'should I captain Haaland' "
            "and routes it via the hint path. "
            "outcome='ok', intent='captain_score'. "
            "debug.classification_source='intent_hint' confirms the hint fired. "
            "V2 Phase 1c/1d — slash-command routing bias."
        ),
    },
    {
        "id": "intent_hint_no_change",
        "payload": {
            "question": "should I captain Salah",
            "intent_hint": "compare_players",
            "debug": True,
        },
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": True,
        "expected_outcome": "ok",
        "note": (
            "'should I captain Salah' routes deterministically to captain_score. "
            "intent_hint='compare_players' is ignored — deterministic router wins. "
            "outcome='ok', intent='captain_score'. "
            "debug.classification_source=null confirms the hint never fired. "
            "Demonstrates the invariant: intent_hint only fires on router miss."
        ),
    },
    {
        "id": "intent_hint_invalid_safe",
        "payload": {"question": "Haaland", "intent_hint": "not_a_valid_intent"},
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 200,
        "expected_supported": False,
        "expected_outcome": "unsupported_intent",
        "note": (
            "Bare name 'Haaland' does not route deterministically; "
            "intent_hint='not_a_valid_intent' is not in INTENT_HINT_ALLOWLIST "
            "so it is silently ignored. No route is found; falls through to "
            "unsupported_intent. outcome='unsupported_intent', supported=False. "
            "Demonstrates safe fallback — invalid hints never cause errors."
        ),
    },
]

HTTP_EDGE_CASES: list[dict[str, Any]] = [
    {
        "id": "malformed_request",
        "payload": {},  # missing required 'question' field
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_status": 422,
        "note": (
            "Missing required 'question' field. HTTP 422 (request validation error). "
            "Use HTTP status 422 to detect malformed payloads."
        ),
    },
    {
        "id": "service_not_ready",
        "payload": {"question": "should I captain Haaland"},
        "bootstrap": None,  # uninitialised — triggers 503
        "expected_status": 503,
        "note": (
            "Bootstrap not initialised at startup. HTTP 503 (service unavailable). "
            "Should not occur in normal operation (lifespan initialises bootstrap)."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_http_scenario(scenario: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run a single HTTP scenario and return ``(status_code, json_body)``.

    Creates a fresh TestClient with the appropriate bootstrap for each call.
    For ``bootstrap=None``, clears the server state to trigger the 503 path,
    then the next ``make_client()`` call will restore a valid bootstrap.

    Parameters
    ----------
    scenario:
        One entry from ``HTTP_SCENARIOS`` or ``HTTP_EDGE_CASES``.

    Returns
    -------
    tuple[int, dict]
        HTTP status code and parsed JSON body (empty dict on parse failure).
    """
    if scenario.get("bootstrap") is None:
        client = make_uninitialised_client()
    else:
        client = make_client(scenario["bootstrap"])

    resp = client.post("/ask", json=scenario["payload"])
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("FPL HTTP Integration Examples\n")

    # Health check
    client = make_client(STANDARD_BOOTSTRAP)
    health = client.get("/health")
    print(f"GET /health → HTTP {health.status_code}  {health.json()}\n")

    # POST /ask scenarios
    print("POST /ask — domain scenarios\n")
    all_pass = True
    for s in HTTP_SCENARIOS + HTTP_EDGE_CASES:
        status, body = run_http_scenario(s)
        ok = status == s["expected_status"]
        label = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        supported = body.get("supported", "—")
        outcome   = body.get("outcome",   "—")
        print(f"[{label}] {s['id']}  HTTP {status}  (expected {s['expected_status']})")
        print(f"       {s['note']}")
        if body:
            print(f"       supported={supported}  outcome={outcome}")
        print()

    print("All scenarios passed." if all_pass else "Some scenarios FAILED.")
