"""
run_phase3c_tests.py
====================
Phase 3c test suite — unified final response policy.

Sections
--------
A  FinalResponseDebug dataclass
B  FinalResponse dataclass
C  FINAL_TEXT_POLICY constant
D  respond() — returns FinalResponse
E  respond() — final_text policy (always = review.safe_text)
F  respond() — llm_used flag semantics
G  respond() — review_passed flag
H  respond() — outcome propagation
I  respond() — supported propagation
J  respond() — intent propagation
K  respond() — debug=None by default
L  respond() — include_debug=True populates debug bundle
M  respond() — mock client passing review (llm_used=True)
N  respond() — mock client failing review (llm_used=False, fallback)
O  respond() — never raises
P  Fixture-based respond() — all 9 scenarios, deterministic path
Q  Caller-facing vs debug-facing separation invariants
R  Phase 3b regression
S  Interface report
"""
import os
import sys
import traceback
from dataclasses import fields as dc_fields

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def section(name: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print('='*60)


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {label}")
    if cond:
        _pass += 1
    else:
        _fail += 1
        traceback.print_stack(limit=3)


def summary() -> int:
    total = _pass + _fail
    print(f"\n{'='*60}")
    print(f"  TOTAL: {_pass}/{total} PASS  |  {_fail} FAIL")
    print('='*60)
    return 0 if _fail == 0 else 1


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

sys.path.insert(0, ".")

from fpl_grounded_assistant import (
    # Phase 3c
    FinalResponse,
    FinalResponseDebug,
    FINAL_TEXT_POLICY,
    respond,
    # Phase 3b
    ReviewResult,
    review_llm_response,
    ask_llm_safe,
    VIOLATION_OVERCONFIDENT_NON_OK,
    VIOLATION_INVENTED_NUMBERS,
    VIOLATION_AMBIGUOUS_FALSE_RESOLUTION,
    VIOLATION_EMPTY_LLM_TEXT,
    # Phase 3a
    LLMResponse,
    ask_llm,
    DEFAULT_MODEL,
    # Phase 2m
    adapt,
    AdapterResponse,
    # Phase 2k/2l
    dispatch,
    DispatchResult,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
    OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
    # Phase 2n
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    FIXTURE_DEFINITIONS,
    run_all,
    ConversationFixture,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BS  = STANDARD_BOOTSTRAP
ABS = AMBIGUOUS_BOOTSTRAP

# Remove API key so all respond() calls use deterministic fallback
_saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)


def _clean_content(text: str) -> type:
    class _C:
        pass
    _C.text = text
    return _C


# Mock classes for live client simulation
class _PassingContent:
    text = "Haaland looks like a strong captain pick this week."

class _PassingResponse:
    content = [_PassingContent()]

class _PassingClient:
    class _Messages:
        def create(self, **kwargs):
            return _PassingResponse()
    messages = _Messages()


class _FailingContent:
    # Overconfident + invented number on not_found outcome → violation
    text = "I can definitely find that player — score is 99 and top tier."

class _FailingResponse:
    content = [_FailingContent()]

class _FailingClient:
    class _Messages:
        def create(self, **kwargs):
            return _FailingResponse()
    messages = _Messages()


class _ErrorClient:
    class _Messages:
        def create(self, **kwargs):
            raise RuntimeError("Mock API error")
    messages = _Messages()


# ---------------------------------------------------------------------------
# A. FinalResponseDebug dataclass
# ---------------------------------------------------------------------------

section("A. FinalResponseDebug dataclass")

_frd_fields = {f.name for f in dc_fields(FinalResponseDebug)}
ok("llm_text"      in _frd_fields, "A1 llm_text field present")
ok("response_text" in _frd_fields, "A2 response_text field present")
ok("violations"    in _frd_fields, "A3 violations field present")
ok("prompt_used"   in _frd_fields, "A4 prompt_used field present")
ok("model"         in _frd_fields, "A5 model field present")
ok(len(_frd_fields) == 5,          "A6 exactly 5 fields")

# Frozen
_frd_tmp = FinalResponseDebug(
    llm_text="test", response_text="test", violations=(),
    prompt_used="prompt", model="none",
)
try:
    _frd_tmp.llm_text = "changed"  # type: ignore[misc]
    ok(False, "A7 frozen — assignment should raise")
except Exception:
    ok(True, "A7 frozen — assignment raises")

ok(isinstance(_frd_tmp.violations, tuple), "A8 violations is tuple")
ok(isinstance(_frd_tmp.llm_text, str),     "A9 llm_text is str")
ok(isinstance(_frd_tmp.model, str),        "A10 model is str")

# ---------------------------------------------------------------------------
# B. FinalResponse dataclass
# ---------------------------------------------------------------------------

section("B. FinalResponse dataclass")

_fr_fields = {f.name for f in dc_fields(FinalResponse)}
ok("final_text"    in _fr_fields, "B1 final_text field present")
ok("outcome"       in _fr_fields, "B2 outcome field present")
ok("supported"     in _fr_fields, "B3 supported field present")
ok("intent"        in _fr_fields, "B4 intent field present")
ok("review_passed" in _fr_fields, "B5 review_passed field present")
ok("llm_used"      in _fr_fields, "B6 llm_used field present")
ok("debug"         in _fr_fields, "B7 debug field present")
ok(len(_fr_fields) == 7,          "B8 exactly 7 fields")

# Frozen
_fr_tmp = FinalResponse(
    final_text="test", outcome=OUTCOME_OK, supported=True,
    intent=INTENT_CAPTAIN_SCORE, review_passed=True, llm_used=False, debug=None,
)
try:
    _fr_tmp.final_text = "changed"  # type: ignore[misc]
    ok(False, "B9 frozen — assignment should raise")
except Exception:
    ok(True, "B9 frozen — assignment raises")

ok(isinstance(_fr_tmp.final_text, str),    "B10 final_text is str")
ok(isinstance(_fr_tmp.outcome, str),       "B11 outcome is str")
ok(isinstance(_fr_tmp.supported, bool),    "B12 supported is bool")
ok(isinstance(_fr_tmp.intent, str),        "B13 intent is str")
ok(isinstance(_fr_tmp.review_passed, bool),"B14 review_passed is bool")
ok(isinstance(_fr_tmp.llm_used, bool),     "B15 llm_used is bool")
ok(_fr_tmp.debug is None,                  "B16 debug is None by default construction")

# ---------------------------------------------------------------------------
# C. FINAL_TEXT_POLICY constant
# ---------------------------------------------------------------------------

section("C. FINAL_TEXT_POLICY constant")

ok(isinstance(FINAL_TEXT_POLICY, str),   "C1 FINAL_TEXT_POLICY is str")
ok(len(FINAL_TEXT_POLICY) > 20,          "C2 FINAL_TEXT_POLICY is non-trivial")
ok("safe_text" in FINAL_TEXT_POLICY.lower() or "review" in FINAL_TEXT_POLICY.lower(),
                                         "C3 FINAL_TEXT_POLICY references review/safe_text")
ok("response_text" in FINAL_TEXT_POLICY or "fallback" in FINAL_TEXT_POLICY.lower(),
                                         "C4 FINAL_TEXT_POLICY references fallback")

# ---------------------------------------------------------------------------
# D. respond() — returns FinalResponse
# ---------------------------------------------------------------------------

section("D. respond() — returns FinalResponse")

_fr_d = respond("should I captain Haaland", BS)
ok(isinstance(_fr_d, FinalResponse),  "D1 respond() returns FinalResponse")
ok(isinstance(_fr_d.final_text, str), "D2 final_text is str")
ok(isinstance(_fr_d.outcome, str),    "D3 outcome is str")
ok(isinstance(_fr_d.supported, bool), "D4 supported is bool")
ok(isinstance(_fr_d.intent, str),     "D5 intent is str")
ok(isinstance(_fr_d.review_passed, bool), "D6 review_passed is bool")
ok(isinstance(_fr_d.llm_used, bool),  "D7 llm_used is bool")
ok(_fr_d.debug is None,               "D8 debug is None by default")

# All scenario types return FinalResponse
_all_calls = [
    ("should I captain Haaland",          BS,  None,                   OUTCOME_OK),
    ("what gameweek is it",               BS,  None,                   OUTCOME_OK),
    ("summary for Salah",                 BS,  None,                   OUTCOME_OK),
    ("who is Haaland",                    BS,  None,                   OUTCOME_OK),
    ("top captains this week",            BS,
     [{"query": "Haaland"}, {"query": "Salah"}],                        OUTCOME_OK),
    ("should I captain xyznotaplayer999", BS,  None,                   OUTCOME_NOT_FOUND),
    ("who is Doe",                        ABS, None,                   OUTCOME_AMBIGUOUS),
    ("top captains this week",            BS,  None,                   OUTCOME_MISSING_ARGUMENTS),
    ("Is Haaland fit to play?",           BS,  None,                   OUTCOME_UNSUPPORTED_INTENT),
]
for _msg, _bs, _cands, _oc in _all_calls:
    _fr = respond(_msg, _bs, candidates_list=_cands)
    ok(isinstance(_fr, FinalResponse), f"D9 FinalResponse for outcome={_oc}")

# ---------------------------------------------------------------------------
# E. respond() — final_text policy (always = review.safe_text)
# ---------------------------------------------------------------------------

section("E. respond() — final_text policy")

# Policy: final_text == review.safe_text.
# In deterministic fallback path: review.safe_text == llm_text == response_text
# So final_text == response_text

for _msg, _bs, _cands, _oc in _all_calls:
    # get what ask_llm_safe produces
    _lr_e, _rr_e = ask_llm_safe(_msg, _bs, candidates_list=_cands)
    _fr_e = respond(_msg, _bs, candidates_list=_cands)
    ok(_fr_e.final_text == _rr_e.safe_text,
       f"E1 final_text == review.safe_text for outcome={_oc}")
    ok(len(_fr_e.final_text) > 0,
       f"E2 final_text is non-empty for outcome={_oc}")

# In deterministic path: final_text == response_text
_fr_e_det = respond("should I captain Haaland", BS)
_ar_e_det = adapt("should I captain Haaland", BS)
ok(_fr_e_det.final_text == _ar_e_det.response_text,
   "E3 deterministic path: final_text == response_text")

# Deterministic path is always safe (no overconfidence, no invented numbers)
for _msg, _bs, _cands, _oc in _all_calls:
    _fr_e2 = respond(_msg, _bs, candidates_list=_cands)
    ok(isinstance(_fr_e2.final_text, str), f"E4 final_text is str for outcome={_oc}")

# ---------------------------------------------------------------------------
# F. respond() — llm_used flag semantics
# ---------------------------------------------------------------------------

section("F. respond() — llm_used flag semantics")

# Deterministic path: llm_called=False → llm_used=False regardless of review
for _msg, _bs, _cands, _oc in _all_calls:
    _fr_f = respond(_msg, _bs, candidates_list=_cands)
    ok(_fr_f.llm_used is False,
       f"F1 deterministic path: llm_used=False for outcome={_oc}")

# Mock client passing review → llm_used=True
_fr_f_pass = respond("should I captain Haaland", BS, client=_PassingClient())
ok(_fr_f_pass.llm_used is True,     "F2 passing mock client: llm_used=True")
ok(_fr_f_pass.review_passed is True, "F3 passing mock client: review_passed=True")

# Mock client failing review (bad not_found text) → llm_used=False
_fr_f_fail = respond(
    "should I captain xyznotaplayer999", BS, client=_FailingClient()
)
ok(_fr_f_fail.llm_used is False,     "F4 failing review: llm_used=False")
ok(_fr_f_fail.review_passed is False,"F5 failing review: review_passed=False")

# Error client → LLM falls back to deterministic → llm_used=False
_fr_f_err = respond("should I captain Haaland", BS, client=_ErrorClient())
ok(_fr_f_err.llm_used is False,     "F6 error client: llm_used=False")

# llm_used invariant: llm_used=True → review_passed=True AND final_text != response_text (unless identical)
# We can test: llm_used=True implies review_passed=True
_fr_f_p2 = respond("who is Haaland", BS, client=_PassingClient())
if _fr_f_p2.llm_used:
    ok(_fr_f_p2.review_passed is True, "F7 llm_used=True implies review_passed=True")
else:
    ok(True, "F7 skip — llm_used=False for this case")

# llm_used=False → final_text == response_text
_ar_f = adapt("should I captain xyznotaplayer999", BS)
_fr_f_notfound = respond("should I captain xyznotaplayer999", BS)
ok(_fr_f_notfound.llm_used is False, "F8 deterministic not_found: llm_used=False")
ok(_fr_f_notfound.final_text == _ar_f.response_text,
   "F9 deterministic not_found: final_text == response_text")

# ---------------------------------------------------------------------------
# G. respond() — review_passed flag
# ---------------------------------------------------------------------------

section("G. respond() — review_passed flag")

# Deterministic fallback always passes review
for _msg, _bs, _cands, _oc in _all_calls:
    _fr_g = respond(_msg, _bs, candidates_list=_cands)
    ok(_fr_g.review_passed is True,
       f"G1 deterministic path: review_passed=True for outcome={_oc}")

# Passing mock client → review_passed=True
_fr_g_pass = respond("should I captain Haaland", BS, client=_PassingClient())
ok(_fr_g_pass.review_passed is True, "G2 passing mock: review_passed=True")

# Failing review → review_passed=False
_fr_g_fail = respond("should I captain xyznotaplayer999", BS, client=_FailingClient())
ok(_fr_g_fail.review_passed is False, "G3 failing review: review_passed=False")

# Error client → deterministic fallback → review_passed=True
_fr_g_err = respond("should I captain Haaland", BS, client=_ErrorClient())
ok(_fr_g_err.review_passed is True, "G4 error client (deterministic fallback): review_passed=True")

# ---------------------------------------------------------------------------
# H. respond() — outcome propagation
# ---------------------------------------------------------------------------

section("H. respond() — outcome propagation")

_outcome_cases = [
    ("should I captain Haaland",          BS,  None,                   OUTCOME_OK),
    ("what gameweek is it",               BS,  None,                   OUTCOME_OK),
    ("summary for Salah",                 BS,  None,                   OUTCOME_OK),
    ("who is Haaland",                    BS,  None,                   OUTCOME_OK),
    ("top captains this week",            BS,
     [{"query": "Haaland"}, {"query": "Salah"}],                        OUTCOME_OK),
    ("should I captain xyznotaplayer999", BS,  None,                   OUTCOME_NOT_FOUND),
    ("who is Doe",                        ABS, None,                   OUTCOME_AMBIGUOUS),
    ("top captains this week",            BS,  None,                   OUTCOME_MISSING_ARGUMENTS),
    ("Is Haaland fit to play?",           BS,  None,                   OUTCOME_UNSUPPORTED_INTENT),
]

for _msg, _bs, _cands, _expected_oc in _outcome_cases:
    _fr_h = respond(_msg, _bs, candidates_list=_cands)
    ok(_fr_h.outcome == _expected_oc,
       f"H1 outcome={_expected_oc} propagated correctly")

# Outcome unchanged even when LLM is called
_fr_h_llm = respond("should I captain Haaland", BS, client=_PassingClient())
ok(_fr_h_llm.outcome == OUTCOME_OK, "H2 outcome=ok preserved with LLM client")

_fr_h_llm_nf = respond("should I captain xyznotaplayer999", BS, client=_FailingClient())
ok(_fr_h_llm_nf.outcome == OUTCOME_NOT_FOUND, "H3 outcome=not_found preserved even when client fails review")

# ---------------------------------------------------------------------------
# I. respond() — supported propagation
# ---------------------------------------------------------------------------

section("I. respond() — supported propagation")

# supported=True for all recognised intents
_fr_i_ok    = respond("should I captain Haaland", BS)
_fr_i_nf    = respond("should I captain xyznotaplayer999", BS)
_fr_i_amb   = respond("who is Doe", ABS)
_fr_i_miss  = respond("top captains this week", BS)  # no candidates

ok(_fr_i_ok.supported   is True,  "I1 supported=True for ok outcome")
ok(_fr_i_nf.supported   is True,  "I2 supported=True for not_found outcome")
ok(_fr_i_amb.supported  is True,  "I3 supported=True for ambiguous outcome")
ok(_fr_i_miss.supported is True,  "I4 supported=True for missing_arguments outcome")

# supported=False only for unsupported intent
_fr_i_us = respond("Is Haaland fit to play?", BS)
ok(_fr_i_us.supported is False, "I5 supported=False for unsupported_intent")

# supported propagated correctly via LLM client
_fr_i_llm_ok = respond("should I captain Haaland", BS, client=_PassingClient())
ok(_fr_i_llm_ok.supported is True,  "I6 supported=True with LLM client for ok")

# supported=False preserved when review fails (outcome unchanged)
_fr_i_us_bad = respond("Is Haaland fit to play?", BS, client=_FailingClient())
ok(_fr_i_us_bad.supported is False, "I7 supported=False preserved even with bad client")

# ---------------------------------------------------------------------------
# J. respond() — intent propagation
# ---------------------------------------------------------------------------

section("J. respond() — intent propagation")

_intent_cases = [
    ("should I captain Haaland",          BS,  None,                   INTENT_CAPTAIN_SCORE),
    ("what gameweek is it",               BS,  None,                   INTENT_CURRENT_GAMEWEEK),
    ("summary for Salah",                 BS,  None,                   INTENT_PLAYER_SUMMARY),
    ("who is Haaland",                    BS,  None,                   INTENT_PLAYER_RESOLVE),
    ("top captains this week",            BS,
     [{"query": "Haaland"}, {"query": "Salah"}],                        INTENT_RANK_CANDIDATES),
    ("should I captain xyznotaplayer999", BS,  None,                   INTENT_CAPTAIN_SCORE),
    ("who is Doe",                        ABS, None,                   INTENT_PLAYER_RESOLVE),
    ("top captains this week",            BS,  None,                   INTENT_RANK_CANDIDATES),
    ("Is Haaland fit to play?",           BS,  None,                   INTENT_UNSUPPORTED),
]

for _msg, _bs, _cands, _expected_intent in _intent_cases:
    _fr_j = respond(_msg, _bs, candidates_list=_cands)
    ok(_fr_j.intent == _expected_intent,
       f"J1 intent={_expected_intent} propagated correctly")

# Intent preserved when LLM is used
_fr_j_llm = respond("should I captain Haaland", BS, client=_PassingClient())
ok(_fr_j_llm.intent == INTENT_CAPTAIN_SCORE,
   "J2 intent=captain_score preserved with LLM client")

# ---------------------------------------------------------------------------
# K. respond() — debug=None by default
# ---------------------------------------------------------------------------

section("K. respond() — debug=None by default")

for _msg, _bs, _cands, _oc in _all_calls:
    _fr_k = respond(_msg, _bs, candidates_list=_cands)
    ok(_fr_k.debug is None,
       f"K1 debug=None by default for outcome={_oc}")

# include_debug=False is explicit default
_fr_k_false = respond("should I captain Haaland", BS, include_debug=False)
ok(_fr_k_false.debug is None, "K2 include_debug=False: debug is None")

# include_debug=False with LLM client
_fr_k_llm = respond("should I captain Haaland", BS, client=_PassingClient(),
                    include_debug=False)
ok(_fr_k_llm.debug is None, "K3 include_debug=False with LLM client: debug is None")

# ---------------------------------------------------------------------------
# L. respond() — include_debug=True populates debug bundle
# ---------------------------------------------------------------------------

section("L. respond() — include_debug=True populates debug bundle")

_fr_l = respond("should I captain Haaland", BS, include_debug=True)
ok(_fr_l.debug is not None,                  "L1 include_debug=True: debug is not None")
ok(isinstance(_fr_l.debug, FinalResponseDebug), "L2 debug is FinalResponseDebug")
ok(isinstance(_fr_l.debug.llm_text, str),    "L3 debug.llm_text is str")
ok(isinstance(_fr_l.debug.response_text, str),"L4 debug.response_text is str")
ok(isinstance(_fr_l.debug.violations, tuple),"L5 debug.violations is tuple")
ok(isinstance(_fr_l.debug.prompt_used, str), "L6 debug.prompt_used is str")
ok(isinstance(_fr_l.debug.model, str),       "L7 debug.model is str")

# In deterministic path: debug fields align with LLMResponse
_lr_l = ask_llm("should I captain Haaland", BS)
_fr_l2 = respond("should I captain Haaland", BS, include_debug=True)
ok(_fr_l2.debug.llm_text == _lr_l.llm_text,
   "L8 debug.llm_text matches ask_llm().llm_text")
ok(_fr_l2.debug.response_text == _lr_l.adapter_response.response_text,
   "L9 debug.response_text matches adapter_response.response_text")
ok(len(_fr_l2.debug.violations) == 0,
   "L10 debug.violations empty for deterministic path (passes review)")
ok(len(_fr_l2.debug.prompt_used) > 0,
   "L11 debug.prompt_used non-empty")
ok(_fr_l2.debug.model == "none",
   "L12 debug.model='none' for deterministic fallback")

# Debug bundle for all outcomes
for _msg, _bs, _cands, _oc in _all_calls:
    _fr_ld = respond(_msg, _bs, candidates_list=_cands, include_debug=True)
    ok(isinstance(_fr_ld.debug, FinalResponseDebug),
       f"L13 debug is FinalResponseDebug for outcome={_oc}")
    ok(isinstance(_fr_ld.debug.violations, tuple),
       f"L14 debug.violations is tuple for outcome={_oc}")

# ---------------------------------------------------------------------------
# M. respond() — mock client passing review (llm_used=True path)
# ---------------------------------------------------------------------------

section("M. respond() — mock client passing review")

_fr_m = respond("should I captain Haaland", BS, client=_PassingClient(),
                include_debug=True)
ok(isinstance(_fr_m, FinalResponse),     "M1 returns FinalResponse with mock OK client")
ok(_fr_m.llm_used is True,              "M2 llm_used=True with passing mock client")
ok(_fr_m.review_passed is True,         "M3 review_passed=True with passing mock client")
ok(_fr_m.outcome == OUTCOME_OK,         "M4 outcome=ok preserved")
ok(_fr_m.supported is True,             "M5 supported=True preserved")
ok(_fr_m.intent == INTENT_CAPTAIN_SCORE,"M6 intent preserved")
# final_text = llm_text (review passed)
ok(_fr_m.final_text == _PassingContent.text.strip(),
   "M7 final_text == stripped LLM text when review passes")
# debug shows the actual llm_text
ok(_fr_m.debug is not None,              "M8 debug populated when include_debug=True")
ok(_fr_m.debug.llm_text == _PassingContent.text.strip(),
   "M9 debug.llm_text matches raw LLM output")
# debug.violations is empty since review passed
ok(len(_fr_m.debug.violations) == 0,    "M10 debug.violations empty when review passes")

# ---------------------------------------------------------------------------
# N. respond() — mock client failing review (fallback path)
# ---------------------------------------------------------------------------

section("N. respond() — mock client failing review")

# _FailingClient returns overconfident + invented number on not_found outcome
_fr_n = respond("should I captain xyznotaplayer999", BS, client=_FailingClient(),
                include_debug=True)
ok(isinstance(_fr_n, FinalResponse),     "N1 returns FinalResponse with failing mock client")
ok(_fr_n.llm_used is False,             "N2 llm_used=False when review fails")
ok(_fr_n.review_passed is False,        "N3 review_passed=False when review fails")
ok(_fr_n.outcome == OUTCOME_NOT_FOUND,  "N4 outcome=not_found preserved")
ok(_fr_n.supported is True,             "N5 supported=True preserved even with review failure")

# final_text falls back to response_text
_ar_n = adapt("should I captain xyznotaplayer999", BS)
ok(_fr_n.final_text == _ar_n.response_text,
   "N6 final_text falls back to response_text when review fails")
ok(_fr_n.final_text != _FailingContent.text,
   "N7 final_text != bad llm_text")

# debug shows violations and the rejected llm_text
ok(_fr_n.debug is not None,             "N8 debug populated when include_debug=True")
ok(len(_fr_n.debug.violations) > 0,     "N9 debug.violations non-empty when review fails")
ok(_fr_n.debug.llm_text == _FailingContent.text,
   "N10 debug.llm_text preserves the rejected LLM text")
ok(_fr_n.debug.response_text == _ar_n.response_text,
   "N11 debug.response_text == deterministic backend text")
ok(any(VIOLATION_OVERCONFIDENT_NON_OK in v or VIOLATION_INVENTED_NUMBERS in v
       for v in _fr_n.debug.violations),
   "N12 debug.violations contain expected violation types")

# Error client → deterministic fallback → llm_used=False, review_passed=True
_fr_n_err = respond("should I captain Haaland", BS, client=_ErrorClient(),
                    include_debug=True)
ok(_fr_n_err.llm_used is False,         "N13 error client: llm_used=False")
ok(_fr_n_err.review_passed is True,     "N14 error client: review_passed=True (deterministic fallback)")
ok(len(_fr_n_err.debug.violations) == 0,"N15 error client: no violations (deterministic text)")

# ---------------------------------------------------------------------------
# O. respond() — never raises
# ---------------------------------------------------------------------------

section("O. respond() — never raises")

_never_raise_cases = [
    ("",           BS,  None, "O1 empty message"),
    ("   ",        BS,  None, "O2 whitespace message"),
    ("a" * 500,    BS,  None, "O3 very long message"),
    ("!@#$%^",     BS,  None, "O4 special characters"),
]

for _msg, _bs, _cands, _label in _never_raise_cases:
    try:
        _fr_o = respond(_msg, _bs, candidates_list=_cands)
        ok(isinstance(_fr_o, FinalResponse), f"{_label} — returns FinalResponse")
        ok(isinstance(_fr_o.final_text, str), f"{_label} — final_text is str")
    except Exception as _e:
        ok(False, f"{_label} — raised unexpectedly: {_e}")

# Error client also never raises
try:
    _fr_o_err = respond("should I captain Haaland", BS, client=_ErrorClient())
    ok(isinstance(_fr_o_err, FinalResponse), "O5 error client never raises")
except Exception as _e:
    ok(False, f"O5 error client raised unexpectedly: {_e}")

# ---------------------------------------------------------------------------
# P. Fixture-based respond() — all 9 scenarios, deterministic path
# ---------------------------------------------------------------------------

section("P. Fixture-based respond() — all 9 scenarios")

_p2n_results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)

for _fix, _ar in _p2n_results:
    _fr_p = respond(
        _fix.user_message,
        AMBIGUOUS_BOOTSTRAP if _fix.use_ambiguous_bootstrap else STANDARD_BOOTSTRAP,
        candidates_list=_fix.candidates_list,
        include_debug=True,
    )
    ok(isinstance(_fr_p, FinalResponse),
       f"P1 FinalResponse for fixture={_fix.scenario_id}")
    ok(_fr_p.outcome == _fix.expected_outcome,
       f"P2 outcome={_fix.expected_outcome} for fixture={_fix.scenario_id}")
    ok(_fr_p.supported == _fix.expected_supported,
       f"P3 supported={_fix.expected_supported} for fixture={_fix.scenario_id}")
    ok(_fr_p.intent == _fix.expected_intent,
       f"P4 intent={_fix.expected_intent} for fixture={_fix.scenario_id}")
    ok(_fr_p.review_passed is True,
       f"P5 review_passed=True (deterministic) for fixture={_fix.scenario_id}")
    ok(_fr_p.llm_used is False,
       f"P6 llm_used=False (deterministic) for fixture={_fix.scenario_id}")
    ok(len(_fr_p.final_text) > 0,
       f"P7 final_text non-empty for fixture={_fix.scenario_id}")
    ok(_fr_p.debug is not None,
       f"P8 debug populated for fixture={_fix.scenario_id}")
    ok(len(_fr_p.debug.violations) == 0,
       f"P9 no violations for deterministic fixture={_fix.scenario_id}")
    # final_text == response_text in deterministic path
    ok(_fr_p.final_text == _fr_p.debug.response_text,
       f"P10 final_text==response_text (deterministic) for fixture={_fix.scenario_id}")

# ---------------------------------------------------------------------------
# Q. Caller-facing vs debug-facing separation invariants
# ---------------------------------------------------------------------------

section("Q. Caller-facing vs debug-facing separation")

# Caller-facing fields — must be directly usable without internals
_fr_q = respond("should I captain Haaland", BS)
ok(isinstance(_fr_q.final_text, str),    "Q1 final_text directly usable (str)")
ok(_fr_q.outcome in {OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS,
                     OUTCOME_MISSING_ARGUMENTS, OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT},
                                         "Q2 outcome is a known OUTCOME_* constant")
ok(_fr_q.supported in {True, False},     "Q3 supported is bool")
ok(isinstance(_fr_q.intent, str),        "Q4 intent is str")
ok(isinstance(_fr_q.review_passed, bool),"Q5 review_passed is bool")
ok(isinstance(_fr_q.llm_used, bool),     "Q6 llm_used is bool")

# debug is None by default — callers don't get internals unless opted in
ok(_fr_q.debug is None,                  "Q7 debug=None: internals not exposed by default")

# Internal fields are only in debug bundle (when include_debug=True)
_fr_q_dbg = respond("should I captain Haaland", BS, include_debug=True)
# Check that prompt_used, model, violations are NOT on FinalResponse itself
ok(not hasattr(_fr_q_dbg, "prompt_used"), "Q8 prompt_used NOT on FinalResponse (debug-facing only)")
ok(not hasattr(_fr_q_dbg, "violations"),  "Q9 violations NOT on FinalResponse (debug-facing only)")
ok(not hasattr(_fr_q_dbg, "llm_text"),   "Q10 llm_text NOT on FinalResponse (debug-facing only)")

# When debug is present, all debug fields are there
ok(hasattr(_fr_q_dbg.debug, "prompt_used"), "Q11 prompt_used IN debug bundle")
ok(hasattr(_fr_q_dbg.debug, "violations"),  "Q12 violations IN debug bundle")
ok(hasattr(_fr_q_dbg.debug, "llm_text"),   "Q13 llm_text IN debug bundle")

# Caller policy: final_text is always safe regardless of debug state
for _msg, _bs, _cands, _oc in _all_calls:
    _fr_q2 = respond(_msg, _bs, candidates_list=_cands, include_debug=True)
    # final_text == safe_text == response_text in deterministic path
    ok(_fr_q2.final_text == _fr_q2.debug.response_text,
       f"Q14 final_text==response_text (deterministic) for outcome={_oc}")

# ---------------------------------------------------------------------------
# R. Phase 3b regression
# ---------------------------------------------------------------------------

section("R. Phase 3b regression")

_lr_r, _rr_r = ask_llm_safe("should I captain Haaland", BS)
ok(isinstance(_lr_r, LLMResponse),  "R1 ask_llm_safe returns LLMResponse")
ok(isinstance(_rr_r, ReviewResult), "R2 ask_llm_safe returns ReviewResult")
ok(_rr_r.passed is True,            "R3 deterministic fallback passes review")
ok(isinstance(_rr_r.safe_text, str),"R4 safe_text is str")
ok(len(_rr_r.violations) == 0,      "R5 no violations in deterministic fallback")

# Review catches bad LLM text
from fpl_grounded_assistant import LLMResponse as _LR
_dr_r = dispatch("should I captain xyznotaplayer999", BS)
_ar_r = adapt("should I captain xyznotaplayer999", BS)
_bad_lr = _LR(
    user_message="should I captain xyznotaplayer999",
    adapter_response=_ar_r,
    llm_text="I can definitely find that player — score is 99 and top tier.",
    prompt_used="test",
    model=DEFAULT_MODEL,
    llm_called=True,
)
_bad_rr = review_llm_response(_bad_lr)
ok(_bad_rr.passed is False,         "R6 review catches overconfident + invented number")
ok(len(_bad_rr.violations) > 0,     "R7 violations non-empty for bad text")
ok(_bad_rr.safe_text == _ar_r.response_text,
                                    "R8 safe_text falls back to response_text on violation")

# ---------------------------------------------------------------------------
# S. Interface report
# ---------------------------------------------------------------------------

section("S. Interface report")

print("\n  Phase 3c public surface:")
print(f"    respond(user_message, bootstrap, ..., include_debug=False) → FinalResponse")
print(f"    FinalResponse — frozen dataclass, 7 fields")
print(f"    FinalResponseDebug — frozen dataclass, 5 fields (debug-facing only)")
print(f"    FINAL_TEXT_POLICY — str constant documenting the selection rule")
print()
print("  FinalResponse caller-facing fields:")
for _f in dc_fields(FinalResponse):
    print(f"    {_f.name}")
print()
print("  FinalResponseDebug fields (debug-facing, opt-in only):")
for _f in dc_fields(FinalResponseDebug):
    print(f"    {_f.name}")
print()
print("  Final-text policy:")
print(f"    {FINAL_TEXT_POLICY}")
print()
print("  llm_used semantics:")
print("    llm_used=True  → LLM was called AND its text passed review → final_text=llm_text")
print("    llm_used=False → deterministic fallback used → final_text=response_text")
print("    (covers: no API key, API error, review failure, no LLM call at all)")
print()
print("  Deferred:")
print("    multi-turn memory, pronoun resolution, combined intents, UI, streaming")

ok(True, "S1 interface report printed")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

if _saved_key:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key

sys.exit(summary())


