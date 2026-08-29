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
                    tool_output_metric=case.expect["metric"], tool_output_order="desc",
                ))
            elif axis.id == "invented_metric_relay":
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
    """i15's actual failure mode."""
    run = _perfect_run()
    obs = _find(run, "gi-04")           # the deliberate "jornada 3" bait
    obs["tool_sequence"] = ["get_gameweek_context"]
    obs["tool_chosen"] = "get_gameweek_context"

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
