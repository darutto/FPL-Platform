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
# Comparison serialisation helper  (Phase 5j)
# ---------------------------------------------------------------------------

def _serial_comparison(comparison: Any) -> dict[str, Any]:
    """Serialise a ``ComparisonMeta`` instance to a JSON-safe dict.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    comparison:
        A non-None ``ComparisonMeta`` value from ``FinalResponse.comparison``.

    Returns
    -------
    dict with keys: winner, margin, label, reasons, player_a, player_b.
    player_a / player_b are dicts with five keys each, or None when not
    present (legacy or non-OK paths).
    """
    def _player_ctx(ctx: Any) -> dict[str, Any] | None:
        if ctx is None:
            return None
        return {
            "web_name":        ctx.web_name,
            "position":        ctx.position,
            "captain_score":   ctx.captain_score,
            "role_bonus":      ctx.role_bonus,
            "set_piece_notes": list(ctx.set_piece_notes),
        }

    return {
        "winner":   comparison.winner,
        "margin":   comparison.margin,
        "label":    comparison.label,
        "reasons":  list(comparison.reasons),
        "player_a": _player_ctx(comparison.player_a),
        "player_b": _player_ctx(comparison.player_b),
    }


# ---------------------------------------------------------------------------
# Captain score metadata serialisation helper  (Phase 5n)
# ---------------------------------------------------------------------------

def _serial_captain(captain: Any) -> dict[str, Any]:
    """Serialise a ``CaptainScoreMeta`` instance to a JSON-safe dict.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    captain:
        A non-None ``CaptainScoreMeta`` value from ``FinalResponse.captain``.

    Returns
    -------
    dict with keys: web_name, team_short, captain_score, tier,
    role_bonus, set_piece_notes.
    """
    return {
        "web_name":        captain.web_name,
        "team_short":      captain.team_short,
        "captain_score":   captain.captain_score,
        "tier":            captain.tier,
        "role_bonus":      captain.role_bonus,
        "set_piece_notes": list(captain.set_piece_notes),
    }


# ---------------------------------------------------------------------------
# Ranked captain candidates serialisation helper  (Phase 5p)
# ---------------------------------------------------------------------------

def _serial_captain_ranking(captain_ranking: Any) -> list[dict[str, Any]]:
    """Serialise a ``tuple[RankedCaptainEntry, ...]`` to a JSON-safe list.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    captain_ranking:
        A non-None ``tuple[RankedCaptainEntry, ...]`` value from
        ``FinalResponse.captain_ranking``.

    Returns
    -------
    list of dicts, each with keys: rank, web_name, team_short,
    captain_score, tier, role_bonus, set_piece_notes.
    """
    return [
        {
            "rank":            entry.rank,
            "web_name":        entry.web_name,
            "team_short":      entry.team_short,
            "captain_score":   entry.captain_score,
            "tier":            entry.tier,
            "role_bonus":      entry.role_bonus,
            "set_piece_notes": list(entry.set_piece_notes),
        }
        for entry in captain_ranking
    ]


# ---------------------------------------------------------------------------
# Core logic  (separated from arg parsing for testability)
# ---------------------------------------------------------------------------

def run(
    question: str,
    bootstrap: dict[str, Any],
    *,
    debug: bool = False,
    candidates_list: list[dict[str, Any]] | None = None,
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
    r: FinalResponse = respond(question, bootstrap, include_debug=debug, candidates_list=candidates_list)

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
        if r.comparison is not None:                       # Phase 5j
            payload["comparison"] = _serial_comparison(r.comparison)
        if r.captain is not None:                          # Phase 5n
            payload["captain"] = _serial_captain(r.captain)
        if r.captain_ranking is not None:                  # Phase 5p
            payload["captain_ranking"] = _serial_captain_ranking(r.captain_ranking)
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
    candidates_list: list[dict[str, Any]] | None = None,
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
            candidates_list=candidates_list,
        )
        turn: dict[str, Any] = {
            "question":   q,
            "final_text": r.final_text,
            "outcome":    r.outcome,
            "supported":  r.supported,
            "intent":     r.intent,
        }
        if r.comparison is not None:                       # Phase 5j
            turn["comparison"] = _serial_comparison(r.comparison)
        if r.captain is not None:                          # Phase 5n
            turn["captain"] = _serial_captain(r.captain)
        if r.captain_ranking is not None:                  # Phase 5p
            turn["captain_ranking"] = _serial_captain_ranking(r.captain_ranking)
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
