# UAT Capture Sheet — 2026-03-28 GKP Calibration Refresh

**Pass label:** gkp_calibration
**Date:** 2026-03-28
**Focus:** Post-calibration differential behavior verification (GKP profile calibration: saves 0.25→0.15, form 0.30→0.40)
**GW / data mode:** GW31 BGW live data (same data state as Pass 20260328)
**Tester:** Claude (automated operator pass)

---

## Pre-flight

| Check | Status |
|---|---|
| `run_validation.py --no-artifacts` passes 44/44 | PASS |
| `run_blank_gw_differential_tests.py` passes 28/28 | PASS |
| `run_gkp_overpromotion_analysis.py` passes 26/26 | PASS |
| `run_gkp_weight_sensitivity.py` passes 18/18 | PASS |
| Production GKP profile in `position_score.py` | form=0.40, saves=0.15, cs=0.15, fixture=0.20 |

---

## CLI Differential — Normal prompt

**Command:** `python fpl_cli.py "good differentials this week" --debug`

**Full debug JSON output:**
```json
{
  "final_text": "Top differentials (ownership < 15%):\n  1. Gordon (NEW, MID) — score 67.3, 7.4% owned, £7.4m\n  2. Beto (EVE, FWD) — score 59.4, 2.6% owned, £5.0m\n  3. King (FUL, MID) — score 59.3, 1.7% owned, £4.4m\n  4. Ellborg (SUN, GKP) — score 58.4, 0.1% owned, £4.0m\n  5. Leno (FUL, GKP) — score 58.2, 2.0% owned, £4.9m",
  "outcome": "ok",
  "intent": "differential_picks",
  "review_passed": true,
  "llm_used": false,
  "differential": {
    "ownership_threshold": 15.0,
    "top_n": 5,
    "picks": [
      {"rank": 1, "web_name": "Gordon",  "team_short": "NEW", "position": "MID", "captain_score": 64.29, "ownership": 7.4,  "now_cost": 74},
      {"rank": 2, "web_name": "Beto",    "team_short": "EVE", "position": "FWD", "captain_score": 56.35, "ownership": 2.6,  "now_cost": 50},
      {"rank": 3, "web_name": "King",    "team_short": "FUL", "position": "MID", "captain_score": 56.27, "ownership": 1.7,  "now_cost": 44},
      {"rank": 4, "web_name": "Ellborg", "team_short": "SUN", "position": "GKP", "captain_score": 44.07, "ownership": 0.1,  "now_cost": 40},
      {"rank": 5, "web_name": "Leno",    "team_short": "FUL", "position": "GKP", "captain_score": 49.2,  "ownership": 2.0,  "now_cost": 49}
    ]
  }
}
```

**Position mix observed:** MID=2, FWD=1, GKP=2

**Comparison to previous pass (20260328):** Previous pass (pre-calibration, GW31 BGW) had 3 GKPs in top-5 (ranks 2, 3, 5 — Ellborg SUN, Benitez CRY, Hermansen WHU), with 2 of those being blank-GW teams (fixed separately). Under calibrated weights, GW31 live data shows 2 GKPs in positions 4 and 5, both playing. GKP rank reduced from 3 to 2 in live output; outfield leads the top-3.

**GKP characterisation for ranks 4–5:**
- Ellborg (SUN, GKP, rank 4): captain_score=44.07, position_score=58.4. SUN plays GW31 (not blank). saves_per_90 high (strong uplift source).
- Leno (FUL, GKP, rank 5): captain_score=49.2, position_score=58.2. FUL plays GW31 home. saves_per_90 moderate.

Both GKPs present in ranks 4–5 are consistent with the residual-risk pattern confirmed by analysis: high-saves GKPs remain above outfield players whose form/xGI is not dominant. This is expected, documented behavior.

---

## CLI Differential — Plain prompt variant

**Command:** `python fpl_cli.py "what are the best differentials"`

**Output:**
```
Top differentials (ownership < 15%):
  1. Gordon (NEW, MID) — score 67.3, 7.4% owned, £7.4m
  2. Beto (EVE, FWD) — score 59.4, 2.6% owned, £5.0m
  3. King (FUL, MID) — score 59.3, 1.7% owned, £4.4m
  4. Ellborg (SUN, GKP) — score 58.4, 0.1% owned, £4.0m
  5. Leno (FUL, GKP) — score 58.2, 2.0% owned, £4.9m
```

Identical to `--debug` path. CLI/plain parity confirmed.

---

## CLI Comparison — GKP vs Outfield using live differential players

**Command:** `python fpl_cli.py "compare Ellborg and Gordon" --debug`

**Key output:**
```
Gordon (67.29) edges Ellborg (58.39) — moderate margin (8.9).
Advantages: stronger form (7.5 vs 4.0); easier fixture (FDR 3H vs 3A); higher xGI output.
```

**Structured metadata:**
```json
"comparison": {
  "winner": "Gordon",
  "margin": 8.9,
  "label": "moderate",
  "player_a": {
    "web_name": "Ellborg", "position": "GKP",
    "captain_score": 44.07, "position_score": 58.39,
    "is_home": false, "effective_fdr": 3.5
  },
  "player_b": {
    "web_name": "Gordon", "position": "MID",
    "captain_score": 64.29, "position_score": 67.29,
    "is_home": true, "effective_fdr": 2.5
  }
}
```

**Check:** `position_score` present on both players. GKP Ellborg position_score (58.39) > captain_score (44.07); drift=+14.32 (saves uplift visible). Gordon MID position_score (67.29) ≈ captain_score (64.29) + 3.0 venue adjustment. Winner correctly Gordon. Margin 8.9 reasonable.

---

## CLI Captain Score — GKP in differential list

**Command:** `python fpl_cli.py "captain score for Ellborg" --debug`

**Output:**
```json
{
  "final_text": "Ellborg (SUN) — Differential [44.07]. Weak attacking process; Secure minutes; High-upside differential profile.",
  "intent": "captain_score",
  "captain": {
    "web_name": "Ellborg", "team_short": "SUN",
    "captain_score": 44.07, "tier": "differential"
  }
}
```

Captain score surface unchanged by calibration (Layer 1 is frozen). Tier and score correct.

---

## CLI Transfer — GKP transfer check

**Command:** `python fpl_cli.py "should I transfer Saka for Leno" --debug`

**Output:**
```json
{
  "final_text": "Recommendation: Transfer in Leno. Score: 58 vs Saka's 53 (+5.7). Advantages: easier fixture (FDR 2H vs 3). Net saving: £4.9m.",
  "intent": "transfer_advice",
  "transfer": {
    "player_out": "Saka", "player_in": "Leno",
    "recommendation": "transfer_in",
    "score_delta": 5.65,
    "price_delta": -49
  }
}
```

**Check:** Transfer uses position_score for ranking. Leno (GKP) position_score=58 > Saka (DEF, doubtful) position_score=53. Score delta = 5.65 which is marginal_transfer_in boundary (5.0) — produces "transfer_in" recommendation. This is the calibrated position_score driving transfer advice. Leno's FUL home fixture (FDR 2H effective_fdr=1.5) is a strong fixture advantage that explains the recommendation. Operator note: this is a cross-position transfer comparison (DEF→GKP); the position_score enables it but the recommendation should be read in context of team needs.

---

## respond() surface — controlled fixture verification

**GKP_OVERPROMOTION_BOOTSTRAP (strong GKPs: Flekken saves=3.5, Fabianski 3.0, Pickford 2.5):**

```
rank=1 Flekken  (GKP) pos_score=66.12 owned=4.2%
rank=2 Fabianski(GKP) pos_score=58.75 owned=3.8%
rank=3 Murillo  (DEF) pos_score=53.56 owned=3.5%
rank=4 Pickford (GKP) pos_score=53.38 owned=5.1%
rank=5 E.Anderson(MID) pos_score=53.19 owned=6.0%
```

GKP=3 in top-5 (residual risk, expected). Murillo DEF at rank 3 — outfield can appear between strong GKPs.

**GKP_BALANCED_BOOTSTRAP (moderate GKPs: Kaminski saves=3.0, Trafford 2.5):**

```
rank=1 Gibbs-White(MID) pos_score=61.28 owned=8.0%
rank=2 Welbeck    (FWD) pos_score=61.28 owned=7.0%
rank=3 A.Pereira  (MID) pos_score=59.22 owned=9.0%
rank=4 Estupinan  (DEF) pos_score=58.58 owned=3.5%
rank=5 Jimenez    (FWD) pos_score=57.22 owned=10.0%
```

GKP=0 in top-5 (calibration effective). Kaminski at rank 6 (pos_score=56.75). No GKPs promoted.

---

## Regression suites

| Suite | Result |
|---|---|
| `run_validation.py --no-artifacts` | 44/44 PASS |
| `run_blank_gw_differential_tests.py` | 28/28 PASS |
| `run_gkp_overpromotion_analysis.py` | 26/26 PASS |
| `run_gkp_weight_sensitivity.py` | 18/18 PASS |

---

## Exit Decision Checklist

- [x] Differential intent routing correct on all tested prompts
- [x] Blank-GW filter still active (29328 BGW regression 28/28 PASS)
- [x] Calibrated GKP profile confirmed in production (form=0.40, saves=0.15)
- [x] Marginal GKP elimination confirmed in balanced controlled fixture (GKP=0)
- [x] Residual strong-GKP caution documented and not re-opened
- [x] No new blockers found
- [x] captain_score surface unchanged (Layer 1 frozen)
- [x] Transfer advice reflects calibrated position_score (Leno example correct)
- [x] 44/44 V1 validation corpus PASS
- [x] Pass Index row added to UAT_FINDINGS.md
- [x] Compact summary inserted above END OF REAL PASS SUMMARIES marker
