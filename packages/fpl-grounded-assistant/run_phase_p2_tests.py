"""
run_phase_p2_tests.py
=====================
Phase P2.1+P2.2: find_players + get_player_snapshot atomic tools.

Validates that:
- find_players() returns status="ok" with at least 1 match for a known player.
- Every match has the full grounding payload (all 21 required keys present).
- Unicode normalization works (Núñez matches Nunez).
- Case-insensitive matching works.
- No-match query returns status="not_found", match_count=0.
- limit parameter caps results correctly.
- limit>10 is silently capped to 10.
- match_rank ordering: exact < prefix < substring.
- find_players is registered in tool_schema_registry (19 tools after P2.2).
- Status codes map correctly (injured player → "Injured").
- Orchestrator can invoke find_players via ask_orchestrated() with a mock LLM.
- get_player_snapshot() returns status="ok" for unique match (Haaland).
- get_player_snapshot() returns 20 grounding fields (21 minus match_rank).
- get_player_snapshot() returns status="not_found" for unknown names.
- get_player_snapshot() returns status="ambiguous" for multi-match prefix queries.
- get_player_snapshot() registered in TOOL_NAMES (registry = 19 tools).
- Orchestrator can dispatch get_player_snapshot via ask_orchestrated().

Sections
--------
T1  Basic match               -- haaland → status=ok, >=1 match
T2  Full grounding payload    -- all 21 required fields present on every match
T3  Unicode normalization     -- Núñez-style accents stripped for matching
T4  Case-insensitive          -- hAaLaNd matches Haaland
T5  Not found                 -- xx_no_such_player → not_found, 0 matches
T6  Limit cap                 -- limit=2 returns <=2 matches
T7  Limit>10 silent cap       -- limit=99 returns <=10 matches
T8  match_rank ordering       -- exact before prefix before substring
T9  Schema registry           -- 19 tools, find_players+get_player_snapshot included
T10 Status code mapping       -- injured player → "Injured"
T11 Orchestrator integration  -- ask_orchestrated() with mock LLM returns find_players output
U1  Snapshot basic match      -- haaland → status=ok, player.web_name=Haaland
U2  Snapshot payload          -- 20 fields present (21 minus match_rank)
U3  Snapshot not_found        -- unknown name → not_found, non-empty message
U4  Snapshot ambiguous        -- multi-prefix "sa" → ambiguous, candidates with match_rank
U5  Snapshot accent/case      -- Núñez ≡ Nunez
U6  Snapshot candidates cap   -- ambiguous candidates ≤ 5
U7  Snapshot registry         -- get_player_snapshot in TOOL_NAMES (19 tools)
U8  Snapshot schema           -- validate_tool_schema_shape passes
U9  Snapshot orchestrator     -- ask_orchestrated() dispatches get_player_snapshot
U10 Ambiguous query field     -- ambiguous response preserves query for LLM

Run from packages/fpl-grounded-assistant::

    python run_phase_p2_tests.py
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.find_players import find_players
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.tool_schema_registry import (
    list_tool_schemas,
    get_tool_schema,
    TOOL_NAMES,
    validate_tool_schema_shape,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import (
    ask_orchestrated,
    OUTCOME_OK,
    OUTCOME_TOOL_RESULT_ERROR,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


# Grounding payload fields that MUST be present in every match dict (P2 contract)
_REQUIRED_MATCH_FIELDS = [
    # Identity
    "id", "web_name", "team_short", "position",
    # Availability
    "minutes_played_season", "status", "news", "news_added",
    "chance_of_playing_this_round",
    # Form & performance
    "form", "total_points", "points_per_game",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "ict_index",
    # Selection meta
    "now_cost", "selected_by_percent", "transfers_in_event", "transfers_out_event",
    # Match confidence
    "match_rank",
]


# ---------------------------------------------------------------------------
# Extended bootstrap with accented player name for T3
# ---------------------------------------------------------------------------

import copy as _copy

_ACCENTED_BOOTSTRAP = _copy.deepcopy(STANDARD_BOOTSTRAP)
_ACCENTED_BOOTSTRAP["elements"].append({
    "id": 99,
    "first_name": "Luis",
    "second_name": "Núñez",
    "web_name": "Núñez",
    "team": 14,
    "team_code": 1,
    "element_type": 4,
    "status": "a",
    "now_cost": 60,
    "selected_by_percent": "5.0",
    "form": "4.0",
    "expected_goals": "0.30",
    "expected_assists": "0.10",
    "expected_goal_involvements": "0.40",
    "minutes": 900,
    "total_points": 45,
    "points_per_game": "5.0",
    "ict_index": "30.0",
    "transfers_in_event": 1000,
    "transfers_out_event": 500,
})

# ---------------------------------------------------------------------------
# Mock LLM client for orchestrator integration test (T11)
# ---------------------------------------------------------------------------

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockFindPlayersClient:
    """Returns a find_players tool_use call for 'Haaland'."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_fp_001"
            name  = "find_players"
            input = {"name_query": "Haaland", "limit": 3}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


# ---------------------------------------------------------------------------
# Section T1: Basic match
# ---------------------------------------------------------------------------

print("\n=== T1: basic match ===")

_r1 = find_players("haaland", bootstrap=STANDARD_BOOTSTRAP)
ok(_r1["status"] == "ok",        "T1.1: status=ok for known player")
ok(_r1["match_count"] >= 1,      "T1.2: match_count >= 1")
ok(isinstance(_r1["matches"], list) and len(_r1["matches"]) >= 1,
   "T1.3: matches is non-empty list")

# ---------------------------------------------------------------------------
# Section T2: Full grounding payload present on every match
# ---------------------------------------------------------------------------

print("\n=== T2: full grounding payload ===")

_r2 = find_players("haaland", bootstrap=STANDARD_BOOTSTRAP)
_first_match = _r2["matches"][0]

for _field in _REQUIRED_MATCH_FIELDS:
    ok(_field in _first_match, f"T2: field '{_field}' present in match")

ok(len(_REQUIRED_MATCH_FIELDS) == 21, "T2: contract has exactly 21 required fields")

# ---------------------------------------------------------------------------
# Section T3: Unicode normalization (Núñez → Nunez)
# ---------------------------------------------------------------------------

print("\n=== T3: unicode normalization ===")

_r3_accent = find_players("Núñez", bootstrap=_ACCENTED_BOOTSTRAP)
_r3_plain  = find_players("Nunez",  bootstrap=_ACCENTED_BOOTSTRAP)

ok(_r3_accent["status"] == "ok" and _r3_accent["match_count"] >= 1,
   "T3.1: Núñez (accented) matches player")
ok(_r3_plain["status"] == "ok" and _r3_plain["match_count"] >= 1,
   "T3.2: Nunez (plain) matches same player")
ok(_r3_accent["match_count"] == _r3_plain["match_count"],
   "T3.3: accented and plain queries return same match count")

# ---------------------------------------------------------------------------
# Section T4: Case-insensitive matching
# ---------------------------------------------------------------------------

print("\n=== T4: case-insensitive matching ===")

_r4 = find_players("hAaLaNd", bootstrap=STANDARD_BOOTSTRAP)
ok(_r4["status"] == "ok" and _r4["match_count"] >= 1,
   "T4.1: mixed-case hAaLaNd matches Haaland")
_r4_lower = find_players("haaland", bootstrap=STANDARD_BOOTSTRAP)
ok(_r4["match_count"] == _r4_lower["match_count"],
   "T4.2: mixed-case and lower-case return same match count")

# ---------------------------------------------------------------------------
# Section T5: No match → not_found
# ---------------------------------------------------------------------------

print("\n=== T5: not_found ===")

_r5 = find_players("xx_no_such_player_xyz", bootstrap=STANDARD_BOOTSTRAP)
ok(_r5["status"] == "not_found",  "T5.1: unknown query returns not_found")
ok(_r5["match_count"] == 0,       "T5.2: match_count=0")
ok(_r5["matches"] == [],          "T5.3: matches=[]")
ok("query" in _r5,                "T5.4: query field present")

# ---------------------------------------------------------------------------
# Section T6: limit=2 returns at most 2 matches
# ---------------------------------------------------------------------------

print("\n=== T6: limit cap ===")

# Use a query that matches multiple players (broad substring like "a")
_r6 = find_players("a", limit=2, bootstrap=STANDARD_BOOTSTRAP)
ok(len(_r6["matches"]) <= 2, "T6.1: limit=2 returns <=2 matches")
ok(_r6["match_count"] <= 2,  "T6.2: match_count respects limit")

# ---------------------------------------------------------------------------
# Section T7: limit>10 silently capped to 10
# ---------------------------------------------------------------------------

print("\n=== T7: limit>10 silent cap ===")

_r7 = find_players("a", limit=99, bootstrap=STANDARD_BOOTSTRAP)
ok(len(_r7["matches"]) <= 10, "T7.1: limit=99 silently capped — <=10 matches returned")
ok(_r7["match_count"] <= 10,  "T7.2: match_count also capped at 10")

# ---------------------------------------------------------------------------
# Section T8: match_rank ordering (exact < prefix < substring)
# ---------------------------------------------------------------------------

print("\n=== T8: match_rank ordering ===")

# Build a bootstrap with players where we know the rank:
# - "Salah": exact match on web_name (rank 0)
# - "Saka": prefix match on web_name starting with 'sa' (rank 1 for 'sa')
# - "De Bruyne": substring match for 'bruyne' (rank 2)
import copy as _copy2
_rank_bootstrap = _copy2.deepcopy(STANDARD_BOOTSTRAP)

# Query "Salah" → rank 0 (exact on web_name)
# Query "sa" → rank 1 for Salah (prefix), rank 1 for Saka (prefix)
# Let's query "al" → substring in Salah (rank 2) and in Haaland (rank 2)
# Better: use exact name "Salah" against a bootstrap where only Salah, Saka, Raya exist
# and verify Salah is rank 0 (exact match)
_r8_exact = find_players("Salah", bootstrap=STANDARD_BOOTSTRAP)
ok(_r8_exact["status"] == "ok",                     "T8.1: 'Salah' finds a match")
ok(_r8_exact["matches"][0]["match_rank"] == 0,       "T8.2: exact match is rank 0")
ok(_r8_exact["matches"][0]["web_name"] == "Salah",   "T8.3: first match is the exact player")

# Prefix match: "haa" is a prefix of "Haaland" web_name
_r8_prefix = find_players("haa", bootstrap=STANDARD_BOOTSTRAP)
ok(_r8_prefix["status"] == "ok",                    "T8.4: prefix query 'haa' finds Haaland")
ok(_r8_prefix["matches"][0]["match_rank"] == 1,      "T8.5: prefix match is rank 1")

# Substring match: "ruyne" is a substring of "De Bruyne" but not a prefix
_r8_sub = find_players("ruyne", bootstrap=STANDARD_BOOTSTRAP)
ok(_r8_sub["status"] == "ok",                       "T8.6: substring query 'ruyne' finds De Bruyne")
ok(_r8_sub["matches"][0]["match_rank"] == 2,         "T8.7: substring match is rank 2")

# ---------------------------------------------------------------------------
# Section T9: Schema registry (18 tools, find_players registered)
# ---------------------------------------------------------------------------

print("\n=== T9: schema registry ===")

_all_schemas = list_tool_schemas()
ok("find_players" in TOOL_NAMES,             "T9.1: find_players in TOOL_NAMES frozenset")
ok("find_players" in _all_schemas,           "T9.2: find_players in list_tool_schemas()")
ok(len(_all_schemas) == 19,                  "T9.3: registry has exactly 19 tools")

_fp_schema = get_tool_schema("find_players")
ok(_fp_schema is not None,                   "T9.4: get_tool_schema('find_players') returns non-None")
ok(_fp_schema.name == "find_players",        "T9.5: schema.name == 'find_players'")
ok("name_query" in _fp_schema.parameters.get("properties", {}),
   "T9.6: name_query in schema properties")
ok("name_query" in _fp_schema.parameters.get("required", []),
   "T9.7: name_query is required")

# ---------------------------------------------------------------------------
# Section T10: Status code mapping
# ---------------------------------------------------------------------------

print("\n=== T10: status code mapping ===")

# De Bruyne has status="i" (injured) in STANDARD_BOOTSTRAP
_r10 = find_players("De Bruyne", bootstrap=STANDARD_BOOTSTRAP)
ok(_r10["status"] == "ok",                               "T10.1: De Bruyne found")
ok(_r10["matches"][0]["status"] == "Injured",            "T10.2: status 'i' maps to 'Injured'")

# Saka has status="d" (doubtful)
_r10b = find_players("Saka", bootstrap=STANDARD_BOOTSTRAP)
ok(_r10b["status"] == "ok",                              "T10.3: Saka found")
ok(_r10b["matches"][0]["status"] == "Doubtful",          "T10.4: status 'd' maps to 'Doubtful'")

# Haaland has status="a" (available)
_r10c = find_players("Haaland", bootstrap=STANDARD_BOOTSTRAP)
ok(_r10c["status"] == "ok",                              "T10.5: Haaland found")
ok(_r10c["matches"][0]["status"] == "Available",         "T10.6: status 'a' maps to 'Available'")

# ---------------------------------------------------------------------------
# Section T11: Orchestrator integration
# ---------------------------------------------------------------------------

print("\n=== T11: orchestrator integration ===")

_mock_client = _MockFindPlayersClient()

_r11 = ask_orchestrated(
    "find players named Haaland",
    STANDARD_BOOTSTRAP,
    client=_mock_client,
    provider="anthropic",
)

ok(_r11.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "T11.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_r11.tool_chosen == "find_players",
   "T11.2: orchestrator dispatched find_players tool")
ok(isinstance(_r11.tool_output, dict),
   "T11.3: tool_output is a dict")
ok(_r11.tool_output.get("status") in ("ok", "not_found"),
   "T11.4: tool_output.status is ok or not_found")
ok("matches" in _r11.tool_output,
   "T11.5: tool_output contains matches key")

# Clean up env vars
os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)


# ---------------------------------------------------------------------------
# Section U: get_player_snapshot atomic tool (P2.2)
# ---------------------------------------------------------------------------

print("\n=== U1: basic ok match ===")

_u1 = get_player_snapshot("haaland", bootstrap=STANDARD_BOOTSTRAP)
ok(_u1["status"] == "ok",                                  "U1.1: status=ok for known player")
ok("player" in _u1,                                        "U1.2: 'player' key present in ok response")
ok(_u1["player"]["web_name"] == "Haaland",                 "U1.3: player.web_name == 'Haaland'")

print("\n=== U2: full grounding payload (20 fields, no match_rank) ===")

# Single-answer omits match_rank; 21 required fields minus match_rank = 20.
_SNAPSHOT_REQUIRED_FIELDS = [
    f for f in _REQUIRED_MATCH_FIELDS if f != "match_rank"
]
_u2 = get_player_snapshot("Haaland", bootstrap=STANDARD_BOOTSTRAP)
ok(_u2["status"] == "ok",                                  "U2.0: Haaland snapshot ok")
for _field in _SNAPSHOT_REQUIRED_FIELDS:
    ok(_field in _u2["player"], f"U2: field '{_field}' present in player dict")
ok(len(_SNAPSHOT_REQUIRED_FIELDS) == 20,                   "U2: snapshot contract has exactly 20 required fields")
ok("match_rank" not in _u2["player"],                      "U2: match_rank absent from single-answer player")

print("\n=== U3: not_found ===")

_u3 = get_player_snapshot("xx_no_such_player_xyz", bootstrap=STANDARD_BOOTSTRAP)
ok(_u3["status"] == "not_found",                           "U3.1: unknown name returns not_found")
ok(bool(_u3.get("message")),                               "U3.2: not_found has non-empty message")
ok("query" in _u3,                                         "U3.3: not_found has query field")

print("\n=== U4: ambiguous - multiple prefix matches ===")

# "sa" is a prefix of both "Salah" and "Saka" in STANDARD_BOOTSTRAP -> ambiguous
_u4 = get_player_snapshot("sa", bootstrap=STANDARD_BOOTSTRAP)
ok(_u4["status"] == "ambiguous",                           "U4.1: 'sa' prefix matches multiple players: ambiguous")
ok(isinstance(_u4.get("candidates"), list) and len(_u4["candidates"]) > 0,
   "U4.2: ambiguous response has non-empty candidates list")
ok(all("match_rank" in c for c in _u4["candidates"]),      "U4.3: each candidate has match_rank field")
ok("query" in _u4,                                         "U4.4: ambiguous response keeps query field for LLM")
ok(bool(_u4.get("message")),                               "U4.5: ambiguous has non-empty message")

print("\n=== U5: case + accent insensitivity ===")

_u5_accent = get_player_snapshot("Núñez", bootstrap=_ACCENTED_BOOTSTRAP)
_u5_plain  = get_player_snapshot("Nunez",  bootstrap=_ACCENTED_BOOTSTRAP)
ok(_u5_accent["status"] == "ok",                           "U5.1: accented query resolves to ok")
ok(_u5_plain["status"] == "ok",                            "U5.2: Nunez (plain) resolves to ok")
ok(_u5_accent["player"]["web_name"] == _u5_plain["player"]["web_name"],
   "U5.3: accented and plain resolve to same player")

print("\n=== U6: ambiguous candidates <= 5 ===")

# Use a broad substring query that matches many players
_u6 = get_player_snapshot("a", bootstrap=STANDARD_BOOTSTRAP)
ok(_u6["status"] in ("ok", "ambiguous"),                   "U6.1: query 'a' returns ok or ambiguous (not error)")
if _u6["status"] == "ambiguous":
    ok(len(_u6["candidates"]) <= 5,                        "U6.2: candidates capped at 5")
else:
    ok(True,                                               "U6.2: single match - candidates cap not exercised")

print("\n=== U7: registered in TOOL_NAMES (registry grows 18->19) ===")

ok("get_player_snapshot" in TOOL_NAMES,                    "U7.1: get_player_snapshot in TOOL_NAMES frozenset")
_all_schemas_u = list_tool_schemas()
ok("get_player_snapshot" in _all_schemas_u,                "U7.2: get_player_snapshot in list_tool_schemas()")
ok(len(_all_schemas_u) == 19,                              "U7.3: registry has exactly 19 tools")

print("\n=== U8: schema validates ===")

_gps_schema = get_tool_schema("get_player_snapshot")
ok(_gps_schema is not None,                                "U8.1: get_tool_schema('get_player_snapshot') returns non-None")
ok(_gps_schema.name == "get_player_snapshot",              "U8.2: schema.name == 'get_player_snapshot'")
ok("player_name" in _gps_schema.parameters.get("properties", {}),
   "U8.3: player_name in schema properties")
ok("player_name" in _gps_schema.parameters.get("required", []),
   "U8.4: player_name is required")
ok(validate_tool_schema_shape(_gps_schema),                "U8.5: validate_tool_schema_shape passes")

print("\n=== U9: orchestrator dispatch via ask_orchestrated ===")

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockSnapshotClient:
    """Returns a get_player_snapshot tool_use call for 'Haaland'."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_gps_001"
            name  = "get_player_snapshot"
            input = {"player_name": "Haaland"}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


_mock_snap = _MockSnapshotClient()
_u9 = ask_orchestrated(
    "get snapshot for Haaland",
    STANDARD_BOOTSTRAP,
    client=_mock_snap,
    provider="anthropic",
)

ok(_u9.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "U9.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_u9.tool_chosen == "get_player_snapshot",               "U9.2: orchestrator dispatched get_player_snapshot")
ok(isinstance(_u9.tool_output, dict),                      "U9.3: tool_output is a dict")
ok(_u9.tool_output.get("status") in ("ok", "not_found", "ambiguous"),
   "U9.4: tool_output.status is one of the 3 valid statuses")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)

print("\n=== U10: ambiguous response keeps query for LLM ===")

_u10 = get_player_snapshot("sa", bootstrap=STANDARD_BOOTSTRAP)
ok(_u10["status"] == "ambiguous",                          "U10.1: 'sa' still returns ambiguous")
ok("query" in _u10,                                        "U10.2: ambiguous response has query field")
ok(_u10["query"] == "sa",                                  "U10.3: query field contains normalized query")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

_total = _pass + _fail
print(f"\n{'='*50}")
print(f"P2 results: {_pass}/{_total} PASS")
if _fail:
    print(f"  FAILURES: {_fail}")
    sys.exit(1)
else:
    print("  All assertions PASSED.")
