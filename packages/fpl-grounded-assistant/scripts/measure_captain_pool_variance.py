"""Measure candidate-pool variance for an identical captaincy question.

MEASUREMENT ONLY. This script must be committed unchanged with the pre-change
observations so the decision rule cannot be moved after seeing the result.

Pre-registered setup
--------------------
* Question (exact): ``¿A quién debería dar el brazalete?``
* Provider/model: ``openai`` / ``gpt-5.6-luna`` by default. ``--provider`` and
  ``--model`` re-point a repeat run at another model without editing this file;
  the values actually used are written into every observation and printed in
  the header, so a re-run is never confusable with the pre-registered one. The
  defaults are the pinned production pair, unchanged, and no env var can move
  them (see the note in ``measure_tool_routing``).
* Frozen bootstrap: ``agentic-loop-bootstrap-2026-08-18.json``; its SHA-256 is
  written into every observation.
* Repetitions: at least 20. The script refuses a smaller N.
* Sampling controls: production defaults (``temperature=None``, ``top_p=None``)
  through ``measure_tool_routing.run_one``.

Pre-registered primary metric and decision rule
------------------------------------------------
The primary metric is the number of distinct ordered ``candidates`` arrays the
model emits on turns where it selects ``rank_captain_candidates``. Candidate
identity is the string value of each candidate's ``query`` in emitted order;
per-candidate scoring overrides do not create a second list identity. Turns
that select another tool are reported separately and excluded from this metric
because those tools have no ``candidates`` argument.

* >= 3 distinct emitted lists in 20 valid turns: PROCEED. Axis 3 is supported
  by observed variance as well as by the structural schema gap.
* exactly 1 distinct emitted list: STOP_AND_REINVESTIGATE. Do not change the
  ranking schema on the strength of this measurement.
* exactly 2 distinct emitted lists, or fewer than 20 valid observations:
  INCONCLUSIVE. Pause rather than treating the threshold as met.
* Any harness exception makes the run INVALID, regardless of the counts.

Each JSONL row records the chosen tool, full tool sequence, emitted candidates,
candidate count and names, synthesis_turn, and the common routing observation.

Usage (from packages/fpl-grounded-assistant):

    python scripts/measure_captain_pool_variance.py \
        --out ../../field-notes/artifacts/captain-pool-variance-pre.jsonl \
        --reps 20
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402

QUESTION = "¿A quién debería dar el brazalete?"
QUESTION_ID = "captain-pool-variance"
MIN_REPS = 20
RANK_TOOL = "rank_captain_candidates"


def _candidate_names(tool_args: dict[str, Any]) -> list[str]:
    raw = tool_args.get("candidates")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            names.append(str(item.get("query", "<missing-query>")))
        else:
            names.append(str(item))
    return names


def _verdict(observations: list[dict[str, Any]]) -> tuple[str, int]:
    if any(obs.get("exception") is not None for obs in observations):
        return "INVALID", 3

    valid = [obs for obs in observations if obs.get("exception") is None]
    rank_turns = [obs for obs in valid if obs.get("tool_chosen") == RANK_TOOL]
    distinct = {tuple(obs["candidate_names"]) for obs in rank_turns}

    if len(valid) < MIN_REPS:
        return "INCONCLUSIVE", 1
    if len(distinct) >= 3:
        return "PROCEED", 0
    if len(distinct) == 1:
        return "STOP_AND_REINVESTIGATE", 1
    return "INCONCLUSIVE", 1


def _summarise(observations: list[dict[str, Any]]) -> int:
    rank_turns = [
        obs for obs in observations
        if obs.get("exception") is None and obs.get("tool_chosen") == RANK_TOOL
    ]
    lists = Counter(tuple(obs["candidate_names"]) for obs in rank_turns)
    chosen = Counter(obs.get("tool_chosen") or "<none>" for obs in observations)
    verdict, code = _verdict(observations)

    print("\n--- CHOSEN TOOLS ---")
    for name, count in sorted(chosen.items()):
        print(f"  {name}: {count}")
    print("\n--- DISTINCT RANK CANDIDATE LISTS ---")
    for names, count in sorted(lists.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count}x {list(names)}")
    # Reported, not part of the pre-registered decision rule. Before the row
    # carried this flag the empty-synthesis events were visible only on stderr
    # and belonged to no observation, so they could not be attributed at all.
    empty = [obs for obs in observations if obs.get("empty_provider_response")]
    print("\n--- EMPTY PROVIDER RESPONSES (render() fallback) ---")
    print(f"  {len(empty)}/{len(observations)} turns; "
          f"reps: {[obs.get('rep') for obs in empty]}")
    print(f"\nprimary_metric_distinct_lists={len(lists)}")
    print(f"rank_turns={len(rank_turns)} total_turns={len(observations)}")
    print(f"VERDICT={verdict}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=MIN_REPS)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--env-file",
        default=str(base.PACKAGE_ROOT / ".env"),
        help="Optional dotenv file; existing environment variables win.",
    )
    parser.add_argument(
        "--provider",
        default=base.PROVIDER,
        choices=sorted(base.API_KEY_ENV_BY_PROVIDER),
        help="LLM provider (default: the pinned %(default)s). Selects the API "
             "key env var too.",
    )
    parser.add_argument(
        "--model",
        default=base.MODEL,
        help="Model id (default: the pinned %(default)s). A model with no entry "
             "in measure_tool_routing.PRICING_PER_1M_BY_MODEL still runs; its "
             "cost is reported as unknown, never estimated at other rates.",
    )
    args = parser.parse_args(argv)

    if args.reps < MIN_REPS:
        print(f"--reps must be >= {MIN_REPS}; refusing to weaken the gate.", file=sys.stderr)
        return 2

    base._configure_imports()
    base._load_env_file(Path(args.env_file))

    # base.run_one reads these at call time; set them so --provider/--model are
    # real and not silently ignored. Same mechanism golden_battery.py uses.
    base.PROVIDER, base.MODEL = args.provider, args.model

    api_key = base.require_api_key(base.PROVIDER)

    bootstrap_path = Path(args.bootstrap)
    bootstrap_bytes = bootstrap_path.read_bytes()
    bootstrap = json.loads(bootstrap_bytes)
    bootstrap_sha256 = hashlib.sha256(bootstrap_bytes).hexdigest()
    question = {
        "id": QUESTION_ID,
        "family": "captain_pool",
        "acceptable_tools": [RANK_TOOL],
        "control": False,
        "question": QUESTION,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, Any]] = []
    print(
        f"captain pool variance: {args.reps} identical calls against "
        f"{base.PROVIDER}/{base.MODEL}; bootstrap_sha256={bootstrap_sha256}",
        file=sys.stderr,
    )
    with out_path.open("a", encoding="utf-8") as fh:
        for rep in range(args.reps):
            obs = base.run_one(question, rep, bootstrap, api_key)
            tool_args = obs.get("tool_args") or {}
            names = _candidate_names(tool_args)
            obs.update(
                bootstrap_sha256=bootstrap_sha256,
                emitted_candidates=tool_args.get("candidates"),
                candidate_count=len(names),
                candidate_names=names,
            )
            fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
            fh.flush()
            observations.append(obs)
            print(
                f"  {rep + 1}/{args.reps}: tool={obs.get('tool_chosen')} "
                f"candidates={names} synthesis_turn={obs.get('synthesis_turn')} "
                f"empty_provider_response={obs.get('empty_provider_response')}",
                file=sys.stderr,
            )

    print(f"cost={base.format_spend(observations)}", file=sys.stderr)
    return _summarise(observations)


if __name__ == "__main__":
    raise SystemExit(main())
