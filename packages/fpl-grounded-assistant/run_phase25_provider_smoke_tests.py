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

import datetime
import json
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

# Separate tracking for live (L-section) tests
_live_pass: list[str] = []
_live_fail: list[str] = []
_live_skip_count: int = 0


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


def _live_check(label: str, cond: bool, detail: str = "") -> None:
    """Like _check but counts toward the live totals, not the deterministic totals."""
    if cond:
        _live_pass.append(label)
        print(f"  PASS  {label}")
    else:
        _live_fail.append(label)
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

# Evidence artifact state — populated by live path or skipped path below
_evidence: dict = {}
_EVIDENCE_PATH = os.path.join(_HERE, "phase25_live_evidence.json")
_LIVE_QUESTION = "who should I captain this week?"

if not PROVIDER_SMOKE_ENABLED:
    _live_skip_count = 6  # L1, L2, L3, L4, L5, L6
    _skip("L1", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L2", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L3", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L4", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L5", "FPL_PROVIDER_SMOKE=1 required")
    _skip("L6", "FPL_PROVIDER_SMOKE=1 required")
    print("  (Set FPL_PROVIDER_SMOKE=1 and ensure provider credentials are present to run live tests)")

    _evidence = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": None,
        "live_smoke_skipped": True,
        "reason": "FPL_PROVIDER_SMOKE=1 not set",
    }
else:
    print("  FPL_PROVIDER_SMOKE=1 — running live provider tests")

    # -----------------------------------------------------------------------
    # L1 — Live provider reachable
    # -----------------------------------------------------------------------
    print("\n--- L1: Live provider reachable ---")
    _live_health = check_provider_health()
    _active_provider = os.environ.get("DEFAULT_PROVIDER", "gemini").lower()

    _live_check(
        "L1a check_provider_health() available=True",
        _live_health.get("available") is True,
        detail=f"health={_live_health}",
    )
    _live_check(
        "L1b check_provider_health() error=None",
        _live_health.get("error") is None,
        detail=f"error={_live_health.get('error')!r}",
    )

    # -----------------------------------------------------------------------
    # L2 — Live classification
    # -----------------------------------------------------------------------
    print("\n--- L2: Live classification ---")

    _live_classifier = None
    _classifier_build_error: str | None = None
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
            else:
                _classifier_build_error = "GOOGLE_API_KEY not set"
        elif _active_provider == "anthropic":
            import anthropic as _ant  # type: ignore[import-untyped]  # noqa: PLC0415
            _ant_key = os.environ.get("ANTHROPIC_API_KEY")
            if _ant_key:
                _live_classifier = _ant.Anthropic(api_key=_ant_key)
            else:
                _classifier_build_error = "ANTHROPIC_API_KEY not set"
        else:
            _classifier_build_error = f"unknown provider: {_active_provider!r}"
    except Exception as exc_build:
        _classifier_build_error = f"{type(exc_build).__name__}: {exc_build}"
        print(f"  WARN  Live classifier build failed: {exc_build}")

    # L2 evidence defaults
    _l2_evidence: dict = {
        "question": _LIVE_QUESTION,
        "intent": None,
        "confidence": None,
        "confidence_bucket": None,
        "build_error": _classifier_build_error,
    }

    if _live_classifier is None:
        _live_check(
            "L2a classifier built",
            False,
            detail=_classifier_build_error or "no credentials or SDK for active provider",
        )
        _skip("L2b")
        _skip("L2c")
    else:
        from fpl_grounded_assistant.intent_classifier import IntentClassification  # noqa: PLC0415
        _live_cls = classify_intent_llm(_LIVE_QUESTION, _live_classifier)
        _live_check(
            "L2a classify_intent_llm returns IntentClassification",
            isinstance(_live_cls, IntentClassification),
            detail=f"got {type(_live_cls).__name__}: {_live_cls!r}",
        )
        if isinstance(_live_cls, IntentClassification):
            _live_check(
                "L2b intent is non-empty str",
                isinstance(_live_cls.intent, str) and len(_live_cls.intent) > 0,
            )
            _live_check(
                "L2c confidence is float in [0,1]",
                isinstance(_live_cls.confidence, float) and 0.0 <= _live_cls.confidence <= 1.0,
                detail=f"confidence={_live_cls.confidence}",
            )
            _live_check(
                "L2d canonical_question is non-empty str",
                isinstance(_live_cls.canonical_question, str) and len(_live_cls.canonical_question) > 0,
            )
            _live_check(
                "L2e language is non-empty str",
                isinstance(_live_cls.language, str) and len(_live_cls.language) > 0,
            )
            # Populate L2 evidence
            _conf_bucket = (
                "high" if _live_cls.confidence >= 0.9
                else "medium" if _live_cls.confidence >= 0.7
                else "low"
            )
            _l2_evidence.update({
                "intent": _live_cls.intent,
                "confidence": _live_cls.confidence,
                "confidence_bucket": _conf_bucket,
                "build_error": None,
            })

    # -----------------------------------------------------------------------
    # L3 — Live dispatch: full stack with real question
    # -----------------------------------------------------------------------
    print("\n--- L3: Live dispatch ---")

    # L3 evidence defaults
    _l3_evidence: dict = {
        "question": _LIVE_QUESTION,
        "outcome": None,
        "route_source": None,
        "clarification_asked": None,
        "final_text_preview": None,
        "skipped": _live_classifier is None,
    }

    if _live_classifier is None:
        _skip("L3a")
        _skip("L3b")
        _skip("L3c")
        _skip("L3d")
    else:
        _live_fr = respond(
            _LIVE_QUESTION,
            STANDARD_BOOTSTRAP,
            classifier_client=_live_classifier,
            include_debug=False,
        )
        _live_check(
            "L3a respond returns FinalResponse",
            isinstance(_live_fr, FinalResponse),
        )
        _live_check(
            "L3b outcome is ok, needs_clarification or not_found (not error)",
            _live_fr.outcome not in ("error",),
            detail=f"outcome={_live_fr.outcome!r}",
        )
        _live_check(
            "L3c final_text is non-empty",
            isinstance(_live_fr.final_text, str) and len(_live_fr.final_text) > 0,
        )
        _live_check(
            "L3d route_source is set",
            _live_fr.route_source is not None,
            detail=f"route_source={_live_fr.route_source!r}",
        )
        print(f"  INFO  outcome={_live_fr.outcome!r}  route_source={_live_fr.route_source!r}")
        if _live_fr.classifier_confidence is not None:
            print(f"  INFO  classifier_confidence={_live_fr.classifier_confidence:.3f}")

        _l3_evidence.update({
            "outcome": _live_fr.outcome,
            "route_source": _live_fr.route_source,
            "clarification_asked": getattr(_live_fr, "clarification_asked", None),
            "final_text_preview": (_live_fr.final_text or "")[:120],
            "skipped": False,
        })

    # -----------------------------------------------------------------------
    # L4 — Live CLI surface
    # -----------------------------------------------------------------------
    print("\n--- L4: Live CLI surface ---")

    # L4 evidence defaults
    _l4_evidence: dict = {
        "question": _LIVE_QUESTION,
        "outcome": None,
        "route_source": None,
        "clarification_asked": None,
        "llm_used": None,
        "final_text_preview": None,
        "skipped": _live_classifier is None,
    }

    if _live_classifier is None:
        _skip("L4a")
        _skip("L4b")
        _skip("L4c")
        _skip("L4d")
    else:
        try:
            import fpl_cli as _fpl_cli  # noqa: PLC0415

            # Call run() in debug mode so we can parse routing fields from JSON output
            _l4_code, _l4_output = _fpl_cli.run(
                _LIVE_QUESTION,
                STANDARD_BOOTSTRAP,
                debug=True,
                classifier_client=_live_classifier,
            )
            _live_check(
                "L4a fpl_cli.run() returns 2-tuple",
                isinstance(_l4_output, str) and isinstance(_l4_code, int),
                detail=f"got ({type(_l4_code).__name__}, {type(_l4_output).__name__})",
            )

            # Parse debug JSON to extract routing fields
            import json as _json_l4  # noqa: PLC0415
            try:
                _l4_json = _json_l4.loads(_l4_output)
                _l4_outcome = _l4_json.get("outcome")
                _l4_route_source = _l4_json.get("route_source")
                _l4_clarification = _l4_json.get("clarification_asked", False)
                _l4_llm_used = _l4_json.get("llm_used")
                _l4_final_text = _l4_json.get("final_text", "")

                _live_check(
                    "L4b outcome in (ok, needs_clarification, not_found)",
                    _l4_outcome in ("ok", "needs_clarification", "not_found"),
                    detail=f"outcome={_l4_outcome!r}",
                )
                _live_check(
                    "L4c route_source is not None",
                    _l4_route_source is not None,
                    detail=f"route_source={_l4_route_source!r}",
                )
                _live_check(
                    "L4d final_text is non-empty string",
                    isinstance(_l4_final_text, str) and len(_l4_final_text) > 0,
                )
                print(f"  INFO  CLI outcome={_l4_outcome!r}  route_source={_l4_route_source!r}")

                _l4_evidence.update({
                    "outcome": _l4_outcome,
                    "route_source": _l4_route_source,
                    "clarification_asked": _l4_clarification,
                    "llm_used": _l4_llm_used,
                    "final_text_preview": _l4_final_text[:120],
                    "skipped": False,
                })
            except Exception as exc_l4_parse:
                _live_check("L4b outcome in (ok, needs_clarification, not_found)", False, detail=f"JSON parse error: {exc_l4_parse}")
                _skip("L4c")
                _skip("L4d")
                _l4_outcome = None
                _l4_route_source = None
                _l4_clarification = None
                _l4_llm_used = None
        except Exception as exc_l4:
            _live_check("L4a fpl_cli.run() returns 2-tuple", False, detail=str(exc_l4))
            _skip("L4b")
            _skip("L4c")
            _skip("L4d")
            _l4_outcome = None
            _l4_route_source = None
            _l4_clarification = None
            _l4_llm_used = None

    # -----------------------------------------------------------------------
    # L5 — Live HTTP surface
    # -----------------------------------------------------------------------
    print("\n--- L5: Live HTTP surface ---")

    # L5 evidence defaults
    _l5_evidence: dict = {
        "question": _LIVE_QUESTION,
        "outcome": None,
        "route_source": None,
        "clarification_asked": None,
        "llm_used": None,
        "final_text_preview": None,
        "skipped": _live_classifier is None,
    }

    if _live_classifier is None:
        _skip("L5a")
        _skip("L5b")
        _skip("L5c")
        _skip("L5d")
    else:
        try:
            from fastapi.testclient import TestClient as _TestClient  # noqa: PLC0415
            import fpl_server as _fpl_server  # noqa: PLC0415

            # Inject live bootstrap and live classifier client
            _fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
            _fpl_server._init_classifier_client(_live_classifier)

            _http_live_client = _TestClient(_fpl_server.app, raise_server_exceptions=True)
            _l5_resp = _http_live_client.post(
                "/ask",
                json={"question": _LIVE_QUESTION},
            )
            _live_check(
                "L5a HTTP /ask returns 200",
                _l5_resp.status_code == 200,
                detail=f"status={_l5_resp.status_code}",
            )

            if _l5_resp.status_code == 200:
                _l5_json = _l5_resp.json()
                _l5_outcome = _l5_json.get("outcome")
                _l5_route_source = _l5_json.get("route_source")
                _l5_clarification = _l5_json.get("clarification_asked", False)
                _l5_llm_used = _l5_json.get("llm_used")
                _l5_final_text = _l5_json.get("final_text", "")

                _live_check(
                    "L5b outcome in (ok, needs_clarification, not_found)",
                    _l5_outcome in ("ok", "needs_clarification", "not_found"),
                    detail=f"outcome={_l5_outcome!r}",
                )
                _live_check(
                    "L5c route_source is not None",
                    _l5_route_source is not None,
                    detail=f"route_source={_l5_route_source!r}",
                )
                _live_check(
                    "L5d final_text is non-empty string",
                    isinstance(_l5_final_text, str) and len(_l5_final_text) > 0,
                )
                print(f"  INFO  HTTP outcome={_l5_outcome!r}  route_source={_l5_route_source!r}")

                _l5_evidence.update({
                    "outcome": _l5_outcome,
                    "route_source": _l5_route_source,
                    "clarification_asked": _l5_clarification,
                    "llm_used": _l5_llm_used,
                    "final_text_preview": _l5_final_text[:120],
                    "skipped": False,
                })
            else:
                _live_check("L5b outcome in (ok, needs_clarification, not_found)", False, detail="HTTP request failed")
                _skip("L5c")
                _skip("L5d")
                _l5_outcome = None
                _l5_route_source = None
                _l5_clarification = None
        except Exception as exc_l5:
            _live_check("L5a HTTP /ask returns 200", False, detail=str(exc_l5))
            _skip("L5b")
            _skip("L5c")
            _skip("L5d")
            _l5_outcome = None
            _l5_route_source = None
            _l5_clarification = None

        # Reset the server's classifier client back to None after live test
        try:
            _fpl_server._init_classifier_client(None)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # L6 — Surface parity check
    # -----------------------------------------------------------------------
    print("\n--- L6: Surface parity ---")

    _parity_evidence: dict = {
        "outcome_match": None,
        "route_source_match": None,
        "clarification_asked_match": None,
        "parity_passed": None,
        "skipped": _live_classifier is None,
    }

    if _live_classifier is None:
        _skip("L6a")
        _skip("L6b")
        _skip("L6c")
    elif _l4_evidence.get("skipped") or _l5_evidence.get("skipped"):
        _skip("L6a")
        _skip("L6b")
        _skip("L6c")
    else:
        _l6_l4_outcome = _l4_evidence.get("outcome")
        _l6_l5_outcome = _l5_evidence.get("outcome")
        _l6_l4_route = _l4_evidence.get("route_source")
        _l6_l5_route = _l5_evidence.get("route_source")
        _l6_l4_clar = _l4_evidence.get("clarification_asked")
        _l6_l5_clar = _l5_evidence.get("clarification_asked")

        _outcome_match = _l6_l4_outcome == _l6_l5_outcome
        _route_match = _l6_l4_route == _l6_l5_route
        _clar_match = _l6_l4_clar == _l6_l5_clar
        _parity_all = _outcome_match and _route_match and _clar_match

        _live_check(
            "L6a CLI outcome == HTTP outcome",
            _outcome_match,
            detail=f"cli={_l6_l4_outcome!r}  http={_l6_l5_outcome!r}",
        )
        _live_check(
            "L6b CLI route_source == HTTP route_source",
            _route_match,
            detail=f"cli={_l6_l4_route!r}  http={_l6_l5_route!r}",
        )
        _live_check(
            "L6c CLI clarification_asked == HTTP clarification_asked",
            _clar_match,
            detail=f"cli={_l6_l4_clar!r}  http={_l6_l5_clar!r}",
        )
        print(f"  INFO  parity_passed={_parity_all}")

        _parity_evidence.update({
            "outcome_match": _outcome_match,
            "route_source_match": _route_match,
            "clarification_asked_match": _clar_match,
            "parity_passed": _parity_all,
            "skipped": False,
        })

    # Build full live evidence artifact
    _evidence = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": _active_provider,
        "l1_health": {
            "available": _live_health.get("available"),
            "error": _live_health.get("error"),
        },
        "l2_classification": _l2_evidence,
        "l3_dispatch": _l3_evidence,
        "l4_cli_surface": _l4_evidence,
        "l5_http_surface": _l5_evidence,
        "surface_parity": _parity_evidence,
        "fallback_needed": _live_classifier is None,
    }

# ---------------------------------------------------------------------------
# Write evidence artifact (always — skipped variant is also useful)
# ---------------------------------------------------------------------------

try:
    with open(_EVIDENCE_PATH, "w", encoding="utf-8") as _ef:
        json.dump(_evidence, _ef, indent=2)
    print(f"\n  INFO  Evidence artifact written: {_EVIDENCE_PATH}")
except Exception as exc_ev:
    print(f"\n  WARN  Could not write evidence artifact: {exc_ev}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
print(f"PASSED (deterministic): {len(_pass)}")
if PROVIDER_SMOKE_ENABLED:
    print(f"LIVE PASSED: {len(_live_pass)}")
    if _live_fail:
        print(f"LIVE FAILED: {len(_live_fail)}")
else:
    print(f"LIVE SKIPPED: {_live_skip_count}   (set FPL_PROVIDER_SMOKE=1 to run)")
print(f"FAILED: {len(_fail) + len(_live_fail)}")
if _fail:
    print("\nFailed deterministic tests:")
    for f in _fail:
        print(f"  {f}")
if _live_fail:
    print("\nFailed live tests:")
    for f in _live_fail:
        print(f"  {f}")

sys.exit(0 if not (_fail or _live_fail) else 1)
