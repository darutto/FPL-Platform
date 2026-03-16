"""
run_phase5d_tests.py
====================
Phase 5d: comparison explainability and renderer enrichment.

Validates that ``compare_players()`` output is enriched with deterministic
comparative reason phrases (``comparison_reasons``) and a margin clarity
label (``margin_label``), and that the ``recommendation`` text surfaces
these in a human-readable form.

Run::

    cd packages/fpl-grounded-assistant
    PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\\
    ../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\\
    ../fpl-api-client:../fpl-pipeline:. python run_phase5d_tests.py

Sections
--------
A  -- _margin_label(): threshold constants and label values
B  -- _explain_comparison(): per-signal coverage with synthetic player dicts
C  -- compare_players() additive output fields (STANDARD_BOOTSTRAP)
D  -- recommendation text enrichment
E  -- Phase 5c/5b/5a regression
"""
from __future__ import annotations

import os
import sys

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

_passed = 0
_failed = 0


def ok(label: str, expr: bool) -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        print(f"FAIL  {label}")


def eq(label: str, got: object, want: object) -> None:
    if got != want:
        print(f"FAIL  {label}  got={got!r}  want={want!r}")
    ok(label, got == want)


from fpl_grounded_assistant import (
    STANDARD_BOOTSTRAP,
    INTENT_COMPARE_PLAYERS,
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    compare_players,
    dispatch,
    respond,
    ConversationSession,
    _explain_comparison,
    _margin_label,
    _FORM_ADV_THRESHOLD,
    _FDR_ADV_THRESHOLD,
    _XGI_ADV_THRESHOLD,
    _RISK_ADV_THRESHOLD,
    _MARGIN_NARROW,
    _MARGIN_CLEAR,
)


# ---------------------------------------------------------------------------
# Helper: build a synthetic scored player dict for _explain_comparison tests
# ---------------------------------------------------------------------------

def _make_player(
    form: float,
    fdr: int,
    xgi_per_90: float,
    minutes_risk: float,
    role_bonus: float = 0.0,
) -> dict:
    return {
        "score_inputs": {
            "form":               form,
            "fixture_difficulty": fdr,
            "xgi_per_90":         xgi_per_90,
            "minutes_risk":       minutes_risk,
        },
        "role_signals": {"role_bonus": role_bonus},
    }


# ===========================================================================
# Section A -- _margin_label() threshold constants and values
# ===========================================================================

print("A  _margin_label() thresholds")

# Constant exports
ok("A1  _MARGIN_NARROW exported",       isinstance(_MARGIN_NARROW, float))
ok("A2  _MARGIN_CLEAR exported",        isinstance(_MARGIN_CLEAR, float))
ok("A3  NARROW < CLEAR",                _MARGIN_NARROW < _MARGIN_CLEAR)

# Narrow edge
eq("A4  0.0 → narrow",                  _margin_label(0.0),              "narrow")
eq("A5  just below NARROW → narrow",    _margin_label(_MARGIN_NARROW - 0.01), "narrow")

# Moderate edge
eq("A6  exactly NARROW → moderate",     _margin_label(_MARGIN_NARROW),   "moderate")
eq("A7  between NARROW and CLEAR",      _margin_label((_MARGIN_NARROW + _MARGIN_CLEAR) / 2), "moderate")
eq("A8  just below CLEAR → moderate",   _margin_label(_MARGIN_CLEAR - 0.01), "moderate")

# Clear edge
eq("A9  exactly CLEAR → clear",         _margin_label(_MARGIN_CLEAR),    "clear")
eq("A10 large margin → clear",          _margin_label(25.0),             "clear")


# ===========================================================================
# Section B -- _explain_comparison(): per-signal coverage
# ===========================================================================

print("B  _explain_comparison() signal coverage")

# Threshold constant exports
ok("B1  _FORM_ADV_THRESHOLD exported",  isinstance(_FORM_ADV_THRESHOLD, float))
ok("B2  _FDR_ADV_THRESHOLD exported",   isinstance(_FDR_ADV_THRESHOLD, int))
ok("B3  _XGI_ADV_THRESHOLD exported",   isinstance(_XGI_ADV_THRESHOLD, float))
ok("B4  _RISK_ADV_THRESHOLD exported",  isinstance(_RISK_ADV_THRESHOLD, float))

# Form advantage: delta exactly at threshold → included
_w_form = _make_player(form=9.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_l_form = _make_player(form=9.0 - _FORM_ADV_THRESHOLD, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_b5 = _explain_comparison(_w_form, _l_form)
ok("B5  form delta >= threshold → included",    any("form" in r for r in _b5))
ok("B6  form reason contains winner form value", any("9.0" in r for r in _b5))

# Form advantage: delta below threshold → not included
_w_form2 = _make_player(form=8.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_l_form2 = _make_player(form=8.0 - (_FORM_ADV_THRESHOLD - 0.1), fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_b7 = _explain_comparison(_w_form2, _l_form2)
ok("B7  form delta below threshold → not included", not any("form" in r for r in _b7))

# FDR advantage: winner FDR lower by threshold
_w_fdr = _make_player(form=7.0, fdr=2, xgi_per_90=0.20, minutes_risk=0.0)
_l_fdr = _make_player(form=7.0, fdr=2 + _FDR_ADV_THRESHOLD, xgi_per_90=0.20, minutes_risk=0.0)
_b8 = _explain_comparison(_w_fdr, _l_fdr)
ok("B8  FDR advantage detected",   any("fixture" in r for r in _b8))
ok("B9  FDR values in reason",     any("FDR" in r for r in _b8))

# FDR equal: no advantage
_w_fdr2 = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_l_fdr2 = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_b10 = _explain_comparison(_w_fdr2, _l_fdr2)
ok("B10 equal FDR → no fixture reason", not any("fixture" in r for r in _b10))

# xGI advantage (use 2× threshold to avoid floating-point boundary)
_w_xgi = _make_player(form=7.0, fdr=3, xgi_per_90=0.50, minutes_risk=0.0)
_l_xgi = _make_player(form=7.0, fdr=3, xgi_per_90=0.50 - _XGI_ADV_THRESHOLD * 2, minutes_risk=0.0)
_b11 = _explain_comparison(_w_xgi, _l_xgi)
ok("B11 xGI advantage detected",   any("xGI" in r for r in _b11))

# Minutes security advantage
_w_mins = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_l_mins = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=_RISK_ADV_THRESHOLD)
_b12 = _explain_comparison(_w_mins, _l_mins)
ok("B12 minutes security advantage detected", any("minutes" in r for r in _b12))

# Minutes risk below threshold → not included
_w_mins2 = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_l_mins2 = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=_RISK_ADV_THRESHOLD - 1.0)
_b13 = _explain_comparison(_w_mins2, _l_mins2)
ok("B13 minutes delta below threshold → not included", not any("minutes" in r for r in _b13))

# Set-piece advantage
_w_sp = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0, role_bonus=5.0)
_l_sp = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0, role_bonus=0.0)
_b14 = _explain_comparison(_w_sp, _l_sp)
ok("B14 set-piece advantage detected", any("set-piece" in r for r in _b14))

# Equal role bonus → no set-piece advantage
_w_sp2 = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0, role_bonus=5.0)
_l_sp2 = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0, role_bonus=5.0)
_b15 = _explain_comparison(_w_sp2, _l_sp2)
ok("B15 equal role bonus → no set-piece reason", not any("set-piece" in r for r in _b15))

# All neutral: empty list
_w_neut = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_l_neut = _make_player(form=7.0, fdr=3, xgi_per_90=0.20, minutes_risk=0.0)
_b16 = _explain_comparison(_w_neut, _l_neut)
ok("B16 all neutral → empty list",  _b16 == [])

# Multiple signals: all five advantages at once
_w_all = _make_player(
    form=9.5, fdr=2, xgi_per_90=0.60,
    minutes_risk=0.0, role_bonus=5.0
)
_l_all = _make_player(
    form=7.0, fdr=4, xgi_per_90=0.40,
    minutes_risk=50.0, role_bonus=0.0
)
_b17 = _explain_comparison(_w_all, _l_all)
ok("B17 all five signals → 5 reasons", len(_b17) == 5)
ok("B18 form in multi-signal",         any("form" in r for r in _b17))
ok("B19 fixture in multi-signal",      any("fixture" in r for r in _b17))
ok("B20 xGI in multi-signal",          any("xGI" in r for r in _b17))
ok("B21 minutes in multi-signal",      any("minutes" in r for r in _b17))
ok("B22 set-piece in multi-signal",    any("set-piece" in r for r in _b17))

# Returns a list
ok("B23 returns list type",            isinstance(_b16, list))


# ===========================================================================
# Section C -- compare_players() additive output fields
# ===========================================================================

print("C  compare_players() additive fields")

_c1 = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)
eq("C1  status ok",                   _c1["status"], "ok")

# New fields present
ok("C2  comparison_reasons in output", "comparison_reasons" in _c1)
ok("C3  margin_label in output",       "margin_label" in _c1)
ok("C4  comparison_reasons is list",   isinstance(_c1["comparison_reasons"], list))
ok("C5  margin_label is string",       isinstance(_c1["margin_label"], str))
ok("C6  margin_label valid value",
   _c1["margin_label"] in {"narrow", "moderate", "clear"})

# Existing fields still present
ok("C7  winner still present",         "winner" in _c1)
ok("C8  margin still present",         "margin" in _c1)
ok("C9  player_a still present",       "player_a" in _c1)
ok("C10 player_b still present",       "player_b" in _c1)
ok("C11 recommendation still present", "recommendation" in _c1)

# Haaland vs Salah specifics: Salah wins (stronger form)
eq("C12 winner = Salah",               _c1["winner"], "Salah")
ok("C13 comparison_reasons non-empty", len(_c1["comparison_reasons"]) > 0)
ok("C14 form reason present",
   any("form" in r for r in _c1["comparison_reasons"]))
# margin ~5.73 → "moderate"
eq("C15 margin_label moderate",        _c1["margin_label"], "moderate")

# Not-found: no comparison_reasons or margin_label expected (error output shape)
_c16 = compare_players("Haaland", "NoSuchPlayer99", STANDARD_BOOTSTRAP)
eq("C16 not_found has no comparison_reasons",
   "comparison_reasons" not in _c16, True)

# Tie case: comparison_reasons should be empty list (symmetric inputs)
# Use Haaland vs Haaland (same player → same inputs → tie)
_c17 = compare_players("Haaland", "Haaland", STANDARD_BOOTSTRAP)
eq("C17 tie winner is None",           _c17.get("winner"), None)
ok("C18 tie comparison_reasons empty", _c17.get("comparison_reasons") == [])
eq("C19 tie margin_label narrow",      _c17.get("margin_label"), "narrow")


# ===========================================================================
# Section D -- recommendation text enrichment
# ===========================================================================

print("D  recommendation text enrichment")

_d1 = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)
_rec = _d1["recommendation"]

ok("D1  recommendation non-empty",    bool(_rec))
ok("D2  winner name in rec",          "Salah" in _rec)
ok("D3  loser name in rec",           "Haaland" in _rec)
ok("D4  scores in rec",               str(_d1["player_a"]["captain_score"]) in _rec
                                      or str(_d1["player_b"]["captain_score"]) in _rec)
ok("D5  margin_label in rec",         _d1["margin_label"] in _rec)
ok("D6  'Advantages:' in rec",        "Advantages:" in _rec)
ok("D7  form reason in rec",          any("form" in r for r in _d1["comparison_reasons"])
                                      and "form" in _rec)

# Tie recommendation: no "edges", no "Advantages:"
_d8 = compare_players("Haaland", "Haaland", STANDARD_BOOTSTRAP)
_trec = _d8.get("recommendation", "")
ok("D8  tie rec non-empty",           bool(_trec))
ok("D9  tie rec contains 'tied'",     "tied" in _trec.lower())
ok("D10 tie rec no 'edges'",          "edges" not in _trec.lower())

# Not-found: renderer still works
from fpl_grounded_assistant.renderer import _render_compare_players
_d11_raw = compare_players("Haaland", "NoSuchPlayer99", STANDARD_BOOTSTRAP)
_d11_text = _render_compare_players(_d11_raw)
ok("D11 not_found renders non-empty", bool(_d11_text))
ok("D12 not_found mentions query",    "Haaland" in _d11_text or "NoSuchPlayer99" in _d11_text)

# Haaland vs Saka: Haaland should win clearly (>= 10 margin) — multiple advantages
_d13 = compare_players("Haaland", "Saka", STANDARD_BOOTSTRAP)
eq("D13 Haaland beats Saka",          _d13["winner"], "Haaland")
eq("D14 clear margin",                _d13["margin_label"], "clear")
ok("D15 multiple advantages",         len(_d13["comparison_reasons"]) >= 2)
ok("D16 form advantage present",
   any("form" in r for r in _d13["comparison_reasons"]))
ok("D17 minutes advantage present",
   any("minutes" in r for r in _d13["comparison_reasons"]))


# ===========================================================================
# Section E -- Phase 5c/5b/5a regression
# ===========================================================================

print("E  Phase 5c/5b/5a regression")

# Phase 5a: compare_players() unchanged core contract
_e1 = compare_players("Haaland", "Salah", STANDARD_BOOTSTRAP)
eq("E1  5a winner still Salah",        _e1["winner"], "Salah")
ok("E2  5a margin still ~5.73",        abs(_e1["margin"] - 5.73) < 0.5)
ok("E3  5a player_a.reasons non-empty", bool(_e1["player_a"]["reasons"]))

# Phase 5b: dispatch() end-to-end
_e4 = dispatch("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("E4  5b dispatch outcome ok",       _e4.outcome, OUTCOME_OK)
eq("E5  5b dispatch intent",           _e4.intent, INTENT_COMPARE_PLAYERS)
ok("E6  5b answer_text non-empty",     bool(_e4.answer_text))
ok("E7  5b answer_text == recommendation",
   _e4.answer_text == _e4.raw_output.get("recommendation", ""))

# Phase 5b: respond() end-to-end
_e8 = respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
eq("E8  5b respond outcome ok",        _e8.outcome, OUTCOME_OK)
ok("E9  5b respond final_text",        bool(_e8.final_text))
ok("E10 5b respond mentions Salah",    "Salah" in _e8.final_text)

# Phase 5c: comparison follow-up still works
_sess = ConversationSession()
_sess.respond("compare Haaland and Salah", STANDARD_BOOTSTRAP)
_e11 = _sess.respond("And Saka?", STANDARD_BOOTSTRAP)
eq("E11 5c follow-up outcome ok",      _e11.outcome, OUTCOME_OK)
ok("E12 5c follow-up mentions Haaland", "Haaland" in _e11.final_text)
ok("E13 5c follow-up mentions Saka",   "Saka" in _e11.final_text)
# Richer recommendation still contains both names
ok("E14 5c follow-up recommendation enriched",
   "Advantages:" in _e11.final_text or "clear" in _e11.final_text)


# ===========================================================================
# Summary
# ===========================================================================

_total = _passed + _failed
print(f"\n{'='*50}")
print(f"Phase 5d: {_passed}/{_total} PASS")
if _failed:
    print(f"          {_failed} FAILED")
    sys.exit(1)
else:
    print("          All assertions passed.")
