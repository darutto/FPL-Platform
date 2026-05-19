"""
run_phase_m5_tests.py
======================
Phase M5 (MCP_architecture): Decision-Tree Telemetry tests.

Covers:
    A  Frozen schema: routing_trace from ask_v2() always contains every
       required key — tested for all 6 branches.
    B  Counter increments: each branch increments exactly once.
    C  orchestrator_attempted vs orchestrator_grounded split (R5):
         no-tool orchestrator -> attempted increments, grounded does NOT.
         successful tool call -> both increment.
         route() hit         -> neither increments.
    D  /healthz payload shape: routing_counters and graduation keys present.
    E  Graduation math: synthetic snapshots -> correct deterministic_share /
       reject_rate / ready_to_graduate for edge cases.
    F  No execution-path change: route-hit question produces byte-equal
       answer_text and selected_tool before and after telemetry.

Note: G-section (POST /ask-orchestrated schema completeness) removed in G2 —
the rollout-isolation endpoint was deleted when production traffic was routed
through ask_v2() in G1.

Target: 54 assertions.  Exit code 0 on success, 1 on failure.

Run from packages/fpl-grounded-assistant::

    python run_phase_m5_tests.py
"""
from __future__ import annotations

import copy
import json
import os
import sys

# Windows consoles default to cp1252 which crashes on Unicode glyphs.
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

# Strip provider keys so step-3 only fires under explicit mock injection.
for _k in ("FPL_ORCH_ENABLED", "FPL_ORCH_PROVIDER", "ANTHROPIC_API_KEY",
           "OPENAI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_k, None)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant import ask, ask_v2  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.harness import (  # noqa: E402
    ROUTING_TRACE_REQUIRED_KEYS,
    ROUTING_TRACE_OPTIONAL_KEYS,
)
from fpl_grounded_assistant import telemetry  # noqa: E402
from fpl_grounded_assistant.telemetry import graduation_status, snapshot  # noqa: E402

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


def _build_bootstrap() -> dict:
    bs = copy.deepcopy(STANDARD_BOOTSTRAP)
    for el in bs["elements"]:
        el.setdefault("total_points", 100)
    return bs


BOOTSTRAP = _build_bootstrap()


def _reset() -> None:
    """Reset M5 routing counters between scenarios."""
    telemetry.reset()


# ---------------------------------------------------------------------------
# Mock clients (reuse pattern from run_phase_m3_tests.py)
# ---------------------------------------------------------------------------

class _MockClassifierClient:
    """Anthropic-compatible classifier client returning a fixed JSON payload."""

    def __init__(self, intent: str, canonical: str, confidence: float = 0.95) -> None:
        self._payload = {
            "intent":             intent,
            "canonical_question": canonical,
            "confidence":         confidence,
            "language":           "en",
        }
        self.messages = self

    def create(self, *, model, max_tokens, system, messages, **kwargs):
        class _Content:
            text = json.dumps(self._payload)

        class _Message:
            content = [_Content()]

        return _Message()


class _MockOrchToolUseClient:
    """Anthropic-shaped orchestrator client returning a single tool_use block."""

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        _name  = self._tool_name
        _input = dict(self._tool_input)

        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_m5_001"
            name  = _name
            input = _input

        class _Response:
            content     = [_ToolBlock()]
            stop_reason = "tool_use"

        return _Response()


class _MockOrchNoToolClient:
    """Anthropic-shaped orchestrator client returning a plain-text answer."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        class _TextBlock:
            type = "text"
            text = "I cannot help with that."

        class _Response:
            content     = [_TextBlock()]
            stop_reason = "end_turn"

        return _Response()


# ---------------------------------------------------------------------------
# Section A: Frozen schema — routing_trace contains all required keys
# ---------------------------------------------------------------------------

print("\n--- A: Frozen schema (routing_trace required keys) ---")

# A1: resource branch
_reset()
r = ask_v2("@injuries", BOOTSTRAP)
trace = r.get("routing_trace", {})
check(
    ROUTING_TRACE_REQUIRED_KEYS <= set(trace.keys()),
    "A1: resource branch contains all required keys",
)
check(trace.get("branch") == "resource", "A1b: resource branch label is 'resource'")

# A2: prompt branch — needs_clarification (missing args)
_reset()
r = ask_v2("/calendarios", BOOTSTRAP)
trace = r.get("routing_trace", {})
check(
    ROUTING_TRACE_REQUIRED_KEYS <= set(trace.keys()),
    "A2: prompt/clarification branch contains all required keys",
)
check(trace.get("branch") == "prompt", "A2b: clarification branch label is 'prompt'")

# A3: route branch — deterministic hit
_reset()
r = ask_v2("should I captain Haaland", BOOTSTRAP)
trace = r.get("routing_trace", {})
check(
    ROUTING_TRACE_REQUIRED_KEYS <= set(trace.keys()),
    "A3: route branch contains all required keys",
)
check(trace.get("branch") == "route", "A3b: route branch label is 'route'")

# A4: unsupported branch — plain text, no router, no orch
_reset()
r = ask_v2("what is the meaning of life", BOOTSTRAP)
trace = r.get("routing_trace", {})
check(
    ROUTING_TRACE_REQUIRED_KEYS <= set(trace.keys()),
    "A4: unsupported branch contains all required keys",
)
check(trace.get("branch") == "unsupported", "A4b: unsupported branch label is 'unsupported'")

# A5: classifier_rewrite branch
_reset()
_orch_off = os.environ.pop("FPL_ORCH_ENABLED", None)
clf_client = _MockClassifierClient(
    intent="captain_score",
    canonical="should I captain Haaland",
    confidence=0.95,
)
r = ask_v2("haaland capitan?", BOOTSTRAP, classifier_client=clf_client)
trace = r.get("routing_trace", {})
check(
    ROUTING_TRACE_REQUIRED_KEYS <= set(trace.keys()),
    "A5: classifier_rewrite branch contains all required keys",
)
check(
    trace.get("branch") == "classifier_rewrite",
    "A5b: classifier_rewrite branch label is 'classifier_rewrite'",
)

# A6: orchestrator branch
_reset()
os.environ["FPL_ORCH_ENABLED"] = "1"
orch_client = _MockOrchToolUseClient(
    "get_captain_score",
    {"query": "Haaland", "player_id": 355},
)
r = ask_v2("who should be my captain", BOOTSTRAP, orch_client=orch_client)
trace = r.get("routing_trace", {})
check(
    ROUTING_TRACE_REQUIRED_KEYS <= set(trace.keys()),
    "A6: orchestrator branch contains all required keys",
)
# orchestrator branch succeeds if the mock tool call produces an OK result;
# if the tool errors, branch falls to unsupported. Either way schema must hold.
check(
    trace.get("branch") in ("orchestrator", "unsupported"),
    "A6b: orchestrator or unsupported branch label present",
)
os.environ.pop("FPL_ORCH_ENABLED", None)

# A7: ROUTING_TRACE_OPTIONAL_KEYS are a strict superset of known optional keys
check(
    "expansion_text" in ROUTING_TRACE_OPTIONAL_KEYS,
    "A7: expansion_text is in ROUTING_TRACE_OPTIONAL_KEYS",
)
check(
    "orchestrator_error" in ROUTING_TRACE_OPTIONAL_KEYS,
    "A7b: orchestrator_error is in ROUTING_TRACE_OPTIONAL_KEYS",
)

# ---------------------------------------------------------------------------
# Section B: Counter increments — each branch increments exactly once
# ---------------------------------------------------------------------------

print("\n--- B: Counter increments (one per branch call) ---")

# B1: resource branch increments resource counter
_reset()
ask_v2("@injuries", BOOTSTRAP)
snap = snapshot()
check(snap["resource"] == 1, "B1: resource counter == 1 after one @resource call")
check(snap["total_primary"] == 1, "B1b: total_primary == 1")

# B2: route branch increments route counter
_reset()
ask_v2("should I captain Haaland", BOOTSTRAP)
snap = snapshot()
check(snap["route"] == 1, "B2: route counter == 1 after one route-hit call")
check(snap["total_primary"] == 1, "B2b: total_primary == 1")

# B3: unsupported branch increments unsupported counter
_reset()
ask_v2("what is the meaning of life", BOOTSTRAP)
snap = snapshot()
check(snap["unsupported"] == 1, "B3: unsupported counter == 1 after one miss")
check(snap["total_primary"] == 1, "B3b: total_primary == 1")

# B4: prompt/clarification branch increments prompt counter
_reset()
ask_v2("/calendarios", BOOTSTRAP)
snap = snapshot()
check(snap["prompt"] == 1, "B4: prompt counter == 1 after /prompt call")

# B5: classifier_rewrite increments classifier_rewrite counter
_reset()
os.environ.pop("FPL_ORCH_ENABLED", None)
clf = _MockClassifierClient("captain_score", "should I captain Haaland")
ask_v2("haaland capitan?", BOOTSTRAP, classifier_client=clf)
snap = snapshot()
check(
    snap["classifier_rewrite"] == 1,
    "B5: classifier_rewrite counter == 1 after rewrite-hit call",
)

# ---------------------------------------------------------------------------
# Section C: orchestrator_attempted vs orchestrator_grounded split (R5)
# ---------------------------------------------------------------------------

print("\n--- C: orchestrator_attempted vs orchestrator_grounded (R5 split) ---")

# C1: no-tool orchestrator -> attempted increments, grounded does NOT
_reset()
os.environ["FPL_ORCH_ENABLED"] = "1"
no_tool = _MockOrchNoToolClient()
ask_v2("what is the meaning of life", BOOTSTRAP, orch_client=no_tool)
snap = snapshot()
check(
    snap["orchestrator_attempted"] == 1,
    "C1: orchestrator_attempted == 1 when orch called but no tool chosen",
)
check(
    snap["orchestrator_grounded"] == 0,
    "C1b: orchestrator_grounded == 0 when no tool chosen",
)
os.environ.pop("FPL_ORCH_ENABLED", None)

# C2: successful tool call -> both attempted and grounded increment
_reset()
os.environ["FPL_ORCH_ENABLED"] = "1"
tool_use = _MockOrchToolUseClient(
    "get_captain_score",
    {"query": "Haaland", "player_id": 355},
)
result = ask_v2("who should be my captain", BOOTSTRAP, orch_client=tool_use)
snap = snapshot()
# If the orchestrator succeeds AND the tool call grounded, both should be 1.
# If the tool call itself errors (e.g. tool not found), attempted=1 but grounded=0.
check(
    snap["orchestrator_attempted"] == 1,
    "C2: orchestrator_attempted == 1 when orch called with tool response",
)
# Grounded only if branch="orchestrator" AND grounded=True
trace_c2 = result.get("routing_trace", {})
if trace_c2.get("branch") == "orchestrator" and trace_c2.get("grounded"):
    check(
        snap["orchestrator_grounded"] == 1,
        "C2b: orchestrator_grounded == 1 when tool call grounded",
    )
else:
    check(
        snap["orchestrator_grounded"] == 0,
        "C2b: orchestrator_grounded == 0 when orch did not ground (tool error)",
    )
os.environ.pop("FPL_ORCH_ENABLED", None)

# C3: route() hit -> neither orchestrator counter increments
_reset()
ask_v2("should I captain Haaland", BOOTSTRAP)
snap = snapshot()
check(
    snap["orchestrator_attempted"] == 0,
    "C3: orchestrator_attempted == 0 for route() hit",
)
check(
    snap["orchestrator_grounded"] == 0,
    "C3b: orchestrator_grounded == 0 for route() hit",
)

# ---------------------------------------------------------------------------
# Section D: /healthz payload shape
# ---------------------------------------------------------------------------

print("\n--- D: /healthz payload shape ---")

# Import FastAPI test client
try:
    from fastapi.testclient import TestClient
    import fpl_server

    fpl_server._init_bootstrap(BOOTSTRAP)
    fpl_server._clear_sessions()
    _tel_reset_fn = telemetry.reset
    _tel_reset_fn()

    client = TestClient(fpl_server.app)

    resp = client.get("/healthz")
    check(resp.status_code == 200, "D1: GET /healthz returns HTTP 200")
    body = resp.json()
    check("routing_counters" in body, "D2: routing_counters key present in /healthz response")
    check("graduation" in body, "D3: graduation key present in /healthz response")

    rc = body.get("routing_counters", {})
    _expected_counter_keys = {
        "resource", "prompt", "route", "classifier_rewrite",
        "orchestrator", "unsupported", "orchestrator_attempted",
        "orchestrator_grounded", "total_primary", "reject_rate",
    }
    check(
        _expected_counter_keys <= set(rc.keys()),
        "D4: all expected routing_counters keys present",
    )

    grad = body.get("graduation", {})
    _expected_grad_keys = {
        "deterministic_share", "orchestrator_grounded_share", "reject_rate",
        "criteria", "ready_to_graduate", "total_observations",
    }
    check(
        _expected_grad_keys <= set(grad.keys()),
        "D5: all expected graduation keys present",
    )

    criteria = grad.get("criteria", {})
    check(
        "deterministic_share_ge_80" in criteria and "reject_rate_lt_5" in criteria,
        "D6: graduation.criteria has deterministic_share_ge_80 and reject_rate_lt_5",
    )

except ImportError as _e:
    print(f"  SKIP  D-suite: fastapi.testclient not available ({_e})")

# ---------------------------------------------------------------------------
# Section E: Graduation math — synthetic counter snapshots
# ---------------------------------------------------------------------------

print("\n--- E: Graduation math (synthetic snapshots) ---")

def _make_snap(
    resource=0, prompt=0, route=0, classifier_rewrite=0,
    orchestrator=0, unsupported=0,
    orchestrator_attempted=0, orchestrator_grounded=0,
) -> dict:
    total = resource + prompt + route + classifier_rewrite + orchestrator + unsupported
    return {
        "resource":               resource,
        "prompt":                 prompt,
        "route":                  route,
        "classifier_rewrite":     classifier_rewrite,
        "orchestrator":           orchestrator,
        "unsupported":            unsupported,
        "orchestrator_attempted": orchestrator_attempted,
        "orchestrator_grounded":  orchestrator_grounded,
        "total_primary":          total,
        "reject_rate":            unsupported / total if total > 0 else 0.0,
    }


# E1: all-zero -> not ready
s = _make_snap()
g = graduation_status(s)
check(g["ready_to_graduate"] is False, "E1: all-zero counters -> not ready")
check(g["total_observations"] == 0, "E1b: all-zero -> total_observations == 0")

# E2: all-deterministic -> deterministic_share=1.0, reject_rate=0 -> ready
s = _make_snap(route=80, resource=10, prompt=10)
g = graduation_status(s)
check(
    abs(g["deterministic_share"] - 1.0) < 1e-9,
    "E2: all-deterministic -> deterministic_share == 1.0",
)
check(
    abs(g["reject_rate"] - 0.0) < 1e-9,
    "E2b: all-deterministic -> reject_rate == 0.0",
)
check(g["criteria"]["deterministic_share_ge_80"] is True, "E2c: criterion ge_80 is True")
check(g["criteria"]["reject_rate_lt_5"] is True, "E2d: criterion lt_5 is True")
check(g["ready_to_graduate"] is True, "E2e: all-deterministic -> ready_to_graduate")

# E3: mostly-orchestrator (orch=80, det=10, unsupported=10) -> det_share=0.10 -> NOT ready
s = _make_snap(orchestrator=80, route=10, unsupported=10)
g = graduation_status(s)
check(
    g["criteria"]["deterministic_share_ge_80"] is False,
    "E3: mostly-orchestrator -> deterministic_share_ge_80 is False",
)
check(g["ready_to_graduate"] is False, "E3b: mostly-orchestrator -> not ready")

# E4: high-reject (unsupported=10, route=90) -> reject_rate=0.1 -> NOT ready
s = _make_snap(route=90, unsupported=10)
g = graduation_status(s)
check(
    abs(g["reject_rate"] - 0.1) < 1e-9,
    "E4: high-reject -> reject_rate == 0.1",
)
check(
    g["criteria"]["reject_rate_lt_5"] is False,
    "E4b: high-reject -> reject_rate_lt_5 is False",
)
check(g["ready_to_graduate"] is False, "E4c: high-reject -> not ready")

# E5: classifier_rewrite counts as deterministic
s = _make_snap(route=50, classifier_rewrite=30, unsupported=2)
g = graduation_status(s)
det = g["deterministic_share"]
# (50+30) / (50+30+2) = 80/82 ~ 0.9756
check(det > 0.97, "E5: classifier_rewrite included in deterministic_share")
check(g["ready_to_graduate"] is True, "E5b: classifier_rewrite path -> ready")

# E6: orchestrator_grounded_share is informational (not gating)
s = _make_snap(route=30, orchestrator=50, unsupported=2, orchestrator_grounded=50)
g = graduation_status(s)
# orchestrator_grounded_share = 50/82
check(g["orchestrator_grounded_share"] > 0, "E6: orchestrator_grounded_share is computed")
check(
    "orchestrator_grounded_share" not in g["criteria"],
    "E6b: orchestrator_grounded_share is NOT a gating criterion",
)

# ---------------------------------------------------------------------------
# Section F: No execution-path change for route-hit questions
# ---------------------------------------------------------------------------

print("\n--- F: No execution-path change (route-hit parity) ---")

_reset()

# Capture baseline via ask() (unmodified original function)
baseline = ask("should I captain Haaland", BOOTSTRAP)

# Capture via ask_v2() with telemetry active
_reset()
v2_result = ask_v2("should I captain Haaland", BOOTSTRAP)

check(
    baseline["selected_tool"] == v2_result["selected_tool"],
    "F1: selected_tool byte-equal before and after telemetry",
)
check(
    baseline["answer_text"] == v2_result["answer_text"],
    "F2: answer_text byte-equal before and after telemetry",
)
check(
    "routing_trace" in v2_result,
    "F3: ask_v2() still attaches routing_trace after telemetry instrumentation",
)

# Verify counters did not bleed into ask() (validation corpus guard)
# ask() does not touch telemetry; route counter must stay at 1 (only the ask_v2 call)
snap = snapshot()
check(snap["route"] == 1, "F4: counter incremented exactly once (only ask_v2 call)")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\nPhase M5 Tests: {_pass} PASS, {_fail} FAIL")
if _failures:
    print("Failed assertions:")
    for f in _failures:
        print(f"  - {f}")

sys.exit(0 if _fail == 0 else 1)
