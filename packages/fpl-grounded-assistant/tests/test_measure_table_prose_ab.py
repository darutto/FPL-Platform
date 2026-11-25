"""No-call checks for scripts/measure_table_prose_ab.py: the 'before' arm is main's prompts, rebuilt in memory."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_table_prose_ab as ab  # noqa: E402


def test_before_arm_rebuilds_mains_pinned_prompts_and_after_differs():
    arms = ab.build_arms()  # aborts (SystemExit) unless every rebuilt prompt matches main's pin
    for key in ("orch", "loop", "evaluator"):
        assert arms["before"][key] != arms["after"][key]
    assert "TOP_N_ASKS" not in arms["before"]["orch"] and "TOP_N_ASKS" in arms["after"]["orch"]
    assert "CARD TURNS" not in arms["before"]["evaluator"] and "CARD TURNS" in arms["after"]["evaluator"]


def test_question_set_is_six_es_and_two_en():
    langs = [q["lang"] for q in ab.QUESTIONS]
    assert langs.count("es") == 6 and langs.count("en") == 2
