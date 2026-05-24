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
- Status codes map correctly (injured player -> "Injured").
- Orchestrator can invoke find_players via ask_orchestrated() with a mock LLM.
- get_player_snapshot() returns status="ok" for unique match (Haaland).
- get_player_snapshot() returns 20 grounding fields (21 minus match_rank).
- get_player_snapshot() returns status="not_found" for unknown names.
- get_player_snapshot() returns status="ambiguous" for multi-match prefix queries.
- get_player_snapshot() registered in TOOL_NAMES (registry = 19 tools).
- Orchestrator can dispatch get_player_snapshot via ask_orchestrated().

Sections
--------
T1  Basic match               -- haaland -> status=ok, >=1 match
T2  Full grounding payload    -- all 21 required fields present on every match
T3  Unicode normalization     -- Núñez-style accents stripped for matching
T4  Case-insensitive          -- hAaLaNd matches Haaland
T5  Not found                 -- xx_no_such_player -> not_found, 0 matches
T6  Limit cap                 -- limit=2 returns <=2 matches
T7  Limit>10 silent cap       -- limit=99 returns <=10 matches
T8  match_rank ordering       -- exact before prefix before substring
T9  Schema registry           -- 19 tools, find_players+get_player_snapshot included
T10 Status code mapping       -- injured player -> "Injured"
T11 Orchestrator integration  -- ask_orchestrated() with mock LLM returns find_players output
U1  Snapshot basic match      -- haaland -> status=ok, player.web_name=Haaland
U2  Snapshot payload          -- 20 fields present (21 minus match_rank)
U3  Snapshot not_found        -- unknown name -> not_found, non-empty message
U4  Snapshot ambiguous        -- multi-prefix "sa" -> ambiguous, candidates with match_rank
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
from fpl_grounded_assistant.get_gameweek_context import (
    get_gameweek_context,
    _clear_context_cache,
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
# Section T3: Unicode normalization (Núñez -> Nunez)
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
# Section T5: No match -> not_found
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

# Query "Salah" -> rank 0 (exact on web_name)
# Query "sa" -> rank 1 for Salah (prefix), rank 1 for Saka (prefix)
# Let's query "al" -> substring in Salah (rank 2) and in Haaland (rank 2)
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
ok(len(_all_schemas) == 25,                  "T9.3: registry has exactly 25 tools (after P2.8)")

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
ok(len(_all_schemas_u) == 25,                              "U7.3: registry has exactly 25 tools (after P2.8)")

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
ok(len(_all_schemas_v) == 25,                                  "V10.3: registry has exactly 25 tools (after P2.8)")

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
ok(len(_all_schemas_w) == 25,                                    "W10.3: registry has exactly 25 tools (after P2.8)")

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
# Section X: get_gameweek_context atomic tool (P2.5)
# ---------------------------------------------------------------------------

# ---- Build a minimal event list bootstrap for testing ----

_clear_context_cache()

# Normal mid-season bootstrap: GW27 current (in progress), GW28 next.
_GW_EVENTS = [
    {"id": i, "name": f"Gameweek {i}", "deadline_time": f"2026-01-{i:02d}T11:30:00Z",
     "finished": i < 27, "is_current": i == 27, "is_next": i == 28, "is_previous": i == 26}
    for i in range(1, 39)
]

_CTX_BOOTSTRAP = _copy.deepcopy(STANDARD_BOOTSTRAP)
_CTX_BOOTSTRAP["events"] = _GW_EVENTS
# Reuse _GW38_BOOTSTRAP teams (id 1-6, ARS CHE LIV MCI TOT MUN)
_CTX_BOOTSTRAP["teams"] = [
    {"id": 1, "name": "Arsenal",          "short_name": "ARS"},
    {"id": 2, "name": "Chelsea",          "short_name": "CHE"},
    {"id": 3, "name": "Liverpool",        "short_name": "LIV"},
    {"id": 4, "name": "Man City",         "short_name": "MCI"},
    {"id": 5, "name": "Tottenham",        "short_name": "TOT"},
    {"id": 6, "name": "Manchester Utd",   "short_name": "MUN"},
]

# Inject blank fixtures for GW28 (TOT + MUN missing -> blank)
# and double fixtures for GW29 (LIV appears twice -> double).
_CTX_BLANK_FIXTURES_GW28 = [
    {
        "id": 2801, "team_h": 1, "team_a": 2,
        "team_h_difficulty": 3, "team_a_difficulty": 4,
        "finished": False, "team_h_score": None, "team_a_score": None,
        "minutes": None, "kickoff_time": "2026-02-01T15:00:00Z",
    },
    {
        "id": 2802, "team_h": 3, "team_a": 4,
        "team_h_difficulty": 2, "team_a_difficulty": 3,
        "finished": False, "team_h_score": None, "team_a_score": None,
        "minutes": None, "kickoff_time": "2026-02-01T17:30:00Z",
    },
    # TOT (id=5) and MUN (id=6) don't appear -> blank teams.
]

_CTX_DGW_FIXTURES_GW29 = [
    {
        "id": 2901, "team_h": 3, "team_a": 1,
        "team_h_difficulty": 3, "team_a_difficulty": 4,
        "finished": False, "team_h_score": None, "team_a_score": None,
        "minutes": None, "kickoff_time": "2026-02-08T15:00:00Z",
    },
    {
        "id": 2902, "team_h": 2, "team_a": 3,  # LIV (id=3) appears twice
        "team_h_difficulty": 2, "team_a_difficulty": 5,
        "finished": False, "team_h_score": None, "team_a_score": None,
        "minutes": None, "kickoff_time": "2026-02-11T19:45:00Z",
    },
]

# Normal GW fixtures for GW30-32 (all 6 teams play exactly once)
def _normal_gw_fixtures(gw: int) -> list:
    return [
        {"id": gw * 100 + 1, "team_h": 1, "team_a": 2,
         "team_h_difficulty": 3, "team_a_difficulty": 3,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": f"2026-02-{gw:02d}T15:00:00Z"},
        {"id": gw * 100 + 2, "team_h": 3, "team_a": 4,
         "team_h_difficulty": 2, "team_a_difficulty": 4,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": f"2026-02-{gw:02d}T17:30:00Z"},
        {"id": gw * 100 + 3, "team_h": 5, "team_a": 6,
         "team_h_difficulty": 3, "team_a_difficulty": 3,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": f"2026-02-{gw:02d}T20:00:00Z"},
    ]

# Fixture override map for X8/X9 (inject alert data for GW28-32)
_X_FIXTURES_OVERRIDE = {
    28: _CTX_BLANK_FIXTURES_GW28,
    29: _CTX_DGW_FIXTURES_GW29,
    30: _normal_gw_fixtures(30),
    31: _normal_gw_fixtures(31),
    32: _normal_gw_fixtures(32),
}

print("\n=== X1: basic call returns status=ok with all top-level keys ===")

_clear_context_cache()
_x1 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
_X1_REQUIRED_KEYS = [
    "status", "current_gw", "next_gw", "current_gw_deadline", "next_gw_deadline",
    "season_total_gws", "is_season_over", "is_pre_season", "current_gw_status",
    "blank_gw_alerts", "double_gw_alerts",
]
ok(_x1["status"] == "ok",                             "X1.1: status=ok")
for _xk in _X1_REQUIRED_KEYS:
    ok(_xk in _x1,                                    f"X1.2: key '{_xk}' present in response")

print("\n=== X2: current_gw is an int ===")

_x2 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
ok(isinstance(_x2["current_gw"], int),                 "X2.1: current_gw is int")
ok(_x2["current_gw"] == 27,                            "X2.2: current_gw == 27 (is_current=True in events)")

print("\n=== X3: next_gw is an int ===")

_clear_context_cache()
_x3 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
ok(_x3["next_gw"] is None or isinstance(_x3["next_gw"], int),
   "X3.1: next_gw is int or None")
ok(_x3["next_gw"] == 28,                               "X3.2: next_gw == 28 (is_next=True in events)")

print("\n=== X4: current_gw_status is one of {pending, in_progress, finished} ===")

_clear_context_cache()
_x4 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
ok(_x4["current_gw_status"] in {"pending", "in_progress", "finished"},
   "X4.1: current_gw_status is a valid status string")
ok(_x4["current_gw_status"] == "in_progress",          "X4.2: GW27 (is_current + not finished) = in_progress")

print("\n=== X5: is_season_over and is_pre_season are bools ===")

_clear_context_cache()
_x5 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
ok(isinstance(_x5["is_season_over"], bool),            "X5.1: is_season_over is bool")
ok(isinstance(_x5["is_pre_season"], bool),             "X5.2: is_pre_season is bool")
ok(_x5["is_season_over"] is False,                     "X5.3: mid-season, is_season_over=False")
ok(_x5["is_pre_season"] is False,                      "X5.4: GW27 in progress, is_pre_season=False")

print("\n=== X6: blank_gw_alerts is a list ===")

_clear_context_cache()
_x6 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
ok(isinstance(_x6["blank_gw_alerts"], list),           "X6.1: blank_gw_alerts is a list")

print("\n=== X7: double_gw_alerts is a list ===")

_clear_context_cache()
_x7 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
ok(isinstance(_x7["double_gw_alerts"], list),          "X7.1: double_gw_alerts is a list")

print("\n=== X8: blank GW injection, blank_gw_alerts contains TOT + MUN for GW28 ===")

_clear_context_cache()
_x8 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
_x8_blank_gws = [a["gw"] for a in _x8["blank_gw_alerts"]]
ok(28 in _x8_blank_gws,                                "X8.1: GW28 appears in blank_gw_alerts")
_x8_gw28 = next((a for a in _x8["blank_gw_alerts"] if a["gw"] == 28), None)
ok(_x8_gw28 is not None,                               "X8.2: GW28 alert dict found")
ok("TOT" in _x8_gw28["blank_teams"],                   "X8.3: TOT in blank_teams for GW28")
ok("MUN" in _x8_gw28["blank_teams"],                   "X8.4: MUN in blank_teams for GW28")
ok("ARS" not in _x8_gw28["blank_teams"],               "X8.5: ARS (playing) not in blank_teams for GW28")
ok(_x8_gw28["count"] == 2,                             "X8.6: count=2 (TOT + MUN blank in GW28)")

print("\n=== X9: double GW injection, double_gw_alerts contains LIV for GW29 ===")

_clear_context_cache()
_x9 = get_gameweek_context(bootstrap=_CTX_BOOTSTRAP, fixtures=_X_FIXTURES_OVERRIDE)
_x9_double_gws = [a["gw"] for a in _x9["double_gw_alerts"]]
ok(29 in _x9_double_gws,                               "X9.1: GW29 appears in double_gw_alerts")
_x9_gw29 = next((a for a in _x9["double_gw_alerts"] if a["gw"] == 29), None)
ok(_x9_gw29 is not None,                               "X9.2: GW29 alert dict found")
ok("LIV" in _x9_gw29["double_teams"],                  "X9.3: LIV in double_teams for GW29")
ok(_x9_gw29["count"] == 1,                             "X9.4: count=1 (only LIV doubles in GW29)")

print("\n=== X10: tool registered in TOOL_NAMES; registry now has 22 tools ===")

ok("get_gameweek_context" in TOOL_NAMES,               "X10.1: get_gameweek_context in TOOL_NAMES frozenset")
_all_schemas_x = list_tool_schemas()
ok("get_gameweek_context" in _all_schemas_x,           "X10.2: get_gameweek_context in list_tool_schemas()")
ok(len(_all_schemas_x) == 25,                          "X10.3: registry has exactly 25 tools (after P2.8)")

print("\n=== X11: schema validates ===")

_gc_schema = get_tool_schema("get_gameweek_context")
ok(_gc_schema is not None,                             "X11.1: get_tool_schema('get_gameweek_context') returns non-None")
ok(_gc_schema.name == "get_gameweek_context",          "X11.2: schema.name == 'get_gameweek_context'")
ok(_gc_schema.parameters.get("properties") == {},      "X11.3: schema.parameters.properties == {} (no-arg tool)")
ok(_gc_schema.parameters.get("required") == [],        "X11.4: schema.parameters.required == []")
ok(validate_tool_schema_shape(_gc_schema),             "X11.5: validate_tool_schema_shape passes")

print("\n=== X12: orchestrator dispatches get_gameweek_context via mock LLM ===")

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockGWContextClient:
    """Returns a get_gameweek_context tool_use call with no args."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_gwc_001"
            name  = "get_gameweek_context"
            input = {}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


_mock_gwc = _MockGWContextClient()
_x12 = ask_orchestrated(
    "qué jornada es la que viene",
    _CTX_BOOTSTRAP,
    client=_mock_gwc,
    provider="anthropic",
)

ok(_x12.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "X12.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_x12.tool_chosen == "get_gameweek_context",         "X12.2: orchestrator dispatched get_gameweek_context tool")
ok(isinstance(_x12.tool_output, dict),                 "X12.3: tool_output is a dict")
ok(_x12.tool_output.get("status") in ("ok", "error"), "X12.4: tool_output.status is ok or error")
ok("current_gw" in _x12.tool_output or "code" in _x12.tool_output,
   "X12.5: tool_output has current_gw (ok) or code (error)")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)


# ---------------------------------------------------------------------------
# Section Y: get_team_snapshot atomic tool (P2.6)
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.get_team_snapshot import (
    get_team_snapshot,
    _clear_snapshot_cache,
)

# ---- Minimal bootstrap for team-snapshot tests ----
# Teams: WOL (id=40), MUN (id=11), MCI (id=13), plus ARS+LIV for opponents.
# WOL players: 6 players (so we can test top_n_players cap).
# Events: GW27 current (finished), GW28 next.
# _gw_fixtures: GW28 and GW29 both have WOL fixtures.

_WOL_BOOTSTRAP: dict = _copy.deepcopy(STANDARD_BOOTSTRAP)
_WOL_BOOTSTRAP["teams"] = [
    # FPL common name "Wolves" so substring "wolves" matches exact on name after normalize
    {"id": 40, "name": "Wolves",          "short_name": "WOL", "code": 39, "strength": 3,
     "strength_overall_home": 1150, "strength_overall_away": 1100},
    {"id": 11, "name": "Manchester Utd",  "short_name": "MUN", "code": 12, "strength": 3},
    {"id": 13, "name": "Manchester City", "short_name": "MCI", "code": 43, "strength": 5},
    {"id": 1,  "name": "Arsenal",         "short_name": "ARS", "code": 3,  "strength": 4},
    {"id": 14, "name": "Liverpool",       "short_name": "LIV", "code": 1,  "strength": 5},
]
_WOL_BOOTSTRAP["elements"] = [
    # WOL players (team=40): 6 players with different total_points and form
    {"id": 101, "first_name": "Rui",     "second_name": "Patricio",  "web_name": "Patricio",
     "team": 40, "team_code": 39, "element_type": 1, "status": "a",
     "now_cost": 45, "selected_by_percent": "5.0", "form": "4.0",
     "expected_goals": "0.00", "expected_assists": "0.00",
     "expected_goal_involvements": "0.00", "minutes": 2250,
     "total_points": 70, "points_per_game": "4.0", "ict_index": "20.0",
     "transfers_in_event": 100, "transfers_out_event": 50},
    {"id": 102, "first_name": "Max",     "second_name": "Kilman",    "web_name": "Kilman",
     "team": 40, "team_code": 39, "element_type": 2, "status": "a",
     "now_cost": 50, "selected_by_percent": "8.0", "form": "5.0",
     "expected_goals": "0.05", "expected_assists": "0.10",
     "expected_goal_involvements": "0.15", "minutes": 2160,
     "total_points": 85, "points_per_game": "5.0", "ict_index": "30.0",
     "transfers_in_event": 200, "transfers_out_event": 80},
    {"id": 103, "first_name": "Joao",    "second_name": "Gomes",     "web_name": "J.Gomes",
     "team": 40, "team_code": 39, "element_type": 3, "status": "a",
     "now_cost": 55, "selected_by_percent": "10.0", "form": "6.0",
     "expected_goals": "0.15", "expected_assists": "0.25",
     "expected_goal_involvements": "0.40", "minutes": 1980,
     "total_points": 90, "points_per_game": "5.5", "ict_index": "40.0",
     "transfers_in_event": 500, "transfers_out_event": 100},
    {"id": 104, "first_name": "Pedro",   "second_name": "Neto",      "web_name": "P.Neto",
     "team": 40, "team_code": 39, "element_type": 3, "status": "a",
     "now_cost": 60, "selected_by_percent": "12.0", "form": "7.0",
     "expected_goals": "0.30", "expected_assists": "0.35",
     "expected_goal_involvements": "0.65", "minutes": 1800,
     "total_points": 95, "points_per_game": "5.8", "ict_index": "50.0",
     "transfers_in_event": 700, "transfers_out_event": 120},
    {"id": 105, "first_name": "Hwang",   "second_name": "Hee-chan",  "web_name": "Hwang",
     "team": 40, "team_code": 39, "element_type": 4, "status": "a",
     "now_cost": 65, "selected_by_percent": "15.0", "form": "8.0",
     "expected_goals": "0.45", "expected_assists": "0.20",
     "expected_goal_involvements": "0.65", "minutes": 1620,
     "total_points": 110, "points_per_game": "6.5", "ict_index": "65.0",
     "transfers_in_event": 1200, "transfers_out_event": 200},
    {"id": 106, "first_name": "Matheus", "second_name": "Cunha",     "web_name": "Cunha",
     "team": 40, "team_code": 39, "element_type": 4, "status": "a",
     "now_cost": 75, "selected_by_percent": "18.0", "form": "9.0",
     "expected_goals": "0.60", "expected_assists": "0.30",
     "expected_goal_involvements": "0.90", "minutes": 1800,
     "total_points": 130, "points_per_game": "7.0", "ict_index": "80.0",
     "transfers_in_event": 2000, "transfers_out_event": 300},
    # ARS player (team=1): for completeness
    {"id": 3,  "first_name": "Bukayo",  "second_name": "Saka",
     "web_name": "Saka", "team": 1, "team_code": 3, "element_type": 3,
     "status": "a", "now_cost": 100, "selected_by_percent": "35.0",
     "form": "5.5", "expected_goals": "0.45", "expected_assists": "0.40",
     "expected_goal_involvements": "0.85", "minutes": 900,
     "total_points": 75, "points_per_game": "5.0", "ict_index": "45.0",
     "transfers_in_event": 300, "transfers_out_event": 100},
]
_WOL_BOOTSTRAP["events"] = [
    {"id": 27, "name": "Gameweek 27", "deadline_time": "2026-02-21T11:30:00Z",
     "finished": True,  "is_current": False, "is_next": False, "is_previous": True},
    {"id": 28, "name": "Gameweek 28", "deadline_time": "2026-02-28T11:30:00Z",
     "finished": False, "is_current": True,  "is_next": False, "is_previous": False},
    {"id": 29, "name": "Gameweek 29", "deadline_time": "2026-03-07T11:30:00Z",
     "finished": False, "is_current": False, "is_next": True,  "is_previous": False},
    {"id": 30, "name": "Gameweek 30", "deadline_time": "2026-03-14T11:30:00Z",
     "finished": False, "is_current": False, "is_next": False, "is_previous": False},
    {"id": 31, "name": "Gameweek 31", "deadline_time": "2026-03-21T11:30:00Z",
     "finished": False, "is_current": False, "is_next": False, "is_previous": False},
    {"id": 32, "name": "Gameweek 32", "deadline_time": "2026-03-28T11:30:00Z",
     "finished": False, "is_current": False, "is_next": False, "is_previous": False},
    {"id": 38, "name": "Gameweek 38", "deadline_time": "2026-05-17T11:30:00Z",
     "finished": False, "is_current": False, "is_next": False, "is_previous": False},
]
# Inject WOL fixtures for GW29–GW33 (current GW=28 so we start from 29)
_WOL_BOOTSTRAP["_gw_fixtures"] = {
    "29": [
        {"id": 2901, "team_h": 40, "team_a": 1,
         "team_h_difficulty": 4, "team_a_difficulty": 3,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": "2026-03-01T15:00:00Z"},
    ],
    "30": [
        {"id": 3001, "team_h": 14, "team_a": 40,
         "team_h_difficulty": 2, "team_a_difficulty": 5,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": "2026-03-08T15:00:00Z"},
    ],
    "31": [
        {"id": 3101, "team_h": 40, "team_a": 11,
         "team_h_difficulty": 2, "team_a_difficulty": 3,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": "2026-03-15T15:00:00Z"},
    ],
    "32": [
        {"id": 3201, "team_h": 13, "team_a": 40,
         "team_h_difficulty": 3, "team_a_difficulty": 5,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": "2026-03-22T15:00:00Z"},
    ],
    "33": [
        {"id": 3301, "team_h": 40, "team_a": 14,
         "team_h_difficulty": 5, "team_a_difficulty": 2,
         "finished": False, "team_h_score": None, "team_a_score": None,
         "minutes": None, "kickoff_time": "2026-03-29T15:00:00Z"},
    ],
}

# Required fixture fields for the upcoming_fixtures list
_UPCOMING_FIXTURE_REQUIRED_FIELDS = [
    "gw", "opponent_short", "opponent_name", "is_home", "fdr", "kickoff_time",
]

# Required summary keys
_SNAPSHOT_SUMMARY_KEYS = [
    "avg_fdr_next_5", "is_easy_run", "is_hard_run",
    "top_scorer_web_name", "top_form_web_name",
]

_clear_snapshot_cache()

print("\n=== Y1: get_team_snapshot('wolves') -> status=ok, team.short_name=='WOL' ===")

_y1 = get_team_snapshot("wolves", bootstrap=_WOL_BOOTSTRAP)
ok(_y1["status"] == "ok",                                       "Y1.1: status=ok for 'wolves'")
ok("team" in _y1,                                               "Y1.2: 'team' key present in ok response")
ok(_y1["team"]["short_name"] == "WOL",                          "Y1.3: team.short_name=='WOL'")
ok(_y1["team"]["name"] == "Wolves",                             "Y1.4: team.name=='Wolves'")

print("\n=== Y2: top_players has 5 entries (default), each with full 20-field grounding payload ===")

_y2 = _y1
ok("top_players" in _y2 and isinstance(_y2["top_players"], list),
   "Y2.1: top_players is a list")
ok(len(_y2["top_players"]) == 5,                                "Y2.2: top_players has 5 entries by default")
_SNAPSHOT_REQUIRED_FIELDS_NO_RANK = [f for f in _REQUIRED_MATCH_FIELDS if f != "match_rank"]
for _yfield in _SNAPSHOT_REQUIRED_FIELDS_NO_RANK:
    ok(_yfield in _y2["top_players"][0], f"Y2: field '{_yfield}' present in top_player entry")

print("\n=== Y3: top_players sorted by total_points desc ===")

_y3 = _y1
_tp_pts = [p["total_points"] for p in _y3["top_players"]]
ok(_tp_pts == sorted(_tp_pts, reverse=True),                    "Y3.1: top_players sorted by total_points desc")
ok(_y3["top_players"][0]["web_name"] == "Cunha",                "Y3.2: top player (130 pts) is Cunha")

print("\n=== Y4: upcoming_fixtures has 5 entries (default), each with required fields ===")

_y4 = _y1
ok("upcoming_fixtures" in _y4 and isinstance(_y4["upcoming_fixtures"], list),
   "Y4.1: upcoming_fixtures is a list")
ok(len(_y4["upcoming_fixtures"]) == 5,                          "Y4.2: upcoming_fixtures has 5 entries by default")
for _ufield in _UPCOMING_FIXTURE_REQUIRED_FIELDS:
    ok(_ufield in _y4["upcoming_fixtures"][0], f"Y4: field '{_ufield}' present in fixture entry")

print("\n=== Y5: summary has all 5 expected keys ===")

_y5 = _y1
ok("summary" in _y5,                                            "Y5.1: summary key present")
for _skey in _SNAPSHOT_SUMMARY_KEYS:
    ok(_skey in _y5["summary"], f"Y5: summary key '{_skey}' present")

print("\n=== Y6: summary.avg_fdr_next_5 matches mean of first 5 FDRs ===")

_y6 = _y1
_fdrs = [f["fdr"] for f in _y6["upcoming_fixtures"][:5]]
_expected_avg = round(sum(_fdrs) / len(_fdrs), 2) if _fdrs else 0.0
ok(abs(_y6["summary"]["avg_fdr_next_5"] - _expected_avg) < 0.01,
   f"Y6.1: avg_fdr_next_5={_y6['summary']['avg_fdr_next_5']} matches computed mean={_expected_avg}")

print("\n=== Y7: get_team_snapshot('WOL') (exact short) returns same result as 'wolves' ===")

_clear_snapshot_cache()
_y7 = get_team_snapshot("WOL", bootstrap=_WOL_BOOTSTRAP)
ok(_y7["status"] == "ok",                                       "Y7.1: 'WOL' exact short code -> status=ok")
ok(_y7["team"]["short_name"] == "WOL",                          "Y7.2: team.short_name=='WOL' for 'WOL' query")
ok(_y7["team"]["id"] == _y1["team"]["id"],                      "Y7.3: same team.id as 'wolves' query")

print("\n=== Y8: 'manchester' -> ambiguous (MUN + MCI) ===")

_clear_snapshot_cache()
_y8 = get_team_snapshot("manchester", bootstrap=_WOL_BOOTSTRAP)
ok(_y8["status"] == "ambiguous",                                "Y8.1: 'manchester' -> ambiguous")
ok("candidates" in _y8 and isinstance(_y8["candidates"], list), "Y8.2: candidates list present")
_y8_shorts = [c["short_name"] for c in _y8["candidates"]]
ok("MUN" in _y8_shorts,                                         "Y8.3: MUN in ambiguous candidates")
ok("MCI" in _y8_shorts,                                         "Y8.4: MCI in ambiguous candidates")
ok("query" in _y8,                                              "Y8.5: query field present in ambiguous response")
ok(bool(_y8.get("message")),                                    "Y8.6: message field is non-empty")

print("\n=== Y9: unknown query -> status=not_found ===")

_clear_snapshot_cache()
_y9 = get_team_snapshot("xx_no_such_team_xyz", bootstrap=_WOL_BOOTSTRAP)
ok(_y9["status"] == "not_found",                                "Y9.1: unknown team -> not_found")
ok("query" in _y9,                                              "Y9.2: query field present in not_found")
ok(bool(_y9.get("message")),                                    "Y9.3: message non-empty in not_found")

print("\n=== Y10: top_n_players=2 returns 2 players ===")

_clear_snapshot_cache()
_y10 = get_team_snapshot("WOL", top_n_players=2, bootstrap=_WOL_BOOTSTRAP)
ok(_y10["status"] == "ok",                                      "Y10.1: status=ok for top_n_players=2")
ok(len(_y10["top_players"]) == 2,                               "Y10.2: top_players has exactly 2 entries")

print("\n=== Y11: top_n_players=99 capped at 10 ===")

_clear_snapshot_cache()
_y11 = get_team_snapshot("WOL", top_n_players=99, bootstrap=_WOL_BOOTSTRAP)
ok(_y11["status"] == "ok",                                      "Y11.1: status=ok for top_n_players=99")
ok(len(_y11["top_players"]) <= 10,                              "Y11.2: top_players capped at 10 (silent cap)")

print("\n=== Y12: fixture_horizon=2 returns 2 fixtures ===")

_clear_snapshot_cache()
_y12 = get_team_snapshot("WOL", fixture_horizon=2, bootstrap=_WOL_BOOTSTRAP)
ok(_y12["status"] == "ok",                                      "Y12.1: status=ok for fixture_horizon=2")
ok(len(_y12["upcoming_fixtures"]) == 2,                         "Y12.2: upcoming_fixtures has 2 entries")

print("\n=== Y13: registered in TOOL_NAMES; registry now 23 ===")

ok("get_team_snapshot" in TOOL_NAMES,                           "Y13.1: get_team_snapshot in TOOL_NAMES frozenset")
_all_schemas_y = list_tool_schemas()
ok("get_team_snapshot" in _all_schemas_y,                       "Y13.2: get_team_snapshot in list_tool_schemas()")
ok(len(_all_schemas_y) == 25,                                   "Y13.3: registry has exactly 25 tools (after P2.8)")

print("\n=== Y14: schema validates ===")

_gts_schema = get_tool_schema("get_team_snapshot")
ok(_gts_schema is not None,                                     "Y14.1: get_tool_schema('get_team_snapshot') returns non-None")
ok(_gts_schema.name == "get_team_snapshot",                     "Y14.2: schema.name == 'get_team_snapshot'")
ok("team_name" in _gts_schema.parameters.get("properties", {}),
   "Y14.3: team_name in schema properties")
ok("team_name" in _gts_schema.parameters.get("required", []),  "Y14.4: team_name is required")
ok(validate_tool_schema_shape(_gts_schema),                     "Y14.5: validate_tool_schema_shape passes")

print("\n=== Y15: orchestrator dispatches get_team_snapshot via mock LLM ===")

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockTeamSnapshotClient:
    """Returns a get_team_snapshot tool_use call for 'wolves'."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_gts_001"
            name  = "get_team_snapshot"
            input = {"team_name": "wolves"}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


_clear_snapshot_cache()
_mock_team = _MockTeamSnapshotClient()
_y15 = ask_orchestrated(
    "quien es el mejor jugador de wolves",
    _WOL_BOOTSTRAP,
    client=_mock_team,
    provider="anthropic",
)

ok(_y15.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "Y15.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_y15.tool_chosen == "get_team_snapshot",                     "Y15.2: orchestrator dispatched get_team_snapshot")
ok(isinstance(_y15.tool_output, dict),                          "Y15.3: tool_output is a dict")
ok(_y15.tool_output.get("status") in ("ok", "not_found", "ambiguous", "error"),
   "Y15.4: tool_output.status is one of the valid statuses")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)


# ---------------------------------------------------------------------------
# Section Z: P2.7 web_fetch — allowlist + SSRF + truncation + dispatcher
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.web_fetch import web_fetch as _web_fetch

print("\n=== Z: web_fetch allowlist + SSRF + truncation ===")

# ---- Z1-Z6: Allowlist coverage (path-prefix filters enforced) -------------
_z_fetch_ok = lambda url: "<html><body>football news</body></html>"

print("\n=== Z1: allowlisted BBC sport/football URL ===")
_z1 = _web_fetch("https://www.bbc.com/sport/football/12345", fetch_fn=_z_fetch_ok)
ok(_z1["status"] == "ok", "Z1.1: bbc.com/sport/football -> status=ok")
ok(_z1["domain"] == "www.bbc.com", "Z1.2: domain extracted correctly")

print("\n=== Z2: BBC /weather/today -> refused (wrong path) ===")
_z2 = _web_fetch("https://www.bbc.com/weather/today", fetch_fn=_z_fetch_ok)
ok(_z2["status"] == "refused", "Z2.1: bbc.com/weather -> status=refused")
ok(_z2.get("code") == "url_not_allowlisted",
      "Z2.2: code=url_not_allowlisted (path filter caught it)")

print("\n=== Z3: example.com -> refused (not allowlisted) ===")
_z3 = _web_fetch("https://example.com/anything", fetch_fn=_z_fetch_ok)
ok(_z3["status"] == "refused", "Z3.1: example.com -> status=refused")
ok(_z3.get("code") == "url_not_allowlisted", "Z3.2: code=url_not_allowlisted")
ok("allowed_domains" in _z3 and isinstance(_z3["allowed_domains"], list),
      "Z3.3: allowed_domains list returned for refused result")

print("\n=== Z4: fantasy.premierleague.com (any path) -> ok ===")
_z4 = _web_fetch("https://fantasy.premierleague.com/api/bootstrap-static/", fetch_fn=_z_fetch_ok)
ok(_z4["status"] == "ok", "Z4: fantasy.premierleague.com -> ok (no path filter)")

print("\n=== Z5: Athletic /football/<id> -> ok ===")
_z5 = _web_fetch("https://www.theathletic.com/football/12345", fetch_fn=_z_fetch_ok)
ok(_z5["status"] == "ok", "Z5: theathletic.com/football -> ok")

print("\n=== Z6: Athletic /news/<id> -> refused (wrong path) ===")
_z6 = _web_fetch("https://www.theathletic.com/news/12345", fetch_fn=_z_fetch_ok)
ok(_z6["status"] == "refused", "Z6.1: theathletic.com/news -> refused")
ok(_z6.get("code") == "url_not_allowlisted", "Z6.2: code=url_not_allowlisted (path)")

# ---- Z7-Z9: URL parsing edge cases ----------------------------------------
print("\n=== Z7: malformed url -> refused ===")
_z7 = _web_fetch("not a url", fetch_fn=_z_fetch_ok)
ok(_z7["status"] == "refused", "Z7.1: malformed -> refused")
# Either url_invalid (no scheme) or url_not_allowlisted; both acceptable
ok(_z7.get("code") in ("url_invalid", "url_not_allowlisted"),
      "Z7.2: code is url_invalid or url_not_allowlisted")

print("\n=== Z8: ftp:// scheme -> refused ===")
_z8 = _web_fetch("ftp://example.com/foo", fetch_fn=_z_fetch_ok)
ok(_z8["status"] == "refused", "Z8.1: ftp:// -> refused")
ok(_z8.get("code") == "url_invalid", "Z8.2: code=url_invalid (non-http scheme)")

print("\n=== Z9: empty url -> refused ===")
_z9 = _web_fetch("", fetch_fn=_z_fetch_ok)
ok(_z9["status"] == "refused", "Z9.1: empty -> refused")
ok(_z9.get("code") == "url_invalid", "Z9.2: code=url_invalid")

# ---- Z10-Z13: SSRF guards -------------------------------------------------
print("\n=== Z10: 127.0.0.1 -> refused (SSRF or allowlist) ===")
_z10 = _web_fetch("http://127.0.0.1/admin", fetch_fn=_z_fetch_ok)
ok(_z10["status"] == "refused", "Z10.1: 127.0.0.1 -> refused")
# SSRF fires before allowlist for IP literals
ok(_z10.get("code") in ("private_address_blocked", "url_not_allowlisted"),
      "Z10.2: code is SSRF or allowlist refusal")

print("\n=== Z11: 169.254.169.254 (AWS metadata) -> refused ===")
_z11 = _web_fetch("http://169.254.169.254/latest/meta-data/", fetch_fn=_z_fetch_ok)
ok(_z11["status"] == "refused", "Z11.1: 169.254 -> refused (link-local SSRF)")
ok(_z11.get("code") in ("private_address_blocked", "url_not_allowlisted"),
      "Z11.2: code is SSRF or allowlist refusal")

print("\n=== Z12: 192.168.1.1 -> refused ===")
_z12 = _web_fetch("http://192.168.1.1/", fetch_fn=_z_fetch_ok)
ok(_z12["status"] == "refused", "Z12.1: 192.168.1.1 -> refused (RFC1918 SSRF)")
ok(_z12.get("code") in ("private_address_blocked", "url_not_allowlisted"),
      "Z12.2: code is SSRF or allowlist refusal")

print("\n=== Z13: DNS rebinding (allowlisted host resolves to private IP) -> refused ===")
# Monkey-patch socket.gethostbyname to return private IP for an allowlisted host.
import socket as _socket
_orig_gethostbyname = _socket.gethostbyname
def _dns_rebind(host):
    if host == "fantasy.premierleague.com":
        return "127.0.0.1"
    return _orig_gethostbyname(host)
_socket.gethostbyname = _dns_rebind
try:
    _z13 = _web_fetch("https://fantasy.premierleague.com/api/bootstrap-static/",
                       fetch_fn=_z_fetch_ok)
    ok(_z13["status"] == "refused",
          "Z13.1: allowlisted-host-but-private-IP -> refused (DNS rebinding caught)")
    ok(_z13.get("code") == "private_address_blocked",
          "Z13.2: code=private_address_blocked")
finally:
    _socket.gethostbyname = _orig_gethostbyname

# ---- Z14-Z16: Response handling -------------------------------------------
print("\n=== Z14: long body -> truncated=True, excerpt 4000 chars ===")
_long_body = "x" * 10000
_z14 = _web_fetch("https://fantasy.premierleague.com/x",
                   fetch_fn=lambda url: _long_body)
ok(_z14["status"] == "ok", "Z14.1: long body fetch ok")
ok(_z14["truncated"] is True, "Z14.2: truncated=True")
ok(len(_z14["text_excerpt"]) == 4000, "Z14.3: text_excerpt is 4000 chars")

print("\n=== Z15: short body -> truncated=False, full content ===")
_z15 = _web_fetch("https://fantasy.premierleague.com/y",
                   fetch_fn=lambda url: "short")
ok(_z15["status"] == "ok", "Z15.1: short body fetch ok")
ok(_z15["truncated"] is False, "Z15.2: truncated=False")
ok(_z15["text_excerpt"] == "short", "Z15.3: full body returned")

print("\n=== Z16: fetch_fn raises -> status=error ===")
def _z16_raise(url):
    raise RuntimeError("simulated network failure")
_z16 = _web_fetch("https://fantasy.premierleague.com/z",
                   fetch_fn=_z16_raise)
ok(_z16["status"] == "error", "Z16.1: fetch exception -> status=error")
ok(_z16.get("code") == "fetch_failed", "Z16.2: code=fetch_failed")

# ---- Z17-Z20: Schema registration + dispatcher ----------------------------
print("\n=== Z17: web_fetch registered in TOOL_NAMES; registry=24 ===")
from fpl_grounded_assistant.tool_schema_registry import (
    TOOL_NAMES as _Z_TOOL_NAMES,
    _ALL_SCHEMAS as _Z_ALL_SCHEMAS,
    get_tool_schema as _Z_get_tool_schema,
)
ok("web_fetch" in _Z_TOOL_NAMES, "Z17.1: web_fetch in TOOL_NAMES")
ok(len(_Z_ALL_SCHEMAS) == 25, "Z17.2: registry has exactly 25 tools (after P2.8)")

print("\n=== Z18: schema validates ===")
_z18_schema = _Z_get_tool_schema("web_fetch")
ok(_z18_schema is not None, "Z18.1: schema retrievable")
ok(_z18_schema.name == "web_fetch", "Z18.2: schema.name == 'web_fetch'")
ok("url" in _z18_schema.parameters.get("properties", {}),
      "Z18.3: url in properties")
ok("url" in _z18_schema.parameters.get("required", []),
      "Z18.4: url in required")
ok(validate_tool_schema_shape(_z18_schema),
      "Z18.5: validate_tool_schema_shape passes")

print("\n=== Z19: schema description advertises allowlist restriction ===")
ok("allowlisted" in _z18_schema.description.lower(),
      "Z19.1: description contains 'allowlisted'")

print("\n=== Z20: orchestrator dispatches web_fetch via mock LLM ===")
os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"

class _Z20MockClient:
    def __init__(self) -> None:
        self.messages = self
    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_z20_001"
            name  = "web_fetch"
            input = {"url": "https://fantasy.premierleague.com/api/bootstrap-static/"}
        class _R:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
        return _R()

from fpl_grounded_assistant.orchestrator import (
    ask_orchestrated as _Z_ask, OUTCOME_OK as _Z_OK,
    OUTCOME_TOOL_RESULT_ERROR as _Z_TRE,
)
_z20_result = _Z_ask("get me the bootstrap",
                       STANDARD_BOOTSTRAP,
                       client=_Z20MockClient())
# Two acceptable outcomes: ok (real fetch succeeded) or tool_result_error (real
# fetch hit the network and failed/timed-out, which is fine in CI without network)
ok(_z20_result.outcome in (_Z_OK, _Z_TRE),
      f"Z20.1: orchestrator dispatched web_fetch (outcome={_z20_result.outcome})")
ok(_z20_result.tool_chosen == "web_fetch",
      "Z20.2: orchestrator chose web_fetch")
ok(isinstance(_z20_result.tool_output, dict),
      "Z20.3: tool_output is a dict")
ok("status" in _z20_result.tool_output,
      "Z20.4: tool_output has 'status' key")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)


# ---------------------------------------------------------------------------
# Section AA: P2.8 renderers + rank_players_by_metric (Gap A + Gap B)
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.renderer import render as _render
from fpl_grounded_assistant.rank_players_by_metric import rank_players_by_metric as _rank

print("\n=== AA1-AA7: P2 tool renderers return non-empty string (no unknown_tool) ===")

# AA1: find_players ok output
_aa1_out = {"status": "ok", "query": "haaland", "match_count": 1,
            "matches": [{"web_name": "Haaland", "team_short": "MCI", "position": "FWD",
                         "now_cost": 145, "form": 8.0, "total_points": 200,
                         "minutes_played_season": 1800}]}
_aa1_rendered = _render("find_players", _aa1_out)
ok(isinstance(_aa1_rendered, str) and len(_aa1_rendered) > 0, "AA1.1: find_players renderer returns non-empty string")
ok("unknown_tool" not in _aa1_rendered, "AA1.2: no 'unknown_tool' in find_players rendered output")

# AA2: get_player_snapshot ok output
_aa2_out = {"status": "ok", "player": {
    "web_name": "Haaland", "team_short": "MCI", "position": "FWD",
    "now_cost": 145, "selected_by_percent": 52.3, "status": "Available",
    "form": 8.0, "total_points": 200, "points_per_game": 7.0,
    "expected_goals": 1.5, "expected_assists": 0.2,
    "expected_goal_involvements": 1.7, "ict_index": 60.0,
    "minutes_played_season": 1800, "news": "", "chance_of_playing_this_round": None,
    "news_added": None, "transfers_in_event": 5000, "transfers_out_event": 1000,
}}
_aa2_rendered = _render("get_player_snapshot", _aa2_out)
ok(isinstance(_aa2_rendered, str) and len(_aa2_rendered) > 0, "AA2.1: get_player_snapshot renderer returns non-empty string")
ok("unknown_tool" not in _aa2_rendered, "AA2.2: no 'unknown_tool' in get_player_snapshot rendered output")
ok("Haaland" in _aa2_rendered, "AA2.3: player name appears in rendered output")

# AA3: get_player_history ok output
_aa3_out = {"status": "ok",
            "player": {"web_name": "Haaland", "team_short": "MCI", "position": "FWD"},
            "last_n_gws": 2,
            "history": [
                {"round": 27, "opponent_team_short": "MUN", "minutes": 90,
                 "total_points": 8, "goals_scored": 1, "assists": 0,
                 "expected_goals": 0.85, "expected_assists": 0.10, "was_home": True},
            ],
            "summary": {"total_points": 8, "avg_form": 8.0, "total_xgi": 0.95}}
_aa3_rendered = _render("get_player_history", _aa3_out)
ok(isinstance(_aa3_rendered, str) and len(_aa3_rendered) > 0, "AA3.1: get_player_history renderer returns non-empty string")
ok("unknown_tool" not in _aa3_rendered, "AA3.2: no 'unknown_tool' in get_player_history rendered output")

# AA4: get_fixtures_for_gw ok output
_aa4_out = {"status": "ok", "gw": 38, "is_blank": False, "is_double": False,
            "finished": False,
            "fixtures": [{"id": 1, "kickoff_time": "2026-05-17T15:00:00Z",
                          "home_team_short": "ARS", "away_team_short": "CHE",
                          "home_fdr": 3, "away_fdr": 4,
                          "finished": False, "home_score": None, "away_score": None}],
            "summary": {"total_fixtures": 1, "easiest_for_home_team": "ARS",
                        "hardest_for_home_team": "ARS",
                        "double_gw_teams": [], "blank_gw_teams": []}}
_aa4_rendered = _render("get_fixtures_for_gw", _aa4_out)
ok(isinstance(_aa4_rendered, str) and len(_aa4_rendered) > 0, "AA4.1: get_fixtures_for_gw renderer returns non-empty string")
ok("unknown_tool" not in _aa4_rendered, "AA4.2: no 'unknown_tool' in get_fixtures_for_gw rendered output")
ok("GW38" in _aa4_rendered, "AA4.3: GW number appears in rendered output")

# AA5: get_gameweek_context ok output
_aa5_out = {"status": "ok", "current_gw": 28, "next_gw": 29,
            "current_gw_deadline": "2026-02-21T11:30:00Z",
            "next_gw_deadline": "2026-02-28T11:30:00Z",
            "season_total_gws": 38, "is_season_over": False,
            "is_pre_season": False, "current_gw_status": "in_progress",
            "blank_gw_alerts": [], "double_gw_alerts": []}
_aa5_rendered = _render("get_gameweek_context", _aa5_out)
ok(isinstance(_aa5_rendered, str) and len(_aa5_rendered) > 0, "AA5.1: get_gameweek_context renderer returns non-empty string")
ok("unknown_tool" not in _aa5_rendered, "AA5.2: no 'unknown_tool' in get_gameweek_context rendered output")
ok("GW28" in _aa5_rendered, "AA5.3: current GW number appears in rendered output")

# AA6: get_team_snapshot ok output
_aa6_out = {"status": "ok",
            "team": {"id": 40, "short_name": "WOL", "name": "Wolves", "strength": 3,
                     "strength_overall_home": 1150, "strength_overall_away": 1100,
                     "form": None, "position": None, "played": None,
                     "win": None, "draw": None, "loss": None, "points": None},
            "upcoming_fixtures": [
                {"gw": 29, "opponent_short": "ARS", "opponent_name": "Arsenal",
                 "is_home": True, "fdr": 4, "kickoff_time": "2026-03-01T15:00:00Z"},
            ],
            "top_players": [
                {"web_name": "Cunha", "position": "FWD", "total_points": 130,
                 "form": 9.0, "now_cost": 75, "team_short": "WOL",
                 "selected_by_percent": 18.0},
            ],
            "summary": {"avg_fdr_next_5": 4.0, "is_easy_run": False,
                        "is_hard_run": True, "top_scorer_web_name": "Cunha",
                        "top_form_web_name": "Cunha"}}
_aa6_rendered = _render("get_team_snapshot", _aa6_out)
ok(isinstance(_aa6_rendered, str) and len(_aa6_rendered) > 0, "AA6.1: get_team_snapshot renderer returns non-empty string")
ok("unknown_tool" not in _aa6_rendered, "AA6.2: no 'unknown_tool' in get_team_snapshot rendered output")
ok("Wolves" in _aa6_rendered or "WOL" in _aa6_rendered, "AA6.3: team name/short appears in rendered output")

# AA7: web_fetch ok output
_aa7_out = {"status": "ok", "url": "https://fantasy.premierleague.com/api/bootstrap-static/",
            "domain": "fantasy.premierleague.com", "content_type": "application/json",
            "content_length": 5000, "text_excerpt": "football data here", "truncated": False}
_aa7_rendered = _render("web_fetch", _aa7_out)
ok(isinstance(_aa7_rendered, str) and len(_aa7_rendered) > 0, "AA7.1: web_fetch renderer returns non-empty string")
ok("unknown_tool" not in _aa7_rendered, "AA7.2: no 'unknown_tool' in web_fetch rendered output")
ok("5000" in _aa7_rendered, "AA7.3: content_length appears in rendered output")

print("\n=== AA8-AA10: renderers handle non-ok statuses ===")

# AA8: find_players not_found
_aa8_out = {"status": "not_found", "query": "xyz_fake"}
_aa8_rendered = _render("find_players", _aa8_out)
ok(isinstance(_aa8_rendered, str) and len(_aa8_rendered) > 0, "AA8.1: find_players not_found returns non-empty string")
ok("unknown_tool" not in _aa8_rendered, "AA8.2: no unknown_tool in find_players not_found")

# AA9: get_player_snapshot ambiguous
_aa9_out = {"status": "ambiguous", "query": "sa",
            "candidates": [
                {"web_name": "Salah", "team_short": "LIV", "position": "MID", "match_rank": 1},
                {"web_name": "Saka",  "team_short": "ARS", "position": "MID", "match_rank": 1},
            ],
            "message": "Multiple players match 'sa'. Please specify."}
_aa9_rendered = _render("get_player_snapshot", _aa9_out)
ok(isinstance(_aa9_rendered, str) and len(_aa9_rendered) > 0, "AA9.1: get_player_snapshot ambiguous returns non-empty string")
ok("unknown_tool" not in _aa9_rendered, "AA9.2: no unknown_tool in ambiguous output")
ok("Salah" in _aa9_rendered or "Saka" in _aa9_rendered, "AA9.3: candidate names appear in ambiguous output")

# AA10: web_fetch refused
_aa10_out = {"status": "refused", "url": "https://example.com/x",
             "code": "url_not_allowlisted",
             "message": "URL domain 'example.com' is not in the allowlist.",
             "allowed_domains": ["fantasy.premierleague.com"]}
_aa10_rendered = _render("web_fetch", _aa10_out)
ok(isinstance(_aa10_rendered, str) and len(_aa10_rendered) > 0, "AA10.1: web_fetch refused returns non-empty string")
ok("unknown_tool" not in _aa10_rendered, "AA10.2: no unknown_tool in web_fetch refused")

print("\n=== AA11-AA18: rank_players_by_metric unit tests ===")

# AA11: basic xgi top-5 call
_aa11 = _rank("expected_goal_involvements", top_n=5, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa11["status"] == "ok", "AA11.1: rank by expected_goal_involvements -> status=ok")
ok(len(_aa11["ranked"]) == 5, "AA11.2: returned 5 ranked entries")

# AA12: ranked entries sorted descending
_aa12 = _rank("expected_goal_involvements", top_n=10, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa12["status"] == "ok", "AA12.0: precondition status=ok")
_aa12_vals = [e["metric_value"] for e in _aa12["ranked"]]
ok(_aa12_vals == sorted(_aa12_vals, reverse=True), "AA12.1: ranked entries sorted by metric_value descending")

# AA13: each entry has full 21 grounding fields + metric_value + rank
_aa13 = _rank("form", top_n=3, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa13["status"] == "ok", "AA13.0: precondition status=ok")
_aa13_entry = _aa13["ranked"][0]
for _field in _REQUIRED_MATCH_FIELDS:
    ok(_field in _aa13_entry, f"AA13: grounding field '{_field}' present in ranked entry")
ok("metric_value" in _aa13_entry, "AA13: metric_value present in ranked entry")
ok("rank" in _aa13_entry, "AA13: rank present in ranked entry")
ok(_aa13_entry["rank"] == 1, "AA13: first entry has rank=1")

# AA14: alias "xgi" maps to expected_goal_involvements
_aa14a = _rank("xgi", top_n=5, bootstrap=STANDARD_BOOTSTRAP)
_aa14b = _rank("expected_goal_involvements", top_n=5, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa14a["status"] == "ok", "AA14.1: 'xgi' alias returns status=ok")
ok(_aa14a["metric"] == _aa14b["metric"], "AA14.2: 'xgi' resolves to same field as expected_goal_involvements")
ok([e["metric_value"] for e in _aa14a["ranked"]] == [e["metric_value"] for e in _aa14b["ranked"]],
   "AA14.3: 'xgi' and 'expected_goal_involvements' return same values")

# AA15: invalid metric returns invalid_argument
_aa15 = _rank("not_a_real_metric_xyz", bootstrap=STANDARD_BOOTSTRAP)
ok(_aa15["status"] == "invalid_argument", "AA15.1: unknown metric -> status=invalid_argument")
ok(_aa15.get("code") == "unknown_metric", "AA15.2: code=unknown_metric")
ok("valid_metrics" in _aa15 and isinstance(_aa15["valid_metrics"], list) and len(_aa15["valid_metrics"]) > 0,
   "AA15.3: valid_metrics list returned")

# AA16: position filter — only midfielders (MID)
_aa16 = _rank("form", top_n=10, position="MID", bootstrap=STANDARD_BOOTSTRAP)
ok(_aa16["status"] == "ok", "AA16.1: position='MID' filter -> status=ok")
ok(_aa16["position_filter"] == "MID", "AA16.2: position_filter='MID' in response")
ok(all(e["position"] == "MID" for e in _aa16["ranked"]), "AA16.3: all ranked entries have position=MID")

# AA17: min_minutes filter excludes low-minute players
# De Bruyne has only 270 minutes in STANDARD_BOOTSTRAP; min_minutes=500 should exclude him
_aa17 = _rank("total_points", top_n=10, min_minutes=500, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa17["status"] == "ok", "AA17.1: min_minutes=500 filter -> status=ok")
ok(_aa17["min_minutes_filter"] == 500, "AA17.2: min_minutes_filter=500 in response")
ok(all(e.get("minutes_played_season", 0) >= 500 for e in _aa17["ranked"]),
   "AA17.3: all ranked entries have minutes_played_season >= 500")

# AA18: top_n=99 silently capped to 50
_aa18 = _rank("form", top_n=99, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa18["status"] == "ok", "AA18.1: top_n=99 -> status=ok")
ok(_aa18["top_n"] <= 50, "AA18.2: top_n=99 silently capped at 50 (top_n field <= 50)")
ok(len(_aa18["ranked"]) <= 50, "AA18.3: len(ranked) <= 50")

print("\n=== AA19: rank_players_by_metric registered in TOOL_NAMES; registry == 25 ===")

ok("rank_players_by_metric" in TOOL_NAMES, "AA19.1: rank_players_by_metric in TOOL_NAMES frozenset")
_all_schemas_aa = list_tool_schemas()
ok("rank_players_by_metric" in _all_schemas_aa, "AA19.2: rank_players_by_metric in list_tool_schemas()")
ok(len(_all_schemas_aa) == 25, "AA19.3: registry has exactly 25 tools")
_rpm_schema = get_tool_schema("rank_players_by_metric")
ok(_rpm_schema is not None, "AA19.4: get_tool_schema('rank_players_by_metric') returns non-None")
ok(validate_tool_schema_shape(_rpm_schema), "AA19.5: schema passes validate_tool_schema_shape")

print("\n=== AA20: orchestrator dispatches rank_players_by_metric via mock LLM ===")

os.environ["FPL_ORCH_TEST_INJECTION"] = "1"
os.environ["FPL_EVAL_DISABLED"] = "1"


class _MockRankMetricClient:
    """Returns a rank_players_by_metric tool_use call for xgi."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_rpm_001"
            name  = "rank_players_by_metric"
            input = {"metric": "expected_goal_involvements", "top_n": 10}

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"
            usage       = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                         "cache_read_input_tokens": 0})()

        return _Response()


_mock_rank = _MockRankMetricClient()
_aa20 = ask_orchestrated(
    "dame el top 10 de jugadores por xgi",
    STANDARD_BOOTSTRAP,
    client=_mock_rank,
    provider="anthropic",
)

ok(_aa20.outcome in (OUTCOME_OK, OUTCOME_TOOL_RESULT_ERROR),
   "AA20.1: outcome is ok or tool_result_error (not llm_error/no_tool)")
ok(_aa20.tool_chosen == "rank_players_by_metric",
   "AA20.2: orchestrator dispatched rank_players_by_metric tool")
ok(isinstance(_aa20.tool_output, dict),
   "AA20.3: tool_output is a dict")
ok(_aa20.tool_output.get("status") in ("ok", "invalid_argument", "error"),
   "AA20.4: tool_output.status is one of the valid statuses")

os.environ.pop("FPL_ORCH_TEST_INJECTION", None)
os.environ.pop("FPL_EVAL_DISABLED", None)

print("\n=== AA21: rank_players_by_metric renderer (via render()) ===")

_aa21_out = _rank("expected_goal_involvements", top_n=5, bootstrap=STANDARD_BOOTSTRAP)
ok(_aa21_out["status"] == "ok", "AA21.0: precondition")
_aa21_rendered = _render("rank_players_by_metric", _aa21_out)
ok(isinstance(_aa21_rendered, str) and len(_aa21_rendered) > 0,
   "AA21.1: rank_players_by_metric renderer returns non-empty string")
ok("unknown_tool" not in _aa21_rendered,
   "AA21.2: no 'unknown_tool' in rank_players_by_metric rendered output")
ok("expected_goal_involvements" in _aa21_rendered or "xgi" in _aa21_rendered.lower() or
   "expected_goal" in _aa21_rendered,
   "AA21.3: metric name appears in rendered output")


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
