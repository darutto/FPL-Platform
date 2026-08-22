#!/usr/bin/env python3
"""Render experiment observations as a readable question/answer document for Axis 3.

The experiment artifact packs each answer into a <details> block inside a markdown
table cell, with newlines flattened to <br>. That is fine for machine diffing and
unreadable for a human scoring answer quality. This renders the same observations
as plain prose, grouped by scenario, with each answer under its own heading.

Emits two files:
  <out>.md    the reading document
  <out>.scores.json  a pre-keyed template to fill in, consumable by
                     run_agentic_loop_experiment.py --semantic-scores

Usage:
  python render_axis3_review.py --input ../../../field-notes/RUN.json \
      --arms B --scenarios Q10,Q11 --reps 1 --out ../../../field-notes/axis3-review
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCENARIO_TEXT: dict[str, str] = {}
RUBRICS: dict[str, str] = {}


def _load(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in paths:
        rows.extend(json.loads(Path(p).read_text(encoding="utf-8")))
    return rows


def _csv(value: str | None) -> set[str] | None:
    return {v.strip() for v in value.split(",")} if value else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", required=True,
                    help="observations .json (repeatable, to compare providers across runs)")
    ap.add_argument("--arms")
    ap.add_argument("--providers")
    ap.add_argument("--scenarios")
    ap.add_argument("--reps", help="comma-separated repetition numbers, e.g. 1 or 1,2")
    ap.add_argument("--out", required=True, help="output path WITHOUT extension")
    args = ap.parse_args()

    # Scenario text and rubrics live in the driver; import lazily so this script
    # stays usable even if that module grows heavier dependencies.
    import run_agentic_loop_experiment as drv

    rows = _load(args.input)
    arms, provs = _csv(args.arms), _csv(args.providers)
    scens, reps = _csv(args.scenarios), _csv(args.reps)

    def keep(r: dict[str, Any]) -> bool:
        return (
            (arms is None or r["arm"] in arms)
            and (provs is None or r["provider"] in provs)
            and (scens is None or r["scenario"] in scens)
            and (reps is None or str(r["repetition"]) in reps)
        )

    rows = [r for r in rows if keep(r)]
    if not rows:
        raise SystemExit("no observations matched the filters")

    order = {s: i for i, s in enumerate(drv.SCENARIOS)}
    rows.sort(key=lambda r: (order.get(r["scenario"], 99), r["scenario"],
                             r["provider"], r["arm"], r["repetition"]))

    lines: list[str] = [
        "# Axis 3 — lectura y puntuación humana",
        "",
        "Cada respuesta va completa y sin escapar. Puntúa contra la rúbrica de su "
        "escena y anota el resultado en el `.scores.json` que acompaña a este archivo.",
        "",
        "Axis 3 mide **si la respuesta contesta lo que se preguntó**, no si es legal "
        "ni si evitó fallar. Una respuesta puede ser válida y aun así inútil.",
        "",
        f"Observaciones: **{len(rows)}**",
        "",
        "---",
        "",
    ]

    current = None
    for r in rows:
        sc = r["scenario"]
        if sc != current:
            current = sc
            lines += [
                f"## {sc}", "",
                "**Pregunta**", "",
                f"> {drv.SCENARIOS[sc]}", "",
                "**Rúbrica**", "",
                f"> {drv.SEMANTIC_RUBRICS[sc]}", "",
                "---", "",
            ]
        model = r.get("model") or r["provider"]
        key = f'{r["provider"]}/{r["arm"]}/{sc}/{r["repetition"]}'
        tools = " → ".join(t.get("name", "") for t in r.get("tool_calls_trace") or []) \
            or (r.get("tool_chosen") or "ninguna")
        usd = r.get("usd")
        lines += [
            f'### `{key}`',
            "",
            f'- modelo: `{model}` · brazo {r["arm"]} · repetición {r["repetition"]}',
            f'- outcome: `{r["outcome"]}` · rondas: {r.get("rounds_used", 0)}'
            f' · tokens: {r.get("total_tokens", 0)}'
            + (f' · ${usd:.5f}' if isinstance(usd, (int, float)) else ""),
            f'- herramientas: `{tools}`',
            "",
            "**Respuesta**", "",
            (r.get("answer_text") or "_(vacía)_").strip(),
            "",
            "---",
            "",
        ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")

    template = {
        f'{r["provider"]}/{r["arm"]}/{r["scenario"]}/{r["repetition"]}':
            {"score": None, "rubric": drv.SEMANTIC_RUBRICS[r["scenario"]], "notes": ""}
        for r in rows
    }
    out.with_suffix(".scores.json").write_text(
        json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {out.with_suffix('.md')} ({len(rows)} observations)")
    print(f"wrote {out.with_suffix('.scores.json')} (template, score=null)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
