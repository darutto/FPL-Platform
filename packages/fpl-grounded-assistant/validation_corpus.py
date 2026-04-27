"""
validation_corpus.py
====================
Phase V1 / V2: Validation Corpus.

A human-readable, deterministic set of golden scenarios that cover the
current supported and bounded unsupported intent matrix.

V2 additions (Phase 7j):
- Structured transfer metadata assertions (expect_transfer)
- Structured chip advice metadata assertions (expect_chip)
- Structured fixture run metadata assertions (expect_fixture_run)
- Structured differential picks metadata assertions (expect_differential)
- Transfer follow-up resolution scenario (Phase 7f)
- Differential picks ok-path scenario (Phase 7g, using DIFFERENTIAL_BOOTSTRAP)

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
transfer          -- direct transfer advice + structured metadata (Phase 6a/7a)
chip              -- chip advice + structured metadata (Phase 6b/7b)
chip_advice       -- chip advice with structured ChipAdviceMeta (Phase 7b)
multi_intent      -- multi-intent detection and sub-response composition
player_fixture_run -- player fixture run + structured metadata (Phase 7h)
differential_picks -- differential picks + structured metadata (Phase 7g)
transfer_followup -- deterministic transfer follow-up (Phase 7f)

Surface vocabulary
------------------
cli           -- fpl_cli.run()            (single stateless turn)
http          -- POST /ask                (single stateless turn, TestClient)
session_cli   -- fpl_cli.run_session()    (multi-turn, supports resolver stub)
session_http  -- POST /session/{id}/ask  (multi-turn, deterministic only)

Cross-surface parity scope
--------------------------
For cli/http scenarios: intent, outcome, supported, and key structured
field presence (captain, comparison, captain_ranking, transfer, chip,
fixture_run, differential) must agree across both surfaces.

For session_cli/session_http scenarios: intent, outcome, and supported
for the final turn must agree.  Resolver_source is verified on session_cli
only (HTTP session uses deterministic fallback without an LLM client).

For LLM stub scenarios (comparison_followup_llm, pronoun_llm): tested on
session_cli only.  HTTP session always uses deterministic fallback because
the HTTP endpoint does not accept an external resolver_client.  This is
explicitly intended, not a gap.

Bootstrap names
---------------
"standard"           -- STANDARD_BOOTSTRAP (GW28, 4 players, no available low-ownership)
"ambiguous"          -- AMBIGUOUS_BOOTSTRAP (extends standard with two Doe players)
"differential"       -- DIFFERENTIAL_BOOTSTRAP (extends standard with Palmer 3.5%,
                        Mbeumo 8.2% — both available and under the 15% threshold)
"dgw"                -- DGW_BOOTSTRAP (GW28, 6 teams each with 2 GW28 fixtures,
                        Phase 8c: triggers free_hit conditions_favorable)
"bgw"                -- BGW_BOOTSTRAP (GW28, 2 teams blanked — no GW28 fixture,
                        Phase 8c: triggers free_hit conditions_marginal)
"marginal_transfer"  -- MARGINAL_TRANSFER_BOOTSTRAP (deepcopy of standard with Haaland
                        form raised to 9.1, giving delta ~1.33 → marginal_transfer_in;
                        Phase 8e2: triggers hit_warning when free_transfers==1)
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
    expect_transfer:
        Whether ``FinalResponse.transfer`` should be non-None (Phase 7j).
    expect_chip:
        Whether ``FinalResponse.chip`` should be non-None (Phase 7j).
    expect_fixture_run:
        Whether ``FinalResponse.fixture_run`` should be non-None (Phase 7j).
    expect_differential:
        Whether ``FinalResponse.differential`` should be non-None (Phase 7j).
    expected_resolver_source:
        Expected ``ResolverDebug.resolver_source`` for session_cli paths.
        ``None`` when resolver source is not asserted.
    classifier_stub_json:
        JSON string the ``_StubAnthropicClient`` returns for Phase 4k
        classifier scenarios (``requires_stub == "classifier"``).
        ``None`` for all non-classifier scenarios.
    notes:
        Human-readable notes about expected values, e.g. player tier or
        set-piece role.  Present in the generated Markdown report.
    expect_budget_constraint:
        When non-None, asserts that ``transfer.budget_constraint`` equals
        this value (Phase 8f1 — explicit squad_context outcome validation).
    expect_hit_warning:
        When non-None, asserts that ``transfer.hit_warning`` equals this
        value (Phase 8f1 — explicit squad_context outcome validation).
    expect_chip_unavailable:
        When non-None, asserts that ``chip.chip_unavailable`` equals this
        value (Phase 8f1 — explicit squad_context outcome validation).
    expect_chip_signal_label:
        When non-None, asserts that ``chip.signal_label`` exactly matches
        this string (Phase 8f1 — validates 8c DGW/BGW/normal detection).
    squad_context_prior_turns:
        When non-None, this squad_context is sent on all prior session turns
        while ``squad_context`` (which may be None) is sent on the final turn.
        Only meaningful for session surfaces.  Enables statelessness checks:
        a constraint fires on turn 1 but does not persist to turn 2.
        On ``session_cli`` the prior-turns context is ignored (single context
        per session); use ``session_http`` for statelessness scenarios.
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
    expect_transfer:          bool                         = field(default=False)   # Phase 7j
    expect_chip:              bool                         = field(default=False)   # Phase 7j
    expect_fixture_run:       bool                         = field(default=False)   # Phase 7j
    expect_differential:      bool                         = field(default=False)   # Phase 7j
    expected_resolver_source: str | None                   = field(default=None)
    classifier_stub_json:     str | None                   = field(default=None)
    notes:                    str                          = field(default="")
    squad_context:            "dict | None"                = field(default=None)  # Phase 8e1
    # Phase 8f1: explicit structured-outcome expectations
    expect_budget_constraint: "bool | None"                = field(default=None)  # assert transfer.budget_constraint
    expect_hit_warning:       "bool | None"                = field(default=None)  # assert transfer.hit_warning
    expect_chip_unavailable:  "bool | None"                = field(default=None)  # assert chip.chip_unavailable
    expect_chip_signal_label: "str | None"                 = field(default=None)  # assert chip.signal_label exact match
    # Phase 8f2: per-turn squad_context for session statelessness scenarios
    squad_context_prior_turns: "dict | None"               = field(default=None)  # applied to prior turns; final turn uses squad_context


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

    # ------------------------------------------------------------------
    # 14 — Phase 4k: natural captain phrasing (LLM classifier stub)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="natural_captain_phrasing",
        family="llm_classify",
        description=(
            "Natural captain question that deterministic route() cannot handle. "
            "LLM classifier rewrites to canonical form; route() then routes it."
        ),
        question="is Saka worth captaining?",
        bootstrap="standard",
        surfaces=("cli", "http", "session_cli", "session_http"),
        expected_intent="captain_score",
        expected_outcome="ok",
        expected_supported=True,
        requires_stub="classifier",
        classifier_stub_json=(
            '{"intent": "captain_score", '
            '"canonical_question": "should I captain Saka", '
            '"confidence": 0.92, "language": "en"}'
        ),
        expect_captain=True,
        notes=(
            "Phase 4l: all 4 surfaces. "
            "Stub returns canonical 'should I captain Saka'; route() extracts Saka. "
            "classification_source == 'llm_classifier' in debug bundle on all surfaces."
        ),
    ),

    # ------------------------------------------------------------------
    # 15 — Phase 4k: natural comparison phrasing (LLM classifier stub)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="natural_comparison_phrasing",
        family="llm_classify",
        description=(
            "Natural comparison question that deterministic route() cannot handle. "
            "LLM classifier rewrites to canonical form; route() extracts both players."
        ),
        question="what's the score differential between Salah and Haaland?",
        bootstrap="standard",
        surfaces=("cli", "http", "session_cli", "session_http"),
        expected_intent="compare_players",
        expected_outcome="ok",
        expected_supported=True,
        requires_stub="classifier",
        classifier_stub_json=(
            '{"intent": "compare_players", '
            '"canonical_question": "compare Salah and Haaland", '
            '"confidence": 0.88, "language": "en"}'
        ),
        expect_comparison=True,
        notes=(
            "Phase 4l: all 4 surfaces. "
            "Stub returns canonical 'compare Salah and Haaland'; route() extracts both. "
            "classification_source == 'llm_classifier'. comparison metadata present."
        ),
    ),

    # ------------------------------------------------------------------
    # 16 — Phase 4k: natural ranking phrasing (LLM classifier stub)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="natural_ranking_phrasing",
        family="llm_classify",
        description=(
            "Natural ranking question that deterministic route() cannot handle. "
            "LLM classifier rewrites to canonical form; candidates_list supplied."
        ),
        question="who looks best for captain this week?",
        bootstrap="standard",
        surfaces=("cli", "http", "session_cli", "session_http"),
        expected_intent="rank_candidates",
        expected_outcome="ok",
        expected_supported=True,
        candidates_list=(
            {"query": "Salah"},
            {"query": "Haaland"},
            {"query": "Saka"},
        ),
        requires_stub="classifier",
        classifier_stub_json=(
            '{"intent": "rank_candidates", '
            '"canonical_question": "top captains this week", '
            '"confidence": 0.90, "language": "en"}'
        ),
        expect_captain_ranking=True,
        notes=(
            "Phase 4l: all 4 surfaces. "
            "Stub returns canonical 'top captains this week'; candidates_list supplied. "
            "classification_source == 'llm_classifier'. captain_ranking present."
        ),
    ),

    # ------------------------------------------------------------------
    # 17 — Phase 6a: direct transfer advice (known players)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_advice_direct",
        family="transfer",
        description=(
            "Direct transfer advice: sell Saka for Salah. "
            "Both players known in STANDARD_BOOTSTRAP. "
            "Deterministic recommendation with structured TransferMeta."
        ),
        question="should I sell Saka for Salah",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_transfer=True,
        notes=(
            "Phase 6a/7a: deterministic transfer advice with structured metadata. "
            "Salah (higher captain_score) vs Saka -- recommendation should be "
            "'transfer_in'. FinalResponse.transfer non-null: "
            "player_out='Saka', player_in='Salah', recommendation='transfer_in', "
            "score_delta (float > 0), price_delta (int), reasons (non-empty list). "
            "captain, comparison, captain_ranking all absent."
        ),
    ),

    # ------------------------------------------------------------------
    # 18 — Phase 6a: transfer advice not found
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_advice_not_found",
        family="transfer",
        description=(
            "Transfer advice where the target player cannot be found. "
            "Outcome should be not_found, supported=True."
        ),
        question="should I sell Saka for UnknownPlayerXYZ",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="transfer_advice",
        expected_outcome="not_found",
        expected_supported=True,
        notes=(
            "Phase 6a: transfer advice not_found path. "
            "UnknownPlayerXYZ is not in STANDARD_BOOTSTRAP. "
            "supported=True (intent was recognised), outcome=not_found."
        ),
    ),

    # ------------------------------------------------------------------
    # 19 — Phase 6b: chip advice -- triple captain
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_tc",
        family="chip",
        description=(
            "Chip advice for triple captain. "
            "Routing detects 'triple captain' + advisory phrase. "
            "Returns conditions_marginal for STANDARD_BOOTSTRAP (GW28, top score ~60)."
        ),
        question="should I use triple captain this week",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "Phase 6b: chip advice capability. "
            "STANDARD_BOOTSTRAP GW28, top MID/FWD captain score ~60 "
            "(between _TC_MARGINAL_THRESHOLD=55 and _TC_FAVORABLE_THRESHOLD=75). "
            "Recommendation: conditions_marginal. "
            "final_text contains 'Triple captain conditions: marginal'."
        ),
    ),

    # ------------------------------------------------------------------
    # 20 — Phase 6b: chip advice -- wildcard
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_wc",
        family="chip",
        description=(
            "Chip advice for wildcard. "
            "Routing detects 'wildcard' + 'this week'. "
            "GW28 is in the viable window (7 <= 28 < 29) -> conditions_marginal."
        ),
        question="should I wildcard this week",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "Phase 6b: wildcard chip advice. "
            "STANDARD_BOOTSTRAP GW28 falls in viable window "
            "(_WC_EARLY_CUTOFF=6 < 28 < _WC_LATE_CUTOFF=29). "
            "Recommendation: conditions_marginal. "
            "final_text contains 'Wildcard conditions: marginal'."
        ),
    ),

    # ------------------------------------------------------------------
    # 21 — Phase 6b/8c: chip advice -- free hit (normal GW)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_fh",
        family="chip",
        description=(
            "Chip advice for free hit in a normal gameweek. "
            "Phase 8c: STANDARD_BOOTSTRAP has no DGW/BGW teams "
            "-> recommendation=conditions_unfavorable."
        ),
        question="should I free hit this week",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "Phase 8c: free hit chip advice with DGW/BGW detection. "
            "STANDARD_BOOTSTRAP GW28: all 5 teams have exactly 1 GW28 fixture "
            "-> gameweek_type='normal' -> recommendation=conditions_unfavorable. "
            "outcome=ok (intent recognised, chip processed). "
            "final_text contains 'Free hit conditions: unfavorable'."
        ),
    ),

    # ------------------------------------------------------------------
    # 22 — Phase 6c: multi-intent (gameweek + player summary)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="multi_intent_gw_and_summary",
        family="multi_intent",
        description=(
            "Multi-intent question combining current-gameweek and player-summary. "
            "Both halves independently route; respond() returns intent=multi_intent."
        ),
        question="tell me about Salah and what gameweek is it",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="multi_intent",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "Phase 6c: first multi-intent slice. "
            "Part 1: 'tell me about Salah' -> player_summary OK. "
            "Part 2: 'what gameweek is it' -> current_gameweek OK. "
            "combined outcome=ok; sub_responses has 2 entries. "
            "final_text concatenates both sub-responses separated by blank line."
        ),
    ),

    # ------------------------------------------------------------------
    # 23 — Phase 6c: multi-intent (captain score + player resolve)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="multi_intent_captain_and_resolve",
        family="multi_intent",
        description=(
            "Multi-intent question combining captain-score and player-resolve. "
            "Both halves independently route; respond() returns intent=multi_intent."
        ),
        question="should I captain Haaland and who is Saka",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="multi_intent",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "Phase 6c: multi-intent combining captain_score and player_resolve. "
            "Part 1: 'should I captain Haaland' -> captain_score OK. "
            "Part 2: 'who is Saka' -> player_resolve OK. "
            "sub_responses[0].intent=captain_score, sub_responses[1].intent=player_resolve. "
            "single-intent turns: sub_responses absent."
        ),
    ),

    # ------------------------------------------------------------------
    # 24 — Phase 6d: multi-intent with structured sub-response metadata
    # ------------------------------------------------------------------
    ValidationScenario(
        id="multi_intent_captain_and_comparison",
        family="multi_intent",
        description=(
            "Multi-intent combining captain-score and comparison. "
            "Both sub-responses expose bounded structured metadata: "
            "captain on the captain sub-intent, comparison on the compare sub-intent."
        ),
        question="should I captain Haaland and compare Salah and Haaland",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="multi_intent",
        expected_outcome="ok",
        expected_supported=True,
        notes=(
            "Phase 6d: structured sub-response metadata. "
            "Part 1: 'should I captain Haaland' -> captain_score OK; sub_responses[0].captain non-null. "
            "Part 2: 'compare Salah and Haaland' -> compare_players OK; sub_responses[1].comparison non-null. "
            "Splits on first ' and '; part_b contains its own ' and ' (two-player connector). "
            "Top-level response: intent=multi_intent, sub_responses has 2 entries. "
            "CLI debug + HTTP body expose captain/comparison per sub-response."
        ),
    ),

    # ------------------------------------------------------------------
    # 25 — Phase 7b: chip advice with structured ChipAdviceMeta
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_triple_captain_structured",
        family="chip_advice",
        description=(
            "Triple captain chip advice returns structured ChipAdviceMeta "
            "with chip, recommendation, gw, signal_value, and signal_label."
        ),
        question="should I use triple captain this week",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_chip=True,
        notes=(
            "Phase 7b: structured chip metadata. "
            "FinalResponse.chip non-null; chip=='triple_captain'. "
            "recommendation in {conditions_favorable, conditions_marginal, conditions_unfavorable}. "
            "signal_value is top MID/FWD captain score (float); signal_label=='top captain score'. "
            "gw is current gameweek (int). "
            "CLI debug and HTTP /ask body both expose 'chip' dict. "
            "Non-debug CLI output is final_text only (unchanged)."
        ),
    ),

    # ------------------------------------------------------------------
    # 26 — Phase 7h: player fixture run — direct suffix form
    # ------------------------------------------------------------------
    ValidationScenario(
        id="fixture_run_direct",
        family="player_fixture_run",
        description=(
            "Player fixture run via suffix form ('Salah fixtures') returns "
            "structured FixtureRunMeta with web_name, team_short, position, "
            "horizon, current_gameweek, and a list of upcoming fixture entries."
        ),
        question="Salah fixtures",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="player_fixture_run",
        expected_outcome="ok",
        expected_supported=True,
        expect_fixture_run=True,
        notes=(
            "Phase 7h: player fixture run with structured metadata. "
            "FinalResponse.fixture_run non-null; web_name=='Salah', team_short=='LIV', position=='MID'. "
            "horizon==5; len(fixtures)==5; each fixture has gameweek, opponent_short, is_home, difficulty. "
            "CLI debug and HTTP /ask body both expose 'fixture_run' dict. "
            "Non-debug CLI output is plain text only (unchanged)."
        ),
    ),

    # ------------------------------------------------------------------
    # 27 — Phase 7h: player fixture run — player not found
    # ------------------------------------------------------------------
    ValidationScenario(
        id="fixture_run_not_found",
        family="player_fixture_run",
        description=(
            "Player fixture run for an unknown player returns not_found outcome "
            "with supported=True and fixture_run=None."
        ),
        question="NonExistentXYZ fixtures",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="player_fixture_run",
        expected_outcome="not_found",
        expected_supported=True,
        notes=(
            "Phase 7h: fixture run not-found path. "
            "Player 'NonExistentXYZ' does not exist in the registry. "
            "FinalResponse.fixture_run is None; outcome='not_found'; supported=True. "
            "final_text is a graceful 'not found' message."
        ),
    ),

    # ------------------------------------------------------------------
    # 28 — Phase 7g: differential picks — direct keyword form
    # ------------------------------------------------------------------
    ValidationScenario(
        id="differential_picks_direct",
        family="differential_picks",
        description=(
            "Differential picks query returns ok outcome with DifferentialPicksMeta "
            "when the bootstrap contains available players with ownership < 15%."
        ),
        question="good differentials",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="differential_picks",
        expected_outcome="error",   # standard bootstrap has no qualifying players → "empty" → error
        expected_supported=True,
        notes=(
            "Phase 7g: differential picks intent routing. "
            "STANDARD_BOOTSTRAP has no available players with ownership < 15% "
            "(De Bruyne is 14.2% but injured), so the tool returns status='empty' "
            "which maps to outcome='error' (not 'ok'). "
            "Intent routing is correct (differential_picks). "
            "FinalResponse.differential is None since outcome != ok. "
            "See run_phase7g_tests.py for full ok-path coverage using DIFFERENTIAL_BOOTSTRAP."
        ),
    ),

    # ------------------------------------------------------------------
    # 29 — Phase 7g: differential picks — low ownership keyword form
    # ------------------------------------------------------------------
    ValidationScenario(
        id="differential_picks_low_ownership",
        family="differential_picks",
        description=(
            "Low ownership keyword form routes to differential_picks intent."
        ),
        question="low ownership picks",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="differential_picks",
        expected_outcome="error",   # same bootstrap caveat as above
        expected_supported=True,
        notes=(
            "Phase 7g: low-ownership keyword routing. "
            "'low ownership picks' routes to differential_picks intent. "
            "Same bootstrap caveat as differential_picks_direct."
        ),
    ),

    # ------------------------------------------------------------------
    # 30 — Phase 7f: deterministic transfer follow-up
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_followup_det",
        family="transfer_followup",
        description=(
            "Session transfer follow-up resolved deterministically. "
            "Prior turn establishes sell Saka for Salah; follow-up "
            "'what about Haaland instead' is rewritten to "
            "'sell Saka for Haaland'."
        ),
        question="what about Haaland instead",
        bootstrap="standard",
        surfaces=("session_cli", "session_http"),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        session_prior_turns=("should I sell Saka for Salah",),
        expect_transfer=True,
        expected_resolver_source="transfer_followup",
        notes=(
            "Phase 7f: deterministic transfer follow-up rewrite. "
            "Prior turn: sell Saka for Salah (sets last_transfer=('Saka','Salah')). "
            "Follow-up: 'what about Haaland instead' -> 'sell Saka for Haaland'. "
            "resolver_source == 'transfer_followup' on session_cli. "
            "FinalResponse.transfer non-null on both surfaces: "
            "player_out='Saka', player_in='Haaland'. "
            "Haaland (FWD, high form) vs Saka (doubtful, lower minutes). "
            "recommendation is likely 'transfer_in' or 'marginal_transfer_in'."
        ),
    ),

    # ------------------------------------------------------------------
    # 31 — Phase 8b: venue-aware comparison — structured ok-path
    # ------------------------------------------------------------------
    ValidationScenario(
        id="venue_aware_comparison",
        family="comparison",
        description=(
            "Phase 8b: comparison with STANDARD_BOOTSTRAP (has team_fixtures) "
            "returns ComparisonMeta with is_home and effective_fdr per player. "
            "Salah (LIV home GW28, efdr=3.5) vs Saka (ARS home GW28, efdr=4.5); "
            "Salah wins; FDR reason includes venue tag."
        ),
        question="compare Salah and Saka",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="compare_players",
        expected_outcome="ok",
        expected_supported=True,
        expect_comparison=True,
        notes=(
            "Phase 8b: venue-aware comparison cross-surface parity. "
            "Both players are home in GW28 per STANDARD_BOOTSTRAP team_fixtures. "
            "Salah (LIV, raw FDR=4, efdr=3.5) wins over Saka (ARS, raw FDR=5, efdr=4.5). "
            "comparison.player_a and player_b each expose is_home=True and effective_fdr. "
            "comparison_reasons includes 'easier fixture (FDR 4H vs 5H)' because "
            "efdr diff = 1.0 >= threshold and both players are tagged home. "
            "Layer 1 captain_score still uses raw int FDR (no venue adjustment). "
            "CLI debug and HTTP /ask body both expose the comparison dict."
        ),
    ),

    # ------------------------------------------------------------------
    # 32 — Phase 7g: differential picks — structured ok-path
    # ------------------------------------------------------------------
    ValidationScenario(
        id="differential_picks_structured",
        family="differential_picks",
        description=(
            "Differential picks with DIFFERENTIAL_BOOTSTRAP returns "
            "DifferentialPicksMeta with at least one qualifying pick."
        ),
        question="good differentials",
        bootstrap="differential",
        surfaces=("cli", "http"),
        expected_intent="differential_picks",
        expected_outcome="ok",
        expected_supported=True,
        expect_differential=True,
        notes=(
            "Phase 7g: differential picks structured ok-path (V2 corpus). "
            "DIFFERENTIAL_BOOTSTRAP adds Palmer (CHE, 3.5% owned, status='a') "
            "and Mbeumo (MUN, 8.2% owned, status='a'). Both qualify (< 15%). "
            "FinalResponse.differential non-null: "
            "ownership_threshold==15.0, top_n==5, len(picks) >= 1. "
            "picks[0].rank==1; each pick has web_name, team_short, position, "
            "captain_score, ownership, now_cost. "
            "CLI debug and HTTP /ask body both expose 'differential' dict."
        ),
    ),

    # ------------------------------------------------------------------
    # 33 — Phase 8c: free hit in a double gameweek (favorable)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_fh_dgw",
        family="chip_advice",
        description=(
            "Free hit chip advice with DGW_BOOTSTRAP: 6 teams each play twice "
            "in GW28 -> recommendation=conditions_favorable."
        ),
        question="should I free hit this week",
        bootstrap="dgw",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_chip=True,
        expect_chip_signal_label="double gameweek teams",  # Phase 8f1: explicit 8c signal validation
        notes=(
            "Phase 8c: free hit in large double gameweek. "
            "DGW_BOOTSTRAP: ARS, MCI, LIV, CHE, MUN, TOT each have 2 GW28 fixtures "
            "-> _classify_gameweek_type returns ('double', [...], 6). "
            "affected_count (6) >= _FH_DGW_FAVORABLE_TEAMS (6) "
            "-> recommendation=conditions_favorable. "
            "FinalResponse.chip non-null: chip='free_hit', "
            "signal_value=6.0, signal_label='double gameweek teams'. "
            "final_text contains 'Free hit conditions: favorable'."
        ),
    ),

    # ------------------------------------------------------------------
    # 34 — Phase 8c: free hit in a blank gameweek (marginal)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_fh_bgw",
        family="chip_advice",
        description=(
            "Free hit chip advice with BGW_BOOTSTRAP: 2 teams (ARS, MCI) have "
            "no GW28 fixture -> recommendation=conditions_marginal."
        ),
        question="should I free hit this week",
        bootstrap="bgw",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_chip=True,
        expect_chip_signal_label="blank gameweek teams",   # Phase 8f1: explicit 8c signal validation
        notes=(
            "Phase 8c: free hit in blank gameweek. "
            "BGW_BOOTSTRAP: ARS and MCI have no GW28 entries "
            "-> _classify_gameweek_type returns ('blank', ['ARS', 'MCI'], 2). "
            "recommendation=conditions_marginal (save for next DGW). "
            "FinalResponse.chip non-null: chip='free_hit', "
            "signal_value=2.0, signal_label='blank gameweek teams'. "
            "final_text contains 'Free hit conditions: marginal'."
        ),
    ),

    # ------------------------------------------------------------------
    # 35 — Phase 8c: free hit in a normal gameweek (unfavorable)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_advice_fh_normal",
        family="chip_advice",
        description=(
            "Free hit chip advice with STANDARD_BOOTSTRAP: all 5 teams have "
            "exactly 1 GW28 fixture -> recommendation=conditions_unfavorable."
        ),
        question="should I free hit this week",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_chip=True,
        expect_chip_signal_label="normal gameweek",        # Phase 8f1: explicit 8c signal validation
        notes=(
            "Phase 8c: free hit in normal gameweek. "
            "STANDARD_BOOTSTRAP: all 5 teams have 1 GW28 fixture each "
            "-> _classify_gameweek_type returns ('normal', [], 0). "
            "recommendation=conditions_unfavorable. "
            "FinalResponse.chip non-null: chip='free_hit', "
            "signal_value=0.0, signal_label='normal gameweek'. "
            "final_text contains 'Free hit conditions: unfavorable'."
        ),
    ),

    # ------------------------------------------------------------------
    # 36 — Phase 8d-i: fixture run follow-up (session surfaces)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="fixture_run_followup",
        family="fixture_run",
        description=(
            "Deterministic fixture run follow-up: after 'Haaland fixtures', "
            "'what about Salah?' rewrites to 'Salah fixtures' without LLM."
        ),
        question="what about Salah?",
        bootstrap="standard",
        surfaces=("session_cli", "session_http"),
        session_prior_turns=("Haaland fixtures",),
        expected_intent="player_fixture_run",
        expected_outcome="ok",
        expected_supported=True,
        expect_fixture_run=True,
        expected_resolver_source="fixture_run_followup",
        notes=(
            "Phase 8d-i: deterministic fixture run follow-up rewrite. "
            "Prior turn: 'Haaland fixtures' (sets last_fixture_run_player='Haaland'). "
            "Follow-up: 'what about Salah?' → deterministic rewrite to 'Salah fixtures'. "
            "resolver_source='fixture_run_followup'. "
            "fixture_run.web_name should be 'Salah' (resolved from STANDARD_BOOTSTRAP). "
            "No LLM call required for the rewrite."
        ),
    ),

    # ------------------------------------------------------------------
    # 37 — Phase 8d-ii: differential picks follow-up (session surfaces)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="differential_followup",
        family="captain",
        description=(
            "Deterministic differential follow-up: after 'good differentials', "
            "'what about Mbeumo?' rewrites to 'should I captain Mbeumo?' "
            "without LLM."
        ),
        question="what about Mbeumo?",
        bootstrap="differential",
        surfaces=("session_cli", "session_http"),
        session_prior_turns=("good differentials",),
        expected_intent="captain_score",
        expected_outcome="ok",
        expected_supported=True,
        expect_captain=True,
        expected_resolver_source="differential_followup",
        notes=(
            "Phase 8d-ii: deterministic differential follow-up rewrite. "
            "Prior turn: 'good differentials' (sets last_differential=True). "
            "Follow-up: 'what about Mbeumo?' -> deterministic rewrite to "
            "'should I captain Mbeumo?'. "
            "resolver_source='differential_followup'. "
            "Resolves via captain score path (INTENT_CAPTAIN_SCORE). "
            "No LLM call required for the rewrite."
        ),
    ),

    # ------------------------------------------------------------------
    # 38 — Phase 8e1: transfer budget constraint override (scenarios 38–40 are squad_context)
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_budget_constraint",
        family="transfer",
        description=(
            "Transfer advice with squad_context itb below price_delta: "
            "'sell Saka buy Salah' with itb=20 (£2.0m), price_delta=35 (£3.5m) "
            "-> budget_constraint=True in TransferMeta."
        ),
        question="should I sell Saka for Salah",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_transfer=True,
        squad_context={"itb": 20},  # £2.0m; price_delta=35 (£3.5m) -> constrained
        expect_budget_constraint=True,   # Phase 8f1: explicit flag validation
        notes=(
            "Phase 8e1: budget_constraint override. "
            "Saka now_cost=100, Salah now_cost=135, price_delta=35 (£3.5m). "
            "itb=20 (£2.0m) < 35 -> budget_constraint=True in TransferMeta. "
            "final_text becomes budget constraint message. "
            "transfer metadata is still populated (intent=ok)."
        ),
    ),

    # ------------------------------------------------------------------
    # 39 — Phase 8e2: transfer hit warning
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_hit_warning",
        family="transfer",
        description=(
            "Transfer advice with squad_context free_transfers==1 and a marginal "
            "recommendation -> hit_warning=True in TransferMeta."
        ),
        question="should I sell Haaland for Salah",
        bootstrap="marginal_transfer",
        surfaces=("cli", "http"),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_transfer=True,
        squad_context={"free_transfers": 1},
        expect_hit_warning=True,         # Phase 8f1: explicit flag validation
        notes=(
            "Phase 8e2: hit_warning flag. "
            "MARGINAL_TRANSFER_BOOTSTRAP has Haaland form=9.1 (score ~59.25) "
            "vs Salah form=9.5 (score ~60.58), delta ~1.33 -> marginal_transfer_in. "
            "free_transfers==1 + marginal_transfer_in -> hit_warning=True. "
            "final_text is NOT overridden (advisory flag only, not a hard block). "
            "recommendation stays marginal_transfer_in."
        ),
    ),

    # ------------------------------------------------------------------
    # 40 — Phase 8e1: chip unavailable override
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_unavailable_tc",
        family="chip",
        description=(
            "Chip advice with squad_context chips_remaining that excludes "
            "triple_captain -> chip_unavailable=True in ChipAdviceMeta."
        ),
        question="should I use my triple captain",
        bootstrap="standard",
        surfaces=("cli", "http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_chip=True,
        squad_context={"chips_remaining": ["wildcard", "bench_boost", "free_hit"]},
        expect_chip_unavailable=True,    # Phase 8f1: explicit flag validation
        notes=(
            "Phase 8e1: chip_unavailable override. "
            "Requested chip: triple_captain. "
            "chips_remaining excludes triple_captain -> chip_unavailable=True. "
            "final_text becomes chip unavailable message. "
            "chip metadata is still populated (intent=ok)."
        ),
    ),

    # ------------------------------------------------------------------
    # 41 — Phase 8f2: transfer budget constraint on session surfaces
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_budget_constraint_session",
        family="transfer",
        description=(
            "Transfer budget constraint applied via squad_context on a session turn. "
            "Validates that session surfaces enforce the constraint identically to "
            "the stateless cli/http surfaces."
        ),
        question="should I sell Saka for Salah",
        bootstrap="standard",
        surfaces=("session_cli", "session_http"),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_transfer=True,
        expect_budget_constraint=True,
        squad_context={"itb": 20},
        notes=(
            "Phase 8f2: budget_constraint on session surfaces. "
            "Mirrors scenario 38 on session_cli and session_http. "
            "itb=20 (£2.0m) < price_delta=35 (£3.5m) -> budget_constraint=True. "
            "squad_context is per-turn; session state is not modified."
        ),
    ),

    # ------------------------------------------------------------------
    # 42 — Phase 8f2: chip unavailable on session surfaces
    # ------------------------------------------------------------------
    ValidationScenario(
        id="chip_unavailable_session",
        family="chip",
        description=(
            "Chip unavailable override applied via squad_context on a session turn. "
            "Validates that session surfaces enforce the constraint identically to "
            "the stateless cli/http surfaces."
        ),
        question="should I use my triple captain",
        bootstrap="standard",
        surfaces=("session_cli", "session_http"),
        expected_intent="chip_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_chip=True,
        expect_chip_unavailable=True,
        squad_context={"chips_remaining": ["wildcard", "bench_boost", "free_hit"]},
        notes=(
            "Phase 8f2: chip_unavailable on session surfaces. "
            "Mirrors scenario 40 on session_cli and session_http. "
            "chips_remaining excludes triple_captain -> chip_unavailable=True. "
            "squad_context is per-turn; session state is not modified."
        ),
    ),

    # ------------------------------------------------------------------
    # 43 — Phase 8f2: hit warning on session surfaces
    # ------------------------------------------------------------------
    ValidationScenario(
        id="transfer_hit_warning_session",
        family="transfer",
        description=(
            "Transfer hit warning applied via squad_context on a session turn. "
            "Validates that session surfaces enforce the advisory flag identically "
            "to the stateless cli/http surfaces."
        ),
        question="should I sell Haaland for Salah",
        bootstrap="marginal_transfer",
        surfaces=("session_cli", "session_http"),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_transfer=True,
        expect_hit_warning=True,
        squad_context={"free_transfers": 1},
        notes=(
            "Phase 8f2: hit_warning on session surfaces. "
            "Mirrors scenario 39 on session_cli and session_http. "
            "MARGINAL_TRANSFER_BOOTSTRAP: Haaland form=9.1, delta ~1.33 -> marginal_transfer_in. "
            "free_transfers==1 + marginal_transfer_in -> hit_warning=True. "
            "final_text is NOT overridden (advisory flag only)."
        ),
    ),

    # ------------------------------------------------------------------
    # 44 — Phase 8f2: squad_context statelessness across session turns
    # ------------------------------------------------------------------
    ValidationScenario(
        id="squad_context_stateless",
        family="transfer",
        description=(
            "squad_context applied on turn 1 does not persist to turn 2. "
            "Prior turn: 'sell Saka for Salah' WITH itb=20 -> budget_constraint=True. "
            "Final turn: same question WITHOUT squad_context -> budget_constraint=False."
        ),
        question="should I sell Saka for Salah",
        bootstrap="standard",
        surfaces=("session_http",),
        expected_intent="transfer_advice",
        expected_outcome="ok",
        expected_supported=True,
        expect_transfer=True,
        expect_budget_constraint=False,
        session_prior_turns=("should I sell Saka for Salah",),
        squad_context=None,                         # final turn: no constraint
        squad_context_prior_turns={"itb": 20},      # prior turn: constraint fires
        notes=(
            "Phase 8f2: squad_context statelessness. "
            "Turn 1: budget_constraint fires (itb=20 < price_delta=35). "
            "Turn 2 (asserted): same question, no squad_context -> budget_constraint=False. "
            "Confirms squad_context is NOT persisted to ConversationState between turns. "
            "session_http only: prior-turn squad_context is injected per-payload. "
            "session_cli excluded — cli_run_session takes a single context for all turns."
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
