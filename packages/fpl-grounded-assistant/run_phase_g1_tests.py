"""
run_phase_g1_tests.py
======================
Phase G1 (mcp-graduation): Adapter parity + per-intent metadata projection tests.

Covers:
    A  Per-intent structured-metadata projection: one assertion per intent
       verifying the correct metadata key is populated from a synthetic
       ask_v2 dict.  Covers all 14 intents (14 assertions).
    B  needs_clarification outcome: clarification_asked == True, all
       structured-meta keys are None (2 assertions).
    C  unsupported outcome: all structured-meta None, final_text carries
       the original message, supported == False (3 assertions).
    D  @unknown_resource branch: resource outcome with no matching resource
       handled correctly — all structured-meta None (2 assertions).
    E  Squad-override application: when squad_context is set AND transfer is
       populated with price_delta > itb, budget_constraint fires and
       final_text is replaced, transfer.budget_constraint == True (3 assertions).
    F  Squad-override chip unavailable: chip not in chips_remaining triggers
       chip_unavailable + final_text replacement (2 assertions).
    G  routing_trace gating: only appears when req.debug == True, never when
       False (2 assertions).
    H  orch_outcome populated when branch == "orchestrator", None otherwise
       (2 assertions).
    I  route_conflict == False always (2 assertions — orchestrator + route branch).
    J  llm_used == True for orchestrator and classifier_rewrite, False for
       route and resource (4 assertions).
    K  review_passed semantics: True when grounded, False when unsupported
       (2 assertions).
    L  route_source derivation: "llm_classifier" for classifier_rewrite,
       "intent_hint" when hint fired, None for plain route (3 assertions).

Total: >= 41 assertions.  Exit code 0 on success, 1 on any failure.

Run from packages/fpl-grounded-assistant::

    python run_phase_g1_tests.py
"""
from __future__ import annotations

import os
import sys
from typing import Any

# Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

# Strip orchestrator env vars so they don't accidentally interfere.
for _k in ("FPL_ORCH_ENABLED", "FPL_ORCH_PROVIDER", "ANTHROPIC_API_KEY",
           "OPENAI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_k, None)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_server import AskRequest, AskResponse  # noqa: E402
from fpl_grounded_assistant.harness_adapter import to_ask_response  # noqa: E402
from fpl_grounded_assistant.final_response import (  # noqa: E402
    TransferMeta,
    ChipAdviceMeta,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_CHIP_ADVICE,
    INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
    INTENT_PLAYER_FORM,
    INTENT_INJURY_LIST,
    INTENT_PRICE_CHANGES,
    INTENT_TEAM_FIXTURE_CALENDAR,
    INTENT_TEAM_SCHEDULE,
    INTENT_POSITION_FIXTURE_RUN,
    INTENT_TRANSFER_SUGGESTION,
    _TOOL_TO_INTENT,
)

# ---------------------------------------------------------------------------
# Test plumbing
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        _failures.append(label)
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _routing_trace(
    branch: str = "route",
    *,
    grounded: bool = True,
    classifier_confidence: float | None = None,
    orchestrator_outcome: str | None = None,
    classification_source: str | None = None,
    orchestrator_called: bool = False,
    classifier_called: bool = False,
    router_hit: bool = True,
) -> dict[str, Any]:
    """Build a minimal routing_trace dict for a given branch."""
    return {
        "branch":                    branch,
        "decision_kind":             "text",
        "decision_outcome":          "ok" if grounded else "unsupported",
        "router_hit":                router_hit,
        "classifier_called":         classifier_called,
        "classifier_confidence":     classifier_confidence,
        "classifier_intent":         None,
        "orchestrator_called":       orchestrator_called,
        "orchestrator_tool_calls":   None,
        "orchestrator_outcome":      orchestrator_outcome,
        "grounded":                  grounded,
        "feature_flag_orch_enabled": False,
        **({"classification_source": classification_source}
           if classification_source is not None else {}),
    }


def _none_meta() -> dict[str, Any]:
    """Return a dict with all 14 structured-metadata keys set to None."""
    return {
        "comparison": None,
        "captain": None,
        "captain_ranking": None,
        "transfer": None,
        "chip": None,
        "fixture_run": None,
        "differential": None,
        "player_form": None,
        "injury_list": None,
        "price_changes": None,
        "team_calendar": None,
        "team_schedule": None,
        "position_fixture_run": None,
        "transfer_suggestion": None,
    }


def _base_ask_v2(
    selected_tool: str | None,
    outcome: str,
    branch: str,
    grounded: bool,
    answer_text: str = "Test answer.",
    extra_routing: dict | None = None,
    **structured_meta_overrides: Any,
) -> dict[str, Any]:
    """Build a synthetic ask_v2 return dict for unit testing."""
    rt = _routing_trace(branch=branch, grounded=grounded)
    if extra_routing:
        rt.update(extra_routing)
    meta = _none_meta()
    meta.update(structured_meta_overrides)
    return {
        "selected_tool": selected_tool,
        "tool_input":    {},
        "raw_output":    {"status": "ok" if outcome == "ok" else outcome},
        "answer_text":   answer_text,
        "outcome":       outcome,
        "kind":          "text",
        "routing_trace": rt,
        **meta,
    }


def _req(*, debug: bool = False, squad_context: dict | None = None) -> AskRequest:
    return AskRequest(question="test question", debug=debug, squad_context=squad_context)


# ---------------------------------------------------------------------------
# --- SECTION A: Per-intent structured metadata projection (14 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- A: Per-intent structured metadata projection ---")

# Intent → tool name mapping (reverse _TOOL_TO_INTENT for convenience)
_INTENT_TO_TOOL: dict[str, str] = {v: k for k, v in _TOOL_TO_INTENT.items()}

# A1: captain_score → captain populated
_d = _base_ask_v2(
    "get_captain_score", "ok", "route", True,
    captain={"web_name": "Salah", "captain_score": 8.5, "tier": "elite",
             "team_short": "LIV", "role_bonus": 1.0, "set_piece_notes": ""},
)
resp = to_ask_response(_d, _req())
check(resp.captain is not None and resp.captain.get("web_name") == "Salah",
      "A1: captain_score → captain populated")

# A2: rank_candidates → captain_ranking populated
_d = _base_ask_v2(
    "rank_captain_candidates", "ok", "route", True,
    captain_ranking=[{"rank": 1, "web_name": "Haaland"}],
)
resp = to_ask_response(_d, _req())
check(resp.captain_ranking is not None and len(resp.captain_ranking) == 1,
      "A2: rank_candidates → captain_ranking populated")

# A3: compare_players → comparison populated
_d = _base_ask_v2(
    "compare_players", "ok", "route", True,
    comparison={"winner": "Salah", "margin": 2.0, "label": "clear", "reasons": []},
)
resp = to_ask_response(_d, _req())
check(resp.comparison is not None and resp.comparison.get("winner") == "Salah",
      "A3: compare_players → comparison populated")

# A4: transfer_advice → transfer populated
_transfer = TransferMeta(
    player_out="Jones", player_in="Salah",
    recommendation="strong_transfer_in", score_delta=3.0,
    price_delta=5, reasons=["Better form"],
)
_d = _base_ask_v2(
    "get_transfer_advice", "ok", "route", True,
    transfer=_transfer,
)
resp = to_ask_response(_d, _req())
check(resp.transfer is not None and resp.transfer.get("player_in") == "Salah",
      "A4: transfer_advice → transfer populated")

# A5: chip_advice → chip populated
_chip = ChipAdviceMeta(
    chip="triple_captain", recommendation="activate", gw=38,
    signal_value=0.9, signal_label="high",
)
_d = _base_ask_v2(
    "get_chip_advice", "ok", "route", True,
    chip=_chip,
)
resp = to_ask_response(_d, _req())
check(resp.chip is not None and resp.chip.get("chip") == "triple_captain",
      "A5: chip_advice → chip populated")

# A6: player_fixture_run → fixture_run populated
_d = _base_ask_v2(
    "get_player_fixture_run", "ok", "route", True,
    fixture_run={"player_name": "Salah", "fixtures": []},
)
resp = to_ask_response(_d, _req())
check(resp.fixture_run is not None and resp.fixture_run.get("player_name") == "Salah",
      "A6: player_fixture_run → fixture_run populated")

# A7: differential_picks → differential populated
_d = _base_ask_v2(
    "get_differential_picks", "ok", "route", True,
    differential={"picks": [], "gw": 30},
)
resp = to_ask_response(_d, _req())
check(resp.differential is not None and "picks" in resp.differential,
      "A7: differential_picks → differential populated")

# A8: player_form → player_form populated
_d = _base_ask_v2(
    "get_player_form", "ok", "route", True,
    player_form={"players": [], "gw_range": "30-34"},
)
resp = to_ask_response(_d, _req())
check(resp.player_form is not None and "players" in resp.player_form,
      "A8: player_form → player_form populated")

# A9: injury_list → injury_list populated
_d = _base_ask_v2(
    "get_injury_list", "ok", "route", True,
    injury_list={"injuries": [], "gw": 30},
)
resp = to_ask_response(_d, _req())
check(resp.injury_list is not None and "injuries" in resp.injury_list,
      "A9: injury_list → injury_list populated")

# A10: price_changes → price_changes populated
_d = _base_ask_v2(
    "get_price_changes", "ok", "route", True,
    price_changes={"risers": [], "fallers": []},
)
resp = to_ask_response(_d, _req())
check(resp.price_changes is not None and "risers" in resp.price_changes,
      "A10: price_changes → price_changes populated")

# A11: team_fixture_calendar → team_calendar populated
_d = _base_ask_v2(
    "get_team_fixture_calendar", "ok", "route", True,
    team_calendar={"team": "LIV", "fixtures": []},
)
resp = to_ask_response(_d, _req())
check(resp.team_calendar is not None and resp.team_calendar.get("team") == "LIV",
      "A11: team_fixture_calendar → team_calendar populated")

# A12: team_schedule → team_schedule populated
_d = _base_ask_v2(
    "get_team_schedule", "ok", "route", True,
    team_schedule={"team": "MCI", "schedule": []},
)
resp = to_ask_response(_d, _req())
check(resp.team_schedule is not None and resp.team_schedule.get("team") == "MCI",
      "A12: team_schedule → team_schedule populated")

# A13: position_fixture_run → position_fixture_run populated
_d = _base_ask_v2(
    "get_position_fixture_run", "ok", "route", True,
    position_fixture_run={"position": "MID", "teams": []},
)
resp = to_ask_response(_d, _req())
check(resp.position_fixture_run is not None
      and resp.position_fixture_run.get("position") == "MID",
      "A13: position_fixture_run → position_fixture_run populated")

# A14: transfer_suggestion → transfer_suggestion populated
_d = _base_ask_v2(
    "get_transfer_suggestion", "ok", "route", True,
    transfer_suggestion={"suggestions": []},
)
resp = to_ask_response(_d, _req())
check(resp.transfer_suggestion is not None and "suggestions" in resp.transfer_suggestion,
      "A14: transfer_suggestion → transfer_suggestion populated")


# ---------------------------------------------------------------------------
# --- SECTION B: needs_clarification outcome (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- B: needs_clarification outcome ---")

_d = {
    "selected_tool": None,
    "tool_input": {},
    "raw_output": {"status": "needs_clarification"},
    "answer_text": "Could you be more specific?",
    "outcome": "needs_clarification",
    "kind": "prompt",
    "prompt_name": "capitan",
    "missing_fields": ["player_name"],
    "errors": [],
    "routing_trace": _routing_trace("prompt", grounded=False, router_hit=False),
    **_none_meta(),
}
resp = to_ask_response(_d, _req())
check(resp.clarification_asked is True,
      "B1: needs_clarification → clarification_asked == True")
check(
    resp.captain is None and resp.comparison is None and resp.transfer is None
    and resp.chip is None and resp.fixture_run is None and resp.differential is None
    and resp.player_form is None and resp.injury_list is None
    and resp.price_changes is None and resp.team_calendar is None
    and resp.team_schedule is None and resp.position_fixture_run is None
    and resp.transfer_suggestion is None and resp.captain_ranking is None,
    "B2: needs_clarification → all 14 structured-meta keys are None",
)


# ---------------------------------------------------------------------------
# --- SECTION C: unsupported outcome (3 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- C: unsupported outcome ---")

_unsup_msg = "Sorry, I cannot answer that."
_d = {
    "selected_tool": None,
    "tool_input": {},
    "raw_output": {"status": "unsupported"},
    "answer_text": _unsup_msg,
    "outcome": "unsupported",
    "kind": "text",
    "suggestions": [],
    "routing_trace": _routing_trace("unsupported", grounded=False, router_hit=False),
    **_none_meta(),
}
resp = to_ask_response(_d, _req())
check(resp.supported is False,
      "C1: unsupported → supported == False")
check(resp.final_text == _unsup_msg,
      "C2: unsupported → final_text carries original message")
check(
    resp.captain is None and resp.comparison is None and resp.transfer is None
    and resp.chip is None and resp.fixture_run is None,
    "C3: unsupported → structured-meta is None",
)


# ---------------------------------------------------------------------------
# --- SECTION D: @unknown_resource branch (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- D: @unknown_resource branch ---")

_d = {
    "selected_tool": None,
    "tool_input": {},
    "raw_output": {"status": "unsupported"},
    "answer_text": "@unknown_resource not found.",
    "outcome": "unsupported",
    "kind": "resource",
    "routing_trace": {
        "branch": "unsupported",
        "decision_kind": "resource",
        "decision_outcome": "unsupported",
        "router_hit": False,
        "classifier_called": False,
        "classifier_confidence": None,
        "classifier_intent": None,
        "orchestrator_called": False,
        "orchestrator_tool_calls": None,
        "orchestrator_outcome": None,
        "grounded": False,
        "feature_flag_orch_enabled": False,
    },
    **_none_meta(),
}
resp = to_ask_response(_d, _req())
check(resp.supported is False,
      "D1: @unknown_resource → supported == False")
check(
    resp.comparison is None and resp.captain is None and resp.transfer is None,
    "D2: @unknown_resource → structured-meta all None",
)


# ---------------------------------------------------------------------------
# --- SECTION E: Squad-override — budget_constraint (3 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- E: Squad-override — budget_constraint ---")

# price_delta=30 (£3.0m) > itb=20 (£2.0m) → budget_constraint fires
_expensive_transfer = TransferMeta(
    player_out="Jones", player_in="Haaland",
    recommendation="strong_transfer_in", score_delta=4.0,
    price_delta=30, reasons=["Fixtures"],
)
_d = _base_ask_v2(
    "get_transfer_advice", "ok", "route", True,
    answer_text="Buy Haaland.",
    transfer=_expensive_transfer,
)
_squad = {"itb": 20, "free_transfers": 2, "chips_remaining": ["wildcard"]}
req_with_squad = _req(squad_context=_squad)
resp = to_ask_response(_d, req_with_squad)

check(resp.transfer is not None and resp.transfer.get("budget_constraint") is True,
      "E1: squad_context budget_constraint → transfer.budget_constraint == True")
check("Budget constraint" in resp.final_text,
      "E2: squad_context budget_constraint → final_text replaced with budget message")
check("Buy Haaland" not in resp.final_text,
      "E3: squad_context budget_constraint → original final_text NOT in response")


# ---------------------------------------------------------------------------
# --- SECTION F: Squad-override — chip_unavailable (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- F: Squad-override — chip_unavailable ---")

_tc_chip = ChipAdviceMeta(
    chip="triple_captain", recommendation="activate", gw=38,
    signal_value=0.9, signal_label="high",
)
_d = _base_ask_v2(
    "get_chip_advice", "ok", "route", True,
    answer_text="Use triple captain now.",
    chip=_tc_chip,
)
_squad_no_tc = {"chips_remaining": ["wildcard", "free_hit"], "itb": 50, "free_transfers": 1}
resp = to_ask_response(_d, _req(squad_context=_squad_no_tc))

check(resp.chip is not None and resp.chip.get("chip_unavailable") is True,
      "F1: chip_unavailable → chip.chip_unavailable == True")
check("Chip unavailable" in resp.final_text,
      "F2: chip_unavailable → final_text replaced with chip unavailable message")


# ---------------------------------------------------------------------------
# --- SECTION G: routing_trace gating (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- G: routing_trace debug gating ---")

_d = _base_ask_v2("get_captain_score", "ok", "route", True,
                  captain={"web_name": "Salah", "captain_score": 8.5, "tier": "elite",
                           "team_short": "LIV", "role_bonus": 1.0, "set_piece_notes": ""})

# debug=False → debug blob should be None
resp_no_debug = to_ask_response(_d, _req(debug=False))
check(resp_no_debug.debug is None,
      "G1: debug=False → debug blob is None (routing_trace NOT exposed)")

# debug=True → debug blob should contain routing_trace
resp_debug = to_ask_response(_d, _req(debug=True))
check(
    resp_debug.debug is not None and "routing_trace" in resp_debug.debug,
    "G2: debug=True → debug blob contains routing_trace",
)


# ---------------------------------------------------------------------------
# --- SECTION H: orch_outcome semantics (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- H: orch_outcome populated only for orchestrator branch ---")

# H1: branch == "orchestrator" → orch_outcome == routing_trace orchestrator_outcome
_orch_rt = _routing_trace(
    "orchestrator", grounded=True,
    orchestrator_called=True, orchestrator_outcome="ok",
)
_d = {
    "selected_tool": "get_captain_score",
    "tool_input": {},
    "raw_output": {"status": "ok"},
    "answer_text": "Orchestrator says captain Salah.",
    "outcome": "ok",
    "kind": "text",
    "routing_trace": _orch_rt,
    **_none_meta(),
    "captain": {"web_name": "Salah", "captain_score": 9.0, "tier": "elite",
                "team_short": "LIV", "role_bonus": 1.5, "set_piece_notes": ""},
}
resp = to_ask_response(_d, _req())
check(resp.orch_outcome == "ok",
      "H1: branch=orchestrator → orch_outcome == routing_trace orchestrator_outcome")

# H2: branch == "route" → orch_outcome is None
_d2 = _base_ask_v2("get_captain_score", "ok", "route", True,
                   captain={"web_name": "Salah", "captain_score": 8.5, "tier": "elite",
                            "team_short": "LIV", "role_bonus": 1.0, "set_piece_notes": ""})
resp2 = to_ask_response(_d2, _req())
check(resp2.orch_outcome is None,
      "H2: branch=route → orch_outcome is None")


# ---------------------------------------------------------------------------
# --- SECTION I: route_conflict always False (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- I: route_conflict always False ---")

_d_route = _base_ask_v2("get_captain_score", "ok", "route", True,
                        captain={"web_name": "Salah", "captain_score": 8.5, "tier": "elite",
                                 "team_short": "LIV", "role_bonus": 1.0, "set_piece_notes": ""})
check(to_ask_response(_d_route, _req()).route_conflict is False,
      "I1: route branch → route_conflict == False")

_d_orch_rt = _routing_trace("orchestrator", grounded=True,
                            orchestrator_called=True, orchestrator_outcome="ok")
_d_orch = {
    "selected_tool": "get_captain_score", "tool_input": {}, "raw_output": {"status": "ok"},
    "answer_text": "Orch captain Salah.", "outcome": "ok", "kind": "text",
    "routing_trace": _d_orch_rt,
    **_none_meta(),
    "captain": {"web_name": "Salah", "captain_score": 9.0, "tier": "elite",
                "team_short": "LIV", "role_bonus": 1.5, "set_piece_notes": ""},
}
check(to_ask_response(_d_orch, _req()).route_conflict is False,
      "I2: orchestrator branch → route_conflict == False")


# ---------------------------------------------------------------------------
# --- SECTION J: llm_used semantics (4 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- J: llm_used semantics ---")

# J1: orchestrator branch → llm_used == True
resp = to_ask_response(_d_orch, _req())
check(resp.llm_used is True,
      "J1: branch=orchestrator → llm_used == True")

# J2: classifier_rewrite branch → llm_used == True
_cr_rt = _routing_trace(
    "classifier_rewrite", grounded=True,
    classifier_called=True, classifier_confidence=0.92,
    classification_source="llm_classifier", router_hit=True,
)
_d_cr = {
    "selected_tool": "get_captain_score", "tool_input": {}, "raw_output": {"status": "ok"},
    "answer_text": "Classifier says captain Salah.", "outcome": "ok", "kind": "text",
    "routing_trace": _cr_rt,
    **_none_meta(),
    "captain": {"web_name": "Salah", "captain_score": 8.0, "tier": "elite",
                "team_short": "LIV", "role_bonus": 1.0, "set_piece_notes": ""},
}
resp = to_ask_response(_d_cr, _req())
check(resp.llm_used is True,
      "J2: branch=classifier_rewrite → llm_used == True")

# J3: route branch → llm_used == False
resp = to_ask_response(_d_route, _req())
check(resp.llm_used is False,
      "J3: branch=route → llm_used == False")

# J4: resource branch → llm_used == False
_d_res = {
    "selected_tool": None, "tool_input": {}, "raw_output": {"status": "ok"},
    "answer_text": "Resource data here.", "outcome": "ok", "kind": "resource",
    "resource": "injuries", "resource_rows": [],
    "routing_trace": {
        "branch": "resource", "decision_kind": "resource", "decision_outcome": "ok",
        "router_hit": False, "classifier_called": False, "classifier_confidence": None,
        "classifier_intent": None, "orchestrator_called": False,
        "orchestrator_tool_calls": None, "orchestrator_outcome": None,
        "grounded": True, "feature_flag_orch_enabled": False,
    },
    **_none_meta(),
}
resp = to_ask_response(_d_res, _req())
check(resp.llm_used is False,
      "J4: branch=resource → llm_used == False")


# ---------------------------------------------------------------------------
# --- SECTION K: review_passed semantics (2 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- K: review_passed semantics ---")

# K1: grounded route → review_passed == True
resp = to_ask_response(_d_route, _req())
check(resp.review_passed is True,
      "K1: grounded route branch → review_passed == True")

# K2: full-ladder miss (unsupported, grounded=False) → review_passed == False
_d_miss = {
    "selected_tool": None, "tool_input": {}, "raw_output": {"status": "unsupported"},
    "answer_text": "Sorry, I cannot help.", "outcome": "unsupported", "kind": "text",
    "routing_trace": _routing_trace("unsupported", grounded=False, router_hit=False),
    **_none_meta(),
}
resp = to_ask_response(_d_miss, _req())
check(resp.review_passed is False,
      "K2: unsupported (grounded=False) → review_passed == False")


# ---------------------------------------------------------------------------
# --- SECTION L: route_source derivation (3 assertions) ---
# ---------------------------------------------------------------------------

print("\n--- L: route_source derivation ---")

# L1: classifier_rewrite → route_source == "llm_classifier"
resp = to_ask_response(_d_cr, _req())
check(resp.route_source == "llm_classifier",
      "L1: classifier_rewrite branch → route_source == 'llm_classifier'")

# L2: intent_hint routing (classification_source == "intent_hint") → "intent_hint"
_hint_rt = {
    "branch": "route",
    "decision_kind": "text",
    "decision_outcome": "ok",
    "router_hit": True,
    "classifier_called": False,
    "classifier_confidence": None,
    "classifier_intent": None,
    "orchestrator_called": False,
    "orchestrator_tool_calls": None,
    "orchestrator_outcome": None,
    "grounded": True,
    "feature_flag_orch_enabled": False,
    "classification_source": "intent_hint",
}
_d_hint = {
    "selected_tool": "get_captain_score", "tool_input": {}, "raw_output": {"status": "ok"},
    "answer_text": "Captain Salah.", "outcome": "ok", "kind": "text",
    "routing_trace": _hint_rt,
    **_none_meta(),
    "captain": {"web_name": "Salah", "captain_score": 8.5, "tier": "elite",
                "team_short": "LIV", "role_bonus": 1.0, "set_piece_notes": ""},
}
resp = to_ask_response(_d_hint, _req())
check(resp.route_source == "intent_hint",
      "L2: classification_source=intent_hint → route_source == 'intent_hint'")

# L3: plain route (no hint, no classifier) → route_source == None
resp = to_ask_response(_d_route, _req())
check(resp.route_source is None,
      "L3: plain route branch → route_source == None")


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
print(f"  TOTAL: {_pass + _fail} assertions  |  PASS: {_pass}  |  FAIL: {_fail}")
if _failures:
    print("\n  Failed assertions:")
    for f in _failures:
        print(f"    - {f}")
print(f"{'='*60}")

sys.exit(0 if _fail == 0 else 1)
