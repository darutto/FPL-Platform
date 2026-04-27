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
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# sys.path setup  (same pattern as fpl_repl.py / fpl_server.py)
# ---------------------------------------------------------------------------

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
            "position_score":  ctx.position_score,   # Phase 8a1 Layer 2
            "is_home":         ctx.is_home,           # Phase 8b
            "effective_fdr":   ctx.effective_fdr,     # Phase 8b
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
# Transfer metadata serialisation helper  (Phase 7a)
# ---------------------------------------------------------------------------

def _serial_transfer(transfer: Any) -> dict[str, Any]:
    """Serialise a ``TransferMeta`` instance to a JSON-safe dict.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    transfer:
        A non-None ``TransferMeta`` value from ``FinalResponse.transfer``.

    Returns
    -------
    dict with keys: player_out, player_in, recommendation, score_delta,
    price_delta, reasons.
    """
    return {
        "player_out":        transfer.player_out,
        "player_in":         transfer.player_in,
        "recommendation":    transfer.recommendation,
        "score_delta":       transfer.score_delta,
        "price_delta":       transfer.price_delta,
        "reasons":           list(transfer.reasons),
        "budget_constraint": transfer.budget_constraint,  # Phase 8e1
        "hit_warning":       transfer.hit_warning,        # Phase 8e2
    }


# ---------------------------------------------------------------------------
# Chip advice metadata serialisation helper  (Phase 7b)
# ---------------------------------------------------------------------------

def _serial_chip(chip: Any) -> dict[str, Any]:
    """Serialise a ``ChipAdviceMeta`` instance to a JSON-safe dict.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    chip:
        A non-None ``ChipAdviceMeta`` value from ``FinalResponse.chip``.

    Returns
    -------
    dict with keys: chip, recommendation, gw, signal_value, signal_label.
    """
    return {
        "chip":             chip.chip,
        "recommendation":   chip.recommendation,
        "gw":               chip.gw,
        "signal_value":     chip.signal_value,
        "signal_label":     chip.signal_label,
        "chip_unavailable": chip.chip_unavailable,  # Phase 8e1
    }


# ---------------------------------------------------------------------------
# Fixture run metadata serialisation helper  (Phase 7h)
# ---------------------------------------------------------------------------

def _serial_fixture_run(fixture_run: Any) -> dict[str, Any]:
    """Serialise a ``FixtureRunMeta`` instance to a JSON-safe dict.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    fixture_run:
        A non-None ``FixtureRunMeta`` value from ``FinalResponse.fixture_run``.

    Returns
    -------
    dict with keys: web_name, team_short, position, horizon,
    current_gameweek, fixtures.
    """
    return {
        "web_name":         fixture_run.web_name,
        "team_short":       fixture_run.team_short,
        "position":         fixture_run.position,
        "horizon":          fixture_run.horizon,
        "current_gameweek": fixture_run.current_gameweek,
        "fixtures": [
            {
                "gameweek":       fx.gameweek,
                "opponent_short": fx.opponent_short,
                "is_home":        fx.is_home,
                "difficulty":     fx.difficulty,
            }
            for fx in fixture_run.fixtures
        ],
    }


# ---------------------------------------------------------------------------
# Differential picks metadata serialisation helper  (Phase 7g)
# ---------------------------------------------------------------------------

def _serial_differential(differential: Any) -> dict[str, Any]:
    """Serialise a ``DifferentialPicksMeta`` instance to a JSON-safe dict.

    Mirrors the shape used by ``fpl_server.py`` so CLI debug output and
    HTTP response bodies stay aligned.

    Parameters
    ----------
    differential:
        A non-None ``DifferentialPicksMeta`` value from
        ``FinalResponse.differential``.

    Returns
    -------
    dict with keys: ownership_threshold, top_n, picks.
    """
    return {
        "ownership_threshold": differential.ownership_threshold,
        "top_n":               differential.top_n,
        "picks": [
            {
                "rank":          p.rank,
                "web_name":      p.web_name,
                "team_short":    p.team_short,
                "position":      p.position,
                "captain_score": p.captain_score,
                "ownership":     p.ownership,
                "now_cost":      p.now_cost,
            }
            for p in differential.picks
        ],
    }


# ---------------------------------------------------------------------------
# Core logic  (separated from arg parsing for testability)
# ---------------------------------------------------------------------------

def run(
    question: str,
    bootstrap: dict[str, Any],
    *,
    debug: bool = False,
    candidates_list: list[dict[str, Any]] | None = None,
    classifier_client: Any = None,
    squad_context: dict[str, Any] | None = None,  # Phase 8e1
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
    r: FinalResponse = respond(
        question, bootstrap,
        include_debug=debug,
        candidates_list=candidates_list,
        classifier_client=classifier_client,
        squad_context=squad_context,        # Phase 8e1
    )

    if debug:
        payload: dict[str, Any] = {
            "final_text":    r.final_text,
            "outcome":       r.outcome,
            "supported":     r.supported,
            "intent":        r.intent,
            "review_passed": r.review_passed,
            "llm_used":      r.llm_used,
        }
        if r.orch_outcome is not None:                         # Orch-4c: audit
            payload["orch_outcome"] = r.orch_outcome
        if r.debug is not None:
            payload["debug"] = {
                "response_text":        r.debug.response_text,
                "llm_text":             r.debug.llm_text,
                "violations":           list(r.debug.violations),
                "prompt_used":          r.debug.prompt_used,
                "model":                r.debug.model,
                "classification_source": r.debug.classification_source,
            }
        if r.comparison is not None:                       # Phase 5j
            payload["comparison"] = _serial_comparison(r.comparison)
        if r.captain is not None:                          # Phase 5n
            payload["captain"] = _serial_captain(r.captain)
        if r.captain_ranking is not None:                  # Phase 5p
            payload["captain_ranking"] = _serial_captain_ranking(r.captain_ranking)
        if r.transfer is not None:                         # Phase 7a
            payload["transfer"] = _serial_transfer(r.transfer)
        if r.chip is not None:                             # Phase 7b
            payload["chip"] = _serial_chip(r.chip)
        if r.fixture_run is not None:                      # Phase 7h
            payload["fixture_run"] = _serial_fixture_run(r.fixture_run)
        if r.differential is not None:                     # Phase 7g
            payload["differential"] = _serial_differential(r.differential)
        if r.sub_responses is not None:                    # Phase 6c/6d
            sub_list: list[dict[str, Any]] = []
            for sr in r.sub_responses:
                sub_d: dict[str, Any] = {
                    "final_text": sr.final_text,
                    "outcome":    sr.outcome,
                    "supported":  sr.supported,
                    "intent":     sr.intent,
                }
                if sr.comparison is not None:
                    sub_d["comparison"] = _serial_comparison(sr.comparison)
                if sr.captain is not None:
                    sub_d["captain"] = _serial_captain(sr.captain)
                if sr.captain_ranking is not None:
                    sub_d["captain_ranking"] = _serial_captain_ranking(sr.captain_ranking)
                if sr.transfer is not None:                # Phase 7a
                    sub_d["transfer"] = _serial_transfer(sr.transfer)
                if sr.chip is not None:                    # Phase 7b
                    sub_d["chip"] = _serial_chip(sr.chip)
                if sr.fixture_run is not None:             # Phase 7h
                    sub_d["fixture_run"] = _serial_fixture_run(sr.fixture_run)
                if sr.differential is not None:            # Phase 7g
                    sub_d["differential"] = _serial_differential(sr.differential)
                sub_list.append(sub_d)
            payload["sub_responses"] = sub_list
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
    classifier_client: Any = None,
    squad_context: dict[str, Any] | None = None,  # Phase 8e1
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
            classifier_client=classifier_client,  # Phase 4l
            squad_context=squad_context,           # Phase 8e1
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
        if r.transfer is not None:                         # Phase 7a
            turn["transfer"] = _serial_transfer(r.transfer)
        if r.chip is not None:                             # Phase 7b
            turn["chip"] = _serial_chip(r.chip)
        if r.fixture_run is not None:                      # Phase 7h
            turn["fixture_run"] = _serial_fixture_run(r.fixture_run)
        if r.differential is not None:                     # Phase 7g
            turn["differential"] = _serial_differential(r.differential)
        if r.sub_responses is not None:                    # Phase 6d
            sub_list_s: list[dict[str, Any]] = []
            for sr in r.sub_responses:
                sub_d_s: dict[str, Any] = {
                    "final_text": sr.final_text,
                    "outcome":    sr.outcome,
                    "supported":  sr.supported,
                    "intent":     sr.intent,
                }
                if sr.comparison is not None:
                    sub_d_s["comparison"] = _serial_comparison(sr.comparison)
                if sr.captain is not None:
                    sub_d_s["captain"] = _serial_captain(sr.captain)
                if sr.captain_ranking is not None:
                    sub_d_s["captain_ranking"] = _serial_captain_ranking(sr.captain_ranking)
                if sr.transfer is not None:                # Phase 7a
                    sub_d_s["transfer"] = _serial_transfer(sr.transfer)
                if sr.chip is not None:                    # Phase 7b
                    sub_d_s["chip"] = _serial_chip(sr.chip)
                if sr.fixture_run is not None:             # Phase 7h
                    sub_d_s["fixture_run"] = _serial_fixture_run(sr.fixture_run)
                if sr.differential is not None:            # Phase 7g
                    sub_d_s["differential"] = _serial_differential(sr.differential)
                sub_list_s.append(sub_d_s)
            turn["sub_responses"] = sub_list_s
        if debug and r.debug is not None:
            debug_bundle: dict[str, Any] = {
                "response_text":         r.debug.response_text,
                "llm_text":              r.debug.llm_text,
                "violations":            list(r.debug.violations),
                "prompt_used":           r.debug.prompt_used,
                "model":                 r.debug.model,
                "classification_source": r.debug.classification_source,  # Phase 4l
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
    parser.add_argument(
        "--itb",
        type=float,
        default=None,
        metavar="POUNDS",
        help=(
            "Money in the bank in £m (e.g. --itb 2.5 means £2.5m). "
            "When set, transfer advice is blocked with budget_constraint if "
            "the upgrade cost exceeds this amount. (Phase 8e1)"
        ),
    )
    parser.add_argument(
        "--chips-remaining",
        type=str,
        default=None,
        metavar="CHIPS",
        help=(
            "Comma-separated list of chips you still hold "
            "(e.g. --chips-remaining wildcard,free_hit). "
            "When set, chip advice is marked chip_unavailable if the requested "
            "chip is not in this list. (Phase 8e1)"
        ),
    )
    parser.add_argument(
        "--free-transfers",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of free transfers available this gameweek (e.g. --free-transfers 1). "
            "When set to 1 and a marginal_transfer_in is recommended, "
            "hit_warning=True is set on TransferMeta. (Phase 8e2)"
        ),
    )
    args = parser.parse_args(argv)

    # Build squad_context from optional CLI flags (Phase 8e1/8e2)
    squad_ctx: dict[str, Any] | None = None
    if args.itb is not None or args.chips_remaining is not None or args.free_transfers is not None:
        squad_ctx = {}
        if args.itb is not None:
            squad_ctx["itb"] = int(round(args.itb * 10))  # convert £m to tenths of £
        if args.chips_remaining is not None:
            squad_ctx["chips_remaining"] = [
                c.strip() for c in args.chips_remaining.split(",") if c.strip()
            ]
        if args.free_transfers is not None:
            squad_ctx["free_transfers"] = args.free_transfers

    ctx = assemble_captain_context()
    bootstrap = ctx["bootstrap"]

    code, output = run(args.question, bootstrap, debug=args.debug, squad_context=squad_ctx)
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
