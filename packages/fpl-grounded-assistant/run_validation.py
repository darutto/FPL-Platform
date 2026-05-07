"""
run_validation.py
=================
Phase V1 / V2: Cross-Surface Smoke Runner.

Exercises the frozen validation corpus (validation_corpus.py) across
CLI, stateless HTTP, and session surfaces.  Produces two artifacts:

    validation_results.json  — machine-readable per-scenario results
    validation_report.md     — human-readable summary and scenario table

Exit codes
----------
0   All scenarios passed.
1   One or more scenarios failed.

Usage::

    cd packages/fpl-grounded-assistant
    python run_validation.py

    # Suppress artifact writes (useful when called from the test runner):
    python run_validation.py --no-artifacts

Surfaces exercised per scenario
--------------------------------
cli           → fpl_cli.run()
http          → POST /ask via FastAPI TestClient
session_cli   → fpl_cli.run_session() (supports resolver stub)
session_http  → POST /session/{id}/ask via TestClient (deterministic only)

LLM stub protocol
-----------------
Scenarios that require ``requires_stub="comp_llm"`` or ``"ref_llm"`` pass a
pre-built stub client to ``run_session(resolver_client=...)``.

Scenarios that require ``requires_stub="classifier"`` pass a per-scenario
stub client to all relevant surfaces: ``fpl_cli.run(classifier_client=...)``,
``fpl_server._init_classifier_client(stub)`` for HTTP/session_http, and
``fpl_cli.run_session(classifier_client=...)`` for session_cli.  The stub is
built from the scenario's ``classifier_stub_json`` field.  Phase 4l extends
classifier parity to all four surfaces.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB  = lambda name: os.path.join(_PKGS, name)
for _pkg in [
    _HERE,
    _SIB("fpl-api-client"),
    _SIB("fpl-data-core"),
    _SIB("fpl-player-registry"),
    _SIB("fpl-query-tools"),
    _SIB("fpl-tool-contract"),
    _SIB("fpl-tool-runner"),
    _SIB("fpl-captain-engine"),
    _SIB("fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)


# ---------------------------------------------------------------------------
# Imports (after sys.path setup)
# ---------------------------------------------------------------------------

from validation_corpus import VALIDATION_SCENARIOS, ValidationScenario  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import (               # noqa: E402
    STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP, DIFFERENTIAL_BOOTSTRAP,
    DGW_BOOTSTRAP, BGW_BOOTSTRAP, MARGINAL_TRANSFER_BOOTSTRAP,
    PLAYER_FORM_BOOTSTRAP, PRICE_CHANGES_BOOTSTRAP,               # Phase 2.6d
)
from fpl_cli import run as cli_run, run_session as cli_run_session       # noqa: E402
import fpl_server                                                          # noqa: E402
from fastapi.testclient import TestClient                                  # noqa: E402


# ---------------------------------------------------------------------------
# LLM stubs
# ---------------------------------------------------------------------------

class _StubBlock:
    """Mimics a single Anthropic content block."""
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMessage:
    """Mimics an Anthropic API response message."""
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    """Mimics anthropic.Anthropic().messages."""
    def __init__(self, response_json: str) -> None:
        self._response_json = response_json

    def create(self, **kwargs: Any) -> _StubMessage:  # noqa: ANN401
        return _StubMessage(self._response_json)


class _StubAnthropicClient:
    """Minimal stub that satisfies the resolver client interface.

    Used in place of ``anthropic.Anthropic()`` so that LLM-assisted
    resolver paths can be exercised without any network call.
    """
    def __init__(self, response_json: str) -> None:
        self.messages = _StubMessages(response_json)


# Fixed stub responses for the two LLM resolver paths.

COMP_LLM_STUB = _StubAnthropicClient(
    '{"is_comparison_followup": true, "new_player": "Saka", '
    '"confidence": 0.95, "language": "es"}'
)
"""Phase 5f comparison follow-up stub.

Returns: is_comparison_followup=true, new_player='Saka', confidence=0.95.
Expected rewritten question: 'compare Haaland and Saka'.
"""

REF_LLM_STUB = _StubAnthropicClient(
    '{"resolved_query": "Salah", "intent_guess": "captain_score", '
    '"reference_source": "pronoun", "confidence": 0.9, "language": "es"}'
)
"""Phase 4f reference resolver stub.

Returns: resolved_query='Salah', intent_guess='captain_score', confidence=0.9.
Expected rewritten question: 'should I captain Salah'.
"""

_STUB_MAP: dict[str, _StubAnthropicClient] = {
    "comp_llm": COMP_LLM_STUB,
    "ref_llm":  REF_LLM_STUB,
}


def _make_classifier_stub(scenario: "ValidationScenario") -> "_StubAnthropicClient | None":
    """Build a per-scenario classifier stub from ``scenario.classifier_stub_json``.

    Returns ``None`` when the scenario has no classifier stub JSON.
    """
    if scenario.classifier_stub_json is None:
        return None
    return _StubAnthropicClient(scenario.classifier_stub_json)


# ---------------------------------------------------------------------------
# Bootstrap resolver
# ---------------------------------------------------------------------------

def _resolve_bootstrap(name: str) -> dict[str, Any]:
    if name == "ambiguous":
        return AMBIGUOUS_BOOTSTRAP
    if name == "differential":
        return DIFFERENTIAL_BOOTSTRAP
    if name == "dgw":          # Phase 8c: double gameweek
        return DGW_BOOTSTRAP
    if name == "bgw":          # Phase 8c: blank gameweek
        return BGW_BOOTSTRAP
    if name == "marginal_transfer":  # Phase 8e2: Haaland form raised for marginal delta
        return MARGINAL_TRANSFER_BOOTSTRAP
    if name == "player_form":        # Phase 2.6d: element_summary injection
        return PLAYER_FORM_BOOTSTRAP
    if name == "price_changes":      # Phase 2.6d: cost_change_event populated
        return PRICE_CHANGES_BOOTSTRAP
    return STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Per-surface runners
# ---------------------------------------------------------------------------

def run_cli_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via ``fpl_cli.run()`` and return a result dict.

    When ``scenario.requires_stub == "classifier"``, a per-scenario
    ``_StubAnthropicClient`` is built from ``scenario.classifier_stub_json``
    and passed as ``classifier_client`` to both run() calls.
    """
    candidates = list(scenario.candidates_list) if scenario.candidates_list else None
    classifier_stub = (
        _make_classifier_stub(scenario)
        if scenario.requires_stub == "classifier"
        else None
    )

    exit_code, output_text = cli_run(
        scenario.question,
        bootstrap,
        debug=False,
        candidates_list=candidates,
        classifier_client=classifier_stub,
        squad_context=scenario.squad_context,  # Phase 8e1
        intent_hint=scenario.intent_hint,       # Phase 2.7d: routing bias
    )
    # Also run with debug=True to access structured fields and classification_source
    _, debug_output = cli_run(
        scenario.question,
        bootstrap,
        debug=True,
        candidates_list=candidates,
        classifier_client=classifier_stub,
        squad_context=scenario.squad_context,  # Phase 8e1
        intent_hint=scenario.intent_hint,       # Phase 2.7d: routing bias
    )
    debug_body: dict[str, Any] = {}
    try:
        debug_body = json.loads(debug_output)
    except json.JSONDecodeError:
        pass

    debug_bundle: dict[str, Any] = debug_body.get("debug") or {}
    return {
        "surface":                "cli",
        "exit_code":              exit_code,
        "intent":                 debug_body.get("intent"),
        "outcome":                debug_body.get("outcome"),
        "supported":              debug_body.get("supported"),
        "captain":                debug_body.get("captain"),
        "comparison":             debug_body.get("comparison"),
        "captain_ranking":        debug_body.get("captain_ranking"),
        "transfer":               debug_body.get("transfer"),          # Phase 7j
        "chip":                   debug_body.get("chip"),              # Phase 7j
        "fixture_run":            debug_body.get("fixture_run"),       # Phase 7j
        "differential":           debug_body.get("differential"),      # Phase 7j
        "player_form":            debug_body.get("player_form"),       # Phase 2.6d
        "injury_list":            debug_body.get("injury_list"),       # Phase 2.6d
        "price_changes":          debug_body.get("price_changes"),     # Phase 2.6d
        "team_calendar":          debug_body.get("team_calendar"),     # Phase 2.6e
        "team_schedule":          debug_body.get("team_schedule"),          # Phase 2.6e.3
        "position_fixture_run":   debug_body.get("position_fixture_run"),   # Phase 2.6e.4
        "transfer_suggestion":    debug_body.get("transfer_suggestion"),    # Phase 2.6h
        "final_text":             debug_body.get("final_text", output_text),
        "classification_source":  debug_bundle.get("classification_source"),
        # Phase 2.7d: routing audit fields
        "route_source":           debug_body.get("route_source"),
        "classifier_confidence":  debug_body.get("classifier_confidence"),
        "route_conflict":         debug_body.get("route_conflict", False),
    }


def run_http_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via POST /ask (TestClient) and return a result dict.

    When ``scenario.requires_stub == "classifier"``, a per-scenario
    ``_StubAnthropicClient`` is injected via ``fpl_server._init_classifier_client``
    and the request is made with ``debug=True`` so that ``classification_source``
    is present in the response debug bundle.  The client is reset to ``None``
    after the request.
    """
    classifier_stub = (
        _make_classifier_stub(scenario)
        if scenario.requires_stub == "classifier"
        else None
    )

    fpl_server._init_bootstrap(bootstrap)
    if classifier_stub is not None:
        fpl_server._init_classifier_client(classifier_stub)

    client = TestClient(fpl_server.app, raise_server_exceptions=True)

    use_debug = classifier_stub is not None
    payload: dict[str, Any] = {"question": scenario.question, "debug": use_debug}
    if scenario.candidates_list:
        payload["candidates_list"] = list(scenario.candidates_list)
    if scenario.squad_context is not None:  # Phase 8e1
        payload["squad_context"] = scenario.squad_context
    if scenario.intent_hint is not None:    # Phase 2.7d: routing bias
        payload["intent_hint"] = scenario.intent_hint

    resp = client.post("/ask", json=payload)
    body: dict[str, Any] = {}
    try:
        body = resp.json()
    except Exception:
        pass

    if classifier_stub is not None:
        fpl_server._init_classifier_client(None)  # reset

    debug_bundle: dict[str, Any] = body.get("debug") or {}
    return {
        "surface":                "http",
        "http_status":            resp.status_code,
        "intent":                 body.get("intent"),
        "outcome":                body.get("outcome"),
        "supported":              body.get("supported"),
        "captain":                body.get("captain"),
        "comparison":             body.get("comparison"),
        "captain_ranking":        body.get("captain_ranking"),
        "transfer":               body.get("transfer"),               # Phase 7j
        "chip":                   body.get("chip"),                   # Phase 7j
        "fixture_run":            body.get("fixture_run"),            # Phase 7j
        "differential":           body.get("differential"),           # Phase 7j
        "player_form":            body.get("player_form"),            # Phase 2.6d
        "injury_list":            body.get("injury_list"),            # Phase 2.6d
        "price_changes":          body.get("price_changes"),          # Phase 2.6d
        "team_calendar":          body.get("team_calendar"),          # Phase 2.6e
        "team_schedule":          body.get("team_schedule"),              # Phase 2.6e.3
        "position_fixture_run":   body.get("position_fixture_run"),     # Phase 2.6e.4
        "transfer_suggestion":    body.get("transfer_suggestion"),      # Phase 2.6h
        "final_text":             body.get("final_text", ""),
        "classification_source":  debug_bundle.get("classification_source"),
        # Phase 2.7d: routing audit fields
        "route_source":           body.get("route_source"),
        "classifier_confidence":  body.get("classifier_confidence"),
        "route_conflict":         body.get("route_conflict", False),
    }


def run_session_cli_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via ``fpl_cli.run_session()`` and return a result dict
    for the *final* turn.

    Passes ``resolver_client`` when the scenario requires a resolver stub.
    Passes ``classifier_client`` when ``requires_stub == "classifier"`` (Phase 4l).
    Passes ``debug=True`` to capture resolver and classifier metadata.
    """
    resolver_client = _STUB_MAP.get(scenario.requires_stub or "")
    classifier_stub = (
        _make_classifier_stub(scenario)
        if scenario.requires_stub == "classifier"
        else None
    )
    candidates = list(scenario.candidates_list) if scenario.candidates_list else None

    questions = list(scenario.session_prior_turns) + [scenario.question]
    turns = cli_run_session(
        questions,
        bootstrap,
        debug=True,
        resolver_client=resolver_client,
        candidates_list=candidates,
        classifier_client=classifier_stub,
        squad_context=scenario.squad_context,  # Phase 8e1
    )

    last: dict[str, Any] = turns[-1] if turns else {}
    debug_bundle  = last.get("debug") or {}
    resolver_dbg  = debug_bundle.get("resolver") or {}

    return {
        "surface":                "session_cli",
        "intent":                 last.get("intent"),
        "outcome":                last.get("outcome"),
        "supported":              last.get("supported"),
        "captain":                last.get("captain"),
        "comparison":             last.get("comparison"),
        "captain_ranking":        last.get("captain_ranking"),
        "transfer":               last.get("transfer"),               # Phase 7j
        "chip":                   last.get("chip"),                   # Phase 7j
        "fixture_run":            last.get("fixture_run"),            # Phase 7j
        "differential":           last.get("differential"),           # Phase 7j
        "player_form":            last.get("player_form"),            # Phase 2.6d
        "injury_list":            last.get("injury_list"),            # Phase 2.6d
        "price_changes":          last.get("price_changes"),          # Phase 2.6d
        "team_calendar":          last.get("team_calendar"),          # Phase 2.6e
        "team_schedule":          last.get("team_schedule"),              # Phase 2.6e.3
        "position_fixture_run":   last.get("position_fixture_run"),     # Phase 2.6e.4
        "transfer_suggestion":    last.get("transfer_suggestion"),      # Phase 2.6h
        "final_text":             last.get("final_text", ""),
        "resolver_source":        resolver_dbg.get("resolver_source"),
        "rewritten_question":     resolver_dbg.get("rewritten_question"),
        "classification_source":  debug_bundle.get("classification_source"),
        # Phase 2.7d: routing audit fields (available directly on the turn dict)
        "route_source":           last.get("route_source"),
        "classifier_confidence":  last.get("classifier_confidence"),
        "route_conflict":         last.get("route_conflict", False),
    }


def run_session_http_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via the HTTP session API (TestClient) and return a
    result dict for the *final* turn.

    When ``scenario.requires_stub == "classifier"``, a per-scenario
    ``_StubAnthropicClient`` is injected via ``fpl_server._init_classifier_client``
    and turns are requested with ``debug=True`` so that ``classification_source``
    is present in the final response debug bundle.  The client is reset to
    ``None`` after all turns complete.

    Note: resolver_client scenarios (``ref_llm``, ``comp_llm``) are NOT
    supported on this surface — those stubs have no HTTP injection path.
    """
    classifier_stub = (
        _make_classifier_stub(scenario)
        if scenario.requires_stub == "classifier"
        else None
    )

    fpl_server._init_bootstrap(bootstrap)
    fpl_server._clear_sessions()
    if classifier_stub is not None:
        fpl_server._init_classifier_client(classifier_stub)

    client = TestClient(fpl_server.app, raise_server_exceptions=True)

    create_resp = client.post("/session")
    if create_resp.status_code != 200:
        if classifier_stub is not None:
            fpl_server._init_classifier_client(None)
        return {"surface": "session_http", "error": f"create failed: {create_resp.status_code}"}

    session_id = create_resp.json()["session_id"]
    last_body: dict[str, Any] = {}

    use_debug = classifier_stub is not None
    all_turns = list(scenario.session_prior_turns) + [scenario.question]
    n_turns = len(all_turns)
    for i, turn_q in enumerate(all_turns):
        is_final = (i == n_turns - 1)
        ask_payload: dict[str, Any] = {"question": turn_q, "debug": use_debug}
        if scenario.candidates_list:
            ask_payload["candidates_list"] = list(scenario.candidates_list)
        # Phase 8f2: per-turn squad_context support.
        # Prior turns use squad_context_prior_turns (when set); final turn uses squad_context.
        # When squad_context_prior_turns is None, all turns use scenario.squad_context (original behaviour).
        if is_final:
            turn_ctx = scenario.squad_context
        else:
            turn_ctx = (
                scenario.squad_context_prior_turns
                if scenario.squad_context_prior_turns is not None
                else scenario.squad_context
            )
        if turn_ctx is not None:
            ask_payload["squad_context"] = turn_ctx
        # Phase 2.7d: inject intent_hint on final turn only
        if is_final and scenario.intent_hint is not None:
            ask_payload["intent_hint"] = scenario.intent_hint
        r = client.post(f"/session/{session_id}/ask", json=ask_payload)
        if r.status_code == 200:
            last_body = r.json()

    client.delete(f"/session/{session_id}")

    if classifier_stub is not None:
        fpl_server._init_classifier_client(None)  # reset

    debug_bundle: dict[str, Any] = last_body.get("debug") or {}
    return {
        "surface":                "session_http",
        "intent":                 last_body.get("intent"),
        "outcome":                last_body.get("outcome"),
        "supported":              last_body.get("supported"),
        "captain":                last_body.get("captain"),
        "comparison":             last_body.get("comparison"),
        "captain_ranking":        last_body.get("captain_ranking"),
        "transfer":               last_body.get("transfer"),          # Phase 7j
        "chip":                   last_body.get("chip"),              # Phase 7j
        "fixture_run":            last_body.get("fixture_run"),       # Phase 7j
        "differential":           last_body.get("differential"),      # Phase 7j
        "player_form":            last_body.get("player_form"),       # Phase 2.6d
        "injury_list":            last_body.get("injury_list"),       # Phase 2.6d
        "price_changes":          last_body.get("price_changes"),     # Phase 2.6d
        "team_calendar":          last_body.get("team_calendar"),     # Phase 2.6e
        "team_schedule":          last_body.get("team_schedule"),          # Phase 2.6e.3
        "position_fixture_run":   last_body.get("position_fixture_run"), # Phase 2.6e.4
        "transfer_suggestion":    last_body.get("transfer_suggestion"),  # Phase 2.6h
        "final_text":             last_body.get("final_text", ""),
        "classification_source":  debug_bundle.get("classification_source"),
        # Phase 2.7d: routing audit fields
        "route_source":           last_body.get("route_source"),
        "classifier_confidence":  last_body.get("classifier_confidence"),
        "route_conflict":         last_body.get("route_conflict", False),
    }


# ---------------------------------------------------------------------------
# Per-surface dispatcher
# ---------------------------------------------------------------------------

_SURFACE_RUNNERS = {
    "cli":          run_cli_surface,
    "http":         run_http_surface,
    "session_cli":  run_session_cli_surface,
    "session_http": run_session_http_surface,
}


# ---------------------------------------------------------------------------
# Assertion checker
# ---------------------------------------------------------------------------

def _check_scenario_result(
    scenario: ValidationScenario,
    surface_name: str,
    sr: dict[str, Any],
) -> list[str]:
    """Return a list of failure strings (empty == all passed)."""
    failures: list[str] = []

    def fail(msg: str) -> None:
        failures.append(f"[{surface_name}] {msg}")

    # Core contract
    if sr.get("intent") != scenario.expected_intent:
        fail(f"intent: expected={scenario.expected_intent!r}, got={sr.get('intent')!r}")
    if sr.get("outcome") != scenario.expected_outcome:
        fail(f"outcome: expected={scenario.expected_outcome!r}, got={sr.get('outcome')!r}")
    if sr.get("supported") is not scenario.expected_supported:
        fail(f"supported: expected={scenario.expected_supported}, got={sr.get('supported')}")

    # Structured field presence
    if scenario.expect_captain:
        if sr.get("captain") is None:
            fail("captain: expected non-None, got None")
        else:
            cap = sr["captain"]
            if cap.get("tier") not in ("safe", "upside", "differential", "avoid", "low_confidence"):
                fail(f"captain.tier: unexpected value {cap.get('tier')!r}")
    else:
        # For non-captain-score intents, captain should be None/absent
        if scenario.expected_intent != "captain_score" and sr.get("captain") is not None:
            fail("captain: expected None for non-captain turn")

    if scenario.expect_comparison:
        if sr.get("comparison") is None:
            fail("comparison: expected non-None, got None")
        else:
            cmp = sr["comparison"]
            if "winner" not in cmp:
                fail("comparison: missing 'winner' key")
            if "margin" not in cmp:
                fail("comparison: missing 'margin' key")
    else:
        if scenario.expected_intent != "compare_players" and sr.get("comparison") is not None:
            fail("comparison: expected None for non-comparison turn")

    if scenario.expect_captain_ranking:
        cr = sr.get("captain_ranking")
        if cr is None:
            fail("captain_ranking: expected non-None, got None")
        elif not isinstance(cr, list):
            fail(f"captain_ranking: expected list, got {type(cr).__name__}")
        elif len(cr) == 0:
            fail("captain_ranking: expected non-empty list")
        elif cr[0].get("rank") != 1:
            fail(f"captain_ranking[0].rank: expected 1, got {cr[0].get('rank')}")

    # Structured transfer metadata (Phase 7j)
    if scenario.expect_transfer:
        tr = sr.get("transfer")
        if tr is None:
            fail("transfer: expected non-None, got None")
        else:
            for key in ("player_out", "player_in", "recommendation", "score_delta", "price_delta", "reasons"):
                if key not in tr:
                    fail(f"transfer: missing key '{key}'")
            valid_recs = {"transfer_in", "marginal_transfer_in", "hold"}
            if tr.get("recommendation") not in valid_recs:
                fail(f"transfer.recommendation: unexpected value {tr.get('recommendation')!r}")
    else:
        if scenario.expected_intent != "transfer_advice" and sr.get("transfer") is not None:
            fail("transfer: expected None for non-transfer turn")

    # Structured chip metadata (Phase 7j)
    if scenario.expect_chip:
        ch = sr.get("chip")
        if ch is None:
            fail("chip: expected non-None, got None")
        else:
            for key in ("chip", "recommendation", "gw", "signal_value", "signal_label"):
                if key not in ch:
                    fail(f"chip: missing key '{key}'")
            valid_chip_recs = {"conditions_favorable", "conditions_marginal",
                               "conditions_unfavorable", "missing_context"}
            if ch.get("recommendation") not in valid_chip_recs:
                fail(f"chip.recommendation: unexpected value {ch.get('recommendation')!r}")
    else:
        if scenario.expected_intent != "chip_advice" and sr.get("chip") is not None:
            fail("chip: expected None for non-chip turn")

    # Structured fixture run metadata (Phase 7j)
    if scenario.expect_fixture_run:
        fr = sr.get("fixture_run")
        if fr is None:
            fail("fixture_run: expected non-None, got None")
        else:
            for key in ("web_name", "team_short", "position", "horizon", "current_gameweek", "fixtures"):
                if key not in fr:
                    fail(f"fixture_run: missing key '{key}'")
            fixtures = fr.get("fixtures", [])
            if len(fixtures) == 0:
                fail("fixture_run.fixtures: expected non-empty list")
    else:
        if scenario.expected_intent != "player_fixture_run" and sr.get("fixture_run") is not None:
            fail("fixture_run: expected None for non-fixture-run turn")

    # Structured differential picks metadata (Phase 7j)
    if scenario.expect_differential:
        diff = sr.get("differential")
        if diff is None:
            fail("differential: expected non-None, got None")
        else:
            for key in ("ownership_threshold", "top_n", "picks"):
                if key not in diff:
                    fail(f"differential: missing key '{key}'")
            picks = diff.get("picks", [])
            if len(picks) == 0:
                fail("differential.picks: expected non-empty list")
            elif picks[0].get("rank") != 1:
                fail(f"differential.picks[0].rank: expected 1, got {picks[0].get('rank')}")
            else:
                first = picks[0]
                for pkey in ("web_name", "team_short", "position", "captain_score", "ownership", "now_cost"):
                    if pkey not in first:
                        fail(f"differential.picks[0]: missing key '{pkey}'")
    else:
        if scenario.expected_intent != "differential_picks" and sr.get("differential") is not None:
            fail("differential: expected None for non-differential turn")

    # Phase 8f1: explicit squad_context outcome validation
    if scenario.expect_budget_constraint is not None:
        tr = sr.get("transfer")
        if tr is None:
            fail("expect_budget_constraint: transfer is None, cannot check budget_constraint")
        else:
            got_bc = tr.get("budget_constraint")
            if got_bc != scenario.expect_budget_constraint:
                fail(
                    f"transfer.budget_constraint: expected={scenario.expect_budget_constraint}, "
                    f"got={got_bc!r}"
                )

    if scenario.expect_hit_warning is not None:
        tr = sr.get("transfer")
        if tr is None:
            fail("expect_hit_warning: transfer is None, cannot check hit_warning")
        else:
            got_hw = tr.get("hit_warning")
            if got_hw != scenario.expect_hit_warning:
                fail(
                    f"transfer.hit_warning: expected={scenario.expect_hit_warning}, "
                    f"got={got_hw!r}"
                )

    if scenario.expect_chip_unavailable is not None:
        ch = sr.get("chip")
        if ch is None:
            fail("expect_chip_unavailable: chip is None, cannot check chip_unavailable")
        else:
            got_cu = ch.get("chip_unavailable")
            if got_cu != scenario.expect_chip_unavailable:
                fail(
                    f"chip.chip_unavailable: expected={scenario.expect_chip_unavailable}, "
                    f"got={got_cu!r}"
                )

    if scenario.expect_chip_signal_label is not None:
        ch = sr.get("chip")
        if ch is None:
            fail("expect_chip_signal_label: chip is None, cannot check signal_label")
        else:
            got_sl = ch.get("signal_label")
            if got_sl != scenario.expect_chip_signal_label:
                fail(
                    f"chip.signal_label: expected={scenario.expect_chip_signal_label!r}, "
                    f"got={got_sl!r}"
                )

    # Phase 2.6d: player_form, injury_list, price_changes structured metadata
    if scenario.expect_player_form:
        pf = sr.get("player_form")
        if pf is None:
            fail("player_form: expected non-None, got None")
        else:
            for key in ("web_name", "team_short", "position", "n_games", "history"):
                if key not in pf:
                    fail(f"player_form: missing key '{key}'")
    else:
        if scenario.expected_intent != "player_form" and sr.get("player_form") is not None:
            fail("player_form: expected None for non-player-form turn")

    if scenario.expect_injury_list:
        il = sr.get("injury_list")
        if il is None:
            fail("injury_list: expected non-None, got None")
        else:
            for key in ("injured", "doubtful", "other", "total"):
                if key not in il:
                    fail(f"injury_list: missing key '{key}'")
    else:
        if scenario.expected_intent != "injury_list" and sr.get("injury_list") is not None:
            fail("injury_list: expected None for non-injury-list turn")

    if scenario.expect_price_changes:
        pc = sr.get("price_changes")
        if pc is None:
            fail("price_changes: expected non-None, got None")
        else:
            for key in ("risers", "fallers"):
                if key not in pc:
                    fail(f"price_changes: missing key '{key}'")
    else:
        if scenario.expected_intent != "price_changes" and sr.get("price_changes") is not None:
            fail("price_changes: expected None for non-price-changes turn")

    # Phase 2.6e: team_fixture_calendar structured metadata
    if scenario.expect_team_calendar:
        tc = sr.get("team_calendar")
        if tc is None:
            fail("team_calendar: expected non-None, got None")
        else:
            for key in ("mode", "horizon", "top_n", "teams"):
                if key not in tc:
                    fail(f"team_calendar: missing key '{key}'")
            if not isinstance(tc.get("teams"), list):
                fail("team_calendar.teams: expected list")
    else:
        if scenario.expected_intent != "team_fixture_calendar" and sr.get("team_calendar") is not None:
            fail("team_calendar: expected None for non-team-calendar turn")

    # Phase 2.6e.3: team_schedule structured metadata
    if scenario.expect_team_schedule:
        ts = sr.get("team_schedule")
        if ts is None:
            fail("team_schedule: expected non-None, got None")
        else:
            for key in ("team_short", "team_name", "horizon", "fixture_count", "fixtures"):
                if key not in ts:
                    fail(f"team_schedule: missing key '{key}'")
            if not isinstance(ts.get("fixtures"), list):
                fail("team_schedule.fixtures: expected list")
    else:
        if scenario.expected_intent != "team_schedule" and sr.get("team_schedule") is not None:
            fail("team_schedule: expected None for non-team-schedule turn")

    # Phase 2.6e.4: position_fixture_run structured metadata
    if scenario.expect_position_fixture_run:
        pf = sr.get("position_fixture_run")
        if pf is None:
            fail("position_fixture_run: expected non-None, got None")
        else:
            for key in ("position", "position_label", "mode", "horizon", "top_n", "teams"):
                if key not in pf:
                    fail(f"position_fixture_run: missing key '{key}'")
            if not isinstance(pf.get("teams"), list):
                fail("position_fixture_run.teams: expected list")
    else:
        if scenario.expected_intent != "position_fixture_run" and sr.get("position_fixture_run") is not None:
            fail("position_fixture_run: expected None for non-position-fixture-run turn")

    # Phase 2.6h: transfer_suggestion structured metadata
    if scenario.expect_transfer_suggestion:
        ts = sr.get("transfer_suggestion")
        if ts is None:
            fail("transfer_suggestion: expected non-None, got None")
        else:
            for key in ("position", "position_label", "horizon", "top_n", "picks"):
                if key not in ts:
                    fail(f"transfer_suggestion: missing key '{key}'")
            if not isinstance(ts.get("picks"), list):
                fail("transfer_suggestion.picks: expected list")
    else:
        if scenario.expected_intent != "transfer_suggestion" and sr.get("transfer_suggestion") is not None:
            fail("transfer_suggestion: expected None for non-transfer-suggestion turn")

    # Resolver source (session_cli only)
    if surface_name == "session_cli" and scenario.expected_resolver_source is not None:
        got_src = sr.get("resolver_source")
        if got_src != scenario.expected_resolver_source:
            fail(f"resolver_source: expected={scenario.expected_resolver_source!r}, got={got_src!r}")

    # Classification source (all surfaces, Phase 4k/4l)
    if scenario.requires_stub == "classifier":
        got_cls = sr.get("classification_source")
        if got_cls != "llm_classifier":
            fail(f"classification_source: expected='llm_classifier', got={got_cls!r}")

    # Phase 2.7d: routing audit contract assertions
    if scenario.expected_route_source is not None:
        got_rs = sr.get("route_source")
        if got_rs != scenario.expected_route_source:
            fail(
                f"route_source: expected={scenario.expected_route_source!r}, "
                f"got={got_rs!r}"
            )

    if scenario.expect_classifier_confidence_present:
        got_cc = sr.get("classifier_confidence")
        if got_cc is None:
            fail("classifier_confidence: expected non-None, got None")

    return failures


# ---------------------------------------------------------------------------
# Cross-surface parity check
# ---------------------------------------------------------------------------

def _check_cross_surface_parity(
    results_by_surface: dict[str, dict[str, Any]],
) -> list[str]:
    """Check that intent/outcome/supported agree across all surfaces.

    Also checks that structured-field presence (None vs non-None) is
    consistent — if one surface returns a non-null transfer/chip/
    fixture_run/differential, all surfaces should.
    """
    failures: list[str] = []
    surfaces = list(results_by_surface.keys())
    if len(surfaces) < 2:
        return failures

    ref_name = surfaces[0]
    ref = results_by_surface[ref_name]
    for other_name in surfaces[1:]:
        other = results_by_surface[other_name]
        # Core contract fields must match exactly
        for field_name in ("intent", "outcome", "supported"):
            rv = ref.get(field_name)
            ov = other.get(field_name)
            if rv != ov:
                failures.append(
                    f"parity [{ref_name} vs {other_name}] {field_name}: "
                    f"{rv!r} != {ov!r}"
                )
        # Phase 2.7d: route_source must agree across surfaces (exact value match)
        for field_name in ("route_source",):
            rv = ref.get(field_name)
            ov = other.get(field_name)
            if rv != ov:
                failures.append(
                    f"parity [{ref_name} vs {other_name}] {field_name}: "
                    f"{rv!r} != {ov!r}"
                )
        # Structured field presence must agree (None vs non-None)
        for field_name in ("captain", "comparison", "captain_ranking",
                           "transfer", "chip", "fixture_run", "differential",
                           "player_form", "injury_list", "price_changes",  # Phase 2.6d
                           "team_calendar",                                  # Phase 2.6e
                           "team_schedule",                                  # Phase 2.6e.3
                           "position_fixture_run",                           # Phase 2.6e.4
                           "transfer_suggestion"):                           # Phase 2.6h
            rv_present = ref.get(field_name) is not None
            ov_present = other.get(field_name) is not None
            if rv_present != ov_present:
                failures.append(
                    f"parity [{ref_name} vs {other_name}] {field_name} presence: "
                    f"{ref_name}={'non-null' if rv_present else 'null'} "
                    f"{other_name}={'non-null' if ov_present else 'null'}"
                )
    return failures


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_all_scenarios() -> list[dict[str, Any]]:
    """Execute all scenarios and return structured results."""
    results: list[dict[str, Any]] = []

    for scenario in VALIDATION_SCENARIOS:
        bootstrap = _resolve_bootstrap(scenario.bootstrap)
        surface_results: dict[str, dict[str, Any]] = {}
        all_failures: list[str] = []

        for surface_name in scenario.surfaces:
            runner = _SURFACE_RUNNERS.get(surface_name)
            if runner is None:
                all_failures.append(f"Unknown surface: {surface_name}")
                continue
            sr = runner(scenario, bootstrap)
            surface_results[surface_name] = sr
            all_failures.extend(_check_scenario_result(scenario, surface_name, sr))

        # Cross-surface parity
        parity_failures = _check_cross_surface_parity(surface_results)
        all_failures.extend(parity_failures)

        passed = len(all_failures) == 0
        results.append({
            "id":               scenario.id,
            "family":           scenario.family,
            "description":      scenario.description,
            "question":         scenario.question,
            "surfaces_tested":  list(scenario.surfaces),
            "surface_results":  surface_results,
            "expected": {
                "intent":    scenario.expected_intent,
                "outcome":   scenario.expected_outcome,
                "supported": scenario.expected_supported,
            },
            "failures":         all_failures,
            "pass":             passed,
            "notes":            scenario.notes,
        })

    return results


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------

def write_json_artifact(results: list[dict[str, Any]], path: str) -> None:
    """Write machine-readable results to JSON."""
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    artifact = {
        "run_at":         datetime.now(tz=timezone.utc).isoformat(),
        "scenario_count": total,
        "pass_count":     passed,
        "fail_count":     total - passed,
        "scenarios":      results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)


def write_markdown_artifact(results: list[dict[str, Any]], path: str) -> None:
    """Write human-readable Markdown validation report."""
    total  = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed

    lines: list[str] = []
    lines.append("# FPL Grounded Assistant — Validation Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **{total} scenarios** tested")
    lines.append(f"- **{passed} PASS**, **{failed} FAIL**")
    lines.append("")

    # Overview table
    lines.append("## Scenario Overview")
    lines.append("")
    lines.append("| ID | Family | Intent | Outcome | Surfaces | Status |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        status  = "✓ PASS" if r["pass"] else "✗ FAIL"
        surfaces = ", ".join(r["surfaces_tested"])
        exp      = r["expected"]
        lines.append(
            f"| {r['id']} | {r['family']} | {exp['intent']} "
            f"| {exp['outcome']} | {surfaces} | {status} |"
        )

    lines.append("")
    lines.append("## Scenario Details")
    lines.append("")

    for r in results:
        status = "✓ PASS" if r["pass"] else "✗ FAIL"
        lines.append(f"### {r['id']}  ({status})")
        lines.append("")
        lines.append(f"**Family:** {r['family']}  ")
        lines.append(f"**Description:** {r['description']}  ")
        lines.append(f"**Question:** `{r['question']}`  ")
        lines.append(f"**Expected:** intent=`{r['expected']['intent']}` "
                     f"outcome=`{r['expected']['outcome']}` "
                     f"supported=`{r['expected']['supported']}`  ")
        lines.append(f"**Notes:** {r['notes']}")
        lines.append("")

        # Per-surface result
        if r["surface_results"]:
            lines.append("**Surface results:**")
            lines.append("")
            for surf_name, sr in r["surface_results"].items():
                lines.append(f"- `{surf_name}`: "
                              f"intent=`{sr.get('intent')}` "
                              f"outcome=`{sr.get('outcome')}` "
                              f"supported=`{sr.get('supported')}`")
                if surf_name == "session_cli" and sr.get("resolver_source"):
                    lines.append(f"  resolver_source=`{sr.get('resolver_source')}`")
                    if sr.get("rewritten_question"):
                        lines.append(f"  rewritten=`{sr.get('rewritten_question')}`")
                captain_info = sr.get("captain")
                if captain_info:
                    lines.append(f"  captain.tier=`{captain_info.get('tier')}` "
                                  f"captain.role_bonus=`{captain_info.get('role_bonus')}`")
                ranking_info = sr.get("captain_ranking")
                if ranking_info:
                    lines.append(f"  captain_ranking: {len(ranking_info)} entries, "
                                  f"#1={ranking_info[0].get('web_name') if ranking_info else '?'}")
                comparison_info = sr.get("comparison")
                if comparison_info:
                    lines.append(f"  comparison.winner=`{comparison_info.get('winner')}` "
                                  f"comparison.label=`{comparison_info.get('label')}`")
                transfer_info = sr.get("transfer")
                if transfer_info:
                    _tr_flags = ""
                    if transfer_info.get("budget_constraint"):
                        _tr_flags += " budget_constraint=`True`"
                    if transfer_info.get("hit_warning"):
                        _tr_flags += " hit_warning=`True`"
                    lines.append(f"  transfer.player_out=`{transfer_info.get('player_out')}` "
                                  f"transfer.player_in=`{transfer_info.get('player_in')}` "
                                  f"transfer.recommendation=`{transfer_info.get('recommendation')}`"
                                  f"{_tr_flags}")
                chip_info = sr.get("chip")
                if chip_info:
                    _chip_flags = ""
                    if chip_info.get("chip_unavailable"):
                        _chip_flags += " chip_unavailable=`True`"
                    lines.append(f"  chip.chip=`{chip_info.get('chip')}` "
                                  f"chip.recommendation=`{chip_info.get('recommendation')}` "
                                  f"chip.gw=`{chip_info.get('gw')}` "
                                  f"chip.signal_label=`{chip_info.get('signal_label')}`"
                                  f"{_chip_flags}")
                fixture_info = sr.get("fixture_run")
                if fixture_info:
                    fx_list = fixture_info.get("fixtures", [])
                    lines.append(f"  fixture_run.web_name=`{fixture_info.get('web_name')}` "
                                  f"fixture_run.team_short=`{fixture_info.get('team_short')}` "
                                  f"fixture_run.horizon=`{fixture_info.get('horizon')}` "
                                  f"fixtures={len(fx_list)}")
                diff_info = sr.get("differential")
                if diff_info:
                    picks = diff_info.get("picks", [])
                    top = picks[0].get("web_name") if picks else "?"
                    lines.append(f"  differential.ownership_threshold=`{diff_info.get('ownership_threshold')}` "
                                  f"picks={len(picks)} top=`{top}`")
            lines.append("")

        # Failures
        if r["failures"]:
            lines.append("**Failures:**")
            lines.append("")
            for f_msg in r["failures"]:
                lines.append(f"- {f_msg}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `run_validation.py` — "
        "FPL Grounded Assistant Phase V1/V2 validation corpus._"
    )

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run all scenarios, write artifacts, return exit code."""
    parser = argparse.ArgumentParser(prog="run_validation")
    parser.add_argument(
        "--no-artifacts",
        action="store_true",
        default=False,
        help="Skip writing JSON/Markdown output files.",
    )
    args = parser.parse_args(argv)

    results = run_all_scenarios()

    total  = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"Validation: {passed}/{total} scenarios PASS")
    if failed:
        print(f"FAILED scenarios:")
        for r in results:
            if not r["pass"]:
                print(f"  ✗ {r['id']}")
                for f_msg in r["failures"]:
                    print(f"    {f_msg}")
    print(f"{'='*60}\n")

    if not args.no_artifacts:
        json_path = os.path.join(_HERE, "validation_results.json")
        md_path   = os.path.join(_HERE, "validation_report.md")
        write_json_artifact(results, json_path)
        write_markdown_artifact(results, md_path)
        print(f"Artifacts written:")
        print(f"  {json_path}")
        print(f"  {md_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
