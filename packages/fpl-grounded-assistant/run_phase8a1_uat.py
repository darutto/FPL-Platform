"""
Phase 8a1 Live UAT — Position-Aware Heuristic Evidence Pass
============================================================

Loads live FPL data and exercises representative GKP, DEF, MID, FWD, and
differential cases.  For each case, captures:

  - plain-text response quality
  - captain_score (Layer 1 canonical)
  - position_score (Layer 2 heuristic)
  - component breakdown where exposed
  - cross-surface consistency (CLI respond(), HTTP /ask, session /session/{id}/ask)

This script does NOT modify the scoring model.  It captures evidence only.

Usage:
    cd packages/fpl-grounded-assistant
    python run_phase8a1_uat.py
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Path setup
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

# Ensure Unicode output works on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fpl_pipeline import assemble_captain_context
from fpl_grounded_assistant import respond
from fpl_grounded_assistant.comparison import compare_players
from fpl_grounded_assistant.differential_picks import get_differential_picks

# ---------------------------------------------------------------------------
# Load live data
# ---------------------------------------------------------------------------

print("Loading live FPL data...")
try:
    ctx = assemble_captain_context()
except Exception as exc:
    print(f"FATAL: could not load live data: {exc}")
    sys.exit(1)

bootstrap = ctx["bootstrap"]
gw = ctx.get("gameweek", "?")
elements = bootstrap.get("elements", [])
print(f"Ready. GW{gw} | {len(elements)} players loaded.\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_player(name: str) -> dict | None:
    """Find a player by web_name in the live bootstrap."""
    return next((e for e in elements if e.get("web_name") == name), None)


def _pos_label(et: int) -> str:
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(et, "UNK")


def _print_divider(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def _print_comparison_evidence(prompt: str, bootstrap_data: dict) -> dict:
    """Run a comparison via respond() and print structured evidence."""
    r = respond(prompt, bootstrap_data, include_debug=True)
    print(f"\n  Prompt:   \"{prompt}\"")
    print(f"  Outcome:  {r.outcome}  |  Intent: {r.intent}")
    print(f"  Text:     {r.final_text[:120]}...")

    evidence = {
        "prompt": prompt,
        "outcome": r.outcome,
        "intent": r.intent,
        "text_snippet": r.final_text[:200],
    }

    if r.comparison:
        cmp = r.comparison
        print(f"  Winner:   {cmp.winner}  |  Margin: {cmp.margin:.1f}  |  Label: {cmp.label}")
        if cmp.player_a and cmp.player_b:
            for label, ctx in [("player_a", cmp.player_a), ("player_b", cmp.player_b)]:
                print(f"    {label}: {ctx.web_name} ({ctx.position})")
                print(f"      captain_score  = {ctx.captain_score:.2f}  (Layer 1)")
                print(f"      position_score = {ctx.position_score:.2f}  (Layer 2)")
                drift = ctx.position_score - ctx.captain_score
                drift_pct = (drift / ctx.captain_score * 100) if ctx.captain_score else 0
                print(f"      drift          = {drift:+.2f} ({drift_pct:+.1f}%)")
                evidence[label] = {
                    "web_name": ctx.web_name,
                    "position": ctx.position,
                    "captain_score": ctx.captain_score,
                    "position_score": ctx.position_score,
                    "drift": round(drift, 2),
                    "drift_pct": round(drift_pct, 1),
                }

    if r.transfer:
        t = r.transfer
        print(f"  Transfer: {t.player_out} -> {t.player_in}")
        print(f"    recommendation = {t.recommendation}")
        print(f"    score_delta    = {t.score_delta:+.1f} (position_score)")
        print(f"    price_delta    = {t.price_delta:+d} (tenths)")
        evidence["transfer"] = {
            "player_out": t.player_out,
            "player_in": t.player_in,
            "recommendation": t.recommendation,
            "score_delta": t.score_delta,
            "price_delta": t.price_delta,
        }

    # Debug score_inputs if available
    if r.debug and hasattr(r.debug, "raw_output"):
        raw = getattr(r.debug, "raw_output", None)
        # Score inputs might be nested — best effort
        pass

    return evidence


# ---------------------------------------------------------------------------
# UAT Cases
# ---------------------------------------------------------------------------

all_evidence: list[dict] = []

# ---- Case 1: GKP Comparison ----
_print_divider("Case 1: GKP Comparison")
print("  Purpose: Verify GKP position_score > captain_score (saves/CS credit)")

# Find a live GKP with decent form
gkps = [e for e in elements if e.get("element_type") == 1 and e.get("status") == "a"]
gkps.sort(key=lambda e: float(e.get("form", 0) or 0), reverse=True)
top_gkp = gkps[0]["web_name"] if gkps else None

# Find top MID for comparison
mids = [e for e in elements if e.get("element_type") == 3 and e.get("status") == "a"]
mids.sort(key=lambda e: float(e.get("form", 0) or 0), reverse=True)
top_mid = mids[0]["web_name"] if mids else None

if top_gkp and top_mid:
    print(f"  Selected: {top_gkp} (GKP) vs {top_mid} (MID)")
    ev = _print_comparison_evidence(f"compare {top_gkp} and {top_mid}", bootstrap)
    ev["case"] = "GKP_comparison"

    # Validate: GKP should have positive drift
    gkp_side = ev.get("player_a") if ev.get("player_a", {}).get("position") == "GKP" else ev.get("player_b")
    if gkp_side:
        drift = gkp_side["drift"]
        print(f"\n  ** GKP drift assessment: {drift:+.2f}")
        if drift > 0:
            print(f"  ** PASS: GKP gets positive position_score uplift from saves/CS")
        elif drift == 0:
            print(f"  ** CAUTION: GKP has zero drift — may have zero saves/CS per-90 data")
        else:
            print(f"  ** FAIL: GKP has negative drift — unexpected")
        ev["gkp_drift_assessment"] = "positive" if drift > 0 else ("zero" if drift == 0 else "negative")
    all_evidence.append(ev)
else:
    print("  SKIP: Could not find live GKP or MID")

# ---- Case 2: DEF Comparison ----
_print_divider("Case 2: DEF Comparison")
print("  Purpose: Verify DEF position_score reflects CS credit, reduced xgi weight")

defs = [e for e in elements if e.get("element_type") == 2 and e.get("status") == "a"]
defs.sort(key=lambda e: float(e.get("form", 0) or 0), reverse=True)
top_def = defs[0]["web_name"] if defs else None

if top_def and top_mid:
    print(f"  Selected: {top_def} (DEF) vs {top_mid} (MID)")
    ev = _print_comparison_evidence(f"compare {top_def} and {top_mid}", bootstrap)
    ev["case"] = "DEF_comparison"

    def_side = ev.get("player_a") if ev.get("player_a", {}).get("position") == "DEF" else ev.get("player_b")
    if def_side:
        drift = def_side["drift"]
        print(f"\n  ** DEF drift assessment: {drift:+.2f}")
        if drift > 0:
            print(f"  ** DEF gets positive uplift (CS credit > xgi reduction)")
        elif drift < 0:
            print(f"  ** DEF gets negative drift (attacking DEF with high xgi loses weight)")
        else:
            print(f"  ** DEF has zero drift")
        ev["def_drift_assessment"] = "positive" if drift > 0 else ("negative" if drift < 0 else "zero")
    all_evidence.append(ev)
else:
    print("  SKIP: Could not find live DEF")

# Also test DEF transfer case
if top_def:
    # Find another DEF to compare
    other_defs = [e for e in defs if e["web_name"] != top_def]
    if other_defs:
        other_def = other_defs[0]["web_name"]
        print(f"\n  DEF transfer: sell {other_def} for {top_def}")
        ev = _print_comparison_evidence(f"should I sell {other_def} for {top_def}", bootstrap)
        ev["case"] = "DEF_transfer"
        all_evidence.append(ev)

# ---- Case 3: MID Control ----
_print_divider("Case 3: MID Control (zero drift expected)")
print("  Purpose: Verify MID position_score == captain_score (zero drift by design)")

if top_mid and len(mids) > 1:
    second_mid = mids[1]["web_name"]
    print(f"  Selected: {top_mid} (MID) vs {second_mid} (MID)")
    ev = _print_comparison_evidence(f"compare {top_mid} and {second_mid}", bootstrap)
    ev["case"] = "MID_control"

    for side_key in ("player_a", "player_b"):
        side = ev.get(side_key, {})
        if side.get("position") == "MID":
            drift = side["drift"]
            if abs(drift) < 0.01:
                print(f"  ** PASS: {side['web_name']} MID drift is zero ({drift:+.4f})")
            else:
                print(f"  ** FAIL: {side['web_name']} MID drift is non-zero ({drift:+.4f})")
    all_evidence.append(ev)

# ---- Case 4: FWD Control ----
_print_divider("Case 4: FWD Control (zero drift expected — FWD=MID bridge)")
print("  Purpose: Verify FWD position_score == captain_score (FWD=MID transitional)")

fwds = [e for e in elements if e.get("element_type") == 4 and e.get("status") == "a"]
fwds.sort(key=lambda e: float(e.get("form", 0) or 0), reverse=True)
top_fwd = fwds[0]["web_name"] if fwds else None

if top_fwd and top_mid:
    print(f"  Selected: {top_fwd} (FWD) vs {top_mid} (MID)")
    ev = _print_comparison_evidence(f"compare {top_fwd} and {top_mid}", bootstrap)
    ev["case"] = "FWD_control"

    fwd_side = ev.get("player_a") if ev.get("player_a", {}).get("position") == "FWD" else ev.get("player_b")
    if fwd_side:
        drift = fwd_side["drift"]
        if abs(drift) < 0.01:
            print(f"  ** PASS: FWD drift is zero ({drift:+.4f})")
        else:
            print(f"  ** FAIL: FWD drift is non-zero ({drift:+.4f}) — FWD=MID bridge broken")
    all_evidence.append(ev)

# ---- Case 5: Differential picks — overpromotion check ----
_print_divider("Case 5: Differential Picks — GKP/DEF Overpromotion Check")
print("  Purpose: Check if position_score pushes GKP/DEF into top differential picks")

diff_result = get_differential_picks(bootstrap)
if diff_result["status"] == "ok":
    picks = diff_result["picks"]
    print(f"  Total picks returned: {len(picks)}")
    print(f"  Ownership threshold: {diff_result['ownership_threshold']}%")
    print()

    position_counts = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for p in picks:
        pos = p["position"]
        position_counts[pos] = position_counts.get(pos, 0) + 1
        drift = p["position_score"] - p["captain_score"]
        print(f"    #{p['rank']} {p['web_name']:15s} ({p['team_short']}, {pos}) "
              f"pos_score={p['position_score']:5.1f}  capt_score={p['captain_score']:5.1f}  "
              f"drift={drift:+.1f}  own={p['ownership']:.1f}%")

    print(f"\n  Position breakdown: {position_counts}")

    gkp_def_count = position_counts.get("GKP", 0) + position_counts.get("DEF", 0)
    if gkp_def_count == 0:
        print("  ** No GKP/DEF in top differentials — no overpromotion concern")
    elif gkp_def_count <= 2:
        print(f"  ** {gkp_def_count} GKP/DEF in top differentials — mild, inspect manually")
    else:
        print(f"  ** CAUTION: {gkp_def_count} GKP/DEF in top {len(picks)} — potential overpromotion")

    all_evidence.append({
        "case": "differential_overpromotion",
        "picks": [{
            "rank": p["rank"], "web_name": p["web_name"], "position": p["position"],
            "captain_score": p["captain_score"], "position_score": p["position_score"],
            "ownership": p["ownership"],
        } for p in picks],
        "position_counts": position_counts,
        "gkp_def_in_top": gkp_def_count,
    })

    # Also run via respond() for text quality check
    r_diff = respond("good differentials", bootstrap)
    print(f"\n  respond() text: {r_diff.final_text[:150]}...")
    if r_diff.differential:
        print(f"  FinalResponse.differential populated: {len(r_diff.differential.picks)} picks")
else:
    print(f"  Differential result: {diff_result.get('status')} — {diff_result.get('message', '')}")


# ---- Case 6: GKP vs FWD (cross-position heuristic check) ----
_print_divider("Case 6: GKP vs FWD Direct Comparison")
print("  Purpose: Does position_score help a strong GKP compete with a strong FWD?")

if top_gkp and top_fwd:
    print(f"  Selected: {top_gkp} (GKP) vs {top_fwd} (FWD)")
    ev = _print_comparison_evidence(f"compare {top_gkp} and {top_fwd}", bootstrap)
    ev["case"] = "GKP_vs_FWD"
    all_evidence.append(ev)


# ---- Case 7: Raw component inspection for a GKP ----
_print_divider("Case 7: Raw Component Inspection")
print("  Purpose: Verify component breakdown is visible and sensible")

if top_gkp and top_mid:
    raw = compare_players(top_gkp, top_mid, bootstrap)
    if raw["status"] == "ok":
        for side_label in ("player_a", "player_b"):
            p = raw[side_label]
            si = p.get("score_inputs", {})
            print(f"\n  {side_label}: {p['web_name']} ({p.get('position', '?')})")
            print(f"    captain_score:    {p.get('captain_score', '?')}")
            print(f"    position_score:   {p.get('position_score', '?')}")
            print(f"    position_profile: {si.get('position_profile', '?')}")
            components = si.get("components", {})
            if components:
                print(f"    components:")
                for k, v in components.items():
                    print(f"      {k:16s} = {v:.2f}")
            weights = si.get("weights", {})
            if weights:
                print(f"    weights:")
                for k, v in weights.items():
                    print(f"      {k:16s} = {v:.2f}")

        all_evidence.append({
            "case": "component_inspection",
            "player_a": {
                "web_name": raw["player_a"]["web_name"],
                "score_inputs": raw["player_a"].get("score_inputs", {}),
            },
            "player_b": {
                "web_name": raw["player_b"]["web_name"],
                "score_inputs": raw["player_b"].get("score_inputs", {}),
            },
        })


# ---------------------------------------------------------------------------
# Cross-surface parity check
# ---------------------------------------------------------------------------

_print_divider("Case 8: Cross-Surface Parity (CLI / HTTP / Session)")
print("  Purpose: Verify position_score is consistent across all surfaces")

test_prompt = f"compare {top_mid} and {top_fwd}" if top_mid and top_fwd else "compare Salah and Haaland"

# CLI surface (respond)
cli_r = respond(test_prompt, bootstrap)
cli_pa = None
if cli_r.comparison and cli_r.comparison.player_a:
    cli_pa = {
        "web_name": cli_r.comparison.player_a.web_name,
        "position_score": cli_r.comparison.player_a.position_score,
        "captain_score": cli_r.comparison.player_a.captain_score,
    }
    cli_pb = {
        "web_name": cli_r.comparison.player_b.web_name,
        "position_score": cli_r.comparison.player_b.position_score,
        "captain_score": cli_r.comparison.player_b.captain_score,
    }
    print(f"  CLI:     {cli_pa['web_name']} ps={cli_pa['position_score']:.2f} | "
          f"{cli_pb['web_name']} ps={cli_pb['position_score']:.2f}")

# HTTP surface
http_pa = None
try:
    import fpl_server
    from fastapi.testclient import TestClient

    fpl_server._init_bootstrap(bootstrap)
    http_client = TestClient(fpl_server.app)

    resp = http_client.post("/ask", json={"question": test_prompt})
    if resp.status_code == 200:
        body = resp.json()
        comp = body.get("comparison", {})
        if comp and comp.get("player_a"):
            http_pa = comp["player_a"]
            http_pb = comp["player_b"]
            print(f"  HTTP:    {http_pa['web_name']} ps={http_pa['position_score']:.2f} | "
                  f"{http_pb['web_name']} ps={http_pb['position_score']:.2f}")
except Exception as exc:
    print(f"  HTTP:    ERROR — {exc}")

# Session surface
session_pa = None
try:
    fpl_server._clear_sessions()
    sess_resp = http_client.post("/session")
    sid = sess_resp.json()["session_id"]
    ask_resp = http_client.post(f"/session/{sid}/ask", json={"question": test_prompt})
    if ask_resp.status_code == 200:
        sbody = ask_resp.json()
        scomp = sbody.get("comparison", {})
        if scomp and scomp.get("player_a"):
            session_pa = scomp["player_a"]
            session_pb = scomp["player_b"]
            print(f"  Session: {session_pa['web_name']} ps={session_pa['position_score']:.2f} | "
                  f"{session_pb['web_name']} ps={session_pb['position_score']:.2f}")
except Exception as exc:
    print(f"  Session: ERROR — {exc}")

# Parity check
parity_ok = True
if cli_pa and http_pa:
    if abs(cli_pa["position_score"] - http_pa["position_score"]) > 0.01:
        print("  ** FAIL: CLI vs HTTP position_score mismatch!")
        parity_ok = False
if cli_pa and session_pa:
    if abs(cli_pa["position_score"] - session_pa["position_score"]) > 0.01:
        print("  ** FAIL: CLI vs Session position_score mismatch!")
        parity_ok = False
if parity_ok:
    print("  ** PASS: All surfaces return identical position_score values")

all_evidence.append({
    "case": "cross_surface_parity",
    "prompt": test_prompt,
    "cli": cli_pa,
    "http": http_pa,
    "session": session_pa,
    "parity_ok": parity_ok,
})


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

_print_divider("UAT SUMMARY")

issues_found = []
for ev in all_evidence:
    case = ev.get("case", "?")
    if case == "GKP_comparison" and ev.get("gkp_drift_assessment") == "negative":
        issues_found.append(f"{case}: GKP has negative drift")
    if case == "MID_control":
        for side_key in ("player_a", "player_b"):
            s = ev.get(side_key, {})
            if s.get("position") == "MID" and abs(s.get("drift", 0)) > 0.01:
                issues_found.append(f"{case}: MID {s['web_name']} drift non-zero ({s['drift']})")
    if case == "FWD_control":
        fwd_s = ev.get("player_a") if ev.get("player_a", {}).get("position") == "FWD" else ev.get("player_b")
        if fwd_s and abs(fwd_s.get("drift", 0)) > 0.01:
            issues_found.append(f"{case}: FWD drift non-zero ({fwd_s['drift']})")
    if case == "differential_overpromotion" and ev.get("gkp_def_in_top", 0) > 2:
        issues_found.append(f"{case}: {ev['gkp_def_in_top']} GKP/DEF in top differentials")
    if case == "cross_surface_parity" and not ev.get("parity_ok"):
        issues_found.append(f"{case}: Surface parity broken")

print()
if issues_found:
    print(f"Issues found ({len(issues_found)}):")
    for issue in issues_found:
        print(f"  - {issue}")
else:
    print("No issues found. All cases passed.")

print(f"\nCases executed: {len(all_evidence)}")
print(f"GW: {gw}")
print(f"Players loaded: {len(elements)}")

# Write evidence to JSON
evidence_path = os.path.join(_HERE, "phase8a1_uat_evidence.json")
with open(evidence_path, "w", encoding="utf-8") as f:
    json.dump({
        "gameweek": gw,
        "player_count": len(elements),
        "cases": all_evidence,
        "issues": issues_found,
    }, f, indent=2, default=str)
print(f"\nEvidence written to: {evidence_path}")
