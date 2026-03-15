"""
fpl_cli — thin CLI entrypoint for the FPL grounded assistant.

Phase 4b: thin external interface.

Wraps ``respond()`` behind a single-question CLI.  The bootstrap is assembled
live via ``assemble_captain_context()``.  No internal modules need to be touched
by the caller.

Usage
-----
    python fpl_cli.py "should I captain Haaland"
    python fpl_cli.py "should I captain Haaland" --debug

Exit codes
----------
0   Supported intent -- question was answered
1   Unsupported intent -- question is outside the assistant's scope
2   Unexpected error (should not occur -- respond() never raises)
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from fpl_grounded_assistant import respond, FinalResponse
from fpl_pipeline import assemble_captain_context


# ---------------------------------------------------------------------------
# Core logic  (separated from arg parsing for testability)
# ---------------------------------------------------------------------------

def run(
    question: str,
    bootstrap: dict[str, Any],
    *,
    debug: bool = False,
) -> tuple[int, str]:
    """Run ``respond()`` with an injected bootstrap and return ``(exit_code, output)``.

    Parameters
    ----------
    question:
        Raw user question.
    bootstrap:
        FPL bootstrap dict (typically ``assemble_captain_context()["bootstrap"]``).
    debug:
        When ``True``, output is a JSON string containing all ``FinalResponse``
        fields plus the debug bundle.  When ``False``, output is ``final_text``
        only.

    Returns
    -------
    (exit_code, output)
        exit_code: 0 if ``supported=True``, 1 if ``supported=False``
        output:    string to print to stdout
    """
    r: FinalResponse = respond(question, bootstrap, include_debug=debug)

    if debug:
        payload: dict[str, Any] = {
            "final_text":    r.final_text,
            "outcome":       r.outcome,
            "supported":     r.supported,
            "intent":        r.intent,
            "review_passed": r.review_passed,
            "llm_used":      r.llm_used,
        }
        if r.debug is not None:
            payload["debug"] = {
                "response_text": r.debug.response_text,
                "llm_text":      r.debug.llm_text,
                "violations":    list(r.debug.violations),
                "prompt_used":   r.debug.prompt_used,
                "model":         r.debug.model,
            }
        output = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        output = r.final_text

    exit_code = 0 if r.supported else 1
    return exit_code, output


# ---------------------------------------------------------------------------
# Multi-turn session runner
# ---------------------------------------------------------------------------

def run_session(
    questions: list[str],
    bootstrap: dict[str, Any],
    *,
    debug: bool = False,
    resolver_client: Any = None,
) -> list[dict[str, Any]]:
    """Run a list of questions through a ConversationSession.

    Uses ``ConversationSession`` internally so pronoun and reference
    follow-ups are resolved across turns.

    Parameters
    ----------
    questions:
        Ordered list of user questions for this session.
    bootstrap:
        FPL bootstrap dict.
    debug:
        When ``True``, each result dict includes a ``debug`` key with the
        full ``FinalResponseDebug`` bundle including resolver metadata.
    resolver_client:
        Optional Anthropic client for Phase 4f LLM reference resolution.
        When absent, Phase 4e deterministic pronoun fallback is used.

    Returns
    -------
    list[dict]
        One dict per question. Each dict always contains:
        ``question``, ``final_text``, ``outcome``, ``supported``, ``intent``.
        When ``debug=True`` and a resolver ran, also includes
        ``rewritten_question`` and a ``debug`` bundle with ``resolver`` metadata.
    """
    from fpl_grounded_assistant import ConversationSession
    session = ConversationSession()
    results: list[dict[str, Any]] = []
    for q in questions:
        r = session.respond(
            q, bootstrap,
            include_debug=debug,
            resolver_client=resolver_client,
        )
        turn: dict[str, Any] = {
            "question":   q,
            "final_text": r.final_text,
            "outcome":    r.outcome,
            "supported":  r.supported,
            "intent":     r.intent,
        }
        if debug and r.debug is not None:
            debug_bundle: dict[str, Any] = {
                "response_text": r.debug.response_text,
                "llm_text":      r.debug.llm_text,
                "violations":    list(r.debug.violations),
                "prompt_used":   r.debug.prompt_used,
                "model":         r.debug.model,
            }
            if r.debug.resolver is not None:
                rdbg = r.debug.resolver
                debug_bundle["resolver"] = {
                    "resolver_used":       rdbg.resolver_used,
                    "resolver_source":     rdbg.resolver_source,
                    "resolver_confidence": rdbg.resolver_confidence,
                    "rewritten_question":  rdbg.rewritten_question,
                    "fallback_reason":     rdbg.fallback_reason,
                }
                if rdbg.resolver_used:
                    turn["rewritten_question"] = rdbg.rewritten_question
            turn["debug"] = debug_bundle
        results.append(turn)
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Parse arguments, assemble live bootstrap, call ``run()``, print output.

    Returns the exit code (0 or 1).
    """
    parser = argparse.ArgumentParser(
        prog="fpl_cli",
        description=(
            "FPL grounded assistant -- ask a captaincy or player question "
            "and get a grounded, structured answer."
        ),
    )
    parser.add_argument(
        "question",
        help="Your FPL question (e.g. 'should I captain Haaland this week?')",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help=(
            "Print structured JSON response instead of plain text. "
            "Includes outcome, intent, review_passed, llm_used, and debug bundle."
        ),
    )
    args = parser.parse_args(argv)

    ctx = assemble_captain_context()
    bootstrap = ctx["bootstrap"]

    code, output = run(args.question, bootstrap, debug=args.debug)
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
