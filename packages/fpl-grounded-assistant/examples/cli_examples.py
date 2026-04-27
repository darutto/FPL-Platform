"""
FPL Grounded Assistant — CLI integration examples.
====================================================
Phase 4d: external integration examples and client fixtures.
Phase 5j: comparison debug exposure.
Phase 5o: captain debug exposure.
Phase 5q: ranked captain debug exposure.
Phase 7c: transfer and chip debug exposure.
Phase 8a1: position-aware scoring — GKP comparison debug exposure.

Shows how to call ``fpl_cli.run()`` for each supported scenario.
All examples use the built-in fixture bootstraps — no network or LLM required.

Scenarios covered
-----------------
supported_ok               -- captain score for a known player
supported_ambiguous        -- player name matches multiple entries
supported_not_found        -- supported intent, player not in registry
supported_missing_arguments -- ranking intent without candidates_list
unsupported_intent         -- question outside the supported intent set
comparison_direct          -- direct two-player comparison
comparison_not_found       -- comparison with one unknown player
comparison_debug           -- comparison with debug=True; shows structured
                              comparison payload including player_a/b context
captain_debug              -- captain score with debug=True; shows structured
                              captain payload (Phase 5n/5o)
captain_ranking_debug      -- ranked captain query with debug=True and
                              candidates_list; shows structured captain_ranking
                              payload (Phase 5p/5q)
transfer_debug             -- transfer advice with debug=True; shows structured
                              transfer payload (Phase 7a/7c)
chip_debug                 -- chip advice with debug=True; shows structured
                              chip payload (Phase 7b/7c)
fixture_run_direct         -- player fixture run with debug=True; shows structured
                              fixture_run payload (Phase 7h)
differential_picks_direct  -- differential picks with debug=True; shows structured
                              differential payload (Phase 7g)
position_score_gkp_comparison -- GKP vs FWD comparison with debug=True; shows
                              position_score (Phase 8a1 position-aware heuristic)

Key exit-code contract
-----------------------
- exit 0  -- request was handled by the supported system contract
             (this includes ok, ambiguous, not_found, missing_arguments)
- exit 1  -- unsupported_intent only

Run directly::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner;../fpl-player-registry;../fpl-captain-engine;\\
    ../fpl-data-core;../fpl-tool-contract;../fpl-query-tools;\\
    ../fpl-api-client;../fpl-pipeline;. python examples/cli_examples.py

Or import from a test runner::

    from examples.cli_examples import CLI_SCENARIOS, run_cli_scenario
"""
from __future__ import annotations

from typing import Any

from fpl_grounded_assistant import STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP
from fpl_cli import run

# Minimal bootstrap extension for differential picks example.
# Adds two low-ownership available players (Palmer, Mbeumo) to the standard
# fixture set so the differential_picks_direct example returns actual picks.
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
# Scenario definitions
# ---------------------------------------------------------------------------
# Each scenario is a plain dict matching the final_response_fixtures schema:
#   id           -- unique name (mirrors final_response_fixtures.scenario_id)
#   question     -- raw question passed to run()
#   bootstrap    -- which bootstrap dict to use
#   expected_exit -- 0 if supported, 1 if unsupported_intent
#   note         -- brief explanation for external readers

CLI_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "supported_ok",
        "question": "should I captain Haaland",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "note": (
            "Captain score for a known player (Haaland). "
            "Supported intent, deterministic result. "
            "exit=0 — request was handled by the supported system contract."
        ),
    },
    {
        "id": "supported_ambiguous",
        "question": "who is Doe",
        "bootstrap": AMBIGUOUS_BOOTSTRAP,
        "expected_exit": 0,
        "note": (
            "Player name 'Doe' matches two players in AMBIGUOUS_BOOTSTRAP. "
            "The system surfaces an ambiguous result rather than guessing. "
            "exit=0 — the request was handled; outcome detail is in final_text."
        ),
    },
    {
        "id": "supported_not_found",
        "question": "should I captain xyznotaplayer999",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "note": (
            "Supported intent (captain score) but player not in registry. "
            "final_text explains the player was not found. "
            "exit=0 — the system handled the request; outcome is in final_text."
        ),
    },
    {
        "id": "supported_missing_arguments",
        "question": "top captains this week",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "note": (
            "Ranking intent recognised, but candidates_list was not passed to run(). "
            "The system returns missing_arguments rather than silently failing. "
            "exit=0 — the request was handled; outcome is in final_text."
        ),
    },
    {
        "id": "unsupported_intent",
        "question": "Is Haaland fit to play?",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 1,
        "note": (
            "Out-of-scope question — not in the supported intent set. "
            "exit=1 signals to callers that this intent is outside system coverage. "
            "final_text still contains a user-facing message."
        ),
    },
    # Phase 5e: comparison exposure
    {
        "id": "comparison_direct",
        "question": "compare Haaland and Salah",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "note": (
            "Direct player comparison. Both players in STANDARD_BOOTSTRAP. "
            "exit=0 — comparison is a supported intent. "
            "final_text includes explanation-enriched recommendation (Phase 5d): "
            "winner, margin label, and Advantages clause."
        ),
    },
    {
        "id": "comparison_not_found",
        "question": "compare Haaland and NoSuchPlayer99",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "note": (
            "Comparison where the second player is not in the registry. "
            "exit=0 — supported intent even when a player is not found. "
            "final_text explains the player could not be found."
        ),
    },
    # Phase 5j: comparison debug exposure
    {
        "id": "comparison_debug",
        "question": "compare Haaland and Saka",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Direct player comparison with debug=True. "
            "Output is a JSON object that includes the structured comparison "
            "payload with winner, margin, label, reasons, and per-player context "
            "(player_a and player_b each with web_name, position, captain_score, "
            "role_bonus, set_piece_notes). "
            "Default CLI output (debug=False) remains plain text only."
        ),
    },
    # Phase 5o: captain debug exposure
    {
        "id": "captain_debug",
        "question": "should I captain Salah",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Direct captain score query with debug=True. "
            "Output is a JSON object that includes the structured captain "
            "payload (Phase 5n): web_name, team_short, captain_score, tier, "
            "role_bonus, and set_piece_notes. "
            "Salah: tier='safe', role_bonus=5.0, "
            "set_piece_notes=['penalty_taker_1']. "
            "Default CLI output (debug=False) remains plain text only. "
            "Non-captain turns (e.g. comparison, gameweek) do not include "
            "the captain key."
        ),
    },
    # Phase 5q: ranked captain debug exposure
    {
        "id": "captain_ranking_debug",
        "question": "top captains this week",
        "bootstrap": STANDARD_BOOTSTRAP,
        "candidates_list": [
            {"query": "Salah"},
            {"query": "Haaland"},
            {"query": "Saka"},
        ],
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Ranked captain query with debug=True and candidates_list supplied. "
            "Output is a JSON object that includes the structured captain_ranking "
            "payload (Phase 5p): a list of entries each with rank, web_name, "
            "team_short, captain_score, tier, role_bonus, and set_piece_notes. "
            "Salah ranks #1 (tier='safe', penalty_taker_1), "
            "Haaland ranks #2 (tier='upside', penalty_taker_1), "
            "Saka ranks #3 (tier='differential', freekick_taker_2). "
            "Default CLI output (debug=False) remains plain text only. "
            "Non-ranking turns do not include the captain_ranking key."
        ),
    },
    # Phase 7c: transfer debug exposure
    {
        "id": "transfer_debug",
        "question": "should I sell Saka for Salah",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Transfer advice with debug=True. "
            "Output is a JSON object that includes the structured transfer "
            "payload (Phase 7a): player_out, player_in, recommendation, "
            "score_delta, price_delta, and reasons. "
            "Salah > Saka by a large margin → recommendation='transfer_in'. "
            "Default CLI output (debug=False) remains plain text only. "
            "Non-transfer turns (e.g. captain, comparison) do not include "
            "the transfer key."
        ),
    },
    # Phase 7c: chip debug exposure
    {
        "id": "chip_debug",
        "question": "should I use triple captain this week",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Chip advice with debug=True. "
            "Output is a JSON object that includes the structured chip "
            "payload (Phase 7b): chip, recommendation, gw, signal_value, "
            "signal_label. "
            "chip=='triple_captain'; signal_value is the top available MID/FWD "
            "captain score (float); signal_label=='top captain score'. "
            "recommendation in {conditions_favorable, conditions_marginal, "
            "conditions_unfavorable}. "
            "Default CLI output (debug=False) remains plain text only. "
            "Non-chip turns do not include the chip key."
        ),
    },
    {
        "id": "fixture_run_direct",
        "question": "Salah fixtures",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Player fixture run with debug=True (Phase 7h). "
            "Output is a JSON object that includes the structured fixture_run "
            "payload: web_name, team_short, position, horizon, "
            "current_gameweek, fixtures (list of {gameweek, opponent_short, "
            "is_home, difficulty}). "
            "Default CLI output (debug=False) is plain text only. "
            "Non-fixture turns do not include the fixture_run key."
        ),
    },
    {
        "id": "differential_picks_direct",
        "question": "good differentials",
        "bootstrap": _DIFFERENTIAL_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Differential picks with debug=True (Phase 7g). "
            "Output is a JSON object that includes the structured differential "
            "payload: ownership_threshold (15.0), top_n (int), and picks "
            "(list of {rank, web_name, team_short, position, captain_score, "
            "ownership, now_cost}). "
            "Players are filtered to status='a' and ownership < 15%. "
            "Ranked by deterministic captain score descending. "
            "Default CLI output (debug=False) is plain text only. "
            "Non-differential turns do not include the differential key."
        ),
    },
    # Phase 8a1: position-aware heuristic — GKP comparison debug exposure
    {
        "id": "position_score_gkp_comparison",
        "question": "compare Raya and Haaland",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "GKP vs FWD comparison with debug=True (Phase 8a1). "
            "Output is a JSON object that includes the structured comparison "
            "payload. player_a (Raya, GKP) and player_b (Haaland, FWD) each "
            "expose position_score (Layer 2 position-aware heuristic) alongside "
            "canonical captain_score (Layer 1). "
            "position_score uses position-specific weight profiles over 7 "
            "normalised components (form, fixture, xgi, minutes, saves, cs, dc). "
            "GKP weights saves and clean_sheet; FWD uses canonical MID weights "
            "(transitional bridge). "
            "Canonical captain_score is preserved unchanged for auditability. "
            "Default CLI output (debug=False) remains plain text only."
        ),
    },
    # Phase 8b: venue-aware fixture factor — comparison debug exposure
    {
        "id": "venue_aware_comparison_debug",
        "question": "compare Salah and Saka",
        "bootstrap": STANDARD_BOOTSTRAP,
        "expected_exit": 0,
        "debug": True,
        "note": (
            "Phase 8b venue-aware comparison with debug=True. "
            "STANDARD_BOOTSTRAP has team_fixtures for GW28. "
            "Salah (LIV, team 14) is home: raw FDR=4, effective_fdr=3.5 (home -0.5). "
            "Saka (ARS, team 1) is home: raw FDR=5, effective_fdr=4.5 (home -0.5). "
            "player_a and player_b each expose is_home (True/False/None) and "
            "effective_fdr (float, 1.0-5.0) in the structured comparison payload. "
            "Layer 2 (position_score) uses effective_fdr; "
            "Layer 1 (captain_score) still uses raw int FDR — unchanged. "
            "comparison_reasons includes venue-tagged FDR phrase: "
            "'easier fixture (FDR 4H vs 5H)' when efdr diff >= 1. "
            "Default CLI output (debug=False) remains plain text only."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_cli_scenario(scenario: dict[str, Any]) -> tuple[int, str]:
    """Run a single CLI scenario and return ``(exit_code, output)``.

    Parameters
    ----------
    scenario:
        One entry from ``CLI_SCENARIOS``.  An optional ``"debug": True``
        key causes ``run()`` to be called with ``debug=True``, producing a
        JSON string instead of plain text (Phase 5j).  An optional
        ``"candidates_list"`` key is forwarded to ``run()`` for ranked
        captain scenarios (Phase 5q).

    Returns
    -------
    tuple[int, str]
        ``exit_code`` (0 or 1) and output string (plain text or JSON).
    """
    return run(
        scenario["question"],
        scenario["bootstrap"],
        debug=scenario.get("debug", False),
        candidates_list=scenario.get("candidates_list"),
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("FPL CLI Integration Examples\n")
    all_pass = True
    for s in CLI_SCENARIOS:
        code, output = run_cli_scenario(s)
        ok = code == s["expected_exit"]
        label = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"[{label}] {s['id']}  exit={code}  (expected {s['expected_exit']})")
        print(f"       {s['note']}")
        first_line = output.split("\n")[0]
        print(f"       → {first_line[:100]}")
        print()
    print("All scenarios passed." if all_pass else "Some scenarios FAILED.")
