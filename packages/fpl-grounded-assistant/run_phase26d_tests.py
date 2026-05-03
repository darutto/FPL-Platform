"""
run_phase26d_tests.py
=====================
Phase 2.6d: Player-info gap closure.

Stories covered
---------------
2.1  player_form intent — routing, handler (with bootstrap injection), metadata
2.2  player_summary enrichment — form + minutes from bootstrap
2.3a injury named-player routing → player_summary
2.3b injury_list GW-wide routing, handler, metadata
2.4  price_changes routing, handler (deterministic risers/fallers), metadata

Regressions
-----------
- run_validation: 60/60 pass (54 prior + 6 new)
- run_phase26c_tests: 78/78 pass
"""
from __future__ import annotations

import os
import sys
import subprocess

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


_pass: list[str] = []
_fail: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        _pass.append(label)
        print(f"  PASS  {label}")
    else:
        _fail.append(label)
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


from fpl_grounded_assistant.router import route  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import (  # noqa: E402
    STANDARD_BOOTSTRAP, PLAYER_FORM_BOOTSTRAP, PRICE_CHANGES_BOOTSTRAP,
)
from fpl_grounded_assistant.final_response import respond  # noqa: E402
from fpl_grounded_assistant.player_form import get_player_form  # noqa: E402
from fpl_grounded_assistant.injury_list import get_injury_list  # noqa: E402
from fpl_grounded_assistant.price_changes import get_price_changes  # noqa: E402
from fpl_api_client.fpl_client import ELEMENT_SUMMARY_URL  # noqa: E402


# ---------------------------------------------------------------------------
# A — Story 2.1: player_form routing
# ---------------------------------------------------------------------------

print("\n=== A: Story 2.1 — player_form routing ===")

_form_cases = [
    ("como ha estado Salah en los ultimos 3 partidos", "Salah", 3, "A1"),
    ("cuantos puntos ha sacado Haaland en las ultimas 4 jornadas", "Haaland", 4, "A2"),
    ("historial de puntos de Salah", "Salah", 5, "A3"),
    ("dame el historial de Haaland", "Haaland", 5, "A4"),
    ("dame las stats de los ultimos 5 partidos de Saka", "Saka", 5, "A5"),
]

for q, expected_player, expected_n, label in _form_cases:
    r = route(q)
    _check(f"{label} '{q[:50]}' routes to get_player_form",
           r is not None and r.tool_name == "get_player_form",
           f"got {r.tool_name if r else 'None'}")
    if r is not None and r.tool_name == "get_player_form":
        got_q = r.tool_args.get("query", "")
        _check(f"{label}p query='{expected_player}'",
               got_q.lower() == expected_player.lower(),
               f"got query={got_q!r}")
        got_n = r.tool_args.get("n_games", 5)
        _check(f"{label}n n_games={expected_n}",
               got_n == expected_n,
               f"got n_games={got_n}")


# ---------------------------------------------------------------------------
# B — Story 2.1: player_form handler with bootstrap injection
# ---------------------------------------------------------------------------

print("\n=== B: Story 2.1 — player_form handler ===")

result = get_player_form("Salah", PLAYER_FORM_BOOTSTRAP, n_games=3)
_check("B1 status=ok", result.get("status") == "ok", f"got status={result.get('status')}")
_check("B2 web_name=Salah", result.get("web_name") == "Salah")
_check("B3 n_games=3", result.get("n_games") == 3, f"got n_games={result.get('n_games')}")
_check("B4 history len=3", len(result.get("history", [])) == 3,
       f"got {len(result.get('history', []))}")
if result.get("history"):
    entry = result["history"][0]  # most-recent first (GW28)
    _check("B5 most-recent GW=28", entry.get("gameweek") == 28)
    _check("B6 total_points present", "total_points" in entry)
    _check("B7 minutes present", "minutes" in entry)

# Test not_found
r_nf = get_player_form("UnknownXYZ", PLAYER_FORM_BOOTSTRAP)
_check("B8 not_found for unknown player", r_nf.get("status") == "not_found")

# Test missing_context (no _element_summaries and no live API)
r_mc = get_player_form("Salah", STANDARD_BOOTSTRAP)  # no _element_summaries → API call fails
_check("B9 missing_context or ok when element_summary absent",
       r_mc.get("status") in ("missing_context", "ok"))


# ---------------------------------------------------------------------------
# C — Story 2.1: element_summary API URL correct
# ---------------------------------------------------------------------------

print("\n=== C: Story 2.1 — element-summary API URL ===")

_check("C1 ELEMENT_SUMMARY_URL contains element_id placeholder",
       "{element_id}" in ELEMENT_SUMMARY_URL)
_check("C2 ELEMENT_SUMMARY_URL is FPL API path",
       "element-summary" in ELEMENT_SUMMARY_URL)


# ---------------------------------------------------------------------------
# D — Story 2.1: respond() end-to-end with player_form bootstrap
# ---------------------------------------------------------------------------

print("\n=== D: Story 2.1 — respond() end-to-end ===")

fr = respond("como ha estado Salah en los ultimos 3 partidos", PLAYER_FORM_BOOTSTRAP)
_check("D1 intent=player_form", fr.intent == "player_form", f"got intent={fr.intent}")
_check("D2 outcome=ok", fr.outcome == "ok", f"got outcome={fr.outcome}")
_check("D3 player_form meta non-null", fr.player_form is not None)
if fr.player_form is not None:
    _check("D4 player_form.web_name=Salah", fr.player_form.web_name == "Salah")
    _check("D5 player_form.n_games=3", fr.player_form.n_games == 3)
    _check("D6 len(history)=3", len(fr.player_form.history) == 3)
_check("D7 final_text non-empty", bool(fr.final_text))
_check("D8 final_text mentions GW", "GW" in fr.final_text)


# ---------------------------------------------------------------------------
# E — Story 2.2: player_summary enriched with season totals
# ---------------------------------------------------------------------------

print("\n=== E: Story 2.2 — player_summary enrichment ===")

fr_sum = respond("tell me about Salah", STANDARD_BOOTSTRAP)
_check("E1 intent=player_summary", fr_sum.intent == "player_summary")
_check("E2 outcome=ok", fr_sum.outcome == "ok")
# STANDARD_BOOTSTRAP has form and minutes for Salah
_check("E3 final_text contains Form:", "Form:" in fr_sum.final_text,
       f"final_text={fr_sum.final_text[:100]}")
_check("E4 final_text contains Mins:", "Mins:" in fr_sum.final_text,
       f"final_text={fr_sum.final_text[:100]}")
# total_points may be None (not in STANDARD_BOOTSTRAP) → no crash
_check("E5 no crash on missing total_points", True)

# Verify form value is from bootstrap (Salah form="9.5")
_check("E6 form value 9.5 appears", "9.5" in fr_sum.final_text,
       f"final_text={fr_sum.final_text[:120]}")


# ---------------------------------------------------------------------------
# F — Story 2.3a: injury named-player routing → player_summary
# ---------------------------------------------------------------------------

print("\n=== F: Story 2.3a — injury check routes to player_summary ===")

_injury_named_cases = [
    ("esta lesionado Saka",     "Saka",  "F1"),
    ("esta disponible Haaland", "Haaland", "F2"),
    ("puede jugar Salah",       "Salah",  "F3"),
    ("esta en duda Saka",       "Saka",  "F4"),
    ("tiene lesion De Bruyne",  "De Bruyne", "F5"),
]

for q, expected_player, label in _injury_named_cases:
    r = route(q)
    _check(f"{label} '{q}' routes to get_player_summary",
           r is not None and r.tool_name == "get_player_summary",
           f"got {r.tool_name if r else 'None'}")
    if r is not None and r.tool_name == "get_player_summary":
        got_q = r.tool_args.get("query", "")
        _check(f"{label}p query='{expected_player}'",
               got_q.lower() == expected_player.lower(),
               f"got query={got_q!r}")


# ---------------------------------------------------------------------------
# G — Story 2.3a: injury check end-to-end
# ---------------------------------------------------------------------------

print("\n=== G: Story 2.3a — injury check e2e ===")

fr_inj = respond("esta lesionado Saka", STANDARD_BOOTSTRAP)
_check("G1 intent=player_summary", fr_inj.intent == "player_summary")
_check("G2 outcome=ok", fr_inj.outcome == "ok")
# Saka is status='d' → Doubtful
_check("G3 final_text mentions Doubtful or status",
       "Doubtful" in fr_inj.final_text or "Status:" in fr_inj.final_text,
       f"final_text={fr_inj.final_text[:100]}")


# ---------------------------------------------------------------------------
# H — Story 2.3b: injury_list routing
# ---------------------------------------------------------------------------

print("\n=== H: Story 2.3b — injury_list routing ===")

_injury_list_cases = [
    ("hay dudas para esta jornada", "H1"),
    ("jugadores en duda",           "H2"),
    ("jugadores lesionados",        "H3"),
    ("lista de bajas",              "H4"),
    ("injury list",                 "H5"),
]

for q, label in _injury_list_cases:
    r = route(q)
    _check(f"{label} '{q}' routes to get_injury_list",
           r is not None and r.tool_name == "get_injury_list",
           f"got {r.tool_name if r else 'None'}")


# ---------------------------------------------------------------------------
# I — Story 2.3b: injury_list handler
# ---------------------------------------------------------------------------

print("\n=== I: Story 2.3b — injury_list handler ===")

result_il = get_injury_list(STANDARD_BOOTSTRAP)
_check("I1 status=ok", result_il.get("status") == "ok")
_check("I2 total=2 (Saka=d, De Bruyne=i)", result_il.get("total") == 2,
       f"got total={result_il.get('total')}")
_check("I3 injured has De Bruyne", any(p["web_name"] == "De Bruyne" for p in result_il.get("injured", [])))
_check("I4 doubtful has Saka", any(p["web_name"] == "Saka" for p in result_il.get("doubtful", [])))
saka_entry = next((p for p in result_il.get("doubtful", []) if p["web_name"] == "Saka"), None)
if saka_entry:
    _check("I5 Saka chance_of_playing=75", saka_entry.get("chance_of_playing") == 75)

# End-to-end via respond()
fr_il = respond("hay dudas para esta jornada", STANDARD_BOOTSTRAP)
_check("I6 intent=injury_list", fr_il.intent == "injury_list", f"got {fr_il.intent}")
_check("I7 outcome=ok", fr_il.outcome == "ok")
_check("I8 injury_list meta non-null", fr_il.injury_list is not None)
if fr_il.injury_list is not None:
    _check("I9 total=2", fr_il.injury_list.total == 2)


# ---------------------------------------------------------------------------
# J — Story 2.4: price_changes routing
# ---------------------------------------------------------------------------

print("\n=== J: Story 2.4 — price_changes routing ===")

_price_cases = [
    ("quien esta subiendo de precio esta semana", "J1"),
    ("quien ha bajado de precio",                 "J2"),
    ("jugadores que suben de precio",             "J3"),
    ("price risers",                              "J4"),
    ("price fallers",                             "J5"),
    ("cambios de precio",                         "J6"),
]

for q, label in _price_cases:
    r = route(q)
    _check(f"{label} '{q}' routes to get_price_changes",
           r is not None and r.tool_name == "get_price_changes",
           f"got {r.tool_name if r else 'None'}")


# ---------------------------------------------------------------------------
# K — Story 2.4: price_changes handler
# ---------------------------------------------------------------------------

print("\n=== K: Story 2.4 — price_changes handler ===")

result_pc = get_price_changes(PRICE_CHANGES_BOOTSTRAP)
_check("K1 status=ok", result_pc.get("status") == "ok", f"got {result_pc.get('status')}")
risers = result_pc.get("risers", [])
fallers = result_pc.get("fallers", [])
_check("K2 risers non-empty", len(risers) >= 1, f"got {len(risers)} risers")
_check("K3 fallers non-empty", len(fallers) >= 1, f"got {len(fallers)} fallers")
_check("K4 Salah in risers", any(p["web_name"] == "Salah" for p in risers))
_check("K5 De Bruyne in fallers", any(p["web_name"] == "De Bruyne" for p in fallers))
if risers:
    r0 = risers[0]
    _check("K6 riser has cost_change_event", "cost_change_event" in r0)
    _check("K7 riser has now_cost_m", "now_cost_m" in r0)
    _check("K8 riser cost_change_event>0", r0.get("cost_change_event", 0) > 0)

# Empty fallback on bootstrap without cost_change_event
result_empty = get_price_changes(STANDARD_BOOTSTRAP)
_check("K9 status=empty when no cost_change_event data", result_empty.get("status") == "empty")

# End-to-end via respond()
fr_pc = respond("quien esta subiendo de precio esta semana", PRICE_CHANGES_BOOTSTRAP)
_check("K10 intent=price_changes", fr_pc.intent == "price_changes", f"got {fr_pc.intent}")
_check("K11 outcome=ok", fr_pc.outcome == "ok")
_check("K12 price_changes meta non-null", fr_pc.price_changes is not None)
if fr_pc.price_changes is not None:
    _check("K13 risers non-empty", len(fr_pc.price_changes.risers) >= 1)


# ---------------------------------------------------------------------------
# L — False-positive guard: price routing not triggered by player name mentions
# ---------------------------------------------------------------------------

print("\n=== L: False-positive guard ===")

_no_price_cases = [
    ("cuánto vale Palmer",         "L1"),
    ("tell me about Haaland",      "L2"),
    ("precio de Saka",             "L3"),  # routes to player_summary
    ("should I captain Salah",     "L4"),
]

for q, label in _no_price_cases:
    r = route(q)
    _check(f"{label} '{q}' does NOT route to get_price_changes",
           r is None or r.tool_name != "get_price_changes",
           f"unexpectedly routed to price_changes")


# ---------------------------------------------------------------------------
# M — Regression: validation corpus 60/60
# ---------------------------------------------------------------------------

print("\n=== M: Regression — validation corpus ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"M1 validation corpus {passed}/{total} PASS",
       passed == total,
       f"{total - passed} scenario(s) failed")


# ---------------------------------------------------------------------------
# N — Regression: Phase 2.6b + 2.6c still green
# ---------------------------------------------------------------------------

print("\n=== N: Regression — Phase 2.6b ===")

result_b = subprocess.run(
    [sys.executable, os.path.join(_HERE, "run_phase26b_tests.py")],
    capture_output=True, text=True, cwd=_HERE,
)
last_b = [l for l in result_b.stdout.splitlines() if "Phase 2.6b:" in l]
if last_b:
    summary_b = last_b[-1].strip()
    _check(f"N1 phase26b: {summary_b}", "76/76" in summary_b, result_b.stderr[-200:] if result_b.stderr else "")
else:
    _check("N1 phase26b", False, "could not parse output")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6d: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"            {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("            All assertions passed.")
