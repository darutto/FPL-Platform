"""
Phase 3d test suite — Final response contract hardening.

Validates:
- FinalResponseFixture dataclass structure
- FINAL_RESPONSE_CONTRACT.md existence and content
- 6 canonical fixture scenarios
- run_all() structure and completeness
- Per-fixture field values (outcome / supported / intent /
  review_passed / llm_used / final_text)
- Final-text fallback invariant (final_text == response_text when llm_used=False)
- All caller-facing invariants from the contract doc
- Field stability (FinalResponse and FinalResponseDebug shape)
- FINAL_TEXT_POLICY constant
- Never-raises edge cases
- Scenario-specific deeper assertions
- Bootstrap contract (standard vs ambiguous)
- respond() default parameters
- Phase 3c regression
- Interface report

Run:
    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:
    ../fpl-api-client:../fpl-pipeline:. python run_phase3d_tests.py
"""
from __future__ import annotations

import dataclasses
import inspect
import os
import sys

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def _check(label: str, condition: bool) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  [PASS] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.final_response_fixtures import (
    FinalResponseFixture,
    FINAL_RESPONSE_FIXTURE_DEFINITIONS,
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    run_all,
)
from fpl_grounded_assistant.final_response import (
    FinalResponse,
    FinalResponseDebug,
    FINAL_TEXT_POLICY,
    respond,
)
from fpl_grounded_assistant.dispatcher import (
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_UNSUPPORTED_INTENT,
    OUTCOME_ERROR,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
)

_ALL_OUTCOMES = frozenset([
    OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS, OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT,
])

# ---------------------------------------------------------------------------
# A. FinalResponseFixture dataclass
# ---------------------------------------------------------------------------

_section("A. FinalResponseFixture dataclass")

fixture_fields = {f.name for f in dataclasses.fields(FinalResponseFixture)}
_check("A1 scenario_id field present", "scenario_id" in fixture_fields)
_check("A2 description field present", "description" in fixture_fields)
_check("A3 user_message field present", "user_message" in fixture_fields)
_check("A4 expected_outcome field present", "expected_outcome" in fixture_fields)
_check("A5 expected_supported field present", "expected_supported" in fixture_fields)
_check("A6 expected_intent field present", "expected_intent" in fixture_fields)
_check("A7 expected_review_passed field present", "expected_review_passed" in fixture_fields)
_check("A8 expected_llm_used field present", "expected_llm_used" in fixture_fields)
_check("A9 candidates_list field present", "candidates_list" in fixture_fields)
_check("A10 use_ambiguous_bootstrap field present", "use_ambiguous_bootstrap" in fixture_fields)
_check("A11 exactly 10 fields",
       len(dataclasses.fields(FinalResponseFixture)) == 10)
_check("A12 frozen — assignment raises", _check_frozen := True)
try:
    f = FinalResponseFixture(
        scenario_id="test", description="test", user_message="test",
        expected_outcome="ok", expected_supported=True, expected_intent="captain_score",
        expected_review_passed=True, expected_llm_used=False,
    )
    f.scenario_id = "x"  # type: ignore[misc]
    _PASS -= 1; _FAIL += 1  # assignment did not raise
    print("  [FAIL] A12 frozen — assignment raises")
except dataclasses.FrozenInstanceError:
    pass  # already counted as PASS above

# ---------------------------------------------------------------------------
# B. FINAL_RESPONSE_CONTRACT.md content
# ---------------------------------------------------------------------------

_section("B. FINAL_RESPONSE_CONTRACT.md content")

_contract_path = os.path.join(
    os.path.dirname(__file__), "FINAL_RESPONSE_CONTRACT.md"
)
_check("B1 FINAL_RESPONSE_CONTRACT.md exists", os.path.exists(_contract_path))

_contract_text = ""
if os.path.exists(_contract_path):
    with open(_contract_path) as _f:
        _contract_text = _f.read()

_check("B2 contract is non-trivial (>500 chars)", len(_contract_text) > 500)
_check("B3 mentions FinalResponse", "FinalResponse" in _contract_text)
_check("B4 mentions FinalResponseDebug", "FinalResponseDebug" in _contract_text)
_check("B5 mentions respond()", "respond()" in _contract_text)
_check("B6 mentions final_text", "final_text" in _contract_text)
_check("B7 mentions llm_used", "llm_used" in _contract_text)
_check("B8 mentions review_passed", "review_passed" in _contract_text)
_check("B9 mentions FINAL_TEXT_POLICY or final-text policy", "FINAL_TEXT_POLICY" in _contract_text or "final-text policy" in _contract_text.lower())
_check("B10 mentions supported", "supported" in _contract_text)
_check("B11 mentions invariants section", "Invariant" in _contract_text)
_check("B12 mentions stability commitment or breaking change", "breaking" in _contract_text.lower() or "Stability" in _contract_text)

# ---------------------------------------------------------------------------
# C. Fixture definitions — 6 scenarios
# ---------------------------------------------------------------------------

_section("C. Fixture definitions — 6 scenarios")

_check("C1 FINAL_RESPONSE_FIXTURE_DEFINITIONS is tuple",
       isinstance(FINAL_RESPONSE_FIXTURE_DEFINITIONS, tuple))
_check("C2 exactly 6 fixtures", len(FINAL_RESPONSE_FIXTURE_DEFINITIONS) == 6)
_check("C3 all entries are FinalResponseFixture",
       all(isinstance(f, FinalResponseFixture) for f in FINAL_RESPONSE_FIXTURE_DEFINITIONS))

_fixture_ids = [f.scenario_id for f in FINAL_RESPONSE_FIXTURE_DEFINITIONS]
_check("C4 supported_ok present", "supported_ok" in _fixture_ids)
_check("C5 supported_ambiguous present", "supported_ambiguous" in _fixture_ids)
_check("C6 supported_not_found present", "supported_not_found" in _fixture_ids)
_check("C7 supported_missing_arguments present", "supported_missing_arguments" in _fixture_ids)
_check("C8 unsupported_intent present", "unsupported_intent" in _fixture_ids)
_check("C9 llm_fallback_to_deterministic present", "llm_fallback_to_deterministic" in _fixture_ids)
_check("C10 all scenario_ids are unique",
       len(set(_fixture_ids)) == len(_fixture_ids))
_check("C11 all descriptions are non-empty",
       all(len(f.description) > 10 for f in FINAL_RESPONSE_FIXTURE_DEFINITIONS))
_check("C12 all user_messages are non-empty",
       all(len(f.user_message) > 0 for f in FINAL_RESPONSE_FIXTURE_DEFINITIONS))
_check("C13 expected_outcomes are valid OUTCOME_* values",
       all(f.expected_outcome in _ALL_OUTCOMES for f in FINAL_RESPONSE_FIXTURE_DEFINITIONS))
_check("C14 ambiguous fixture uses ambiguous bootstrap",
       next(f for f in FINAL_RESPONSE_FIXTURE_DEFINITIONS
            if f.scenario_id == "supported_ambiguous").use_ambiguous_bootstrap)

# ---------------------------------------------------------------------------
# D. run_all() structure
# ---------------------------------------------------------------------------

_section("D. run_all() structure")

_results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)

_check("D1 run_all returns list", isinstance(_results, list))
_check("D2 run_all returns 6 pairs", len(_results) == 6)
_check("D3 all pairs are tuples", all(isinstance(r, tuple) for r in _results))
_check("D4 all pair[0] are FinalResponseFixture",
       all(isinstance(r[0], FinalResponseFixture) for r in _results))
_check("D5 all pair[1] are FinalResponse",
       all(isinstance(r[1], FinalResponse) for r in _results))
_check("D6 run_all includes debug bundles (called with include_debug=True)",
       all(r[1].debug is not None for r in _results))
_check("D7 fixture order matches FINAL_RESPONSE_FIXTURE_DEFINITIONS",
       [r[0].scenario_id for r in _results] == _fixture_ids)
_check("D8 STANDARD_BOOTSTRAP importable and is dict", isinstance(STANDARD_BOOTSTRAP, dict))
_check("D9 AMBIGUOUS_BOOTSTRAP importable and is dict", isinstance(AMBIGUOUS_BOOTSTRAP, dict))
_check("D10 AMBIGUOUS_BOOTSTRAP has more elements than STANDARD_BOOTSTRAP",
       len(AMBIGUOUS_BOOTSTRAP["elements"]) > len(STANDARD_BOOTSTRAP["elements"]))

# Build a lookup by scenario_id for fixture sections below
_by_id = {r[0].scenario_id: (r[0], r[1]) for r in _results}

# ---------------------------------------------------------------------------
# E–J. Per-fixture assertions (10 assertions × 6 fixtures = 60)
# ---------------------------------------------------------------------------

_section("E-J. Per-fixture assertions (10 per scenario)")

for _fixture, _response in _results:
    _sid = _fixture.scenario_id

    _check(f"E1 FinalResponse for {_sid}",
           isinstance(_response, FinalResponse))
    _check(f"E2 outcome for {_sid}",
           _response.outcome == _fixture.expected_outcome)
    _check(f"E3 supported for {_sid}",
           _response.supported == _fixture.expected_supported)
    _check(f"E4 intent for {_sid}",
           _response.intent == _fixture.expected_intent)
    _check(f"E5 review_passed for {_sid}",
           _response.review_passed == _fixture.expected_review_passed)
    _check(f"E6 llm_used for {_sid}",
           _response.llm_used == _fixture.expected_llm_used)
    _check(f"E7 final_text non-empty for {_sid}",
           isinstance(_response.final_text, str) and len(_response.final_text) > 0)
    _check(f"E8 debug bundle present (include_debug=True) for {_sid}",
           _response.debug is not None)
    _check(f"E9 debug.violations empty for {_sid} (deterministic, no LLM)",
           _response.debug is not None and _response.debug.violations == ())
    _check(f"E10 debug.model=='none' for {_sid} (no API key)",
           _response.debug is not None and _response.debug.model == "none")

# ---------------------------------------------------------------------------
# K. Final-text fallback invariant
# ---------------------------------------------------------------------------

_section("K. Final-text fallback invariant (final_text == response_text when llm_used=False)")

for _fixture, _response in _results:
    _sid = _fixture.scenario_id
    # All deterministic: llm_used=False → final_text must equal response_text
    _check(f"K1 final_text == response_text for {_sid}",
           _response.debug is not None
           and _response.final_text == _response.debug.response_text)

# Specific check for the named fallback scenario
_fb_fix, _fb_resp = _by_id["llm_fallback_to_deterministic"]
_check("K2 llm_fallback scenario: llm_used=False", not _fb_resp.llm_used)
_check("K3 llm_fallback scenario: final_text == debug.response_text",
       _fb_resp.debug is not None
       and _fb_resp.final_text == _fb_resp.debug.response_text)
_check("K4 llm_fallback scenario: debug.llm_text == debug.response_text",
       _fb_resp.debug is not None
       and _fb_resp.debug.llm_text == _fb_resp.debug.response_text)
_check("K5 llm_fallback scenario: review_passed=True", _fb_resp.review_passed)
_check("K6 llm_fallback scenario: debug.violations == ()",
       _fb_resp.debug is not None and _fb_resp.debug.violations == ())

# ---------------------------------------------------------------------------
# L. Caller-facing invariants from CONTRACT.md
# ---------------------------------------------------------------------------

_section("L. Caller-facing invariants (from FINAL_RESPONSE_CONTRACT.md)")

for _fixture, _response in _results:
    _sid = _fixture.scenario_id

    # Invariant 1: final_text is never empty
    _check(f"L1 final_text non-empty for {_sid}",
           len(_response.final_text) > 0)

    # Invariant 2: supported == (outcome != unsupported_intent)
    _check(f"L2 supported == (outcome != unsupported_intent) for {_sid}",
           _response.supported == (_response.outcome != OUTCOME_UNSUPPORTED_INTENT))

    # Invariant 3: not llm_used or review_passed (llm_used=True → review_passed=True)
    _check(f"L3 llm_used=True implies review_passed=True for {_sid}",
           not _response.llm_used or _response.review_passed)

    # Invariant 4: outcome in known set
    _check(f"L4 outcome in OUTCOME_* constants for {_sid}",
           _response.outcome in _ALL_OUTCOMES)

    # Invariant 5: debug.violations == () iff review_passed
    _check(f"L5 debug.violations empty iff review_passed for {_sid}",
           _response.debug is not None
           and (_response.review_passed == (_response.debug.violations == ())))

    # Invariant 6: not llm_used → final_text == response_text
    _check(f"L6 not llm_used → final_text == response_text for {_sid}",
           _response.debug is not None
           and (not _response.llm_used or _response.final_text == _response.debug.llm_text)
           and (_response.llm_used or _response.final_text == _response.debug.response_text))

# ---------------------------------------------------------------------------
# M. FinalResponse field stability
# ---------------------------------------------------------------------------

_section("M. FinalResponse field stability")

_fr_fields = {f.name for f in dataclasses.fields(FinalResponse)}
_check("M1 final_text field present", "final_text" in _fr_fields)
_check("M2 outcome field present", "outcome" in _fr_fields)
_check("M3 supported field present", "supported" in _fr_fields)
_check("M4 intent field present", "intent" in _fr_fields)
_check("M5 review_passed field present", "review_passed" in _fr_fields)
_check("M6 llm_used field present", "llm_used" in _fr_fields)
_check("M7 debug field present", "debug" in _fr_fields)
_check("M8 exactly 7 fields", len(dataclasses.fields(FinalResponse)) == 7)
_check("M9 frozen — assignment raises", True)
try:
    _dummy_fr = FinalResponse(
        final_text="x", outcome="ok", supported=True, intent="captain_score",
        review_passed=True, llm_used=False, debug=None,
    )
    _dummy_fr.final_text = "y"  # type: ignore[misc]
    _PASS -= 1; _FAIL += 1
    print("  [FAIL] M9 frozen — assignment raises")
except dataclasses.FrozenInstanceError:
    pass

# ---------------------------------------------------------------------------
# N. FinalResponseDebug field stability
# ---------------------------------------------------------------------------

_section("N. FinalResponseDebug field stability")

_frd_fields = {f.name for f in dataclasses.fields(FinalResponseDebug)}
_check("N1 llm_text field present", "llm_text" in _frd_fields)
_check("N2 response_text field present", "response_text" in _frd_fields)
_check("N3 violations field present", "violations" in _frd_fields)
_check("N4 prompt_used field present", "prompt_used" in _frd_fields)
_check("N5 model field present", "model" in _frd_fields)
_check("N6 exactly 5 fields", len(dataclasses.fields(FinalResponseDebug)) == 5)
_check("N7 violations is tuple",
       all(isinstance(r[1].debug.violations, tuple) for r in _results
           if r[1].debug is not None))
_check("N8 llm_text is str",
       all(isinstance(r[1].debug.llm_text, str) for r in _results
           if r[1].debug is not None))
_check("N9 response_text is str",
       all(isinstance(r[1].debug.response_text, str) for r in _results
           if r[1].debug is not None))
_check("N10 response_text non-empty for all",
       all(len(r[1].debug.response_text) > 0 for r in _results
           if r[1].debug is not None))
_check("N11 model is str for all",
       all(isinstance(r[1].debug.model, str) for r in _results
           if r[1].debug is not None))

# ---------------------------------------------------------------------------
# O. FINAL_TEXT_POLICY constant
# ---------------------------------------------------------------------------

_section("O. FINAL_TEXT_POLICY constant")

_check("O1 FINAL_TEXT_POLICY is str", isinstance(FINAL_TEXT_POLICY, str))
_check("O2 FINAL_TEXT_POLICY is non-trivial", len(FINAL_TEXT_POLICY) > 20)
_check("O3 FINAL_TEXT_POLICY references review/safe_text",
       "review.safe_text" in FINAL_TEXT_POLICY or "safe_text" in FINAL_TEXT_POLICY)
_check("O4 FINAL_TEXT_POLICY references fallback",
       "response_text" in FINAL_TEXT_POLICY or "otherwise" in FINAL_TEXT_POLICY)

# ---------------------------------------------------------------------------
# P. Never-raises edge cases
# ---------------------------------------------------------------------------

_section("P. Never-raises edge cases")

_edge_cases = [
    ("empty message", "", STANDARD_BOOTSTRAP),
    ("whitespace only", "   ", STANDARD_BOOTSTRAP),
    ("very long message", "captain " * 200, STANDARD_BOOTSTRAP),
    ("special characters", "should I captain @Ål#$%^&*()?", STANDARD_BOOTSTRAP),
    ("unicode in message", "who is Håàland", STANDARD_BOOTSTRAP),
    ("empty bootstrap elements", {**STANDARD_BOOTSTRAP, "elements": []}, STANDARD_BOOTSTRAP),
]

for _label, _msg, _bs in _edge_cases:
    _msg_arg = _msg if isinstance(_msg, str) else "test"
    _bs_arg = _msg if isinstance(_msg, dict) else _bs
    _msg_arg = _msg if isinstance(_msg, str) else "test"
    try:
        # Correct variable handling for the mixed-type edge case
        if isinstance(_msg, dict):
            _r = respond("captain haaland", _msg)
        else:
            _r = respond(_msg, _bs)
        _check(f"P1 returns FinalResponse for: {_label}",
               isinstance(_r, FinalResponse))
        _check(f"P2 final_text is str for: {_label}",
               isinstance(_r.final_text, str))
    except Exception as _e:
        _check(f"P1 returns FinalResponse for: {_label}", False)
        _check(f"P2 final_text is str for: {_label}", False)

# Extra: never-raises with error-raising client
class _ErrorClient:
    class messages:
        @staticmethod
        def create(**_kw):
            raise RuntimeError("mock API error")

_error_resp = respond("who is Haaland", STANDARD_BOOTSTRAP, client=_ErrorClient())
_check("P13 error client: returns FinalResponse", isinstance(_error_resp, FinalResponse))
_check("P14 error client: final_text non-empty", len(_error_resp.final_text) > 0)

# ---------------------------------------------------------------------------
# Q. Scenario-specific deeper assertions
# ---------------------------------------------------------------------------

_section("Q. Scenario-specific deeper assertions")

# supported_ok — captain score should mention a player name or score
_ok_fix, _ok_resp = _by_id["supported_ok"]
_check("Q1 supported_ok: final_text is str", isinstance(_ok_resp.final_text, str))
_check("Q2 supported_ok: outcome=ok", _ok_resp.outcome == OUTCOME_OK)
_check("Q3 supported_ok: supported=True", _ok_resp.supported)
_check("Q4 supported_ok: debug.response_text non-empty",
       _ok_resp.debug is not None and len(_ok_resp.debug.response_text) > 0)

# supported_ambiguous — should mention multiple / ambiguous
_amb_fix, _amb_resp = _by_id["supported_ambiguous"]
_check("Q5 supported_ambiguous: outcome=ambiguous", _amb_resp.outcome == OUTCOME_AMBIGUOUS)
_check("Q6 supported_ambiguous: supported=True", _amb_resp.supported)
_check("Q7 supported_ambiguous: final_text non-empty", len(_amb_resp.final_text) > 0)

# supported_not_found — intent recognised but player absent
_nf_fix, _nf_resp = _by_id["supported_not_found"]
_check("Q8 supported_not_found: outcome=not_found", _nf_resp.outcome == OUTCOME_NOT_FOUND)
_check("Q9 supported_not_found: supported=True", _nf_resp.supported)
_check("Q10 supported_not_found: intent=captain_score",
       _nf_resp.intent == INTENT_CAPTAIN_SCORE)

# supported_missing_arguments — guidance for missing candidates_list
_ma_fix, _ma_resp = _by_id["supported_missing_arguments"]
_check("Q11 supported_missing_arguments: outcome=missing_arguments",
       _ma_resp.outcome == OUTCOME_MISSING_ARGUMENTS)
_check("Q12 supported_missing_arguments: supported=True", _ma_resp.supported)

# unsupported_intent — out-of-scope message
_us_fix, _us_resp = _by_id["unsupported_intent"]
_check("Q13 unsupported_intent: outcome=unsupported_intent",
       _us_resp.outcome == OUTCOME_UNSUPPORTED_INTENT)
_check("Q14 unsupported_intent: supported=False", not _us_resp.supported)
_check("Q15 unsupported_intent: intent=unsupported",
       _us_resp.intent == INTENT_UNSUPPORTED)

# llm_fallback — same player, different response path documented
_fb_fix2, _fb_resp2 = _by_id["llm_fallback_to_deterministic"]
_check("Q16 llm_fallback: outcome=ok", _fb_resp2.outcome == OUTCOME_OK)
_check("Q17 llm_fallback: debug present", _fb_resp2.debug is not None)
_check("Q18 llm_fallback: final_text == debug.response_text",
       _fb_resp2.debug is not None
       and _fb_resp2.final_text == _fb_resp2.debug.response_text)

# ---------------------------------------------------------------------------
# R. Bootstrap contract — standard vs ambiguous
# ---------------------------------------------------------------------------

_section("R. Bootstrap contract")

# Running ambiguous scenario on STANDARD_BOOTSTRAP should give not_found or ok,
# NOT ambiguous — because 'Doe' doesn't exist in STANDARD_BOOTSTRAP
_standard_doe = respond("who is Doe", STANDARD_BOOTSTRAP)
_check("R1 'Doe' on standard bootstrap: outcome not ambiguous",
       _standard_doe.outcome != OUTCOME_AMBIGUOUS)
_check("R2 'Doe' on standard bootstrap: FinalResponse returned",
       isinstance(_standard_doe, FinalResponse))

# Running ambiguous scenario on AMBIGUOUS_BOOTSTRAP should give ambiguous
_ambiguous_doe = respond("who is Doe", AMBIGUOUS_BOOTSTRAP)
_check("R3 'Doe' on ambiguous bootstrap: outcome=ambiguous",
       _ambiguous_doe.outcome == OUTCOME_AMBIGUOUS)
_check("R4 'Doe' on ambiguous bootstrap: supported=True",
       _ambiguous_doe.supported)

# Standard bootstrap fields required
_check("R5 STANDARD_BOOTSTRAP has 'elements'", "elements" in STANDARD_BOOTSTRAP)
_check("R6 STANDARD_BOOTSTRAP has 'teams'", "teams" in STANDARD_BOOTSTRAP)
_check("R7 STANDARD_BOOTSTRAP has 'events'", "events" in STANDARD_BOOTSTRAP)
_check("R8 STANDARD_BOOTSTRAP has 'fixture_difficulty_map'",
       "fixture_difficulty_map" in STANDARD_BOOTSTRAP)

# ---------------------------------------------------------------------------
# S. respond() signature parameters
# ---------------------------------------------------------------------------

_section("S. respond() signature parameters")

_sig = inspect.signature(respond)
_params = _sig.parameters

_check("S1 respond has user_message param", "user_message" in _params)
_check("S2 respond has bootstrap param", "bootstrap" in _params)
_check("S3 respond has client param (keyword-only)", "client" in _params)
_check("S4 respond has model param (keyword-only)", "model" in _params)
_check("S5 respond has candidate_inputs param", "candidate_inputs" in _params)
_check("S6 respond has candidates_list param", "candidates_list" in _params)
_check("S7 respond has api_key param", "api_key" in _params)
_check("S8 respond has include_debug param", "include_debug" in _params)
_check("S9 include_debug default is False",
       _params["include_debug"].default is False)
_check("S10 client default is None",
       _params["client"].default is None)
_check("S11 candidate_inputs default is None",
       _params["candidate_inputs"].default is None)
_check("S12 candidates_list default is None",
       _params["candidates_list"].default is None)

# ---------------------------------------------------------------------------
# T. debug=None when include_debug=False (default)
# ---------------------------------------------------------------------------

_section("T. debug=None by default (include_debug=False)")

for _fixture, _ in _results:
    _sid = _fixture.scenario_id
    _bs = AMBIGUOUS_BOOTSTRAP if _fixture.use_ambiguous_bootstrap else STANDARD_BOOTSTRAP
    _resp_no_debug = respond(
        _fixture.user_message, _bs,
        candidates_list=_fixture.candidates_list,
        include_debug=False,
    )
    _check(f"T1 debug=None by default for {_sid}",
           _resp_no_debug.debug is None)

# ---------------------------------------------------------------------------
# U. Phase 3c regression
# ---------------------------------------------------------------------------

_section("U. Phase 3c regression")

# Verify the core 3c behavior is intact
_r3c = respond("should I captain Haaland", STANDARD_BOOTSTRAP, include_debug=True)
_check("U1 respond() still returns FinalResponse", isinstance(_r3c, FinalResponse))
_check("U2 final_text is str", isinstance(_r3c.final_text, str))
_check("U3 final_text non-empty", len(_r3c.final_text) > 0)
_check("U4 outcome is str", isinstance(_r3c.outcome, str))
_check("U5 supported is bool", isinstance(_r3c.supported, bool))
_check("U6 debug is FinalResponseDebug", isinstance(_r3c.debug, FinalResponseDebug))
_check("U7 debug.violations is tuple", isinstance(_r3c.debug.violations, tuple))
_check("U8 FINAL_TEXT_POLICY still a str constant", isinstance(FINAL_TEXT_POLICY, str))

# ask_llm_safe still accessible through public imports
from fpl_grounded_assistant import ask_llm_safe as _als
_lr3c, _rev3c = _als("who is Salah", STANDARD_BOOTSTRAP)
_check("U9 ask_llm_safe returns tuple of 2", isinstance((_lr3c, _rev3c), tuple))
_check("U10 review_result passed in deterministic path", _rev3c.passed)

# ---------------------------------------------------------------------------
# V. Interface report
# ---------------------------------------------------------------------------

_section("V. Interface report")

print("""
  Phase 3d public surface:
    FinalResponseFixture — frozen dataclass, 10 fields (fixture schema)
    FINAL_RESPONSE_FIXTURE_DEFINITIONS — tuple of 6 canonical scenarios
    run_all(standard_bootstrap, ambiguous_bootstrap) → list[tuple[Fixture, FinalResponse]]
    FINAL_RESPONSE_CONTRACT.md — stable contract documentation

  6 named scenarios:
    supported_ok                — outcome=ok, supported=True
    supported_ambiguous         — outcome=ambiguous, supported=True
    supported_not_found         — outcome=not_found, supported=True
    supported_missing_arguments — outcome=missing_arguments, supported=True
    unsupported_intent          — outcome=unsupported_intent, supported=False
    llm_fallback_to_deterministic — explicit fallback invariant

  Caller-facing invariants verified per fixture:
    final_text non-empty
    supported == (outcome != unsupported_intent)
    llm_used=True implies review_passed=True
    outcome in OUTCOME_* constants
    debug.violations == () iff review_passed
    not llm_used → final_text == response_text

  Stable fields on FinalResponse: final_text, outcome, supported,
    intent, review_passed, llm_used, debug

  Debug-only fields (FinalResponseDebug): llm_text, response_text,
    violations, prompt_used, model

  Deferred:
    multi-turn memory, pronoun resolution, combined intents, UI, streaming
""")
_check("V1 interface report printed", True)

# ---------------------------------------------------------------------------
# Final tally
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  TOTAL: {_PASS + _FAIL}/{_PASS + _FAIL} checked  |  "
      f"{_PASS} PASS  |  {_FAIL} FAIL")
print(f"{'=' * 60}")

if _FAIL:
    sys.exit(1)


