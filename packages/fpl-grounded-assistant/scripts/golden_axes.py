"""i25 golden battery — axes, cases, assertions and PRE-REGISTERED thresholds.

This module answers exactly one question: **can this model be the production
model?** It holds no I/O and makes no calls, so every assertion in it can be
exercised against recorded traces by the test suite without credentials — which
is what lets the battery itself be tested (see tests/test_golden_battery.py).

Why a fixed battery at all
--------------------------
The apparatus was rebuilt four times in one week and **three times the
instrument was the bug**: a ``.get(...) or ''`` that manufactured empty turns
that never happened, a hash script that compared two tracebacks and reported
"IDENTICAL", and a probe that read ``minutes`` instead of
``minutes_played_season`` and reported every row as zero. An improvised
instrument has that failure rate; a fixed one whose cases were reviewed once
does not.

The sharper argument came out of i41: the empty-synthesis defect (i46) was
found **sideways**, in three of nine calls of a measurement aimed at something
else. Without a standing battery, the chance of finding a defect depends on
somebody happening to measure something adjacent, and that does not scale with
the number of tools.

Design rules, all deliberate
----------------------------
*   **Deterministic assertions on the trace, never on the prose.** Tool in the
    acceptable set; argument values where they matter (``metric``, ``order``);
    ``status``; ``synthesis_turn``. **No LLM judge in v1** — that is what stops
    batteries like this from ever being finished.
*   **Acceptable SETS, not single answers.** Inherited from the routing corpus
    and kept on purpose: a one-tool key manufactures failures that are really
    labelling errors.
*   **Guards outrank targets.** One over-fire on a negative control fails the
    model even if every target passes. Deliberately asymmetric, as in i41.
*   **Thresholds live in this file**, written before the first run against a
    new model, so they cannot be adjusted after seeing results. Each carries
    the measured ``gpt-5.6-luna`` reference it was set from.

Adding an axis (e.g. i32, language) must not require touching the runner: append
an ``Axis`` to ``AXES`` and the runner picks up its cases, dedupes them against
the others, and scores it.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

TARGET = "target"
GUARD = "guard"

SQUAD_TOOL = "get_my_squad"
RANK_TOOL = "rank_players_by_metric"


# ---------------------------------------------------------------------------
# Case / Axis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Case:
    """One question plus what the trace must show. ``expect`` is axis-specific."""
    id: str
    question: str
    expect: dict[str, Any] = field(default_factory=dict)
    #: Corpus questions carry these; ad-hoc cases default sensibly.
    family: str = "golden"
    acceptable_tools: tuple[str, ...] = ()
    control: bool = False

    def as_question(self) -> dict[str, Any]:
        """The shape ``measure_tool_routing.run_one`` expects."""
        return {
            "id": self.id,
            "family": self.family,
            "acceptable_tools": list(self.acceptable_tools),
            "control": self.control,
            "question": self.question,
        }


@dataclass(frozen=True)
class Axis:
    id: str
    kind: str                      # TARGET | GUARD
    threshold: float               # target: min pass rate. guard: max fire rate.
    reference: str                 # the measured gpt-5.6-luna figure it was set from
    rationale: str
    cases: tuple[Case, ...]
    check: Callable[[Case, dict[str, Any]], bool]
    #: A second figure always reported next to the gated one, so the criterion
    #: cannot be moved quietly between them.
    companion: "Callable[[Case, dict[str, Any]], bool] | None" = None
    companion_label: str = ""
    companion_reference: str = ""
    #: False when a stale entity does not invalidate the assertion. A GUARD
    #: asserts a tool must NOT fire: whether Salah is still in the league
    #: changes what "Compara Haaland y Salah" measures, but not whether the
    #: user's own squad is relevant to it -- it is not. Excluding it would
    #: silently shrink the very guard whose zero-fire record is the asset being
    #: protected (i41: 0 in 45 negative calls).
    stale_sensitive: bool = True
    #: Set when the axis measures a defect of OURS rather than of the model. A
    #: blocked axis still fails the run, but is reported on its own line: while
    #: i46 is open every candidate fails this identically, and a gate that
    #: rejects everyone stops discriminating -- the first thing that happens
    #: when Sonnet fails it the same way in i22 is that people start ignoring
    #: the verdict.
    blocked_by: "str | None" = None

    def passed(self, rate: float) -> bool:
        if self.kind == GUARD:
            return rate <= self.threshold
        return rate >= self.threshold


# ---------------------------------------------------------------------------
# Shared predicates
# ---------------------------------------------------------------------------

def _tools(obs: dict[str, Any]) -> list[str]:
    return list(obs.get("tool_sequence") or [])


def _is_valid(obs: dict[str, Any]) -> bool:
    """An excepted observation is not evidence either way; the runner refuses
    to score a run containing any, rather than silently averaging over them."""
    return obs.get("exception") is None


# --- axis: routing ---------------------------------------------------------

def _check_routing(case: Case, obs: dict[str, Any]) -> bool:
    """Some tool from the acceptable set was called. An empty set means the
    corpus does not pin this question, and any tool call counts."""
    called = _tools(obs)
    if not called:
        return False
    acceptable = set(case.acceptable_tools)
    return bool(acceptable & set(called)) if acceptable else True


# --- axis: metric resolution ----------------------------------------------

def _check_metric_resolution(case: Case, obs: dict[str, Any]) -> bool:
    """The ranking tool ran AND resolved the metric to the expected field.

    Asserting the resolved field, not merely absence of an error, is the point:
    "goles en contra" once returned ``status: ok`` while ranking top scorers.
    """
    if RANK_TOOL not in _tools(obs):
        return False
    if obs.get("tool_output_status") != "ok":
        return False
    return obs.get("tool_output_metric") == case.expect["metric"]


# --- axis: invented metric is relayed -------------------------------------

_GAMEWEEK_TOOLS = frozenset({"get_current_gameweek", "get_gameweek_context"})


def _answering_tool(obs: dict[str, Any]) -> "str | None":
    """The tool whose output the answer is built from — the last one called.

    Not ``tool_chosen``, which is the PRIMARY: on the one measured turn where a
    gameweek tool appeared next to the answering tool, ``tool_chosen`` was
    ``get_gameweek_context`` while ``rank_captain_candidates`` actually answered.
    """
    called = _tools(obs)
    return called[-1] if called else None


def _check_invented_no_gameweek_answer(case: Case, obs: dict[str, Any]) -> bool:
    """LOOSENED, reported not gated: no gameweek tool ANSWERED the question.

    Was "no gameweek tool anywhere in the sequence". Loosened because i15's
    failure mode is a gameweek tool *answering* a question about a metric that
    does not exist, and because a question that literally says "esta fecha" can
    reasonably gather gameweek context alongside the tool that answers.

    The justification is i15's own note of 2026-08-26, which recorded that
    reading before this battery existed — NOT the run that failed on it. Changed
    in the same commit as the tightening below, so this is not a loosening taken
    alone after seeing what made it fail.
    """
    return _answering_tool(obs) not in _GAMEWEEK_TOOLS


def _check_invented_relay(case: Case, obs: dict[str, Any]) -> bool:
    """NARROW, the gate: the relay must actually have happened.

    Two ways to fail beyond the gameweek fallback, both measured:

    *   **No tool at all.** Answering from memory about a metric that does not
        exist is the worse version of what this axis watches: the user is never
        told the metric is not real.
    *   **A confident answer to a rewritten question.** On "hambre de gol" the
        model emitted ``metric='goles esta temporada'``, which resolves to
        ``goals_scored``, so the tool returned ``status=ok`` and the user got a
        top-scorers list without ever learning that "hambre de gol" is not a
        metric. Requiring ``unknown_metric`` in the trace is what catches it.

    This mirrors i15's own second figure ("relayed unknown_metric: 8/10"), which
    is the reference the threshold is set from.
    """
    if not _check_invented_no_gameweek_answer(case, obs):
        return False
    if not _tools(obs):
        return False
    return obs.get("tool_output_code") == "unknown_metric"


# --- axis: order direction -------------------------------------------------

def _check_order_direction(case: Case, obs: dict[str, Any]) -> bool:
    """A "menos / más barato / menor" question must actually rank ascending.

    Asserts the order the tool APPLIED, not the argument the model passed: a
    model that omits ``order`` and a tool that defaults to ``desc`` produced a
    fluent answer naming the most expensive defender as the cheapest.
    """
    if RANK_TOOL not in _tools(obs):
        return False
    return obs.get("tool_output_order") == case.expect["order"]


# --- axis: ownership without a possessive ---------------------------------

def _check_ownership(case: Case, obs: dict[str, Any]) -> bool:
    return SQUAD_TOOL in _tools(obs)


# --- axis: over-fire guards ------------------------------------------------

def _check_overfire(case: Case, obs: dict[str, Any]) -> bool:
    """GUARD semantics: True means the bad thing HAPPENED (the rate is a fire
    rate, and the threshold is a ceiling of 0)."""
    return SQUAD_TOOL in _tools(obs)


# --- axis: synthesis present ----------------------------------------------

def _check_synthesis(case: Case, obs: dict[str, Any]) -> bool:
    """Every turn that called a tool must also produce a synthesis turn.

    ``synthesis_turn=False`` renders the raw tool output to the user; that is
    i46, found sideways in three of nine calls of a measurement about something
    else. Turns that called no tool cannot have a synthesis turn and are not
    counted against this axis.
    """
    if not _tools(obs):
        return True
    return bool(obs.get("synthesis_turn"))


# ---------------------------------------------------------------------------
# Cases — every one already measured. No new questions (out of scope by brief).
# ---------------------------------------------------------------------------

def _routing_cases(tier: str) -> tuple[Case, ...]:
    """The 90-case labelled routing corpus, reused verbatim.

    ``tier='controls'`` keeps only the 47 control cases (single-element
    acceptable set) for a fast check; ``full`` is the decision run.
    """
    from tool_routing_corpus import CORPUS

    return tuple(
        Case(
            id=q["id"],
            question=q["question"],
            family=q["family"],
            acceptable_tools=_patched_tools(q),
            control=bool(q["control"]),
        )
        for q in CORPUS
        if tier == "full" or q["control"]
    )


#: i18/i19 live probe, 2026-08-27. Reference: unknown_metric 1/26 calls after
#: PR #181. Verbatim from probe_i18_i19_r1/r2.json.
METRIC_RESOLUTION_CASES: tuple[Case, ...] = (
    Case("gm-01", "¿Quién tiene más transferencias de entrada esta jornada?",
         {"metric": "transfers_in_event"}),
    Case("gm-02", "¿A qué jugadores les están dando más salida esta semana?",
         {"metric": "transfers_out_event"}),
    Case("gm-03", "Dame los mediocampistas más caros de la liga",
         {"metric": "now_cost"}),
    Case("gm-04", "¿Qué defensas tienen menos goles esperados en contra?",
         {"metric": "expected_goals_conceded"}),
    Case("gm-05", "¿Quiénes son los tiradores de penales de sus equipos?",
         {"metric": "penalties_order"}),
    Case("gm-06", "¿Qué jugadores tiran los tiros libres directos?",
         {"metric": "direct_freekicks_order"}),
    Case("gm-07", "¿Qué jugadores tienen más tarjetas amarillas?",
         {"metric": "yellow_cards"}),
    Case("gm-08", "¿Qué porteros hacen más paradas?", {"metric": "saves"}),
    Case("gm-09", "¿Quién tiene más creatividad en la liga?", {"metric": "creativity"}),
    Case("gm-10", "Ordename los jugadores por amenaza ofensiva", {"metric": "threat"}),
)

#: i15 live confirmation, 2026-08-26. Reference: 0/10 fell through to a
#: gameweek tool. gi-04 and gi-05 are deliberate bait -- they name the gameweek
#: explicitly, which is the keyword overlap that used to divert routing.
INVENTED_METRIC_CASES: tuple[Case, ...] = (
    Case("gi-01", "Dame el top 10 de jugadores por chispa ofensiva", {}),
    Case("gi-02", "¿Quién tiene más hambre de gol esta temporada?", {}),
    Case("gi-03", "¿Quién tiene mejor vibra esta fecha?", {}),
    Case("gi-04", "Ranking de jugadores por garra en la jornada 3", {}),
    Case("gi-05", "Ordename los jugadores por regularidad de gameweek", {}),
)

#: i42/i44 direction probes. Reference: order='asc' applied on every call after
#: PR #181. Verbatim from probe_direction.json.
ORDER_DIRECTION_CASES: tuple[Case, ...] = (
    Case("gd-01", "Dame los cinco defensas más baratos de la liga", {"order": "asc"}),
    Case("gd-02", "¿Qué mediocampistas tienen menos propiedad? Busco diferenciales",
         {"order": "asc"}),
    Case("gd-03", "¿Qué porteros conceden menos goles esperados?", {"order": "asc"}),
    # The fourth direction case. Same question text as gm-04 in the metric axis,
    # and deliberately the same id: the runner dedupes it, so it is called once
    # and scored twice -- resolved field AND applied direction on one turn.
    Case("gm-04", "¿Qué defensas tienen menos goles esperados en contra?",
         {"order": "asc"}),
)

#: i41. sb-02/sb-13 verbatim from the routing corpus, kept here so the axis is
#: legible on its own; the runner dedupes them against the routing cases.
OWNERSHIP_CASE_IDS: tuple[str, ...] = ("sb-02", "sb-13")

#: i41 guard. The three ad-hoc negatives plus the eight corpus questions from
#: the over-fire audit -- including tf-09/pv-09, which open with "Necesito
#: saber" (the verb the widened description generalises) and pv-01, which asks
#: about a player's OWNERSHIP. Reference: 0 fires in 45 negative calls.
GUARD_CASE_IDS: tuple[str, ...] = (
    "tf-09", "pv-09", "pv-01", "pv-10", "tf-02", "pv-13", "cp-01", "tf-12",
)
GUARD_ADHOC_CASES: tuple[Case, ...] = (
    Case("neg-defensas", "¿Qué defensas baratos hay?", {},
         acceptable_tools=("get_transfer_suggestion", RANK_TOOL)),
    Case("neg-comparar", "Compara Haaland y Salah", {},
         acceptable_tools=("compare_players", "rank_captain_candidates")),
    Case("neg-jornada", "¿Cuál es la jornada actual?", {},
         acceptable_tools=("get_current_gameweek", "get_gameweek_context")),
)


#: The routing corpus predates ``get_my_squad`` entirely (zero mentions), so it
#: labels sb-02/sb-13 as ``select_players_within_budget`` alone. After PR #186
#: those two turns call ``get_my_squad`` — the behaviour i41 shipped and
#: measured at 5/5. Scored against the stale label, correct behaviour reads as a
#: routing regression, and the two axes contradict each other on the same turn.
#:
#: Patched HERE and not in the corpus on purpose: #171, i38 and i41 were all
#: scored against the corpus as it stands, and editing it would retroactively
#: change what those published numbers meant. This is a labelling correction of
#: exactly the kind the acceptable-SET design exists to absorb.
_ACCEPTABLE_TOOL_PATCHES: dict[str, tuple[str, ...]] = {
    "sb-02": (SQUAD_TOOL,),
    "sb-13": (SQUAD_TOOL,),
}


def _patched_tools(question: dict[str, Any]) -> tuple[str, ...]:
    extra = _ACCEPTABLE_TOOL_PATCHES.get(question["id"], ())
    return tuple(question["acceptable_tools"]) + extra


def _corpus_cases(ids: tuple[str, ...]) -> tuple[Case, ...]:
    from tool_routing_corpus import CORPUS

    by_id = {q["id"]: q for q in CORPUS}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"golden_axes: ids not in tool_routing_corpus: {missing}")
    return tuple(
        Case(id=q["id"], question=q["question"], family=q["family"],
             acceptable_tools=_patched_tools(q), control=bool(q["control"]))
        for q in (by_id[i] for i in ids)
    )


# ---------------------------------------------------------------------------
# The battery. Thresholds pre-registered; each cites its measured reference.
# ---------------------------------------------------------------------------

def build_axes(tier: str = "full") -> tuple[Axis, ...]:
    routing = _routing_cases(tier)
    return (
        Axis(
            id="routing",
            kind=TARGET,
            threshold=0.80,
            reference="#171 / i38: the corpus is labelled with acceptable sets, "
                      "not a single key; luna's rate is the row this run records.",
            rationale="A model that cannot reach the right tool cannot be fixed "
                      "by any downstream assertion. Set below the observed rate "
                      "because acceptable-set labelling already absorbs the "
                      "defensible-alternative cases.",
            cases=routing,
            check=_check_routing,
        ),
        Axis(
            id="metric_resolution",
            kind=TARGET,
            threshold=0.95,
            reference="i18/i19 after PR #181: unknown_metric on 1 of 26 calls (96%).",
            rationale="Asserts the RESOLVED field, not just absence of error -- "
                      "'goles en contra' once returned status=ok while ranking "
                      "top scorers. Set at 0.95, not 0.90: with 10 cases a 0.90 "
                      "bar lets one entirely broken case through, which the "
                      "mutation test caught. At 0.95 a single flaky rep "
                      "(29/30) still passes while a consistently broken case "
                      "(27/30) fails -- the sensitivity actually wanted.",
            cases=METRIC_RESOLUTION_CASES,
            check=_check_metric_resolution,
        ),
        Axis(
            id="invented_metric_relay",
            kind=TARGET,
            threshold=0.80,
            reference="i15 live, 2026-08-26: relayed unknown_metric on 8 of 10 "
                      "calls (80%).",
            rationale="The GATE is the narrow check: the relay must have "
                      "happened. Its threshold comes from i15's own relay "
                      "figure (8/10), not from the 0/10 gameweek-fallback "
                      "figure, because they measure different things -- the "
                      "companion below is what that 0/10 refers to. Both are "
                      "always reported so the criterion cannot be moved "
                      "quietly between them.",
            cases=INVENTED_METRIC_CASES,
            check=_check_invented_relay,
            companion=_check_invented_no_gameweek_answer,
            companion_label="no gameweek answer",
            companion_reference="i15 live, 2026-08-26: 0/10 fell through to a "
                                "gameweek tool (100%).",
        ),
        Axis(
            id="order_direction",
            kind=TARGET,
            threshold=1.00,
            reference="i42/i44 after PR #181: order='asc' applied on every call.",
            rationale="Asserts the order APPLIED, not the argument passed. The "
                      "failure is silent: a descending page reordered by the "
                      "model reads exactly like a correct answer.",
            cases=ORDER_DIRECTION_CASES,
            check=_check_order_direction,
        ),
        Axis(
            id="ownership_no_possessive",
            kind=TARGET,
            threshold=0.80,
            reference="i41 after PR #186: sb-02 5/5 and sb-13 5/5.",
            rationale="Two cases only, so one flake at 3 reps is 5/6 -- the "
                      "threshold tolerates that and still fails a real "
                      "regression to the pre-#186 0/5.",
            cases=_corpus_cases(OWNERSHIP_CASE_IDS),
            check=_check_ownership,
        ),
        Axis(
            id="overfire_guards",
            kind=GUARD,
            threshold=0.0,
            reference="i41: 0 fires of get_my_squad in 45 negative calls.",
            rationale="GUARD -- outranks every target. A false fire injects "
                      "someone's squad into a general question: dirtier "
                      "context, higher cost, possible bias. Failing to call is "
                      "cheaper than calling wrongly, so the ceiling is zero. "
                      "NOT stale-sensitive: a departed player changes what the "
                      "question measures but not whether the squad is relevant "
                      "to it, so dropping those cases would only shrink the "
                      "guard.",
            cases=_corpus_cases(GUARD_CASE_IDS) + GUARD_ADHOC_CASES,
            check=_check_overfire,
            stale_sensitive=False,
        ),
        Axis(
            id="synthesis_present",
            kind=TARGET,
            threshold=1.00,
            reference="i46, opened 2026-08-28: 3 of 9 calls in an unrelated "
                      "probe returned synthesis_turn=False.",
            rationale="Scored over EVERY observation in the run, so it costs no "
                      "extra calls -- exactly the standing check whose absence "
                      "let i46 be found sideways. BLOCKED: it measures our "
                      "defect, not the model's, so it gets its own verdict "
                      "line. Every candidate fails it identically while i46 is "
                      "open, and a gate that rejects everyone stops "
                      "discriminating.",
            cases=(),          # scored across the whole run, see runner
            check=_check_synthesis,
            blocked_by="i46",
        ),
    )


#: Axes scored over every observation rather than their own case list.
WHOLE_RUN_AXES = frozenset({"synthesis_present"})


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class AxisResult:
    axis_id: str
    kind: str
    threshold: float
    numerator: int
    denominator: int
    reference: str
    #: Cases dropped because a pinned entity no longer resolves. Reported, never
    #: silently absorbed -- see golden_preflight.
    excluded: int = 0
    excluded_ids: tuple[str, ...] = ()
    companion_numerator: "int | None" = None
    companion_label: str = ""
    companion_reference: str = ""
    blocked_by: "str | None" = None

    @property
    def companion_rate(self) -> "float | None":
        if self.companion_numerator is None or not self.denominator:
            return None
        return self.companion_numerator / self.denominator

    @property
    def rate(self) -> float:
        return self.numerator / self.denominator if self.denominator else 0.0

    @property
    def passed(self) -> bool:
        if self.denominator == 0:
            return False
        if self.kind == GUARD:
            return self.rate <= self.threshold
        return self.rate >= self.threshold

    @property
    def label(self) -> str:
        return "fires" if self.kind == GUARD else "pass"


def score_axis(
    axis: Axis,
    observations: list[dict[str, Any]],
    stale_case_ids: "frozenset[str] | set[str]" = frozenset(),
) -> AxisResult:
    """Score one axis against the shared observation pool.

    Pure and deterministic: the tests drive it with recorded traces.

    ``stale_case_ids`` are dropped from the denominator, not counted as passes
    and not as failures. A question whose player has left measures nothing: the
    first reference run scored pv-11 as a 3/3 reproduction of i46 when there was
    simply nothing to synthesise. Both denominators are reported.
    """
    if axis.id in WHOLE_RUN_AXES:
        candidates = [o for o in observations if _is_valid(o)]
        by_case: dict[str, Case] = {}
    else:
        wanted = {c.id: c for c in axis.cases}
        candidates = [o for o in observations
                      if _is_valid(o) and o.get("question_id") in wanted]
        by_case = wanted

    if axis.stale_sensitive:
        relevant = [o for o in candidates if o.get("question_id") not in stale_case_ids]
        dropped = sorted({str(o.get("question_id")) for o in candidates
                          if o.get("question_id") in stale_case_ids})
    else:
        relevant, dropped = candidates, []

    hits = 0
    companion_hits = 0
    for obs in relevant:
        case = by_case.get(obs.get("question_id")) or Case(
            id=str(obs.get("question_id")), question=str(obs.get("question", "")),
        )
        if axis.check(case, obs):
            hits += 1
        if axis.companion is not None and axis.companion(case, obs):
            companion_hits += 1

    return AxisResult(
        axis_id=axis.id, kind=axis.kind, threshold=axis.threshold,
        numerator=hits, denominator=len(relevant), reference=axis.reference,
        excluded=len(candidates) - len(relevant), excluded_ids=tuple(dropped),
        companion_numerator=companion_hits if axis.companion is not None else None,
        companion_label=axis.companion_label,
        companion_reference=axis.companion_reference,
        blocked_by=axis.blocked_by,
    )


def overall_verdict(results: list[AxisResult]) -> tuple[bool, str]:
    """Guards outrank targets; blocked axes get their own line.

    A blocked axis (one measuring OUR defect, e.g. i46) still fails the run but
    is never conflated with the model's own failures. Reporting "2 axes failed"
    when one of them fails identically for every candidate is how a verdict
    stops being read.
    """
    guards = [r for r in results if r.kind == GUARD]
    targets = [r for r in results if r.kind == TARGET]

    breached = [r for r in guards if not r.passed]
    if breached:
        names = ", ".join(r.axis_id for r in breached)
        return False, f"REJECT — guard breached ({names}). Guards outrank targets."

    failed = [r for r in targets if not r.passed]
    if not failed:
        return True, "ACCEPT — every guard held and every target met its threshold."

    model_failures = [r for r in failed if r.blocked_by is None]
    blocked_failures = [r for r in failed if r.blocked_by is not None]

    parts: list[str] = []
    if model_failures:
        names = ", ".join(r.axis_id for r in model_failures)
        parts.append(f"{len(model_failures)} model axis ({names})")
    if blocked_failures:
        names = ", ".join(f"{r.axis_id} blocked by {r.blocked_by}"
                          for r in blocked_failures)
        parts.append(f"{len(blocked_failures)} blocked ({names})")
    return False, "REJECT — " + "; ".join(parts) + "."
