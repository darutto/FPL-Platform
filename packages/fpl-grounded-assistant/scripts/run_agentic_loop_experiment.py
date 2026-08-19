"""Run the four-arm agentic-loop experiment outside CI.

The driver launches one fresh worker process per observation so arm A imports
the baseline worktree and arms B/C/D import the treatment worktree. Set
``FPL_RUN_AGENTIC_EXPERIMENT=1`` explicitly; provider credentials are inherited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCENARIOS: dict[str, str] = {
    "Q6": (
        "\u00bfhay forma de que t\u00fa me des una respuesta de si el bench boost es una "
        "opci\u00f3n viable en la fecha uno armando un equipo desde cero basado en nuestras "
        "m\u00e9tricas de evaluaci\u00f3n de jugadores individualmente y de fixtures?"
    ),
    "Q7": (
        "Haaland es un lock in. As\u00ed es que mi presupuesto arranca con un -15.5. "
        "A partir de ah\u00ed creo que voy a jugar con una alineaci\u00f3n de 4-5-1 o de 5-4-1, "
        "quiero analizar los dos \u00e1ngulos. Empecemos con 4 medios con mejores 5 fechas "
        "y precio que permita el budget"
    ),
    "Q9": (
        "Adem\u00e1s de Haaland, \u00bfqui\u00e9nes son dos buenos delanteros para incluir en mi "
        "equipo para la fecha 1? Estoy indeciso entre jugadores muy baratos y elegir "
        "medios o defensas m\u00e1s caros o pagar un poco m\u00e1s por delanteros"
    ),
}

ARMS: dict[str, dict[str, str]] = {
    "A": {"label": "baseline", "loop": "0", "prompt": "0"},
    "B": {"label": "tools", "loop": "0", "prompt": "0"},
    "C": {"label": "loop", "loop": "1", "prompt": "0"},
    "D": {"label": "loop+prompt", "loop": "1", "prompt": "1"},
}

# Model-level table owned by this experiment. Operators may replace it with
# --pricing-json; the exact table used is printed in the artifact header.
DEFAULT_MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "cache_read": 0.15},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075},
}

SEMANTIC_RUBRICS: dict[str, str] = {
    "Q6": "Explains why the named bench makes Bench Boost viable or not.",
    "Q7": "Explains fixture discrimination, budget allocation, and at least one alternative.",
    "Q9": "Presents at least two price strategies and quantifies the budget difference.",
}


def _configure_imports(repo_root: Path) -> None:
    packages = repo_root / "packages"
    for package in packages.iterdir():
        if package.is_dir():
            sys.path.insert(0, str(package))


def _worker(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    _configure_imports(repo_root)
    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))

    from fpl_grounded_assistant.harness import _build_eval_client
    from fpl_grounded_assistant.orch_config import get_orch_model
    from fpl_grounded_assistant.orchestrator import ask_orchestrated
    from fpl_grounded_assistant.evaluator import _EVALUATOR_MODELS

    provider = args.provider
    model = get_orch_model(provider)
    key_name = "GOOGLE_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    api_key = os.environ.get(key_name)
    eval_client = _build_eval_client(provider, api_key=api_key)
    result = ask_orchestrated(
        SCENARIOS[args.scenario],
        bootstrap,
        provider=provider,
        model=model,
        api_key=api_key,
        max_tokens=4096,
        temperature=0.0,
        # Anthropic recommends changing temperature or top_p, not both. Gemini
        # accepts both controls, so pin top_p there for reproducibility.
        top_p=None if args.provider == "anthropic" else 1.0,
        _eval_client=eval_client,
    )
    verdict = asdict(result.evaluator_verdict) if result.evaluator_verdict is not None else None
    payload = {
        "provider": provider,
        "model": model,
        "evaluator_model": _EVALUATOR_MODELS.get(provider),
        "outcome": result.outcome,
        "answer_text": result.answer_text,
        "tool_chosen": result.tool_chosen,
        "tool_args": result.tool_args,
        "tool_output": result.tool_output,
        "tool_calls_trace": list(getattr(result, "tool_calls_trace", ())),
        "rounds_used": getattr(result, "rounds_used", 0),
        "rounds_exhausted": getattr(result, "rounds_exhausted", False),
        "primary_input_tokens": result.primary_input_tokens,
        "primary_output_tokens": result.primary_output_tokens,
        "primary_cache_read_tokens": result.primary_cache_read_tokens,
        "evaluator_tokens": result.evaluator_input_tokens + result.evaluator_output_tokens,
        "total_tokens": result.total_tokens,
        "evaluator_verdict": verdict,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _capture_bootstrap(target: Path) -> None:
    import requests

    response = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=30)
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    metadata = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": response.url,
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }
    target.with_suffix(target.suffix + ".meta.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )


def _load_semantic_scores(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _estimate_cost(observation: dict[str, Any], pricing: dict[str, dict[str, float]]) -> float | None:
    prices = pricing.get(observation["model"])
    if not prices:
        return None
    primary = (
        observation["primary_input_tokens"] * prices["input"]
        + observation["primary_output_tokens"] * prices["output"]
        + observation["primary_cache_read_tokens"] * prices.get("cache_read", prices["input"])
    ) / 1_000_000
    evaluator_prices = pricing.get(observation.get("evaluator_model"), prices)
    # evaluator.py currently exposes only combined tokens; charge them at the
    # output rate to keep the experiment estimate conservative.
    evaluator = observation["evaluator_tokens"] * evaluator_prices["output"] / 1_000_000
    return primary + evaluator


def _markdown_answer(text: str) -> str:
    escaped = (text or "").replace("|", "&#124;").replace("\n", "<br>")
    return f"<details><summary>answer</summary>{escaped}</details>"


def _render_artifact(
    observations: list[dict[str, Any]],
    *,
    bootstrap_path: Path,
    bootstrap_hash: str,
    captured_at: str,
    pricing: dict[str, dict[str, float]],
    repetitions: int,
) -> str:
    from fpl_grounded_assistant.experiment_measurement import summarize_axis2_by_source

    lines = [
        "# Agentic loop experiment results",
        "",
        "## Pinned configuration",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Bootstrap: `{bootstrap_path}`",
        f"- Bootstrap SHA-256: `{bootstrap_hash}`",
        f"- Bootstrap captured at: `{captured_at}`",
        "- Providers: `anthropic`, `gemini`",
        "- max_tokens: `4096`; temperature: `0.0`; Anthropic top_p omitted; Gemini top_p: `1.0`.",
        "- Anthropic decoding default not otherwise overridden: extended thinking off.",
        "- Gemini decoding default not otherwise overridden: thinking level `medium`.",
        "- Evaluator: same-provider cheapest model, verdict-only; no primary retry",
        "- FPL_ORCH_MAX_ROUNDS: `3` tool-execution rounds",
        f"- Repetitions per critical scenario/configuration: `{repetitions}`",
        "- Scope: direct `ask_orchestrated`; not an end-to-end UI/session test",
        "- Cost note: evaluator tokens are combined by the current API and conservatively charged at output price.",
        "- Price sources: https://platform.claude.com/docs/en/about-claude/pricing and https://ai.google.dev/gemini-api/docs/pricing",
        "",
        "### Model pricing used (USD per 1M tokens)",
        "",
        "```json",
        json.dumps(pricing, indent=2, sort_keys=True),
        "```",
        "",
        "## Three separate axes",
        "",
        "- Axis 1: user-visible catastrophic failure versus substantive answer.",
        "- Axis 2: deterministic legality; `structured_output_missing` is never treated as invalid.",
        "- Axis 2 is grouped by source. Raw-tool fallbacks never share a pass rate with model JSON; their bootstrap-synthesized price and arithmetic checks are non-comparable.",
        "- Axis 3: human semantic score using the scenario-specific rubric; legality is not a proxy.",
        "",
    ]

    lines.extend(["## Summary", "", "| Provider | Arm | Scenario | Catastrophic rate | Axis 2 | Human semantic | Avg rounds | Avg tokens | Avg USD |", "|---|---|---|---:|---|---|---:|---:|---:|"])
    for provider in ("anthropic", "gemini"):
        for arm in ARMS:
            for scenario in SCENARIOS:
                rows = [row for row in observations if row["provider"] == provider and row["arm"] == arm and row["scenario"] == scenario]
                catastrophic = sum(row["axis1"]["catastrophic_failure"] for row in rows)
                axis2_counts = summarize_axis2_by_source(rows)
                human_values = [row["axis3"].get("score") for row in rows if isinstance(row["axis3"].get("score"), (int, float))]
                human = f"{sum(human_values)/len(human_values):.2f}" if human_values else "pending"
                costs = [row["usd"] for row in rows if row["usd"] is not None]
                lines.append(
                    f"| {provider} | {arm} {ARMS[arm]['label']} | {scenario} | "
                    f"{catastrophic}/{len(rows)} | {json.dumps(axis2_counts)} | {human} | "
                    f"{sum(row['rounds_used'] for row in rows)/len(rows):.2f} | "
                    f"{sum(row['total_tokens'] for row in rows)/len(rows):.0f} | "
                    f"{sum(costs)/len(costs):.6f} |" if costs else
                    f"| {provider} | {arm} {ARMS[arm]['label']} | {scenario} | "
                    f"{catastrophic}/{len(rows)} | {json.dumps(axis2_counts)} | {human} | "
                    f"{sum(row['rounds_used'] for row in rows)/len(rows):.2f} | "
                    f"{sum(row['total_tokens'] for row in rows)/len(rows):.0f} | n/a |"
                )

    for provider in ("anthropic", "gemini"):
        lines.extend(["", f"## Answers: {provider}", ""])
        for scenario, question in SCENARIOS.items():
            lines.extend([f"### {scenario}", "", question, "", f"Human rubric: {SEMANTIC_RUBRICS[scenario]}", ""])
            for repetition in range(1, repetitions + 1):
                lines.extend([f"#### Repetition {repetition}", "", "| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |", "|---|---|---|---|---|---|---|---|"])
                for arm in ARMS:
                    row = next(item for item in observations if item["provider"] == provider and item["arm"] == arm and item["scenario"] == scenario and item["repetition"] == repetition)
                    tools = " \u2192 ".join(entry.get("name", "") for entry in row["tool_calls_trace"]) or (row.get("tool_chosen") or "none")
                    usd = "n/a" if row["usd"] is None else f"${row['usd']:.6f}"
                    lines.append(
                        f"| {arm} {ARMS[arm]['label']} | {row['outcome']} | {row['axis1']['classification']} | "
                        f"{row['axis2'].get('source') or 'none'} / {row['axis2']['status']} | {row['axis3'].get('score', 'pending')} | "
                        f"{row['rounds_used']} / {tools} | {row['total_tokens']} / {usd} | {_markdown_answer(row['answer_text'])} |"
                    )
                    if row["axis2"].get("errors"):
                        lines.append(f"\nAxis 2 errors ({arm}): `{json.dumps(row['axis2']['errors'])}`\n")
                    if row["axis2"].get("non_comparable_checks"):
                        lines.append(
                            f"\nAxis 2 non-comparable checks ({arm}): "
                            f"`{json.dumps(row['axis2']['non_comparable_checks'])}`\n"
                        )
    lines.extend([
        "",
        "## Decision gate",
        "",
        "Do not call this launch-ready, buy paid data, or collapse the arms into one headline. "
        "If C/D pass simple retrieval but fail legality or the human semantic rubrics for Q6/Q7/Q9, "
        "the next milestone is a decision-layer constraint solver, not Sportmonks.",
        "",
    ])
    return "\n".join(lines)


def _driver(args: argparse.Namespace) -> int:
    bootstrap_path = Path(args.bootstrap).resolve()
    if args.capture_only:
        _capture_bootstrap(bootstrap_path)
        print(f"captured {bootstrap_path}")
        return 0
    if os.environ.get("FPL_RUN_AGENTIC_EXPERIMENT", "").lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit("Set FPL_RUN_AGENTIC_EXPERIMENT=1 to run paid live calls.")

    script = Path(__file__).resolve()
    agentic_root = Path(args.agentic_root).resolve()
    baseline_root = Path(args.baseline_root).resolve()
    if args.capture_bootstrap:
        _capture_bootstrap(bootstrap_path)
    raw_bootstrap = bootstrap_path.read_bytes()
    bootstrap = json.loads(raw_bootstrap)
    bootstrap_hash = hashlib.sha256(raw_bootstrap).hexdigest()
    metadata_path = bootstrap_path.with_suffix(bootstrap_path.suffix + ".meta.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    captured_at = metadata.get("captured_at", "unknown")
    semantic_scores = _load_semantic_scores(args.semantic_scores)
    pricing = (
        json.loads(Path(args.pricing_json).read_text(encoding="utf-8"))
        if args.pricing_json else DEFAULT_MODEL_PRICING_PER_1M
    )

    haaland_ids = [
        int(player["id"])
        for player in bootstrap.get("elements", [])
        if str(player.get("web_name", "")).lower() == "haaland"
    ]
    if len(haaland_ids) != 1:
        raise SystemExit(f"Expected one Haaland in frozen bootstrap, found {haaland_ids}")

    _configure_imports(agentic_root)
    from fpl_grounded_assistant.experiment_measurement import (
        classify_user_visible,
        grade_structured_output,
    )

    observations: list[dict[str, Any]] = []
    for provider in ("anthropic", "gemini"):
        for arm, config in ARMS.items():
            worktree = baseline_root if arm == "A" else agentic_root
            for scenario in SCENARIOS:
                for repetition in range(1, args.repetitions + 1):
                    env = os.environ.copy()
                    env.update({
                        "FPL_ORCH_LOOP_ENABLED": config["loop"],
                        "FPL_ORCH_LOOP_PROMPT": config["prompt"],
                        "FPL_ORCH_MAX_ROUNDS": "3",
                        "FPL_ORCH_EVAL_VERDICT_ONLY": "1",
                        "FPL_ORCH_EXPERIMENT_OUTPUT": "1",
                    })
                    env.pop("FPL_EVAL_DISABLED", None)
                    completed = subprocess.run(
                        [
                            sys.executable, str(script), "--worker",
                            "--repo-root", str(worktree),
                            "--bootstrap", str(bootstrap_path),
                            "--provider", provider,
                            "--scenario", scenario,
                        ],
                        cwd=worktree,
                        env=env,
                        check=False,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    if completed.returncode:
                        result = {
                            "provider": provider,
                            "model": "unknown",
                            "evaluator_model": None,
                            "outcome": "worker_error",
                            "answer_text": completed.stderr[-2000:],
                            "tool_chosen": None,
                            "tool_args": {},
                            "tool_output": {},
                            "tool_calls_trace": [],
                            "rounds_used": 0,
                            "rounds_exhausted": False,
                            "primary_input_tokens": 0,
                            "primary_output_tokens": 0,
                            "primary_cache_read_tokens": 0,
                            "evaluator_tokens": 0,
                            "total_tokens": 0,
                            "evaluator_verdict": None,
                        }
                    else:
                        result = json.loads(completed.stdout.strip().splitlines()[-1])
                    result.update({"arm": arm, "scenario": scenario, "repetition": repetition})
                    result["axis1"] = classify_user_visible(
                        result["outcome"],
                        result["answer_text"],
                        result.get("tool_output"),
                    )
                    result["axis2"] = grade_structured_output(
                        scenario,
                        result["answer_text"],
                        result["tool_output"],
                        bootstrap,
                        haaland_ids if scenario in {"Q7", "Q9"} else [],
                    )
                    semantic_key = f"{provider}/{arm}/{scenario}/{repetition}"
                    result["axis3"] = semantic_scores.get(semantic_key, {
                        "score": "pending_human_review",
                        "rubric": SEMANTIC_RUBRICS[scenario],
                    })
                    result["usd"] = _estimate_cost(result, pricing)
                    observations.append(result)
                    print(f"completed {provider} arm={arm} {scenario} rep={repetition}", flush=True)

    artifact = _render_artifact(
        observations,
        bootstrap_path=bootstrap_path,
        bootstrap_hash=bootstrap_hash,
        captured_at=captured_at,
        pricing=pricing,
        repetitions=args.repetitions,
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(artifact, encoding="utf-8")
    output.with_suffix(".json").write_text(
        json.dumps(observations, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {output}")
    return 0


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_candidates = [
        repo_root / ".claude/worktrees/loop-baseline",
        *(parent / ".claude/worktrees/loop-baseline" for parent in repo_root.parents),
    ]
    baseline_default = next(
        (candidate for candidate in baseline_candidates if candidate.exists()),
        baseline_candidates[0],
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--repo-root", default=str(repo_root))
    parser.add_argument("--agentic-root", default=str(repo_root))
    parser.add_argument("--baseline-root", default=str(baseline_default))
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--capture-bootstrap", action="store_true")
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--provider", choices=("anthropic", "gemini"))
    parser.add_argument("--scenario", choices=tuple(SCENARIOS))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--semantic-scores")
    parser.add_argument("--pricing-json")
    parser.add_argument("--output", default=str(repo_root / "field-notes/2026-08-18-agentic-loop-experiment.md"))
    return parser


if __name__ == "__main__":
    parsed = _parser().parse_args()
    raise SystemExit(_worker(parsed) if parsed.worker else _driver(parsed))
