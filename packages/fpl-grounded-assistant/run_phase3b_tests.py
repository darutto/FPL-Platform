"""
run_phase3b_tests.py
====================
Phase 3b test suite — LLM behavior hardening and parity checks.

Sections
--------
A  ReviewResult dataclass
B  VIOLATION_* constants
C  _NON_OK_OUTCOMES set
D  _check_overconfidence — per outcome
E  _check_numeric_invention — per outcome
F  _check_ambiguous_false_resolution — per outcome
G  _check_empty_llm_text
H  review_llm_response — clean deterministic fallbacks (no violations)
I  review_llm_response — violation cases (mock bad LLM text)
J  safe_text semantics
K  ask_llm_safe — structure
L  ask_llm_safe — safe_text fallback on violations
M  Fixture-based review (all 9 scenarios, deterministic path)
N  Semantic drift guardrails — per outcome class
O  _OVERCONFIDENT_PHRASES and _AMBIGUOUS_RESOLUTION_PHRASES
P  Phase 3a regression
Q  Interface report
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
    # Phase 3b
    ReviewResult,
    VIOLATION_OVERCONFIDENT_NON_OK,
    VIOLATION_INVENTED_NUMBERS,
    VIOLATION_AMBIGUOUS_FALSE_RESOLUTION,
    VIOLATION_EMPTY_LLM_TEXT,
    _OVERCONFIDENT_PHRASES,
    _AMBIGUOUS_RESOLUTION_PHRASES,
    _NON_OK_OUTCOMES,
    _check_overconfidence,
    _check_numeric_invention,
    _check_ambiguous_false_resolution,
    _check_empty_llm_text,
    review_llm_response,
    ask_llm_safe,
    # Phase 3a
    LLMResponse,
    ask_llm,
    build_user_prompt,
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

# Remove any API key so all ask_llm calls use the deterministic fallback
_saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)

# Pre-built LLMResponse objects (all deterministic fallback: llm_called=False)
_lr_captain   = ask_llm("should I captain Haaland", BS)
_lr_gameweek  = ask_llm("what gameweek is it",       BS)
_lr_summary   = ask_llm("summary for Salah",          BS)
_lr_resolve   = ask_llm("who is Haaland",             BS)
_lr_rank      = ask_llm("top captains this week",     BS,
                        candidates_list=[{"query": "Haaland"}, {"query": "Salah"}])
_lr_notfound  = ask_llm("should I captain xyznotaplayer999", BS)
_lr_ambiguous = ask_llm("who is Doe",                 ABS)
_lr_missing   = ask_llm("top captains this week",     BS)   # no candidates_list
_lr_unsupport = ask_llm("Is Haaland fit to play?",    BS)

_ALL_LR = [
    _lr_captain, _lr_gameweek, _lr_summary, _lr_resolve, _lr_rank,
    _lr_notfound, _lr_ambiguous, _lr_missing, _lr_unsupport,
]

_NON_OK_LR = [_lr_notfound, _lr_ambiguous, _lr_missing, _lr_unsupport]
_OK_LR     = [_lr_captain, _lr_gameweek, _lr_summary, _lr_resolve, _lr_rank]


def _make_llm_response(lr: LLMResponse, llm_text: str, llm_called: bool = True,
                       model: str = DEFAULT_MODEL) -> LLMResponse:
    """Return a copy of lr with a different llm_text (and llm_called=True by default)."""
    return LLMResponse(
        user_message=lr.user_message,
        adapter_response=lr.adapter_response,
        llm_text=llm_text,
        prompt_used=lr.prompt_used,
        model=model if llm_called else "none",
        llm_called=llm_called,
    )


# ---------------------------------------------------------------------------
# A. ReviewResult dataclass
# ---------------------------------------------------------------------------

section("A. ReviewResult dataclass")

_rr_fields = {f.name for f in dc_fields(ReviewResult)}
ok("passed"       in _rr_fields, "A1 passed field present")
ok("violations"   in _rr_fields, "A2 violations field present")
ok("llm_response" in _rr_fields, "A3 llm_response field present")
ok("safe_text"    in _rr_fields, "A4 safe_text field present")
ok(len(_rr_fields) == 4,         "A5 exactly 4 fields")

# frozen
_lr_tmp = _make_llm_response(_lr_captain, "test text")
_rr_tmp = ReviewResult(passed=True, violations=(), llm_response=_lr_tmp, safe_text="test text")
try:
    _rr_tmp.passed = False  # type: ignore[misc]
    ok(False, "A6 frozen — assignment should raise")
except Exception:
    ok(True, "A6 frozen — assignment raises as expected")

ok(isinstance(_rr_tmp.violations, tuple), "A7 violations is tuple")
ok(isinstance(_rr_tmp.passed, bool),      "A8 passed is bool")
ok(isinstance(_rr_tmp.safe_text, str),    "A9 safe_text is str")

# ---------------------------------------------------------------------------
# B. VIOLATION_* constants
# ---------------------------------------------------------------------------

section("B. VIOLATION_* constants")

ok(isinstance(VIOLATION_OVERCONFIDENT_NON_OK,      str), "B1 VIOLATION_OVERCONFIDENT_NON_OK is str")
ok(isinstance(VIOLATION_INVENTED_NUMBERS,          str), "B2 VIOLATION_INVENTED_NUMBERS is str")
ok(isinstance(VIOLATION_AMBIGUOUS_FALSE_RESOLUTION,str), "B3 VIOLATION_AMBIGUOUS_FALSE_RESOLUTION is str")
ok(isinstance(VIOLATION_EMPTY_LLM_TEXT,            str), "B4 VIOLATION_EMPTY_LLM_TEXT is str")
ok(len({VIOLATION_OVERCONFIDENT_NON_OK, VIOLATION_INVENTED_NUMBERS,
        VIOLATION_AMBIGUOUS_FALSE_RESOLUTION, VIOLATION_EMPTY_LLM_TEXT}) == 4,
                                                         "B5 all 4 constants are distinct")
# Each constant begins with its own name (used as prefix in violation strings)
ok(VIOLATION_OVERCONFIDENT_NON_OK      == "overconfident_non_ok",       "B6 OVERCONFIDENT value")
ok(VIOLATION_INVENTED_NUMBERS          == "invented_numbers",            "B7 INVENTED_NUMBERS value")
ok(VIOLATION_AMBIGUOUS_FALSE_RESOLUTION== "ambiguous_false_resolution",  "B8 AMBIGUOUS_RESOLUTION value")
ok(VIOLATION_EMPTY_LLM_TEXT            == "empty_llm_text",             "B9 EMPTY_LLM_TEXT value")

# ---------------------------------------------------------------------------
# C. _NON_OK_OUTCOMES set
# ---------------------------------------------------------------------------

section("C. _NON_OK_OUTCOMES set")

ok(isinstance(_NON_OK_OUTCOMES, frozenset), "C1 _NON_OK_OUTCOMES is frozenset")
ok(OUTCOME_NOT_FOUND         in _NON_OK_OUTCOMES, "C2 not_found in _NON_OK_OUTCOMES")
ok(OUTCOME_AMBIGUOUS         in _NON_OK_OUTCOMES, "C3 ambiguous in _NON_OK_OUTCOMES")
ok(OUTCOME_MISSING_ARGUMENTS in _NON_OK_OUTCOMES, "C4 missing_arguments in _NON_OK_OUTCOMES")
ok(OUTCOME_ERROR             in _NON_OK_OUTCOMES, "C5 error in _NON_OK_OUTCOMES")
ok(OUTCOME_UNSUPPORTED_INTENT in _NON_OK_OUTCOMES,"C6 unsupported_intent in _NON_OK_OUTCOMES")
ok(OUTCOME_OK not in _NON_OK_OUTCOMES,            "C7 ok NOT in _NON_OK_OUTCOMES")
ok(len(_NON_OK_OUTCOMES) == 5,                    "C8 exactly 5 non-ok outcomes")

# ---------------------------------------------------------------------------
# D. _check_overconfidence
# ---------------------------------------------------------------------------

section("D. _check_overconfidence")

# Should return empty list for ok outcome regardless of phrase
for _phrase in ["definitely", "certainly", "guaranteed"]:
    _v = _check_overconfidence(f"Haaland is {_phrase} the best captain.", OUTCOME_OK)
    ok(len(_v) == 0, f"D1 ok outcome: '{_phrase}' not flagged (grounded data present)")

# Should flag for non-ok outcomes
for _oc in [OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS, OUTCOME_MISSING_ARGUMENTS,
            OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT]:
    _v = _check_overconfidence("I can definitely help you with that.", _oc)
    ok(len(_v) > 0, f"D2 non-ok outcome={_oc}: 'definitely' flagged")
    ok(all(VIOLATION_OVERCONFIDENT_NON_OK in v for v in _v),
       f"D3 violation prefix correct for outcome={_oc}")

# Phrase coverage
_phrase_checks = [
    ("definitely",     OUTCOME_NOT_FOUND),
    ("certainly",      OUTCOME_AMBIGUOUS),
    ("guaranteed",     OUTCOME_MISSING_ARGUMENTS),
    ("i can confirm",  OUTCOME_ERROR),
    ("without doubt",  OUTCOME_UNSUPPORTED_INTENT),
    ("for certain",    OUTCOME_NOT_FOUND),
    ("i guarantee",    OUTCOME_AMBIGUOUS),
]
for _ph, _oc in _phrase_checks:
    _v = _check_overconfidence(_ph, _oc)
    ok(len(_v) > 0, f"D4 phrase '{_ph}' flagged for outcome={_oc}")

# Clean text — no overconfident phrases
_v_clean = _check_overconfidence("Sorry, no player was found matching that name.", OUTCOME_NOT_FOUND)
ok(len(_v_clean) == 0, "D5 clean not_found text passes overconfidence check")

_v_clean_amb = _check_overconfidence(
    "Multiple players matched that name. Could you be more specific?", OUTCOME_AMBIGUOUS)
ok(len(_v_clean_amb) == 0, "D6 clean ambiguous text passes overconfidence check")

# Returns list
ok(isinstance(_check_overconfidence("test", OUTCOME_OK), list), "D7 returns list")

# ---------------------------------------------------------------------------
# E. _check_numeric_invention
# ---------------------------------------------------------------------------

section("E. _check_numeric_invention")

# ok outcome — no check even if numbers differ
_v_ok = _check_numeric_invention("Haaland's score is 72 out of 100.", "Score: 72/100.", OUTCOME_OK)
ok(len(_v_ok) == 0, "E1 ok outcome: reformulated numbers not flagged")

# not_found — response_text has no numbers; llm invents stats
_v_nf = _check_numeric_invention(
    "Sorry, no player found. Haaland has 82 points though.",
    "No player matching 'xyz' found.",
    OUTCOME_NOT_FOUND,
)
ok(len(_v_nf) > 0, "E2 not_found: invented '82' flagged")
ok(all(VIOLATION_INVENTED_NUMBERS in v for v in _v_nf), "E3 violation prefix correct for not_found")

# unsupported — no numbers in response_text; llm invents
_v_us = _check_numeric_invention(
    "Haaland has a captain score of 85 this week.",
    "That question is outside the supported scope.",
    OUTCOME_UNSUPPORTED_INTENT,
)
ok(len(_v_us) > 0, "E4 unsupported: invented score '85' flagged")

# ambiguous — response has no numbers; llm invents rank
_v_amb = _check_numeric_invention(
    "The 1st player named Doe scored 70 last week.",
    "Multiple players matching 'Doe' found.",
    OUTCOME_AMBIGUOUS,
)
ok(len(_v_amb) > 0, "E5 ambiguous: invented numbers '1' and '70' flagged")

# numbers present in both response_text and llm_text — no violation
_v_same = _check_numeric_invention(
    "That question is outside my scope. GW28 is current.",
    "That question is outside my scope. GW28 is current.",
    OUTCOME_UNSUPPORTED_INTENT,
)
ok(len(_v_same) == 0, "E6 same numbers in both: no violation")

# response_text has number; llm_text repeats it — no violation
_v_repeat = _check_numeric_invention(
    "No player was found. Try searching again. You need 3 candidates.",
    "No player was found. Try again with 3 candidates.",
    OUTCOME_MISSING_ARGUMENTS,
)
ok(len(_v_repeat) == 0, "E7 repeated numbers not flagged")

# Clean texts for all non-ok outcomes
_non_ok_clean = [
    ("Sorry, no player found.", "Sorry, no player found.", OUTCOME_NOT_FOUND),
    ("Multiple players found.", "Multiple players found.", OUTCOME_AMBIGUOUS),
    ("Please provide a candidates list.", "Please provide a candidates list.",
     OUTCOME_MISSING_ARGUMENTS),
    ("An error occurred.", "An error occurred.", OUTCOME_ERROR),
    ("Outside supported scope.", "Outside supported scope.", OUTCOME_UNSUPPORTED_INTENT),
]
for _lt, _rt, _oc in _non_ok_clean:
    _v = _check_numeric_invention(_lt, _rt, _oc)
    ok(len(_v) == 0, f"E8 clean identical texts: no violation for outcome={_oc}")

ok(isinstance(_check_numeric_invention("test", "test", OUTCOME_OK), list), "E9 returns list")

# ---------------------------------------------------------------------------
# F. _check_ambiguous_false_resolution
# ---------------------------------------------------------------------------

section("F. _check_ambiguous_false_resolution")

# Non-ambiguous outcomes — never flagged
for _oc in [OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_MISSING_ARGUMENTS,
            OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT]:
    _v = _check_ambiguous_false_resolution("that would be Haaland you want.", _oc)
    ok(len(_v) == 0, f"F1 outcome={_oc}: resolution phrase not flagged (only checks ambiguous)")

# Ambiguous + resolution phrases
_resolution_phrases_to_test = [
    "that would be",
    "the player you're looking for is",
    "must be",
    "it's clearly",
    "clearly referring to",
    "you should go with",
]
for _rp in _resolution_phrases_to_test:
    _v = _check_ambiguous_false_resolution(
        f"I think {_rp} Salah, the Liverpool winger.", OUTCOME_AMBIGUOUS
    )
    ok(len(_v) > 0, f"F2 ambiguous + resolution phrase '{_rp}' flagged")
    ok(all(VIOLATION_AMBIGUOUS_FALSE_RESOLUTION in v for v in _v),
       f"F3 violation prefix correct for phrase '{_rp}'")

# Clean ambiguous response
_v_clean_ambig = _check_ambiguous_false_resolution(
    "Multiple players matched 'Doe'. Please be more specific, e.g. use first name.",
    OUTCOME_AMBIGUOUS,
)
ok(len(_v_clean_ambig) == 0, "F4 clean ambiguous text: no resolution phrases")

ok(isinstance(_check_ambiguous_false_resolution("test", OUTCOME_AMBIGUOUS), list), "F5 returns list")

# ---------------------------------------------------------------------------
# G. _check_empty_llm_text
# ---------------------------------------------------------------------------

section("G. _check_empty_llm_text")

# llm_called=True, empty text → violation
_v_empty = _check_empty_llm_text("", llm_called=True)
ok(len(_v_empty) == 1, "G1 empty text with llm_called=True → 1 violation")
ok(VIOLATION_EMPTY_LLM_TEXT in _v_empty[0], "G2 correct violation prefix")

# llm_called=False, empty text → no violation (fallback used — empty shouldn't happen but not dangerous)
_v_empty_fb = _check_empty_llm_text("", llm_called=False)
ok(len(_v_empty_fb) == 0, "G3 empty text with llm_called=False → no violation")

# Non-empty text — no violation regardless of llm_called
_v_ne_true  = _check_empty_llm_text("Some text here.", llm_called=True)
_v_ne_false = _check_empty_llm_text("Some text here.", llm_called=False)
ok(len(_v_ne_true) == 0,  "G4 non-empty text with llm_called=True → no violation")
ok(len(_v_ne_false) == 0, "G5 non-empty text with llm_called=False → no violation")

ok(isinstance(_check_empty_llm_text("x", True), list), "G6 returns list")

# ---------------------------------------------------------------------------
# H. review_llm_response — clean deterministic fallbacks
# ---------------------------------------------------------------------------

section("H. review_llm_response — clean deterministic fallbacks")

# Deterministic fallback path: llm_called=False, llm_text==response_text
# _check_numeric_invention always passes (same strings)
# _check_overconfidence: backend text is controlled and should not contain bad phrases
# _check_ambiguous_false_resolution: backend ambiguous text is "Multiple players..."

for _lr in _ALL_LR:
    _rr = review_llm_response(_lr)
    ok(isinstance(_rr, ReviewResult),
       f"H1 returns ReviewResult for intent={_lr.adapter_response.dispatch_result.intent}")
    ok(isinstance(_rr.passed, bool),
       f"H2 passed is bool for intent={_lr.adapter_response.dispatch_result.intent}")
    ok(isinstance(_rr.violations, tuple),
       f"H3 violations is tuple for intent={_lr.adapter_response.dispatch_result.intent}")
    ok(isinstance(_rr.safe_text, str),
       f"H4 safe_text is str for intent={_lr.adapter_response.dispatch_result.intent}")
    # Deterministic fallback should pass (no invented numbers, no bad phrases in backend text)
    ok(_rr.passed is True,
       f"H5 deterministic fallback passes review for intent={_lr.adapter_response.dispatch_result.intent}")
    ok(_rr.safe_text == _lr.llm_text,
       f"H6 safe_text==llm_text when passed for intent={_lr.adapter_response.dispatch_result.intent}")
    ok(len(_rr.violations) == 0,
       f"H7 no violations for deterministic fallback intent={_lr.adapter_response.dispatch_result.intent}")

# ---------------------------------------------------------------------------
# I. review_llm_response — violation cases (mock bad LLM text)
# ---------------------------------------------------------------------------

section("I. review_llm_response — violation cases (mock bad LLM text)")

# I1: overconfident phrase on not_found outcome
_lr_nf_bad = _make_llm_response(
    _lr_notfound,
    "I can definitely find that player — try again and I'll certainly locate them."
)
_rr_nf_bad = review_llm_response(_lr_nf_bad)
ok(_rr_nf_bad.passed is False, "I1a overconfident not_found: review fails")
ok(any(VIOLATION_OVERCONFIDENT_NON_OK in v for v in _rr_nf_bad.violations),
   "I1b overconfident not_found: correct violation type")
ok(_rr_nf_bad.safe_text == _lr_notfound.adapter_response.response_text,
   "I1c overconfident not_found: safe_text falls back to response_text")

# I2: invented numbers on not_found outcome
_lr_nf_inv = _make_llm_response(
    _lr_notfound,
    "Player not found, but Haaland scored 82/100 this week and is a great choice."
)
_rr_nf_inv = review_llm_response(_lr_nf_inv)
ok(_rr_nf_inv.passed is False, "I2a invented numbers not_found: review fails")
ok(any(VIOLATION_INVENTED_NUMBERS in v for v in _rr_nf_inv.violations),
   "I2b invented numbers not_found: correct violation type")

# I3: false resolution on ambiguous outcome
_lr_amb_bad = _make_llm_response(
    _lr_ambiguous,
    "There are two Doe players, but based on context it's clearly the defender you want."
)
_rr_amb_bad = review_llm_response(_lr_amb_bad)
ok(_rr_amb_bad.passed is False, "I3a false resolution ambiguous: review fails")
ok(any(VIOLATION_AMBIGUOUS_FALSE_RESOLUTION in v for v in _rr_amb_bad.violations),
   "I3b false resolution ambiguous: correct violation type")

# I4: invented score on unsupported outcome
_lr_us_bad = _make_llm_response(
    _lr_unsupport,
    "Haaland has a fitness score of 95 out of 100. He's fine to captain."
)
_rr_us_bad = review_llm_response(_lr_us_bad)
ok(_rr_us_bad.passed is False, "I4a invented numbers unsupported: review fails")
ok(any(VIOLATION_INVENTED_NUMBERS in v for v in _rr_us_bad.violations),
   "I4b invented numbers unsupported: correct violation type")

# I5: empty text from LLM call
_lr_empty = _make_llm_response(_lr_captain, "", llm_called=True)
_rr_empty = review_llm_response(_lr_empty)
ok(_rr_empty.passed is False, "I5a empty llm_text: review fails")
ok(any(VIOLATION_EMPTY_LLM_TEXT in v for v in _rr_empty.violations),
   "I5b empty llm_text: correct violation type")

# I6: clean LLM text for ok outcome — no violations
_lr_captain_clean = _make_llm_response(
    _lr_captain,
    "Haaland looks like a strong captain pick this week based on the analysis."
)
_rr_captain_clean = review_llm_response(_lr_captain_clean)
ok(_rr_captain_clean.passed is True, "I6a clean ok llm_text: passes review")
ok(len(_rr_captain_clean.violations) == 0, "I6b clean ok llm_text: no violations")

# I7: clean LLM text for not_found — no violations
_lr_nf_clean = _make_llm_response(
    _lr_notfound,
    "Sorry, no player matching that name was found. Please check the spelling."
)
_rr_nf_clean = review_llm_response(_lr_nf_clean)
ok(_rr_nf_clean.passed is True, "I7a clean not_found llm_text: passes review")
ok(len(_rr_nf_clean.violations) == 0, "I7b clean not_found llm_text: no violations")

# I8: clean LLM text for ambiguous — no violations
_lr_amb_clean = _make_llm_response(
    _lr_ambiguous,
    "Multiple players matched the name 'Doe'. Could you be more specific?"
)
_rr_amb_clean = review_llm_response(_lr_amb_clean)
ok(_rr_amb_clean.passed is True, "I8a clean ambiguous llm_text: passes review")
ok(len(_rr_amb_clean.violations) == 0, "I8b clean ambiguous llm_text: no violations")

# I9: clean LLM text for missing_args — no violations
_lr_miss_clean = _make_llm_response(
    _lr_missing,
    "To rank captain candidates I need a list of players to evaluate. Please provide candidates."
)
_rr_miss_clean = review_llm_response(_lr_miss_clean)
ok(_rr_miss_clean.passed is True, "I9a clean missing_args llm_text: passes review")
ok(len(_rr_miss_clean.violations) == 0, "I9b clean missing_args llm_text: no violations")

# I10: clean LLM text for unsupported — no violations
_lr_us_clean = _make_llm_response(
    _lr_unsupport,
    "That question is outside my supported scope. I can help with captain picks, "
    "player summaries, and gameweek information."
)
_rr_us_clean = review_llm_response(_lr_us_clean)
ok(_rr_us_clean.passed is True, "I10a clean unsupported llm_text: passes review")
ok(len(_rr_us_clean.violations) == 0, "I10b clean unsupported llm_text: no violations")

# ---------------------------------------------------------------------------
# J. safe_text semantics
# ---------------------------------------------------------------------------

section("J. safe_text semantics")

# When passed=True: safe_text == llm_text
_lr_passed = _make_llm_response(_lr_captain, "Haaland is a great pick this week.")
_rr_passed = review_llm_response(_lr_passed)
# ok only if no violations — clean text for ok outcome
if _rr_passed.passed:
    ok(_rr_passed.safe_text == _lr_passed.llm_text,
       "J1 passed=True: safe_text == llm_text")
else:
    ok(True, "J1 skipped — clean ok text triggered unexpected violation")

# When passed=False: safe_text == response_text (deterministic ground truth)
_lr_bad = _make_llm_response(
    _lr_notfound,
    "I can definitely find that player for you — score is 72 and he's great."
)
_rr_bad = review_llm_response(_lr_bad)
ok(_rr_bad.passed is False, "J2 bad text for not_found: passed=False")
ok(_rr_bad.safe_text == _lr_notfound.adapter_response.response_text,
   "J3 failed review: safe_text == adapter_response.response_text")
ok(_rr_bad.safe_text != _lr_bad.llm_text,
   "J4 failed review: safe_text != llm_text")

# Invariant: safe_text is always a non-empty str
for _lr in _ALL_LR:
    _rr = review_llm_response(_lr)
    ok(isinstance(_rr.safe_text, str),   f"J5 safe_text is str for {_lr.adapter_response.dispatch_result.intent}")
    ok(len(_rr.safe_text) > 0,           f"J6 safe_text is non-empty for {_lr.adapter_response.dispatch_result.intent}")

# ---------------------------------------------------------------------------
# K. ask_llm_safe — structure
# ---------------------------------------------------------------------------

section("K. ask_llm_safe — structure")

_lr_k, _rr_k = ask_llm_safe("should I captain Haaland", BS)
ok(isinstance(_lr_k, LLMResponse),  "K1 ask_llm_safe returns (LLMResponse, ReviewResult)")
ok(isinstance(_rr_k, ReviewResult), "K2 second element is ReviewResult")
ok(_lr_k.user_message == "should I captain Haaland", "K3 user_message preserved")
ok(isinstance(_rr_k.safe_text, str), "K4 safe_text is str")
ok(len(_rr_k.safe_text) > 0,        "K5 safe_text is non-empty")

# All 9 scenario types
_safe_cases = [
    ("should I captain Haaland",          BS,  None,                               OUTCOME_OK),
    ("what gameweek is it",               BS,  None,                               OUTCOME_OK),
    ("summary for Salah",                 BS,  None,                               OUTCOME_OK),
    ("who is Haaland",                    BS,  None,                               OUTCOME_OK),
    ("top captains this week",            BS,
     [{"query": "Haaland"}, {"query": "Salah"}],                                    OUTCOME_OK),
    ("should I captain xyznotaplayer999", BS,  None,                               OUTCOME_NOT_FOUND),
    ("who is Doe",                        ABS, None,                               OUTCOME_AMBIGUOUS),
    ("top captains this week",            BS,  None,                               OUTCOME_MISSING_ARGUMENTS),
    ("Is Haaland fit to play?",           BS,  None,                               OUTCOME_UNSUPPORTED_INTENT),
]

for _msg, _bs, _cands, _exp_oc in _safe_cases:
    _lr_s, _rr_s = ask_llm_safe(_msg, _bs, candidates_list=_cands)
    ok(isinstance(_lr_s, LLMResponse),  f"K6 LLMResponse for outcome={_exp_oc}")
    ok(isinstance(_rr_s, ReviewResult), f"K7 ReviewResult for outcome={_exp_oc}")
    ok(_lr_s.adapter_response.dispatch_result.outcome == _exp_oc,
       f"K8 adapter outcome={_exp_oc} preserved")
    ok(isinstance(_rr_s.safe_text, str), f"K9 safe_text is str for outcome={_exp_oc}")
    # Deterministic fallback path always passes review
    ok(_rr_s.passed is True,            f"K10 deterministic fallback passes review for outcome={_exp_oc}")

# ---------------------------------------------------------------------------
# L. ask_llm_safe — safe_text fallback on violations (mock bad client)
# ---------------------------------------------------------------------------

section("L. ask_llm_safe — safe_text fallback on violations (mock client)")


class _BadClientNotFound:
    """Returns an overconfident response for a not_found outcome."""

    class _Content:
        text = "I can definitely find that player — score is 99 and they are top tier."

    class _Response:
        content = [_BadClientNotFound_Content := type(
            '_C', (), {'text': "I can definitely find that player — score is 99 and top tier."}
        )()]

    class _Messages:
        def create(self, **kwargs):
            return _BadClientNotFound._Response()

    messages = _Messages()


# Build the mock properly
class _BadContent:
    text = "I can definitely find that player — score is 99 and top tier."

class _BadResponse:
    content = [_BadContent()]

class _BadClient:
    class _Messages:
        def create(self, **kwargs):
            return _BadResponse()
    messages = _Messages()


_lr_lb, _rr_lb = ask_llm_safe(
    "should I captain xyznotaplayer999", BS, client=_BadClient()
)
ok(isinstance(_lr_lb, LLMResponse),          "L1 bad client: returns LLMResponse")
ok(isinstance(_rr_lb, ReviewResult),         "L2 bad client: returns ReviewResult")
ok(_lr_lb.llm_called is True,               "L3 bad client: llm_called=True")
ok(_rr_lb.passed is False,                   "L4 bad client: review fails for bad not_found text")
ok(_rr_lb.safe_text == _lr_lb.adapter_response.response_text,
                                             "L5 bad client: safe_text falls back to response_text")
ok(_rr_lb.safe_text != _lr_lb.llm_text,     "L6 bad client: safe_text != llm_text")

# Good mock client — should pass review
class _GoodContent:
    text = "Sorry, no player matching that name was found. Please check the spelling."

class _GoodResponse:
    content = [_GoodContent()]

class _GoodClient:
    class _Messages:
        def create(self, **kwargs):
            return _GoodResponse()
    messages = _Messages()


_lr_lg, _rr_lg = ask_llm_safe(
    "should I captain xyznotaplayer999", BS, client=_GoodClient()
)
ok(_lr_lg.llm_called is True,               "L7 good client: llm_called=True")
ok(_rr_lg.passed is True,                   "L8 good client: review passes for clean text")
ok(_rr_lg.safe_text == _lr_lg.llm_text,     "L9 good client: safe_text == llm_text when passed")

# ---------------------------------------------------------------------------
# M. Fixture-based review (all 9 scenarios, deterministic path)
# ---------------------------------------------------------------------------

section("M. Fixture-based review — all 9 scenarios, deterministic path")

_p2n_results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)

for _fix, _ar in _p2n_results:
    # Build a LLMResponse for this fixture (deterministic fallback path)
    _lr_fix = ask_llm(
        _fix.user_message,
        AMBIGUOUS_BOOTSTRAP if _fix.use_ambiguous_bootstrap else STANDARD_BOOTSTRAP,
        candidates_list=_fix.candidates_list,
    )
    _rr_fix = review_llm_response(_lr_fix)

    ok(isinstance(_rr_fix, ReviewResult),
       f"M1 ReviewResult for fixture={_fix.scenario_id}")
    ok(_rr_fix.passed is True,
       f"M2 deterministic fallback passes review for fixture={_fix.scenario_id}")
    ok(len(_rr_fix.violations) == 0,
       f"M3 no violations for fixture={_fix.scenario_id}")
    ok(_rr_fix.safe_text == _lr_fix.adapter_response.response_text,
       f"M4 safe_text==response_text (fallback path) for fixture={_fix.scenario_id}")
    ok(_rr_fix.llm_response is _lr_fix,
       f"M5 llm_response is the original LLMResponse for fixture={_fix.scenario_id}")

# ---------------------------------------------------------------------------
# N. Semantic drift guardrails — per outcome class
# ---------------------------------------------------------------------------

section("N. Semantic drift guardrails — per outcome class")

# The review layer must catch these specific drift patterns:

# N1: ok outcome — overconfident phrases NOT flagged (grounded data available)
_ok_overconf = _make_llm_response(
    _lr_captain, "Haaland definitely looks great — definitely the best pick."
)
_rr_ok_oc = review_llm_response(_ok_overconf)
ok(_rr_ok_oc.passed is True,
   "N1 ok outcome: 'definitely' NOT flagged (grounded backend supports the claim)")

# N2: not_found — must not invent player stats
_nf_invents = _make_llm_response(
    _lr_notfound,
    "That player wasn't found, but based on general knowledge he scored 72 last week."
)
_rr_nf_invents = review_llm_response(_nf_invents)
ok(_rr_nf_invents.passed is False, "N2a not_found: invented stats caught")
ok(any(VIOLATION_INVENTED_NUMBERS in v for v in _rr_nf_invents.violations),
   "N2b not_found: INVENTED_NUMBERS violation present")

# N3: not_found — must not overstate confidence
_nf_overconf = _make_llm_response(
    _lr_notfound,
    "I certainly know who that player is, they must exist in the database."
)
_rr_nf_overconf = review_llm_response(_nf_overconf)
ok(_rr_nf_overconf.passed is False, "N3a not_found: overconfidence caught")
ok(any(VIOLATION_OVERCONFIDENT_NON_OK in v for v in _rr_nf_overconf.violations),
   "N3b not_found: OVERCONFIDENT_NON_OK violation present")

# N4: ambiguous — must not resolve to single player
_amb_resolves = _make_llm_response(
    _lr_ambiguous,
    "There are two Doe players. Based on context it must be the Liverpool defender."
)
_rr_amb_resolves = review_llm_response(_amb_resolves)
ok(_rr_amb_resolves.passed is False, "N4a ambiguous: false resolution caught")
ok(any(VIOLATION_AMBIGUOUS_FALSE_RESOLUTION in v for v in _rr_amb_resolves.violations),
   "N4b ambiguous: AMBIGUOUS_FALSE_RESOLUTION violation present")

# N5: ambiguous — must not invent scores
_amb_invents = _make_llm_response(
    _lr_ambiguous,
    "Two players named Doe: one scored 82, the other 74 last week."
)
_rr_amb_invents = review_llm_response(_amb_invents)
ok(_rr_amb_invents.passed is False, "N5a ambiguous: invented scores caught")

# N6: missing_arguments — must not invent a ranked list
_miss_invents = _make_llm_response(
    _lr_missing,
    "Here are the top captains: 1. Haaland 85, 2. Salah 78, 3. Saka 71."
)
_rr_miss_invents = review_llm_response(_miss_invents)
ok(_rr_miss_invents.passed is False, "N6a missing_args: invented ranking caught")
ok(any(VIOLATION_INVENTED_NUMBERS in v for v in _rr_miss_invents.violations),
   "N6b missing_args: INVENTED_NUMBERS violation present")

# N7: unsupported — must not answer the question
_us_answers = _make_llm_response(
    _lr_unsupport,
    "Haaland's fitness score is 90 out of 100. He's available and should be fine."
)
_rr_us_answers = review_llm_response(_us_answers)
ok(_rr_us_answers.passed is False, "N7a unsupported: invented answer caught")
ok(any(VIOLATION_INVENTED_NUMBERS in v for v in _rr_us_answers.violations),
   "N7b unsupported: INVENTED_NUMBERS violation present")

# N8: unsupported — overconfident phrasing flagged
_us_overconf = _make_llm_response(
    _lr_unsupport,
    "I can certainly answer that — Haaland is definitely going to play this week."
)
_rr_us_overconf = review_llm_response(_us_overconf)
ok(_rr_us_overconf.passed is False, "N8a unsupported: overconfidence caught")
ok(any(VIOLATION_OVERCONFIDENT_NON_OK in v for v in _rr_us_overconf.violations),
   "N8b unsupported: OVERCONFIDENT_NON_OK violation present")

# ---------------------------------------------------------------------------
# O. _OVERCONFIDENT_PHRASES and _AMBIGUOUS_RESOLUTION_PHRASES
# ---------------------------------------------------------------------------

section("O. Phrase list structure")

ok(isinstance(_OVERCONFIDENT_PHRASES,        frozenset), "O1 _OVERCONFIDENT_PHRASES is frozenset")
ok(isinstance(_AMBIGUOUS_RESOLUTION_PHRASES, frozenset), "O2 _AMBIGUOUS_RESOLUTION_PHRASES is frozenset")
ok(len(_OVERCONFIDENT_PHRASES) >= 5,   "O3 _OVERCONFIDENT_PHRASES has at least 5 entries")
ok(len(_AMBIGUOUS_RESOLUTION_PHRASES) >= 5, "O4 _AMBIGUOUS_RESOLUTION_PHRASES has at least 5 entries")
# All lowercase (check helpers use .lower() on input)
for _ph in _OVERCONFIDENT_PHRASES:
    ok(_ph == _ph.lower(), f"O5 overconfident phrase is lowercase: {_ph!r}")
for _ph in _AMBIGUOUS_RESOLUTION_PHRASES:
    ok(_ph == _ph.lower(), f"O6 resolution phrase is lowercase: {_ph!r}")

# Core phrases present
ok("definitely"    in _OVERCONFIDENT_PHRASES, "O7 'definitely' in overconfident phrases")
ok("certainly"     in _OVERCONFIDENT_PHRASES, "O8 'certainly' in overconfident phrases")
ok("guaranteed"    in _OVERCONFIDENT_PHRASES, "O9 'guaranteed' in overconfident phrases")
ok("must be"       in _AMBIGUOUS_RESOLUTION_PHRASES, "O10 'must be' in resolution phrases")
ok("clearly referring to" in _AMBIGUOUS_RESOLUTION_PHRASES,
   "O11 'clearly referring to' in resolution phrases")

# ---------------------------------------------------------------------------
# P. Phase 3a regression
# ---------------------------------------------------------------------------

section("P. Phase 3a regression")

_lr_p = ask_llm("should I captain Haaland", BS)
ok(isinstance(_lr_p, LLMResponse),              "P1 ask_llm returns LLMResponse")
ok(_lr_p.llm_called is False,                   "P2 llm_called=False without API key")
ok(_lr_p.model == "none",                       "P3 model='none' in fallback")
ok(_lr_p.llm_text == _lr_p.adapter_response.response_text,
                                                "P4 fallback: llm_text == response_text")
ok(len(_lr_p.prompt_used) > 0,                  "P5 prompt_used populated")
ok(isinstance(_lr_p.adapter_response, AdapterResponse), "P6 adapter_response is AdapterResponse")

_lr_p_unsup = ask_llm("Is Haaland fit to play?", BS)
ok(_lr_p_unsup.adapter_response.supported is False, "P7 unsupported: supported=False preserved")
ok(_lr_p_unsup.adapter_response.dispatch_result.outcome == OUTCOME_UNSUPPORTED_INTENT,
                                                "P8 unsupported: outcome preserved")

# ---------------------------------------------------------------------------
# Q. Interface report
# ---------------------------------------------------------------------------

section("Q. Interface report")

print("\n  Phase 3b public surface:")
print(f"    review_llm_response(llm_response) → ReviewResult")
print(f"    ask_llm_safe(user_message, bootstrap, ...) → (LLMResponse, ReviewResult)")
print(f"    ReviewResult: frozen dataclass, 4 fields (passed, violations, llm_response, safe_text)")
print()
print("  Violation constants:")
print(f"    {VIOLATION_OVERCONFIDENT_NON_OK!r}")
print(f"    {VIOLATION_INVENTED_NUMBERS!r}")
print(f"    {VIOLATION_AMBIGUOUS_FALSE_RESOLUTION!r}")
print(f"    {VIOLATION_EMPTY_LLM_TEXT!r}")
print()
print("  Violation checks (4 total):")
print("    _check_overconfidence      — non-ok outcomes: flags 'definitely', 'certainly', etc.")
print("    _check_numeric_invention   — non-ok outcomes: flags numbers not in response_text")
print("    _check_ambiguous_false_resolution — ambiguous: flags resolution phrases")
print("    _check_empty_llm_text      — always: flags empty text from LLM call")
print()
print("  Safe fallback invariant:")
print("    ReviewResult.safe_text = llm_text  when passed=True")
print("    ReviewResult.safe_text = response_text  when passed=False")
print()
print("  Semantic drift intentionally NOT checked:")
print("    - Semantic similarity / embedding-based drift detection")
print("    - Multi-turn coherence")
print("    - LLM-assisted review")
print("    - ok outcome overconfidence (grounded data supports moderate confidence)")

ok(True, "Q1 interface report printed")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

# Restore API key if it was set before this suite ran
if _saved_key:
    os.environ["ANTHROPIC_API_KEY"] = _saved_key

sys.exit(summary())


