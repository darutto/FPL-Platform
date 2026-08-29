"""i25 — the golden battery must be able to FAIL.

A battery that never fails is not a battery. These tests feed recorded-shape
traces to the assertions and require each mutation to be rejected: the wrong
tool, a missing sort direction, a metric resolved to the wrong field, an
invented metric answered from a gameweek tool, a missing synthesis turn, and —
the one that outranks everything else — a negative control firing.

No credentials and no network: ``golden_axes`` holds no I/O, which is what lets
CI run this while the battery itself stays off CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
_SCRIPTS = _PKG / "scripts"
for _p in (str(_PKG), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import golden_axes as gx  # noqa: E402

TIER = "controls"


def _obs(case, **overrides):
    """An observation in the shape measure_tool_routing.run_one emits."""
    row = {
        "question_id": case.id,
        "question": case.question,
        "family": case.family,
        "acceptable_tools": list(case.acceptable_tools),
        "control": case.control,
        "rep": 0,
        "exception": None,
        "outcome": "ok",
        "tool_chosen": None,
        "tool_sequence": [],
        "tool_call_count": 1,
        "tool_args": {},
        "tool_output_status": "ok",
        "tool_output_code": None,
        "tool_output_metric": None,
        "tool_output_order": None,
        "synthesis_turn": True,
        "cost_usd": 0.0,
    }
    row.update(overrides)
    return row


#: Cases that belong to two axes at once must satisfy BOTH in a clean run.
#: sb-02/sb-13 are routing cases *and* ownership cases: a turn calling only
#: select_players_within_budget passes routing and fails ownership, and one
#: calling only get_my_squad does the reverse. This surfaced a genuine stale
#: label in the corpus (see _ACCEPTABLE_TOOL_PATCHES) rather than a test bug.
_DUAL_AXIS_TOOLS = {qid: [gx.SQUAD_TOOL] for qid in gx.OWNERSHIP_CASE_IDS}

#: gm-04 ("menos goles esperados en contra") is scored by BOTH the metric axis
#: (resolved field) and the direction axis (applied order) off one call. A clean
#: run has to satisfy both at once, exactly as sb-02 does for routing/ownership.
_DUAL_AXIS_ORDER = {c.id: c.expect["order"] for c in gx.ORDER_DIRECTION_CASES}


def _perfect_run():
    """A run where every axis is satisfied. The baseline every mutation breaks."""
    observations = []
    for axis in gx.build_axes(TIER):
        for case in axis.cases:
            if axis.id == "routing":
                tool = case.acceptable_tools[0] if case.acceptable_tools else "get_team_snapshot"
                sequence = [tool] + _DUAL_AXIS_TOOLS.get(case.id, [])
                observations.append(_obs(case, tool_sequence=sequence, tool_chosen=tool))
            elif axis.id == "metric_resolution":
                observations.append(_obs(
                    case, tool_sequence=[gx.RANK_TOOL], tool_chosen=gx.RANK_TOOL,
                    tool_output_metric=case.expect["metric"],
                    tool_output_order=_DUAL_AXIS_ORDER.get(case.id, "desc"),
                ))
            elif axis.id == "invented_metric_relay":
                # A clean relay: the tool ran and told the user the metric is
                # not real. Both halves matter -- see the narrow-gate tests.
                observations.append(_obs(
                    case, tool_sequence=[gx.RANK_TOOL], tool_chosen=gx.RANK_TOOL,
                    tool_output_status="invalid_argument",
                    tool_output_code="unknown_metric",
                ))
            elif axis.id == "order_direction":
                observations.append(_obs(
                    case, tool_sequence=[gx.RANK_TOOL], tool_chosen=gx.RANK_TOOL,
                    tool_output_order=case.expect["order"],
                ))
            elif axis.id == "ownership_no_possessive":
                observations.append(_obs(
                    case, tool_sequence=[gx.SQUAD_TOOL], tool_chosen=gx.SQUAD_TOOL,
                ))
            elif axis.id == "overfire_guards":
                tool = case.acceptable_tools[0] if case.acceptable_tools else "get_team_snapshot"
                observations.append(_obs(case, tool_sequence=[tool], tool_chosen=tool))
    # Deduplicate the way the runner does: one observation per case id.
    seen, deduped = set(), []
    for obs in observations:
        if obs["question_id"] in seen:
            continue
        seen.add(obs["question_id"])
        deduped.append(obs)
    return deduped


def _score(observations):
    return [gx.score_axis(a, observations) for a in gx.build_axes(TIER)]


def _by_id(results):
    return {r.axis_id: r for r in results}


def _find(observations, question_id):
    for obs in observations:
        if obs["question_id"] == question_id:
            return obs
    raise AssertionError(f"no observation for {question_id}")


# ---------------------------------------------------------------------------
# The baseline must pass, or every mutation below proves nothing
# ---------------------------------------------------------------------------

def test_a_clean_run_is_accepted():
    accepted, verdict = gx.overall_verdict(_score(_perfect_run()))

    assert accepted, verdict
    assert verdict.startswith("ACCEPT")


def test_every_axis_scores_a_nonzero_denominator():
    """A silently empty axis would pass by vacuum. Denominator 0 is never a pass."""
    for result in _score(_perfect_run()):
        assert result.denominator > 0, f"{result.axis_id} scored nothing"


# ---------------------------------------------------------------------------
# Mutations — each must be rejected
# ---------------------------------------------------------------------------

def test_wrong_tool_fails_routing():
    run = _perfect_run()
    routing = [a for a in gx.build_axes(TIER) if a.id == "routing"][0]
    # Break a fifth of the routing cases: enough to cross an 80% threshold.
    for case in routing.cases[: max(1, len(routing.cases) // 4)]:
        obs = _find(run, case.id)
        obs["tool_sequence"] = ["web_fetch"]
        obs["tool_chosen"] = "web_fetch"

    results = _by_id(_score(run))

    assert not results["routing"].passed
    assert not gx.overall_verdict(list(results.values()))[0]


def test_no_tool_at_all_fails_routing():
    run = _perfect_run()
    routing = [a for a in gx.build_axes(TIER) if a.id == "routing"][0]
    for case in routing.cases[: max(1, len(routing.cases) // 4)]:
        _find(run, case.id)["tool_sequence"] = []

    assert not _by_id(_score(run))["routing"].passed


def test_missing_order_fails_direction():
    """The i42 defect: the model omits order and the tool defaults to desc, so
    a "más baratos" question silently returns the most expensive."""
    run = _perfect_run()
    _find(run, "gd-01")["tool_output_order"] = "desc"

    results = _by_id(_score(run))

    assert not results["order_direction"].passed
    assert not gx.overall_verdict(list(results.values()))[0]


def test_absent_order_field_fails_direction():
    run = _perfect_run()
    _find(run, "gd-02")["tool_output_order"] = None

    assert not _by_id(_score(run))["order_direction"].passed


def test_metric_resolved_to_the_wrong_field_fails_even_when_status_is_ok():
    """The "goles en contra" defect: status=ok, real numbers, wrong field.
    Asserting only on status would have passed this."""
    run = _perfect_run()
    obs = _find(run, "gm-04")           # expects expected_goals_conceded
    obs["tool_output_status"] = "ok"
    obs["tool_output_metric"] = "goals_scored"

    assert not _by_id(_score(run))["metric_resolution"].passed


def test_unknown_metric_on_a_real_metric_fails_resolution():
    run = _perfect_run()
    obs = _find(run, "gm-01")
    obs["tool_output_status"] = "invalid_argument"
    obs["tool_output_code"] = "unknown_metric"

    assert not _by_id(_score(run))["metric_resolution"].passed


def test_invented_metric_falling_through_to_a_gameweek_tool_fails():
    """i15's actual failure mode and the axis's gate. One is enough: the
    threshold is 100%, which is what i15 measured (0/10 fell through)."""
    run = _perfect_run()
    obs = _find(run, "gi-04")           # the deliberate "jornada 3" bait
    obs["tool_sequence"] = ["get_gameweek_context"]
    obs["tool_chosen"] = "get_gameweek_context"
    obs["tool_output_code"] = None

    case = gx.Case("gi-04", obs["question"], {})
    assert not gx._check_invented_no_gameweek_answer(case, obs)
    assert not _by_id(_score(run))["invented_metric_relay"].passed


def test_invented_metric_answered_by_another_non_gameweek_tool_still_passes():
    """Recorded as defensible when i15 was verified: "mejor vibra" going to
    rank_captain_candidates is a different tool, not the failure mode. The
    assertion must not quietly tighten into "one right tool"."""
    run = _perfect_run()
    obs = _find(run, "gi-03")
    obs["tool_sequence"] = ["rank_captain_candidates"]

    assert _by_id(_score(run))["invented_metric_relay"].passed


def test_missing_synthesis_turn_fails():
    """i46 — the defect found sideways in three of nine calls."""
    run = _perfect_run()
    _find(run, "gm-01")["synthesis_turn"] = False

    assert not _by_id(_score(run))["synthesis_present"].passed


def test_no_tool_turn_is_not_counted_against_synthesis():
    """A turn that called nothing cannot have a synthesis turn; counting it
    would make the axis unreachable rather than informative."""
    run = _perfect_run()
    obs = _find(run, "neg-jornada")
    obs["tool_sequence"] = []
    obs["synthesis_turn"] = False

    assert _by_id(_score(run))["synthesis_present"].passed


def test_ownership_regression_fails():
    run = _perfect_run()
    for qid in gx.OWNERSHIP_CASE_IDS:
        # Back to pre-#186 behaviour: the budget tool runs, the squad is never
        # fetched, so the answer is built without knowing what the user owns.
        _find(run, qid)["tool_sequence"] = ["select_players_within_budget"]

    assert not _by_id(_score(run))["ownership_no_possessive"].passed


# ---------------------------------------------------------------------------
# The guard, and its precedence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("qid", ["neg-defensas", "tf-09", "pv-01"])
def test_a_single_over_fire_breaches_the_guard(qid):
    run = _perfect_run()
    _find(run, qid)["tool_sequence"] = [gx.SQUAD_TOOL]

    assert not _by_id(_score(run))["overfire_guards"].passed


def test_one_over_fire_rejects_the_model_even_with_every_target_passing():
    """The asymmetry, stated as a test: a false fire injects someone's squad
    into a general question. Failing to call is cheaper than calling wrongly."""
    run = _perfect_run()
    _find(run, "neg-comparar")["tool_sequence"] = [gx.SQUAD_TOOL]

    results = _score(run)
    by_id = _by_id(results)
    assert all(r.passed for r in results if r.kind == gx.TARGET)

    accepted, verdict = gx.overall_verdict(results)
    assert not accepted
    assert "guard" in verdict.lower()
    assert "overfire_guards" in verdict
    assert not by_id["overfire_guards"].passed


def test_guard_threshold_is_zero_and_cannot_be_met_by_averaging():
    guard = [a for a in gx.build_axes(TIER) if a.kind == gx.GUARD][0]
    assert guard.threshold == 0.0

    result = gx.AxisResult(
        axis_id=guard.id, kind=gx.GUARD, threshold=guard.threshold,
        numerator=1, denominator=45, reference="",
    )
    assert not result.passed, "1 fire in 45 must not pass a zero ceiling"


# ---------------------------------------------------------------------------
# Run hygiene
# ---------------------------------------------------------------------------

def test_excepted_observations_are_excluded_not_counted_as_passes():
    run = _perfect_run()
    obs = _find(run, "gd-03")
    obs["exception"] = "RuntimeError('boom')"
    obs["tool_sequence"] = []

    before = gx.score_axis(
        [a for a in gx.build_axes(TIER) if a.id == "order_direction"][0], _perfect_run()
    )
    after = _by_id(_score(run))["order_direction"]

    assert after.denominator == before.denominator - 1
    assert after.passed, "excluding is right; counting it as a pass would not be"


def test_thresholds_are_declared_with_a_measured_reference():
    """A threshold with no provenance is a number somebody felt like. Each must
    name the measurement it came from."""
    for axis in gx.build_axes(TIER):
        assert axis.reference.strip(), axis.id
        assert axis.rationale.strip(), axis.id
        assert 0.0 <= axis.threshold <= 1.0, axis.id


def test_controls_tier_is_a_strict_subset_of_full():
    controls = {c.id for a in gx.build_axes("controls") for c in a.cases}
    full = {c.id for a in gx.build_axes("full") for c in a.cases}

    assert controls < full
    assert len(full) > len(controls)


def test_adding_an_axis_needs_no_runner_change():
    """The extension point i32 (language) will use: the runner reads AXES, so a
    new axis is scored by the same code path with no edit to the runner."""
    extra = gx.Axis(
        id="language", kind=gx.TARGET, threshold=1.0, reference="not yet measured",
        rationale="placeholder proving the shape is open for extension",
        cases=(gx.Case("lang-01", "¿Quién marcó más goles?", {}),),
        check=lambda case, obs: bool(obs.get("tool_sequence")),
    )
    observations = [_obs(extra.cases[0], tool_sequence=[gx.RANK_TOOL])]

    result = gx.score_axis(extra, observations)

    assert result.passed and result.denominator == 1


def test_ownership_cases_accept_the_tool_that_actually_serves_them():
    """The routing corpus predates get_my_squad and labels sb-02/sb-13 as
    select_players_within_budget alone. Unpatched, the behaviour i41 shipped and
    measured at 5/5 would score as a routing regression, and the routing and
    ownership axes would contradict each other on the same turn."""
    from tool_routing_corpus import CORPUS

    raw = {q["id"]: q["acceptable_tools"] for q in CORPUS}
    routing = [a for a in gx.build_axes("full") if a.id == "routing"][0]
    by_id = {c.id: c for c in routing.cases}

    for qid in gx.OWNERSHIP_CASE_IDS:
        assert gx.SQUAD_TOOL not in raw[qid], "corpus changed; re-check the patch"
        assert gx.SQUAD_TOOL in by_id[qid].acceptable_tools
        # The original label must survive alongside it, not be replaced.
        assert "select_players_within_budget" in by_id[qid].acceptable_tools


# ---------------------------------------------------------------------------
# i25 round 2 — the narrow relay gate, changed in BOTH directions at once
# ---------------------------------------------------------------------------

def _gi_case(qid="gi-01"):
    return [c for c in gx.INVENTED_METRIC_CASES if c.id == qid][0]


def test_gameweek_context_alongside_the_answering_tool_no_longer_breaches():
    """LOOSENED half. "¿Quién tiene mejor vibra esta fecha?" gathered gameweek
    context and answered from rank_captain_candidates. i15's note of 2026-08-26
    recorded that reading as defensible before this battery existed, which is
    the justification -- not the run it failed."""
    case = _gi_case("gi-03")
    obs = _obs(case, tool_sequence=["get_gameweek_context", "rank_captain_candidates"],
               tool_chosen="get_gameweek_context")

    assert gx._check_invented_no_gameweek_answer(case, obs)
    assert gx._answering_tool(obs) == "rank_captain_candidates"


def test_gameweek_tool_answering_alone_still_breaches():
    case = _gi_case("gi-04")
    obs = _obs(case, tool_sequence=["get_gameweek_context"])

    assert not gx._check_invented_no_gameweek_answer(case, obs)
    assert not gx._check_invented_relay(case, obs)


def test_no_tool_at_all_fails_the_narrow_gate():
    """TIGHTENED half. Answering from memory about a metric that does not exist
    is the worse version of the failure this axis watches: the user is never
    told the metric is not real. gi-02 did this in 1 of 3 reps."""
    case = _gi_case("gi-02")
    obs = _obs(case, tool_sequence=[], tool_call_count=0)

    assert not gx._check_invented_relay(case, obs)
    # The loosened companion cannot see it -- which is why both are reported.
    assert gx._check_invented_no_gameweek_answer(case, obs)


def test_a_rewritten_metric_answered_with_status_ok_fails_the_narrow_gate():
    """The measured case that made this tightening necessary: on "hambre de
    gol" the model emitted metric='goles esta temporada', which resolves to
    goals_scored, so the tool returned ok and the user got a top-scorers list
    without ever learning the metric was not real."""
    case = _gi_case("gi-02")
    obs = _obs(case, tool_sequence=[gx.RANK_TOOL], tool_chosen=gx.RANK_TOOL,
               tool_args={"metric": "goles esta temporada"},
               tool_output_status="ok", tool_output_metric="goals_scored",
               tool_output_code=None)

    assert not gx._check_invented_relay(case, obs)
    assert gx._check_invented_no_gameweek_answer(case, obs)


def test_both_relay_figures_are_always_reported():
    """The criterion cannot be moved quietly between the two numbers."""
    axis = [a for a in gx.build_axes(TIER) if a.id == "invented_metric_relay"][0]
    assert axis.companion is not None
    assert axis.companion_label and axis.companion_reference

    result = gx.score_axis(axis, _perfect_run())
    assert result.companion_numerator is not None
    assert result.companion_rate is not None


def test_the_narrow_gate_is_stricter_than_the_companion():
    """Net effect of changing both directions at once: strictly fewer traces
    pass the gate than pass the companion."""
    case = _gi_case("gi-02")
    traces = [
        _obs(case, tool_sequence=[]),                                    # memory
        _obs(case, tool_sequence=[gx.RANK_TOOL], tool_output_code=None),  # rewritten
        _obs(case, tool_sequence=[gx.RANK_TOOL], tool_output_code="unknown_metric"),
    ]
    gate = [gx._check_invented_relay(case, o) for o in traces]
    companion = [gx._check_invented_no_gameweek_answer(case, o) for o in traces]

    assert gate == [False, False, True]
    assert companion == [True, True, True]
    assert sum(gate) < sum(companion)


# ---------------------------------------------------------------------------
# Stale cases are excluded, never counted
# ---------------------------------------------------------------------------

def test_stale_cases_leave_the_denominator_and_are_reported():
    run = _perfect_run()
    _find(run, "gm-01")["tool_output_metric"] = "goals_scored"   # would FAIL

    scored = gx.score_axis(
        [a for a in gx.build_axes(TIER) if a.id == "metric_resolution"][0],
        run, stale_case_ids={"gm-01"},
    )

    assert scored.excluded == 1
    assert scored.excluded_ids == ("gm-01",)
    assert scored.denominator == len(gx.METRIC_RESOLUTION_CASES) - 1
    assert scored.passed, "a stale case must not be counted as a failure either"


def test_a_stale_case_is_not_counted_as_a_pass_either():
    """The i46 lesson: pv-11 failed 3/3 for want of a player, and the first run
    read that as a reproduction. Excluding must move the denominator, not the
    numerator."""
    axis = [a for a in gx.build_axes(TIER) if a.id == "synthesis_present"][0]
    run = _perfect_run()
    target = _find(run, "gm-01")
    target["synthesis_turn"] = False

    full = gx.score_axis(axis, run)
    excluded = gx.score_axis(axis, run, stale_case_ids={"gm-01"})

    assert full.denominator == excluded.denominator + 1
    assert full.numerator == excluded.numerator      # the failure left, not a pass
    assert not full.passed and excluded.passed


# ---------------------------------------------------------------------------
# Our defect vs the model's
# ---------------------------------------------------------------------------

def test_synthesis_axis_is_marked_blocked_by_i46():
    axis = [a for a in gx.build_axes(TIER) if a.id == "synthesis_present"][0]
    assert axis.blocked_by == "i46"


def test_verdict_separates_a_blocked_axis_from_a_model_failure():
    """A gate that rejects every candidate stops discriminating. The verdict
    must say which failure belongs to the model and which is ours."""
    run = _perfect_run()
    _find(run, "gm-01")["synthesis_turn"] = False      # blocked axis (i46)
    for qid in ("gd-01", "gd-02"):
        _find(run, qid)["tool_output_order"] = "desc"  # model axis

    results = _score(run)
    accepted, verdict = gx.overall_verdict(results)

    assert not accepted
    assert "1 model axis (order_direction)" in verdict
    assert "1 blocked (synthesis_present blocked by i46)" in verdict


def test_a_blocked_axis_alone_still_rejects_but_names_itself():
    run = _perfect_run()
    _find(run, "gm-01")["synthesis_turn"] = False

    accepted, verdict = gx.overall_verdict(_score(run))

    assert not accepted
    assert "blocked by i46" in verdict
    assert "model axis" not in verdict


def test_a_breached_guard_still_outranks_everything_including_blocked():
    run = _perfect_run()
    _find(run, "gm-01")["synthesis_turn"] = False
    _find(run, "neg-defensas")["tool_sequence"] = [gx.SQUAD_TOOL]

    accepted, verdict = gx.overall_verdict(_score(run))

    assert not accepted
    assert verdict.startswith("REJECT — guard breached")


# ---------------------------------------------------------------------------
# The direction axis gained a fourth case (brief correction)
# ---------------------------------------------------------------------------

def test_direction_axis_has_four_cases_and_shares_one_with_the_metric_axis():
    axes = {a.id: a for a in gx.build_axes(TIER)}
    direction_ids = [c.id for c in axes["order_direction"].cases]
    metric_ids = [c.id for c in axes["metric_resolution"].cases]

    assert len(direction_ids) == 4
    assert "gm-04" in direction_ids and "gm-04" in metric_ids


def test_the_shared_case_is_called_once_and_scored_twice():
    """Same question text under the same id, so the runner dedupes it."""
    direction = [c for c in gx.ORDER_DIRECTION_CASES if c.id == "gm-04"][0]
    metric = [c for c in gx.METRIC_RESOLUTION_CASES if c.id == "gm-04"][0]

    assert direction.question == metric.question
    assert direction.expect == {"order": "asc"}
    assert metric.expect == {"metric": "expected_goals_conceded"}


def test_the_over_fire_guard_is_not_shrunk_by_stale_cases():
    """neg-comparar names Salah, who has left. It no longer measures "a
    comparison between two current players" — but it is still a question that
    must not pull the user's squad, so it still counts as a guard. Excluding it
    would shrink the very record being protected (i41: 0 fires in 45)."""
    axis = [a for a in gx.build_axes(TIER) if a.kind == gx.GUARD][0]
    run = _perfect_run()

    scored = gx.score_axis(axis, run, stale_case_ids={"neg-comparar", "pv-10"})
    unscored = gx.score_axis(axis, run)

    assert axis.stale_sensitive is False
    assert scored.denominator == unscored.denominator
    assert scored.excluded == 0


def test_a_stale_case_still_breaches_the_guard_if_it_fires():
    axis = [a for a in gx.build_axes(TIER) if a.kind == gx.GUARD][0]
    run = _perfect_run()
    _find(run, "neg-comparar")["tool_sequence"] = [gx.SQUAD_TOOL]

    result = gx.score_axis(axis, run, stale_case_ids={"neg-comparar"})

    assert not result.passed, "a stale question that over-fires is still an over-fire"


def test_target_axes_remain_stale_sensitive():
    for axis in gx.build_axes(TIER):
        if axis.kind == gx.TARGET:
            assert axis.stale_sensitive, axis.id


# ---------------------------------------------------------------------------
# The gate is i15's decided criterion; the strict figure is reported beside it
# ---------------------------------------------------------------------------

def test_the_gate_is_the_decided_criterion_not_the_stricter_one():
    """A briefly-held gate required the relay to have HAPPENED. It was reverted:
    "refuse rather than reinterpret" is a product policy nobody had decided, and
    a gate encodes decided policy rather than inventing it. The strict figure is
    kept as the companion, not discarded."""
    axis = [a for a in gx.build_axes(TIER) if a.id == "invented_metric_relay"][0]

    assert axis.check is gx._check_invented_no_gameweek_answer
    assert axis.companion is gx._check_invented_relay
    assert axis.threshold == 1.00
    assert "0/10" in axis.reference
    assert "NOT gated" in axis.companion_reference


def test_a_declared_reinterpretation_passes_the_gate_and_fails_the_companion():
    """The behaviour that made the stricter gate wrong: the model names the
    substitution in the user's language and grounds it. Gate passes; the strict
    figure still records it, so nothing is lost."""
    case = _gi_case("gi-02")
    obs = _obs(case, tool_sequence=[gx.RANK_TOOL], tool_chosen=gx.RANK_TOOL,
               tool_args={"metric": "goles esta temporada"},
               tool_output_status="ok", tool_output_metric="goals_scored",
               tool_output_code=None,
               answer_text="Si por «hambre de gol» entendemos el xG acumulado, "
                           "el líder es Haaland: 25,5 xG.")

    assert gx._check_invented_no_gameweek_answer(case, obs)   # gate
    assert not gx._check_invented_relay(case, obs)            # companion
    assert gx.classify_invented_behaviour(case, obs) == gx.DECLARED


def test_a_clarification_request_passes_the_gate():
    case = _gi_case("gi-03")
    obs = _obs(case, tool_sequence=[],
               answer_text="¿Te refieres a quién es el mejor capitán esta "
                           "jornada? Dime 2-5 jugadores y los comparo.")

    assert gx._check_invented_no_gameweek_answer(case, obs)
    assert gx.classify_invented_behaviour(case, obs) == gx.CLARIFIED


def test_silent_adoption_is_named_even_though_it_passes_the_gate():
    """The one behaviour of the three that IS the fluent-lie class. It passes
    the gate today because the product decision is open (i48) — but it is
    counted every run so the decision is made on a series, not an impression."""
    case = _gi_case("gi-03")
    obs = _obs(case, tool_sequence=["rank_captain_candidates"],
               tool_chosen="rank_captain_candidates",
               answer_text="La mejor vibra esta fecha: Haaland. Ranking: "
                           "1. Haaland 36,59  2. Saka 33,98")

    assert gx._check_invented_no_gameweek_answer(case, obs)
    assert gx.classify_invented_behaviour(case, obs) == gx.ADOPTED


def test_a_raw_dump_is_not_blamed_on_the_model():
    """A turn with no synthesis has no model behaviour to classify; counting it
    as silent adoption would attribute i46 to the model."""
    case = _gi_case("gi-03")
    obs = _obs(case, tool_sequence=["rank_captain_candidates"],
               synthesis_turn=False,
               answer_text="1. Haaland (MCI) 36.59 · pateador de penales")

    assert gx.classify_invented_behaviour(case, obs) == gx.NO_SYNTH


def test_a_clean_relay_is_classified_before_any_prose_is_read():
    """The one classification that never depends on the answer text."""
    case = _gi_case("gi-01")
    obs = _obs(case, tool_sequence=[gx.RANK_TOOL],
               tool_output_status="invalid_argument",
               tool_output_code="unknown_metric", answer_text="")

    assert gx.classify_invented_behaviour(case, obs) == gx.RELAYED


def test_the_breakdown_is_reported_and_never_gates():
    axis = [a for a in gx.build_axes(TIER) if a.id == "invented_metric_relay"][0]
    result = gx.score_axis(axis, _perfect_run())

    assert axis.breakdown is not None and axis.breakdown_note
    assert result.breakdown == {gx.RELAYED: len(gx.INVENTED_METRIC_CASES)}
    # The verdict is unaffected by how the breakdown splits.
    assert result.passed


def test_every_behaviour_label_is_reachable():
    """A bucket nothing can land in is a bucket that hides a behaviour."""
    case = _gi_case("gi-02")
    traces = {
        gx.GAMEWEEK:  _obs(case, tool_sequence=["get_gameweek_context"]),
        gx.RELAYED:   _obs(case, tool_sequence=[gx.RANK_TOOL],
                           tool_output_code="unknown_metric"),
        gx.NO_SYNTH:  _obs(case, tool_sequence=[gx.RANK_TOOL], synthesis_turn=False),
        gx.CLARIFIED: _obs(case, tool_sequence=[], answer_text="¿Te refieres a goles?"),
        gx.DECLARED:  _obs(case, tool_sequence=[gx.RANK_TOOL],
                           answer_text="Si por hambre de gol entendemos xG..."),
        gx.ADOPTED:   _obs(case, tool_sequence=[gx.RANK_TOOL],
                           answer_text="Haaland lidera con 27 goles."),
    }
    for expected, obs in traces.items():
        assert gx.classify_invented_behaviour(case, obs) == expected, expected


def test_luna_passes_the_reverted_gate_on_the_recorded_traces():
    """The reference row this revert produces: the measured behaviour that made
    the stricter gate fail now passes, and the strict count is still visible."""
    case = _gi_case("gi-02")
    recorded = [
        _obs(case, tool_sequence=[gx.RANK_TOOL], tool_output_code="unknown_metric"),
        _obs(case, tool_sequence=[gx.RANK_TOOL], tool_output_code=None,
             answer_text="Si por hambre de gol entendemos el xG acumulado..."),
        _obs(case, tool_sequence=["rank_captain_candidates"],
             answer_text="La mejor vibra: Haaland"),
    ]
    axis = [a for a in gx.build_axes(TIER) if a.id == "invented_metric_relay"][0]

    assert all(axis.check(case, o) for o in recorded)
    assert sum(axis.companion(case, o) for o in recorded) == 1
