"""
run_phase8e1_tests.py
======================
Phase 8e1: Squad context plumbing and hard constraint overrides.

Sections
--------
A  TransferMeta.budget_constraint -- field present, correct default
B  ChipAdviceMeta.chip_unavailable -- field present, correct default
C  Transfer budget constraint logic -- boundary, below, above, negative delta
D  Chip unavailable logic -- chip absent, chip present, empty list
E  squad_context=None preserves existing behavior
F  CLI surface parity -- budget_constraint and chip_unavailable in debug JSON
G  HTTP /ask surface -- squad_context in request body
H  HTTP /session ask -- squad_context in session turn
I  Corpus scenarios -- transfer_budget_constraint and chip_unavailable_tc
J  Regression: V1 stateless gate (cli+http, all stateless scenarios)
K  Multi-intent with squad_context -- constraints forwarded to each sub-call

Run from packages/fpl-grounded-assistant::

    python run_phase8e1_tests.py
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

from fpl_grounded_assistant import respond, TransferMeta, ChipAdviceMeta
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_cli import run as cli_run
import fpl_server
from fastapi.testclient import TestClient

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


# squad_context fixtures
# Saka now_cost=100 (£10.0m), Salah now_cost=135 (£13.5m)
# price_delta = 135 - 100 = 35 (£3.5m upgrade)
_SC_TRANSFER_CONSTRAINED = {"itb": 20}   # £2.0m < £3.5m -> constrained
_SC_TRANSFER_UNCONSTRAINED = {"itb": 50} # £5.0m > £3.5m -> not constrained
_SC_TC_UNAVAILABLE = {"chips_remaining": ["wildcard", "bench_boost", "free_hit"]}
_SC_TC_AVAILABLE = {"chips_remaining": ["triple_captain", "wildcard"]}


# ---------------------------------------------------------------------------
# Section A: TransferMeta.budget_constraint field
# ---------------------------------------------------------------------------

print("\n=== A: TransferMeta.budget_constraint field ===")

# A1: field exists with default False when no squad_context
r_a1 = respond("should I sell Saka for Salah", STANDARD_BOOTSTRAP)
ok(r_a1.transfer is not None, "A1: transfer meta populated for transfer question")
ok(
    r_a1.transfer is not None and r_a1.transfer.budget_constraint is False,
    "A2: budget_constraint defaults to False when no squad_context",
)

# A3: field is False when itb is generous
r_a3 = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context=_SC_TRANSFER_UNCONSTRAINED,
)
ok(
    r_a3.transfer is not None and r_a3.transfer.budget_constraint is False,
    "A3: budget_constraint=False when itb > price_delta",
)

# A4: field is True when constrained
r_a4 = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context=_SC_TRANSFER_CONSTRAINED,
)
ok(
    r_a4.transfer is not None and r_a4.transfer.budget_constraint is True,
    "A4: budget_constraint=True when price_delta > itb",
)


# ---------------------------------------------------------------------------
# Section B: ChipAdviceMeta.chip_unavailable field
# ---------------------------------------------------------------------------

print("\n=== B: ChipAdviceMeta.chip_unavailable field ===")

# B1: field exists with default False when no squad_context
r_b1 = respond("should I use my triple captain", STANDARD_BOOTSTRAP)
ok(r_b1.chip is not None, "B1: chip meta populated for chip question")
ok(
    r_b1.chip is not None and r_b1.chip.chip_unavailable is False,
    "B2: chip_unavailable defaults to False when no squad_context",
)

# B3: field is False when chip IS in chips_remaining
r_b3 = respond(
    "should I use my triple captain", STANDARD_BOOTSTRAP,
    squad_context=_SC_TC_AVAILABLE,
)
ok(
    r_b3.chip is not None and r_b3.chip.chip_unavailable is False,
    "B3: chip_unavailable=False when chip in chips_remaining",
)

# B4: field is True when chip NOT in chips_remaining
r_b4 = respond(
    "should I use my triple captain", STANDARD_BOOTSTRAP,
    squad_context=_SC_TC_UNAVAILABLE,
)
ok(
    r_b4.chip is not None and r_b4.chip.chip_unavailable is True,
    "B4: chip_unavailable=True when chip not in chips_remaining",
)


# ---------------------------------------------------------------------------
# Section C: Transfer budget constraint boundary and behavior
# ---------------------------------------------------------------------------

print("\n=== C: Transfer budget constraint boundary ===")

# C1: price_delta=35, itb=35 -- exactly equal: NOT constrained (> not >=)
r_c1 = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context={"itb": 35},
)
ok(
    r_c1.transfer is not None and r_c1.transfer.budget_constraint is False,
    "C1: price_delta == itb -> not constrained (strict >)",
)

# C2: price_delta=35, itb=34 -- just below: IS constrained
r_c2 = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context={"itb": 34},
)
ok(
    r_c2.transfer is not None and r_c2.transfer.budget_constraint is True,
    "C2: price_delta > itb by 1 -> constrained",
)

# C3: final_text contains constraint message when constrained
r_c3 = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context=_SC_TRANSFER_CONSTRAINED,
)
ok(
    "Budget constraint" in r_c3.final_text,
    f"C3: final_text contains 'Budget constraint' (got {r_c3.final_text[:60]!r})",
)
ok(
    "Salah" in r_c3.final_text,
    f"C4: final_text mentions player_in name (got {r_c3.final_text[:80]!r})",
)
ok(
    "2.0m" in r_c3.final_text or "2.0" in r_c3.final_text,
    f"C5: final_text mentions itb amount in £m (got {r_c3.final_text!r})",
)

# C6: recommendation field unchanged (score-based, before override)
ok(
    r_c3.transfer is not None and r_c3.transfer.recommendation in (
        "transfer_in", "marginal_transfer_in", "hold"
    ),
    f"C6: recommendation still holds score-based value (got {r_c3.transfer.recommendation!r})",
)

# C7: negative price_delta (cheaper player_in): constraint never fires even with itb=0
r_c7 = respond(
    "should I sell Salah for Saka", STANDARD_BOOTSTRAP,
    squad_context={"itb": 0},
)
ok(
    r_c7.transfer is None or r_c7.transfer.budget_constraint is False,
    "C7: negative price_delta -> constraint never fires (player_in is cheaper)",
)

# C8: no squad_context -> final_text is the regular response (not constraint message)
r_c8 = respond("should I sell Saka for Salah", STANDARD_BOOTSTRAP)
ok(
    "Budget constraint" not in r_c8.final_text,
    "C8: no squad_context -> no budget constraint message",
)


# ---------------------------------------------------------------------------
# Section D: Chip unavailable logic
# ---------------------------------------------------------------------------

print("\n=== D: Chip unavailable logic ===")

# D1: final_text contains unavailable message when chip not in list
r_d1 = respond(
    "should I use my triple captain", STANDARD_BOOTSTRAP,
    squad_context=_SC_TC_UNAVAILABLE,
)
ok(
    "Chip unavailable" in r_d1.final_text,
    f"D1: final_text contains 'Chip unavailable' (got {r_d1.final_text!r})",
)
ok(
    "triple_captain" in r_d1.final_text,
    f"D2: final_text mentions chip name (got {r_d1.final_text!r})",
)

# D3: recommendation field unchanged (conditions-based)
ok(
    r_d1.chip is not None and r_d1.chip.recommendation in (
        "conditions_favorable", "conditions_marginal",
        "conditions_unfavorable", "missing_context",
    ),
    f"D3: chip.recommendation still holds conditions value (got {r_d1.chip.recommendation!r})",
)

# D4: chip available -> no message override
r_d4 = respond(
    "should I use my triple captain", STANDARD_BOOTSTRAP,
    squad_context=_SC_TC_AVAILABLE,
)
ok(
    "Chip unavailable" not in r_d4.final_text,
    "D4: chip available -> no unavailable message",
)

# D5: empty chips_remaining -> all chips unavailable
r_d5 = respond(
    "should I use my triple captain", STANDARD_BOOTSTRAP,
    squad_context={"chips_remaining": []},
)
ok(
    r_d5.chip is not None and r_d5.chip.chip_unavailable is True,
    "D5: empty chips_remaining -> chip_unavailable=True",
)

# D6: wildcard unavailable check
r_d6 = respond(
    "should I use my wildcard", STANDARD_BOOTSTRAP,
    squad_context={"chips_remaining": ["triple_captain", "bench_boost"]},
)
ok(
    r_d6.chip is not None and r_d6.chip.chip_unavailable is True,
    "D6: wildcard not in chips_remaining -> chip_unavailable=True",
)

# D7: no squad_context -> final_text is regular advice (no override)
r_d7 = respond("should I use my triple captain", STANDARD_BOOTSTRAP)
ok(
    "Chip unavailable" not in r_d7.final_text,
    "D7: no squad_context -> no chip unavailable message",
)


# ---------------------------------------------------------------------------
# Section E: squad_context=None preserves existing behavior
# ---------------------------------------------------------------------------

print("\n=== E: squad_context=None preserves existing behavior ===")

r_e_no_ctx = respond("should I sell Saka for Salah", STANDARD_BOOTSTRAP)
r_e_none = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context=None,
)
ok(
    (r_e_no_ctx.transfer is not None) == (r_e_none.transfer is not None),
    "E1: squad_context=None identical to omitting squad_context (transfer present)",
)
ok(
    r_e_no_ctx.final_text == r_e_none.final_text,
    "E2: squad_context=None -> identical final_text",
)
ok(
    r_e_none.transfer is not None and r_e_none.transfer.budget_constraint is False,
    "E3: squad_context=None -> budget_constraint=False",
)


# ---------------------------------------------------------------------------
# Section F: CLI surface parity
# ---------------------------------------------------------------------------

print("\n=== F: CLI surface parity ===")

# F1: budget_constraint=True present in CLI debug JSON
_, f1_out = cli_run(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    debug=True,
    squad_context=_SC_TRANSFER_CONSTRAINED,
)
import json as _json
f1_body = _json.loads(f1_out)
ok(
    f1_body.get("transfer", {}).get("budget_constraint") is True,
    "F1: CLI debug JSON has transfer.budget_constraint=True",
)
ok(
    "Budget constraint" in f1_body.get("final_text", ""),
    "F2: CLI debug JSON final_text contains constraint message",
)

# F3: chip_unavailable=True present in CLI debug JSON
_, f3_out = cli_run(
    "should I use my triple captain", STANDARD_BOOTSTRAP,
    debug=True,
    squad_context=_SC_TC_UNAVAILABLE,
)
f3_body = _json.loads(f3_out)
ok(
    f3_body.get("chip", {}).get("chip_unavailable") is True,
    "F3: CLI debug JSON has chip.chip_unavailable=True",
)
ok(
    "Chip unavailable" in f3_body.get("final_text", ""),
    "F4: CLI debug JSON final_text contains chip unavailable message",
)

# F5: no squad_context -> budget_constraint=False in CLI debug JSON
_, f5_out = cli_run(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    debug=True,
)
f5_body = _json.loads(f5_out)
ok(
    f5_body.get("transfer", {}).get("budget_constraint") is False,
    "F5: no squad_context -> budget_constraint=False in CLI JSON",
)


# ---------------------------------------------------------------------------
# Section G: HTTP /ask surface
# ---------------------------------------------------------------------------

print("\n=== G: HTTP /ask surface ===")

fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
client = TestClient(fpl_server.app, raise_server_exceptions=True)

# G1: budget_constraint in /ask response with squad_context
g1_resp = client.post("/ask", json={
    "question": "should I sell Saka for Salah",
    "squad_context": _SC_TRANSFER_CONSTRAINED,
})
ok(g1_resp.status_code == 200, "G1: POST /ask with squad_context -> 200")
g1_body = g1_resp.json()
ok(
    g1_body.get("transfer", {}).get("budget_constraint") is True,
    f"G2: HTTP /ask transfer.budget_constraint=True (got {g1_body.get('transfer', {}).get('budget_constraint')})",
)
ok(
    "Budget constraint" in g1_body.get("final_text", ""),
    "G3: HTTP /ask final_text contains constraint message",
)

# G4: chip_unavailable in /ask response with squad_context
g4_resp = client.post("/ask", json={
    "question": "should I use my triple captain",
    "squad_context": _SC_TC_UNAVAILABLE,
})
ok(g4_resp.status_code == 200, "G4: POST /ask chip with squad_context -> 200")
g4_body = g4_resp.json()
ok(
    g4_body.get("chip", {}).get("chip_unavailable") is True,
    f"G5: HTTP /ask chip.chip_unavailable=True (got {g4_body.get('chip', {}).get('chip_unavailable')})",
)

# G6: no squad_context -> budget_constraint=False
g6_resp = client.post("/ask", json={"question": "should I sell Saka for Salah"})
ok(g6_resp.status_code == 200, "G6: POST /ask without squad_context -> 200")
ok(
    g6_resp.json().get("transfer", {}).get("budget_constraint") is False,
    "G7: no squad_context -> budget_constraint=False in HTTP response",
)


# ---------------------------------------------------------------------------
# Section H: HTTP /session ask surface
# ---------------------------------------------------------------------------

print("\n=== H: HTTP /session ask surface ===")

fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._clear_sessions()
h_client = TestClient(fpl_server.app, raise_server_exceptions=True)

h_sess = h_client.post("/session").json()["session_id"]

# H1: budget_constraint in session turn
h1_resp = h_client.post(f"/session/{h_sess}/ask", json={
    "question": "should I sell Saka for Salah",
    "squad_context": _SC_TRANSFER_CONSTRAINED,
})
ok(h1_resp.status_code == 200, "H1: session ask with squad_context -> 200")
h1_body = h1_resp.json()
ok(
    h1_body.get("transfer", {}).get("budget_constraint") is True,
    "H2: session ask transfer.budget_constraint=True",
)

# H2: next turn without squad_context is unaffected (stateless per turn)
h3_resp = h_client.post(f"/session/{h_sess}/ask", json={
    "question": "should I sell Saka for Salah",
})
ok(
    h3_resp.json().get("transfer", {}).get("budget_constraint") is False,
    "H3: subsequent turn without squad_context -> budget_constraint=False",
)

h_client.delete(f"/session/{h_sess}")


# ---------------------------------------------------------------------------
# Section I: Corpus scenarios
# ---------------------------------------------------------------------------

print("\n=== I: Corpus scenarios ===")

from validation_corpus import SCENARIO_BY_ID
from run_validation import run_cli_surface, run_http_surface, _resolve_bootstrap, _check_scenario_result

for sid in ["transfer_budget_constraint", "chip_unavailable_tc"]:
    scenario = SCENARIO_BY_ID[sid]
    bs = _resolve_bootstrap(scenario.bootstrap)
    for runner, sname in [(run_cli_surface, "cli"), (run_http_surface, "http")]:
        sr = runner(scenario, bs)
        fails = _check_scenario_result(scenario, sname, sr)
        ok(
            not fails,
            f"I: corpus/{sid}/{sname} passes all assertions" + (f" ({fails[0]})" if fails else ""),
        )

# I-extra: verify budget_constraint=True is in corpus runner output
_bc_cli = run_cli_surface(SCENARIO_BY_ID["transfer_budget_constraint"], STANDARD_BOOTSTRAP)
ok(
    _bc_cli.get("transfer", {}).get("budget_constraint") is True,
    "I-extra1: corpus transfer_budget_constraint cli -> budget_constraint=True in result",
)

_cu_cli = run_cli_surface(SCENARIO_BY_ID["chip_unavailable_tc"], STANDARD_BOOTSTRAP)
ok(
    _cu_cli.get("chip", {}).get("chip_unavailable") is True,
    "I-extra2: corpus chip_unavailable_tc cli -> chip_unavailable=True in result",
)


# ---------------------------------------------------------------------------
# Section K: Multi-intent turns with squad_context
# ---------------------------------------------------------------------------

print("\n=== K: Multi-intent with squad_context ===")

# K1–K3: transfer + chip combined multi-intent with both constraints active
_SC_BOTH = {
    "itb": 20,                                                  # £2.0m < £3.5m -> transfer constrained
    "chips_remaining": ["wildcard", "bench_boost", "free_hit"], # TC absent -> chip constrained
}
_MULTI_Q = "should I sell Saka for Salah and should I use my triple captain"

r_k1 = respond(_MULTI_Q, STANDARD_BOOTSTRAP, squad_context=_SC_BOTH)
ok(
    r_k1.intent == "multi_intent",
    f"K1: multi-intent detected (intent={r_k1.intent!r})",
)
ok(
    r_k1.sub_responses is not None and len(r_k1.sub_responses) == 2,
    f"K2: two sub-responses present (got {len(r_k1.sub_responses) if r_k1.sub_responses else 0})",
)

# K3: transfer sub-response has budget_constraint=True
_transfer_sub = next(
    (s for s in (r_k1.sub_responses or []) if s.transfer is not None), None
)
ok(
    _transfer_sub is not None and _transfer_sub.transfer.budget_constraint is True,
    f"K3: transfer sub-response has budget_constraint=True"
    + (f" (got {_transfer_sub.transfer.budget_constraint!r})" if _transfer_sub else " (no transfer sub)"),
)

# K4: chip sub-response has chip_unavailable=True
_chip_sub = next(
    (s for s in (r_k1.sub_responses or []) if s.chip is not None), None
)
ok(
    _chip_sub is not None and _chip_sub.chip.chip_unavailable is True,
    f"K4: chip sub-response has chip_unavailable=True"
    + (f" (got {_chip_sub.chip.chip_unavailable!r})" if _chip_sub else " (no chip sub)"),
)

# K5: combined final_text contains both constraint messages
ok(
    r_k1.final_text is not None and "Budget constraint" in r_k1.final_text,
    f"K5: combined final_text contains 'Budget constraint' (got {r_k1.final_text[:80]!r})",
)
ok(
    r_k1.final_text is not None and "Chip unavailable" in r_k1.final_text,
    f"K6: combined final_text contains 'Chip unavailable' (got {r_k1.final_text[:80]!r})",
)

# K7: transfer-only constraint in multi-intent (chip available, transfer constrained)
_SC_TRANSFER_ONLY = {
    "itb": 20,
    "chips_remaining": ["triple_captain", "wildcard", "bench_boost", "free_hit"],
}
r_k7 = respond(_MULTI_Q, STANDARD_BOOTSTRAP, squad_context=_SC_TRANSFER_ONLY)
_transfer_sub_k7 = next(
    (s for s in (r_k7.sub_responses or []) if s.transfer is not None), None
)
_chip_sub_k7 = next(
    (s for s in (r_k7.sub_responses or []) if s.chip is not None), None
)
ok(
    _transfer_sub_k7 is not None and _transfer_sub_k7.transfer.budget_constraint is True,
    "K7: transfer-only constrained multi-intent -> transfer sub has budget_constraint=True",
)
ok(
    _chip_sub_k7 is not None and _chip_sub_k7.chip.chip_unavailable is False,
    "K8: transfer-only constrained multi-intent -> chip sub has chip_unavailable=False",
)

# K9: chip-only constraint in multi-intent (chip unavailable, transfer unconstrained)
_SC_CHIP_ONLY = {
    "itb": 50,
    "chips_remaining": ["wildcard", "bench_boost", "free_hit"],
}
r_k9 = respond(_MULTI_Q, STANDARD_BOOTSTRAP, squad_context=_SC_CHIP_ONLY)
_transfer_sub_k9 = next(
    (s for s in (r_k9.sub_responses or []) if s.transfer is not None), None
)
_chip_sub_k9 = next(
    (s for s in (r_k9.sub_responses or []) if s.chip is not None), None
)
ok(
    _transfer_sub_k9 is not None and _transfer_sub_k9.transfer.budget_constraint is False,
    "K9: chip-only constrained multi-intent -> transfer sub has budget_constraint=False",
)
ok(
    _chip_sub_k9 is not None and _chip_sub_k9.chip.chip_unavailable is True,
    "K10: chip-only constrained multi-intent -> chip sub has chip_unavailable=True",
)

# K11: multi-intent without squad_context -> both unconstrained (baseline)
r_k11 = respond(_MULTI_Q, STANDARD_BOOTSTRAP)
_transfer_sub_k11 = next(
    (s for s in (r_k11.sub_responses or []) if s.transfer is not None), None
)
_chip_sub_k11 = next(
    (s for s in (r_k11.sub_responses or []) if s.chip is not None), None
)
ok(
    _transfer_sub_k11 is not None and _transfer_sub_k11.transfer.budget_constraint is False,
    "K11: no squad_context multi-intent -> transfer sub budget_constraint=False",
)
ok(
    _chip_sub_k11 is not None and _chip_sub_k11.chip.chip_unavailable is False,
    "K12: no squad_context multi-intent -> chip sub chip_unavailable=False",
)


# ---------------------------------------------------------------------------
# Section J: V1 stateless regression gate
# ---------------------------------------------------------------------------

print("\n=== J: V1 stateless regression gate ===")

from run_validation import run_all_scenarios

j_results = run_all_scenarios()
j_all_pass = all(r.get("pass") for r in j_results)
j_fail_ids = [r["id"] for r in j_results if not r.get("pass")]
ok(
    j_all_pass,
    f"J: full validation corpus passes ({len(j_results)} scenarios)"
    + (f" -- FAIL: {j_fail_ids}" if j_fail_ids else ""),
)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _pass + _fail
print(f"\n{'=' * 50}")
print(f"Phase 8e1 (incl. K multi-intent): {_pass}/{total} assertions passed.")
if _fail == 0:
    print("            All assertions passed.")
else:
    print(f"            {_fail} assertion(s) FAILED.")
