"""Unit tests for analyze_tool_routing.py's pure aggregation functions.

All data here is fabricated in-memory -- no LLM calls, no real observations
file. These tests protect the matrix/hit-rate arithmetic itself, which is
exactly the code a formatting bug could hide inside (per the measurement
task: "A harness that errors can report a clean result -- two identical
tracebacks diff clean").
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_tool_routing import (  # noqa: E402
    NO_TOOL,
    build_confusion_matrix,
    control_summary,
    count_exceptions,
    first_tool,
    is_hit_any,
    is_hit_first,
    load_observations,
    per_question_hit_rates,
    total_cost_usd,
    worst_offenders,
)


def _obs(
    question_id: str,
    family: str,
    acceptable_tools: list[str],
    control: bool,
    tool_sequence: list[str],
    exception: str | None = None,
    cost_usd: float = 0.0001,
) -> dict:
    return {
        "question_id": question_id,
        "family": family,
        "acceptable_tools": acceptable_tools,
        "control": control,
        "tool_sequence": tool_sequence,
        "tool_chosen": tool_sequence[0] if tool_sequence else None,
        "exception": exception,
        "cost_usd": cost_usd,
    }


def test_first_tool_reads_sequence_before_falling_back():
    obs = _obs("q1", "advice", ["get_chip_advice"], True, ["get_chip_advice", "build_squad"])
    assert first_tool(obs) == "get_chip_advice"


def test_first_tool_falls_back_to_tool_chosen_when_sequence_empty():
    obs = {"tool_sequence": [], "tool_chosen": "get_captain_score", "acceptable_tools": []}
    assert first_tool(obs) == "get_captain_score"


def test_is_hit_first_true_when_first_tool_in_acceptable_set():
    obs = _obs("q1", "advice", ["get_chip_advice", "build_squad"], False, ["build_squad", "get_chip_advice"])
    assert is_hit_first(obs) is True


def test_is_hit_first_false_on_the_known_confusion():
    obs = _obs("cvg-01", "chip_vs_gameweek", ["get_chip_advice", "build_squad"], False, ["get_gameweek_context"])
    assert is_hit_first(obs) is False


def test_is_hit_any_true_when_second_call_is_correct_even_if_first_is_not():
    # Models a case where the model explores get_current_gameweek first, then
    # calls the actually-acceptable tool in a follow-up round.
    obs = _obs("q1", "advice", ["get_chip_advice"], False, ["get_current_gameweek", "get_chip_advice"])
    assert is_hit_first(obs) is False
    assert is_hit_any(obs) is True


def test_build_confusion_matrix_counts_first_tool_per_family():
    observations = [
        _obs("cvg-01", "chip_vs_gameweek", ["get_chip_advice"], False, ["get_gameweek_context"]),
        _obs("cvg-01", "chip_vs_gameweek", ["get_chip_advice"], False, ["get_chip_advice"]),
        _obs("cvg-01", "chip_vs_gameweek", ["get_chip_advice"], False, ["get_gameweek_context"]),
        _obs("gw-01", "gameweek_state", ["get_current_gameweek"], True, ["get_current_gameweek"]),
    ]
    matrix = build_confusion_matrix(observations)
    assert matrix["chip_vs_gameweek"]["get_gameweek_context"] == 2
    assert matrix["chip_vs_gameweek"]["get_chip_advice"] == 1
    assert matrix["gameweek_state"]["get_current_gameweek"] == 1


def test_build_confusion_matrix_excludes_harness_exceptions():
    observations = [
        _obs("q1", "advice", ["get_chip_advice"], True, [], exception="boom"),
        _obs("q1", "advice", ["get_chip_advice"], True, ["get_chip_advice"]),
    ]
    matrix = build_confusion_matrix(observations)
    assert matrix["advice"]["get_chip_advice"] == 1
    assert sum(matrix["advice"].values()) == 1


def test_build_confusion_matrix_uses_no_tool_sentinel_when_nothing_was_called():
    observations = [_obs("q1", "advice", ["get_chip_advice"], True, [])]
    matrix = build_confusion_matrix(observations)
    assert matrix["advice"][NO_TOOL] == 1


def test_per_question_hit_rates_matches_the_known_5_of_6_split():
    # Reproduces the exact ratio documented in the measurement task for the
    # pinned question: get_gameweek_context wins 5 times in 6.
    observations = [
        _obs("cvg-01", "chip_vs_gameweek", ["get_chip_advice", "build_squad"], False,
             ["get_gameweek_context"] if i < 5 else ["get_chip_advice"])
        for i in range(6)
    ]
    result = per_question_hit_rates(observations)["cvg-01"]
    assert result["n"] == 6
    assert result["hits_first"] == 1
    assert result["hit_rate_first"] == 1 / 6


def test_per_question_hit_rates_excludes_exceptions_from_n():
    observations = [
        _obs("q1", "advice", ["get_chip_advice"], True, ["get_chip_advice"]),
        _obs("q1", "advice", ["get_chip_advice"], True, [], exception="timeout"),
    ]
    result = per_question_hit_rates(observations)["q1"]
    assert result["n"] == 1
    assert result["hit_rate_first"] == 1.0


def test_control_summary_flags_a_failing_control_as_worst():
    per_question = {
        "ctrl-good": {"control": True, "hit_rate_first": 1.0},
        "ctrl-bad": {"control": True, "hit_rate_first": 0.2},
        "ambiguous-1": {"control": False, "hit_rate_first": 0.5},
    }
    summary = control_summary(per_question)
    assert summary["n_questions"] == 2
    worst_ids = {w["question_id"] for w in summary["worst"]}
    assert "ctrl-bad" in worst_ids
    assert "ambiguous-1" not in worst_ids


def test_worst_offenders_only_considers_ambiguous_questions():
    per_question = {
        "ctrl-bad": {"control": True, "hit_rate_first": 0.0},
        "amb-bad": {"control": False, "hit_rate_first": 0.1},
        "amb-good": {"control": False, "hit_rate_first": 0.9},
    }
    offenders = worst_offenders(per_question, n=5)
    ids = [o["question_id"] for o in offenders]
    assert "ctrl-bad" not in ids
    assert ids[0] == "amb-bad"


def test_count_exceptions_and_total_cost():
    observations = [
        _obs("q1", "advice", ["get_chip_advice"], True, ["get_chip_advice"], cost_usd=0.001),
        _obs("q2", "advice", ["get_chip_advice"], True, [], exception="boom", cost_usd=0.0),
    ]
    assert count_exceptions(observations) == 1
    assert total_cost_usd(observations) == 0.001


def test_load_observations_reads_jsonl(tmp_path: Path):
    path = tmp_path / "obs.jsonl"
    rows = [
        {"question_id": "q1", "family": "advice", "acceptable_tools": ["get_chip_advice"],
         "control": True, "tool_sequence": ["get_chip_advice"], "tool_chosen": "get_chip_advice",
         "exception": None, "cost_usd": 0.001},
        {"question_id": "q2", "family": "advice", "acceptable_tools": ["get_chip_advice"],
         "control": True, "tool_sequence": [], "tool_chosen": None,
         "exception": None, "cost_usd": 0.0},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    loaded = load_observations(path)
    assert len(loaded) == 2
    assert loaded[0]["question_id"] == "q1"
