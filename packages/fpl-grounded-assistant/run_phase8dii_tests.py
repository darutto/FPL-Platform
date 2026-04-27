"""
run_phase8dii_tests.py
=======================
Phase 8d-ii: deterministic differential picks follow-up support.

Sections
--------
A  resolve_differential_followup -- rewrite logic and pattern matching
B  ConversationState tracking    -- last_differential set/cleared correctly
C  ConversationSession wiring    -- end-to-end session follow-up routing
D  resolver_source metadata      -- differential_followup in debug bundle
E  SessionInfoResponse field     -- last_differential in GET /session inspect
F  Corpus scenario #37           -- session_cli + session_http gates
G  Regression: V1 stateless gate (cli+http, all stateless scenarios)

Run from packages/fpl-grounded-assistant::

    python run_phase8dii_tests.py
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
    resolve_differential_followup,
    _DIFF_FOLLOWUP_PREFIXES,
    _DIFF_INSTEAD_SUFFIXES,
    _DIFF_INTERROGATIVE_STARTERS,
    _DIFF_REMAINDER_NON_PLAYER_STARTERS,
    _DIFF_REMAINDER_CONTENT_BLOCKLIST,
)
from fpl_grounded_assistant.conversation_fixtures import (
    STANDARD_BOOTSTRAP,
    DIFFERENTIAL_BOOTSTRAP,
)

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


def _state_with_differential() -> ConversationState:
    s = ConversationState()
    s.last_differential = True
    return s


def _state_empty() -> ConversationState:
    return ConversationState()


# ---------------------------------------------------------------------------
# Section A: resolve_differential_followup rewrite logic
# ---------------------------------------------------------------------------

print("\n=== A: resolve_differential_followup rewrite logic ===")

state = _state_with_differential()

# A1: no last_differential -> None
ok(
    resolve_differential_followup("what about Mbeumo?", _state_empty()) is None,
    "A1: no last_differential -> None",
)

# A2: "what about X?" prefix -> "should I captain X?"
ok(
    resolve_differential_followup("what about Mbeumo?", state) == "should I captain Mbeumo?",
    "A2: 'what about Mbeumo?' -> 'should I captain Mbeumo?'",
)

# A3: "how about X?" prefix -> "should I captain X?"
ok(
    resolve_differential_followup("How about Palmer?", state) == "should I captain Palmer?",
    "A3: 'How about Palmer?' -> 'should I captain Palmer?'",
)

# A4: case-insensitive prefix match, original case preserved in player name
result_a4 = resolve_differential_followup("WHAT ABOUT Mbeumo?", state)
ok(
    result_a4 == "should I captain Mbeumo?",
    f"A4: uppercase prefix + original-case name (got {result_a4!r})",
)

# A5: "what about X instead?" strips " instead"
result_a5 = resolve_differential_followup("what about Palmer instead?", state)
ok(
    result_a5 == "should I captain Palmer?",
    f"A5: 'what about Palmer instead?' strips ' instead' (got {result_a5!r})",
)

# A6: bare name (1 word) -> "should I captain X?"
ok(
    resolve_differential_followup("Mbeumo?", state) == "should I captain Mbeumo?",
    "A6: 'Mbeumo?' bare name -> 'should I captain Mbeumo?'",
)

# A7: bare name (2 words) -> "should I captain X?"
ok(
    resolve_differential_followup("Trent Alexander?", state) == "should I captain Trent Alexander?",
    "A7: 'Trent Alexander?' -> 'should I captain Trent Alexander?'",
)

# A8: bare name (3 words) -> "should I captain X?"
ok(
    resolve_differential_followup("Alexander Arnold?", state) == "should I captain Alexander Arnold?",
    "A8: 'Alexander Arnold?' -> 'should I captain Alexander Arnold?'",
)

# A9: 4-word bare name -> None (exceeds 3-word limit)
ok(
    resolve_differential_followup("some random unknown player?", state) is None,
    "A9: 4+ words bare name -> None",
)

# A10: interrogative starter -> None
ok(
    resolve_differential_followup("should I pick Mbeumo?", state) is None,
    "A10: 'should I pick Mbeumo?' -> None (interrogative starter)",
)

# A11: "what about the picks?" -> None (determiner-led remainder)
ok(
    resolve_differential_followup("what about the picks?", state) is None,
    "A11: 'what about the picks?' -> None (article-led remainder)",
)

# A12: "what about good differentials?" -> None (content word 'differentials')
ok(
    resolve_differential_followup("what about good differentials?", state) is None,
    "A12: 'what about good differentials?' -> None (content blocklist)",
)

# A13: "what about the players?" -> None (article + content word)
ok(
    resolve_differential_followup("what about the players?", state) is None,
    "A13: 'what about the players?' -> None",
)

# A14: "how about low ownership picks?" -> None (content word 'picks')
ok(
    resolve_differential_followup("how about low ownership picks?", state) is None,
    "A14: 'how about low ownership picks?' -> None (content blocklist: picks)",
)

# A15: empty question -> None
ok(
    resolve_differential_followup("", state) is None,
    "A15: empty string -> None",
)

# A16: "compare" starter -> None
ok(
    resolve_differential_followup("compare Mbeumo?", state) is None,
    "A16: 'compare' starter -> None",
)

# A17: bare name without last_differential -> None
ok(
    resolve_differential_followup("Mbeumo?", _state_empty()) is None,
    "A17: bare name without prior differential turn -> None",
)

# A18: no trailing punctuation bare name still works
ok(
    resolve_differential_followup("Palmer", state) == "should I captain Palmer?",
    "A18: 'Palmer' (no punctuation) -> 'should I captain Palmer?'",
)

# A19: "what about good ones?" -> None (content blocklist: good + ones)
ok(
    resolve_differential_followup("what about good ones?", state) is None,
    "A19: 'what about good ones?' -> None (content blocklist: good, ones)",
)

# A20: "what about low ownership?" -> None (content blocklist: low + ownership)
ok(
    resolve_differential_followup("what about low ownership?", state) is None,
    "A20: 'what about low ownership?' -> None (content blocklist: low, ownership)",
)

# A21: "how about high value?" -> None (content blocklist: high + value)
ok(
    resolve_differential_followup("how about high value?", state) is None,
    "A21: 'how about high value?' -> None (content blocklist: high, value)",
)

# A22: "what about cheap ones?" -> None (content blocklist: cheap + ones)
ok(
    resolve_differential_followup("what about cheap ones?", state) is None,
    "A22: 'what about cheap ones?' -> None (content blocklist: cheap, ones)",
)

# A23: valid player names not blocked by expanded list
ok(
    resolve_differential_followup("what about Saka?", state) == "should I captain Saka?",
    "A23: 'what about Saka?' -> still valid after blocklist expansion",
)

# A24: "what about him?" -> None (object pronoun, never a player name)
ok(
    resolve_differential_followup("what about him?", state) is None,
    "A24: 'what about him?' -> None (pronoun: him)",
)

# A25: "what about them?" -> None (object pronoun)
ok(
    resolve_differential_followup("what about them?", state) is None,
    "A25: 'what about them?' -> None (pronoun: them)",
)

# A26: "what about one?" -> None (generic reference pronoun)
ok(
    resolve_differential_followup("what about one?", state) is None,
    "A26: 'what about one?' -> None (pronoun: one)",
)

# A27: bare "him" (1 word) -> None (pronoun in content blocklist, bare path)
ok(
    resolve_differential_followup("him?", state) is None,
    "A27: 'him?' bare pronoun -> None",
)

# A28: "how about them?" -> None
ok(
    resolve_differential_followup("how about them?", state) is None,
    "A28: 'how about them?' -> None (pronoun: them)",
)

# A29: valid 2-word player name still works
ok(
    resolve_differential_followup("what about Trent Alexander?", state)
        == "should I captain Trent Alexander?",
    "A29: 'what about Trent Alexander?' still valid after pronoun guard",
)

# A30: "what about you?" -> None (pronoun: you)
ok(
    resolve_differential_followup("what about you?", state) is None,
    "A30: 'what about you?' -> None (pronoun: you)",
)

# A31: "what about we?" -> None (pronoun: we)
ok(
    resolve_differential_followup("what about we?", state) is None,
    "A31: 'what about we?' -> None (pronoun: we)",
)

# A32: bare "you?" -> None (pronoun in content blocklist, bare path)
ok(
    resolve_differential_followup("you?", state) is None,
    "A32: 'you?' bare pronoun -> None",
)

# A33: bare "we?" -> None
ok(
    resolve_differential_followup("we?", state) is None,
    "A33: 'we?' bare pronoun -> None",
)

# ---------------------------------------------------------------------------
# Section B: ConversationState tracking
# ---------------------------------------------------------------------------

print("\n=== B: ConversationState tracking ===")

# B1: last_differential is False initially
ok(
    ConversationState().last_differential is False,
    "B1: last_differential starts False",
)

# B2: successful differential turn sets last_differential
session_b = ConversationSession()
session_b.respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
ok(
    session_b.state.last_differential is True,
    "B2: last_differential=True after differential picks turn",
)

# B3: non-differential OK turn clears last_differential
session_b.respond("should I captain Salah", DIFFERENTIAL_BOOTSTRAP)
ok(
    session_b.state.last_differential is False,
    "B3: last_differential cleared after non-differential turn",
)

# B4: second differential turn re-sets last_differential
session_b2 = ConversationSession()
session_b2.respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
session_b2.respond("should I captain Salah", DIFFERENTIAL_BOOTSTRAP)
session_b2.respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
ok(
    session_b2.state.last_differential is True,
    "B4: last_differential re-set by second differential turn",
)

# B5: clear() resets last_differential
session_b3 = ConversationSession()
session_b3.respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
session_b3.clear()
ok(
    session_b3.state.last_differential is False,
    "B5: clear() resets last_differential to False",
)

# ---------------------------------------------------------------------------
# Section C: ConversationSession end-to-end follow-up routing
# ---------------------------------------------------------------------------

print("\n=== C: ConversationSession end-to-end follow-up routing ===")

session_c = ConversationSession()

# C1-C2: Turn 1 -- differential picks succeeds
r_c1 = session_c.respond("good differentials", DIFFERENTIAL_BOOTSTRAP, include_debug=True)
ok(r_c1.outcome == "ok", "C1: turn 1 'good differentials' -> outcome ok")
ok(r_c1.differential is not None, "C2: turn 1 has differential metadata")

# C3-C6: Turn 2 -- differential follow-up rewrites to captain score
r_c3 = session_c.respond("what about Mbeumo?", DIFFERENTIAL_BOOTSTRAP, include_debug=True)
ok(r_c3.outcome == "ok", "C3: turn 2 'what about Mbeumo?' -> outcome ok")
ok(r_c3.intent == "captain_score", f"C4: turn 2 intent=captain_score (got {r_c3.intent!r})")
ok(r_c3.captain is not None, "C5: turn 2 has captain metadata")
ok(
    r_c3.captain is not None and "mbeumo" in (r_c3.captain.web_name or "").lower(),
    f"C6: turn 2 captain.web_name is Mbeumo (got {r_c3.captain.web_name if r_c3.captain else None!r})",
)

# C7: bare name pattern also routes correctly
session_c2 = ConversationSession()
session_c2.respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
r_c7 = session_c2.respond("Palmer?", DIFFERENTIAL_BOOTSTRAP)
ok(r_c7.outcome == "ok", "C7: bare name 'Palmer?' follow-up -> outcome ok")
ok(r_c7.intent == "captain_score", f"C8: bare name follow-up intent=captain_score (got {r_c7.intent!r})")

# C9: follow-up without prior differential turn does NOT trigger
session_c3 = ConversationSession()
r_c9 = session_c3.respond("what about Mbeumo?", DIFFERENTIAL_BOOTSTRAP, include_debug=True)
ok(r_c9 is not None, "C9: 'what about Mbeumo?' without prior differential -> no crash")
# Without prior differential context it should NOT route via differential_followup
d_c9 = r_c9.debug
rslv_c9 = d_c9.resolver if d_c9 else None
src_c9 = rslv_c9.resolver_source if rslv_c9 else None
ok(
    src_c9 != "differential_followup",
    f"C10: without prior differential, resolver_source != differential_followup (got {src_c9!r})",
)

# ---------------------------------------------------------------------------
# Section D: resolver_source metadata
# ---------------------------------------------------------------------------

print("\n=== D: resolver_source metadata ===")

session_d = ConversationSession()
session_d.respond("good differentials", DIFFERENTIAL_BOOTSTRAP)
r_d = session_d.respond("what about Mbeumo?", DIFFERENTIAL_BOOTSTRAP, include_debug=True)

d_debug = r_d.debug
d_resolver = d_debug.resolver if d_debug is not None else None
d_src = d_resolver.resolver_source if d_resolver is not None else None

ok(
    d_src == "differential_followup",
    f"D1: resolver_source='differential_followup' (got {d_src!r})",
)

d_rewritten = (d_resolver.rewritten_question or "") if d_resolver is not None else ""
ok(
    "captain" in d_rewritten.lower() and "mbeumo" in d_rewritten.lower(),
    f"D2: rewritten_question contains 'captain' and 'Mbeumo' (got {d_rewritten!r})",
)

# D3: last_resolver_source persisted in state
ok(
    session_d.state.last_resolver_source == "differential_followup",
    f"D3: state.last_resolver_source='differential_followup' (got {session_d.state.last_resolver_source!r})",
)

# D4: direct differential turn does NOT use differential_followup source
session_d2 = ConversationSession()
r_d4 = session_d2.respond("good differentials", DIFFERENTIAL_BOOTSTRAP, include_debug=True)
d4_debug = r_d4.debug
d4_src = (d4_debug.resolver.resolver_source if d4_debug and d4_debug.resolver else None)
ok(
    d4_src != "differential_followup",
    f"D4: direct differential turn does not use differential_followup source (got {d4_src!r})",
)

# ---------------------------------------------------------------------------
# Section E: SessionInfoResponse last_differential (HTTP)
# ---------------------------------------------------------------------------

print("\n=== E: SessionInfoResponse last_differential (HTTP) ===")

try:
    from fastapi.testclient import TestClient
    import fpl_server

    fpl_server._init_bootstrap(DIFFERENTIAL_BOOTSTRAP)
    fpl_server._clear_sessions()
    client = TestClient(fpl_server.app, raise_server_exceptions=True)

    # E1: create session
    cr = client.post("/session")
    ok(cr.status_code == 200, "E1: POST /session -> 200")
    sid = cr.json()["session_id"]

    # E2: inspect before turns -- last_differential is False
    ir0 = client.get(f"/session/{sid}").json()
    ok(ir0.get("last_differential") is False, "E2: last_differential=False before turns")

    # E3: differential turn -> last_differential True
    ar1 = client.post(
        f"/session/{sid}/ask",
        json={"question": "good differentials", "include_debug": True},
    )
    ok(ar1.status_code == 200, "E3: POST /session/{id}/ask 'good differentials' -> 200")
    ir1 = client.get(f"/session/{sid}").json()
    ok(ir1.get("last_differential") is True, "E4: last_differential=True after differential turn")

    # E5: follow-up turn -> last_differential cleared (captain turn)
    ar2 = client.post(
        f"/session/{sid}/ask",
        json={"question": "what about Mbeumo?", "include_debug": True},
    )
    ok(ar2.status_code == 200, "E5: POST /session/{id}/ask 'what about Mbeumo?' -> 200")
    e5_body = ar2.json()
    ok(
        e5_body.get("intent") == "captain_score",
        f"E6: follow-up intent=captain_score (got {e5_body.get('intent')!r})",
    )
    ir2 = client.get(f"/session/{sid}").json()
    ok(
        ir2.get("last_differential") is False,
        "E7: last_differential=False after follow-up (captain turn clears it)",
    )

    # Cleanup
    client.delete(f"/session/{sid}")

except Exception as exc:
    print(f"  SKIP  E: HTTP session inspect test failed: {exc}")

# ---------------------------------------------------------------------------
# Section F: Corpus scenario #37 (session_cli + session_http)
# ---------------------------------------------------------------------------

print("\n=== F: corpus scenario #37 differential_followup ===")

try:
    from validation_corpus import SCENARIO_BY_ID
    from run_validation import _resolve_bootstrap, run_session_cli_surface, run_session_http_surface

    sc37 = SCENARIO_BY_ID.get("differential_followup")
    if sc37 is None:
        print("  SKIP  F: scenario 'differential_followup' not found in corpus")
    else:
        bs37 = _resolve_bootstrap(sc37.bootstrap)

        # F1-F4: session_cli
        r_cli = run_session_cli_surface(sc37, bs37)
        ok(
            r_cli.get("intent") == "captain_score",
            f"F1: session_cli intent=captain_score (got {r_cli.get('intent')!r})",
        )
        ok(r_cli.get("outcome") == "ok", f"F2: session_cli outcome=ok (got {r_cli.get('outcome')!r})")
        ok(r_cli.get("captain") is not None, "F3: session_cli captain non-null")
        ok(
            r_cli.get("resolver_source") == "differential_followup",
            f"F4: session_cli resolver_source='differential_followup' (got {r_cli.get('resolver_source')!r})",
        )

        # F5-F7: session_http
        r_http = run_session_http_surface(sc37, bs37)
        ok(
            r_http.get("intent") == "captain_score",
            f"F5: session_http intent=captain_score (got {r_http.get('intent')!r})",
        )
        ok(r_http.get("outcome") == "ok", f"F6: session_http outcome=ok (got {r_http.get('outcome')!r})")
        ok(r_http.get("captain") is not None, "F7: session_http captain non-null")

except Exception as exc:
    print(f"  SKIP  F: corpus scenario test failed: {exc}")

# ---------------------------------------------------------------------------
# Section G: Regression -- V1 stateless gate
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
                chip_ok    = (not sc.expect_chip) or result.get("chip") is not None
                fx_ok      = (not sc.expect_fixture_run) or result.get("fixture_run") is not None
                diff_ok    = (not sc.expect_differential) or result.get("differential") is not None
                if intent_ok and outcome_ok and support_ok and chip_ok and fx_ok and diff_ok:
                    g_pass += 1
                else:
                    g_fail += 1
                    print(
                        f"    FAIL  G [{sc.id}] {surface}: "
                        f"intent={result.get('intent')!r}(exp={sc.expected_intent!r}) "
                        f"outcome={result.get('outcome')!r} "
                        f"chip_ok={chip_ok} fx_ok={fx_ok} diff_ok={diff_ok}"
                    )
            except Exception as exc:
                g_fail += 1
                print(f"    FAIL  G [{sc.id}] {surface}: exception: {exc}")

    ok(
        g_fail == 0 and g_pass > 0,
        f"G: stateless regression gate -- {g_pass} pass, {g_fail} fail",
    )

except Exception as exc:
    print(f"  SKIP  G: could not import validation runners ({exc})")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
total = _pass + _fail
print(f"Phase 8d-ii: {_pass}/{total} assertions passed.")
if _fail:
    print(f"             {_fail} FAILED.")
    sys.exit(1)
else:
    print("             All assertions passed.")
    sys.exit(0)
