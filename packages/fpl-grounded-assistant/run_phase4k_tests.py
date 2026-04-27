"""
run_phase4k_tests.py
====================
Phase 4k: LLM-Assisted Intent Classification — test suite.

Target: ~100 assertions across 8 sections.

Sections
--------
A  intent_classifier module — unit tests for pure functions (16)
B  Stub behaviour — _StubAnthropicClient mimics the classifier interface (6)
C  Dispatcher integration — classify fallback wired into dispatch() (18)
D  Full stack — respond() with classifier_client (14)
E  CLI integration — run() with classifier_client (14)
F  Regression — deterministic routing unchanged by Phase 4k (12)
G  Fallback safety — no client / low confidence / bad JSON / route miss (12)
H  Validation corpus — 3 new scenarios present and well-formed (8)
"""
from __future__ import annotations

import json
import os
import sys
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
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.intent_classifier import (
    IntentClassification,
    CLASSIFIER_SYSTEM_PROMPT,
    build_classifier_prompt,
    _parse_classifier_response,
    classify_intent_llm,
    _CONFIDENCE_THRESHOLD,
)
from fpl_grounded_assistant.dispatcher import (
    dispatch, DispatchResult,
    INTENT_CAPTAIN_SCORE, INTENT_COMPARE_PLAYERS, INTENT_RANK_CANDIDATES,
    INTENT_PLAYER_SUMMARY, INTENT_UNSUPPORTED,
    OUTCOME_OK, OUTCOME_UNSUPPORTED_INTENT, OUTCOME_MISSING_ARGUMENTS,
)
from fpl_grounded_assistant.final_response import respond, FinalResponseDebug
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_cli import run as cli_run
from validation_corpus import VALIDATION_SCENARIOS, SCENARIO_BY_ID


# ---------------------------------------------------------------------------
# Shared stub infrastructure
# ---------------------------------------------------------------------------

class _StubBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMessage:
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    def __init__(self, response_json: str) -> None:
        self._json = response_json

    def create(self, **kwargs: Any) -> _StubMessage:
        return _StubMessage(self._json)


class _StubAnthropicClient:
    """Minimal stub satisfying the classifier_client interface."""
    def __init__(self, response_json: str) -> None:
        self.messages = _StubMessages(response_json)


# Pre-built stubs for each Phase 4k scenario
CAPTAIN_STUB = _StubAnthropicClient(
    '{"intent": "captain_score", '
    '"canonical_question": "should I captain Saka", '
    '"confidence": 0.92, "language": "en"}'
)
COMPARISON_STUB = _StubAnthropicClient(
    '{"intent": "compare_players", '
    '"canonical_question": "compare Salah and Haaland", '
    '"confidence": 0.88, "language": "en"}'
)
RANKING_STUB = _StubAnthropicClient(
    '{"intent": "rank_candidates", '
    '"canonical_question": "top captains this week", '
    '"confidence": 0.90, "language": "en"}'
)
LOW_CONF_STUB = _StubAnthropicClient(
    '{"intent": "captain_score", '
    '"canonical_question": "should I captain Saka", '
    '"confidence": 0.55, "language": "en"}'
)
BAD_JSON_STUB = _StubAnthropicClient("not valid json at all")
UNSUPPORTED_STUB = _StubAnthropicClient(
    '{"intent": "unsupported", '
    '"canonical_question": "some question", '
    '"confidence": 0.95, "language": "en"}'
)
# Stub that classifies but canonical_question still can't be routed
UNROUTABLE_STUB = _StubAnthropicClient(
    '{"intent": "captain_score", '
    '"canonical_question": "grfjlskdjflsdkfjsd", '
    '"confidence": 0.90, "language": "en"}'
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def check(cond: bool, label: str) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        print(f"  FAIL: {label}")


def section(name: str) -> None:
    print(f"\n{name}")


# ---------------------------------------------------------------------------
# Section A — intent_classifier module unit tests (16)
# ---------------------------------------------------------------------------

section("A — intent_classifier module")

# A1: module constants
check(_CONFIDENCE_THRESHOLD == 0.7, "A1: confidence threshold is 0.7")

# A2: CLASSIFIER_SYSTEM_PROMPT lists all 6 intents
for intent in ["captain_score", "rank_candidates", "compare_players",
               "player_summary", "player_resolve", "current_gameweek"]:
    check(intent in CLASSIFIER_SYSTEM_PROMPT, f"A2: system prompt mentions {intent}")

# A3: build_classifier_prompt includes the question
q = "is Saka worth captaining?"
prompt = build_classifier_prompt(q)
check(q in prompt, "A3: build_classifier_prompt includes the question")
check("Classify" in prompt or "classify" in prompt, "A3b: build_classifier_prompt has classify instruction")

# A4: _parse_classifier_response happy path
good_json = '{"intent": "captain_score", "canonical_question": "should I captain Saka", "confidence": 0.92, "language": "en"}'
parsed = _parse_classifier_response(good_json)
check(parsed is not None, "A4: parse succeeds on valid JSON")
check(parsed.intent == "captain_score", "A4b: parsed intent correct")
check(parsed.canonical_question == "should I captain Saka", "A4c: parsed canonical_question correct")
check(abs(parsed.confidence - 0.92) < 1e-9, "A4d: parsed confidence correct")
check(parsed.language == "en", "A4e: parsed language correct")

# A5: _parse_classifier_response failure paths
check(_parse_classifier_response("not json") is None, "A5: bad JSON returns None")
check(_parse_classifier_response('{"intent": "x"}') is None, "A5b: missing required keys returns None")

# A6: IntentClassification is frozen
cls = IntentClassification(intent="captain_score", canonical_question="q", confidence=0.9, language="en")
try:
    cls.intent = "other"  # type: ignore[misc]
    check(False, "A6: IntentClassification should be frozen")
except Exception:
    check(True, "A6: IntentClassification is frozen (immutable)")


# ---------------------------------------------------------------------------
# Section B — Stub behaviour (6)
# ---------------------------------------------------------------------------

section("B — Stub interface")

# B1: stub mimics anthropic.Anthropic().messages.create()
result = CAPTAIN_STUB.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=128,
    system="sys",
    messages=[{"role": "user", "content": "hi"}],
)
check(hasattr(result, "content"), "B1: stub result has .content")
check(len(result.content) > 0, "B1b: stub result.content is non-empty")
check(hasattr(result.content[0], "text"), "B1c: stub result.content[0] has .text")

# B2: classify_intent_llm uses the stub
classification = classify_intent_llm("is Saka worth captaining?", CAPTAIN_STUB)
check(classification is not None, "B2: classify_intent_llm returns non-None with valid stub")
check(classification.intent == "captain_score", "B2b: classification intent correct")
check(classification.canonical_question == "should I captain Saka", "B2c: canonical_question correct")


# ---------------------------------------------------------------------------
# Section C — Dispatcher integration (18)
# ---------------------------------------------------------------------------

section("C — Dispatcher integration")

BS = STANDARD_BOOTSTRAP

# C1: baseline — question that route() can't handle WITHOUT classifier
dr_no_cls = dispatch("is Saka worth captaining?", BS)
check(dr_no_cls.intent == INTENT_UNSUPPORTED, "C1: without classifier -> unsupported intent")
check(dr_no_cls.outcome == OUTCOME_UNSUPPORTED_INTENT, "C1b: outcome is unsupported_intent")
check(dr_no_cls.classification_source is None, "C1c: classification_source is None without classifier")

# C2: WITH captain classifier stub -> routed to captain_score
dr_cap = dispatch("is Saka worth captaining?", BS, classifier_client=CAPTAIN_STUB)
check(dr_cap.intent == INTENT_CAPTAIN_SCORE, "C2: captain classifier stub -> captain_score intent")
check(dr_cap.outcome == OUTCOME_OK, "C2b: captain classifier stub -> ok outcome")
check(dr_cap.classification_source == "llm_classifier", "C2c: classification_source == 'llm_classifier'")

# C3: WITH comparison classifier stub -> routed to compare_players
dr_cmp = dispatch(
    "what's the score differential between Salah and Haaland?", BS,
    classifier_client=COMPARISON_STUB,
)
check(dr_cmp.intent == INTENT_COMPARE_PLAYERS, "C3: comparison classifier stub -> compare_players intent")
check(dr_cmp.outcome == OUTCOME_OK, "C3b: comparison classifier stub -> ok outcome")
check(dr_cmp.classification_source == "llm_classifier", "C3c: classification_source == 'llm_classifier'")

# C4: WITH ranking classifier stub + candidates_list -> routed to rank_candidates
dr_rank = dispatch(
    "who looks best for captain this week?", BS,
    candidates_list=[{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}],
    classifier_client=RANKING_STUB,
)
check(dr_rank.intent == INTENT_RANK_CANDIDATES, "C4: ranking classifier stub -> rank_candidates intent")
check(dr_rank.outcome == OUTCOME_OK, "C4b: ranking classifier stub -> ok outcome (with candidates)")
check(dr_rank.classification_source == "llm_classifier", "C4c: classification_source == 'llm_classifier'")

# C5: low confidence stub -> still unsupported
dr_low = dispatch("is Saka worth captaining?", BS, classifier_client=LOW_CONF_STUB)
check(dr_low.intent == INTENT_UNSUPPORTED, "C5: low confidence -> unsupported")
check(dr_low.classification_source is None, "C5b: low confidence -> classification_source None")

# C6: bad JSON stub -> still unsupported
dr_bad = dispatch("is Saka worth captaining?", BS, classifier_client=BAD_JSON_STUB)
check(dr_bad.intent == INTENT_UNSUPPORTED, "C6: bad JSON -> unsupported")
check(dr_bad.classification_source is None, "C6b: bad JSON -> classification_source None")

# C7: unroutable canonical_question -> still unsupported
dr_unr = dispatch("is Saka worth captaining?", BS, classifier_client=UNROUTABLE_STUB)
check(dr_unr.intent == INTENT_UNSUPPORTED, "C7: unroutable canonical -> unsupported")
check(dr_unr.classification_source is None, "C7b: unroutable canonical -> classification_source None")


# ---------------------------------------------------------------------------
# Section D — Full stack via respond() (14)
# ---------------------------------------------------------------------------

section("D — Full stack via respond()")

# D1: captain natural phrasing -> FinalResponse with captain metadata
fr_cap = respond(
    "is Saka worth captaining?", BS,
    classifier_client=CAPTAIN_STUB,
    include_debug=True,
)
check(fr_cap.intent == INTENT_CAPTAIN_SCORE, "D1: respond() captain intent")
check(fr_cap.outcome == OUTCOME_OK, "D1b: respond() captain outcome ok")
check(fr_cap.supported is True, "D1c: respond() captain supported")
check(fr_cap.captain is not None, "D1d: respond() captain metadata present")
check(fr_cap.debug is not None, "D1e: debug bundle present with include_debug=True")
check(
    fr_cap.debug is not None and fr_cap.debug.classification_source == "llm_classifier",
    "D1f: debug.classification_source == 'llm_classifier'"
)

# D2: comparison natural phrasing -> FinalResponse with comparison metadata
fr_cmp = respond(
    "what's the score differential between Salah and Haaland?", BS,
    classifier_client=COMPARISON_STUB,
    include_debug=True,
)
check(fr_cmp.intent == INTENT_COMPARE_PLAYERS, "D2: respond() comparison intent")
check(fr_cmp.outcome == OUTCOME_OK, "D2b: respond() comparison outcome ok")
check(fr_cmp.comparison is not None, "D2c: respond() comparison metadata present")
check(
    fr_cmp.debug is not None and fr_cmp.debug.classification_source == "llm_classifier",
    "D2d: comparison debug.classification_source == 'llm_classifier'"
)

# D3: ranking natural phrasing + candidates -> FinalResponse with captain_ranking
fr_rank = respond(
    "who looks best for captain this week?", BS,
    candidates_list=[{"query": "Salah"}, {"query": "Haaland"}, {"query": "Saka"}],
    classifier_client=RANKING_STUB,
    include_debug=True,
)
check(fr_rank.intent == INTENT_RANK_CANDIDATES, "D3: respond() ranking intent")
check(fr_rank.captain_ranking is not None, "D3b: respond() captain_ranking present")
check(len(fr_rank.captain_ranking) >= 1, "D3c: captain_ranking has entries")
check(
    fr_rank.debug is not None and fr_rank.debug.classification_source == "llm_classifier",
    "D3d: ranking debug.classification_source == 'llm_classifier'"
)

# D4: classification_source None when deterministic routing succeeds
fr_det = respond("should I captain Salah", BS, include_debug=True)
check(fr_det.intent == INTENT_CAPTAIN_SCORE, "D4: deterministic routing still works")
check(
    fr_det.debug is not None and fr_det.debug.classification_source is None,
    "D4b: classification_source None when deterministic routing used"
)


# ---------------------------------------------------------------------------
# Section E — CLI integration via run() (14)
# ---------------------------------------------------------------------------

section("E — CLI integration via run()")

# E1: captain natural phrasing via CLI
exit_code, output = cli_run(
    "is Saka worth captaining?", BS,
    debug=True,
    classifier_client=CAPTAIN_STUB,
)
check(exit_code == 0, "E1: captain CLI exit_code 0 (supported)")
body: dict = {}
try:
    body = json.loads(output)
except Exception:
    pass
check(body.get("intent") == "captain_score", "E1b: CLI captain intent")
check(body.get("outcome") == "ok", "E1c: CLI captain outcome ok")
check(body.get("captain") is not None, "E1d: CLI captain metadata present")
check(body.get("debug", {}).get("classification_source") == "llm_classifier", "E1e: CLI classification_source in debug")

# E2: comparison natural phrasing via CLI
exit_code2, output2 = cli_run(
    "what's the score differential between Salah and Haaland?", BS,
    debug=True,
    classifier_client=COMPARISON_STUB,
)
check(exit_code2 == 0, "E2: comparison CLI exit_code 0")
body2: dict = {}
try:
    body2 = json.loads(output2)
except Exception:
    pass
check(body2.get("intent") == "compare_players", "E2b: CLI comparison intent")
check(body2.get("comparison") is not None, "E2c: CLI comparison metadata present")
check(body2.get("debug", {}).get("classification_source") == "llm_classifier", "E2d: CLI comparison classification_source")

# E3: without classifier, same question is unsupported
exit_code3, output3 = cli_run("is Saka worth captaining?", BS, debug=True)
check(exit_code3 == 1, "E3: without classifier, natural phrasing -> exit_code 1")
body3: dict = {}
try:
    body3 = json.loads(output3)
except Exception:
    pass
check(body3.get("intent") == "unsupported", "E3b: without classifier -> unsupported intent")
check(body3.get("debug", {}).get("classification_source") is None, "E3c: no classification_source without classifier")

# E4: classification_source absent from non-debug output
exit_code4, output4 = cli_run("is Saka worth captaining?", BS, classifier_client=CAPTAIN_STUB)
check(exit_code4 == 0, "E4: captain non-debug exit_code 0")
check("classification_source" not in output4, "E4b: classification_source not in plain-text output")


# ---------------------------------------------------------------------------
# Section F — Regression: deterministic routing unchanged (12)
# ---------------------------------------------------------------------------

section("F — Regression: deterministic routing unchanged")

DET_CASES = [
    ("should I captain Salah", INTENT_CAPTAIN_SCORE, OUTCOME_OK),
    ("compare Haaland and Salah", INTENT_COMPARE_PLAYERS, OUTCOME_OK),
    ("who is Haaland", "player_resolve", OUTCOME_OK),
    ("tell me about Saka", INTENT_PLAYER_SUMMARY, OUTCOME_OK),
]

for q_det, exp_intent, exp_outcome in DET_CASES:
    # Without classifier
    dr_det = dispatch(q_det, BS)
    check(dr_det.intent == exp_intent, f"F: '{q_det}' -> intent={exp_intent} (no classifier)")
    check(dr_det.classification_source is None, f"F: '{q_det}' -> classification_source None (no classifier)")
    # With classifier — deterministic routing still wins, no classification needed
    dr_with = dispatch(q_det, BS, classifier_client=CAPTAIN_STUB)
    check(dr_with.intent == exp_intent, f"F: '{q_det}' -> intent unchanged WITH classifier")
    check(dr_with.classification_source is None, f"F: '{q_det}' -> classification_source None WITH classifier")


# ---------------------------------------------------------------------------
# Section G — Fallback safety (12)
# ---------------------------------------------------------------------------

section("G — Fallback safety")

# G1: None classifier_client -> unsupported, no error
dr_none = dispatch("is Saka worth captaining?", BS, classifier_client=None)
check(dr_none.intent == INTENT_UNSUPPORTED, "G1: None classifier -> unsupported")
check(dr_none.classification_source is None, "G1b: None classifier -> classification_source None")

# G2: low confidence -> fallback to unsupported
dr_low2 = dispatch("is Saka worth captaining?", BS, classifier_client=LOW_CONF_STUB)
check(dr_low2.outcome == OUTCOME_UNSUPPORTED_INTENT, "G2: low confidence -> outcome unsupported_intent")

# G3: bad JSON -> fallback to unsupported, no exception
dr_bad2 = dispatch("is Saka worth captaining?", BS, classifier_client=BAD_JSON_STUB)
check(dr_bad2.outcome == OUTCOME_UNSUPPORTED_INTENT, "G3: bad JSON -> outcome unsupported_intent")

# G4: classifier returns but canonical_question doesn't route -> fallback
dr_unr2 = dispatch("is Saka worth captaining?", BS, classifier_client=UNROUTABLE_STUB)
check(dr_unr2.outcome == OUTCOME_UNSUPPORTED_INTENT, "G4: unroutable canonical -> fallback to unsupported")

# G5: respond() never raises with bad classifier_client
class _ErrorClient:
    """Client that always raises on .messages.create()."""
    class messages:
        @staticmethod
        def create(**kwargs: Any) -> None:
            raise RuntimeError("network error")

try:
    fr_err = respond("is Saka worth captaining?", BS, classifier_client=_ErrorClient())
    check(fr_err.intent == INTENT_UNSUPPORTED, "G5: error client -> unsupported intent")
    check(True, "G5b: respond() did not raise with error client")
except Exception as exc:
    check(False, f"G5: respond() raised unexpectedly: {exc}")

# G6: ranking without candidates_list -> missing_arguments even with classifier
dr_rank_no_cands = dispatch(
    "who looks best for captain this week?", BS,
    classifier_client=RANKING_STUB,
)
check(dr_rank_no_cands.intent == INTENT_RANK_CANDIDATES, "G6: ranking classified correctly")
check(dr_rank_no_cands.outcome == OUTCOME_MISSING_ARGUMENTS, "G6b: without candidates -> missing_arguments")
check(dr_rank_no_cands.classification_source == "llm_classifier", "G6c: classification_source still set even on missing_args")


# ---------------------------------------------------------------------------
# Section H — Validation corpus (8)
# ---------------------------------------------------------------------------

section("H — Validation corpus")

PHASE4K_IDS = ["natural_captain_phrasing", "natural_comparison_phrasing", "natural_ranking_phrasing"]

# H1: 3 new scenarios present in corpus
all_ids = [s.id for s in VALIDATION_SCENARIOS]
for sid in PHASE4K_IDS:
    check(sid in all_ids, f"H1: scenario '{sid}' in corpus")

# H2: all 3 are family='llm_classify'
for sid in PHASE4K_IDS:
    s = SCENARIO_BY_ID[sid]
    check(s.family == "llm_classify", f"H2: '{sid}' family == 'llm_classify'")

# H3: all 3 have requires_stub='classifier' and classifier_stub_json
for sid in PHASE4K_IDS:
    s = SCENARIO_BY_ID[sid]
    check(s.requires_stub == "classifier", f"H3: '{sid}' requires_stub == 'classifier'")
    check(s.classifier_stub_json is not None, f"H3b: '{sid}' classifier_stub_json is not None")
    # Validate it's parseable JSON
    try:
        data = json.loads(s.classifier_stub_json)
        check("intent" in data and "canonical_question" in data, f"H3c: '{sid}' stub JSON has required keys")
    except json.JSONDecodeError:
        check(False, f"H3c: '{sid}' classifier_stub_json is invalid JSON")

# H4: all 3 now include all 4 surfaces (updated by Phase 4l)
_EXPECTED_4L_SURFACES = ("cli", "http", "session_cli", "session_http")
for sid in PHASE4K_IDS:
    s = SCENARIO_BY_ID[sid]
    check(
        all(surf in s.surfaces for surf in _EXPECTED_4L_SURFACES),
        f"H4: '{sid}' includes all 4 surfaces",
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _PASS + _FAIL
print(f"\n{'='*50}")
print(f"Phase 4k: {_PASS}/{total} PASS")
if _FAIL:
    print(f"          {_FAIL} FAIL")
    sys.exit(1)
else:
    print("          All assertions passed.")
    sys.exit(0)
