"""
FPL Grounded Assistant — CLI integration examples.
====================================================
Phase 4d: external integration examples and client fixtures.

Shows how to call ``fpl_cli.run()`` for each supported scenario.
All examples use the built-in fixture bootstraps — no network or LLM required.

Scenarios covered
-----------------
supported_ok               -- captain score for a known player
supported_ambiguous        -- player name matches multiple entries
supported_not_found        -- supported intent, player not in registry
supported_missing_arguments -- ranking intent without candidates_list
unsupported_intent         -- question outside the supported intent set

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
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_cli_scenario(scenario: dict[str, Any]) -> tuple[int, str]:
    """Run a single CLI scenario and return ``(exit_code, output)``.

    Parameters
    ----------
    scenario:
        One entry from ``CLI_SCENARIOS``.

    Returns
    -------
    tuple[int, str]
        ``exit_code`` (0 or 1) and plain-text ``output`` string.
    """
    return run(scenario["question"], scenario["bootstrap"])


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
