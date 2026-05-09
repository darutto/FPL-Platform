"""
run_phase27g_tests.py
=====================
Phase 2.7g: Telemetry-Driven Hardening Loop.

Validates that in-process telemetry counters are incremented correctly
by routing decisions, and that the /metrics endpoint returns a valid
JSON snapshot with all expected keys.

Telemetry is in-process and module-level: counters are reset before each
logical group so individual assertions are independent.

Test groups
-----------
A — telemetry.py unit: reset + record_response + get_snapshot
B — deterministic route increments route_source_counts["deterministic"]
C — medium-confidence stub: route_source_counts["llm_classifier_medium"] +
    clarification_asked_total
D — high-confidence stub: route_source_counts["llm_classifier_high"]
E — /metrics endpoint: valid JSON with all expected top-level keys
F — error-safety: telemetry never raises even under adversarial inputs
G — regression: validation corpus unchanged
"""
from __future__ import annotations

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

import fpl_grounded_assistant.telemetry as _telemetry
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DIFFERENTIAL_BOOTSTRAP,
)
from fpl_grounded_assistant.final_response import respond

_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _pass.append(label)
        print("  PASS  " + label)
    else:
        _fail.append(label)
        msg = "  FAIL  " + label
        if detail:
            msg += " (" + detail + ")"
        print(msg)


# ---------------------------------------------------------------------------
# LLM stub (same pattern as run_validation.py)
# ---------------------------------------------------------------------------

class _StubBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMessage:
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    def __init__(self, response_json: str) -> None:
        self._response_json = response_json

    def create(self, **kwargs):  # noqa: ANN001,ANN201
        return _StubMessage(self._response_json)


class _StubClassifierClient:
    """Minimal stub classifier that returns a fixed JSON payload."""
    def __init__(self, response_json: str) -> None:
        self.messages = _StubMessages(response_json)


# Stub payloads for different confidence levels.
_HIGH_CONF_JSON = json.dumps({
    "intent": "captain_score",
    "canonical_question": "should I captain Haaland this week",
    "confidence": 0.95,
    "language": "en",
})

_MEDIUM_CONF_JSON = json.dumps({
    "intent": "captain_score",
    "canonical_question": "should I captain Haaland",
    "confidence": 0.75,
    "language": "es",
})

_HIGH_STUB   = _StubClassifierClient(_HIGH_CONF_JSON)
_MEDIUM_STUB = _StubClassifierClient(_MEDIUM_CONF_JSON)


# ---------------------------------------------------------------------------
# A — Unit: reset / record_response / get_snapshot
# ---------------------------------------------------------------------------

print("\n=== A: telemetry unit ===")

_telemetry.reset()
snap = _telemetry.get_snapshot()
_check("A1 snapshot is dict",          isinstance(snap, dict))
_check("A2 all keys present",          all(k in snap for k in [
    "route_source_counts", "outcome_counts",
    "classifier_confidence_bucket_counts",
    "clarification_asked_total",
    "intent_route_counts",
]))
_check("A3 all counters empty after reset", snap == {
    "route_source_counts": {},
    "outcome_counts": {},
    "classifier_confidence_bucket_counts": {},
    "clarification_asked_total": 0,
    "intent_route_counts": {},
})

# Record one event and check increments
_telemetry.reset()
_telemetry.record_response(
    intent="captain_score",
    outcome="ok",
    route_source="deterministic",
    classifier_confidence=None,
    supported=True,
    clarification_asked=False,
)
snap2 = _telemetry.get_snapshot()
_check("A4 route_source deterministic=1",     snap2["route_source_counts"].get("deterministic") == 1)
_check("A5 outcome ok=1",                     snap2["outcome_counts"].get("ok") == 1)
_check("A6 confidence bucket none=1",         snap2["classifier_confidence_bucket_counts"].get("none") == 1)
_check("A7 clarification_asked_total=0",      snap2["clarification_asked_total"] == 0)
_check("A8 intent_route key present",
       "captain_score|deterministic" in snap2["intent_route_counts"])
_check("A9 intent_route count=1",
       snap2["intent_route_counts"].get("captain_score|deterministic") == 1)

# Record a clarification event
_telemetry.record_response(
    intent="transfer_advice",
    outcome="needs_clarification",
    route_source="llm_classifier_medium",
    classifier_confidence=0.75,
    supported=False,
    clarification_asked=True,
)
snap3 = _telemetry.get_snapshot()
_check("A10 clarification_asked_total=1",     snap3["clarification_asked_total"] == 1)
_check("A11 medium confidence bucket=1",      snap3["classifier_confidence_bucket_counts"].get("medium") == 1)
_check("A12 llm_classifier_medium=1",         snap3["route_source_counts"].get("llm_classifier_medium") == 1)

# Confidence bucket edges
_telemetry.reset()
_telemetry.record_response("x", "ok", "det", 0.9,   True,  False)  # high
_telemetry.record_response("x", "ok", "det", 0.89,  True,  False)  # medium
_telemetry.record_response("x", "ok", "det", 0.7,   True,  False)  # medium
_telemetry.record_response("x", "ok", "det", 0.699, True,  False)  # low
_telemetry.record_response("x", "ok", "det", None,  True,  False)  # none
snap4 = _telemetry.get_snapshot()
_check("A13 high bucket=1",   snap4["classifier_confidence_bucket_counts"].get("high") == 1)
_check("A14 medium bucket=2", snap4["classifier_confidence_bucket_counts"].get("medium") == 2)
_check("A15 low bucket=1",    snap4["classifier_confidence_bucket_counts"].get("low") == 1)
_check("A16 none bucket=1",   snap4["classifier_confidence_bucket_counts"].get("none") == 1)


# ---------------------------------------------------------------------------
# B — Deterministic route increments route_source_counts["deterministic"]
# ---------------------------------------------------------------------------

print("\n=== B: deterministic route ===")

_telemetry.reset()

# "who should I captain" is a clear deterministic route (captain_score keyword)
_fr_det = respond("who should I captain this week", STANDARD_BOOTSTRAP)
snap_b = _telemetry.get_snapshot()

_check("B1 intent=captain_score",            _fr_det.intent == "captain_score")
_check("B2 route_source=deterministic",      _fr_det.route_source == "deterministic")
_check("B3 route_source_counts det>=1",
       snap_b["route_source_counts"].get("deterministic", 0) >= 1)
_check("B4 outcome_counts contains the actual outcome",
       snap_b["outcome_counts"].get(_fr_det.outcome, 0) >= 1)
_check("B5 intent_route key present",
       "captain_score|deterministic" in snap_b["intent_route_counts"])


# ---------------------------------------------------------------------------
# C — Medium-confidence stub → route_source_counts["llm_classifier_medium"]
#     + clarification_asked_total incremented
# ---------------------------------------------------------------------------

print("\n=== C: medium-confidence classifier gate ===")

_telemetry.reset()

_fr_med = respond(
    "deberia capear con Haaland",   # ambiguous Spanish — won't deterministically route
    STANDARD_BOOTSTRAP,
    classifier_client=_MEDIUM_STUB,
)
snap_c = _telemetry.get_snapshot()

_check("C1 outcome=needs_clarification",          _fr_med.outcome == "needs_clarification")
_check("C2 route_source=llm_classifier_medium",   _fr_med.route_source == "llm_classifier_medium")
_check("C3 clarification_asked=True",             _fr_med.clarification_asked is True)
_check("C4 llm_classifier_medium count>=1",
       snap_c["route_source_counts"].get("llm_classifier_medium", 0) >= 1)
_check("C5 clarification_asked_total>=1",
       snap_c["clarification_asked_total"] >= 1)
_check("C6 needs_clarification count>=1",
       snap_c["outcome_counts"].get("needs_clarification", 0) >= 1)
_check("C7 medium confidence bucket>=1",
       snap_c["classifier_confidence_bucket_counts"].get("medium", 0) >= 1)


# ---------------------------------------------------------------------------
# D — High-confidence stub → route_source_counts["llm_classifier_high"]
# ---------------------------------------------------------------------------

print("\n=== D: high-confidence classifier gate ===")

_telemetry.reset()

_fr_high = respond(
    "deberia capear con Haaland",
    STANDARD_BOOTSTRAP,
    classifier_client=_HIGH_STUB,
)
snap_d = _telemetry.get_snapshot()

_check("D1 outcome=ok (or not needs_clarification)",
       _fr_high.outcome != "needs_clarification")
_check("D2 route_source=llm_classifier_high",  _fr_high.route_source == "llm_classifier_high")
_check("D3 clarification_asked=False",         _fr_high.clarification_asked is False)
_check("D4 llm_classifier_high count>=1",
       snap_d["route_source_counts"].get("llm_classifier_high", 0) >= 1)
_check("D5 clarification_asked_total=0",
       snap_d["clarification_asked_total"] == 0)
_check("D6 high confidence bucket>=1",
       snap_d["classifier_confidence_bucket_counts"].get("high", 0) >= 1)


# ---------------------------------------------------------------------------
# E — /metrics endpoint returns valid JSON with all expected top-level keys
# ---------------------------------------------------------------------------

print("\n=== E: /metrics HTTP endpoint ===")

try:
    import fpl_server
    from fastapi.testclient import TestClient

    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._init_classifier_client(None)
    _client = TestClient(fpl_server.app)

    _resp = _client.get("/metrics")
    _check("E1 /metrics returns 200",         _resp.status_code == 200)

    _body = _resp.json()
    _check("E2 response is dict",             isinstance(_body, dict))
    _check("E3 element_summary_guard present", "element_summary_guard" in _body)
    _check("E4 routing key present",           "routing" in _body)

    _routing = _body.get("routing", {})
    _check("E5 routing.route_source_counts",
           "route_source_counts" in _routing)
    _check("E6 routing.outcome_counts",
           "outcome_counts" in _routing)
    _check("E7 routing.classifier_confidence_bucket_counts",
           "classifier_confidence_bucket_counts" in _routing)
    _check("E8 routing.clarification_asked_total present",
           "clarification_asked_total" in _routing)
    _check("E9 routing.intent_route_counts",
           "intent_route_counts" in _routing)
    _check("E10 clarification_asked_total is int",
           isinstance(_routing.get("clarification_asked_total"), int))

    # Make a request and check the counter updated in the snapshot
    _telemetry.reset()
    _client.post("/ask", json={"question": "who should I captain"})
    _resp2   = _client.get("/metrics")
    _body2   = _resp2.json()
    _routing2 = _body2.get("routing", {})
    _total_route = sum(_routing2.get("route_source_counts", {}).values())
    _check("E11 /metrics reflects post-ask counters", _total_route >= 1)

except ImportError as e:
    _check("E1 fastapi/starlette not available — skip", True, str(e))
    print("      (TestClient not available; E group skipped)")
except Exception as e:  # noqa: BLE001
    _fail.append("E-group exception: " + str(e))
    print("  FAIL  E-group exception: " + str(e))


# ---------------------------------------------------------------------------
# F — Error-safety: telemetry never raises
# ---------------------------------------------------------------------------

print("\n=== F: error-safety ===")

_telemetry.reset()

# Adversarial: passing wrong types to record_response should not raise
try:
    _telemetry.record_response(
        intent=None,
        outcome=None,
        route_source=None,
        classifier_confidence=None,
        supported=False,
        clarification_asked=False,
    )
    _check("F1 None values safe",             True)
except Exception as e:  # noqa: BLE001
    _check("F1 None values safe",             False, str(e))

# get_snapshot never raises
try:
    _snap = _telemetry.get_snapshot()
    _check("F2 get_snapshot never raises",    isinstance(_snap, dict))
except Exception as e:  # noqa: BLE001
    _check("F2 get_snapshot never raises",    False, str(e))

# reset never raises
try:
    _telemetry.reset()
    _check("F3 reset never raises",           True)
except Exception as e:  # noqa: BLE001
    _check("F3 reset never raises",           False, str(e))


# ---------------------------------------------------------------------------
# G — Regression: validation corpus
# ---------------------------------------------------------------------------

print("\n=== G: Regression ===")

from run_validation import run_all_scenarios

_telemetry.reset()
results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(
    "G1 validation corpus %d/%d PASS" % (passed, total),
    passed == total,
    "%d scenario(s) failed" % (total - passed),
)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("Phase 2.7g: %d/%d assertions passed." % (len(_pass), len(_pass) + len(_fail)))
if _fail:
    print("               %d assertion(s) FAILED." % len(_fail))
    for f in _fail:
        print("  - " + f)
else:
    print("               All assertions passed.")
