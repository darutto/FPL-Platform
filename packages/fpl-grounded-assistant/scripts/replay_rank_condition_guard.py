"""Brief 0a replay: which SAVED ranking questions would the season guard refuse?

Read-only, no network, no model, no paid call. For every saved
``rank_players_by_metric`` call (question + the metric the model sent) it asks
the real tool handler twice on an EMPTY bootstrap -- only the resolution
matters, not the rows:

  before  the pure ranking, as eb35eee4 did (status of the call)
  after   the handler with the guard, fed the question as the user's raw text

and reports, by DISTINCT question, every call whose status changed (a refusal)
A refusal on a question
that does not name a condition is a FALSE REFUSAL and is listed first.

Sources (same set as the planner's Appendix B, E1):
  * every ``*.jsonl`` / ``*.ndjson`` in ``git ls-tree -r <ref>`` (stable part)
  * ``C:\\Users\\thera\\wt-jev-pilot\\**\\*.jsonl``
  * ``<repo>/.worktrees/*/packages/fpl-grounded-assistant/audit_logs/*.ndjson``
  * ``<repo>/packages/fpl-grounded-assistant/audit_logs/*.ndjson``
  * ``C:\\Users\\thera\\fpl-audit\\*.ndjson``
and the 128-question routing corpus (``scripts/tool_routing_corpus.py``): for
each corpus question the DETECTOR is run (the corpus labels tools, not metrics,
so there is no saved call to resolve).

Run from the repo root (or any worktree)::

    python -I packages/fpl-grounded-assistant/scripts/replay_rank_condition_guard.py --ref origin/main --root C:/Users/thera/fpl-platform

Prints counts and the lists; writes nothing.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _p in [_HERE, _PKG] + sorted(glob.glob(os.path.join(_PKGS, "*"))):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401  (registers the tools)
from fpl_grounded_assistant import rank_condition_guard as guard  # noqa: E402
from fpl_tool_runner import run_tool  # noqa: E402

EMPTY = {"elements": [], "teams": [], "element_types": [], "events": []}
TOOL = "rank_players_by_metric"


def _git(*args: str, cwd: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd).decode("utf-8", "replace")


def _sources(repo: str, ref: str, root: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in _git("ls-tree", "-r", "--name-only", ref, cwd=repo).splitlines():
        if name.endswith((".jsonl", ".ndjson")):
            out.append((f"git:{name}", _git("show", f"{ref}:{name}", cwd=repo)))
    audit = "packages/fpl-grounded-assistant/audit_logs/*.ndjson"
    patterns = [
        r"C:/Users/thera/wt-jev-pilot/**/*.jsonl",
        os.path.join(root, ".worktrees", "*", audit),
        os.path.join(root, audit),
        r"C:/Users/thera/fpl-audit/*.ndjson",
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            if "node_modules" in path:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                out.append((path, fh.read()))
    return out


def _walk(obj, question, found):
    if isinstance(obj, dict):
        question = obj.get("question") or question
        name = obj.get("name") or obj.get("tool") or obj.get("tool_chosen") or obj.get("tool_name")
        args = obj.get("args") or obj.get("tool_args") or obj.get("input")
        if name == TOOL and isinstance(args, dict) and args.get("metric"):
            found.append((question or "", dict(args)))
        for value in obj.values():
            _walk(value, question, found)
    elif isinstance(obj, list):
        for value in obj:
            _walk(value, question, found)


def collect(repo: str, ref: str, root: str) -> list[tuple[str, dict, str]]:
    seen: set[str] = set()
    calls: list[tuple[str, dict, str]] = []
    for label, text in _sources(repo, ref, root):
        for line in text.splitlines():
            if TOOL not in line or line in seen:
                continue
            seen.add(line)
            try:
                record = json.loads(line)
            except ValueError:
                continue
            found: list[tuple[str, dict]] = []
            _walk(record, None, found)
            calls.extend((q, a, label) for q, a in found)
    return calls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--repo", default=os.getcwd(), help="a checkout to read <ref> from (git ls-tree / show)")
    ap.add_argument(
        "--root", default=None,
        help="the MAIN checkout that holds .worktrees and audit_logs (default: --repo). "
             "From a worktree this must be given, or the local audit logs are not found.",
    )
    ns = ap.parse_args()

    os.environ.pop("FPL_RANK_SUPPRESS", None)
    os.environ.pop("FPL_RANK_CONDITION_GUARD", None)
    calls = collect(ns.repo, ns.ref, ns.root or ns.repo)
    print(f"saved ranking calls: {len(calls)}; distinct questions: {len({q for q, _a, _s in calls})}")

    refused: dict[tuple[str, str], list] = collections.defaultdict(list)
    unchanged = 0
    for question, args, label in calls:
        before = run_tool(TOOL, dict(args), {**EMPTY, guard.OPT_OUT_KEY: True})
        after = run_tool(TOOL, dict(args), {**EMPTY, guard.QUESTION_KEY: question, guard.RAW_QUESTION_KEY: question})
        key = (question, str(args.get("metric")))
        if after.get("status") == guard.STATUS_CONDITION_NOT_APPLIED and before.get("status") != guard.STATUS_CONDITION_NOT_APPLIED:
            refused[key].append((label, after.get("conditions")))
        else:
            unchanged += 1

    print(f"unchanged calls: {unchanged}; refused (distinct question+metric): {len(refused)}; "
          f"distinct refused questions: {len({q for q, _m in refused})}")
    print("\n== refused, by distinct question (a refusal with a condition in the text is the intent) ==")
    for (question, metric), where in sorted(refused.items()):
        print(f"- {question!r} metric={metric!r} kinds={where[0][1]} calls={len(where)} e.g. {where[0][0]}")
    try:
        from tool_routing_corpus import CORPUS  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        print(f"\n(routing corpus not loadable: {exc})")
        return 0
    seen_q: set[str] = set()
    hits: list[tuple[str, tuple[str, ...], list[str]]] = []
    for entry in CORPUS:
        q = entry["question"]
        if q in seen_q:
            continue
        seen_q.add(q)
        kinds = guard.detect_conditions(q)
        if kinds:
            hits.append((q, kinds, entry.get("acceptable_tools") or []))
    print(f"\n== routing corpus: {len(seen_q)} distinct questions, detector fires on {len(hits)} ==")
    for q, kinds, tools in hits:
        mark = "RANKING-ELIGIBLE" if TOOL in tools else "other tool (guard only acts inside the ranking tool)"
        print(f"- {q!r} kinds={kinds} acceptable={tools} -> {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
