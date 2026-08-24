"""Turn a tool-routing observations JSONL (from measure_tool_routing.py) into
a confusion matrix, per-question hit rates, and a cost/exception summary.

Every function here is a pure function over already-loaded observation
dicts -- no network calls, no file I/O except load_observations() itself --
so this module is unit-testable against fabricated data (see
tests/test_analyze_tool_routing.py) without spending anything.

Deliberately separate from measure_tool_routing.py: a bug in this analysis
code must never be able to touch, let alone lose, the raw paid observations
already sitting on disk.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

#: Sentinel column used in the confusion matrix when no tool was selected at all.
NO_TOOL = "(no_tool)"


def load_observations(path: str | Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                observations.append(json.loads(line))
    return observations


def first_tool(observation: dict[str, Any]) -> str | None:
    """The tool actually picked first, from the full recorded sequence."""
    sequence = observation.get("tool_sequence") or []
    if sequence:
        return sequence[0]
    return observation.get("tool_chosen")


def is_hit_first(observation: dict[str, Any]) -> bool:
    """Did the FIRST tool picked fall in the acceptable set?"""
    tool = first_tool(observation)
    return tool is not None and tool in observation.get("acceptable_tools", [])


def is_hit_any(observation: dict[str, Any]) -> bool:
    """Did ANY tool in the full executed sequence fall in the acceptable set?

    Softer than is_hit_first(): a question whose acceptable set spans two
    tools that are meant to be called in sequence (e.g. build_squad then
    get_chip_advice) can be fully satisfied without the FIRST call being a
    member of the set.
    """
    acceptable = set(observation.get("acceptable_tools", []))
    sequence = observation.get("tool_sequence") or []
    if not sequence and observation.get("tool_chosen"):
        sequence = [observation["tool_chosen"]]
    return any(t in acceptable for t in sequence)


def count_exceptions(observations: list[dict[str, Any]]) -> int:
    return sum(1 for o in observations if o.get("exception") is not None)


def total_cost_usd(observations: list[dict[str, Any]]) -> float:
    return sum(o.get("cost_usd", 0.0) for o in observations)


def build_confusion_matrix(
    observations: list[dict[str, Any]],
) -> dict[str, Counter]:
    """{expected_family: Counter({selected_tool: count})} using the FIRST tool picked.

    Harness exceptions (no LLM call actually completed) are excluded -- they
    are a harness/network failure, not a routing decision, and mixing them in
    would silently understate the real miss rate.
    """
    matrix: dict[str, Counter] = defaultdict(Counter)
    for obs in observations:
        if obs.get("exception") is not None:
            continue
        tool = first_tool(obs) or NO_TOOL
        matrix[obs["family"]][tool] += 1
    return matrix


def per_question_hit_rates(observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{question_id: {family, control, pinned, n, hit_rate_first, hit_rate_any, tools_seen}}"""
    by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        if obs.get("exception") is not None:
            continue
        by_question[obs["question_id"]].append(obs)

    result: dict[str, dict[str, Any]] = {}
    for qid, obs_list in by_question.items():
        n = len(obs_list)
        hits_first = sum(1 for o in obs_list if is_hit_first(o))
        hits_any = sum(1 for o in obs_list if is_hit_any(o))
        tools_seen = Counter(first_tool(o) or NO_TOOL for o in obs_list)
        result[qid] = {
            "family": obs_list[0]["family"],
            "control": obs_list[0]["control"],
            "pinned": obs_list[0].get("pinned", False),
            "acceptable_tools": obs_list[0]["acceptable_tools"],
            "n": n,
            "hits_first": hits_first,
            "hit_rate_first": hits_first / n if n else 0.0,
            "hits_any": hits_any,
            "hit_rate_any": hits_any / n if n else 0.0,
            "tools_seen": dict(tools_seen),
        }
    return result


def control_summary(per_question: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate hit rate over control (unambiguous single-tool) questions only.

    A control miss is a stronger signal than an ambiguous-question miss: it
    means something worse than boundary confusion is going on (see the
    measurement task's "controls" requirement).
    """
    controls = [q for q in per_question.values() if q["control"]]
    if not controls:
        return {"n_questions": 0, "mean_hit_rate": None, "worst": []}
    worst = sorted(controls, key=lambda q: q["hit_rate_first"])[:5]
    return {
        "n_questions": len(controls),
        "mean_hit_rate": sum(q["hit_rate_first"] for q in controls) / len(controls),
        "worst": [
            {"question_id": qid, **q}
            for qid, q in per_question.items()
            if q["control"] and q in worst
        ],
    }


def worst_offenders(per_question: dict[str, dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """Lowest hit_rate_first questions, ambiguous ones only (controls reported separately)."""
    ambiguous = [
        {"question_id": qid, **q} for qid, q in per_question.items() if not q["control"]
    ]
    return sorted(ambiguous, key=lambda q: q["hit_rate_first"])[:n]


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """One-call convenience: everything a report needs, JSON-serialisable."""
    matrix = build_confusion_matrix(observations)
    per_question = per_question_hit_rates(observations)
    return {
        "n_observations": len(observations),
        "n_exceptions": count_exceptions(observations),
        "total_cost_usd": round(total_cost_usd(observations), 4),
        "confusion_matrix": {family: dict(counts) for family, counts in matrix.items()},
        "per_question": per_question,
        "control_summary": control_summary(per_question),
        "worst_offenders": worst_offenders(per_question),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations_jsonl")
    parser.add_argument("--out", default=None, help="write the summary JSON here too")
    args = parser.parse_args(argv)

    observations = load_observations(args.observations_jsonl)
    if not observations:
        print("No observations loaded; nothing to analyze.", file=sys.stderr)
        return 1

    summary = summarize(observations)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if summary["n_exceptions"]:
        print(
            f"WARNING: {summary['n_exceptions']} observations are harness exceptions, "
            "not real routing decisions -- they were excluded from the matrix but you "
            "should investigate before trusting the aggregate.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
