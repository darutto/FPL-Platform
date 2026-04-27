"""
run_phase8e2_tests.py
======================
Phase 8e2: Free Transfers Plumbing and Hit Warning.

Sections
--------
A  TransferMeta.hit_warning -- field present, correct default
B  Hit warning condition -- marginal_transfer_in + free_transfers==1 fires
C  Boundary: recommendation != marginal_transfer_in -> no warning
D  Boundary: free_transfers != 1 -> no warning
E  No squad_context baseline unchanged
F  budget_constraint and hit_warning are independent and composable
G  CLI surface -- hit_warning in debug JSON
H  HTTP /ask surface -- free_transfers in squad_context
I  HTTP /session ask surface -- free_transfers per-turn
J  Multi-intent forwarding -- hit_warning applies inside multi-intent
K  Corpus scenario -- transfer_hit_warning scenario
L  Regression: V1 stateless gate (all stateless scenarios)

Run from packages/fpl-grounded-assistant::

    python run_phase8e2_tests.py
"""
from __future__ import annotations

import copy
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

from fpl_grounded_assistant import respond, TransferMeta
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


# ---------------------------------------------------------------------------
# MARGINAL_TRANSFER_BOOTSTRAP
# ---------------------------------------------------------------------------
# STANDARD_BOOTSTRAP has Haaland form=8.0 (score ~54.85) and Salah form=9.5
# (score ~60.58), giving a delta of ~5.73 -> transfer_in (not marginal).
#
# Raise Haaland form to 9.1 to get captain_score ~59.25, making the delta
# Salah-Haaland ~1.33 -> marginal_transfer_in.
#
# This bootstrap is only used in sections that need a marginal recommendation.

MARGINAL_TRANSFER_BOOTSTRAP: dict = copy.deepcopy(STANDARD_BOOTSTRAP)
for _e in MARGINAL_TRANSFER_BOOTSTRAP["elements"]:
    if _e["web_name"] == "Haaland":
        _e["form"] = "9.1"
        break


# ---------------------------------------------------------------------------
# squad_context fixtures
# ---------------------------------------------------------------------------

_SC_FT1_MARGINAL = {"free_transfers": 1}   # 1 FT + marginal -> warning fires
_SC_FT2_MARGINAL = {"free_transfers": 2}   # 2 FTs -> warning never fires
_SC_FT0_MARGINAL = {"free_transfers": 0}   # 0 FTs -> warning never fires (edge)
_SC_FT1_CLEAR    = {"free_transfers": 1}   # 1 FT but transfer_in -> no warning
# (same dict for clarity — intent differs by bootstrap used)

# For the budget+hit composition test:
# Haaland->Salah with MARGINAL_TRANSFER_BOOTSTRAP: price_delta = 135-145 = -10 (cheaper)
# Use Haaland->Salah as the MARGINAL case.
# To also test budget_constraint alongside: we need a case where player_in > player_out.
# Salah->Haaland gives hold (not marginal). Marginal is Haaland->Salah.
# Haaland (145) -> Salah (135): price_delta = -10 (cheaper), so budget_constraint never fires.
# The two constraints are thus tested independently.


# ---------------------------------------------------------------------------
# Section A: TransferMeta.hit_warning field
# ---------------------------------------------------------------------------

print("\n=== A: TransferMeta.hit_warning field ===")

# A1: field present with default False when no squad_context
r_a1 = respond("should I sell Haaland for Salah", STANDARD_BOOTSTRAP)
ok(r_a1.transfer is not None, "A1: transfer meta populated")
ok(
    r_a1.transfer is not None and r_a1.transfer.hit_warning is False,
    "A2: hit_warning defaults to False when no squad_context",
)

# A3: field present with default False when free_transfers absent from squad_context
r_a3 = respond(
    "should I sell Haaland for Salah", STANDARD_BOOTSTRAP,
    squad_context={"itb": 100},  # itb present but no free_transfers
)
ok(
    r_a3.transfer is not None and r_a3.transfer.hit_warning is False,
    "A3: hit_warning=False when free_transfers absent from squad_context",
)


# ---------------------------------------------------------------------------
# Section B: Hit warning condition fires correctly
# ---------------------------------------------------------------------------

print("\n=== B: Hit warning condition ===")

# B1: marginal_transfer_in + free_transfers==1 -> hit_warning=True
r_b1 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context=_SC_FT1_MARGINAL,
)
_b1_rec = r_b1.transfer.recommendation if r_b1.transfer else "None"
ok(
    r_b1.transfer is not None and r_b1.transfer.recommendation == "marginal_transfer_in",
    f"B1: MARGINAL_TRANSFER_BOOTSTRAP gives marginal_transfer_in (got {_b1_rec!r})",
)
ok(
    r_b1.transfer is not None and r_b1.transfer.hit_warning is True,
    f"B2: hit_warning=True when free_transfers==1 and marginal_transfer_in",
)

# B3: recommendation field unchanged (marginal_transfer_in, not affected by warning)
ok(
    r_b1.transfer is not None and r_b1.transfer.recommendation == "marginal_transfer_in",
    "B3: recommendation unchanged after hit_warning fires",
)

# B4: final_text is NOT replaced (hit_warning is advisory, not a hard block)
ok(
    r_b1.final_text is not None
    and "Budget constraint" not in r_b1.final_text
    and "Chip unavailable" not in r_b1.final_text,
    f"B4: final_text not overridden by hit_warning (got {r_b1.final_text[:60]!r})",
)


# ---------------------------------------------------------------------------
# Section C: Boundary — recommendation != marginal_transfer_in -> no warning
# ---------------------------------------------------------------------------

print("\n=== C: Recommendation boundary ===")

# C1: transfer_in -> no warning even with free_transfers==1
r_c1 = respond(
    "should I sell Haaland for Salah", STANDARD_BOOTSTRAP,
    squad_context={"free_transfers": 1},
)
_c1_rec = r_c1.transfer.recommendation if r_c1.transfer else "None"
ok(
    r_c1.transfer is not None and r_c1.transfer.recommendation == "transfer_in",
    f"C1: STANDARD_BOOTSTRAP gives transfer_in for Haaland->Salah (got {_c1_rec!r})",
)
ok(
    r_c1.transfer is not None and r_c1.transfer.hit_warning is False,
    "C2: hit_warning=False when recommendation==transfer_in (clear upgrade is worth the hit)",
)

# C3: hold -> no warning even with free_transfers==1
r_c3 = respond(
    "should I sell Salah for Haaland", STANDARD_BOOTSTRAP,
    squad_context={"free_transfers": 1},
)
_c3_rec = r_c3.transfer.recommendation if r_c3.transfer else "None"
ok(
    r_c3.transfer is not None and r_c3.transfer.recommendation == "hold",
    f"C3: STANDARD_BOOTSTRAP gives hold for Salah->Haaland (got {_c3_rec!r})",
)
ok(
    r_c3.transfer is not None and r_c3.transfer.hit_warning is False,
    "C4: hit_warning=False when recommendation==hold",
)


# ---------------------------------------------------------------------------
# Section D: Boundary — free_transfers != 1 -> no warning
# ---------------------------------------------------------------------------

print("\n=== D: free_transfers boundary ===")

# D1: free_transfers==2 -> no warning
r_d1 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={"free_transfers": 2},
)
ok(
    r_d1.transfer is not None and r_d1.transfer.hit_warning is False,
    "D1: hit_warning=False when free_transfers==2",
)

# D2: free_transfers==0 -> no warning (0 is not 1)
r_d2 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={"free_transfers": 0},
)
ok(
    r_d2.transfer is not None and r_d2.transfer.hit_warning is False,
    "D2: hit_warning=False when free_transfers==0",
)

# D3: free_transfers absent -> no warning
r_d3 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={},
)
ok(
    r_d3.transfer is not None and r_d3.transfer.hit_warning is False,
    "D3: hit_warning=False when free_transfers absent from squad_context",
)

# D4: free_transfers==1 with STANDARD_BOOTSTRAP (transfer_in, not marginal) -> no warning
r_d4 = respond(
    "should I sell Haaland for Salah", STANDARD_BOOTSTRAP,
    squad_context={"free_transfers": 1},
)
ok(
    r_d4.transfer is not None and r_d4.transfer.hit_warning is False,
    "D4: hit_warning=False when free_transfers==1 but recommendation==transfer_in",
)


# ---------------------------------------------------------------------------
# Section E: No squad_context baseline unchanged
# ---------------------------------------------------------------------------

print("\n=== E: No squad_context baseline ===")

r_e1 = respond("should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP)
r_e2 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context=None,
)
ok(
    r_e1.transfer is not None and r_e1.transfer.hit_warning is False,
    "E1: hit_warning=False with no squad_context",
)
ok(
    r_e1.final_text == r_e2.final_text,
    "E2: squad_context=None identical to omitting squad_context",
)
ok(
    r_e2.transfer is not None and r_e2.transfer.hit_warning is False,
    "E3: squad_context=None -> hit_warning=False",
)


# ---------------------------------------------------------------------------
# Section F: budget_constraint and hit_warning are independent and composable
# ---------------------------------------------------------------------------

print("\n=== F: budget_constraint and hit_warning composable ===")

# F1: budget_constraint fires, hit_warning does not (transfer_in, not marginal)
# Saka->Salah: transfer_in, price_delta=35 (£3.5m), itb=20 (£2.0m) -> budget constrained
r_f1 = respond(
    "should I sell Saka for Salah", STANDARD_BOOTSTRAP,
    squad_context={"itb": 20, "free_transfers": 1},
)
ok(
    r_f1.transfer is not None and r_f1.transfer.budget_constraint is True,
    "F1: budget_constraint=True fires (Saka->Salah, itb=20)",
)
ok(
    r_f1.transfer is not None and r_f1.transfer.hit_warning is False,
    "F2: hit_warning=False when recommendation==transfer_in (even with free_transfers==1)",
)

# F3: hit_warning fires, budget_constraint does not (marginal, player_in cheaper)
# Haaland(145)->Salah(135): price_delta=-10, so budget_constraint never fires;
# but marginal + free_transfers==1 -> hit_warning
r_f3 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={"itb": 5, "free_transfers": 1},  # itb=5 but price_delta=-10 (cheaper)
)
ok(
    r_f3.transfer is not None and r_f3.transfer.budget_constraint is False,
    "F3: budget_constraint=False when player_in is cheaper (price_delta negative)",
)
ok(
    r_f3.transfer is not None and r_f3.transfer.hit_warning is True,
    "F4: hit_warning=True fires independently of budget_constraint",
)

# F5: both flags False (generous itb, free_transfers==2)
r_f5 = respond(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={"itb": 100, "free_transfers": 2},
)
ok(
    r_f5.transfer is not None
    and r_f5.transfer.budget_constraint is False
    and r_f5.transfer.hit_warning is False,
    "F5: both flags False when itb generous and free_transfers==2",
)


# ---------------------------------------------------------------------------
# Section G: CLI surface -- hit_warning in debug JSON
# ---------------------------------------------------------------------------

print("\n=== G: CLI surface ===")

# G1: hit_warning=True in CLI debug JSON
_, g1_out = cli_run(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    debug=True,
    squad_context={"free_transfers": 1},
)
import json as _json
g1_body = _json.loads(g1_out)
ok(
    g1_body.get("transfer", {}).get("hit_warning") is True,
    f"G1: CLI debug JSON has transfer.hit_warning=True (got {g1_body.get('transfer', {}).get('hit_warning')})",
)
ok(
    g1_body.get("transfer", {}).get("recommendation") == "marginal_transfer_in",
    "G2: CLI debug JSON transfer.recommendation unchanged",
)

# G3: hit_warning=False in CLI debug JSON when free_transfers absent
_, g3_out = cli_run(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    debug=True,
)
g3_body = _json.loads(g3_out)
ok(
    g3_body.get("transfer", {}).get("hit_warning") is False,
    "G3: no squad_context -> hit_warning=False in CLI JSON",
)

# G4: hit_warning=False in CLI debug JSON when free_transfers==2
_, g4_out = cli_run(
    "should I sell Haaland for Salah", MARGINAL_TRANSFER_BOOTSTRAP,
    debug=True,
    squad_context={"free_transfers": 2},
)
g4_body = _json.loads(g4_out)
ok(
    g4_body.get("transfer", {}).get("hit_warning") is False,
    "G4: free_transfers==2 -> hit_warning=False in CLI JSON",
)


# ---------------------------------------------------------------------------
# Section H: HTTP /ask surface
# ---------------------------------------------------------------------------

print("\n=== H: HTTP /ask surface ===")

fpl_server._init_bootstrap(MARGINAL_TRANSFER_BOOTSTRAP)
http_client = TestClient(fpl_server.app, raise_server_exceptions=True)

# H1: hit_warning=True in /ask response with free_transfers==1
h1_resp = http_client.post("/ask", json={
    "question": "should I sell Haaland for Salah",
    "squad_context": {"free_transfers": 1},
})
ok(h1_resp.status_code == 200, "H1: POST /ask with free_transfers -> 200")
h1_body = h1_resp.json()
ok(
    h1_body.get("transfer", {}).get("hit_warning") is True,
    f"H2: HTTP /ask transfer.hit_warning=True (got {h1_body.get('transfer', {}).get('hit_warning')})",
)

# H3: hit_warning=False without squad_context
h3_resp = http_client.post("/ask", json={"question": "should I sell Haaland for Salah"})
ok(h3_resp.status_code == 200, "H3: POST /ask without squad_context -> 200")
ok(
    h3_resp.json().get("transfer", {}).get("hit_warning") is False,
    "H4: no squad_context -> hit_warning=False in HTTP response",
)

# H5: hit_warning=False with free_transfers==2
h5_resp = http_client.post("/ask", json={
    "question": "should I sell Haaland for Salah",
    "squad_context": {"free_transfers": 2},
})
ok(
    h5_resp.json().get("transfer", {}).get("hit_warning") is False,
    "H5: free_transfers==2 -> hit_warning=False in HTTP response",
)


# ---------------------------------------------------------------------------
# Section I: HTTP /session ask surface
# ---------------------------------------------------------------------------

print("\n=== I: HTTP /session ask surface ===")

fpl_server._init_bootstrap(MARGINAL_TRANSFER_BOOTSTRAP)
fpl_server._clear_sessions()
sess_client = TestClient(fpl_server.app, raise_server_exceptions=True)
sess_id = sess_client.post("/session").json()["session_id"]

# I1: hit_warning=True in session turn with free_transfers==1
i1_resp = sess_client.post(f"/session/{sess_id}/ask", json={
    "question": "should I sell Haaland for Salah",
    "squad_context": {"free_transfers": 1},
})
ok(i1_resp.status_code == 200, "I1: session ask with free_transfers -> 200")
ok(
    i1_resp.json().get("transfer", {}).get("hit_warning") is True,
    "I2: session ask transfer.hit_warning=True",
)

# I3: next turn without squad_context reverts to unconstrained
i3_resp = sess_client.post(f"/session/{sess_id}/ask", json={
    "question": "should I sell Haaland for Salah",
})
ok(
    i3_resp.json().get("transfer", {}).get("hit_warning") is False,
    "I3: subsequent turn without squad_context -> hit_warning=False",
)

sess_client.delete(f"/session/{sess_id}")


# ---------------------------------------------------------------------------
# Section J: Multi-intent forwarding
# ---------------------------------------------------------------------------

print("\n=== J: Multi-intent forwarding ===")

# J1: hit_warning forwarded to transfer sub-intent in multi-intent turn
# "should I sell Haaland for Salah and should I use my triple captain"
_MULTI_Q = "should I sell Haaland for Salah and should I use my triple captain"
r_j1 = respond(
    _MULTI_Q, MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={"free_transfers": 1},
)
ok(
    r_j1.intent == "multi_intent",
    f"J1: multi-intent detected (intent={r_j1.intent!r})",
)
_transfer_sub = next(
    (s for s in (r_j1.sub_responses or []) if s.transfer is not None), None
)
_j2_hw = _transfer_sub.transfer.hit_warning if _transfer_sub else "no sub"
ok(
    _transfer_sub is not None and _transfer_sub.transfer.hit_warning is True,
    f"J2: transfer sub-response has hit_warning=True (got {_j2_hw!r})",
)

# J3: no squad_context multi-intent -> hit_warning=False in transfer sub
r_j3 = respond(_MULTI_Q, MARGINAL_TRANSFER_BOOTSTRAP)
_transfer_sub_j3 = next(
    (s for s in (r_j3.sub_responses or []) if s.transfer is not None), None
)
ok(
    _transfer_sub_j3 is not None and _transfer_sub_j3.transfer.hit_warning is False,
    "J3: no squad_context multi-intent -> transfer sub hit_warning=False",
)

# J4: free_transfers==2 multi-intent -> hit_warning=False
r_j4 = respond(
    _MULTI_Q, MARGINAL_TRANSFER_BOOTSTRAP,
    squad_context={"free_transfers": 2},
)
_transfer_sub_j4 = next(
    (s for s in (r_j4.sub_responses or []) if s.transfer is not None), None
)
ok(
    _transfer_sub_j4 is not None and _transfer_sub_j4.transfer.hit_warning is False,
    "J4: free_transfers==2 multi-intent -> transfer sub hit_warning=False",
)


# ---------------------------------------------------------------------------
# Section K: Corpus scenario
# ---------------------------------------------------------------------------

print("\n=== K: Corpus scenario ===")

from validation_corpus import SCENARIO_BY_ID
from run_validation import run_cli_surface, run_http_surface, _resolve_bootstrap, _check_scenario_result

for sid in ["transfer_hit_warning"]:
    scenario = SCENARIO_BY_ID[sid]
    bs = _resolve_bootstrap(scenario.bootstrap)
    for runner, sname in [(run_cli_surface, "cli"), (run_http_surface, "http")]:
        sr = runner(scenario, bs)
        fails = _check_scenario_result(scenario, sname, sr)
        ok(
            not fails,
            f"K: corpus/{sid}/{sname} passes all assertions"
            + (f" ({fails[0]})" if fails else ""),
        )

# K-extra: verify hit_warning=True in corpus runner output
_hw_cli = run_cli_surface(SCENARIO_BY_ID["transfer_hit_warning"], bs)
ok(
    _hw_cli.get("transfer", {}).get("hit_warning") is True,
    "K-extra: corpus transfer_hit_warning cli -> hit_warning=True in result",
)


# ---------------------------------------------------------------------------
# Section L: V1 stateless regression gate
# ---------------------------------------------------------------------------

print("\n=== L: V1 stateless regression gate ===")

from run_validation import run_all_scenarios

l_results = run_all_scenarios()
l_all_pass = all(r.get("pass") for r in l_results)
l_fail_ids = [r["id"] for r in l_results if not r.get("pass")]
ok(
    l_all_pass,
    f"L: full validation corpus passes ({len(l_results)} scenarios)"
    + (f" -- FAIL: {l_fail_ids}" if l_fail_ids else ""),
)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total = _pass + _fail
print(f"\n{'=' * 50}")
print(f"Phase 8e2: {_pass}/{total} assertions passed.")
if _fail == 0:
    print("            All assertions passed.")
else:
    print(f"            {_fail} assertion(s) FAILED.")
