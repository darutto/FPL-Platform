"""
validation_corpus.py
====================
Phase V1: Frozen Validation Corpus.

A human-readable, deterministic set of golden scenarios that cover the
current supported and bounded unsupported intent matrix.

This file is intentionally import-free from fpl_grounded_assistant so it
can be read as plain documentation.  The smoke runner (run_validation.py)
resolves bootstrap names, candidates lists, and stub clients at runtime.

Scenario families
-----------------
captain           -- direct single-player captaincy score query
ranking           -- ranked captain candidates with supplied list
summary           -- player summary / stats lookup
resolve           -- player identity lookup
comparison        -- two-player comparison
comparison_followup_det   -- deterministic comparison follow-up (Phase 5c)
comparison_followup_llm   -- LLM-assisted comparison follow-up (Phase 5f, stubbed)
pronoun_det       -- deterministic pronoun substitution (Phase 4e)
pronoun_llm       -- LLM-assisted reference resolution (Phase 4f, stubbed)
failure_modes     -- unsupported, ambiguous, not_found, no_session_follow_up

Surface vocabulary
------------------
cli           -- fpl_cli.run()            (single stateless turn)
http          -- POST /ask                (single stateless turn, TestClient)
session_cli   -- fpl_cli.run_session()    (multi-turn, supports resolver stub)
session_http  -- POST /session/{id}/ask  (multi-turn, deterministic only)

Cross-surface parity scope
--------------------------
For cli/http scenarios: intent, outcome, supported, and key structured
field presence must agree across both surfaces.

For session_cli/session_http scenarios: intent, outcome, and supported
for the final turn must agree.  Resolver_source is verified on session_cli
only (HTTP session uses deterministic fallback without an LLM client).

For LLM stub scenarios (comparison_followup_llm, pronoun_llm): tested on
session_cli only.  HTTP session always uses deterministic fallback because
the HTTP endpoint does not accept an external resolver_client.  This is
explicitly intended, not a gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Scenario dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationScenario:
    """A single golden validation scenario.

    Attributes
    ----------
    id:
        Unique kebab-case identifier.  Used as the key in result artifacts.
    family:
        Scenario category for grouping in reports.
    description:
        One-sentence human-readable explanation of what is being tested.
    question:
        The canonical question used as the test input.
    bootstrap:
        Which bootstrap to use: ``"standard"`` or ``"ambiguous"``.
    surfaces:
        Which execution surfaces to exercise.  Subset of
        ``("cli", "http", "session_cli", "session_http")``.
    expected_intent:
        Expected ``FinalResponse.intent`` value.
    expected_outcome:
        Expected ``FinalResponse.outcome`` value.
    expected_supported:
        Expected ``FinalResponse.supported`` value.
    candidates_list:
        Optional ranked candidates.  Forwarded to ``run()`` /
        ``run_session()`` / ``candidates_list`` HTTP field.
    session_prior_turns:
        Questions to send as setup turns before the target question.
        Only meaningful for ``session_*`` surfaces.
    requires_stub:
        Which LLM stub the session_cli surface needs:
        ``"comp_llm"`` for Phase 5f comparison resolver,
        ``"ref_llm"`` for Phase 4f reference resolver,
        or ``None`` for no stub.
    expect_captain:
        Whether ``FinalResponse.captain`` should be non-None.
    expect_comparison:
        Whether ``FinalResponse.comparison`` should be non-None.
    expect_captain_ranking:
        Whether ``FinalResponse.captain_ranking`` should be non-None and
        non-empty.
    expected_resolver_source:
        Expected ``ResolverDebug.resolver_source`` for session_cli paths.
        ``None`` when resolver source is not asserted.
    notes:
        Human-readable notes about expected values, e.g. player tier or
        set-piece role.  Present in the generated Markdown report.
    """
    id:                       str
    family:                   str
    description:              str
    question:                 str
    bootstrap:                str
    surfaces:                 tuple[str, ...]
    expected_intent:          str
    expected_outcome:         str
    expected_supported:       bool
    candidates_list:          tuple[dict, ...] | None      = field(default=None)
    session_prior_turns:      tuple[str, ...]              = field(default=())
    requires_stub:            str | None                   = field(default=None)
    expect_captain:           bool                         = field(default=False)
    expect_comparison:        bool                         = field(default=False)
    expect_captain_ranking:   bool                         = field(default=False)
    expected_resolver_source: str | None                   = field(default=None)
    notes:                    str                          = field(default="")


# ---------------------------------------------------------------------------
# Frozen scenario corpus
# ---------------------------------------------------------------------------

VALIDATION_SCENARIOS: tuple[ValidationScenario, ...] = (

    # ------------------------------------------------------------------
    # 1 — Direct captain score
    # ------------------------------------------------------------------
    ValidationScenario(
        id="direct_captain_score",
        family="captain",
        description="Realistic direct captaincy question for a known player.",
        question="should I captain Salah",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="captain_score",
        expected_outcome="ok",
        expected_supported=True,
        expect_captain=True,
        notes=(
            "Salah: tier='safe', role_bonus=5.0 (penalty taker). "
            "captain metadata present; comparison and captain_ranking absent."
        ),
    ),

    # ------------------------------------------------------------------
    # 2 — Ranked captain candidates
    # ------------------------------------------------------------------
    ValidationScenario(
        id="ranked_captain_candidates",
        family="ranking",
        description="Ranked captain query with three explicitly supplied candidates.",
        question="top captains this week",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="rank_candidates",
        expected_outcome="ok",
        expected_supported=True,
        candidates_list=(
            {"query": "Salah"},
            {"query": "Haaland"},
            {"query": "Saka"},
        ),
        expect_captain_ranking=True,
        notes=(
            "Three candidates; Salah ranks #1 (safe), Haaland #2 (upside), "
            "Saka #3 (differential). captain and comparison absent."
        ),
    ),

    # ------------------------------------------------------------------
    # 3 — Player summary
    # ------------------------------------------------------------------
    ValidationScenario(
        id="player_summary",
        family="summary",
        description="Player stats/summary lookup for a known player.",
        question="tell me about Haaland",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="player_summary",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "No structured metadata expected (player_summary has no "
            "captain/comparison/captain_ranking fields)."
        ),
    ),

    # ------------------------------------------------------------------
    # 4 — Player resolve / identity
    # ------------------------------------------------------------------
    ValidationScenario(
        id="player_resolve",
        family="resolve",
        description="Player identity lookup for a known player.",
        question="who is Salah",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="player_resolve",
        expected_outcome="ok",
        expected_supported=True,
        notes="No structured metadata expected.",
    ),

    # ------------------------------------------------------------------
    # 5 — Direct comparison
    # ------------------------------------------------------------------
    ValidationScenario(
        id="direct_comparison",
        family="comparison",
        description="Direct two-player comparison between two known players.",
        question="Haaland vs Salah",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="compare_players",
        expected_outcome="ok",
        expected_supported=True,
        expect_comparison=True,
        notes=(
            "comparison metadata present: winner, margin, label, reasons, "
            "player_a (Haaland/FWD), player_b (Salah/MID). "
            "captain and captain_ranking absent."
        ),
    ),

    # ------------------------------------------------------------------
    # 6 — Unsupported intent
    # ------------------------------------------------------------------
    ValidationScenario(
        id="unsupported_prompt",
        family="failure_modes",
        description="Question outside the supported intent set.",
        question="Is Haaland fit to play?",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="unsupported",
        expected_outcome="unsupported_intent",
        expected_supported=False,
        notes=(
            "supported=False; all three structured metadata fields absent. "
            "final_text still contains a user-facing message."
        ),
    ),

    # ------------------------------------------------------------------
    # 7 — Ambiguous player
    # ------------------------------------------------------------------
    ValidationScenario(
        id="ambiguous_player",
        family="failure_modes",
        description="Player name matches multiple entries in the registry.",
        question="who is Doe",
        bootstrap="ambiguous",
        surfaces=("cli", "http"),
        expected_intent="player_resolve",
        expected_outcome="ambiguous",
        expected_supported=True,
        notes=(
            "Uses AMBIGUOUS_BOOTSTRAP with two players sharing web_name 'Doe'. "
            "supported=True; outcome=ambiguous; no structured metadata."
        ),
    ),

    # ------------------------------------------------------------------
    # 8 — Player not found
    # ------------------------------------------------------------------
    ValidationScenario(
        id="not_found_player",
        family="failure_modes",
        description="Supported intent but player not in registry.",
        question="should I captain xyznotaplayer999",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="captain_score",
        expected_outcome="not_found",
        expected_supported=True,
        notes=(
            "supported=True (intent recognised); outcome=not_found "
            "(registry lookup fails). captain absent."
        ),
    ),

    # ------------------------------------------------------------------
    # 9 — No-session follow-up edge case (stateless pronoun)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="no_session_follow_up",
        family="failure_modes",
        description=(
            "Pronoun follow-up issued without any session context. "
            "The system treats 'him' as a literal player query and returns "
            "not_found rather than crashing."
        ),
        question="should I captain him",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="captain_score",
        expected_outcome="not_found",
        expected_supported=True,
        notes=(
            "No ConversationSession — 'him' is passed as-is to the player "
            "registry and not found. Validates graceful failure, not resolution."
        ),
    ),

    # ------------------------------------------------------------------
    # 10 — Deterministic comparison follow-up (Phase 5c)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="comparison_followup_det",
        family="comparison_followup_det",
        description=(
            "Session comparison follow-up resolved deterministically. "
            "Prior turn establishes Haaland vs Salah; follow-up 'And Saka?' "
            "is rewritten to 'compare Haaland and Saka'."
        ),
        question="And Saka?",
        bootstrap="standard",
        surfaces=("session_cli", "session_http"),
        expected_intent="compare_players",
        expected_outcome="ok",
        expected_supported=True,
        session_prior_turns=("compare Haaland and Salah",),
        expect_comparison=True,
        expected_resolver_source="comparison_followup",
        notes=(
            "Prior turn: compare Haaland and Salah. "
            "Follow-up: 'And Saka?' → deterministic rewrite to compare Haaland and Saka. "
            "resolver_source == 'comparison_followup' on session_cli. "
            "comparison metadata present on both surfaces."
        ),
    ),

    # ------------------------------------------------------------------
    # 11 — LLM-assisted comparison follow-up (Phase 5f, stubbed)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="comparison_followup_llm",
        family="comparison_followup_llm",
        description=(
            "Session comparison follow-up resolved by the LLM resolver stub. "
            "Prior turn establishes Haaland vs Salah; Spanish '¿Y Saka?' "
            "is rewritten to 'compare Haaland and Saka' via the Phase 5f stub."
        ),
        question="¿Y Saka?",
        bootstrap="standard",
        surfaces=("session_cli",),
        expected_intent="compare_players",
        expected_outcome="ok",
        expected_supported=True,
        session_prior_turns=("compare Haaland and Salah",),
        requires_stub="comp_llm",
        expect_comparison=True,
        expected_resolver_source="comparison_followup_llm",
        notes=(
            "Surfaces: session_cli only — HTTP session uses deterministic "
            "fallback (no resolver_client). This is intentional. "
            "Stub returns {is_comparison_followup:true, new_player:'Saka', confidence:0.95}. "
            "resolver_source == 'comparison_followup_llm' confirms Phase 5f path."
        ),
    ),

    # ------------------------------------------------------------------
    # 12 — Deterministic pronoun substitution (Phase 4e)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="pronoun_det",
        family="pronoun_det",
        description=(
            "Session pronoun follow-up resolved by Phase 4e deterministic substitution. "
            "Prior turn sets last_player=Salah; 'should I captain him' rewrites to "
            "'should I captain Salah'."
        ),
        question="should I captain him",
        bootstrap="standard",
        surfaces=("session_cli", "session_http"),
        expected_intent="captain_score",
        expected_outcome="ok",
        expected_supported=True,
        session_prior_turns=("should I captain Salah",),
        expect_captain=True,
        expected_resolver_source="fallback_regex",
        notes=(
            "resolver_source == 'fallback_regex' (Phase 4e deterministic path). "
            "captain metadata present; Salah as the resolved player. "
            "session_http also resolves correctly via deterministic fallback."
        ),
    ),

    # ------------------------------------------------------------------
    # 13 — LLM-assisted reference resolution (Phase 4f, stubbed)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="pronoun_llm",
        family="pronoun_llm",
        description=(
            "Session follow-up resolved by the Phase 4f LLM reference resolver stub. "
            "Prior turn sets last_player=Salah; Spanish '¿Y él?' is rewritten to "
            "'should I captain Salah' via the Phase 4f stub."
        ),
        question="¿Y él?",
        bootstrap="standard",
        surfaces=("session_cli",),
        expected_intent="captain_score",
        expected_outcome="ok",
        expected_supported=True,
        session_prior_turns=("should I captain Salah",),
        requires_stub="ref_llm",
        expect_captain=True,
        expected_resolver_source="llm",
        notes=(
            "Surfaces: session_cli only — HTTP session uses deterministic "
            "fallback. This is intentional. "
            "Stub returns {resolved_query:'Salah', intent_guess:'captain_score', "
            "confidence:0.9, language:'es'}. "
            "resolver_source == 'llm' confirms Phase 4f path."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Helpers for consumers
# ---------------------------------------------------------------------------

SCENARIO_IDS: tuple[str, ...] = tuple(s.id for s in VALIDATION_SCENARIOS)

SCENARIO_BY_ID: dict[str, ValidationScenario] = {
    s.id: s for s in VALIDATION_SCENARIOS
}
