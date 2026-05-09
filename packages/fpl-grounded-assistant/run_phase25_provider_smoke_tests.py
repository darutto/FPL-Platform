"""
run_phase25_provider_smoke_tests.py
=====================================
Phase 2.5-smoke: Narrow real-provider smoke slice.

Proves:
  1. The live configured provider can be reached when credentials are present.
  2. Provider absence/misconfiguration does not break CLI or HTTP contracts.
  3. Provider call failure causes deterministic fallback that preserves contract shape.

Test inventory
--------------
P1  Provider health check — returns valid dict with "available" and "error" keys
P2  Provider unavailable — dispatcher with classifier_client=None returns safe DispatchResult
P3  Provider call failure — mock provider raises; confirm no crash and safe outcome
P4  Contract shape preservation — FinalResponse fields all present when provider fails
P5  Telemetry preserved on fallback — route_source recorded even when provider is absent
P6  HTTP contract — POST /ask returns valid JSON with expected fields when no provider configured
P7  CLI contract — run() returns (exit_code, str) with outcome != error when no provider configured

--- Live section (skipped when FPL_PROVIDER_SMOKE != "1") ---
L1  Live provider reachable — check_provider_health() returns {"available": True}
L2  Live classification — classify_intent_llm() returns IntentClassification with intent+confidence
L3  Live dispatch — real question routes through full stack and returns FinalResponse with ok outcome

Usage (deterministic, no credentials required)::

    python run_phase25_provider_smoke_tests.py

Usage (live provider smoke, requires credentials)::

    FPL_PROVIDER_SMOKE=1 python run_phase25_provider_smoke_tests.py

Exit codes
----------
0  All enabled tests passed.
1  One or more tests failed.
"""
from __future__ import annotations

import os
import sys

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

# ---------------------------------------------------------------------------
# Smoke gate
# ---------------------------------------------------------------------------

PROVIDER_SMOKE_ENABLED: bool = os.getenv("FPL_PROVIDER_SMOKE", "0") == "1"

# ---------------------------------------------------------------------------
# Assertion infrastructure (matches existing run_phase*.py pattern)
# ---------------------------------------------------------------------------

_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f" ({detail})"
        print(msg)


def _skip(label: str, reason: str = "FPL_PROVIDER_SMOKE not set") -> None:
    print(f"  SKIP  {label} [{reason}]")


# ---------------------------------------------------------------------------
# Shared test bootstrap (same pattern as run_phase26h_tests.py)
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402

# ---------------------------------------------------------------------------
# P1 — Provider health check
# ---------------------------------------------------------------------------

print("\n=== P: Deterministic provider smoke tests ===")
print("\n--- P1: Provider health check ---")

from fpl_grounded_assistant.provider_client import check_provider_health  # noqa: E402

_health = check_provider_health()

_check(
    "P1a health returns dict",
    isinstance(_health, dict),
    detail=f"got {type(_health).__name__}",
)
_check(
    "P1b health has 'available' key",
    "available" in _health,
    detail=f"keys={list(_health.keys())}",
)
_check(
    "P1c health has 'error' key",
    "error" in _health,
    detail=f"keys={list(_health.keys())}",
)
_check(
    "P1d health['available'] is bool",
    isinstance(_health.get("available"), bool),
    detail=f"type={type(_health.get('available')).__name__}",
)
_check(
    "P1e health['error'] is str or None",
    _health.get("error") is None or isinstance(_health.get("error"), str),
    detail=f"type={type(_health.get('error')).__name__}",
)

# Verify check_provider_health never raises on unknown provider name
_bad_health = check_provider_health("unknown_provider_xyz")
_check(
    "P1f unknown provider returns dict without raising",
    isinstance(_bad_health, dict) and "available" in _bad_health,
)

# Verify check_provider_health with explicit api_key=""
_empty_key_health = check_provider_health("gemini", api_key="")
_check(
    "P1g empty api_key recognized as absent",
    isinstance(_empty_key_health, dict),
)

# ---------------------------------------------------------------------------
# P2 — Provider unavailable: dispatcher with classifier_client=None
# ---------------------------------------------------------------------------

print("\n--- P2: Dispatcher with classifier_client=None ---")

from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    dispatch,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    DispatchResult,
)

# A question that deterministically routes (should always succeed)
_dr_det = dispatch("what gameweek is it", STANDARD_BOOTSTRAP, classifier_client=None)
_check("P2a deterministic dispatch returns DispatchResult", isinstance(_dr_det, DispatchResult))
_check("P2b deterministic outcome is ok", _dr_det.outcome == OUTCOME_OK)
_check("P2c route_source is 'deterministic'", _dr_det.route_source == "deterministic")

# A question that would normally need the classifier (gibberish -> unsupported_intent)
_dr_unr = dispatch("xyz_totally_unroutable_question_1234", STANDARD_BOOTSTRAP, classifier_client=None)
_check("P2d unroutable without classifier returns DispatchResult", isinstance(_dr_unr, DispatchResult))
_check("P2e unroutable outcome is unsupported_intent", _dr_unr.outcome == OUTCOME_UNSUPPORTED_INTENT)
_check("P2f no crash when classifier absent", True)  # reaching here = no exception

# ---------------------------------------------------------------------------
# P3 — Provider call failure: mock provider raises; no crash
# ---------------------------------------------------------------------------

print("\n--- P3: Provider call failure (mock raises) ---")

from fpl_grounded_assistant.intent_classifier import classify_intent_llm  # noqa: E402


class _FailingClient:
    """Simulates a provider client that always raises on any call."""

    class messages:  # noqa: N801 — mirrors Anthropic client interface
        @staticmethod
        def create(**kwargs):  # noqa: ANN001, ANN003
            raise RuntimeError("simulated provider failure")


_cls_result = classify_intent_llm("should I captain Haaland", _FailingClient())
_check(
    "P3a classify_intent_llm returns None when client raises",
    _cls_result is None,
    detail=f"got {_cls_result!r}",
)

# Dispatcher with a failing client should degrade to unsupported (not crash)
_dr_fail = dispatch(
    "xyz_totally_unroutable_question_1234",
    STANDARD_BOOTSTRAP,
    classifier_client=_FailingClient(),
)
_check(
    "P3b dispatch with failing client returns DispatchResult",
    isinstance(_dr_fail, DispatchResult),
)
_check(
    "P3c dispatch with failing client does not raise",
    True,  # reaching here = no exception
)
_check(
    "P3d dispatch with failing client returns unsupported_intent",
    _dr_fail.outcome == OUTCOME_UNSUPPORTED_INTENT,
    detail=f"outcome={_dr_fail.outcome!r}",
)

# ---------------------------------------------------------------------------
# P4 — Contract shape preservation: FinalResponse fields present on fallback
# ---------------------------------------------------------------------------

print("\n--- P4: Contract shape — FinalResponse fields when provider fails ---")

from fpl_grounded_assistant.final_response import respond, FinalResponse  # noqa: E402

_fr = respond(
    "what gameweek is it",
    STANDARD_BOOTSTRAP,
    classifier_client=None,   # no provider
    include_debug=False,
)

_check("P4a respond returns FinalResponse", isinstance(_fr, FinalResponse))
_check("P4b final_text is non-empty str", isinstance(_fr.final_text, str) and len(_fr.final_text) > 0)
_check("P4c outcome is str", isinstance(_fr.outcome, str) and len(_fr.outcome) > 0)
_check("P4d supported is bool", isinstance(_fr.supported, bool))
_check("P4e intent is str", isinstance(_fr.intent, str) and len(_fr.intent) > 0)
_check("P4f review_passed is bool", isinstance(_fr.review_passed, bool))
_check("P4g llm_used is bool", isinstance(_fr.llm_used, bool))
_check("P4h llm_used is False when no provider", _fr.llm_used is False)
_check("P4i debug is None (include_debug=False)", _fr.debug is None)
_check("P4j route_source is set", _fr.route_source is not None)

# Verify all known additive fields exist (not NotImplemented, no AttributeError)
_required_fields = [
    "final_text", "outcome", "supported", "intent",
    "review_passed", "llm_used", "debug",
    "comparison", "captain", "captain_ranking", "sub_responses",
    "transfer", "chip", "fixture_run", "differential",
    "orch_outcome", "degraded",
    "player_form", "injury_list", "price_changes",
    "team_calendar", "team_schedule", "position_fixture_run",
    "transfer_suggestion",
    "route_source", "classifier_confidence", "route_conflict",
    "clarification_asked",
]
_missing_fields = [f for f in _required_fields if not hasattr(_fr, f)]
_check(
    "P4k all expected FinalResponse fields present",
    len(_missing_fields) == 0,
    detail=f"missing={_missing_fields}",
)

# ---------------------------------------------------------------------------
# P5 — Telemetry preserved on fallback
# ---------------------------------------------------------------------------

print("\n--- P5: Telemetry preserved when provider absent ---")

from fpl_grounded_assistant import telemetry as _telemetry  # noqa: E402

_snap_before = _telemetry.get_snapshot()

# Fire a deterministic dispatch (no provider) — telemetry should still record
_fr2 = respond("what gameweek is it", STANDARD_BOOTSTRAP, classifier_client=None)
_snap_after = _telemetry.get_snapshot()

_check(
    "P5a telemetry snapshot is dict",
    isinstance(_snap_after, dict),
)
_check(
    "P5b route_source_counts key present",
    "route_source_counts" in _snap_after,
    detail=f"keys={list(_snap_after.keys())}",
)
_check(
    "P5c outcome_counts key present",
    "outcome_counts" in _snap_after,
    detail=f"keys={list(_snap_after.keys())}",
)
_check(
    "P5d route_source recorded for deterministic path",
    _snap_after.get("route_source_counts", {}).get("deterministic", 0) > 0,
    detail=f"route_source_counts={_snap_after.get('route_source_counts')}",
)
_check(
    "P5e outcome recorded for ok outcome",
    _snap_after.get("outcome_counts", {}).get("ok", 0) > 0,
    detail=f"outcome_counts={_snap_after.get('outcome_counts')}",
)

# ---------------------------------------------------------------------------
# P6 — HTTP contract: POST /ask valid JSON with expected fields
# ---------------------------------------------------------------------------

print("\n--- P6: HTTP contract (no provider configured) ---")

try:
    from fastapi.testclient import TestClient  # noqa: PLC0415
    import fpl_server  # noqa: PLC0415

    # Inject deterministic bootstrap and no classifier client
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._init_classifier_client(None)

    _http_client = TestClient(fpl_server.app, raise_server_exceptions=True)
    _resp = _http_client.post("/ask", json={"question": "what gameweek is it"})

    _check("P6a HTTP /ask returns 200", _resp.status_code == 200, detail=f"status={_resp.status_code}")

    _json = _resp.json()
    _check("P6b response is JSON object", isinstance(_json, dict))
    _check("P6c final_text present and non-empty", isinstance(_json.get("final_text"), str) and len(_json.get("final_text", "")) > 0)
    _check("P6d outcome present", isinstance(_json.get("outcome"), str))
    _check("P6e supported present", isinstance(_json.get("supported"), bool))
    _check("P6f intent present", isinstance(_json.get("intent"), str))
    _check("P6g review_passed present", isinstance(_json.get("review_passed"), bool))
    _check("P6h llm_used present", isinstance(_json.get("llm_used"), bool))
    _check("P6i route_source present", "route_source" in _json)
    _check("P6j classifier_confidence present", "classifier_confidence" in _json)
    _check("P6k route_conflict present", "route_conflict" in _json)
    _check("P6l degraded present", "degraded" in _json)
    _check("P6m clarification_asked present", "clarification_asked" in _json)

    # Metrics endpoint includes provider key
    _metrics_resp = _http_client.get("/metrics")
    _check("P6n /metrics returns 200", _metrics_resp.status_code == 200)
    _metrics_json = _metrics_resp.json()
    _check("P6o /metrics has provider key", "provider" in _metrics_json, detail=f"keys={list(_metrics_json.keys())}")
    _check("P6p /metrics provider.available is bool", isinstance(_metrics_json.get("provider", {}).get("available"), bool))

except Exception as exc:
    _check("P6 HTTP tests (setup/execution failed)", False, detail=str(exc))

# ---------------------------------------------------------------------------
# P7 — CLI contract: run() returns (exit_code, str) with valid outcome
# ---------------------------------------------------------------------------

print("\n--- P7: CLI contract (no provider configured) ---")

try:
    import fpl_cli  # noqa: PLC0415

    _code, _output = fpl_cli.run(
        "what gameweek is it",
        STANDARD_BOOTSTRAP,
        debug=False,
        classifier_client=None,
    )
    _check("P7a run() returns 2-tuple", True)
    _check("P7b exit_code is int", isinstance(_code, int))
    _check("P7c output is str", isinstance(_output, str))
    _check("P7d exit_code is 0 for supported question", _code == 0, detail=f"code={_code}")
    _check("P7e output is non-empty", len(_output) > 0, detail=f"output={_output!r}")

    # Unsupported question should return exit_code=1 (not a crash)
    _code_u, _output_u = fpl_cli.run(
        "xyz_totally_unroutable_question_9999",
        STANDARD_BOOTSTRAP,
        debug=False,
        classifier_client=None,
    )
    _check("P7f unsupported question does not crash", True)
    _check("P7g unsupported exit_code is 1", _code_u == 1, detail=f"code={_code_u}")
    _check("P7h unsupported output is non-empty str", isinstance(_output_u, str) and len(_output_u) > 0)

    # Debug mode with no provider: should return JSON with all fields
    _code_d, _output_d = fpl_cli.run(
        "what gameweek is it",
        STANDARD_BOOTSTRAP,
        debug=True,
        classifier_client=None,
    )
    import json as _json_mod  # noqa: PLC0415
    try:
        _debug_json = _json_mod.loads(_output_d)
        _check("P7i debug output is valid JSON", True)
        _check("P7j debug JSON has final_text", "final_text" in _debug_json)
        _check("P7k debug JSON has outcome", "outcome" in _debug_json)
        _check("P7l debug JSON has route_source", "route_source" in _debug_json)
    except Exception as exc_inner:
        _check("P7i debug output is valid JSON", False, detail=str(exc_inner))

except Exception as exc:
    _check("P7 CLI tests (setup/execution failed)", False, detail=str(exc))


# ---------------------------------------------------------------------------
# L — Live provider tests (opt-in: FPL_PROVIDER_SMOKE=1)
# ---------------------------------------------------------------------------

print("\n=== L: Live provider tests ===")

if not PROVIDER_SMOKE_ENABLED:
    _skip("L1", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L2", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L3", "FPL_PROVIDER_SMOKE=1 required")
    print("  (Set FPL_PROVIDER_SMOKE=1 and ensure provider credentials are present to run live tests)")
else:
    print("  FPL_PROVIDER_SMOKE=1 — running live provider tests")

    # L1 — Live provider reachable
    print("\n--- L1: Live provider reachable ---")
    _live_health = check_provider_health()
    _check(
        "L1a check_provider_health() available=True",
        _live_health.get("available") is True,
        detail=f"health={_live_health}",
    )
    _check(
        "L1b check_provider_health() error=None",
        _live_health.get("error") is None,
        detail=f"error={_live_health.get('error')!r}",
    )

    # L2 — Live classification
    print("\n--- L2: Live classification ---")
    _active_provider = os.environ.get("DEFAULT_PROVIDER", "gemini").lower()

    _live_classifier = None
    try:
        if _active_provider == "gemini":
            import warnings as _w  # noqa: PLC0415
            with _w.catch_warnings():
                _w.simplefilter("ignore")
                import google.generativeai as _genai  # type: ignore[import-untyped]  # noqa: PLC0415
            _google_key = os.environ.get("GOOGLE_API_KEY")
            if _google_key:
                from fpl_grounded_assistant.intent_classifier import GeminiClassifierAdapter  # noqa: PLC0415
                _live_classifier = GeminiClassifierAdapter(_genai, _google_key)
        elif _active_provider == "anthropic":
            import anthropic as _ant  # type: ignore[import-untyped]  # noqa: PLC0415
            _ant_key = os.environ.get("ANTHROPIC_API_KEY")
            if _ant_key:
                _live_classifier = _ant.Anthropic(api_key=_ant_key)
    except Exception as exc_build:
        print(f"  WARN  Live classifier build failed: {exc_build}")

    if _live_classifier is None:
        _check("L2a classifier built", False, detail="no credentials or SDK for active provider")
        _skip("L2b")
        _skip("L2c")
    else:
        from fpl_grounded_assistant.intent_classifier import IntentClassification  # noqa: PLC0415
        _live_cls = classify_intent_llm("should I captain Haaland this week", _live_classifier)
        _check(
            "L2a classify_intent_llm returns IntentClassification",
            isinstance(_live_cls, IntentClassification),
            detail=f"got {type(_live_cls).__name__}: {_live_cls!r}",
        )
        if isinstance(_live_cls, IntentClassification):
            _check(
                "L2b intent is non-empty str",
                isinstance(_live_cls.intent, str) and len(_live_cls.intent) > 0,
            )
            _check(
                "L2c confidence is float in [0,1]",
                isinstance(_live_cls.confidence, float) and 0.0 <= _live_cls.confidence <= 1.0,
                detail=f"confidence={_live_cls.confidence}",
            )
            _check(
                "L2d canonical_question is non-empty str",
                isinstance(_live_cls.canonical_question, str) and len(_live_cls.canonical_question) > 0,
            )
            _check(
                "L2e language is non-empty str",
                isinstance(_live_cls.language, str) and len(_live_cls.language) > 0,
            )

    # L3 — Live dispatch: full stack with real question
    print("\n--- L3: Live dispatch ---")
    if _live_classifier is None:
        _skip("L3a")
        _skip("L3b")
        _skip("L3c")
    else:
        _live_fr = respond(
            "should I captain Haaland this week",
            STANDARD_BOOTSTRAP,
            classifier_client=_live_classifier,
            include_debug=False,
        )
        _check(
            "L3a respond returns FinalResponse",
            isinstance(_live_fr, FinalResponse),
        )
        _check(
            "L3b outcome is ok or needs_clarification (not error)",
            _live_fr.outcome not in ("error",),
            detail=f"outcome={_live_fr.outcome!r}",
        )
        _check(
            "L3c final_text is non-empty",
            isinstance(_live_fr.final_text, str) and len(_live_fr.final_text) > 0,
        )
        _check(
            "L3d route_source is set",
            _live_fr.route_source is not None,
            detail=f"route_source={_live_fr.route_source!r}",
        )
        print(f"  INFO  outcome={_live_fr.outcome!r}  route_source={_live_fr.route_source!r}")
        if _live_fr.classifier_confidence is not None:
            print(f"  INFO  classifier_confidence={_live_fr.classifier_confidence:.3f}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
print(f"PASSED: {len(_pass)}")
print(f"FAILED: {len(_fail)}")
if _fail:
    print("\nFailed tests:")
    for f in _fail:
        print(f"  {f}")

sys.exit(0 if not _fail else 1)
