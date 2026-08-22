"""Adversarial tests for the agentic-loop experiment legality rubric."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import runpy

from fpl_grounded_assistant.experiment_measurement import (
    SQUAD_QUOTAS,
    classify_user_visible,
    exact_completion,
    grade_structured_output,
    summarize_axis2_by_source,
    validate_decision_payload,
    validate_selection_payload,
)


def _player(player_id: int, position: int, club: int, cost: int = 50) -> dict:
    return {
        "id": player_id,
        "web_name": f"P{player_id}",
        "element_type": position,
        "team": club,
        "now_cost": cost,
        "status": "a",
        "minutes": 900,
    }


def _legal_bootstrap() -> dict:
    players = [
        _player(1, 1, 1), _player(2, 1, 2),
        _player(3, 2, 3), _player(4, 2, 4), _player(5, 2, 5),
        _player(6, 2, 6), _player(7, 2, 7),
        _player(8, 3, 8), _player(9, 3, 9), _player(10, 3, 10),
        _player(11, 3, 1), _player(12, 3, 2),
        _player(13, 4, 3, 155), _player(14, 4, 4), _player(15, 4, 5),
        _player(16, 4, 6), _player(17, 4, 7),
    ]
    return {"elements": players}


def _selection_payload(bootstrap: dict, scenario: str = "Q7") -> dict:
    players = {player["id"]: player for player in bootstrap["elements"]}
    locked = [13]
    if scenario == "Q7":
        primary, alternative, formation = [8, 9, 10, 11], [8, 9, 10, 12], "5-4-1"
    else:
        primary, alternative, formation = [14, 15], [16, 17], "3-4-3"
    locked_cost = sum(players[player_id]["now_cost"] for player_id in locked)
    selection_cost = sum(players[player_id]["now_cost"] for player_id in primary)
    return {
        "locked_players": locked,
        "locked_cost": locked_cost / 10,
        "primary_selection": primary,
        "alternative_selection": alternative,
        "quoted_prices": {
            str(player_id): players[player_id]["now_cost"] / 10 for player_id in primary
        },
        "formation": formation,
        "selection_cost": selection_cost / 10,
        "total_cost_including_locked": (locked_cost + selection_cost) / 10,
        "remaining_budget": (1000 - locked_cost - selection_cost) / 10,
        "ranking_basis": "prior_season_carryover",
    }


def _decision_payload(bootstrap: dict) -> dict:
    players = {player["id"]: player for player in bootstrap["elements"]}
    squad = list(range(1, 16))
    xi = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    return {
        "verdict": "viable",
        "squad_selection": squad,
        "starting_xi": xi,
        "bench_selection": bench,
        "formation": "3-4-3",
        "total_cost": sum(players[player_id]["now_cost"] for player_id in squad) / 10,
        "ranking_basis": "prior_season_carryover",
        "reasons": ["Every bench player has a playable fixture."],
    }


def test_exact_flow_succeeds_on_greedy_counterexample_and_recovers_legal_witness():
    # Fixed squad leaves one GKP and one DEF. Club A already has two fixed
    # players. Greedy takes A's cheap keeper and blocks A's only affordable DEF;
    # exact flow takes the slightly dearer B keeper plus A defender.
    fixed = [
        _player(1, 1, 3, 40),
        _player(2, 2, 4, 40), _player(3, 2, 5, 40),
        _player(4, 2, 6, 40), _player(5, 2, 7, 40),
        _player(6, 3, 1, 40), _player(7, 3, 1, 40),
        _player(8, 3, 8, 40), _player(9, 3, 9, 40), _player(10, 3, 10, 40),
        _player(11, 4, 11, 40), _player(12, 4, 12, 40), _player(13, 4, 13, 40),
    ]
    candidates = [
        _player(14, 1, 1, 40),  # greedy choice, but consumes Club A's final slot
        _player(15, 1, 2, 45),  # exact choice
        _player(16, 2, 1, 40),  # only affordable defender
        _player(17, 2, 14, 100),
    ]
    bootstrap = {"elements": fixed + candidates}
    result = exact_completion(
        bootstrap,
        locked_ids=[player["id"] for player in fixed],
        selected_ids=[],
        budget_tenths=605,
    )
    assert result["completion_exists"] is True
    assert result["completion_ids"] == [15, 16]

    witness = [next(player for player in bootstrap["elements"] if player["id"] == player_id)
               for player_id in result["witness_squad"]]
    assert Counter(player["element_type"] for player in witness) == Counter(SQUAD_QUOTAS)
    assert max(Counter(player["team"] for player in witness).values()) <= 3
    assert sum(player["now_cost"] for player in witness) <= 605


def test_exact_flow_reports_genuine_budget_infeasibility():
    bootstrap = _legal_bootstrap()
    result = exact_completion(bootstrap, [13], [14, 15], budget_tenths=200)
    assert result["completion_exists"] is False


def test_exact_flow_fails_immediately_for_fixed_club_cap_violation():
    bootstrap = {"elements": [_player(index, 3, 1) for index in range(1, 5)]}
    result = exact_completion(bootstrap, [1, 2, 3, 4], [])
    assert result == {
        "completion_exists": False,
        "witness_squad": [],
        "reason": "fixed_club_cap_exceeded",
    }


def test_valid_selection_and_decision_payloads_pass():
    bootstrap = _legal_bootstrap()
    assert validate_selection_payload("Q7", _selection_payload(bootstrap), bootstrap, [13])["valid"]
    assert validate_selection_payload("Q9", _selection_payload(bootstrap, "Q9"), bootstrap, [13])["valid"]
    assert validate_decision_payload(_decision_payload(bootstrap), bootstrap)["valid"]


def test_fluent_but_wrong_selection_fails_budget_and_club_limits():
    bootstrap = _legal_bootstrap()
    payload = _selection_payload(bootstrap)
    # Put Haaland and three selected midfielders at Club 3, and lie about costs.
    for player_id in (8, 9, 10):
        bootstrap["elements"][player_id - 1]["team"] = 3
    payload["selection_cost"] = 1.0
    result = validate_selection_payload("Q7", payload, bootstrap, [13])
    assert result["valid"] is False
    assert any(error.startswith("club_cap") for error in result["errors"])
    assert "budget_reconciliation:selection_cost" in result["errors"]


def test_duplicate_ids_and_partial_price_map_fail():
    bootstrap = _legal_bootstrap()
    payload = _selection_payload(bootstrap)
    payload["primary_selection"] = [8, 8, 10, 11]
    payload["quoted_prices"].pop("10")
    result = validate_selection_payload("Q7", payload, bootstrap, [13])
    assert "duplicate_primary_ids" in result["errors"]
    assert "quoted_prices_keys" in result["errors"]


def test_q6_xi_bench_must_partition_and_bench_must_have_goalkeeper():
    bootstrap = _legal_bootstrap()
    payload = _decision_payload(bootstrap)
    payload["bench_selection"] = [6, 7, 8, 12]
    result = validate_decision_payload(payload, bootstrap)
    assert "xi_bench_partition" in result["errors"]
    assert "bench_composition" in result["errors"]


def test_structured_output_missing_is_not_scored_invalid():
    result = grade_structured_output("Q6", "A substantive prose answer without JSON.", {}, _legal_bootstrap(), [])
    assert result["status"] == "structured_output_missing"
    assert result["valid"] is None


def test_raw_ranking_marks_synthesized_checks_non_comparable_and_is_not_pooled():
    bootstrap = _legal_bootstrap()
    raw_grade = grade_structured_output(
        "Q9",
        "Dos delanteros elegibles.",
        {
            "ranking_basis": "prior_season_carryover",
            "ranked": [{"id": 14}, {"id": 15}],
        },
        bootstrap,
        [13],
    )
    assert raw_grade["source"] == "raw_tool_output"
    assert raw_grade["non_comparable_checks"] == [
        "quoted_prices",
        "budget_arithmetic",
    ]

    summary = summarize_axis2_by_source([
        {"axis2": raw_grade},
        {"axis2": {"source": "json_block", "status": "invalid"}},
        {"axis2": {"source": None, "status": "structured_output_missing"}},
    ])
    assert summary == {
        "raw_tool_output": {raw_grade["status"]: 1},
        "json_block": {"invalid": 1},
        "none": {"structured_output_missing": 1},
    }


def test_driver_prompts_and_axis1_spanish_marker_are_not_mojibake():
    script = Path(__file__).parents[1] / "scripts" / "run_agentic_loop_experiment.py"
    namespace = runpy.run_path(str(script), run_name="agentic_experiment_test")
    prompts = namespace["SCENARIOS"]

    assert prompts["Q6"].startswith("¿hay forma")
    assert "tú" in prompts["Q6"]
    assert "Así" in prompts["Q7"]
    assert "Además" in prompts["Q9"]
    assert not any(marker in text for text in prompts.values() for marker in ("Ã", "Â"))

    classification = classify_user_visible(
        "ok",
        "No encontré una herramienta para responder a esto.",
    )
    assert classification["catastrophic_failure"] is True
    assert "content_free_stub" in classification["reasons"]


# The exact strings observed in the 2026-08-16 field-note probe. The
# price-filtered variant is the one that motivated the whole experiment, and an
# earlier marker list matched only the unfiltered wording, so it scored as a
# substantive answer.
FIELD_NOTE_EMPTY_MESSAGES = (
    "No available midfielders under £7.5m found with positive form in the current bootstrap.",
    "No available midfielders found with positive form in the current bootstrap.",
    "No available forwards found with positive form in the current bootstrap.",
)


def test_axis1_flags_every_observed_empty_message_including_price_filtered():
    for message in FIELD_NOTE_EMPTY_MESSAGES:
        classification = classify_user_visible("ok", message)
        assert classification["catastrophic_failure"] is True, message
        assert "content_free_stub" in classification["reasons"], message


def test_axis1_is_arm_uniform_for_identical_text_and_tool_status():
    """The loop reports ok+flag where the legacy path reports tool_result_error.

    Both must score identically, or arms C/D win the churn metric on outcome
    plumbing rather than on answer quality.
    """
    text = (
        "Los datos disponibles no permiten confirmar minutos ni rol para estos "
        "jugadores en la jornada 1, por lo que no hay base suficiente."
    )
    empty_output = {"status": "empty", "message": "no candidates"}

    legacy_arm = classify_user_visible("tool_result_error", text, empty_output)
    loop_arm = classify_user_visible("ok", text, empty_output)

    assert legacy_arm["catastrophic_failure"] == loop_arm["catastrophic_failure"] is True
    assert legacy_arm["reasons"] == loop_arm["reasons"] == ["tool_status=empty"]


def test_axis1_still_flags_orchestration_level_failures():
    for outcome in ("llm_error", "no_client", "no_tool", "worker_error", "cooldown"):
        classification = classify_user_visible(
            outcome,
            "A sufficiently long answer that would otherwise pass the length check.",
            {"status": "ok"},
        )
        assert classification["catastrophic_failure"] is True, outcome
        assert f"outcome={outcome}" in classification["reasons"], outcome


def test_axis1_passes_a_genuinely_substantive_grounded_answer():
    classification = classify_user_visible(
        "ok",
        "Rice (£7.5m, 3093 minutos, 5.1 ppg) encabeza a los medios por debajo de "
        "£7.5m, seguido de Anderson y Rogers. Base: temporada anterior.",
        {"status": "ok", "ranked": [{"id": 1}]},
    )
    assert classification["catastrophic_failure"] is False
    assert classification["reasons"] == []


def test_artifact_groups_axis2_by_source_instead_of_pooling():
    script = Path(__file__).parents[1] / "scripts" / "run_agentic_loop_experiment.py"
    namespace = runpy.run_path(str(script), run_name="agentic_experiment_render_test")
    observations = []
    for provider in ("anthropic", "gemini"):
        for arm in namespace["ARMS"]:
            for scenario in namespace["SCENARIOS"]:
                source = "raw_tool_output" if arm in {"A", "B"} else "json_block"
                observations.append({
                    "provider": provider,
                    "arm": arm,
                    "scenario": scenario,
                    "repetition": 1,
                    "outcome": "ok",
                    "axis1": {"catastrophic_failure": False, "classification": "substantive_answer"},
                    "axis2": {
                        "source": source,
                        "status": "valid",
                        "errors": [],
                        "non_comparable_checks": (
                            ["quoted_prices", "budget_arithmetic"]
                            if source == "raw_tool_output"
                            else []
                        ),
                    },
                    "axis3": {},
                    "rounds_used": 0,
                    "total_tokens": 0,
                    "usd": 0.0,
                    "tool_calls_trace": [],
                    "tool_chosen": "rank_players_by_metric",
                    "answer_text": "Substantive answer",
                })

    artifact = namespace["_render_artifact"](
        observations,
        bootstrap_path=Path("bootstrap.json"),
        bootstrap_hash="abc",
        captured_at="2026-08-18T00:00:00+00:00",
        pricing={},
        repetitions=1,
    )

    assert '{"raw_tool_output": {"valid": 1}}' in artifact
    assert '{"json_block": {"valid": 1}}' in artifact
    assert "raw_tool_output / valid" in artifact
    assert "Axis 2 non-comparable checks" in artifact
