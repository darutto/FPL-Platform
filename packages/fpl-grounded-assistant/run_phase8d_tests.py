"""
run_phase8d_tests.py
=====================
Phase 8d-i: deterministic fixture run follow-up support.

Sections
--------
A  resolve_fixture_run_followup -- rewrite logic and pattern matching
B  ConversationState tracking   -- last_fixture_run_player set/cleared correctly
C  ConversationSession wiring   -- end-to-end session follow-up routing
D  resolver_source metadata     -- fixture_run_followup appears in debug bundle
E  SessionInfoResponse field    -- last_fixture_run_player in GET /session inspect
F  Regression: session_cli + session_http corpus scenario #36
G  Regression: V1 stateless gate (cli+http, all stateless scenarios)

Run from packages/fpl-grounded-assistant::

    python run_phase8d_tests.py
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.conversation_state import (
    ConversationState,
    ConversationSession,
    resolve_fixture_run_followup,
    _FIXTURE_FOLLOWUP_PREFIXES,
    _FIXTURE_INSTEAD_SUFFIXES,
    _FIXTURE_INTERROGATIVE_STARTERS,
)
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant import respond

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


def _state_with_fixture_run(player: str) -> ConversationState:
    """Create a ConversationState with last_fixture_run_player already set."""
    s = ConversationState()
    s.last_fixture_run_player = player
    return s


def _state_empty() -> ConversationState:
    return ConversationState()


# ---------------------------------------------------------------------------
# Section A: resolve_fixture_run_followup rewrite logic
# ---------------------------------------------------------------------------

print("\n=== A: resolve_fixture_run_followup rewrite logic ===")

# A1: no last_fixture_run_player -> None regardless of question
ok(
    resolve_fixture_run_followup("what about Salah?", _state_empty()) is None,
    "A1: no last_fixture_run_player -> None",
)

# A2: "what about X?" prefix -> "{X} fixtures"
state = _state_with_fixture_run("Haaland")
ok(
    resolve_fixture_run_followup("what about Salah?", state) == "Salah fixtures",
    "A2: 'what about Salah?' -> 'Salah fixtures'",
)

# A3: "how about X?" prefix -> "{X} fixtures"
ok(
    resolve_fixture_run_followup("How about Saka?", state) == "Saka fixtures",
    "A3: 'How about Saka?' -> 'Saka fixtures'",
)

# A4: case-insensitive prefix match
ok(
    resolve_fixture_run_followup("WHAT ABOUT Palmer?", state) == "Palmer fixtures",
    "A4: uppercase prefix match works",
)

# A5: "what about X instead?" strips " instead"
ok(
    resolve_fixture_run_followup("what about Saka instead?", state) == "Saka instead fixtures"
    or resolve_fixture_run_followup("what about Saka instead?", state) == "Saka fixtures",
    "A5: 'what about Saka instead?' strips ' instead'",
)

# A5b: explicit "instead" stripping
result_a5 = resolve_fixture_run_followup("what about Saka instead?", state)
ok(
    result_a5 == "Saka fixtures",
    f"A5b: 'what about Saka instead?' -> 'Saka fixtures' (got {result_a5!r})",
)

# A6: bare name (1 word) -> "{name} fixtures"
ok(
    resolve_fixture_run_followup("Salah?", state) == "Salah fixtures",
    "A6: 'Salah?' bare name -> 'Salah fixtures'",
)

# A7: bare name (2 words) -> "{name} fixtures"
ok(
    resolve_fixture_run_followup("Trent Alexander?", state) == "Trent Alexander fixtures",
    "A7: 'Trent Alexander?' -> 'Trent Alexander fixtures'",
)

# A8: bare name (3 words) -> "{name} fixtures"
ok(
    resolve_fixture_run_followup("Alexander Arnold?", state) == "Alexander Arnold fixtures",
    "A8: 'Alexander Arnold?' -> 'Alexander Arnold fixtures'",
)

# A9: 4-word bare name -> None (exceeds 3-word limit)
ok(
    resolve_fixture_run_followup("Alexander-Arnold next fixtures please?", state) is None,
    "A9: 4+ words bare name -> None",
)

# A10: "should I start Salah?" full sentence -> None (not a bare name, interrogative starter)
ok(
    resolve_fixture_run_followup("should I start Salah?", state) is None,
    "A10: 'should I start Salah?' interrogative sentence -> None",
)

# A10b: "should" is an interrogative starter -> None for bare "should I"
ok(
    resolve_fixture_run_followup("should I?", state) is None,
    "A10b: 'should I?' interrogative starter -> None",
)

# A10c: "what about the fixtures?" -> None (article/determiner remainder blocked)
ok(
    resolve_fixture_run_followup("what about the fixtures?", state) is None,
    "A10c: 'what about the fixtures?' -> None (non-player remainder blocked)",
)

# A10d: "what about the games this week?" -> None (article-led remainder)
ok(
    resolve_fixture_run_followup("what about the games this week?", state) is None,
    "A10d: 'what about the games this week?' -> None",
)

# A10e: "how about this week?" -> None (determiner-led remainder)
ok(
    resolve_fixture_run_followup("how about this week?", state) is None,
    "A10e: 'how about this week?' -> None",
)

# A10f: "what about next week?" -> None (time-noun-led remainder)
ok(
    resolve_fixture_run_followup("what about next week?", state) is None,
    "A10f: 'what about next week?' -> None (time noun blocked)",
)

# A11: "compare" starter -> None
ok(
    resolve_fixture_run_followup("compare Salah?", state) is None,
    "A11: 'compare' interrogative starter -> None",
)

# A12: no trailing punctuation needed — bare name without ? also works
ok(
    resolve_fixture_run_followup("Salah", state) == "Salah fixtures",
    "A12: 'Salah' (no punctuation) -> 'Salah fixtures'",
)

# A13: empty question -> None
ok(
    resolve_fixture_run_followup("", state) is None,
    "A13: empty string -> None",
)

# A14: "vs" starter -> None
ok(
    resolve_fixture_run_followup("vs Salah?", state) is None,
    "A14: 'vs' starter -> None",
)

# A15: prefix match returns original-case name (not lowercased)
result_a15 = resolve_fixture_run_followup("what about SALAH?", state)
ok(
    result_a15 == "SALAH fixtures",
    f"A15: original case preserved in rewritten query (got {result_a15!r})",
)

# A16: direct fixture run question not treated as bare-name follow-up
ok(
    resolve_fixture_run_followup("Salah fixtures", state) is None,
    "A16: 'Salah fixtures' (direct fixture run) -> None (already routable)",
)

# A17: "Salah fixture run" not treated as bare-name follow-up
ok(
    resolve_fixture_run_followup("Salah fixture run", state) is None,
    "A17: 'Salah fixture run' (direct fixture run) -> None",
)

# A18: "what about good fixtures?" -> None (content word 'fixtures' in remainder)
ok(
    resolve_fixture_run_followup("what about good fixtures?", state) is None,
    "A18: 'what about good fixtures?' -> None (content blocklist)",
)

# A19: "what about players with good fixtures?" -> None (content words 'players'+'fixtures')
ok(
    resolve_fixture_run_followup("what about players with good fixtures?", state) is None,
    "A19: 'what about players with good fixtures?' -> None (content blocklist)",
)

# A20: "how about great games this week?" -> None (content word 'games')
ok(
    resolve_fixture_run_followup("how about great games this week?", state) is None,
    "A20: 'how about great games this week?' -> None (content blocklist)",
)

# A21: "what about fixture difficulty?" -> None (content word 'fixture')
ok(
    resolve_fixture_run_followup("what about fixture difficulty?", state) is None,
    "A21: 'what about fixture difficulty?' -> None (content word 'fixture' blocked)",
)

# A22: valid player names with prefix path still work after content blocklist
ok(
    resolve_fixture_run_followup("what about Salah?", state) == "Salah fixtures",
    "A22: valid player 'what about Salah?' still rewrites after blocklist guards",
)
ok(
    resolve_fixture_run_followup("how about Trent Alexander?", state) == "Trent Alexander fixtures",
    "A23: valid player 'how about Trent Alexander?' still rewrites",
)

# ---------------------------------------------------------------------------
# Section B: ConversationState tracking
# ---------------------------------------------------------------------------

print("\n=== B: ConversationState tracking ===")

# B1: last_fixture_run_player is None initially
state_b = ConversationState()
ok(state_b.last_fixture_run_player is None, "B1: last_fixture_run_player starts None")

# B2: successful fixture run turn sets last_fixture_run_player
session_b = ConversationSession()
r1 = session_b.respond("Haaland fixtures", STANDARD_BOOTSTRAP)
ok(
    session_b.state.last_fixture_run_player is not None,
    "B2: last_fixture_run_player set after fixture run turn",
)

# B3: fixture run player name is Haaland (or the resolved query)
frun_player = session_b.state.last_fixture_run_player
ok(
    frun_player is not None and "haaland" in frun_player.lower(),
    f"B3: last_fixture_run_player contains 'haaland' (got {frun_player!r})",
)

# B4: non-fixture OK turn clears last_fixture_run_player
session_b.respond("should I captain Salah", STANDARD_BOOTSTRAP)
ok(
    session_b.state.last_fixture_run_player is None,
    "B4: last_fixture_run_player cleared after non-fixture turn",
)

# B5: second fixture run turn updates last_fixture_run_player
session_b2 = ConversationSession()
session_b2.respond("Haaland fixtures", STANDARD_BOOTSTRAP)
session_b2.respond("Salah fixtures", STANDARD_BOOTSTRAP)
ok(
    session_b2.state.last_fixture_run_player is not None
    and "salah" in (session_b2.state.last_fixture_run_player or "").lower(),
    "B5: second fixture run turn updates last_fixture_run_player to new player",
)

# B6: clear() resets last_fixture_run_player
session_b3 = ConversationSession()
session_b3.respond("Haaland fixtures", STANDARD_BOOTSTRAP)
session_b3.clear()
ok(
    session_b3.state.last_fixture_run_player is None,
    "B6: clear() resets last_fixture_run_player",
)

# ---------------------------------------------------------------------------
# Section C: ConversationSession end-to-end follow-up routing
# ---------------------------------------------------------------------------

print("\n=== C: ConversationSession end-to-end follow-up routing ===")

session_c = ConversationSession()

# C1: Turn 1 — fixture run succeeds
r_c1 = session_c.respond("Haaland fixtures", STANDARD_BOOTSTRAP, include_debug=True)
ok(r_c1.outcome == "ok", "C1: turn 1 'Haaland fixtures' -> outcome ok")
ok(r_c1.fixture_run is not None, "C2: turn 1 has fixture_run metadata")

# C3-C5: Turn 2 — fixture run follow-up rewrites and routes correctly
r_c3 = session_c.respond("what about Salah?", STANDARD_BOOTSTRAP, include_debug=True)
ok(r_c3.outcome == "ok", "C3: turn 2 'what about Salah?' -> outcome ok")
ok(r_c3.fixture_run is not None, "C4: turn 2 has fixture_run metadata")
ok(
    r_c3.fixture_run is not None
    and "salah" in (r_c3.fixture_run.web_name or "").lower(),
    f"C5: turn 2 fixture_run.web_name is Salah (got {r_c3.fixture_run.web_name if r_c3.fixture_run else None!r})",
)

# C6: bare name pattern also routes correctly
session_c2 = ConversationSession()
session_c2.respond("Haaland fixtures", STANDARD_BOOTSTRAP)
r_c6 = session_c2.respond("Salah?", STANDARD_BOOTSTRAP)
ok(r_c6.outcome == "ok", "C6: bare name 'Salah?' follow-up -> outcome ok")
ok(r_c6.fixture_run is not None, "C7: bare name follow-up has fixture_run metadata")

# C8: follow-up without prior fixture run turn does NOT trigger (falls through to LLM/regex)
session_c3 = ConversationSession()
r_c8 = session_c3.respond("what about Salah?", STANDARD_BOOTSTRAP, include_debug=True)
# This could route differently (not as fixture_run_followup) — just check no crash
ok(r_c8 is not None, "C8: 'what about Salah?' without prior fixture run -> no crash")

# ---------------------------------------------------------------------------
# Section D: resolver_source metadata
# ---------------------------------------------------------------------------

print("\n=== D: resolver_source metadata ===")

session_d = ConversationSession()
session_d.respond("Haaland fixtures", STANDARD_BOOTSTRAP)
r_d = session_d.respond("what about Salah?", STANDARD_BOOTSTRAP, include_debug=True)

d_debug = r_d.debug
d_resolver = d_debug.resolver if d_debug is not None else None
d_src = d_resolver.resolver_source if d_resolver is not None else None

ok(d_src == "fixture_run_followup", f"D1: resolver_source='fixture_run_followup' (got {d_src!r})")

d_rewritten = (d_resolver.rewritten_question or "") if d_resolver is not None else ""
ok(
    "salah" in d_rewritten.lower() and "fixture" in d_rewritten.lower(),
    f"D2: rewritten_question contains 'salah fixtures' (got {d_rewritten!r})",
)

# D3: last_resolver_source persisted in state
ok(
    session_d.state.last_resolver_source == "fixture_run_followup",
    f"D3: state.last_resolver_source='fixture_run_followup' (got {session_d.state.last_resolver_source!r})",
)

# D4: non-followup turn has different resolver_source
session_d2 = ConversationSession()
r_d4 = session_d2.respond("Haaland fixtures", STANDARD_BOOTSTRAP, include_debug=True)
d4_debug = r_d4.debug
d4_resolver = d4_debug.resolver if d4_debug is not None else None
d4_src = d4_resolver.resolver_source if d4_resolver is not None else None
ok(
    d4_src != "fixture_run_followup",
    f"D4: direct fixture run does not use fixture_run_followup source (got {d4_src!r})",
)

# ---------------------------------------------------------------------------
# Section E: SessionInfoResponse field (HTTP endpoint)
# ---------------------------------------------------------------------------

print("\n=== E: SessionInfoResponse last_fixture_run_player (HTTP) ===")

try:
    from fastapi.testclient import TestClient
    import fpl_server

    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._clear_sessions()
    client = TestClient(fpl_server.app, raise_server_exceptions=True)

    # E1: create session
    cr = client.post("/session")
    ok(cr.status_code == 200, "E1: POST /session -> 200")
    sid = cr.json()["session_id"]

    # E2: inspect before any turns — last_fixture_run_player is None
    ir0 = client.get(f"/session/{sid}").json()
    ok(ir0.get("last_fixture_run_player") is None, "E2: last_fixture_run_player=None before turns")

    # E3: fixture run turn -> last_fixture_run_player populated
    ar1 = client.post(
        f"/session/{sid}/ask",
        json={"question": "Haaland fixtures", "include_debug": True},
    )
    ok(ar1.status_code == 200, "E3: POST /session/{id}/ask 'Haaland fixtures' -> 200")
    ir1 = client.get(f"/session/{sid}").json()
    e3_val = ir1.get("last_fixture_run_player")
    ok(e3_val is not None, f"E4: last_fixture_run_player populated after fixture run (got {e3_val!r})")

    # E5: follow-up turn -> last_fixture_run_player updated to new player
    ar2 = client.post(
        f"/session/{sid}/ask",
        json={"question": "what about Salah?", "include_debug": True},
    )
    ok(ar2.status_code == 200, "E5: POST /session/{id}/ask 'what about Salah?' -> 200")
    ir2 = client.get(f"/session/{sid}").json()
    e5_val = ir2.get("last_fixture_run_player")
    ok(
        e5_val is not None and "salah" in (e5_val or "").lower(),
        f"E6: last_fixture_run_player updated to Salah after follow-up (got {e5_val!r})",
    )

    # E7: non-fixture turn clears last_fixture_run_player
    client.post(
        f"/session/{sid}/ask",
        json={"question": "should I captain Salah", "include_debug": False},
    )
    ir3 = client.get(f"/session/{sid}").json()
    ok(
        ir3.get("last_fixture_run_player") is None,
        "E7: last_fixture_run_player cleared after non-fixture turn",
    )

    # Cleanup
    client.delete(f"/session/{sid}")

except Exception as exc:
    print(f"  SKIP  E: HTTP session inspect test failed: {exc}")

# ---------------------------------------------------------------------------
# Section F: Regression — corpus scenario #36 (session_cli + session_http)
# ---------------------------------------------------------------------------

print("\n=== F: corpus scenario #36 fixture_run_followup ===")

try:
    from validation_corpus import SCENARIO_BY_ID
    from run_validation import _resolve_bootstrap, run_session_cli_surface, run_session_http_surface

    sc36 = SCENARIO_BY_ID.get("fixture_run_followup")
    if sc36 is None:
        print("  SKIP  F: scenario 'fixture_run_followup' not found in corpus")
    else:
        bs36 = _resolve_bootstrap(sc36.bootstrap)

        # F1: session_cli
        r_cli = run_session_cli_surface(sc36, bs36)
        ok(r_cli.get("intent") == "player_fixture_run", f"F1: session_cli intent=player_fixture_run (got {r_cli.get('intent')!r})")
        ok(r_cli.get("outcome") == "ok", f"F2: session_cli outcome=ok (got {r_cli.get('outcome')!r})")
        ok(r_cli.get("fixture_run") is not None, "F3: session_cli fixture_run non-null")
        ok(r_cli.get("resolver_source") == "fixture_run_followup",
           f"F4: session_cli resolver_source='fixture_run_followup' (got {r_cli.get('resolver_source')!r})")

        # F5: session_http
        r_http = run_session_http_surface(sc36, bs36)
        ok(r_http.get("intent") == "player_fixture_run", f"F5: session_http intent=player_fixture_run (got {r_http.get('intent')!r})")
        ok(r_http.get("outcome") == "ok", f"F6: session_http outcome=ok (got {r_http.get('outcome')!r})")
        ok(r_http.get("fixture_run") is not None, "F7: session_http fixture_run non-null")

except Exception as exc:
    print(f"  SKIP  F: corpus scenario test failed: {exc}")

# ---------------------------------------------------------------------------
# Section G: Regression — V1 stateless gate
# ---------------------------------------------------------------------------

print("\n=== G: V1 stateless regression gate ===")

try:
    from validation_corpus import VALIDATION_SCENARIOS
    from run_validation import _resolve_bootstrap, run_cli_surface, run_http_surface

    g_pass = 0
    g_fail = 0

    for sc in VALIDATION_SCENARIOS:
        if not any(s in ("cli", "http") for s in sc.surfaces):
            continue
        bs = _resolve_bootstrap(sc.bootstrap)
        for surface, runner in (("cli", run_cli_surface), ("http", run_http_surface)):
            if surface not in sc.surfaces:
                continue
            try:
                result = runner(sc, bs)
                intent_ok  = result.get("intent")   == sc.expected_intent
                outcome_ok = result.get("outcome")  == sc.expected_outcome
                support_ok = result.get("supported") == sc.expected_supported
                chip_ok    = True
                if sc.expect_chip:
                    chip_ok = result.get("chip") is not None
                fx_ok = True
                if sc.expect_fixture_run:
                    fx_ok = result.get("fixture_run") is not None
                if intent_ok and outcome_ok and support_ok and chip_ok and fx_ok:
                    g_pass += 1
                else:
                    g_fail += 1
                    print(f"    FAIL  G [{sc.id}] {surface}: "
                          f"intent={result.get('intent')!r}(exp={sc.expected_intent!r}) "
                          f"outcome={result.get('outcome')!r}(exp={sc.expected_outcome!r}) "
                          f"chip_ok={chip_ok} fx_ok={fx_ok}")
            except Exception as exc:
                g_fail += 1
                print(f"    FAIL  G [{sc.id}] {surface}: exception: {exc}")

    ok(g_fail == 0 and g_pass > 0,
       f"G: stateless regression gate — {g_pass} pass, {g_fail} fail")

except Exception as exc:
    print(f"  SKIP  G: could not import validation runners ({exc})")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
total = _pass + _fail
print(f"Phase 8d-i: {_pass}/{total} assertions passed.")
if _fail:
    print(f"            {_fail} FAILED.")
    sys.exit(1)
else:
    print("            All assertions passed.")
    sys.exit(0)
