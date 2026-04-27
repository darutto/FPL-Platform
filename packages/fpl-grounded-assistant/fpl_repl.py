"""
fpl_repl.py
===========
Interactive UAT shell for the FPL Grounded Assistant.

Loads live FPL data once at startup, then lets you ask questions in a
conversational loop.  Multi-turn context is preserved within a session
(comparison follow-ups, pronoun resolution, transfer follow-ups all work).

Usage
-----
    cd packages/fpl-grounded-assistant
    python fpl_repl.py           # plain text responses
    python fpl_repl.py --debug   # show structured metadata alongside text

Shell commands (prefix /)
--------------------------
    /help    Show supported intents with example questions
    /debug   Toggle structured metadata display
    /reset   Start a new conversation session (clears multi-turn context)
    /gw      Show current gameweek and loaded player count
    /quit    Exit  (also: /exit or Ctrl-C)
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# sys.path setup  (same pattern as run_validation.py)
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

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------

# Ensure Unicode output works on Windows (cp1252 terminals replace unknown chars)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fpl_pipeline import assemble_captain_context           # noqa: E402
from fpl_grounded_assistant import (                        # noqa: E402
    ConversationSession,
    INTENT_MANIFEST,
    _ANTHROPIC_AVAILABLE,
)
from fpl_grounded_assistant.final_response import FinalResponse  # noqa: E402


# ---------------------------------------------------------------------------
# Metadata display
# ---------------------------------------------------------------------------

def _show_meta(r: FinalResponse) -> None:
    """Print one compact line per populated structured metadata field."""
    if r.captain:
        c = r.captain
        print(f"  [captain]      {c.web_name} ({c.team_short}) | {c.tier} | "
              f"score={c.captain_score:.1f} | role_bonus={c.role_bonus}")

    if r.captain_ranking:
        top = r.captain_ranking[0]
        print(f"  [ranking]      {len(r.captain_ranking)} candidates | "
              f"#1: {top.web_name} ({top.team_short}) {top.tier} score={top.captain_score:.1f}")

    if r.comparison:
        cmp = r.comparison
        reasons_str = "; ".join(cmp.reasons[:2]) if cmp.reasons else "—"
        print(f"  [comparison]   winner={cmp.winner} | {cmp.label} | reasons: {reasons_str}")
        if cmp.player_a and cmp.player_b:
            a, b = cmp.player_a, cmp.player_b
            a_venue = "H" if a.is_home is True else ("A" if a.is_home is False else "?")
            b_venue = "H" if b.is_home is True else ("A" if b.is_home is False else "?")
            print(f"                 {a.web_name}({a.position}): pos_score={a.position_score:.1f}  capt_score={a.captain_score:.1f}  efdr={a.effective_fdr}({a_venue})")
            print(f"                 {b.web_name}({b.position}): pos_score={b.position_score:.1f}  capt_score={b.captain_score:.1f}  efdr={b.effective_fdr}({b_venue})")

    if r.transfer:
        t = r.transfer
        print(f"  [transfer]     {t.player_out} -> {t.player_in} | "
              f"{t.recommendation} | score_delta={t.score_delta:+.1f} (position_score) | "
              f"price_delta={t.price_delta:+d}x0.1m")

    if r.chip:
        ch = r.chip
        sig = f"{ch.signal_value:.1f}" if ch.signal_value is not None else "n/a"
        print(f"  [chip]         {ch.chip} | {ch.recommendation} | "
              f"gw={ch.gw} | signal={sig} ({ch.signal_label})")

    if r.fixture_run:
        fr = r.fixture_run
        fx_str = "  ".join(
            f"GW{fx.gameweek} vs {fx.opponent_short}({'H' if fx.is_home else 'A'}) fdr={fx.difficulty}"
            for fx in fr.fixtures[:3]
        )
        suffix = f"  ...+{len(fr.fixtures)-3} more" if len(fr.fixtures) > 3 else ""
        print(f"  [fixture_run]  {fr.web_name} ({fr.team_short}/{fr.position}) | "
              f"{fr.horizon} fixtures:  {fx_str}{suffix}")

    if r.differential:
        d = r.differential
        if d.picks:
            picks_str = "  ".join(
                f"{p.rank}.{p.web_name}({p.position},ps={p.position_score:.1f},{p.ownership:.1f}%,"
                f"{'H' if p.is_home is True else ('A' if p.is_home is False else '?')})"
                for p in d.picks[:3]
            )
            print(f"  [differential] {len(d.picks)} picks (own<{d.ownership_threshold:.0f}%) | "
                  f"{picks_str}")

    if r.sub_responses:
        for i, sr in enumerate(r.sub_responses):
            print(f"  [sub {i+1}]        intent={sr.intent} | outcome={sr.outcome}")


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

def _print_help(gw: int | None) -> None:
    gw_str = f"GW{gw}" if gw else "unknown GW"
    print(f"\nSupported intents ({gw_str}):")
    for intent, spec in INTENT_MANIFEST.items():
        desc = spec.get("description", "")
        examples = spec.get("example_phrasings", [])
        example = f'  e.g. "{examples[0]}"' if examples else ""
        print(f"  {intent:<26} {desc}")
        if example:
            print(f"    {example}")
    print()
    print("Multi-turn follow-ups (within same session):")
    print('  "And Saka?"              after a comparison')
    print('  "what about Haaland instead"  after a transfer')
    print('  "should I captain him"   after mentioning a player')
    print()
    print("Shell commands:")
    print("  /debug   toggle structured metadata display")
    print("  /reset   new conversation session")
    print("  /gw      show current gameweek")
    print("  /quit    exit")
    print()


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    debug = "--debug" in args

    print()
    print("FPL Grounded Assistant - UAT Shell")
    print("===================================")

    # LLM availability notice
    if _ANTHROPIC_AVAILABLE and os.environ.get("ANTHROPIC_API_KEY"):
        print("LLM: active  (ANTHROPIC_API_KEY set — phrasing and reference resolution enabled)")
    else:
        print("LLM: offline (no ANTHROPIC_API_KEY — deterministic renderer text only)")
    print()

    # Load live FPL data
    print("Loading live FPL data...")
    try:
        ctx = assemble_captain_context()
    except Exception as exc:
        print(f"ERROR: could not load FPL data: {exc}")
        print("Check your network connection and try again.")
        return 1

    bootstrap = ctx["bootstrap"]
    gw        = ctx.get("gameweek")
    elements  = bootstrap.get("elements", [])
    gw_str    = f"GW{gw}" if gw else "gameweek unknown"

    print(f"Ready. {gw_str} | {len(elements)} players loaded.")
    print('Type /help for examples, /debug to toggle metadata, /quit to exit.')
    print()

    session = ConversationSession()

    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        if not line:
            continue

        # Slash commands
        if line.startswith("/"):
            cmd = line.lower().rstrip()
            if cmd in ("/quit", "/exit"):
                print("Goodbye.")
                return 0
            elif cmd == "/reset":
                session = ConversationSession()
                print("[Session reset — new conversation started]")
            elif cmd == "/debug":
                debug = not debug
                print(f"[Debug metadata: {'ON' if debug else 'OFF'}]")
            elif cmd == "/gw":
                print(f"[{gw_str} | {len(elements)} players loaded]")
            elif cmd == "/help":
                _print_help(gw)
            else:
                print(f"[Unknown command: {line}]")
            print()
            continue

        # Send question to assistant
        try:
            r: FinalResponse = session.respond(line, bootstrap, include_debug=False)
        except Exception as exc:
            print(f"[ERROR] {exc}")
            print()
            continue

        print()
        print(f"Assistant: {r.final_text}")

        if debug:
            _show_meta(r)

        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
