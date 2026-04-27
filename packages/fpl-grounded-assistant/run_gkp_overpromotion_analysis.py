# -*- coding: utf-8 -*-
"""
run_gkp_overpromotion_analysis.py
===================================
GKP overpromotion analysis harness for differential picks.

Measures the residual GKP overpromotion pattern after the blank-GW filter
was introduced (Phase blank-GW fix).  Observational only -- no weight changes.

Sections
--------
A  Position mix comparison: captain_score top-N vs position_score top-N
B  Per-player drift (position_score - captain_score) for all candidates
C  Promoted players: in position top-N but NOT captain top-N
D  Saves/cs contribution quantification per promoted GKP
E  Fixture type coverage: normal GW, BGW, high-saves fixture
F  Regression: 44/44 V1 validation corpus still passes

Analysis helper
---------------
analyse_differential_rankings(bootstrap, top_n=5) -> dict
    Returns a comparison of captain_score ranking vs position_score ranking
    over all eligible differential candidates.  All metrics are deterministic.

Run from packages/fpl-grounded-assistant::

    python run_gkp_overpromotion_analysis.py
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

from fpl_grounded_assistant.differential_picks import get_differential_picks
from fpl_grounded_assistant.conversation_fixtures import (
    GKP_OVERPROMOTION_BOOTSTRAP,
    GKP_BALANCED_BOOTSTRAP,
    DIFFERENTIAL_BOOTSTRAP,
    DIFFERENTIAL_BGW_BOOTSTRAP,
)


# ---------------------------------------------------------------------------
# Analysis helper
# ---------------------------------------------------------------------------

def analyse_differential_rankings(
    bootstrap: dict,
    top_n: int = 5,
) -> dict:
    """Compare captain_score ranking vs position_score ranking for differential picks.

    Retrieves all eligible differential candidates (using a large internal
    top_n to avoid truncation), then re-ranks them independently by
    captain_score and position_score.  Returns position mix counts under
    each ranking, per-player drift, and the set of promoted players.

    Parameters
    ----------
    bootstrap:
        Raw FPL bootstrap dict passed to ``get_differential_picks``.
    top_n:
        Number of top picks to compare.  Default 5 (the standard output size).

    Returns
    -------
    dict with keys:
        status            "ok" or "empty"
        top_n             int -- the comparison window size
        captain_top_n     list of pick dicts sorted by captain_score desc
        position_top_n    list of pick dicts sorted by position_score desc
        all_candidates    full scored list sorted by position_score desc
        promoted          list of pick dicts: in position_top_n but NOT captain_top_n
        demoted           list of pick dicts: in captain_top_n but NOT position_top_n
        drift             list of {web_name, position, captain_score, position_score,
                                   drift, saves_score, cs_score} per candidate
        position_mix_captain  {GKP, DEF, MID, FWD} counts in captain top-N
        position_mix_position {GKP, DEF, MID, FWD} counts in position top-N
    """
    # Get all candidates by requesting a large pool
    raw = get_differential_picks(bootstrap, top_n=100)
    if raw["status"] != "ok":
        return {"status": raw["status"], "top_n": top_n}

    candidates = raw["picks"]  # already sorted by position_score desc

    # Sort a separate copy by captain_score
    by_captain = sorted(candidates, key=lambda p: p["captain_score"], reverse=True)

    captain_names = {p["web_name"] for p in by_captain[:top_n]}
    position_names = {p["web_name"] for p in candidates[:top_n]}

    promoted = [p for p in candidates[:top_n] if p["web_name"] not in captain_names]
    demoted  = [p for p in by_captain[:top_n] if p["web_name"] not in position_names]

    def _mix(picks: list[dict]) -> dict[str, int]:
        out = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
        for p in picks:
            pos = p.get("position", "UNK")
            if pos in out:
                out[pos] += 1
        return out

    # Compute saves_score and cs_score components for drift attribution.
    # These are the two GKP-exclusive components that drive the uplift.
    # Normalisation mirrors position_score.py:
    #   saves_score = clamp(saves_per_90 / 4.0 * 100)
    #   cs_score    = clamp(cs_per_90 / 0.5 * 100)
    # Contribution to position_score at GKP weights: saves*0.25 + cs*0.15
    fdr_map  = bootstrap.get("fixture_difficulty_map", {})
    tf       = bootstrap.get("team_fixtures")
    el_index = {el["id"]: el for el in bootstrap.get("elements", [])}

    drift_list = []
    for p in candidates:
        ps = p["position_score"]
        cs_val = p["captain_score"]
        drift_val = round(ps - cs_val, 2)

        # Find the raw element to read GKP-specific fields
        web_name = p["web_name"]
        el = next(
            (e for e in bootstrap.get("elements", []) if e.get("web_name") == web_name),
            {},
        )
        saves_p90  = float(el.get("saves_per_90", 0) or 0)
        cs_p90     = float(el.get("clean_sheets_per_90", 0) or 0)

        saves_score_norm = min(100.0, max(0.0, saves_p90 / 4.0 * 100))
        cs_score_norm    = min(100.0, max(0.0, cs_p90 / 0.5 * 100))

        # Weighted contribution from saves/cs in GKP profile (0 for all others)
        position = p.get("position", "")
        if position == "GKP":
            saves_contribution = round(saves_score_norm * 0.25, 2)
            cs_contribution    = round(cs_score_norm * 0.15, 2)
        else:
            saves_contribution = 0.0
            cs_contribution    = 0.0

        drift_list.append({
            "web_name":          web_name,
            "position":          position,
            "captain_score":     cs_val,
            "position_score":    ps,
            "drift":             drift_val,
            "saves_score":       round(saves_score_norm, 1),
            "cs_score":          round(cs_score_norm, 1),
            "saves_contribution": saves_contribution,
            "cs_contribution":    cs_contribution,
        })

    # Sort drift list by drift descending so top promoters are first
    drift_list.sort(key=lambda d: d["drift"], reverse=True)

    return {
        "status":               "ok",
        "top_n":                top_n,
        "captain_top_n":        by_captain[:top_n],
        "position_top_n":       candidates[:top_n],
        "all_candidates":       candidates,
        "promoted":             promoted,
        "demoted":              demoted,
        "drift":                drift_list,
        "position_mix_captain": _mix(by_captain[:top_n]),
        "position_mix_position": _mix(candidates[:top_n]),
    }


def print_analysis_report(result: dict, label: str = "") -> None:
    """Print a human-readable analysis report to stdout."""
    hdr = f"=== {label} ===" if label else "=== Analysis Report ==="
    print(f"\n{hdr}")

    if result.get("status") != "ok":
        print(f"  Status: {result.get('status')}")
        return

    top_n = result["top_n"]
    mix_c = result["position_mix_captain"]
    mix_p = result["position_mix_position"]

    print(f"  Top-{top_n} position mix:")
    print(f"    Captain ranking:  GKP={mix_c['GKP']}  DEF={mix_c['DEF']}  "
          f"MID={mix_c['MID']}  FWD={mix_c['FWD']}")
    print(f"    Position ranking: GKP={mix_p['GKP']}  DEF={mix_p['DEF']}  "
          f"MID={mix_p['MID']}  FWD={mix_p['FWD']}")

    print(f"\n  Per-player drift (position_score - captain_score), all candidates:")
    for d in result["drift"]:
        promo_flag = " [PROMOTED]" if d["web_name"] in {
            p["web_name"] for p in result["promoted"]
        } else ""
        print(
            f"    {d['web_name']:14s} {d['position']:3s}  "
            f"capt={d['captain_score']:5.2f}  pos={d['position_score']:5.2f}  "
            f"drift={d['drift']:+.2f}  "
            f"saves_contrib={d['saves_contribution']:.2f}  "
            f"cs_contrib={d['cs_contribution']:.2f}{promo_flag}"
        )

    if result["promoted"]:
        print(f"\n  Promoted (in position top-{top_n} but NOT captain top-{top_n}):")
        for p in result["promoted"]:
            print(f"    {p['web_name']:14s} {p['position']:3s}  "
                  f"pos_rank={result['position_top_n'].index(p)+1}  "
                  f"position_score={p['position_score']:.2f}")
    else:
        print(f"\n  No promoted players (position top-{top_n} == captain top-{top_n})")

    if result["demoted"]:
        print(f"\n  Demoted (in captain top-{top_n} but NOT position top-{top_n}):")
        for p in result["demoted"]:
            print(f"    {p['web_name']:14s} {p['position']:3s}  "
                  f"captain_score={p['captain_score']:.2f}")


# ---------------------------------------------------------------------------
# Test runner helpers
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
# Section A: Position mix — GKP_OVERPROMOTION_BOOTSTRAP
# ---------------------------------------------------------------------------

print("\n=== Section A: Position mix comparison (GKP overpromotion fixture) ===")

_result_gkp = analyse_differential_rankings(GKP_OVERPROMOTION_BOOTSTRAP, top_n=5)
print_analysis_report(_result_gkp, "GKP_OVERPROMOTION_BOOTSTRAP")

ok(_result_gkp["status"] == "ok",
   "GKP overpromotion fixture: analysis status=ok")

_mix_c = _result_gkp["position_mix_captain"]
_mix_p = _result_gkp["position_mix_position"]

ok(_mix_c["GKP"] < _mix_p["GKP"],
   "More GKPs in position top-5 than captain top-5 (overpromotion confirmed)")

ok(_mix_p["GKP"] >= 2,
   "At least 2 GKPs in position top-5 (high saves uplift dominates)")

ok(_mix_c["MID"] + _mix_c["FWD"] > _mix_p["MID"] + _mix_p["FWD"],
   "More outfield (MID+FWD) in captain top-5 than position top-5 (outfield demoted)")

# ---------------------------------------------------------------------------
# Section B: Per-player drift direction
# ---------------------------------------------------------------------------

print("\n=== Section B: Drift direction ===")

_gkp_drifts = [d for d in _result_gkp["drift"] if d["position"] == "GKP"]
_outfield_drifts = [d for d in _result_gkp["drift"] if d["position"] in ("MID", "FWD")]

ok(all(d["drift"] > 0 for d in _gkp_drifts),
   "All GKPs have positive drift (saves/cs uplift > zero in position_score)")

ok(all(d["drift"] == 3.0 for d in _outfield_drifts if d["position"] in ("MID", "FWD")),
   "MID and FWD drift = +3.0 exactly (home venue shift: effective_fdr=2.5 vs raw_fdr=3; "
   "no saves/cs component — drift is pure venue adjustment, same magnitude for all)")

# Note: MID/FWD drift may be non-zero when is_home is not None because
# Layer 2 uses effective_fdr and Layer 1 uses raw FDR.
# Verify separately:
_venue_drift = [d["drift"] for d in _outfield_drifts]
print(f"    MID/FWD venue drifts (effective_fdr vs raw): {_venue_drift}")
# These are expected non-zero when home (effective_fdr = raw_fdr - 0.5):
# drift = (6-2.5)*20*0.3 - (6-3)*20*0.3 = 70*0.3 - 60*0.3 = 21 - 18 = 3.0
ok(all(d["drift"] >= 0 for d in _outfield_drifts),
   "MID/FWD drift is non-negative (home effective_fdr=2.5 < raw_fdr=3 -> easier fixture -> higher position_score)")

_all_drift_positive_for_gkp = all(d["drift"] > 3 for d in _gkp_drifts)
ok(_all_drift_positive_for_gkp,
   "GKP drift > 3.0 (saves/cs uplift exceeds any venue shift)")

# ---------------------------------------------------------------------------
# Section C: Promoted players
# ---------------------------------------------------------------------------

print("\n=== Section C: Promoted players ===")

_promoted = _result_gkp["promoted"]
ok(len(_promoted) >= 1,
   "At least 1 player promoted (in position top-5 but not captain top-5)")

_promoted_positions = [p["position"] for p in _promoted]
ok("GKP" in _promoted_positions,
   "At least one promoted player is a GKP (GKP overpromotion confirmed)")

ok(all(p["position"] == "GKP" for p in _promoted),
   "All promoted players are GKPs (saves/cs is the sole driver of promotion)")

# ---------------------------------------------------------------------------
# Section D: Saves/cs contribution quantification
# ---------------------------------------------------------------------------

print("\n=== Section D: Saves/cs contribution per promoted GKP ===")

for d in [x for x in _result_gkp["drift"] if x["web_name"] in {p["web_name"] for p in _promoted}]:
    total_gkp_bonus = d["saves_contribution"] + d["cs_contribution"]
    ok(total_gkp_bonus > 0,
       f"{d['web_name']} promoted: saves_contrib={d['saves_contribution']:.2f} + "
       f"cs_contrib={d['cs_contribution']:.2f} = {total_gkp_bonus:.2f}")

    # Verify the bonus roughly accounts for the promotion drift
    # GKP drift = saves/cs bonus + venue shift - canonical component changes
    ok(d["drift"] > 0,
       f"{d['web_name']} net drift > 0 (saves/cs uplift dominates)")

# ---------------------------------------------------------------------------
# Section E: Fixture type coverage
# ---------------------------------------------------------------------------

print("\n=== Section E: Fixture type coverage ===")

# Normal GW bootstrap — DIFFERENTIAL_BOOTSTRAP has no GKPs at all
_result_normal = analyse_differential_rankings(DIFFERENTIAL_BOOTSTRAP, top_n=5)
print_analysis_report(_result_normal, "DIFFERENTIAL_BOOTSTRAP (normal GW, no GKPs)")

ok(_result_normal["status"] == "ok",
   "Normal bootstrap: analysis status=ok")

_normal_mix_p = _result_normal["position_mix_position"]
ok(_normal_mix_p["GKP"] == 0,
   "Normal bootstrap: 0 GKPs in position top-5 (no GKP candidates present)")

ok(len(_result_normal["promoted"]) == 0,
   "Normal bootstrap: 0 promoted players (no GKPs to overpromote)")

# BGW bootstrap — blank player filtered before ranking; same GKP count
_result_bgw = analyse_differential_rankings(DIFFERENTIAL_BGW_BOOTSTRAP, top_n=5)
print_analysis_report(_result_bgw, "DIFFERENTIAL_BGW_BOOTSTRAP (blank GW)")

ok(_result_bgw["status"] == "ok",
   "BGW bootstrap: analysis status=ok")

ok(_result_bgw["position_mix_position"]["GKP"] == 0,
   "BGW bootstrap: 0 GKPs in position top-5 (no GKP candidates)")

# GKP overpromotion fixture in a "normal GW" context (all teams play)
ok(
    _result_gkp["position_mix_position"]["GKP"] > _result_gkp["position_mix_captain"]["GKP"],
    "GKP overpromotion: position top-5 GKP count > captain top-5 GKP count"
)

# GKP_BALANCED_BOOTSTRAP — after calibration (saves=0.15, form=0.40):
# Kaminski (saves=3.0) drops to rank 6 (position_score 56.75 < Jimenez 57.22).
# This is the expected outcome of the 2026-03-28 calibration.
_result_bal = analyse_differential_rankings(GKP_BALANCED_BOOTSTRAP, top_n=5)
print_analysis_report(_result_bal, "GKP_BALANCED_BOOTSTRAP (calibration verification)")

ok(_result_bal["status"] == "ok",
   "Balanced bootstrap: analysis status=ok")

ok(_result_bal["position_mix_position"]["GKP"] == 0,
   "Balanced bootstrap: 0 GKPs in position top-5 under calibrated weights "
   "(marginal GKP Kaminski eliminated by saves weight reduction)")

ok(len(_result_bal["promoted"]) == 0,
   "Balanced bootstrap: no promoted players under calibrated weights")

# Verify Kaminski is present in the candidates but below rank 5
_bal_all_cands = _result_bal["all_candidates"]
_kaminski_rank = next(
    (i + 1 for i, p in enumerate(_bal_all_cands) if p["web_name"] == "Kaminski"), None
)
ok(_kaminski_rank is not None and _kaminski_rank > 5,
   f"Balanced bootstrap: Kaminski in candidate list at rank {_kaminski_rank} "
   f"(below top-5 threshold, not promoted)")

# ---------------------------------------------------------------------------
# Section F: Regression — V1 validation corpus
# ---------------------------------------------------------------------------

print("\n=== Section F: V1 regression gate ===")

import subprocess
proc = subprocess.run(
    [sys.executable, "run_validation.py", "--no-artifacts"],
    capture_output=True,
    text=True,
    cwd=_HERE,
)
_val_out = proc.stdout + proc.stderr
_val_pass = "44/44 scenarios PASS" in _val_out
ok(_val_pass, "V1 regression: 44/44 PASS")
if not _val_pass:
    print("    Validation output (last 10 lines):")
    for line in _val_out.splitlines()[-10:]:
        print(f"    {line}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
total = _pass + _fail
print(f"Results: {_pass}/{total} PASS")
if _fail:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("All tests passed.")
