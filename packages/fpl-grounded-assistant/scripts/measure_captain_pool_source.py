"""Measure how often the model sends its own captain list instead of ours.

MEASUREMENT ONLY. Commit this script unchanged alongside its first observation
file. The decision rule below is written before any call has been made.

What this counts, and why it could not be counted before
--------------------------------------------------------
The deterministic pool only runs when the model omits ``candidates``. That
omission is requested through the tool schema's description -- persuasion, not
obligation -- so the share of turns that actually reach the deterministic pool
is an open question, not a known quantity.

Two production observations exist, one of each kind. **That is n=1 each. It is
not a rate**, and nothing here should be read as confirming either.

Counting this used to require parsing Spanish prose, because ``pool_source``
lived only in the deterministic renderer, where it picked a sentence that
disappeared the moment synthesis wrote the answer instead. It is now a
structured field on the response, so this probe reads the field. It never
inspects answer text.

Pre-registered setup
--------------------
* Question (exact): the same one the variance probe uses, so the two are
  comparable: ``A quien deberia dar el brazalete?`` (the accented Spanish form
  in ``QUESTION`` below is authoritative).
* Provider/model and sampling controls: production defaults, via
  ``measure_tool_routing.run_one``.
* Frozen bootstrap, with its SHA-256 written into every observation.
* Minimum 20 valid turns. The script refuses fewer.

Pre-registered primary metric and decision rule
------------------------------------------------
The primary metric is the share of valid ``rank_captain_candidates`` turns
whose ``pool_source`` is ``"caller"``.

* ``caller`` share >= 0.25: CALLER_POOL_IS_COMMON. The deterministic pool is
  bypassed often enough that anything relying on it -- the squad accounting,
  the presented lists, the hipster -- is not reliably in play. Schema
  persuasion is insufficient and the argument should be constrained.
* ``caller`` share <= 0.05: DERIVED_POOL_DOMINATES. Treat the deterministic
  pool as the normal path; revisit only if the model or prompt changes.
* anything between, or fewer than 20 valid rank turns: INCONCLUSIVE. Report
  the counts and take no action. An inconclusive result is a result.
* Any harness exception makes the whole run INVALID regardless of counts.
* A turn whose ``pool_source`` is missing is counted as ``unknown`` and
  excluded from the share, and a run where unknowns exceed a tenth of the
  valid rank turns is INVALID: that means the field is not arriving, which is
  a defect in the instrument rather than a finding about the model.

Do not attribute any difference between observations to a cause. The model is
non-deterministic -- an earlier slice measured seven distinct lists in ten
identical turns -- and four explanations already turned out to be false in this
line of work.

Usage (from packages/fpl-grounded-assistant)::

    python scripts/measure_captain_pool_source.py \
        --out ../../field-notes/artifacts/captain-pool-source-2026-09-04.jsonl \
        --reps 20
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402

QUESTION = "¿A quién debería dar el brazalete?"
QUESTION_ID = "captain-pool-source"
MIN_REPS = 20
RANK_TOOL = "rank_captain_candidates"
CALLER_COMMON_SHARE = 0.25
DERIVED_DOMINANT_SHARE = 0.05
MAX_UNKNOWN_SHARE = 0.10


def _verdict(observations: list[dict[str, Any]]) -> tuple[str, int, dict[str, Any]]:
    """Apply the rule above. Returns (verdict, exit_code, counts)."""
    counts: dict[str, Any] = {}
    if any(obs.get("exception") is not None for obs in observations):
        return "INVALID", 3, counts

    valid = [obs for obs in observations if obs.get("exception") is None]
    rank_turns = [obs for obs in valid if obs.get("tool_chosen") == RANK_TOOL]
    sources = Counter(
        obs.get("tool_output_pool_source") or "unknown" for obs in rank_turns
    )
    caller = sources.get("caller", 0)
    derived = sources.get("derived", 0)
    unknown = sources.get("unknown", 0)
    known = caller + derived
    counts = {
        "valid_turns": len(valid),
        "rank_turns": len(rank_turns),
        "caller": caller,
        "derived": derived,
        "unknown": unknown,
        "caller_share": (caller / known) if known else None,
    }

    if rank_turns and unknown > MAX_UNKNOWN_SHARE * len(rank_turns):
        # The field is not arriving. That is our defect, not a finding.
        return "INVALID", 3, counts
    if len(rank_turns) < MIN_REPS or not known:
        return "INCONCLUSIVE", 1, counts

    share = caller / known
    if share >= CALLER_COMMON_SHARE:
        return "CALLER_POOL_IS_COMMON", 0, counts
    if share <= DERIVED_DOMINANT_SHARE:
        return "DERIVED_POOL_DOMINATES", 0, counts
    return "INCONCLUSIVE", 1, counts


def _summarise(observations: list[dict[str, Any]]) -> int:
    verdict, code, counts = _verdict(observations)
    chosen = Counter(obs.get("tool_chosen") or "<none>" for obs in observations)

    print("\n--- CHOSEN TOOLS ---")
    for name, count in sorted(chosen.items()):
        print(f"  {name}: {count}")
    print("\n--- POOL SOURCE ON RANK TURNS ---")
    for key in ("caller", "derived", "unknown"):
        print(f"  {key}: {counts.get(key, 0)}")
    share = counts.get("caller_share")
    print(
        "\nprimary_metric_caller_share="
        + ("n/a" if share is None else f"{share:.3f}")
    )
    print(f"rank_turns={counts.get('rank_turns', 0)} total_turns={len(observations)}")
    print(f"VERDICT={verdict}")
    if verdict == "INCONCLUSIVE":
        print("An inconclusive result is a result. Take no action on it.")
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
    args = parser.parse_args(argv)

    if args.reps < MIN_REPS:
        print(
            f"--reps must be >= {MIN_REPS}; refusing to weaken the gate.",
            file=sys.stderr,
        )
        return 2

    base._configure_imports()
    base._load_env_file(Path(args.env_file))
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set; aborting before any paid call.", file=sys.stderr)
        return 2

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
    cost = 0.0
    print(
        f"captain pool source: {args.reps} identical calls against "
        f"{base.PROVIDER}/{base.MODEL}; bootstrap_sha256={bootstrap_sha256}",
        file=sys.stderr,
    )
    with out_path.open("a", encoding="utf-8") as fh:
        for rep in range(args.reps):
            obs = base.run_one(question, rep, bootstrap, api_key)
            obs.update(bootstrap_sha256=bootstrap_sha256)
            fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
            fh.flush()
            observations.append(obs)
            cost += float(obs.get("cost_usd") or 0.0)
            print(
                f"  {rep + 1}/{args.reps}: tool={obs.get('tool_chosen')} "
                f"pool_source={obs.get('tool_output_pool_source')} "
                f"pool_size={obs.get('tool_output_pool_size')} "
                f"synthesis_turn={obs.get('synthesis_turn')}",
                file=sys.stderr,
            )

    print(f"cost=${cost:.4f}", file=sys.stderr)
    return _summarise(observations)


if __name__ == "__main__":
    raise SystemExit(main())
