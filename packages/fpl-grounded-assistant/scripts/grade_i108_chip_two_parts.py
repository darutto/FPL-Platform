"""i108 E3 gate grader: does a chip answer open GENERAL and then say the PARTICULAR?

Reads the JSONL written by ``measure_tool_routing.py`` (with the i108 E3
fields ``answer_text_full`` and ``chip_trace``) and grades every row from the
answer text against the chip output the call actually executed -- never from
the question.

Decision rule (declared before measuring, agreed in review)
-----------------------------------------------------------
Denominator: rows whose trace ran ``get_chip_advice`` with status ok for a
chip in ``SQUAD_FIT_CHIPS`` (bench_boost / wildcard / free_hit) and for which
``particular_outcome`` is defined. Everything else is reported apart, with its
reason, never as a failure: triple captain (no particular part yet -- open
question), no chip call (a routing gap), members known but no fit computable.

A denominator row passes when all three hold:
* part 1 -- the opening (leading heading line(s) + first paragraph; the
  strict first-paragraph-only count is reported too) carries the verdict label for the output's
  ``recommendation`` (``GENERAL_VERDICT_LABEL``) and, when the favoured group
  is not empty, a favoured team (short code or full name, by the id the tool
  returned) or player is named before the particular phrase;
* part 2 -- the exact ``particular_phrase`` for the output appears;
* order -- the verdict label comes before the particular phrase.

Also reported: transaction words (``opportunity_framing.transaction_hits``,
must be 0) and forbidden openings ("no puedo evaluar tu equipo").

Usage::

    python scripts/grade_i108_chip_two_parts.py ARM.jsonl [ARM2.jsonl ...] \\
        [--bootstrap field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json] \\
        [--threshold 0.95]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
# Same import setup as measure_tool_routing.py: every packages/* dir.
for _pkg in sorted((REPO_ROOT / "packages").iterdir()):
    if _pkg.is_dir() and str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

from fpl_grounded_assistant.chip_two_part import (  # noqa: E402
    FORBIDDEN_OPENINGS,
    GENERAL_VERDICT_LABEL,
    SQUAD_FIT_CHIPS,
    first_paragraph,
    fold,
    opening,
    particular_outcome,
    particular_phrase,
)
from fpl_grounded_assistant.opportunity_framing import transaction_hits  # noqa: E402

# Same default as measure_tool_routing.py.
DEFAULT_BOOTSTRAP = REPO_ROOT / "field-notes" / "artifacts" / "agentic-loop-bootstrap-2026-08-18.json"


def team_names(bootstrap: dict[str, Any]) -> dict[int, list[str]]:
    """team id -> the names a reader may use for it (short code, full name)."""
    names: dict[int, list[str]] = {}
    for t in bootstrap.get("teams", []) or []:
        if t.get("id") is None:
            continue
        names[int(t["id"])] = [n for n in (t.get("short_name"), t.get("name")) if n]
    return names


def grade_row(row: dict[str, Any], names_by_team: dict[int, list[str]]) -> dict[str, Any]:
    """Grade one observation. ``bucket`` says whether it is in the denominator."""
    chip = row.get("chip_trace")
    text = row.get("answer_text_full") or row.get("answer_text") or ""
    folded = fold(text)
    opening_f = fold(opening(text))
    strict_opening_f = fold(first_paragraph(text))
    out: dict[str, Any] = {
        "question_id": row.get("question_id"),
        "rep": row.get("rep"),
        "team_id_present": row.get("team_id_present"),
        "transaction_hits": transaction_hits(text),
        "forbidden_opening": any(fold(p) in opening_f for p in FORBIDDEN_OPENINGS),
    }
    if not isinstance(chip, dict):
        return {**out, "bucket": "no_chip_call"}
    if chip.get("status") != "ok":
        return {**out, "bucket": "chip_not_ok"}
    if chip.get("chip") not in SQUAD_FIT_CHIPS:
        return {**out, "bucket": f"chip_{chip.get('chip')}"}
    outcome = particular_outcome(chip)
    if outcome is None:
        return {**out, "bucket": "no_fit_computable"}

    label = GENERAL_VERDICT_LABEL.get(chip.get("recommendation") or "")
    phrase = particular_phrase(chip) or ""
    label_f, phrase_f = fold(label or ""), fold(phrase)
    label_at = folded.find(label_f) if label_f else -1
    phrase_at = folded.find(phrase_f) if phrase_f else -1

    candidates: list[str] = []
    for t in chip.get("favoured_teams") or []:
        if isinstance(t.get("team"), int):
            candidates += names_by_team.get(t["team"], [])
        if t.get("team_short"):
            candidates.append(t["team_short"])
    candidates += [p.get("web_name") for p in chip.get("favoured_players") or [] if p.get("web_name")]
    horizon = phrase_at if phrase_at >= 0 else len(folded)
    group_named = (not candidates) or any(
        0 <= folded.find(fold(c)) < horizon for c in candidates
    )

    part1 = bool(label_f) and label_f in opening_f and group_named
    part1_strict = bool(label_f) and label_f in strict_opening_f and group_named
    part2 = phrase_at >= 0
    order = label_at >= 0 and phrase_at >= 0 and label_at < phrase_at
    return {
        **out,
        "bucket": "denominator",
        "chip": chip.get("chip"),
        "outcome": outcome,
        "part1": part1,
        "part2": part2,
        "order": order,
        "pass": part1 and part2 and order,
        # The pre-fix definition (first paragraph only, heading = paragraph).
        "pass_strict_opening": part1_strict and part2 and order,
    }


def grade_file(path: Path, names_by_team: dict[int, list[str]]) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [grade_row(r, names_by_team) for r in rows]


def summarize(graded: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    den = [g for g in graded if g["bucket"] == "denominator"]
    passed = sum(g["pass"] for g in den)
    return {
        "rows": len(graded),
        "denominator": len(den),
        "pass": passed,
        "pass_strict_opening": sum(g["pass_strict_opening"] for g in den),
        "part1": sum(g["part1"] for g in den),
        "part2": sum(g["part2"] for g in den),
        "order": sum(g["order"] for g in den),
        "outcomes": dict(Counter(g["outcome"] for g in den)),
        "apart": dict(Counter(g["bucket"] for g in graded if g["bucket"] != "denominator")),
        # The framing condition is on the chip answers (the denominator);
        # rows outside it are counted apart (e.g. a question that itself says
        # "transfer" and never ran the chip tool).
        "transaction_hit_rows": sum(bool(g["transaction_hits"]) for g in den),
        "transaction_hit_rows_apart": sum(
            bool(g["transaction_hits"]) for g in graded if g["bucket"] != "denominator"
        ),
        "forbidden_openings": sum(g["forbidden_opening"] for g in graded),
        "gate": bool(den) and passed / len(den) >= threshold,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", nargs="+")
    parser.add_argument("--bootstrap", default=str(DEFAULT_BOOTSTRAP))
    parser.add_argument("--threshold", type=float, default=0.95)
    args = parser.parse_args(argv)

    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    bootstrap = bootstrap.get("bootstrap", bootstrap)
    names = team_names(bootstrap)
    ok = True
    for path in args.jsonl:
        graded = grade_file(Path(path), names)
        summary = summarize(graded, args.threshold)
        ok = ok and summary["gate"] and summary["transaction_hit_rows"] == 0 and summary["forbidden_openings"] == 0
        print(f"== {path}")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        print("| id | rep | bucket | outcome | part1 | part2 | order | pass | tx hits |")
        print("|---|---|---|---|---|---|---|---|---|")
        for g in graded:
            print(
                f"| {g['question_id']} | {g['rep']} | {g['bucket']} | {g.get('outcome', '')} | "
                f"{g.get('part1', '')} | {g.get('part2', '')} | {g.get('order', '')} | "
                f"{g.get('pass', '')} | {len(g['transaction_hits'])} |"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
