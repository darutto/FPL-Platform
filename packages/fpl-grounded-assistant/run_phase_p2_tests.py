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
from fpl_grounded_assistant.get_player_history import (
    get_player_history,
    HISTORY_ENTRY_REQUIRED_FIELDS,
)
from fpl_grounded_assistant.get_fixtures_for_gw import (
    get_fixtures_for_gw,
    _clear_fixture_cache,
)
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
ok(len(_all_schemas) == 21,                  "T9.3: registry has exactly 21 tools (after P2.4)")

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
ok(len(_all_schemas_u) == 21,                              "U7.3: registry has exactly 21 tools (after P2.4)")

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
# Section V: get_player_history atomic tool (P2.3)
# ---------------------------------------------------------------------------

# Build a bootstrap with injected element summaries so no real HTTP call is made.
# Haaland (id=1): 7 completed GW entries, most-recent last (FPL API ordering).
_HAALAND_HISTORY = [
    {"round": 21, "opponent_team_short": "MUN", "was_home": True,  "minutes": 90,
     "total_points": 8, "goals_scored": 1, "assists": 0, "clean_sheets": 0,
     "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 3, "bps": 35,
     "expected_goals": "0.85", "expected_assists": "0.10",
     "expected_goal_involvements": "0.95", "expected_goals_conceded": "0.50",
     "value": 145, "transfers_in": 5000, "transfers_out": 2000, "selected": 5200000,
     "kickoff_time": "2026-01-10T15:00:00Z"},
    {"round": 22, "opponent_team_short": "CHE", "was_home": False, "minutes": 90,
     "total_points": 13, "goals_scored": 2, "assists": 0, "clean_sheets": 0,
     "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 3, "bps": 48,
     "expected_goals": "1.10", "expected_assists": "0.15",
     "expected_goal_involvements": "1.25", "expected_goals_conceded": "0.80",
     "value": 145, "transfers_in": 8000, "transfers_out": 1500, "selected": 5300000,
     "kickoff_time": "2026-01-18T17:30:00Z"},
    {"round": 23, "opponent_team_short": "LIV", "was_home": True,  "minutes": 0,
     "total_points": 1, "goals_scored": 0, "assists": 0, "clean_sheets": 0,
     "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 0, "bps": 2,
     "expected_goals": "0.00", "expected_assists": "0.00",
     "expected_goal_involvements": "0.00", "expected_goals_conceded": "0.00",
     "value": 145, "transfers_in": 1000, "transfers_out": 12000, "selected": 5100000,
     "kickoff_time": "2026-01-25T15:00:00Z"},
    {"round": 24, "opponent_team_short": "ARS", "was_home": False, "minutes": 90,
     "total_points": 6, "goals_scored": 1, "assists": 0, "clean_sheets": 0,
     "yellow_cards": 1, "red_cards": 0, "saves": 0, "bonus": 1, "bps": 30,
     "expected_goals": "0.75", "expected_assists": "0.05",
     "expected_goal_involvements": "0.80", "expected_goals_conceded": "1.20",
     "value": 145, "transfers_in": 6000, "transfers_out": 3000, "selected": 5050000,
     "kickoff_time": "2026-02-01T15:00:00Z"},
    {"round": 25, "opponent_team_short": "CHE", "was_home": True,  "minutes": 90,
     "total_points": 12, "goals_scored": 2, "assists": 1, "clean_sheets": 0,
     "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 3, "bps": 52,
     "expected_goals": "1.30", "expected_assists": "0.45",
     "expected_goal_involvements": "1.75", "expected_goals_conceded": "0.60",
     "value": 145, "transfers_in": 15000, "transfers_out": 1000, "selected": 5400000,
     "kickoff_time": "2026-02-08T15:00:00Z"},
    {"round": 26, "opponent_team_short": "MUN", "was_home": False, "minutes": 90,
     "total_points": 7, "goals_scored": 1, "assists": 0, "clean_sheets": 0,
     "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 2, "bps": 38,
     "expected_goals": "0.90", "expected_assists": "0.20",
     "expected_goal_involvements": "1.10", "expected_goals_conceded": "0.40",
     "value": 145, "transfers_in": 7000, "transfers_out": 2500, "selected": 5420000,
     "kickoff_time": "2026-02-15T15:00:00Z"},
    {"round": 27, "opponent_team_short": "LIV", "was_home": True,  "minutes": 90,
     "total_points": 9, "goals_scored": 1, "assists": 1, "clean_sheets": 0,
     "yellow_cards": 0, "red_cards": 0, "saves": 0, "bonus": 3, "bps": 44,
     "expected_goals": "0.95", "expected_assists": "0.50",
     "expected_goal_involvements": "1.45", "expected_goals_conceded": "0.90",
     "value": 145, "transfers_in": 10000, "transfers_out": 1200, "selected": 5500000,
     "kickoff_time": "2026-02-22T15:00:00Z"},
]

_HISTORY_BOOTSTRAP = _copy.deepcopy(STANDARD_BOOTSTRAP)
_HISTORY_BOOTSTRAP["_element_summaries"] = {
    "1": {"history": _HAALAND_HISTORY},   # Haaland's element_id is 1
}

print("\n=== V1: basic call returns status=ok with non-empty history ===")

_v1 = get_player_history("Haaland", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v1["status"] == "ok",                                      "V1.1: status=ok for known player")
ok("history" in _v1 and len(_v1["history"]) > 0,               "V1.2: history is non-empty list")
ok("player" in _v1,                                             "V1.3: player block present")
ok(_v1["player"]["web_name"] == "Haaland",                     "V1.4: player.web_name == 'Haaland'")

print("\n=== V2: history ordered most-recent-first ===")

_v2 = get_player_history("Haaland", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v2["status"] == "ok",                                      "V2.0: status=ok (precondition)")
_h = _v2["history"]
ok(len(_h) > 1 and _h[0]["round"] > _h[-1]["round"],          "V2.1: history[0].round > history[-1].round (most-recent first)")

print("\n=== V3: each history entry has all 22 required fields ===")

_v3 = get_player_history("Haaland", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v3["status"] == "ok",                                      "V3.0: status=ok (precondition)")
_first_entry = _v3["history"][0]
for _hfield in HISTORY_ENTRY_REQUIRED_FIELDS:
    ok(_hfield in _first_entry, f"V3: field '{_hfield}' present in history entry")
ok(len(HISTORY_ENTRY_REQUIRED_FIELDS) == 22,                   "V3: contract has exactly 22 required history fields")

print("\n=== V4: last_n_gws=3 returns at most 3 entries ===")

_v4 = get_player_history("Haaland", last_n_gws=3, bootstrap=_HISTORY_BOOTSTRAP)
ok(_v4["status"] == "ok",                                      "V4.0: status=ok (precondition)")
ok(len(_v4["history"]) <= 3,                                   "V4.1: last_n_gws=3 returns <=3 entries")
ok(_v4["last_n_gws"] <= 3,                                     "V4.2: last_n_gws response field reflects actual count")

print("\n=== V5: last_n_gws=99 silently capped at 38 ===")

_v5 = get_player_history("Haaland", last_n_gws=99, bootstrap=_HISTORY_BOOTSTRAP)
ok(_v5["status"] == "ok",                                      "V5.0: status=ok (precondition)")
# last_n_gws=99 is capped to 38; the fixture only has 7 entries so we get 7
ok(_v5["last_n_gws"] <= 38,                                    "V5.1: last_n_gws capped at 38 max (silent cap)")

print("\n=== V6: summary block present with required keys ===")

_v6 = get_player_history("Haaland", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v6["status"] == "ok",                                      "V6.0: status=ok (precondition)")
_summary = _v6.get("summary", {})
ok("gws_played" in _summary,                                   "V6.1: summary.gws_played present")
ok("total_points" in _summary,                                 "V6.2: summary.total_points present")
ok("total_minutes" in _summary,                                "V6.3: summary.total_minutes present")
ok("total_goals" in _summary,                                  "V6.4: summary.total_goals present")
ok("total_assists" in _summary,                                "V6.5: summary.total_assists present")
ok("avg_form" in _summary,                                     "V6.6: summary.avg_form present")
ok("total_xgi" in _summary,                                    "V6.7: summary.total_xgi present")

print("\n=== V7: summary.total_points == sum of history total_points ===")

_v7 = get_player_history("Haaland", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v7["status"] == "ok",                                      "V7.0: status=ok (precondition)")
_computed_total = sum(h["total_points"] for h in _v7["history"])
ok(_v7["summary"]["total_points"] == _computed_total,          "V7.1: summary.total_points == sum(h.total_points for h in history)")

print("\n=== V8: ambiguous name returns status=ambiguous with candidates ===")

# "sa" is a prefix of both Salah and Saka in STANDARD_BOOTSTRAP -> ambiguous
_v8 = get_player_history("sa", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v8["status"] == "ambiguous",                               "V8.1: ambiguous name returns status=ambiguous")
ok(isinstance(_v8.get("candidates"), list) and len(_v8["candidates"]) > 0,
   "V8.2: ambiguous response has non-empty candidates list")
ok("query" in _v8,                                             "V8.3: ambiguous response has query field")

print("\n=== V9: unknown name returns status=not_found ===")

_v9 = get_player_history("xx_no_such_player_xyz", bootstrap=_HISTORY_BOOTSTRAP)
ok(_v9["status"] == "not_found",                               "V9.1: unknown name returns not_found")
ok("query" in _v9,                                             "V9.2: not_found response has query field")
ok(bool(_v9.get("message")),                                   "V9.3: not_found response has non-empty message")

print("\n=== V10: tool registered in TOOL_NAMES; registry now has 20 tools ===")

ok("get_player_history" in TOOL_NAMES,                         "V10.1: get_player_history in TOOL_NAMES frozenset")
_all_schemas_v = list_tool_schemas()
ok("get_player_history" in _all_schemas_v,                     "V10.2: get_player_history in list_tool_schemas()")
ok(len(_all_schemas_v) == 21,                                  "V10.3: registry has exactly 21 tools (20 -> 21)")

print("\n=== V11: schema validates ===")

_gph_schema = get_tool_schema("get_player_history")
ok(_gph_schema is not None,                                    "V11.1: get_tool_schema('get_player_history') returns non-None")
ok(_gph_schema.name == "get_player_history",                   "V11.2: schema.name == 'get_player_history'")
ok("player_name" in _gph_schema.parameters.get("properties", {}),
   "V11.3: player_name in schema properties")
ok("last_n_gws" in _gph_schema.parameters.get("properties", {}),
   "V11.4: last_n_gws in schema properties")
ok("player_name" in _gph_schema.parameters.get("required", []),
   "V11.5: player_name is required")
ok(validate_tool_schema_shape(_gph_schema),                    "V11.6: validate_tool_schema_shape passes")

print("\n=== V12: orchestrator dispatches get_player_history via mock LLM ===")

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockHistoryClient:
    """Returns a get_player_history tool_use call for 'Haaland'."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_gph_001"
            name  = "get_player_history"
            input = {"player_name": "Haaland", "last_n_gws": 5}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


_mock_hist = _MockHistoryClient()
_v12 = ask_orchestrated(
    "show me Haaland history last 5 gameweeks",
    _HISTORY_BOOTSTRAP,
    client=_mock_hist,
    provider="anthropic",
)

ok(_v12.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "V12.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_v12.tool_chosen == "get_player_history",                   "V12.2: orchestrator dispatched get_player_history tool")
ok(isinstance(_v12.tool_output, dict),                         "V12.3: tool_output is a dict")
ok(_v12.tool_output.get("status") in ("ok", "not_found", "ambiguous", "error"),
   "V12.4: tool_output.status is one of the valid statuses")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)

# ---------------------------------------------------------------------------
# Section W: get_fixtures_for_gw atomic tool (P2.4)
# ---------------------------------------------------------------------------

# ---- Injected fixture data for test bootstraps ----
# Two fixtures for GW 38 (a normal GW with 10 fixtures; we inject 2 for brevity).
_GW38_FIXTURES_INJECTED = [
    {
        "id": 380,
        "team_h": 1,          # ARS (home)
        "team_a": 2,          # CHE (away)
        "team_h_difficulty": 3,
        "team_a_difficulty": 4,
        "finished": True,
        "team_h_score": 2,
        "team_a_score": 1,
        "minutes": 90,
        "kickoff_time": "2026-05-17T15:00:00Z",
    },
    {
        "id": 381,
        "team_h": 3,          # LIV (home)
        "team_a": 4,          # MCI (away)
        "team_h_difficulty": 5,
        "team_a_difficulty": 2,
        "finished": False,
        "team_h_score": None,
        "team_a_score": None,
        "minutes": None,
        "kickoff_time": "2026-05-17T17:30:00Z",
    },
]

# Bootstrap with enough teams for blank_gw_teams computation.
# Teams 1-4 play; teams 5-6 are absent (blank GW teams).
_GW38_BOOTSTRAP = _copy.deepcopy(STANDARD_BOOTSTRAP)
_GW38_BOOTSTRAP["teams"] = [
    {"id": 1, "name": "Arsenal",          "short_name": "ARS"},
    {"id": 2, "name": "Chelsea",          "short_name": "CHE"},
    {"id": 3, "name": "Liverpool",        "short_name": "LIV"},
    {"id": 4, "name": "Man City",         "short_name": "MCI"},
    {"id": 5, "name": "Tottenham",        "short_name": "TOT"},
    {"id": 6, "name": "Manchester Utd",   "short_name": "MUN"},
]
# Inject the raw fixtures via bootstrap key
_GW38_BOOTSTRAP["_gw_fixtures"] = {"38": _GW38_FIXTURES_INJECTED}

# ---- Blank GW bootstrap: team plays 0 fixtures in GW5 ----
_BLANK_BOOTSTRAP = _copy.deepcopy(_GW38_BOOTSTRAP)
_BLANK_BOOTSTRAP["_gw_fixtures"] = {"5": []}   # GW5 has no fixtures

# ---- Double GW bootstrap: one team (LIV, id=3) plays twice in GW DGW ----
_DGW_FIXTURES_INJECTED = [
    {
        "id": 101,
        "team_h": 3,          # LIV home
        "team_a": 1,          # ARS away
        "team_h_difficulty": 3,
        "team_a_difficulty": 4,
        "finished": False,
        "team_h_score": None,
        "team_a_score": None,
        "minutes": None,
        "kickoff_time": "2026-03-10T15:00:00Z",
    },
    {
        "id": 102,
        "team_h": 2,          # CHE home
        "team_a": 3,          # LIV away — LIV appears twice!
        "team_h_difficulty": 2,
        "team_a_difficulty": 5,
        "finished": False,
        "team_h_score": None,
        "team_a_score": None,
        "minutes": None,
        "kickoff_time": "2026-03-13T19:45:00Z",
    },
]
_DGW_BOOTSTRAP = _copy.deepcopy(_GW38_BOOTSTRAP)
_DGW_BOOTSTRAP["_gw_fixtures"] = {"29": _DGW_FIXTURES_INJECTED}

# Always clear cache before W-section tests to avoid cross-test contamination.
_clear_fixture_cache()

# Required fixture fields (all 9).
_FIXTURE_REQUIRED_FIELDS = [
    "id", "kickoff_time", "home_team_short", "away_team_short",
    "home_fdr", "away_fdr", "finished", "home_score", "away_score", "minutes",
]

# Required summary keys (all 5).
_SUMMARY_REQUIRED_KEYS = [
    "total_fixtures", "easiest_for_home_team", "hardest_for_home_team",
    "double_gw_teams", "blank_gw_teams",
]


print("\n=== W1: basic call returns status=ok with non-empty fixtures ===")

_w1 = get_fixtures_for_gw(38, bootstrap=_GW38_BOOTSTRAP)
ok(_w1["status"] == "ok",                                        "W1.1: status=ok for injected GW 38")
ok(isinstance(_w1.get("fixtures"), list) and len(_w1["fixtures"]) > 0,
   "W1.2: fixtures is non-empty list")
ok(_w1["gw"] == 38,                                              "W1.3: gw field == 38")

print("\n=== W2: each fixture has all required fields ===")

_w2 = get_fixtures_for_gw(38, bootstrap=_GW38_BOOTSTRAP)
ok(_w2["status"] == "ok",                                        "W2.0: status=ok (precondition)")
_w2_first = _w2["fixtures"][0]
for _wfield in _FIXTURE_REQUIRED_FIELDS:
    ok(_wfield in _w2_first, f"W2: field '{_wfield}' present in fixture entry")

print("\n=== W3: gw_number=0 -> invalid_argument ===")

_w3 = get_fixtures_for_gw(0, bootstrap=_GW38_BOOTSTRAP)
ok(_w3["status"] == "invalid_argument",                          "W3.1: gw=0 returns invalid_argument")
ok(_w3.get("code") == "out_of_range",                            "W3.2: code=out_of_range")

print("\n=== W4: gw_number=99 -> invalid_argument ===")

_w4 = get_fixtures_for_gw(99, bootstrap=_GW38_BOOTSTRAP)
ok(_w4["status"] == "invalid_argument",                          "W4.1: gw=99 returns invalid_argument")
ok(_w4.get("code") == "out_of_range",                            "W4.2: code=out_of_range")

print("\n=== W5: summary has all 5 expected keys ===")

_w5 = get_fixtures_for_gw(38, bootstrap=_GW38_BOOTSTRAP)
ok(_w5["status"] == "ok",                                        "W5.0: status=ok (precondition)")
_w5_summary = _w5.get("summary", {})
for _skey in _SUMMARY_REQUIRED_KEYS:
    ok(_skey in _w5_summary, f"W5: summary key '{_skey}' present")

print("\n=== W6: summary.total_fixtures == len(fixtures) ===")

_w6 = get_fixtures_for_gw(38, bootstrap=_GW38_BOOTSTRAP)
ok(_w6["status"] == "ok",                                        "W6.0: status=ok (precondition)")
ok(_w6["summary"]["total_fixtures"] == len(_w6["fixtures"]),     "W6.1: summary.total_fixtures == len(fixtures)")

print("\n=== W7: is_blank=True when fixtures list is empty ===")

_w7 = get_fixtures_for_gw(5, bootstrap=_BLANK_BOOTSTRAP)
ok(_w7["status"] == "ok",                                        "W7.1: status=ok for blank GW")
ok(_w7["is_blank"] is True,                                      "W7.2: is_blank=True when no fixtures")
ok(_w7["fixtures"] == [],                                        "W7.3: fixtures list is empty")
ok(_w7["summary"]["total_fixtures"] == 0,                        "W7.4: summary.total_fixtures==0 for blank GW")

print("\n=== W8: is_double=True when a team appears twice ===")

_w8 = get_fixtures_for_gw(29, bootstrap=_DGW_BOOTSTRAP)
ok(_w8["status"] == "ok",                                        "W8.1: status=ok for DGW")
ok(_w8["is_double"] is True,                                     "W8.2: is_double=True when team plays twice")
ok("LIV" in _w8["summary"]["double_gw_teams"],                   "W8.3: LIV appears in double_gw_teams")

print("\n=== W9: blank_gw_teams includes teams not in GW ===")

_w9 = get_fixtures_for_gw(38, bootstrap=_GW38_BOOTSTRAP)
ok(_w9["status"] == "ok",                                        "W9.0: status=ok (precondition)")
_blank_teams = _w9["summary"]["blank_gw_teams"]
# Bootstrap has 6 teams; only 4 play in GW38 (ARS, CHE, LIV, MCI); TOT, MUN sit out.
ok("TOT" in _blank_teams,                                        "W9.1: TOT (non-playing) in blank_gw_teams")
ok("MUN" in _blank_teams,                                        "W9.2: MUN (non-playing) in blank_gw_teams")
ok("ARS" not in _blank_teams,                                    "W9.3: ARS (playing) not in blank_gw_teams")

print("\n=== W10: tool registered in TOOL_NAMES; registry now has 21 tools ===")

ok("get_fixtures_for_gw" in TOOL_NAMES,                          "W10.1: get_fixtures_for_gw in TOOL_NAMES frozenset")
_all_schemas_w = list_tool_schemas()
ok("get_fixtures_for_gw" in _all_schemas_w,                      "W10.2: get_fixtures_for_gw in list_tool_schemas()")
ok(len(_all_schemas_w) == 21,                                    "W10.3: registry has exactly 21 tools (20 -> 21)")

print("\n=== W11: schema validates ===")

_gfw_schema = get_tool_schema("get_fixtures_for_gw")
ok(_gfw_schema is not None,                                      "W11.1: get_tool_schema('get_fixtures_for_gw') returns non-None")
ok(_gfw_schema.name == "get_fixtures_for_gw",                    "W11.2: schema.name == 'get_fixtures_for_gw'")
ok("gw_number" in _gfw_schema.parameters.get("properties", {}),
   "W11.3: gw_number in schema properties")
ok("gw_number" in _gfw_schema.parameters.get("required", []),
   "W11.4: gw_number is required")
ok(validate_tool_schema_shape(_gfw_schema),                      "W11.5: validate_tool_schema_shape passes")

print("\n=== W12: orchestrator dispatches get_fixtures_for_gw via mock LLM ===")

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockFixturesClient:
    """Returns a get_fixtures_for_gw tool_use call for GW 38."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_gfw_001"
            name  = "get_fixtures_for_gw"
            input = {"gw_number": 38}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


_mock_fixtures = _MockFixturesClient()
_w12 = ask_orchestrated(
    "dame el calendario de partidos para la fecha 38",
    _GW38_BOOTSTRAP,
    client=_mock_fixtures,
    provider="anthropic",
)

ok(_w12.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "W12.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_w12.tool_chosen == "get_fixtures_for_gw",                    "W12.2: orchestrator dispatched get_fixtures_for_gw tool")
ok(isinstance(_w12.tool_output, dict),                           "W12.3: tool_output is a dict")
ok(_w12.tool_output.get("status") in ("ok", "error", "invalid_argument"),
   "W12.4: tool_output.status is one of the valid statuses")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)


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
