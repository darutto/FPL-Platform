"""
fpl_grounded_assistant.final_response_fixtures
===============================================
Executable fixtures documenting the stable caller-facing ``FinalResponse``
contract across all key scenarios.

Phase 3d: Final response contract hardening.

These fixtures serve three purposes:

1. **Contract documentation** — each scenario is a concrete, named, executable
   reference for the ``respond()`` / ``FinalResponse`` surface described in
   ``FINAL_RESPONSE_CONTRACT.md``.
2. **Regression guard** — ``run_all()`` executes all fixtures against the live
   system (using the deterministic fallback path) and verifies all expected
   field values.
3. **Integration reference** — external callers can import these fixtures to
   verify that ``respond()`` behaves correctly before wiring any UI or
   downstream consumers.

Relationship to ``conversation_fixtures``
------------------------------------------
``conversation_fixtures`` (Phase 2n) documents the *adapter* contract —
``adapt()`` returning ``AdapterResponse``.

These fixtures document the *final response* contract — ``respond()`` returning
``FinalResponse``.  They add ``expected_review_passed`` and ``expected_llm_used``
which do not exist at the adapter layer, and are tested in deterministic mode
(no API key) so ``llm_used=False`` for all scenarios.

Fixture IDs
-----------
supported_ok                — supported, outcome=ok
supported_ambiguous         — supported, outcome=ambiguous
supported_not_found         — supported, outcome=not_found
supported_missing_arguments — supported, outcome=missing_arguments
unsupported_intent          — unsupported, outcome=unsupported_intent
llm_fallback_to_deterministic — explicit fallback invariant:
                                final_text == response_text when no LLM client

Usage
-----
::

    from fpl_grounded_assistant.final_response_fixtures import (
        FINAL_RESPONSE_FIXTURE_DEFINITIONS,
        run_all,
        STANDARD_BOOTSTRAP,
        AMBIGUOUS_BOOTSTRAP,
    )

    results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
    for fixture, response in results:
        print(
            f"{fixture.scenario_id}: "
            f"outcome={response.outcome} "
            f"llm_used={response.llm_used}"
        )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Reuse the bootstraps from conversation_fixtures — single source of truth
from .conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
)


# ---------------------------------------------------------------------------
# Fixture schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinalResponseFixture:
    """A single named caller-facing scenario with expected ``FinalResponse`` values.

    Attributes
    ----------
    scenario_id:
        Unique kebab-case identifier used in test labels and contract docs.
    description:
        Human-readable explanation of what this scenario tests and why it
        belongs in the caller-facing contract.
    user_message:
        The raw message passed to ``respond()``.
    expected_outcome:
        Expected value of ``FinalResponse.outcome`` (one of the ``OUTCOME_*``
        constants).
    expected_supported:
        Expected value of ``FinalResponse.supported``.
    expected_intent:
        Expected value of ``FinalResponse.intent`` (one of the ``INTENT_*``
        constants).
    expected_review_passed:
        Expected value of ``FinalResponse.review_passed``.
        Always ``True`` in deterministic mode (no LLM called ⟹ no violations).
    expected_llm_used:
        Expected value of ``FinalResponse.llm_used``.
        Always ``False`` in deterministic mode (no API key ⟹ no LLM call).
    candidates_list:
        Optional list of candidate dicts forwarded to ``respond()``.
    use_ambiguous_bootstrap:
        When ``True``, ``run_all()`` passes ``AMBIGUOUS_BOOTSTRAP`` instead
        of ``STANDARD_BOOTSTRAP``.
    """
    scenario_id:              str
    description:              str
    user_message:             str
    expected_outcome:         str
    expected_supported:       bool
    expected_intent:          str
    expected_review_passed:   bool
    expected_llm_used:        bool
    candidates_list:          list[dict[str, Any]] | None = None
    use_ambiguous_bootstrap:  bool = False


# ---------------------------------------------------------------------------
# Fixture definitions — 6 canonical caller-facing scenarios
# ---------------------------------------------------------------------------

FINAL_RESPONSE_FIXTURE_DEFINITIONS: tuple[FinalResponseFixture, ...] = (

    FinalResponseFixture(
        scenario_id="supported_ok",
        description=(
            "Canonical supported-and-successful scenario. "
            "Captain scoring query for a known player. "
            "Expected: supported=True, outcome=ok, intent=captain_score, "
            "review_passed=True, llm_used=False (deterministic mode)."
        ),
        user_message="should I captain Haaland",
        expected_outcome="ok",
        expected_supported=True,
        expected_intent="captain_score",
        expected_review_passed=True,
        expected_llm_used=False,
    ),

    FinalResponseFixture(
        scenario_id="supported_ambiguous",
        description=(
            "Supported intent but ambiguous player name — two players share "
            "the web_name 'Doe' in the ambiguous bootstrap. "
            "FinalResponse correctly surfaces the ambiguous outcome without "
            "picking a player. "
            "Expected: supported=True, outcome=ambiguous, intent=player_resolve, "
            "review_passed=True, llm_used=False."
        ),
        user_message="who is Doe",
        expected_outcome="ambiguous",
        expected_supported=True,
        expected_intent="player_resolve",
        expected_review_passed=True,
        expected_llm_used=False,
        use_ambiguous_bootstrap=True,
    ),

    FinalResponseFixture(
        scenario_id="supported_not_found",
        description=(
            "Supported intent but player not in registry. "
            "Intent is correctly recognised (captain_score) but execution "
            "cannot complete — the player name has no match. "
            "Expected: supported=True, outcome=not_found, intent=captain_score, "
            "review_passed=True, llm_used=False."
        ),
        user_message="should I captain xyznotaplayer999",
        expected_outcome="not_found",
        expected_supported=True,
        expected_intent="captain_score",
        expected_review_passed=True,
        expected_llm_used=False,
    ),

    FinalResponseFixture(
        scenario_id="supported_missing_arguments",
        description=(
            "Supported ranking intent but candidates_list not supplied. "
            "Intent is correctly recognised (rank_candidates) but required "
            "input is absent. "
            "Expected: supported=True, outcome=missing_arguments, "
            "intent=rank_candidates, review_passed=True, llm_used=False. "
            "candidates_list intentionally omitted."
        ),
        user_message="top captains this week",
        expected_outcome="missing_arguments",
        expected_supported=True,
        expected_intent="rank_candidates",
        expected_review_passed=True,
        expected_llm_used=False,
        # candidates_list intentionally omitted — tests the missing-arg path
    ),

    FinalResponseFixture(
        scenario_id="unsupported_intent",
        description=(
            "Question outside the supported scope — cannot be routed by the "
            "deterministic keyword router. "
            "FinalResponse.supported=False signals to callers that this is "
            "outside the system's coverage. "
            "Expected: supported=False, outcome=unsupported_intent, "
            "intent=unsupported, review_passed=True, llm_used=False."
        ),
        user_message="Is Haaland fit to play?",
        expected_outcome="unsupported_intent",
        expected_supported=False,
        expected_intent="unsupported",
        expected_review_passed=True,
        expected_llm_used=False,
    ),

    FinalResponseFixture(
        scenario_id="llm_fallback_to_deterministic",
        description=(
            "Explicit test of the LLM-fallback-to-deterministic invariant. "
            "When no LLM client is available (no ANTHROPIC_API_KEY, no "
            "explicit client), respond() falls back to the deterministic "
            "response_text from the grounded backend. "
            "final_text MUST equal response_text (verifiable via debug bundle). "
            "llm_used=False and review_passed=True by definition of the fallback. "
            "Expected: supported=True, outcome=ok, intent=captain_score, "
            "review_passed=True, llm_used=False."
        ),
        user_message="should I captain Salah",
        expected_outcome="ok",
        expected_supported=True,
        expected_intent="captain_score",
        expected_review_passed=True,
        expected_llm_used=False,
    ),
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(
    standard_bootstrap: dict[str, Any],
    ambiguous_bootstrap: dict[str, Any],
) -> list[tuple[FinalResponseFixture, Any]]:
    """Execute all fixtures and return ``(fixture, FinalResponse)`` pairs.

    Always calls ``respond()`` with ``include_debug=True`` so callers can
    verify the fallback invariant (``final_text == response_text`` when
    ``llm_used=False``) without a separate call.

    Parameters
    ----------
    standard_bootstrap:
        Bootstrap dict used for non-ambiguous scenarios.
    ambiguous_bootstrap:
        Bootstrap dict used for the ``supported_ambiguous`` scenario.

    Returns
    -------
    list[tuple[FinalResponseFixture, FinalResponse]]
        One pair per fixture, in definition order.
    """
    from .final_response import respond

    results: list[tuple[FinalResponseFixture, Any]] = []
    for fixture in FINAL_RESPONSE_FIXTURE_DEFINITIONS:
        bs = ambiguous_bootstrap if fixture.use_ambiguous_bootstrap else standard_bootstrap
        response = respond(
            fixture.user_message,
            bs,
            candidates_list=fixture.candidates_list,
            include_debug=True,  # always include debug for contract verification
        )
        results.append((fixture, response))
    return results