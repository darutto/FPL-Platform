"""
run_phase3a_tests.py
====================
Phase 3a test suite — minimal LLM integration layer.

Sections
--------
A  LLMResponse dataclass
B  SYSTEM_PROMPT
C  DEFAULT_MODEL
D  _OUTCOME_INSTRUCTION coverage
E  build_user_prompt — structure
F  build_user_prompt — per-outcome content
G  build_user_prompt — determinism
H  ask_llm — fallback path (no client)
I  ask_llm — fallback preserves adapter_response
J  ask_llm — error fallback (mock client raises)
K  ask_llm — never-raises edge cases
L  LLMResponse invariants (fallback path)
M  _ANTHROPIC_AVAILABLE flag
N  _get_anthropic_client — no API key
O  Conditional LLM call (skipped if no ANTHROPIC_API_KEY)
P  Phase 2n regression
Q  Phase 2m regression
R  Interface report
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
_section = ""


def section(name: str) -> None:
    global _section
    _section = name
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
    # Phase 3a
    LLMResponse,
    SYSTEM_PROMPT,
    DEFAULT_MODEL,
    _OUTCOME_INSTRUCTION,
    build_user_prompt,
    ask_llm,
    _get_anthropic_client,
    _ANTHROPIC_AVAILABLE,
    # Phase 2m
    adapt,
    AdapterResponse,
    # Phase 2k/2l
    DispatchResult,
    dispatch,
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

BS = STANDARD_BOOTSTRAP
ABS = AMBIGUOUS_BOOTSTRAP

# Pre-built AdapterResponse objects for deterministic sections
_ar_captain   = adapt("should I captain Haaland",   BS)
_ar_gameweek  = adapt("what gameweek is it",         BS)
_ar_summary   = adapt("summary for Salah",           BS)
_ar_resolve   = adapt("who is Haaland",              BS)
_ar_rank      = adapt("top captains this week",      BS,
                      candidates_list=[{"query": "Haaland"}, {"query": "Salah"}])
_ar_not_found = adapt("should I captain xyznotaplayer999", BS)
_ar_ambiguous = adapt("who is Doe",                  ABS)
_ar_missing   = adapt("top captains this week",      BS)  # no candidates_list
_ar_unsupport = adapt("Is Haaland fit to play?",     BS)

_ALL_AR = [
    _ar_captain, _ar_gameweek, _ar_summary, _ar_resolve,
    _ar_rank, _ar_not_found, _ar_ambiguous, _ar_missing, _ar_unsupport,
]

# ---------------------------------------------------------------------------
# A. LLMResponse dataclass
# ---------------------------------------------------------------------------

section("A. LLMResponse dataclass")

_llm_fields = {f.name for f in dc_fields(LLMResponse)}
ok("user_message"     in _llm_fields, "A1 user_message field present")
ok("adapter_response" in _llm_fields, "A2 adapter_response field present")
ok("llm_text"         in _llm_fields, "A3 llm_text field present")
ok("prompt_used"      in _llm_fields, "A4 prompt_used field present")
ok("model"            in _llm_fields, "A5 model field present")
ok("llm_called"       in _llm_fields, "A6 llm_called field present")
ok(len(_llm_fields) == 6,             "A7 exactly 6 fields")

# Frozen (immutable)
_dr_tmp = dispatch("who is Haaland", BS)
_ar_tmp = AdapterResponse(
    user_message="who is Haaland",
    dispatch_result=_dr_tmp,
    supported=True,
    response_text=_dr_tmp.answer_text,
)
_lr_tmp = LLMResponse(
    user_message="who is Haaland",
    adapter_response=_ar_tmp,
    llm_text="test text",
    prompt_used="test prompt",
    model="none",
    llm_called=False,
)
try:
    _lr_tmp.llm_text = "changed"  # type: ignore[misc]
    ok(False, "A8 frozen — assignment should raise")
except Exception:
    ok(True, "A8 frozen — assignment raises as expected")

# ---------------------------------------------------------------------------
# B. SYSTEM_PROMPT
# ---------------------------------------------------------------------------

section("B. SYSTEM_PROMPT")

ok(isinstance(SYSTEM_PROMPT, str), "B1 SYSTEM_PROMPT is str")
ok(len(SYSTEM_PROMPT) > 50,        "B2 SYSTEM_PROMPT is non-trivial")
ok("FPL" in SYSTEM_PROMPT or "Fantasy" in SYSTEM_PROMPT,
                                   "B3 SYSTEM_PROMPT mentions FPL/Fantasy")
ok("grounded" in SYSTEM_PROMPT.lower() or "deterministic" in SYSTEM_PROMPT.lower() or
   "fabricate" in SYSTEM_PROMPT.lower(),
                                   "B4 SYSTEM_PROMPT includes accuracy/safety constraint")

# ---------------------------------------------------------------------------
# C. DEFAULT_MODEL
# ---------------------------------------------------------------------------

section("C. DEFAULT_MODEL")

ok(isinstance(DEFAULT_MODEL, str),          "C1 DEFAULT_MODEL is str")
ok(DEFAULT_MODEL == "claude-haiku-4-5-20251001", "C2 DEFAULT_MODEL is claude-haiku-4-5")
ok(len(DEFAULT_MODEL) > 0,                  "C3 DEFAULT_MODEL non-empty")

# ---------------------------------------------------------------------------
# D. _OUTCOME_INSTRUCTION coverage
# ---------------------------------------------------------------------------

section("D. _OUTCOME_INSTRUCTION coverage")

_expected_outcomes = {
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
    OUTCOME_UNSUPPORTED_INTENT,
}

ok(isinstance(_OUTCOME_INSTRUCTION, dict),   "D1 _OUTCOME_INSTRUCTION is dict")
ok(len(_OUTCOME_INSTRUCTION) == 6,           "D2 exactly 6 entries (one per OUTCOME_*)")

for _oc in _expected_outcomes:
    ok(_oc in _OUTCOME_INSTRUCTION,          f"D3 entry for {_oc}")
    ok(isinstance(_OUTCOME_INSTRUCTION[_oc], str), f"D4 instruction for {_oc} is str")
    ok(len(_OUTCOME_INSTRUCTION[_oc]) > 10,  f"D5 instruction for {_oc} is non-trivial")

# ---------------------------------------------------------------------------
# E. build_user_prompt — structure
# ---------------------------------------------------------------------------

section("E. build_user_prompt — structure")

_p_captain = build_user_prompt(_ar_captain)
ok(isinstance(_p_captain, str),         "E1 returns str")
ok(len(_p_captain) > 50,               "E2 non-trivial length")
ok("should I captain Haaland" in _p_captain, "E3 user question present in prompt")
ok("captain_score" in _p_captain,      "E4 intent present in prompt")
ok(OUTCOME_OK in _p_captain,           "E5 outcome present in prompt")
ok(_ar_captain.response_text in _p_captain, "E6 grounded answer present in prompt")
ok(_OUTCOME_INSTRUCTION[OUTCOME_OK] in _p_captain, "E7 per-outcome instruction present")

# Unsupported
_p_unsup = build_user_prompt(_ar_unsupport)
ok("Is Haaland fit to play?" in _p_unsup,   "E8 unsupported user message present")
ok(OUTCOME_UNSUPPORTED_INTENT in _p_unsup,   "E9 unsupported outcome present in prompt")
ok(_OUTCOME_INSTRUCTION[OUTCOME_UNSUPPORTED_INTENT] in _p_unsup,
                                             "E10 unsupported instruction present")

# ---------------------------------------------------------------------------
# F. build_user_prompt — per-outcome content
# ---------------------------------------------------------------------------

section("F. build_user_prompt — per-outcome content")

_outcome_ar_pairs = [
    (OUTCOME_OK,                 _ar_captain),
    (OUTCOME_OK,                 _ar_gameweek),
    (OUTCOME_OK,                 _ar_summary),
    (OUTCOME_OK,                 _ar_resolve),
    (OUTCOME_OK,                 _ar_rank),
    (OUTCOME_NOT_FOUND,          _ar_not_found),
    (OUTCOME_AMBIGUOUS,          _ar_ambiguous),
    (OUTCOME_MISSING_ARGUMENTS,  _ar_missing),
    (OUTCOME_UNSUPPORTED_INTENT, _ar_unsupport),
]

for _oc, _ar in _outcome_ar_pairs:
    _p = build_user_prompt(_ar)
    ok(_oc in _p,
       f"F1 outcome={_oc} present in prompt for {_ar.dispatch_result.intent}")
    ok(_OUTCOME_INSTRUCTION[_oc] in _p,
       f"F2 correct instruction for outcome={_oc}")
    ok(_ar.response_text in _p,
       f"F3 response_text present for outcome={_oc}")

# ---------------------------------------------------------------------------
# G. build_user_prompt — determinism
# ---------------------------------------------------------------------------

section("G. build_user_prompt — determinism")

for _ar in _ALL_AR:
    _p1 = build_user_prompt(_ar)
    _p2 = build_user_prompt(_ar)
    ok(_p1 == _p2,
       f"G1 deterministic for intent={_ar.dispatch_result.intent} outcome={_ar.dispatch_result.outcome}")

# ---------------------------------------------------------------------------
# H. ask_llm — fallback path (no client)
# ---------------------------------------------------------------------------

section("H. ask_llm — fallback path (no client)")

# Ensure no API key for this section
_saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)

_lr_fallback = ask_llm("should I captain Haaland", BS)
ok(isinstance(_lr_fallback, LLMResponse),     "H1 returns LLMResponse")
ok(_lr_fallback.llm_called is False,          "H2 llm_called=False without client")
ok(_lr_fallback.model == "none",              "H3 model='none' without client")
ok(_lr_fallback.llm_text == _lr_fallback.adapter_response.response_text,
                                              "H4 llm_text mirrors response_text (fallback)")
ok(len(_lr_fallback.prompt_used) > 0,         "H5 prompt_used populated even in fallback")
ok(_lr_fallback.user_message == "should I captain Haaland",
                                              "H6 user_message preserved")

# Unsupported falls back cleanly
_lr_unsup_fb = ask_llm("Is Haaland fit to play?", BS)
ok(_lr_unsup_fb.llm_called is False,          "H7 unsupported falls back")
ok(_lr_unsup_fb.adapter_response.supported is False,
                                              "H8 adapter_response.supported=False for unsupported")
ok(len(_lr_unsup_fb.llm_text) > 0,            "H9 llm_text non-empty for unsupported fallback")

# Restore key if it was set
if _saved_key:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key

# ---------------------------------------------------------------------------
# I. ask_llm — fallback preserves adapter_response
# ---------------------------------------------------------------------------

section("I. ask_llm — fallback preserves adapter_response")

_saved_key2 = os.environ.pop("ANTHROPIC_API_KEY", None)

_cases_i = [
    ("should I captain Haaland",          BS,  None,                   OUTCOME_OK),
    ("what gameweek is it",               BS,  None,                   OUTCOME_OK),
    ("top captains this week",            BS,
     [{"query": "Haaland"}, {"query": "Salah"}],                       OUTCOME_OK),
    ("summary for Salah",                 BS,  None,                   OUTCOME_OK),
    ("who is Haaland",                    BS,  None,                   OUTCOME_OK),
    ("should I captain xyznotaplayer999", BS,  None,                   OUTCOME_NOT_FOUND),
    ("who is Doe",                        ABS, None,                   OUTCOME_AMBIGUOUS),
    ("top captains this week",            BS,  None,                   OUTCOME_MISSING_ARGUMENTS),
    ("Is Haaland fit to play?",           BS,  None,                   OUTCOME_UNSUPPORTED_INTENT),
]

for _msg, _bs, _cands, _expected_oc in _cases_i:
    _lr_i = ask_llm(_msg, _bs, candidates_list=_cands)
    ok(isinstance(_lr_i.adapter_response, AdapterResponse),
       f"I1 adapter_response is AdapterResponse for outcome={_expected_oc}")
    ok(_lr_i.adapter_response.dispatch_result.outcome == _expected_oc,
       f"I2 adapter outcome={_expected_oc} preserved in LLMResponse")
    ok(_lr_i.user_message == _msg,
       f"I3 user_message preserved for outcome={_expected_oc}")
    ok(_lr_i.adapter_response.user_message == _msg,
       f"I4 adapter_response.user_message preserved for outcome={_expected_oc}")

if _saved_key2:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key2

# ---------------------------------------------------------------------------
# J. ask_llm — error fallback (mock client raises)
# ---------------------------------------------------------------------------

section("J. ask_llm — error fallback (mock client raises)")


class _MockClientAlwaysRaises:
    """Mock Anthropic client that raises on every messages.create() call."""

    class _Messages:
        def create(self, **kwargs):
            raise RuntimeError("Mock API failure")

    messages = _Messages()


_lr_err = ask_llm("should I captain Haaland", BS, client=_MockClientAlwaysRaises())
ok(isinstance(_lr_err, LLMResponse),          "J1 returns LLMResponse even when client raises")
ok(_lr_err.llm_called is False,               "J2 llm_called=False when client raises")
ok(_lr_err.model == "none",                   "J3 model='none' when client raises")
ok(_lr_err.llm_text == _lr_err.adapter_response.response_text,
                                              "J4 llm_text=deterministic fallback when error")
ok(len(_lr_err.prompt_used) > 0,             "J5 prompt_used populated even when error")


class _MockClientReturnsEmpty:
    """Mock client that returns a response with empty content."""

    class _Content:
        text = ""

    class _Response:
        content = [_Content()]

    class _Messages:
        def create(self, **kwargs):
            return _MockClientReturnsEmpty._Response()

    messages = _Messages()


_lr_empty = ask_llm("should I captain Haaland", BS, client=_MockClientReturnsEmpty())
ok(isinstance(_lr_empty, LLMResponse),        "J6 returns LLMResponse with empty-content client")
# Empty string.strip() == "" — the LLM text will be empty string, llm_called=True
ok(_lr_empty.llm_called is True,              "J7 llm_called=True when client call succeeds")


# Mock that returns a proper response
class _MockClientOK:
    class _Content:
        text = "  Haaland is the top captain pick this week.  "

    class _Response:
        content = [_Content()]

    class _Messages:
        def create(self, **kwargs):
            return _MockClientOK._Response()

    messages = _Messages()


_lr_mock_ok = ask_llm("should I captain Haaland", BS, client=_MockClientOK())
ok(isinstance(_lr_mock_ok, LLMResponse),      "J8 returns LLMResponse with mock OK client")
ok(_lr_mock_ok.llm_called is True,            "J9 llm_called=True with mock OK client")
ok(_lr_mock_ok.model == DEFAULT_MODEL,        "J10 model=DEFAULT_MODEL with mock OK client")
ok(_lr_mock_ok.llm_text == "Haaland is the top captain pick this week.",
                                              "J11 llm_text stripped from mock response")
ok(_lr_mock_ok.adapter_response.dispatch_result.outcome == OUTCOME_OK,
                                              "J12 adapter_response intact with mock OK client")

# ---------------------------------------------------------------------------
# K. ask_llm — never-raises edge cases
# ---------------------------------------------------------------------------

section("K. ask_llm — never-raises edge cases")

_saved_key3 = os.environ.pop("ANTHROPIC_API_KEY", None)

_edge_cases = [
    ("",              BS,  "K1 empty message"),
    ("   ",           BS,  "K2 whitespace-only message"),
    ("a" * 1000,      BS,  "K3 very long message"),
    ("!@#$%^&*()",    BS,  "K4 special characters"),
    ("who is Salah",  {},  "K5 empty bootstrap"),
]

for _msg, _bs, _label in _edge_cases:
    try:
        _lr_edge = ask_llm(_msg, _bs)
        ok(isinstance(_lr_edge, LLMResponse), f"{_label} — returns LLMResponse")
        ok(isinstance(_lr_edge.llm_text, str), f"{_label} — llm_text is str")
    except Exception as _e:
        ok(False, f"{_label} — raised unexpectedly: {_e}")

if _saved_key3:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key3

# ---------------------------------------------------------------------------
# L. LLMResponse invariants (fallback path)
# ---------------------------------------------------------------------------

section("L. LLMResponse invariants (fallback path)")

_saved_key4 = os.environ.pop("ANTHROPIC_API_KEY", None)

for _ar_inv in _ALL_AR:
    _lr_inv = ask_llm(_ar_inv.user_message, BS,
                      candidates_list=_ar_inv.dispatch_result.raw_output.get("candidates"))
    ok(_lr_inv.user_message == _ar_inv.user_message,
       f"L1 user_message preserved for intent={_ar_inv.dispatch_result.intent}")
    ok(isinstance(_lr_inv.adapter_response, AdapterResponse),
       f"L2 adapter_response is AdapterResponse for intent={_ar_inv.dispatch_result.intent}")
    ok(len(_lr_inv.llm_text) >= 0,    # empty is technically allowed; non-empty preferred
       f"L3 llm_text is str for intent={_ar_inv.dispatch_result.intent}")
    ok(isinstance(_lr_inv.prompt_used, str),
       f"L4 prompt_used is str for intent={_ar_inv.dispatch_result.intent}")
    ok(isinstance(_lr_inv.model, str),
       f"L5 model is str for intent={_ar_inv.dispatch_result.intent}")
    ok(isinstance(_lr_inv.llm_called, bool),
       f"L6 llm_called is bool for intent={_ar_inv.dispatch_result.intent}")

    # Fallback invariant: when llm_called=False, llm_text == response_text
    if not _lr_inv.llm_called:
        ok(_lr_inv.llm_text == _lr_inv.adapter_response.response_text,
           f"L7 fallback: llm_text==response_text for intent={_ar_inv.dispatch_result.intent}")

if _saved_key4:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key4

# ---------------------------------------------------------------------------
# M. _ANTHROPIC_AVAILABLE flag
# ---------------------------------------------------------------------------

section("M. _ANTHROPIC_AVAILABLE flag")

ok(isinstance(_ANTHROPIC_AVAILABLE, bool), "M1 _ANTHROPIC_AVAILABLE is bool")
# In CI / this environment, it will be False since anthropic is not installed
# Just confirm the value is consistent with import behaviour
try:
    import anthropic  # type: ignore[import-untyped]
    _expected_avail = True
except ImportError:
    _expected_avail = False
ok(_ANTHROPIC_AVAILABLE == _expected_avail,
   f"M2 _ANTHROPIC_AVAILABLE={_ANTHROPIC_AVAILABLE} consistent with import attempt")

# ---------------------------------------------------------------------------
# N. _get_anthropic_client — no API key
# ---------------------------------------------------------------------------

section("N. _get_anthropic_client — no API key")

_saved_key5 = os.environ.pop("ANTHROPIC_API_KEY", None)

_client_none = _get_anthropic_client()
ok(_client_none is None, "N1 _get_anthropic_client() returns None without API key")

_client_explicit_none = _get_anthropic_client(api_key=None)
ok(_client_explicit_none is None, "N2 _get_anthropic_client(api_key=None) returns None")

_client_empty = _get_anthropic_client(api_key="")
ok(_client_empty is None, "N3 _get_anthropic_client(api_key='') returns None")

if _saved_key5:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key5

# ---------------------------------------------------------------------------
# O. Conditional LLM call (skipped if no ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

section("O. Conditional LLM call (live API)")

_api_key = os.environ.get("ANTHROPIC_API_KEY")
if not _api_key or not _ANTHROPIC_AVAILABLE:
    print(f"  [SKIP] ANTHROPIC_API_KEY not set or anthropic package absent — "
          f"skipping live LLM call tests")
    ok(True, "O0 skip sentinel — conditional section not applicable")
else:
    _lr_live = ask_llm("should I captain Haaland", BS, api_key=_api_key)
    ok(isinstance(_lr_live, LLMResponse),   "O1 live call returns LLMResponse")
    ok(_lr_live.llm_called is True,         "O2 live call sets llm_called=True")
    ok(_lr_live.model == DEFAULT_MODEL,     "O3 live call uses DEFAULT_MODEL")
    ok(len(_lr_live.llm_text) > 0,          "O4 live call returns non-empty llm_text")
    ok(isinstance(_lr_live.adapter_response, AdapterResponse),
                                            "O5 live call preserves adapter_response")
    ok(_lr_live.adapter_response.dispatch_result.outcome == OUTCOME_OK,
                                            "O6 live call has ok outcome")
    # Unsupported — live
    _lr_live_unsup = ask_llm("Is Haaland fit to play?", BS, api_key=_api_key)
    ok(_lr_live_unsup.llm_called is True,   "O7 live unsupported call sets llm_called=True")
    ok(_lr_live_unsup.adapter_response.supported is False,
                                            "O8 live unsupported preserves supported=False")
    ok(len(_lr_live_unsup.llm_text) > 0,    "O9 live unsupported returns non-empty llm_text")

# ---------------------------------------------------------------------------
# P. Phase 2n regression
# ---------------------------------------------------------------------------

section("P. Phase 2n regression")

ok(len(FIXTURE_DEFINITIONS) == 9,      "P1 FIXTURE_DEFINITIONS has 9 fixtures")
_p2n_results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
ok(len(_p2n_results) == 9,             "P2 run_all returns 9 results")

for _fix, _resp in _p2n_results:
    ok(isinstance(_fix, ConversationFixture),   f"P3 fixture type for {_fix.scenario_id}")
    ok(isinstance(_resp, AdapterResponse),      f"P4 response type for {_fix.scenario_id}")
    ok(_resp.supported == _fix.expected_supported,
       f"P5 supported for {_fix.scenario_id}")
    ok(_resp.dispatch_result.outcome == _fix.expected_outcome,
       f"P6 outcome for {_fix.scenario_id}")
    ok(_resp.dispatch_result.intent == _fix.expected_intent,
       f"P7 intent for {_fix.scenario_id}")

# ---------------------------------------------------------------------------
# Q. Phase 2m regression
# ---------------------------------------------------------------------------

section("Q. Phase 2m regression")

_ar_q = adapt("should I captain Haaland", BS)
ok(isinstance(_ar_q, AdapterResponse),           "Q1 adapt returns AdapterResponse")
ok(_ar_q.supported is True,                      "Q2 supported=True for captain intent")
ok(_ar_q.dispatch_result.outcome == OUTCOME_OK,  "Q3 outcome=ok for captain intent")
ok(len(_ar_q.response_text) > 0,                 "Q4 response_text non-empty")

_ar_q_unsup = adapt("Is Haaland fit to play?", BS)
ok(_ar_q_unsup.supported is False,               "Q5 supported=False for unsupported")
ok(_ar_q_unsup.dispatch_result.outcome == OUTCOME_UNSUPPORTED_INTENT,
                                                 "Q6 outcome=unsupported_intent")

# ---------------------------------------------------------------------------
# R. Interface report
# ---------------------------------------------------------------------------

section("R. Interface report")

print("\n  Phase 3a public surface:")
print(f"    ask_llm        — outer entrypoint: adapt() + optional LLM call")
print(f"    LLMResponse    — frozen dataclass, 6 fields")
print(f"    build_user_prompt — pure function, fully testable")
print(f"    DEFAULT_MODEL  = {DEFAULT_MODEL!r}")
print(f"    _ANTHROPIC_AVAILABLE = {_ANTHROPIC_AVAILABLE}")
print()
print("  LLMResponse fields:")
for _f in dc_fields(LLMResponse):
    print(f"    {_f.name}: {_f.type}")
print()
print("  _OUTCOME_INSTRUCTION keys:")
for _k in _OUTCOME_INSTRUCTION:
    print(f"    {_k!r}")
print()
print("  Fallback behaviour:")
print("    ask_llm() with no client/key  → llm_called=False, model='none',")
print("                                    llm_text=adapter_response.response_text")
print("    ask_llm() with raising client → same fallback")
print("    ask_llm() with mock OK client → llm_called=True, llm_text=stripped response")

ok(True, "R1 interface report printed")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

sys.exit(summary())


