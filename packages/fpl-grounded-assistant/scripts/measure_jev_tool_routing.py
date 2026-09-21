"""Pilot measurement: shadow-compare Jev (TypeSafe AI) against
tool_routing_corpus.CORPUS -- the same labelled Spanish-first corpus already
used to measure the current LLM-based orchestrator's tool routing (see
measure_tool_routing.py / field-notes/2026-08-23 confusion-matrix work).

Supports two providers (--provider, default "native"):
- "native": TypeSafe's own API, POST https://api.typesafe.ai/v1/systemone,
  model "jev-latest". Not rate-limited by Vercel's shared free tier; choice
  answers carry a real "confidence" field.
- "gateway": Vercel AI Gateway, POST https://ai-gateway.vercel.sh/v1/evaluate,
  model "typesafe-ai/jev". Kept for comparison -- its free tier rate-limits
  hard (observed: throttles after ~5 requests despite retry/backoff).

This is a PILOT/MEASUREMENT script only:
- Makes real, billed calls to Jev.
- Only IMPORTS tool_routing_corpus.py and tool_schema_registry.py (both
  read-only, pure-data modules with no side effects on import).
- Does NOT touch fpl_server.py, decision_router.py, or any production code
  path. Nothing here is wired into the live routing system.

The "criteria" set for Jev's choice question is the union of every tool name
appearing anywhere in CORPUS's acceptable_tools (not just the sampled subset)
-- deliberately the full-catalog difficulty, not a pre-narrowed one, so the
measured accuracy isn't inflated relative to what a real router would face.

Usage (from packages/fpl-grounded-assistant):
    python scripts/measure_jev_tool_routing.py --per-family 3 --out field-notes/artifacts/jev-tool-routing-pilot.jsonl

Requires TYPESAFE_API_KEY (or AI_GATEWAY_API_KEY for --provider gateway),
read from .env.jev-pilot in this same directory (gitignored; see
packages/fpl-grounded-assistant/.gitignore). Not read from the real .env --
this pilot never touches production provider config.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
ENV_FILE = PACKAGE_ROOT / ".env.jev-pilot"

#: Per-provider wire shape. Only "choice" questions are used in this script,
#: so the boolean/"noul" type-name difference between the two APIs never
#: comes up here -- but it's a real trap (native calls it "noul", not
#: "boolean") if this script is ever extended to ask a boolean question.
PROVIDERS: dict[str, dict[str, str]] = {
    "native": {
        "url": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest",
        "key_env": "TYPESAFE_API_KEY",
    },
    "gateway": {
        "url": "https://ai-gateway.vercel.sh/v1/evaluate",
        "model": "typesafe-ai/jev",
        "key_env": "AI_GATEWAY_API_KEY",
    },
}


def _configure_imports() -> None:
    """Same pattern as measure_tool_routing.py: put every packages/* dir and
    this scripts/ dir on sys.path so the monorepo's cross-package imports
    (e.g. fpl_tool_runner, pulled in transitively via fpl_grounded_assistant's
    __init__) resolve without an editable install."""
    packages_dir = REPO_ROOT / "packages"
    for pkg in sorted(packages_dir.iterdir()):
        if pkg.is_dir():
            sys.path.insert(0, str(pkg))
    sys.path.insert(0, str(Path(__file__).resolve().parent))


_configure_imports()

from fpl_grounded_assistant.tool_schema_registry import get_tool_schema  # noqa: E402
from jev_routing_criteria_v2 import CRITERIA_V2, NONE_OPTION  # noqa: E402
from routing_label_overlay import acceptable_tools as overlaid_acceptable_tools  # noqa: E402
from tool_routing_corpus import CORPUS, ZONAL_TOOLS  # noqa: E402


def load_api_key(key_env: str) -> str:
    if not ENV_FILE.exists():
        raise SystemExit(f"Missing {ENV_FILE} -- paste the {key_env} value there first.")
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key_env}="):
            key = line.split("=", 1)[1].strip()
            if key:
                return key
    raise SystemExit(f"{key_env} is empty in {ENV_FILE}.")


def corpus_tool_names() -> set[str]:
    """Union of every acceptable tool across the WHOLE corpus."""
    names: set[str] = set()
    for item in CORPUS:
        names.update(item["acceptable_tools"])
    return names - ZONAL_TOOLS  # environment-broken in a worktree, not product-broken; excluded per corpus docstring


def build_criteria_v1() -> dict[str, object]:
    """First sentence of each tool's real tool_schema_registry description."""
    criteria: dict[str, object] = {}
    for name in sorted(corpus_tool_names()):
        schema = get_tool_schema(name)
        desc = schema.description if schema else name
        criteria[name] = desc.split(". ")[0].strip().rstrip(".")
    return criteria


def build_criteria_v2() -> dict[str, object]:
    """Structured {what, not_for, examples} per tool plus a no-match option.
    The option name is what Jev returns and what gets matched against
    acceptable_tools, so a typo would be a silent miss: every corpus tool
    must be present. Extra options (full-catalog tools the corpus never
    labels) are allowed and reported -- they are the fair-menu condition."""
    expected = corpus_tool_names()
    actual = set(CRITERIA_V2) - {NONE_OPTION}
    if not expected <= actual:
        raise SystemExit(f"criteria v2 is missing corpus tools: {sorted(expected - actual)}")
    extras = sorted(actual - expected)
    if extras:
        print(f"Criteria v2 extra options beyond corpus labels ({len(extras)}): {extras}")
    return dict(CRITERIA_V2)


CRITERIA_BUILDERS = {"v1": build_criteria_v1, "v2": build_criteria_v2}


def sample_corpus(per_family: int | None) -> list[dict[str, Any]]:
    if per_family is None:
        return list(CORPUS)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in CORPUS:
        by_family[item["family"]].append(item)
    sampled: list[dict[str, Any]] = []
    for family_items in by_family.values():
        sampled.extend(family_items[:per_family])
    return sampled


def _retry_after_seconds(header: str | None) -> float | None:
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except ValueError:
        return None


_RETRYABLE_STATUSES = {429, 503}


def call_jev(
    session: requests.Session,
    api_key: str,
    url: str,
    model: str,
    question: str,
    criteria: dict[str, object],
    max_attempts: int = 6,
) -> dict[str, Any]:
    """Retry 429/503 honoring retry-after when present, exponential backoff
    otherwise. Per Vercel's own guidance (docs/ai-gateway/rate-limits) for
    the gateway provider: a 429 is not a failure of the request, just retry
    it unchanged. Applied to both providers since it's a reasonable default
    even where it's never been observed necessary (native, so far)."""
    body = {
        "model": model,
        "state": question,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which tool should answer this Fantasy Premier League question first?",
                "criteria": criteria,
            }
        },
    }
    for attempt in range(max_attempts):
        resp = session.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=15,
        )
        if resp.status_code not in _RETRYABLE_STATUSES:
            resp.raise_for_status()
            return resp.json()
        if attempt == max_attempts - 1:
            resp.raise_for_status()
        delay = _retry_after_seconds(resp.headers.get("retry-after"))
        if delay is None:
            delay = min(30.0, 2 ** attempt)
        time.sleep(delay)
    raise RuntimeError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-family", type=int, default=3, help="Items sampled per corpus family (default 3). Omit --all to use this.")
    parser.add_argument("--all", action="store_true", help="Run the entire corpus instead of a per-family sample.")
    parser.add_argument("--out", type=Path, default=PACKAGE_ROOT / "field-notes-artifacts-jev-pilot.jsonl")
    parser.add_argument("--delay", type=float, default=4.0, help="Fixed seconds to sleep between requests (default 4.0; irrelevant for --provider native unless it turns out to rate-limit too).")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="native")
    parser.add_argument("--criteria", choices=sorted(CRITERIA_BUILDERS), default="v1", help="v1 = first sentence of each tool description; v2 = structured what/not_for/examples + none_of_these.")
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    api_key = load_api_key(provider["key_env"])
    criteria = CRITERIA_BUILDERS[args.criteria]()
    items = sample_corpus(None if args.all else args.per_family)
    # One connection reused across the run: the v1 full run lost 2 of 118
    # calls to a Windows-side SSL 'Not enough space' from opening a fresh
    # TLS connection per request.
    session = requests.Session()

    print(f"Provider: {args.provider} ({provider['url']}, model={provider['model']})")
    print(f"Criteria: {args.criteria} ({len(criteria)} options)")
    print(f"Sample size: {len(items)} questions (of {len(CORPUS)} total in corpus)")
    print(f"Writing rows to: {args.out}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    correct = 0
    total_confidence_correct: list[float] = []
    total_confidence_incorrect: list[float] = []
    per_family_correct: dict[str, int] = defaultdict(int)
    per_family_total: dict[str, int] = defaultdict(int)
    none_picks = 0
    failed_requests = 0

    with args.out.open("w", encoding="utf-8") as fh:
        for item in items:
            t0 = time.monotonic()
            try:
                result = call_jev(session, api_key, provider["url"], provider["model"], item["question"], criteria)
            except requests.RequestException as exc:
                failed_requests += 1
                print(f"  [{item['id']}] REQUEST FAILED: {exc}")
                time.sleep(args.delay)
                continue
            latency_ms = (time.monotonic() - t0) * 1000

            answer = result.get("answers", {}).get("route", {})
            choice = answer.get("choice")
            probabilities = answer.get("probabilities", {})
            # Native returns "confidence" directly; Gateway doesn't, so fall
            # back to the chosen option's own probability.
            if "confidence" in answer:
                confidence = answer["confidence"]
            else:
                confidence = probabilities.get(choice, 0.0) if choice else 0.0
            acceptable = overlaid_acceptable_tools(item)
            is_match = choice in acceptable
            if choice == NONE_OPTION:
                none_picks += 1

            row = {
                "id": item["id"],
                "family": item["family"],
                "control": item["control"],
                "question": item["question"],
                "acceptable_tools": acceptable,
                "acceptable_tools_corpus": item["acceptable_tools"],
                "jev_choice": choice,
                "jev_confidence": confidence,
                "match": is_match,
                "latency_ms": round(latency_ms, 1),
                "usage": result.get("usage"),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()

            per_family_total[item["family"]] += 1
            if is_match:
                correct += 1
                per_family_correct[item["family"]] += 1
                total_confidence_correct.append(confidence)
            else:
                total_confidence_incorrect.append(confidence)

            mark = "OK" if is_match else "MISS"
            print(f"  [{mark}] {item['id']:12s} jev={choice!r:28s} conf={confidence:.2f} expected={acceptable}")

            time.sleep(args.delay)

    n = len(items)
    answered = n - failed_requests
    print()
    print(f"Overall: {correct}/{n} ({100 * correct / n:.1f}%)" if n else "No items run.")
    if failed_requests:
        print(f"  ({failed_requests} request failures; {correct}/{answered} = {100 * correct / answered:.1f}% of answered)")
    if NONE_OPTION in criteria:
        print(f"  {NONE_OPTION} picked {none_picks} time(s) (corpus has no negatives, so each is a miss)")
    print("Per family:")
    for family in sorted(per_family_total):
        c, t = per_family_correct[family], per_family_total[family]
        print(f"  {family:20s} {c}/{t} ({100 * c / t:.1f}%)")
    if total_confidence_correct:
        print(f"Mean confidence on matches:   {sum(total_confidence_correct) / len(total_confidence_correct):.2f}")
    if total_confidence_incorrect:
        print(f"Mean confidence on misses:    {sum(total_confidence_incorrect) / len(total_confidence_incorrect):.2f}")


if __name__ == "__main__":
    main()
