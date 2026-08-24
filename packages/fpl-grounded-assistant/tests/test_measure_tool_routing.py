"""Unit tests for measure_tool_routing.py's pure/offline pieces.

No real ask_orchestrated() call is made anywhere here: run_one() imports
ask_orchestrated lazily from fpl_grounded_assistant.orchestrator inside the
function body, so tests substitute a fake attribute on that already-imported
module rather than hitting any network or requiring API keys.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_tool_routing as mtr  # noqa: E402


def test_cost_usd_zero_tokens_is_zero():
    assert mtr.cost_usd(0, 0, 0) == 0.0


def test_cost_usd_matches_pricing_table():
    # 1M input tokens costs exactly the tabulated input rate.
    assert mtr.cost_usd(1_000_000, 0, 0) == mtr.PRICING_PER_1M["input"]
    assert mtr.cost_usd(0, 1_000_000, 0) == mtr.PRICING_PER_1M["output"]
    assert mtr.cost_usd(0, 0, 1_000_000) == mtr.PRICING_PER_1M["cache_read"]


@dataclass
class _FakeResult:
    outcome: str = "ok"
    tool_chosen: str | None = "get_chip_advice"
    tool_calls_trace: tuple = ()
    tool_call_count: int = 1
    error: str | None = None
    primary_input_tokens: int = 100
    primary_output_tokens: int = 50
    primary_cache_read_tokens: int = 0
    total_tokens: int = 150
    rounds_used: int = 0


def test_extract_tool_sequence_reads_the_full_trace_not_just_first_tool():
    result = _FakeResult(
        tool_chosen="get_chip_advice",
        tool_calls_trace=(
            {"name": "get_current_gameweek"},
            {"name": "get_chip_advice"},
        ),
    )
    assert mtr.extract_tool_sequence(result) == ["get_current_gameweek", "get_chip_advice"]


def test_extract_tool_sequence_falls_back_to_tool_chosen_when_trace_empty():
    result = _FakeResult(tool_chosen="get_captain_score", tool_calls_trace=())
    assert mtr.extract_tool_sequence(result) == ["get_captain_score"]


def test_extract_tool_sequence_empty_when_nothing_was_called():
    result = _FakeResult(tool_chosen=None, tool_calls_trace=())
    assert mtr.extract_tool_sequence(result) == []


def _question(qid: str = "cvg-01") -> dict[str, Any]:
    return {
        "id": qid,
        "family": "chip_vs_gameweek",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "control": False,
        "question": "evalúa mi equipo y qué tan buena idea es el bench boost en la fecha 2",
    }


def test_run_one_records_a_successful_call(monkeypatch):
    fake_result = _FakeResult(
        tool_chosen="get_gameweek_context",
        tool_calls_trace=({"name": "get_gameweek_context"},),
    )

    def _fake_ask_orchestrated(*args, **kwargs):
        return fake_result

    import fpl_grounded_assistant.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "ask_orchestrated", _fake_ask_orchestrated)

    obs = mtr.run_one(_question(), rep_index=0, bootstrap={}, api_key="fake-key")

    assert obs["exception"] is None
    assert obs["question_id"] == "cvg-01"
    assert obs["tool_sequence"] == ["get_gameweek_context"]
    assert obs["outcome"] == "ok"
    assert obs["provider"] == "openai"
    assert obs["model"] == "gpt-5.6-luna"
    assert obs["cost_usd"] > 0


def test_run_one_never_raises_and_captures_exceptions_as_data(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("network exploded")

    import fpl_grounded_assistant.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "ask_orchestrated", _boom)

    obs = mtr.run_one(_question(), rep_index=0, bootstrap={}, api_key="fake-key")

    assert obs["exception"] is not None
    assert "network exploded" in obs["exception"]
    assert obs["outcome"] == "harness_exception"
    assert obs["tool_sequence"] == []
    assert obs["cost_usd"] == 0.0


def test_load_env_file_does_not_override_existing_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=from-file\nOTHER_VAR=hello\n", encoding="utf-8")

    mtr._load_env_file(env_file)

    import os
    assert os.environ["OPENAI_API_KEY"] == "already-set"
    assert os.environ["OTHER_VAR"] == "hello"
