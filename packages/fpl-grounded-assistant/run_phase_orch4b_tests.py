"""
run_phase_orch4b_tests.py
=========================
Phase Orch-4b: Structured metadata parity on orchestration success path.

POST-GRADUATION NOTE (G2.c): The Orch-4a gate inside respond() was deleted
in commit 118d43e (G2.a) as part of the mcp-graduation sprint. respond() is
now deterministic-only; FPL_ORCH_ENABLED no longer controls respond() routing.
Sections J through R (respond() flag ON end-to-end tests) have been retired —
they tested Orch-4a gate behavior removed in commit 118d43e. Section S
(deterministic path regression) is retained.

Validates that:
- Extraction helpers are importable and callable.
- Each extraction helper produces the correct metadata type from real tool_output.
- Each extraction helper degrades safely to None on empty/malformed input.
- _orch_result_to_final_response populates metadata for all 7 applicable intents.
- Deterministic respond() path (flag OFF) is byte-equivalent before/after refactor.
- FinalResponse contract shape is unchanged in deterministic mode.

Sections
--------
A  Extraction helper imports and surface
B  _extract_captain_meta             -- unit tests
C  _extract_captain_ranking_meta     -- unit tests
D  _extract_comparison_meta          -- unit tests
E  _extract_transfer_meta            -- unit tests
F  _extract_chip_meta                -- unit tests
G  _extract_fixture_run_meta         -- unit tests
H  _extract_differential_meta        -- unit tests
I  _orch_result_to_final_response    -- intent dispatch and metadata population
S  Regression: deterministic path    -- flag OFF produces correct metadata

G2.c: Sections J-R deleted — tested Orch-4a gate behavior removed in commit 118d43e

Run from packages/fpl-grounded-assistant::

    python run_phase_orch4b_tests.py
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

# Ensure flag is OFF before imports
os.environ.pop("FPL_ORCH_ENABLED", None)
os.environ.pop("FPL_ORCH_PROVIDER", None)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.final_response import (
    FinalResponse,
    CaptainScoreMeta,
    RankedCaptainEntry,
    ComparisonMeta,
    ComparisonPlayerContext,
    TransferMeta,
    ChipAdviceMeta,
    FixtureRunMeta,
    FixtureEntry,
    DifferentialPicksMeta,
    DifferentialEntry,
    _extract_captain_meta,
    _extract_captain_ranking_meta,
    _extract_comparison_meta,
    _extract_comparison_player_ctx,
    _extract_transfer_meta,
    _extract_chip_meta,
    _extract_fixture_run_meta,
    _extract_differential_meta,
    _orch_result_to_final_response,
    respond,
)
from fpl_grounded_assistant.orchestrator import (
    OrchestratorResult,
    OUTCOME_OK as ORCH_OUTCOME_OK,
    DEFAULT_ORCH_MODEL,
)
from fpl_grounded_assistant.dispatcher import (
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,
    INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    OUTCOME_OK as DISP_OUTCOME_OK,
)
from fpl_grounded_assistant.orch_config import ORCH_ENABLED_ENV, ORCH_PROVIDER_ENV
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DIFFERENTIAL_BOOTSTRAP,
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


def _set_flag(value: str | None) -> None:
    if value is None:
        os.environ.pop(ORCH_ENABLED_ENV, None)
    else:
        os.environ[ORCH_ENABLED_ENV] = value


def _make_orch_result(
    tool_name: str,
    tool_output: dict,
    answer: str = "grounded answer",
) -> OrchestratorResult:
    """Build a minimal successful OrchestratorResult for mapper tests."""
    return OrchestratorResult(
        question="test",
        tool_chosen=tool_name,
        tool_args={},
        tool_output=tool_output,
        answer_text=answer,
        llm_used=True,
        model=DEFAULT_ORCH_MODEL,
        outcome=ORCH_OUTCOME_OK,
        error=None,
    )


class _AnthropicToolClient:
    """Mock Anthropic-shaped tool_use client for end-to-end tests."""

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self._tool_name  = tool_name
        self._tool_input = tool_input
        self.messages    = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        _name  = self._tool_name
        _input = dict(self._tool_input)

        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_4b"
            name  = _name
            input = _input

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


# ---------------------------------------------------------------------------
# Reference tool_output dicts (mirrors real run_tool() output for STANDARD_BOOTSTRAP)
# ---------------------------------------------------------------------------

_CAPTAIN_RO = {
    "status":        "ok",
    "web_name":      "Haaland",
    "team_short":    "MCI",
    "captain_score": 54.85,
    "tier":          "upside",
    "role_signals": {
        "set_piece_notes": ["penalty_taker_1"],
        "role_bonus":      5.0,
    },
}

_RANKING_RO = {
    "status": "ok",
    "ranked_candidates": [
        {
            "status": "ok", "rank": 1,
            "web_name": "Salah",    "team_short": "LIV",
            "captain_score": 60.58, "tier": "safe",
            "role_signals": {"set_piece_notes": [], "role_bonus": 0.0},
        },
        {
            "status": "ok", "rank": 2,
            "web_name": "Haaland",  "team_short": "MCI",
            "captain_score": 54.85, "tier": "upside",
            "role_signals": {"set_piece_notes": ["penalty_taker_1"], "role_bonus": 5.0},
        },
    ],
}

_COMPARE_RO = {
    "status":             "ok",
    "winner":             "Salah",
    "margin":             5.73,
    "margin_label":       "moderate",
    "comparison_reasons": ["stronger form (8.5 vs 6.0)"],
    "player_a": {
        "web_name":      "Haaland",
        "position":      "FWD",
        "captain_score": 54.85,
        "position_score": 55.0,
        "role_signals":  {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]},
        "score_inputs":  {"fixture_difficulty": 3, "is_home": True, "effective_fdr": 2.5},
    },
    "player_b": {
        "web_name":      "Salah",
        "position":      "MID",
        "captain_score": 60.58,
        "position_score": 61.0,
        "role_signals":  {"role_bonus": 0.0, "set_piece_notes": []},
        "score_inputs":  {"fixture_difficulty": 2, "is_home": False, "effective_fdr": 2.5},
    },
}

_TRANSFER_RO = {
    "status":           "ok",
    "recommendation":   "transfer_in",
    "score_delta":      24.23,
    "price_delta":      35,
    "transfer_reasons": ["stronger form", "easier fixture"],
    "player_out": {"web_name": "Saka"},
    "player_in":  {"web_name": "Salah"},
}

_CHIP_BB_RO = {
    "status":            "ok",
    "chip":              "bench_boost",
    "recommendation":    "conditions_unfavorable",
    "current_gameweek":  28,
    "signals": {
        "average_fdr_top10": 4.33,
        "top_player_count":  3,
    },
}

_CHIP_TC_RO = {
    "status":           "ok",
    "chip":             "triple_captain",
    "recommendation":   "conditions_marginal",
    "current_gameweek": 28,
    "signals": {"top_captain_score": 83.5},
}

_CHIP_WC_RO = {
    "status":           "ok",
    "chip":             "wildcard",
    "recommendation":   "conditions_unfavorable",
    "current_gameweek": 28,
    "signals": {"current_gameweek": 28},
}

_CHIP_FH_NORMAL_RO = {
    "status":           "ok",
    "chip":             "free_hit",
    "recommendation":   "conditions_unfavorable",
    "current_gameweek": 28,
    "signals": {"gameweek_type": "normal"},
}

_CHIP_FH_DOUBLE_RO = {
    "status":           "ok",
    "chip":             "free_hit",
    "recommendation":   "conditions_favorable",
    "current_gameweek": 28,
    "signals": {"gameweek_type": "double", "dgw_count": 6},
}

_FIXTURE_RO = {
    "status":            "ok",
    "web_name":          "Haaland",
    "team_short":        "MCI",
    "position":          "FWD",
    "horizon":           5,
    "current_gameweek":  28,
    "fixtures": [
        {"gameweek": 28, "opponent_short": "BOU", "is_home": True,  "difficulty": 2},
        {"gameweek": 29, "opponent_short": "ARS", "is_home": False, "difficulty": 4},
        {"gameweek": 30, "opponent_short": "EVE", "is_home": True,  "difficulty": 2},
        {"gameweek": 31, "opponent_short": "TOT", "is_home": False, "difficulty": 3},
        {"gameweek": 32, "opponent_short": "CHE", "is_home": True,  "difficulty": 3},
    ],
}

_DIFF_RO = {
    "status":               "ok",
    "ownership_threshold":  15.0,
    "top_n":                2,
    "picks": [
        {
            "rank": 1, "web_name": "Mbeumo", "team_short": "BRE",
            "position": "FWD", "captain_score": 62.0, "position_score": 63.0,
            "ownership": 4.2, "now_cost": 78, "is_home": True,
        },
        {
            "rank": 2, "web_name": "Palmer", "team_short": "CHE",
            "position": "MID", "captain_score": 58.5, "position_score": 59.0,
            "ownership": 11.0, "now_cost": 105, "is_home": None,
        },
    ],
}


# ---------------------------------------------------------------------------
# Section A: Extraction helper imports
# ---------------------------------------------------------------------------

print("\n=== A: extraction helper imports ===")

ok(callable(_extract_captain_meta),             "A1: _extract_captain_meta callable")
ok(callable(_extract_captain_ranking_meta),     "A2: _extract_captain_ranking_meta callable")
ok(callable(_extract_comparison_meta),          "A3: _extract_comparison_meta callable")
ok(callable(_extract_comparison_player_ctx),    "A4: _extract_comparison_player_ctx callable")
ok(callable(_extract_transfer_meta),            "A5: _extract_transfer_meta callable")
ok(callable(_extract_chip_meta),                "A6: _extract_chip_meta callable")
ok(callable(_extract_fixture_run_meta),         "A7: _extract_fixture_run_meta callable")
ok(callable(_extract_differential_meta),        "A8: _extract_differential_meta callable")


# ---------------------------------------------------------------------------
# Section B: _extract_captain_meta
# ---------------------------------------------------------------------------

print("\n=== B: _extract_captain_meta ===")

_cm = _extract_captain_meta(_CAPTAIN_RO)
ok(_cm is not None,                             "B1: returns non-None")
ok(isinstance(_cm, CaptainScoreMeta),           "B2: returns CaptainScoreMeta")
ok(_cm.web_name == "Haaland",                   "B3: web_name == 'Haaland'")
ok(_cm.team_short == "MCI",                     "B4: team_short == 'MCI'")
ok(abs(_cm.captain_score - 54.85) < 0.01,       "B5: captain_score ~54.85")
ok(_cm.tier == "upside",                        "B6: tier == 'upside'")
ok(abs(_cm.role_bonus - 5.0) < 0.01,            "B7: role_bonus == 5.0")
ok("penalty_taker_1" in _cm.set_piece_notes,    "B8: set_piece_notes includes penalty_taker_1")
ok(isinstance(_cm.set_piece_notes, tuple),      "B9: set_piece_notes is tuple")

# Safe degradation on empty/malformed input
ok(_extract_captain_meta({}) is not None,       "B10: empty dict returns non-None (default fields)")
ok(_extract_captain_meta(None) is None,         "B11: None input returns None")


# ---------------------------------------------------------------------------
# Section C: _extract_captain_ranking_meta
# ---------------------------------------------------------------------------

print("\n=== C: _extract_captain_ranking_meta ===")

_rk = _extract_captain_ranking_meta(_RANKING_RO)
ok(_rk is not None,                             "C1: returns non-None")
ok(isinstance(_rk, tuple),                      "C2: returns tuple")
ok(len(_rk) == 2,                               "C3: 2 ranked entries")
ok(isinstance(_rk[0], RankedCaptainEntry),      "C4: entries are RankedCaptainEntry")
ok(_rk[0].rank == 1,                            "C5: first entry rank == 1")
ok(_rk[0].web_name == "Salah",                  "C6: first entry web_name == 'Salah'")
ok(_rk[1].web_name == "Haaland",               "C7: second entry web_name == 'Haaland'")
ok(abs(_rk[0].captain_score - 60.58) < 0.01,   "C8: first entry captain_score ~60.58")
ok(_rk[1].role_bonus == 5.0,                    "C9: Haaland role_bonus == 5.0")
ok("penalty_taker_1" in _rk[1].set_piece_notes,"C10: Haaland set_piece_notes correct")

# Entries with status != "ok" are filtered out
_rk_mixed = _extract_captain_ranking_meta({
    "status": "ok",
    "ranked_candidates": [
        {"status": "ok", "rank": 1, "web_name": "A", "team_short": "XX",
         "captain_score": 50.0, "tier": "safe", "role_signals": {}},
        {"status": "error", "rank": 2, "web_name": "B"},  # filtered
    ],
})
ok(_rk_mixed is not None and len(_rk_mixed) == 1,
   "C11: error-status entries filtered from ranking")

ok(_extract_captain_ranking_meta({}) is not None and len(_extract_captain_ranking_meta({})) == 0,
   "C12: empty ranked_candidates -> empty tuple (not None)")
ok(_extract_captain_ranking_meta(None) is None,  "C13: None input -> None")


# ---------------------------------------------------------------------------
# Section D: _extract_comparison_meta
# ---------------------------------------------------------------------------

print("\n=== D: _extract_comparison_meta ===")

_cmp = _extract_comparison_meta(_COMPARE_RO)
ok(_cmp is not None,                            "D1: returns non-None")
ok(isinstance(_cmp, ComparisonMeta),            "D2: returns ComparisonMeta")
ok(_cmp.winner == "Salah",                      "D3: winner == 'Salah'")
ok(abs(_cmp.margin - 5.73) < 0.01,             "D4: margin ~5.73")
ok(_cmp.label == "moderate",                    "D5: label == 'moderate'")
ok("stronger form" in (_cmp.reasons[0] if _cmp.reasons else ""),
   "D6: reasons contains form phrase")
ok(isinstance(_cmp.reasons, tuple),             "D7: reasons is tuple")
ok(_cmp.player_a is not None,                   "D8: player_a is populated")
ok(_cmp.player_b is not None,                   "D9: player_b is populated")
ok(isinstance(_cmp.player_a, ComparisonPlayerContext),
   "D10: player_a is ComparisonPlayerContext")
ok(_cmp.player_a.web_name == "Haaland",         "D11: player_a.web_name == 'Haaland'")
ok(_cmp.player_b.web_name == "Salah",           "D12: player_b.web_name == 'Salah'")
ok(_cmp.player_a.role_bonus == 5.0,             "D13: player_a.role_bonus == 5.0")
ok(_cmp.player_a.is_home is True,               "D14: player_a.is_home == True")
ok(_cmp.player_b.is_home is False,              "D15: player_b.is_home == False")
ok(abs(_cmp.player_a.effective_fdr - 2.5) < 0.01,
   "D16: player_a.effective_fdr == 2.5")

# Tie case (winner=None)
_cmp_tie = _extract_comparison_meta({
    "status": "ok", "winner": None, "margin": 0.0,
    "margin_label": "narrow", "comparison_reasons": [],
    "player_a": {}, "player_b": {},
})
ok(_cmp_tie is not None and _cmp_tie.winner is None,
   "D17: winner=None for tied comparison")

ok(_extract_comparison_meta(None) is None,      "D18: None input -> None")


# ---------------------------------------------------------------------------
# Section E: _extract_transfer_meta
# ---------------------------------------------------------------------------

print("\n=== E: _extract_transfer_meta ===")

_tr = _extract_transfer_meta(_TRANSFER_RO)
ok(_tr is not None,                             "E1: returns non-None")
ok(isinstance(_tr, TransferMeta),               "E2: returns TransferMeta")
ok(_tr.player_out == "Saka",                    "E3: player_out == 'Saka'")
ok(_tr.player_in == "Salah",                    "E4: player_in == 'Salah'")
ok(_tr.recommendation == "transfer_in",         "E5: recommendation == 'transfer_in'")
ok(abs(_tr.score_delta - 24.23) < 0.01,         "E6: score_delta ~24.23")
ok(_tr.price_delta == 35,                       "E7: price_delta == 35")
ok(isinstance(_tr.reasons, tuple),              "E8: reasons is tuple")
ok(len(_tr.reasons) == 2,                       "E9: 2 reasons")

# Missing required key -> None
ok(_extract_transfer_meta({"status": "ok"}) is None,
   "E10: missing player_out/player_in -> None")
ok(_extract_transfer_meta(None) is None,        "E11: None input -> None")


# ---------------------------------------------------------------------------
# Section F: _extract_chip_meta
# ---------------------------------------------------------------------------

print("\n=== F: _extract_chip_meta ===")

# bench_boost
_ch_bb = _extract_chip_meta(_CHIP_BB_RO)
ok(_ch_bb is not None,                          "F1: bench_boost returns non-None")
ok(isinstance(_ch_bb, ChipAdviceMeta),          "F2: returns ChipAdviceMeta")
ok(_ch_bb.chip == "bench_boost",                "F3: chip == 'bench_boost'")
ok(_ch_bb.recommendation == "conditions_unfavorable",
   "F4: recommendation correct")
ok(_ch_bb.gw == 28,                             "F5: gw == 28")
ok(_ch_bb.signal_label == "average FDR (top 10)",
   "F6: bench_boost signal_label correct")
ok(abs((_ch_bb.signal_value or 0) - 4.33) < 0.01,
   "F7: bench_boost signal_value ~4.33")

# triple_captain
_ch_tc = _extract_chip_meta(_CHIP_TC_RO)
ok(_ch_tc is not None,                          "F8: triple_captain returns non-None")
ok(_ch_tc.signal_label == "top captain score",  "F9: triple_captain signal_label correct")
ok(abs((_ch_tc.signal_value or 0) - 83.5) < 0.01,
   "F10: triple_captain signal_value ~83.5")

# wildcard
_ch_wc = _extract_chip_meta(_CHIP_WC_RO)
ok(_ch_wc is not None,                          "F11: wildcard returns non-None")
ok(_ch_wc.signal_label == "current gameweek",   "F12: wildcard signal_label correct")

# free_hit normal gameweek
_ch_fh_n = _extract_chip_meta(_CHIP_FH_NORMAL_RO)
ok(_ch_fh_n is not None,                        "F13: free_hit normal returns non-None")
ok(_ch_fh_n.signal_label == "normal gameweek",  "F14: free_hit normal signal_label")
ok(_ch_fh_n.signal_value == 0.0,                "F15: free_hit normal signal_value == 0.0")

# free_hit double gameweek
_ch_fh_d = _extract_chip_meta(_CHIP_FH_DOUBLE_RO)
ok(_ch_fh_d is not None,                        "F16: free_hit double returns non-None")
ok(_ch_fh_d.signal_label == "double gameweek teams",
   "F17: free_hit double signal_label")
ok((_ch_fh_d.signal_value or 0) == 6.0,        "F18: free_hit double signal_value == 6.0")

ok(_extract_chip_meta(None) is None,            "F19: None input -> None")


# ---------------------------------------------------------------------------
# Section G: _extract_fixture_run_meta
# ---------------------------------------------------------------------------

print("\n=== G: _extract_fixture_run_meta ===")

_fx = _extract_fixture_run_meta(_FIXTURE_RO)
ok(_fx is not None,                             "G1: returns non-None")
ok(isinstance(_fx, FixtureRunMeta),             "G2: returns FixtureRunMeta")
ok(_fx.web_name == "Haaland",                   "G3: web_name == 'Haaland'")
ok(_fx.team_short == "MCI",                     "G4: team_short == 'MCI'")
ok(_fx.position == "FWD",                       "G5: position == 'FWD'")
ok(_fx.horizon == 5,                            "G6: horizon == 5")
ok(_fx.current_gameweek == 28,                  "G7: current_gameweek == 28")
ok(len(_fx.fixtures) == 5,                      "G8: 5 fixtures")
ok(isinstance(_fx.fixtures, tuple),             "G9: fixtures is tuple")
ok(isinstance(_fx.fixtures[0], FixtureEntry),   "G10: entries are FixtureEntry")
ok(_fx.fixtures[0].gameweek == 28,              "G11: first fixture GW == 28")
ok(_fx.fixtures[0].opponent_short == "BOU",     "G12: first fixture opponent == 'BOU'")
ok(_fx.fixtures[0].is_home is True,             "G13: first fixture is_home == True")
ok(_fx.fixtures[0].difficulty == 2,             "G14: first fixture difficulty == 2")
ok(_fx.fixtures[1].is_home is False,            "G15: second fixture is_home == False")

ok(_extract_fixture_run_meta({}) is not None,   "G16: empty dict -> non-None (no fixtures)")
ok(_extract_fixture_run_meta(None) is None,     "G17: None input -> None")


# ---------------------------------------------------------------------------
# Section H: _extract_differential_meta
# ---------------------------------------------------------------------------

print("\n=== H: _extract_differential_meta ===")

_di = _extract_differential_meta(_DIFF_RO)
ok(_di is not None,                             "H1: returns non-None")
ok(isinstance(_di, DifferentialPicksMeta),      "H2: returns DifferentialPicksMeta")
ok(_di.ownership_threshold == 15.0,             "H3: ownership_threshold == 15.0")
ok(_di.top_n == 2,                              "H4: top_n == 2")
ok(len(_di.picks) == 2,                         "H5: 2 picks")
ok(isinstance(_di.picks, tuple),                "H6: picks is tuple")
ok(isinstance(_di.picks[0], DifferentialEntry), "H7: entries are DifferentialEntry")
ok(_di.picks[0].web_name == "Mbeumo",           "H8: first pick web_name == 'Mbeumo'")
ok(_di.picks[0].rank == 1,                      "H9: first pick rank == 1")
ok(_di.picks[0].position == "FWD",              "H10: first pick position == 'FWD'")
ok(_di.picks[0].is_home is True,                "H11: first pick is_home == True")
ok(_di.picks[1].is_home is None,                "H12: second pick is_home == None")
ok(_di.picks[0].ownership == 4.2,               "H13: first pick ownership == 4.2")
ok(_di.picks[0].now_cost == 78,                 "H14: first pick now_cost == 78")

ok(_extract_differential_meta({}) is not None,  "H15: empty dict -> non-None (no picks)")
ok(_extract_differential_meta(None) is None,    "H16: None input -> None")


# ---------------------------------------------------------------------------
# Section I: _orch_result_to_final_response — intent dispatch
# ---------------------------------------------------------------------------

print("\n=== I: _orch_result_to_final_response intent dispatch ===")

# I1-I5: captain_score
_r_i1 = _make_orch_result("get_captain_score", _CAPTAIN_RO)
_fr_i1 = _orch_result_to_final_response(_r_i1)
ok(_fr_i1.captain is not None,                  "I1: captain populated for get_captain_score")
ok(isinstance(_fr_i1.captain, CaptainScoreMeta),"I2: captain is CaptainScoreMeta")
ok(_fr_i1.captain.web_name == "Haaland",        "I3: captain.web_name == 'Haaland'")
ok(_fr_i1.comparison is None,                   "I4: comparison is None (not compare_players)")
ok(_fr_i1.captain_ranking is None,              "I5: captain_ranking is None")

# I6-I9: rank_candidates
_r_i2 = _make_orch_result("rank_captain_candidates", _RANKING_RO)
_fr_i2 = _orch_result_to_final_response(_r_i2)
ok(_fr_i2.captain_ranking is not None,          "I6: captain_ranking populated")
ok(len(_fr_i2.captain_ranking) == 2,            "I7: 2 ranked entries")
ok(_fr_i2.captain is None,                      "I8: captain is None (not captain_score)")
ok(_fr_i2.comparison is None,                   "I9: comparison is None")

# I10-I12: compare_players
_r_i3 = _make_orch_result("compare_players", _COMPARE_RO)
_fr_i3 = _orch_result_to_final_response(_r_i3)
ok(_fr_i3.comparison is not None,               "I10: comparison populated for compare_players")
ok(_fr_i3.comparison.winner == "Salah",          "I11: comparison.winner == 'Salah'")
ok(_fr_i3.captain is None,                      "I12: captain is None")

# I13-I15: transfer_advice
_r_i4 = _make_orch_result("get_transfer_advice", _TRANSFER_RO)
_fr_i4 = _orch_result_to_final_response(_r_i4)
ok(_fr_i4.transfer is not None,                 "I13: transfer populated for transfer_advice")
ok(_fr_i4.transfer.player_out == "Saka",        "I14: transfer.player_out == 'Saka'")
ok(_fr_i4.captain is None,                      "I15: captain is None")

# I16-I18: chip_advice
_r_i5 = _make_orch_result("get_chip_advice", _CHIP_BB_RO)
_fr_i5 = _orch_result_to_final_response(_r_i5)
ok(_fr_i5.chip is not None,                     "I16: chip populated for chip_advice")
ok(_fr_i5.chip.chip == "bench_boost",           "I17: chip.chip == 'bench_boost'")
ok(_fr_i5.captain is None,                      "I18: captain is None")

# I19-I21: fixture_run
_r_i6 = _make_orch_result("get_player_fixture_run", _FIXTURE_RO)
_fr_i6 = _orch_result_to_final_response(_r_i6)
ok(_fr_i6.fixture_run is not None,              "I19: fixture_run populated")
ok(len(_fr_i6.fixture_run.fixtures) == 5,       "I20: 5 fixtures in run")
ok(_fr_i6.captain is None,                      "I21: captain is None")

# I22-I24: differential_picks
_r_i7 = _make_orch_result("get_differential_picks", _DIFF_RO)
_fr_i7 = _orch_result_to_final_response(_r_i7)
ok(_fr_i7.differential is not None,             "I22: differential populated")
ok(_fr_i7.differential.top_n == 2,              "I23: differential.top_n == 2")
ok(_fr_i7.captain is None,                      "I24: captain is None")

# I25: only one metadata field populated per result (exclusive dispatch)
for _result, _expected_populated in [
    (_fr_i1, "captain"),
    (_fr_i2, "captain_ranking"),
    (_fr_i3, "comparison"),
    (_fr_i4, "transfer"),
    (_fr_i5, "chip"),
    (_fr_i6, "fixture_run"),
    (_fr_i7, "differential"),
]:
    _meta_fields = ["captain","captain_ranking","comparison","transfer","chip","fixture_run","differential"]
    _non_populated = [f for f in _meta_fields if f != _expected_populated and getattr(_result, f) is not None]
    ok(len(_non_populated) == 0,
       f"I25-exclusive: only '{_expected_populated}' populated, others None")


# G2.c: Sections J through R deleted — tested Orch-4a gate behavior removed in commit 118d43e.
# All sections J-R called respond() with FPL_ORCH_ENABLED=1 and asserted orchestrator-shaped
# output. The gate inside respond() was deleted in G2.a; respond() is now deterministic-only.

# ---------------------------------------------------------------------------
# Section S: Regression — deterministic path produces correct metadata
# ---------------------------------------------------------------------------

print("\n=== S: regression: deterministic path ===")

_set_flag(None)

# Captain score
_r_s1 = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
ok(_r_s1.intent == "captain_score",             "S1: captain_score intent")
ok(_r_s1.outcome == DISP_OUTCOME_OK,            "S2: captain_score outcome ok")
ok(_r_s1.captain is not None,                   "S3: captain populated in deterministic path")
ok(_r_s1.captain.web_name == "Haaland",         "S4: deterministic captain.web_name == 'Haaland'")

# Chip advice
_r_s2 = respond("should I bench boost this week", STANDARD_BOOTSTRAP)
ok(_r_s2.intent == "chip_advice",               "S5: chip_advice intent")
ok(_r_s2.chip is not None,                      "S6: chip populated in deterministic path")
ok(_r_s2.chip.chip == "bench_boost",            "S7: deterministic chip.chip == 'bench_boost'")
ok(_r_s2.chip.signal_label == "average FDR (top 10)",
   "S8: deterministic bench_boost signal_label correct")

# Compare players
_r_s3 = respond("Haaland vs Salah", STANDARD_BOOTSTRAP)
ok(_r_s3.intent == "compare_players",           "S9: compare_players intent")
ok(_r_s3.comparison is not None,                "S10: comparison populated in deterministic path")
ok(_r_s3.comparison.player_a is not None,       "S11: comparison.player_a populated")
ok(_r_s3.comparison.player_b is not None,       "S12: comparison.player_b populated")

# Transfer advice
_r_s4 = respond("should I sell Saka for Salah", STANDARD_BOOTSTRAP)
ok(_r_s4.intent == "transfer_advice",           "S13: transfer_advice intent")
ok(_r_s4.transfer is not None,                  "S14: transfer populated in deterministic path")
ok(_r_s4.transfer.player_out == "Saka",         "S15: deterministic transfer.player_out == 'Saka'")

# Unsupported still unsupported
_r_s5 = respond("who will win the Premier League", STANDARD_BOOTSTRAP)
ok(_r_s5.outcome == "unsupported_intent",       "S16: unsupported_intent unchanged")
ok(not _r_s5.supported,                         "S17: unsupported.supported == False")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 50}")
total = _pass + _fail
print(f"Phase Orch-4b: {_pass}/{total} assertions passed.")
if _fail:
    print(f"               {_fail} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
