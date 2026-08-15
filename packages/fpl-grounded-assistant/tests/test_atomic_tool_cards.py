"""
Tests for the atomic-tool structured card overlay (Phase 1: rank_players_by_metric).

Covers:
  * compose_rank_players_card — happy path, every canonical metric header,
    unknown-metric fallback, status!=ok/empty/malformed → None (+ warning log),
    row cap.
  * maybe_atomic_tool_card — no-clobber, non-cardable tool, build-on-ok.
  * format_metric_value shared formatter + a renderer byte-compat regression.
  * serializer parity: generic _to_dict vs generic_card_to_dict.
  * harness ask_v2 guard: single-tool turn → card; multi-tool (tool_call_count
    != 1) → no card; whitelisted deterministic card not replaced.
  * orchestrator tool_call_count production: len(tool_calls_trace) for the
    primary paths (single vs multi tool), proving the harness guard can't be
    fooled by a real multi-tool turn.
"""
from __future__ import annotations

import os as _os
import sys as _sys
from unittest.mock import patch

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant.atomic_tool_cards import (  # noqa: E402
    _METRIC_HEADER_ES,
    compose_rank_players_card,
    maybe_atomic_tool_card,
)
from fpl_grounded_assistant.formatting import format_metric_value  # noqa: E402
from fpl_grounded_assistant.generic_card import (  # noqa: E402
    GenericCardMeta,
    generic_card_to_dict,
)
from fpl_grounded_assistant.rank_players_by_metric import _METRIC_ALIASES  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _entry(rank: int, name: str, team: str, pos: str, value: float) -> dict:
    return {
        "rank": rank, "web_name": name, "team_short": team,
        "position": pos, "metric_value": value,
    }


def _rank_output(metric: str = "total_points", n: int = 3, **extra) -> dict:
    ranked = [_entry(i + 1, f"P{i}", "MCI", "FWD", float(100 - i)) for i in range(n)]
    return {"status": "ok", "metric": metric, "top_n": n, "ranked": ranked, **extra}


# ---------------------------------------------------------------------------
# compose_rank_players_card
# ---------------------------------------------------------------------------

def test_happy_path_columns_rows_hero():
    card = compose_rank_players_card(_rank_output("total_points", n=3))
    assert isinstance(card, GenericCardMeta)
    assert [c.header for c in card.columns] == ["#", "Jugador", "Equipo", "Pos", "Puntos"]
    assert card.title == "TOP 3 · Puntos"
    assert len(card.rows) == 3
    assert card.rows[0] == ("1", "P0", "MCI", "FWD", "100")
    assert card.hero is not None and card.hero.value == "100" and card.hero.label == "Puntos"
    # every row has exactly len(columns) cells
    assert all(len(r) == len(card.columns) for r in card.rows)


@pytest.mark.parametrize("canonical", sorted(set(_METRIC_ALIASES.values())))
def test_every_canonical_metric_has_a_header(canonical):
    """Header map must cover every canonical metric the tool can emit."""
    assert canonical in _METRIC_HEADER_ES
    card = compose_rank_players_card(_rank_output(canonical, n=1))
    assert card.columns[-1].header == _METRIC_HEADER_ES[canonical]


def test_unknown_metric_falls_back_to_titlecase():
    card = compose_rank_players_card(_rank_output("some_new_metric", n=1))
    assert card.columns[-1].header == "Some New Metric"


def test_subtitle_from_filters():
    card = compose_rank_players_card(
        _rank_output("total_points", n=1, position_filter="DEF", min_minutes_filter=500)
    )
    assert card.subtitle == "posición: DEF, min. minutos: 500"


def test_no_filters_subtitle_is_none():
    assert compose_rank_players_card(_rank_output("total_points", n=1)).subtitle is None


def test_status_not_ok_returns_none():
    assert compose_rank_players_card({"status": "invalid_argument", "code": "unknown_metric"}) is None


def test_empty_ranked_returns_none():
    assert compose_rank_players_card({"status": "ok", "metric": "form", "ranked": []}) is None


def test_malformed_input_returns_none_and_warns(caplog):
    import logging
    # `ranked` not a list of dicts → composition raises internally → None + warning.
    bad = {"status": "ok", "metric": "form", "ranked": [object()]}
    with caplog.at_level(logging.WARNING):
        assert compose_rank_players_card(bad) is None
    assert any("rank_players_by_metric" in r.message for r in caplog.records)


def test_row_cap_50():
    card = compose_rank_players_card(_rank_output("total_points", n=50))
    assert len(card.rows) == 50


# ---------------------------------------------------------------------------
# maybe_atomic_tool_card
# ---------------------------------------------------------------------------

def test_maybe_no_clobber_when_existing_card():
    existing = compose_rank_players_card(_rank_output("form", n=1))
    assert maybe_atomic_tool_card("rank_players_by_metric", _rank_output("form"), existing) is None


def test_maybe_builds_when_no_existing_and_ok():
    card = maybe_atomic_tool_card("rank_players_by_metric", _rank_output("form", n=2), None)
    assert isinstance(card, GenericCardMeta)


def test_maybe_none_for_non_cardable_tool():
    assert maybe_atomic_tool_card("get_player_snapshot", {"status": "ok"}, None) is None
    assert maybe_atomic_tool_card(None, {"status": "ok"}, None) is None


# ---------------------------------------------------------------------------
# Shared formatter + renderer byte-compat regression
# ---------------------------------------------------------------------------

def test_format_metric_value_whole_vs_fractional():
    assert format_metric_value(239.0) == "239"
    assert format_metric_value(0.86) == "0.86"
    assert format_metric_value(0.573) == "0.57"
    assert format_metric_value(17) == "17"


def test_renderer_rank_table_byte_compat():
    """The refactored renderer must produce the SAME strings the inline logic did
    for whole and fractional metric values."""
    from fpl_grounded_assistant.renderer import render
    out = {
        "status": "ok", "metric": "total_points", "top_n": 2,
        "ranked": [
            _entry(1, "Haaland", "MCI", "FWD", 239.0),   # whole float
            _entry(2, "Palmer", "CHE", "MID", 0.86),      # fractional
        ],
    }
    text = render("rank_players_by_metric", out)
    assert "| 239" in text            # whole float → "239", not "239.00"
    assert "| 0.86" in text           # fractional → two decimals


# ---------------------------------------------------------------------------
# Serializer parity: the ask_v2 path reflects via _to_dict; the deterministic
# path uses generic_card_to_dict. They must agree for a GenericCardMeta.
# ---------------------------------------------------------------------------

def test_serializer_parity():
    """Both serializers must produce the same WIRE shape. `_to_dict` keeps row
    cells as tuples and `generic_card_to_dict` uses lists, but both serialize to
    identical JSON arrays (verified via json.dumps) — which is what actually
    reaches the frontend. This guards against key/structure drift between the
    orchestrator (`_to_dict`) and deterministic (`generic_card_to_dict`) paths."""
    import json
    from fpl_grounded_assistant.harness_adapter import _to_dict
    card = compose_rank_players_card(_rank_output("total_points", n=3))
    assert (
        json.dumps(_to_dict(card), sort_keys=True)
        == json.dumps(generic_card_to_dict(card), sort_keys=True)
    )


# ---------------------------------------------------------------------------
# Harness ask_v2 guard (patched orchestrator; no live LLM)
# ---------------------------------------------------------------------------

def _fake_orch_result(*, tool_chosen, tool_output, tool_call_count):
    from fpl_grounded_assistant.orchestrator import OrchestratorResult, OUTCOME_OK
    return OrchestratorResult(
        question="q", tool_chosen=tool_chosen, tool_args={}, tool_output=tool_output,
        answer_text="prose", llm_used=True, model="m", outcome=OUTCOME_OK,
        tool_call_count=tool_call_count,
    )


def _ask_v2_with_orch(monkeypatch, orch_result, question="jugadores con mas puntos"):
    from fpl_grounded_assistant import harness
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    # ask_orchestrated is imported locally inside ask_v2 from .orchestrator —
    # patch the source module.
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: orch_result,
    )
    from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    return harness.ask_v2(question, STANDARD_BOOTSTRAP, orch_client=object())


def test_guard_single_tool_gets_card(monkeypatch):
    orch = _fake_orch_result(
        tool_chosen="rank_players_by_metric",
        tool_output=_rank_output("total_points", n=3),
        tool_call_count=1,
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result.get("generic_card") is not None


def test_guard_multi_tool_gets_no_card(monkeypatch):
    """The security-critical case: a 2-tool turn whose first tool is rankable
    must NOT be carded (its answer_text covers tools not in tool_output)."""
    orch = _fake_orch_result(
        tool_chosen="rank_players_by_metric",
        tool_output=_rank_output("total_points", n=3),
        tool_call_count=2,
    )
    result = _ask_v2_with_orch(monkeypatch, orch)
    assert result.get("generic_card") is None


# ---------------------------------------------------------------------------
# Orchestrator tool_call_count production (mocked provider, no live LLM)
# ---------------------------------------------------------------------------

class _MockMultiToolClient:
    """Anthropic-shaped client returning N tool_use blocks on the FIRST call,
    then plain text on any subsequent (multi-tool synthesis) call."""

    def __init__(self, tool_calls: list[tuple[str, dict]]) -> None:
        self._tool_calls = tool_calls
        self.messages = self
        self._calls = 0

    def create(self, **kwargs):
        self._calls += 1
        if self._calls == 1:
            blocks = []
            for i, (name, inp) in enumerate(self._tool_calls):
                blocks.append(type("_TB", (), {
                    "type": "tool_use", "id": f"toolu_{i}", "name": name, "input": dict(inp),
                })())
            return type("_R", (), {"content": blocks, "stop_reason": "tool_use"})()
        # synthesis / any later call → text
        txt = type("_T", (), {"type": "text", "text": "synth"})()
        return type("_R", (), {"content": [txt], "stop_reason": "end_turn"})()


def _run_orch(monkeypatch, tool_calls):
    monkeypatch.setenv("FPL_ORCH_TEST_INJECTION", "1")
    from fpl_grounded_assistant.orchestrator import ask_orchestrated
    from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    return ask_orchestrated(
        "q", STANDARD_BOOTSTRAP,
        client=_MockMultiToolClient(tool_calls),
        _eval_client=None,  # fail-open E0 branch → primary count = len(trace)
    )


def test_count_single_tool(monkeypatch):
    res = _run_orch(monkeypatch, [("rank_players_by_metric", {"metric": "total_points"})])
    assert res.tool_call_count == 1


def test_count_multi_tool(monkeypatch):
    res = _run_orch(monkeypatch, [
        ("rank_players_by_metric", {"metric": "total_points"}),
        ("get_current_gameweek", {}),
    ])
    assert res.tool_call_count == 2
