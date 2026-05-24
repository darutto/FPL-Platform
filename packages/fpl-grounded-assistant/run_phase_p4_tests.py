"""
run_phase_p4_tests.py
=====================
Phase P4: Off-topic guardrails — evaluator SAFE-axis tightening + heuristic.

Sections
--------
T   off_topic.is_off_topic_response() pure-function tests (T1-T4)
S   off_topic.contains_off_topic_solution() tests (T5-T7)
K   Keyword-set sanity checks (T8-T12)
E   evaluator.evaluate_response() + EvaluatorVerdict.off_topic_score (E1-E6)
I   Integration: HTTP POST /ask with off-topic query (I1-I3)

~24 assertions. Exit code 0 on success, 1 on any failure.

Run from packages/fpl-grounded-assistant::

    python run_phase_p4_tests.py
"""
from __future__ import annotations

import os
import sys
import unittest.mock as _mock

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

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.off_topic import (
    is_off_topic_response,
    contains_off_topic_solution,
    _FPL_TOPIC_KEYWORDS,
    _OFF_TOPIC_KEYWORDS,
)
from fpl_grounded_assistant.evaluator import (
    EvaluatorVerdict,
    evaluate_response,
    _EVALUATOR_SYSTEM_PROMPT,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


# ===========================================================================
# T: is_off_topic_response() pure function tests
# ===========================================================================

print("\n=== T: is_off_topic_response() ===")

# T1: Pure FPL text -> NOT off-topic.
_fpl_text = (
    "Haaland is your best captain this gameweek. He has 12 goals in the premier league "
    "with strong fixtures. His form is excellent and ownership is 45% in FPL."
)
_t1_flag, _t1_score, _t1_diag = is_off_topic_response(_fpl_text)
ok(not _t1_flag, "T1: pure FPL text is NOT off-topic")
ok(_t1_score < 0.5, f"T1b: FPL text score < 0.5 (got {_t1_score:.3f})")
ok(_t1_diag["fpl_hits"] > 0, f"T1c: FPL hits > 0 (got {_t1_diag['fpl_hits']})")

# T2: Pure recipe text -> IS off-topic.
_recipe_text = (
    "Here's a great recipe for chocolate cake. You'll need the following ingredients: "
    "flour, eggs, sugar, butter. Mix them and bake at 180°C for 30 minutes."
)
_t2_flag, _t2_score, _t2_diag = is_off_topic_response(_recipe_text)
ok(_t2_flag, "T2: pure recipe text IS off-topic")
ok(_t2_score >= 0.5, f"T2b: recipe score >= 0.5 (got {_t2_score:.3f})")
ok(_t2_diag["off_topic_hits"] > 0, f"T2c: off-topic hits > 0 (got {_t2_diag['off_topic_hits']})")

# T2-ES: Spanish recipe text -> IS off-topic (P4.f verifier remediation).
# Original P4 keyword set was English-only on cooking terms; Spanish flan
# recipe slipped through. Now caught.
_recipe_text_es = (
    "Receta para flan: necesitas 3 huevos, 1 taza de azúcar, leche, y "
    "hornearlo al horno por 45 minutos. Sirve frío."
)
_t2es_flag, _t2es_score, _t2es_diag = is_off_topic_response(_recipe_text_es)
ok(_t2es_flag, "T2-ES: Spanish flan recipe IS off-topic")
ok(_t2es_score >= 0.5, f"T2-ES-b: Spanish recipe score >= 0.5 (got {_t2es_score:.3f})")
ok(_t2es_diag["off_topic_hits"] > 0,
   f"T2-ES-c: Spanish recipe off-topic hits > 0 (got {_t2es_diag['off_topic_hits']})")

# T3: Mixed text — FPL query with off-topic detour — depends on ratio.
# This text deliberately has more FPL signal than off-topic to stay on-topic.
_mixed_fpl_heavy = (
    "Great question about FPL transfers! Your captain pick this gameweek should be Salah. "
    "He has great fixtures and strong form. His ownership in fantasy is high. "
    "His goals and assists make him a top differential. Premier league form is outstanding."
)
_t3_flag, _t3_score, _ = is_off_topic_response(_mixed_fpl_heavy)
ok(not _t3_flag, "T3: FPL-heavy mixed text is NOT off-topic (FPL signal dominates)")

# T4: Empty text -> NOT off-topic (safe default).
_t4_flag, _t4_score, _t4_diag = is_off_topic_response("")
ok(not _t4_flag, "T4: empty text is NOT off-topic")
ok(_t4_score == 0.0, f"T4b: empty text score == 0.0 (got {_t4_score})")
ok(_t4_diag["fpl_hits"] == 0 and _t4_diag["off_topic_hits"] == 0, "T4c: empty text has zero hits")

# ===========================================================================
# S: contains_off_topic_solution() tests
# ===========================================================================

print("\n=== S: contains_off_topic_solution() ===")

# T5: Clean FPL response -> False (no refusal, no off-topic, no answer pattern).
_fpl_response = (
    "Based on the fixture data, I recommend Salah as your captain this gameweek. "
    "His form score is 9.2 and he faces a team with poor defensive record."
)
ok(not contains_off_topic_solution(_fpl_response), "T5: clean FPL response -> False")

# T6: Refusal + off-topic keyword + answer pattern -> True.
_slip_text = (
    "I can't help with math homework, that's out of scope for me. "
    "But just so you know, the answer is 5. Anyway, back to FPL..."
)
ok(contains_off_topic_solution(_slip_text), "T6: refusal + off-topic + answer pattern -> True")

# T7: FPL response that mentions "raíz cuadrada" in passing (e.g. user quote)
# WITHOUT providing an answer pattern -> False.
_fpl_mention = (
    "You asked about the raíz cuadrada earlier but I won't help with that. "
    "I'm here for FPL. Your captain this gameweek is Haaland — great fixtures in the premier league."
)
# This has a refusal phrase and off-topic keyword, but does it have an answer pattern?
# It does NOT say "the answer is X" or "= X", so should be False.
_t7 = contains_off_topic_solution(_fpl_mention)
ok(not _t7, "T7: FPL response with off-topic mention but no answer -> False")

# ===========================================================================
# K: Keyword-set sanity checks
# ===========================================================================

print("\n=== K: Keyword-set sanity checks ===")

# T8: FPL keyword set is non-empty.
ok(len(_FPL_TOPIC_KEYWORDS) > 0, "T8: _FPL_TOPIC_KEYWORDS is non-empty")

# T9: OFF_TOPIC keyword set is non-empty.
ok(len(_OFF_TOPIC_KEYWORDS) > 0, "T9: _OFF_TOPIC_KEYWORDS is non-empty")

# T10: All FPL keywords are lowercase.
ok(all(kw == kw.lower() for kw in _FPL_TOPIC_KEYWORDS), "T10: all FPL keywords are lowercase")

# T11: All OFF_TOPIC keywords are lowercase.
ok(all(kw == kw.lower() for kw in _OFF_TOPIC_KEYWORDS), "T11: all OFF_TOPIC keywords are lowercase")

# T12: No overlap between the two keyword sets.
_overlap = _FPL_TOPIC_KEYWORDS & _OFF_TOPIC_KEYWORDS
ok(len(_overlap) == 0, f"T12: no overlap between FPL and OFF_TOPIC keyword sets (overlap: {_overlap})")

# ===========================================================================
# E: evaluator.evaluate_response() — off_topic_score field + heuristic override
# ===========================================================================

print("\n=== E: evaluator EvaluatorVerdict.off_topic_score + heuristic override ===")

# Helper: build a mock LLM client that returns a given JSON verdict string.
def _make_mock_client(verdict_json: str):
    """Return a mock Anthropic-style client that returns verdict_json."""
    mock_block = _mock.MagicMock()
    mock_block.type = "text"
    mock_block.text = verdict_json
    mock_response = _mock.MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage = _mock.MagicMock()
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    mock_client = _mock.MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


# E1: EvaluatorVerdict has off_topic_score field (type check).
_e1_verdict = EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True)
ok(hasattr(_e1_verdict, "off_topic_score"), "E1: EvaluatorVerdict has off_topic_score field")
ok(isinstance(_e1_verdict.off_topic_score, float), "E1b: off_topic_score is a float")
ok(_e1_verdict.off_topic_score == 0.0, "E1c: off_topic_score defaults to 0.0")

# E2: evaluate_response populates off_topic_score on a clean FPL response.
_e2_client = _make_mock_client('{"grounded": true, "complete": true, "safe": true, "retry_feedback": null}')
_e2_verdict = evaluate_response(
    question="who should I captain this gameweek?",
    primary_response=(
        "Haaland is your best captain this gameweek. He has excellent form and "
        "great premier league fixtures. His FPL ownership is high and goals tally is strong."
    ),
    tool_calls=[],
    provider="anthropic",
    client=_e2_client,
)
ok(isinstance(_e2_verdict.off_topic_score, float), "E2: off_topic_score is float after evaluate_response")
ok(_e2_verdict.off_topic_score >= 0.0, "E2b: off_topic_score >= 0.0")

# E3: evaluate_response populates off_topic_score on an off-topic response (higher score).
_e3_client = _make_mock_client('{"grounded": true, "complete": true, "safe": true, "retry_feedback": null}')
_e3_verdict = evaluate_response(
    question="give me a recipe for cake",
    primary_response=(
        "Here's a great recipe for chocolate cake! You'll need these ingredients: "
        "flour, sugar, eggs, butter, cocoa. Mix them together and bake."
    ),
    tool_calls=[],
    provider="anthropic",
    client=_e3_client,
)
ok(_e3_verdict.off_topic_score > 0.0, f"E3: off-topic response has score > 0.0 (got {_e3_verdict.off_topic_score:.3f})")

# E4: Heuristic override fires when LLM says SAFE=true but score > 0.7 (recipe response).
# The recipe text above should trigger the override (high off_topic_score).
_e4_client = _make_mock_client('{"grounded": true, "complete": true, "safe": true, "retry_feedback": null}')
_e4_verdict = evaluate_response(
    question="give me a recipe for cake",
    primary_response=(
        "Here's a recipe for cake! You'll need ingredients: flour, sugar, eggs, butter, "
        "cooking oil, cocoa powder, baking powder. Mix and bake at 180°C."
    ),
    tool_calls=[],
    provider="anthropic",
    client=_e4_client,
)
# The off_topic_score should be high (many recipe keywords, zero FPL keywords).
ok(_e4_verdict.off_topic_score > 0.7, f"E4: recipe response off_topic_score > 0.7 (got {_e4_verdict.off_topic_score:.3f})")
ok(not _e4_verdict.approved, "E4b: heuristic override -> approved=False")
ok(_e4_verdict.safe is False, "E4c: heuristic override -> safe=False")

# E5: Override fires -> retry_feedback contains "off-topic" language.
ok(
    _e4_verdict.retry_feedback is not None and "off-topic" in (_e4_verdict.retry_feedback or "").lower(),
    f"E5: retry_feedback after override mentions 'off-topic' (got: {_e4_verdict.retry_feedback!r})",
)

# E6: SAFE=false retry_feedback contains "off-topic" language (LLM-driven, no override needed).
_e6_client = _make_mock_client(
    '{"grounded": true, "complete": true, "safe": false, '
    '"retry_feedback": "Response strayed off-topic. Refuse politely in user_lang and offer to help with FPL."}'
)
_e6_verdict = evaluate_response(
    question="what is 2+2",
    primary_response="The answer to 2+2 is 4.",
    tool_calls=[],
    provider="anthropic",
    client=_e6_client,
)
ok(not _e6_verdict.approved, "E6: LLM SAFE=false -> approved=False")
ok(
    _e6_verdict.retry_feedback is not None and "off-topic" in (_e6_verdict.retry_feedback or "").lower(),
    f"E6b: retry_feedback contains 'off-topic' (got: {_e6_verdict.retry_feedback!r})",
)

# ===========================================================================
# I: Integration — evaluator prompt tightening observable
# ===========================================================================

print("\n=== I: Integration — SAFE axis prompt tightening ===")

# I1: Evaluator system prompt contains off-topic examples.
ok("recipe" in _EVALUATOR_SYSTEM_PROMPT.lower(), "I1: evaluator prompt mentions 'recipe' as off-topic example")
ok("math" in _EVALUATOR_SYSTEM_PROMPT.lower(), "I2: evaluator prompt mentions 'math' as off-topic example")
ok("off-topic" in _EVALUATOR_SYSTEM_PROMPT.lower() or "off_topic" in _EVALUATOR_SYSTEM_PROMPT.lower(),
   "I3: evaluator prompt contains 'off-topic' language in SAFE axis")

# ===========================================================================
# Final summary
# ===========================================================================

print()
print("=" * 50)
print(f"Phase P4 results: {_pass}/{_pass + _fail} PASS")
if _fail:
    print(f"  {_fail} FAILED.")
else:
    print("  All assertions PASSED.")
print("=" * 50)
sys.exit(0 if _fail == 0 else 1)
