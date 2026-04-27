"""
Phase 8a1 GKP Overpromotion Triage
===================================

Focused investigation into whether the GKP overpromotion observed in
differential picks is:
  A. Specific to the differential ranking context
  B. A broader cross-position position_score comparability problem
  C. Caused by saves weighting
  D. Caused by ownership filtering narrowing the pool
  E. Caused by pool composition (most low-ownership players are GKPs)

This script does NOT modify the scoring model.  It produces evidence only.

Usage:
    cd packages/fpl-grounded-assistant
    python run_phase8a1_overpromotion_triage.py
"""
from __future__ import annotations

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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fpl_pipeline import assemble_captain_context
from fpl_captain_engine import calculate_captain_score
from fpl_grounded_assistant.position_score import compute_position_score, POSITION_PROFILES
from fpl_grounded_assistant.transfer_advisor import _derive_scoring_inputs

# ---------------------------------------------------------------------------
# Load live data
# ---------------------------------------------------------------------------

print("Loading live FPL data...")
ctx = assemble_captain_context()
bootstrap = ctx["bootstrap"]
gw = ctx.get("gameweek", "?")
elements = bootstrap.get("elements", [])
fdr_map = bootstrap.get("fixture_difficulty_map", {})
print(f"Ready. GW{gw} | {len(elements)} players loaded.\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(et: int) -> str:
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(et, "UNK")


def _score_element(el: dict) -> dict | None:
    """Score a single element with both canonical and position_score."""
    if el.get("status") != "a":
        return None
    pos = _pos(el.get("element_type", 0))
    if pos == "UNK":
        return None
    inputs = _derive_scoring_inputs(el, fdr_map)
    try:
        cs = float(calculate_captain_score(**inputs))
    except Exception:
        return None
    if cs <= 0:
        return None

    saves = float(el.get("saves_per_90", 0) or 0)
    cs_90 = float(el.get("clean_sheets_per_90", 0) or 0)
    dc_90 = float(el.get("defensive_contribution_per_90", 0) or 0)

    ps_result = compute_position_score(
        position=pos,
        form=inputs["form"],
        fixture_difficulty=inputs["fixture_difficulty"],
        xgi_per_90=inputs["xgi_per_90"],
        minutes_risk=inputs["minutes_risk"],
        saves_per_90=saves,
        clean_sheets_per_90=cs_90,
        dc_per_90=dc_90,
    )

    try:
        own = float(el.get("selected_by_percent", 100))
    except (TypeError, ValueError):
        own = 100.0

    return {
        "web_name": el.get("web_name", "?"),
        "position": pos,
        "captain_score": round(cs, 2),
        "position_score": ps_result.position_score,
        "drift": round(ps_result.position_score - cs, 2),
        "ownership": round(own, 1),
        "form": inputs["form"],
        "saves_per_90": saves,
        "cs_per_90": cs_90,
        "components": ps_result.components,
    }


def _divider(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ---------------------------------------------------------------------------
# Score all available players
# ---------------------------------------------------------------------------

all_scored = []
for el in elements:
    s = _score_element(el)
    if s:
        all_scored.append(s)

print(f"Scored {len(all_scored)} available players with positive scores.\n")

pos_counts = {}
for s in all_scored:
    pos_counts[s["position"]] = pos_counts.get(s["position"], 0) + 1
print(f"Position breakdown (all available): {pos_counts}")


# ===================================================================
# INVESTIGATION A: Is overpromotion specific to differentials?
# ===================================================================

_divider("A: Full pool ranking — position_score vs canonical (no ownership filter)")

by_ps = sorted(all_scored, key=lambda x: x["position_score"], reverse=True)
by_cs = sorted(all_scored, key=lambda x: x["captain_score"], reverse=True)

print("\nTop 15 by CANONICAL captain_score (no ownership filter):")
for i, p in enumerate(by_cs[:15]):
    print(f"  #{i+1:2d} {p['web_name']:18s} ({p['position']}) capt={p['captain_score']:5.1f}  "
          f"pos={p['position_score']:5.1f}  drift={p['drift']:+5.1f}  own={p['ownership']:5.1f}%")

print("\nTop 15 by POSITION_SCORE (no ownership filter):")
for i, p in enumerate(by_ps[:15]):
    print(f"  #{i+1:2d} {p['web_name']:18s} ({p['position']}) pos={p['position_score']:5.1f}  "
          f"capt={p['captain_score']:5.1f}  drift={p['drift']:+5.1f}  own={p['ownership']:5.1f}%")

# Count positions in top 10 for each
top10_cs_pos = [p["position"] for p in by_cs[:10]]
top10_ps_pos = [p["position"] for p in by_ps[:10]]
print(f"\nTop-10 positions (canonical):       {top10_cs_pos}")
print(f"Top-10 positions (position_score):  {top10_ps_pos}")

gkp_in_top10_cs = top10_cs_pos.count("GKP")
gkp_in_top10_ps = top10_ps_pos.count("GKP")
print(f"\nGKP in top 10 — canonical: {gkp_in_top10_cs}, position_score: {gkp_in_top10_ps}")


# ===================================================================
# INVESTIGATION B: How does ownership filtering change things?
# ===================================================================

_divider("B: Ownership filter interaction (< 15% ownership)")

low_own = [p for p in all_scored if p["ownership"] < 15.0]
print(f"\nPlayers with ownership < 15%: {len(low_own)}")

low_pos_counts = {}
for s in low_own:
    low_pos_counts[s["position"]] = low_pos_counts.get(s["position"], 0) + 1
print(f"Position breakdown (ownership < 15%): {low_pos_counts}")

# What fraction of each position is below 15%?
print("\nFraction below 15% ownership by position:")
for pos in ["GKP", "DEF", "MID", "FWD"]:
    total = pos_counts.get(pos, 0)
    low = low_pos_counts.get(pos, 0)
    pct = (low / total * 100) if total else 0
    print(f"  {pos}: {low}/{total} ({pct:.0f}%)")

low_by_ps = sorted(low_own, key=lambda x: x["position_score"], reverse=True)
low_by_cs = sorted(low_own, key=lambda x: x["captain_score"], reverse=True)

print("\nTop 10 LOW-OWNERSHIP by canonical:")
for i, p in enumerate(low_by_cs[:10]):
    print(f"  #{i+1:2d} {p['web_name']:18s} ({p['position']}) capt={p['captain_score']:5.1f}  "
          f"pos={p['position_score']:5.1f}  drift={p['drift']:+5.1f}  own={p['ownership']:5.1f}%")

print("\nTop 10 LOW-OWNERSHIP by position_score:")
for i, p in enumerate(low_by_ps[:10]):
    print(f"  #{i+1:2d} {p['web_name']:18s} ({p['position']}) pos={p['position_score']:5.1f}  "
          f"capt={p['captain_score']:5.1f}  drift={p['drift']:+5.1f}  own={p['ownership']:5.1f}%")

low_top10_cs_gkp = [p["position"] for p in low_by_cs[:10]].count("GKP")
low_top10_ps_gkp = [p["position"] for p in low_by_ps[:10]].count("GKP")
print(f"\nGKP in low-own top 10 — canonical: {low_top10_cs_gkp}, position_score: {low_top10_ps_gkp}")


# ===================================================================
# INVESTIGATION C: Drift distribution by position
# ===================================================================

_divider("C: Drift distribution by position")

for pos in ["GKP", "DEF", "MID", "FWD"]:
    pos_players = [p for p in all_scored if p["position"] == pos]
    if not pos_players:
        continue
    drifts = [p["drift"] for p in pos_players]
    avg_drift = sum(drifts) / len(drifts)
    min_drift = min(drifts)
    max_drift = max(drifts)
    pos_players_sorted = sorted(pos_players, key=lambda x: x["drift"], reverse=True)

    print(f"\n  {pos} ({len(pos_players)} players):")
    print(f"    drift: avg={avg_drift:+.1f}  min={min_drift:+.1f}  max={max_drift:+.1f}")
    print(f"    highest-drift player: {pos_players_sorted[0]['web_name']} "
          f"(drift={pos_players_sorted[0]['drift']:+.1f}, "
          f"capt={pos_players_sorted[0]['captain_score']:.1f}, "
          f"pos={pos_players_sorted[0]['position_score']:.1f})")
    if pos in ("GKP", "DEF"):
        print(f"    top-3 by drift:")
        for p in pos_players_sorted[:3]:
            print(f"      {p['web_name']:18s} drift={p['drift']:+.1f}  "
                  f"saves/90={p['saves_per_90']:.2f}  cs/90={p['cs_per_90']:.3f}  "
                  f"form={p['form']:.1f}")


# ===================================================================
# INVESTIGATION D: What if saves weight were reduced?
# ===================================================================

_divider("D: Sensitivity analysis — GKP saves weight impact")

from fpl_grounded_assistant.position_score import PositionWeights

# Current default GKP: saves=0.25
# Test with saves=0.15 (redistributed to form)
gkp_reduced_saves = PositionWeights(
    form=0.40, fixture=0.20, xgi=0.00, minutes=0.10,
    saves=0.15, clean_sheet=0.15, dc=0.00,
)

print("\nWeight comparison:")
print(f"  Default GKP:  saves=0.25, form=0.30")
print(f"  Reduced GKP:  saves=0.15, form=0.40")

# Re-score GKPs with reduced weights
gkp_players = [p for p in all_scored if p["position"] == "GKP"]
for p in gkp_players:
    el = next((e for e in elements if e.get("web_name") == p["web_name"]), None)
    if not el:
        continue
    inputs = _derive_scoring_inputs(el, fdr_map)
    reduced = compute_position_score(
        position="GKP",
        form=inputs["form"],
        fixture_difficulty=inputs["fixture_difficulty"],
        xgi_per_90=inputs["xgi_per_90"],
        minutes_risk=inputs["minutes_risk"],
        saves_per_90=float(el.get("saves_per_90", 0) or 0),
        clean_sheets_per_90=float(el.get("clean_sheets_per_90", 0) or 0),
        dc_per_90=float(el.get("defensive_contribution_per_90", 0) or 0),
        weights_override=gkp_reduced_saves,
    )
    p["ps_reduced_saves"] = reduced.position_score
    p["drift_reduced"] = round(reduced.position_score - p["captain_score"], 2)

print("\nTop GKPs — default vs reduced saves weight:")
gkp_by_ps = sorted(gkp_players, key=lambda x: x["position_score"], reverse=True)
for p in gkp_by_ps[:5]:
    red = p.get("ps_reduced_saves", 0)
    print(f"  {p['web_name']:18s} default={p['position_score']:5.1f}(drift {p['drift']:+.1f})  "
          f"reduced={red:5.1f}(drift {p.get('drift_reduced', 0):+.1f})  "
          f"capt={p['captain_score']:5.1f}  saves/90={p['saves_per_90']:.2f}")

# Would reduced saves fix the differential ranking?
print("\nImpact on differential top-5 (ownership < 15%, reduced saves):")
low_own_all = []
for p in all_scored:
    if p["ownership"] >= 15.0:
        continue
    if p["position"] == "GKP":
        score = p.get("ps_reduced_saves", p["position_score"])
    else:
        score = p["position_score"]
    low_own_all.append({**p, "effective_score": score})

low_own_all.sort(key=lambda x: x["effective_score"], reverse=True)
print(f"  (using reduced saves for GKP, default for others)")
for i, p in enumerate(low_own_all[:10]):
    marker = " <-- GKP" if p["position"] == "GKP" else ""
    print(f"  #{i+1:2d} {p['web_name']:18s} ({p['position']}) eff={p['effective_score']:5.1f}  "
          f"capt={p['captain_score']:5.1f}  own={p['ownership']:5.1f}%{marker}")


# ===================================================================
# INVESTIGATION E: Where do GKPs rank vs all positions at various thresholds?
# ===================================================================

_divider("E: GKP rank positions across ownership thresholds")

for threshold in [5.0, 10.0, 15.0, 25.0, 50.0, 100.0]:
    pool = [p for p in all_scored if p["ownership"] < threshold]
    if not pool:
        continue
    pool.sort(key=lambda x: x["position_score"], reverse=True)
    top5_pos = [p["position"] for p in pool[:5]]
    gkp_count = top5_pos.count("GKP")
    top_gkp = next((p for p in pool if p["position"] == "GKP"), None)
    top_gkp_rank = next((i+1 for i, p in enumerate(pool) if p["position"] == "GKP"), None)
    gkp_info = f"highest GKP at #{top_gkp_rank} ({top_gkp['web_name']})" if top_gkp else "no GKP"
    print(f"  own < {threshold:5.1f}%: pool={len(pool):4d}  GKP in top-5={gkp_count}  {gkp_info}")


# ===================================================================
# SUMMARY
# ===================================================================

_divider("TRIAGE SUMMARY")

print("""
Findings:

1. SCOPE: Is GKP overpromotion specific to differentials?
   Compare the full-pool (no ownership filter) and low-ownership rankings
   above. If GKPs appear in the full-pool top-10 by position_score, the
   issue is broader than differentials.

2. OWNERSHIP FILTER: Does filtering amplify the problem?
   Compare low-ownership pool composition. If GKPs are disproportionately
   represented in the low-ownership pool, filtering mechanically increases
   their representation in top-N.

3. DRIFT MAGNITUDE: How much does position_score lift GKPs?
   See drift distribution in section C. Average GKP drift vs DEF drift
   indicates whether the saves weight is disproportionate.

4. SAVES WEIGHT SENSITIVITY: Would reducing saves weight help?
   Section D shows the impact of saves=0.15 vs saves=0.25.

5. THRESHOLD STABILITY: Does the problem persist across ownership bands?
   Section E shows GKP top-5 presence at various thresholds.
""")
