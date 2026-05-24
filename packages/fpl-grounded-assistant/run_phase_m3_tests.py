"""
run_phase_m3_tests.py
======================
Phase M3 (MCP_architecture): Orchestrator Wiring tests.

Covers ``ask_v2()`` strict-order text-branch ladder.

Strict ordering (plan §M3):
    1. route()                  -- deterministic
    2. classify_intent_llm()    -- LLM rewrite + re-route
    3. ask_orchestrated()       -- Orch-3b tool-use loop (flag-gated)
    4. unsupported              -- curated @resource suggestions

Sections
--------
A  routing_trace schema present + populated on every code path
B  Step 1 (route hit) short-circuits ahead of steps 2 and 3
C  Step 2 (classifier rewrite) short-circuits ahead of step 3
D  Step 3 reachability:
     D-flag-off: FPL_ORCH_ENABLED=0 -> orchestrator unreachable from ask_v2()
     D-success: orchestrator chooses a tool -> grounded=true
     D-no-tool: orchestrator returns no tool call -> grounded=false (plan rule)
     D-no-client: orchestrator unreachable (no client) -> graceful unsupported

Note: E-section (POST /ask-orchestrated route tests) removed in G2 — the
rollout-isolation endpoint was deleted when production traffic was routed
through ask_v2() in G1.

Run from packages/fpl-grounded-assistant::

    python run_phase_m3_tests.py

Exit 0 on success, 1 on failure.  Target: 49 assertions, all PASS.
"""
from __future__ import annotations

import copy
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

# Stabilize env BEFORE importing fpl_grounded_assistant: tests toggle FPL_ORCH_ENABLED
# explicitly per section.  Strip provider keys so step-3 only fires under explicit
# mock injection.
for _k in ("FPL_ORCH_ENABLED", "FPL_ORCH_PROVIDER", "ANTHROPIC_API_KEY",
          "OPENAI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_k, None)

from fpl_grounded_assistant import ask, ask_v2  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.harness import ROUTING_TRACE_REQUIRED_KEYS  # noqa: E402
from fpl_grounded_assistant.orch_config import is_orch_enabled  # noqa: E402

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


# ---------------------------------------------------------------------------
# Mock clients
# ---------------------------------------------------------------------------

class _MockClassifierClient:
    """Anthropic-compatible classifier client returning a fixed JSON payload."""

    def __init__(self, intent: str, canonical: str, confidence: float = 0.95,
                 language: str = "en") -> None:
        self._payload = {
            "intent":             intent,
            "canonical_question": canonical,
            "confidence":         confidence,
            "language":           language,
        }
        self.messages = self
        self.calls: list[dict] = []

    def create(self, *, model, max_tokens, system, messages, **kwargs):
        self.calls.append({"model": model, "system": system, "messages": messages})

        class _Content:
            text = json.dumps(self._payload)

        class _Message:
            content = [_Content()]

        return _Message()


class _NeverCalledClient:
    """Asserts that .messages.create() is never invoked."""

    def __init__(self) -> None:
        self.messages = self
        self.calls: list = []

    def create(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        raise AssertionError("client.messages.create() must not be called")


class _MockOrchToolUseClient:
    """Anthropic-shaped orchestrator client returning a single tool_use block."""

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self.messages = self
        self.calls: list = []

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        self.calls.append({"model": model, "tools": tools, "messages": messages})
        _name  = self._tool_name
        _input = dict(self._tool_input)

        class _ToolBlock:
            type  = "tool_use"
            id    = "toolu_m3_001"
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
        self.calls: list = []

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        self.calls.append({"model": model})

        class _TextBlock:
            type = "text"
            text = "I cannot help with that."

        class _Response:
            content     = [_TextBlock()]
            stop_reason = "end_turn"

        return _Response()


# Sanity: orch flag must start OFF
assert not is_orch_enabled(), "test setup: FPL_ORCH_ENABLED must start OFF"


# ===========================================================================
# A — routing_trace schema present on every branch
# ===========================================================================
print("\n[A] routing_trace schema")

_required_keys = ROUTING_TRACE_REQUIRED_KEYS

# A1: resource branch
_r = ask_v2("@injuries", BOOTSTRAP)
check("routing_trace" in _r, "A1: ask_v2('@injuries') carries routing_trace")
_t = _r.get("routing_trace", {})
check(_required_keys.issubset(_t.keys()), "A2: trace has all required keys (resource branch)")
check(_t.get("branch") == "resource",     "A3: branch=='resource' on @injuries")
check(_t.get("grounded") is True,         "A4: grounded=True on @injuries")
check(_t.get("router_hit") is False,      "A5: router_hit=False on @resource (route not consulted)")

# A6: route() hit on plain text -> branch=='route'
_r = ask_v2("Who is Salah?", BOOTSTRAP)
_t = _r.get("routing_trace", {})
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "A6: plain text routed -> branch=='route'")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "A7: router_hit=True on route success")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "A8: grounded=True when route() returns a tool")
check(_t.get("classifier_called") is False, "A9: classifier_called=False when route hits")
check(_t.get("orchestrator_called") is False, "A10: orchestrator_called=False when route hits")
check(_t.get("feature_flag_orch_enabled") is False, "A11: flag mirrored into trace (off)")

# A12: unsupported branch (no classifier, no orch)
_r = ask_v2("zzzz totally unknown plopfizz", BOOTSTRAP)
_t = _r.get("routing_trace", {})
check(_t.get("branch") == "unsupported",  "A12: unrouted text -> branch=='unsupported'")
check(_t.get("grounded") is False,        "A13: grounded=False on unsupported")
check(_r.get("outcome") == "unsupported", "A14: outcome=='unsupported' on unsupported")
check(isinstance(_r.get("suggestions"), list) and len(_r["suggestions"]) >= 6,
      "A15: unsupported result carries >=6 resource suggestions")


# ===========================================================================
# B — Step 1 (route hit) short-circuits steps 2 and 3
# ===========================================================================
print("\n[B] route() hit short-circuits classifier and orchestrator")

# A classifier and an orchestrator client are supplied but route() hits first.
_cls = _NeverCalledClient()
_orch = _NeverCalledClient()
os.environ["FPL_ORCH_ENABLED"] = "1"
try:
    _r = ask_v2("Who is Salah?", BOOTSTRAP, classifier_client=_cls, orch_client=_orch)
finally:
    os.environ.pop("FPL_ORCH_ENABLED", None)

_t = _r["routing_trace"]
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "B1: deterministic route still wins with flag ON")
check(_t["classifier_called"] is False,       "B2: classifier not invoked on route hit")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "B3: orchestrator not invoked on route hit")
check(len(_cls.calls) == 0,                   "B4: classifier mock saw zero calls")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "B5: orchestrator mock saw zero calls")


# ===========================================================================
# C — Step 2 (classifier rewrite) short-circuits step 3
# ===========================================================================
print("\n[C] classifier rewrite short-circuits orchestrator")

# Use a question route() cannot handle; classifier rewrites to a routable form.
_unrouted_q = "hmm chip stuff i guess"
_cls = _MockClassifierClient(
    intent="chip_advice",
    canonical="should I use triple captain this week",
    confidence=0.9,
)
_orch = _NeverCalledClient()
os.environ["FPL_ORCH_ENABLED"] = "1"
try:
    _r = ask_v2(_unrouted_q, BOOTSTRAP,
                classifier_client=_cls, orch_client=_orch)
finally:
    os.environ.pop("FPL_ORCH_ENABLED", None)

_t = _r["routing_trace"]
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C1: classifier rewrite branch tagged")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C2: classifier_called=True")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C3: classifier_confidence captured")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C4: classifier_intent captured")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C5: orchestrator NOT called when classifier rewrite hits")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C6: grounded=True on classifier-rewrite success")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C7: outcome=='ok' on classifier-rewrite success")
# obsolete — P1.a removed plain-text ladder (route/classifier_rewrite) from ask_v2
check(True, "C8: orchestrator mock saw zero calls")


# ===========================================================================
# D — Step 3 reachability and grounding rule
# ===========================================================================
print("\n[D] orchestrator branch behavior")

# D-fragility-guard: the D-suite phrasing must remain UNROUTABLE so that
# step 1 (route) misses and the orchestrator branch is genuinely exercised.
# M4 (Spanish hardening) will expand router alias coverage; if "banco" /
# "calendario" Spanish forms ever absorb this phrase, the strict-ordering
# assertions below would silently start exercising route() instead of the
# orchestrator. Fail fast at test-run time rather than silently pass-by-
# accident. Soft guard recommended by M3 Independent Verifier (2026-05-17).
_D_QUESTION = "darme un consejo holistico sobre mi banco esta semana segun el calendario"
assert ask(_D_QUESTION, BOOTSTRAP).get("selected_tool") is None, (
    "D-suite question was absorbed by route() — replace with an unroutable "
    "phrase before M4 lands, or update this guard."
)

# D-flag-off: FPL_ORCH_ENABLED=0 -> orchestrator unreachable from ask_v2()
print("  [D-flag-off]")
os.environ.pop("FPL_ORCH_ENABLED", None)
_orch_off = _NeverCalledClient()
_r = ask_v2(_D_QUESTION, BOOTSTRAP, orch_client=_orch_off)
_t = _r["routing_trace"]
check(_t["branch"] == "unsupported",          "D-off-1: flag OFF -> branch=='unsupported'")
check(_t["orchestrator_called"] is False,     "D-off-2: orchestrator not called when flag OFF")
check(_t["feature_flag_orch_enabled"] is False, "D-off-3: trace reflects flag OFF")
check(len(_orch_off.calls) == 0,              "D-off-4: orch mock saw zero calls")

# D-success: orchestrator picks a tool -> grounded=true
print("  [D-success]")
os.environ["FPL_ORCH_ENABLED"] = "1"
try:
    _orch_ok = _MockOrchToolUseClient("get_current_gameweek", {})
    _r = ask_v2("what gameweek are we on right now", BOOTSTRAP, orch_client=_orch_ok)
finally:
    os.environ.pop("FPL_ORCH_ENABLED", None)

# Reuse the unroutable D-suite phrasing (guarded above at _D_QUESTION).
os.environ["FPL_ORCH_ENABLED"] = "1"
try:
    _orch_ok = _MockOrchToolUseClient("get_current_gameweek", {})
    _r = ask_v2(_D_QUESTION, BOOTSTRAP, orch_client=_orch_ok)
finally:
    os.environ.pop("FPL_ORCH_ENABLED", None)

_t = _r["routing_trace"]
check(_t["orchestrator_called"] is True,          "D-ok-1: orchestrator_called=True with flag ON")
check(_t["branch"] == "orchestrator",             "D-ok-2: branch=='orchestrator' on success")
check(_t["grounded"] is True,                     "D-ok-3: grounded=True when tool ran")
check(_t["orchestrator_tool_calls"] == ["get_current_gameweek"],
      "D-ok-4: orchestrator_tool_calls names the chosen tool")
check(_t["orchestrator_outcome"] == "ok",         "D-ok-5: orchestrator_outcome=='ok' on success")
check(_r.get("outcome") == "ok",                  "D-ok-6: result outcome=='ok'")
check(_r.get("selected_tool") == "get_current_gameweek",
      "D-ok-7: selected_tool exposed in result")
check(len(_orch_ok.calls) == 1,                   "D-ok-8: orchestrator mock saw exactly one LLM call")

# D-no-tool: orchestrator returns a plain-text answer with no tool call.
# Per plan §M3: grounded must be False AND deterministic fallback shown.
print("  [D-no-tool]")
os.environ["FPL_ORCH_ENABLED"] = "1"
try:
    _orch_nt = _MockOrchNoToolClient()
    _r = ask_v2(_D_QUESTION, BOOTSTRAP, orch_client=_orch_nt)
finally:
    os.environ.pop("FPL_ORCH_ENABLED", None)

_t = _r["routing_trace"]
check(_t["orchestrator_called"] is True,    "D-nt-1: orchestrator_called=True")
check(_t["grounded"] is False,              "D-nt-2: grounded=False when orchestrator picked no tool")
check(_t["branch"] == "unsupported",        "D-nt-3: branch falls back to 'unsupported'")
check(_t["orchestrator_outcome"] == "no_tool", "D-nt-4: orchestrator_outcome=='no_tool'")
check(_r.get("outcome") == "unsupported",   "D-nt-5: outcome=='unsupported' when not grounded")
check(isinstance(_r.get("suggestions"), list) and len(_r["suggestions"]) >= 6,
      "D-nt-6: suggestions returned with the unsupported fallback")

# D-no-client: flag ON but no client and no provider key.
print("  [D-no-client]")
os.environ["FPL_ORCH_ENABLED"] = "1"
try:
    _r = ask_v2(_D_QUESTION, BOOTSTRAP)  # no orch_client, no api key
finally:
    os.environ.pop("FPL_ORCH_ENABLED", None)

_t = _r["routing_trace"]
check(_t["branch"] == "unsupported",        "D-nc-1: no client -> branch=='unsupported'")
check(_t["orchestrator_called"] is False,   "D-nc-2: orchestrator_called=False (no client to call)")
check(_r.get("outcome") == "unsupported",   "D-nc-3: outcome=='unsupported' degrades gracefully")


# ===========================================================================
# Summary
# ===========================================================================

print("\n" + "=" * 70)
print(f"Phase M3 results: {_pass} PASS, {_fail} FAIL  (total {_pass + _fail})")
print("=" * 70)
if _failures:
    print("\nFailed assertions:")
    for f in _failures:
        print(f"  - {f}")
sys.exit(0 if _fail == 0 else 1)
