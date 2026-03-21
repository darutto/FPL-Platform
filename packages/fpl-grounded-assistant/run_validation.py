"""
run_validation.py
=================
Phase V1: Cross-Surface Smoke Runner.

Exercises the frozen validation corpus (validation_corpus.py) across
CLI, stateless HTTP, and session surfaces.  Produces two artifacts:

    validation_results.json  — machine-readable per-scenario results
    validation_report.md     — human-readable summary and scenario table

Exit codes
----------
0   All scenarios passed.
1   One or more scenarios failed.

Usage::

    cd packages/fpl-grounded-assistant
    python run_validation.py

    # Suppress artifact writes (useful when called from the test runner):
    python run_validation.py --no-artifacts

Surfaces exercised per scenario
--------------------------------
cli           → fpl_cli.run()
http          → POST /ask via FastAPI TestClient
session_cli   → fpl_cli.run_session() (supports resolver stub)
session_http  → POST /session/{id}/ask via TestClient (deterministic only)

LLM stub protocol
-----------------
Scenarios that require ``requires_stub="comp_llm"`` or ``"ref_llm"`` pass a
pre-built stub client to ``run_session(resolver_client=...)``.  The stub
mimics the ``anthropic.Anthropic`` interface well enough to satisfy the
resolver without any network call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
_SIB  = lambda name: os.path.join(_PKGS, name)
for _pkg in [
    _HERE,
    _SIB("fpl-api-client"),
    _SIB("fpl-data-core"),
    _SIB("fpl-player-registry"),
    _SIB("fpl-query-tools"),
    _SIB("fpl-tool-contract"),
    _SIB("fpl-tool-runner"),
    _SIB("fpl-captain-engine"),
    _SIB("fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)


# ---------------------------------------------------------------------------
# Imports (after sys.path setup)
# ---------------------------------------------------------------------------

from validation_corpus import VALIDATION_SCENARIOS, ValidationScenario  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import (               # noqa: E402
    STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP,
)
from fpl_cli import run as cli_run, run_session as cli_run_session       # noqa: E402
import fpl_server                                                          # noqa: E402
from fastapi.testclient import TestClient                                  # noqa: E402


# ---------------------------------------------------------------------------
# LLM stubs
# ---------------------------------------------------------------------------

class _StubBlock:
    """Mimics a single Anthropic content block."""
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMessage:
    """Mimics an Anthropic API response message."""
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    """Mimics anthropic.Anthropic().messages."""
    def __init__(self, response_json: str) -> None:
        self._response_json = response_json

    def create(self, **kwargs: Any) -> _StubMessage:  # noqa: ANN401
        return _StubMessage(self._response_json)


class _StubAnthropicClient:
    """Minimal stub that satisfies the resolver client interface.

    Used in place of ``anthropic.Anthropic()`` so that LLM-assisted
    resolver paths can be exercised without any network call.
    """
    def __init__(self, response_json: str) -> None:
        self.messages = _StubMessages(response_json)


# Fixed stub responses for the two LLM resolver paths.

COMP_LLM_STUB = _StubAnthropicClient(
    '{"is_comparison_followup": true, "new_player": "Saka", '
    '"confidence": 0.95, "language": "es"}'
)
"""Phase 5f comparison follow-up stub.

Returns: is_comparison_followup=true, new_player='Saka', confidence=0.95.
Expected rewritten question: 'compare Haaland and Saka'.
"""

REF_LLM_STUB = _StubAnthropicClient(
    '{"resolved_query": "Salah", "intent_guess": "captain_score", '
    '"reference_source": "pronoun", "confidence": 0.9, "language": "es"}'
)
"""Phase 4f reference resolver stub.

Returns: resolved_query='Salah', intent_guess='captain_score', confidence=0.9.
Expected rewritten question: 'should I captain Salah'.
"""

_STUB_MAP: dict[str, _StubAnthropicClient] = {
    "comp_llm": COMP_LLM_STUB,
    "ref_llm":  REF_LLM_STUB,
}


# ---------------------------------------------------------------------------
# Bootstrap resolver
# ---------------------------------------------------------------------------

def _resolve_bootstrap(name: str) -> dict[str, Any]:
    if name == "ambiguous":
        return AMBIGUOUS_BOOTSTRAP
    return STANDARD_BOOTSTRAP


# ---------------------------------------------------------------------------
# Per-surface runners
# ---------------------------------------------------------------------------

def run_cli_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via ``fpl_cli.run()`` and return a result dict."""
    candidates = list(scenario.candidates_list) if scenario.candidates_list else None
    exit_code, output_text = cli_run(
        scenario.question,
        bootstrap,
        debug=False,
        candidates_list=candidates,
    )
    # Also run with debug=True to access structured fields
    _, debug_output = cli_run(
        scenario.question,
        bootstrap,
        debug=True,
        candidates_list=candidates,
    )
    debug_body: dict[str, Any] = {}
    try:
        debug_body = json.loads(debug_output)
    except json.JSONDecodeError:
        pass

    return {
        "surface":         "cli",
        "exit_code":       exit_code,
        "intent":          debug_body.get("intent"),
        "outcome":         debug_body.get("outcome"),
        "supported":       debug_body.get("supported"),
        "captain":         debug_body.get("captain"),
        "comparison":      debug_body.get("comparison"),
        "captain_ranking": debug_body.get("captain_ranking"),
        "final_text":      debug_body.get("final_text", output_text),
    }


def run_http_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via POST /ask (TestClient) and return a result dict."""
    fpl_server._init_bootstrap(bootstrap)
    client = TestClient(fpl_server.app, raise_server_exceptions=True)

    payload: dict[str, Any] = {"question": scenario.question}
    if scenario.candidates_list:
        payload["candidates_list"] = list(scenario.candidates_list)

    resp = client.post("/ask", json=payload)
    body: dict[str, Any] = {}
    try:
        body = resp.json()
    except Exception:
        pass

    return {
        "surface":         "http",
        "http_status":     resp.status_code,
        "intent":          body.get("intent"),
        "outcome":         body.get("outcome"),
        "supported":       body.get("supported"),
        "captain":         body.get("captain"),
        "comparison":      body.get("comparison"),
        "captain_ranking": body.get("captain_ranking"),
        "final_text":      body.get("final_text", ""),
    }


def run_session_cli_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via ``fpl_cli.run_session()`` and return a result dict
    for the *final* turn.

    Passes ``resolver_client`` when the scenario requires a stub.
    Passes ``debug=True`` to capture resolver metadata.
    """
    resolver_client = _STUB_MAP.get(scenario.requires_stub or "")
    candidates = list(scenario.candidates_list) if scenario.candidates_list else None

    questions = list(scenario.session_prior_turns) + [scenario.question]
    turns = cli_run_session(
        questions,
        bootstrap,
        debug=True,
        resolver_client=resolver_client,
        candidates_list=candidates,
    )

    last: dict[str, Any] = turns[-1] if turns else {}
    debug_bundle  = last.get("debug") or {}
    resolver_dbg  = debug_bundle.get("resolver") or {}

    return {
        "surface":          "session_cli",
        "intent":           last.get("intent"),
        "outcome":          last.get("outcome"),
        "supported":        last.get("supported"),
        "captain":          last.get("captain"),
        "comparison":       last.get("comparison"),
        "captain_ranking":  last.get("captain_ranking"),
        "final_text":       last.get("final_text", ""),
        "resolver_source":  resolver_dbg.get("resolver_source"),
        "rewritten_question": resolver_dbg.get("rewritten_question"),
    }


def run_session_http_surface(
    scenario: ValidationScenario,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Run the scenario via the HTTP session API (TestClient) and return a
    result dict for the *final* turn.

    Note: the HTTP session endpoint has no resolver_client parameter.
    LLM stub scenarios should NOT be in the session_http surface list.
    """
    fpl_server._init_bootstrap(bootstrap)
    fpl_server._clear_sessions()
    client = TestClient(fpl_server.app, raise_server_exceptions=True)

    create_resp = client.post("/session")
    if create_resp.status_code != 200:
        return {"surface": "session_http", "error": f"create failed: {create_resp.status_code}"}

    session_id = create_resp.json()["session_id"]
    last_body: dict[str, Any] = {}

    all_turns = list(scenario.session_prior_turns) + [scenario.question]
    for turn_q in all_turns:
        ask_payload: dict[str, Any] = {"question": turn_q}
        if scenario.candidates_list:
            ask_payload["candidates_list"] = list(scenario.candidates_list)
        r = client.post(f"/session/{session_id}/ask", json=ask_payload)
        if r.status_code == 200:
            last_body = r.json()

    client.delete(f"/session/{session_id}")

    return {
        "surface":          "session_http",
        "intent":           last_body.get("intent"),
        "outcome":          last_body.get("outcome"),
        "supported":        last_body.get("supported"),
        "captain":          last_body.get("captain"),
        "comparison":       last_body.get("comparison"),
        "captain_ranking":  last_body.get("captain_ranking"),
        "final_text":       last_body.get("final_text", ""),
    }


# ---------------------------------------------------------------------------
# Per-surface dispatcher
# ---------------------------------------------------------------------------

_SURFACE_RUNNERS = {
    "cli":          run_cli_surface,
    "http":         run_http_surface,
    "session_cli":  run_session_cli_surface,
    "session_http": run_session_http_surface,
}


# ---------------------------------------------------------------------------
# Assertion checker
# ---------------------------------------------------------------------------

def _check_scenario_result(
    scenario: ValidationScenario,
    surface_name: str,
    sr: dict[str, Any],
) -> list[str]:
    """Return a list of failure strings (empty == all passed)."""
    failures: list[str] = []

    def fail(msg: str) -> None:
        failures.append(f"[{surface_name}] {msg}")

    # Core contract
    if sr.get("intent") != scenario.expected_intent:
        fail(f"intent: expected={scenario.expected_intent!r}, got={sr.get('intent')!r}")
    if sr.get("outcome") != scenario.expected_outcome:
        fail(f"outcome: expected={scenario.expected_outcome!r}, got={sr.get('outcome')!r}")
    if sr.get("supported") is not scenario.expected_supported:
        fail(f"supported: expected={scenario.expected_supported}, got={sr.get('supported')}")

    # Structured field presence
    if scenario.expect_captain:
        if sr.get("captain") is None:
            fail("captain: expected non-None, got None")
        else:
            cap = sr["captain"]
            if cap.get("tier") not in ("safe", "upside", "differential", "avoid", "low_confidence"):
                fail(f"captain.tier: unexpected value {cap.get('tier')!r}")
    else:
        # For non-captain-score intents, captain should be None/absent
        if scenario.expected_intent != "captain_score" and sr.get("captain") is not None:
            fail("captain: expected None for non-captain turn")

    if scenario.expect_comparison:
        if sr.get("comparison") is None:
            fail("comparison: expected non-None, got None")
        else:
            cmp = sr["comparison"]
            if "winner" not in cmp:
                fail("comparison: missing 'winner' key")
            if "margin" not in cmp:
                fail("comparison: missing 'margin' key")
    else:
        if scenario.expected_intent != "compare_players" and sr.get("comparison") is not None:
            fail("comparison: expected None for non-comparison turn")

    if scenario.expect_captain_ranking:
        cr = sr.get("captain_ranking")
        if cr is None:
            fail("captain_ranking: expected non-None, got None")
        elif not isinstance(cr, list):
            fail(f"captain_ranking: expected list, got {type(cr).__name__}")
        elif len(cr) == 0:
            fail("captain_ranking: expected non-empty list")
        elif cr[0].get("rank") != 1:
            fail(f"captain_ranking[0].rank: expected 1, got {cr[0].get('rank')}")

    # Resolver source (session_cli only)
    if surface_name == "session_cli" and scenario.expected_resolver_source is not None:
        got_src = sr.get("resolver_source")
        if got_src != scenario.expected_resolver_source:
            fail(f"resolver_source: expected={scenario.expected_resolver_source!r}, got={got_src!r}")

    return failures


# ---------------------------------------------------------------------------
# Cross-surface parity check
# ---------------------------------------------------------------------------

def _check_cross_surface_parity(
    results_by_surface: dict[str, dict[str, Any]],
) -> list[str]:
    """Check that intent/outcome/supported agree across all surfaces."""
    failures: list[str] = []
    surfaces = list(results_by_surface.keys())
    if len(surfaces) < 2:
        return failures

    ref_name = surfaces[0]
    ref = results_by_surface[ref_name]
    for other_name in surfaces[1:]:
        other = results_by_surface[other_name]
        for field in ("intent", "outcome", "supported"):
            rv = ref.get(field)
            ov = other.get(field)
            if rv != ov:
                failures.append(
                    f"parity [{ref_name} vs {other_name}] {field}: "
                    f"{rv!r} != {ov!r}"
                )
    return failures


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_all_scenarios() -> list[dict[str, Any]]:
    """Execute all scenarios and return structured results."""
    results: list[dict[str, Any]] = []

    for scenario in VALIDATION_SCENARIOS:
        bootstrap = _resolve_bootstrap(scenario.bootstrap)
        surface_results: dict[str, dict[str, Any]] = {}
        all_failures: list[str] = []

        for surface_name in scenario.surfaces:
            runner = _SURFACE_RUNNERS.get(surface_name)
            if runner is None:
                all_failures.append(f"Unknown surface: {surface_name}")
                continue
            sr = runner(scenario, bootstrap)
            surface_results[surface_name] = sr
            all_failures.extend(_check_scenario_result(scenario, surface_name, sr))

        # Cross-surface parity
        parity_failures = _check_cross_surface_parity(surface_results)
        all_failures.extend(parity_failures)

        passed = len(all_failures) == 0
        results.append({
            "id":               scenario.id,
            "family":           scenario.family,
            "description":      scenario.description,
            "question":         scenario.question,
            "surfaces_tested":  list(scenario.surfaces),
            "surface_results":  surface_results,
            "expected": {
                "intent":    scenario.expected_intent,
                "outcome":   scenario.expected_outcome,
                "supported": scenario.expected_supported,
            },
            "failures":         all_failures,
            "pass":             passed,
            "notes":            scenario.notes,
        })

    return results


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------

def write_json_artifact(results: list[dict[str, Any]], path: str) -> None:
    """Write machine-readable results to JSON."""
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    artifact = {
        "run_at":         datetime.now(tz=timezone.utc).isoformat(),
        "scenario_count": total,
        "pass_count":     passed,
        "fail_count":     total - passed,
        "scenarios":      results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)


def write_markdown_artifact(results: list[dict[str, Any]], path: str) -> None:
    """Write human-readable Markdown validation report."""
    total  = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed

    lines: list[str] = []
    lines.append("# FPL Grounded Assistant — Validation Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **{total} scenarios** tested")
    lines.append(f"- **{passed} PASS**, **{failed} FAIL**")
    lines.append("")

    # Overview table
    lines.append("## Scenario Overview")
    lines.append("")
    lines.append("| ID | Family | Intent | Outcome | Surfaces | Status |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        status  = "✓ PASS" if r["pass"] else "✗ FAIL"
        surfaces = ", ".join(r["surfaces_tested"])
        exp      = r["expected"]
        lines.append(
            f"| {r['id']} | {r['family']} | {exp['intent']} "
            f"| {exp['outcome']} | {surfaces} | {status} |"
        )

    lines.append("")
    lines.append("## Scenario Details")
    lines.append("")

    for r in results:
        status = "✓ PASS" if r["pass"] else "✗ FAIL"
        lines.append(f"### {r['id']}  ({status})")
        lines.append("")
        lines.append(f"**Family:** {r['family']}  ")
        lines.append(f"**Description:** {r['description']}  ")
        lines.append(f"**Question:** `{r['question']}`  ")
        lines.append(f"**Expected:** intent=`{r['expected']['intent']}` "
                     f"outcome=`{r['expected']['outcome']}` "
                     f"supported=`{r['expected']['supported']}`  ")
        lines.append(f"**Notes:** {r['notes']}")
        lines.append("")

        # Per-surface result
        if r["surface_results"]:
            lines.append("**Surface results:**")
            lines.append("")
            for surf_name, sr in r["surface_results"].items():
                lines.append(f"- `{surf_name}`: "
                              f"intent=`{sr.get('intent')}` "
                              f"outcome=`{sr.get('outcome')}` "
                              f"supported=`{sr.get('supported')}`")
                if surf_name == "session_cli" and sr.get("resolver_source"):
                    lines.append(f"  resolver_source=`{sr.get('resolver_source')}`")
                    if sr.get("rewritten_question"):
                        lines.append(f"  rewritten=`{sr.get('rewritten_question')}`")
                captain_info = sr.get("captain")
                if captain_info:
                    lines.append(f"  captain.tier=`{captain_info.get('tier')}` "
                                  f"captain.role_bonus=`{captain_info.get('role_bonus')}`")
                ranking_info = sr.get("captain_ranking")
                if ranking_info:
                    lines.append(f"  captain_ranking: {len(ranking_info)} entries, "
                                  f"#1={ranking_info[0].get('web_name') if ranking_info else '?'}")
                comparison_info = sr.get("comparison")
                if comparison_info:
                    lines.append(f"  comparison.winner=`{comparison_info.get('winner')}` "
                                  f"comparison.label=`{comparison_info.get('label')}`")
            lines.append("")

        # Failures
        if r["failures"]:
            lines.append("**Failures:**")
            lines.append("")
            for f_msg in r["failures"]:
                lines.append(f"- {f_msg}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `run_validation.py` — "
        "FPL Grounded Assistant Phase V1 validation corpus._"
    )

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run all scenarios, write artifacts, return exit code."""
    parser = argparse.ArgumentParser(prog="run_validation")
    parser.add_argument(
        "--no-artifacts",
        action="store_true",
        default=False,
        help="Skip writing JSON/Markdown output files.",
    )
    args = parser.parse_args(argv)

    results = run_all_scenarios()

    total  = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"Validation: {passed}/{total} scenarios PASS")
    if failed:
        print(f"FAILED scenarios:")
        for r in results:
            if not r["pass"]:
                print(f"  ✗ {r['id']}")
                for f_msg in r["failures"]:
                    print(f"    {f_msg}")
    print(f"{'='*60}\n")

    if not args.no_artifacts:
        json_path = os.path.join(_HERE, "validation_results.json")
        md_path   = os.path.join(_HERE, "validation_report.md")
        write_json_artifact(results, json_path)
        write_markdown_artifact(results, md_path)
        print(f"Artifacts written:")
        print(f"  {json_path}")
        print(f"  {md_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
