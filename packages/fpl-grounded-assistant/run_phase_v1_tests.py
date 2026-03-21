"""
run_phase_v1_tests.py
=====================
Phase V1: Frozen Validation Corpus and Cross-Surface Smoke Runner

Tests that verify:
  A  Corpus structure — completeness and required scenarios present
  B  Stateless CLI surface — contract values for key scenarios
  C  Stateless HTTP surface — contract values for key scenarios
  D  CLI/HTTP cross-surface parity for stateless scenarios
  E  Session CLI deterministic paths — comparison follow-up, pronoun
  F  Session HTTP deterministic paths — comparison follow-up, pronoun
  G  LLM stub paths — comparison_followup_llm, pronoun_llm via session_cli
  H  Structured metadata presence/absence per scenario
  I  Artifact output — JSON and Markdown files produced and valid
  J  Failure-mode scenarios — graceful handling across surfaces
  K  Full validation runner passes all 13 scenarios

Run::

    cd packages/fpl-grounded-assistant
    python run_phase_v1_tests.py
"""
from __future__ import annotations

import json
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


def ok(label: str, expr: bool, detail: str = "") -> None:
    global _passed, _failed
    if expr:
        _passed += 1
    else:
        _failed += 1
        msg = f"FAIL  {label}"
        if detail:
            msg += f"\n      {detail}"
        print(msg)


# ===========================================================================
# Imports
# ===========================================================================

from validation_corpus import (                                            # noqa: E402
    VALIDATION_SCENARIOS, SCENARIO_IDS, SCENARIO_BY_ID, ValidationScenario,
)
from run_validation import (                                               # noqa: E402
    run_cli_surface, run_http_surface,
    run_session_cli_surface, run_session_http_surface,
    run_all_scenarios,
    write_json_artifact, write_markdown_artifact,
    COMP_LLM_STUB, REF_LLM_STUB,
)
from fpl_grounded_assistant.conversation_fixtures import (                # noqa: E402
    STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP,
)


# ===========================================================================
# Section A — Corpus structure
# ===========================================================================
print("\n--- A: Corpus structure ---")

ok("A1 corpus has 13 scenarios",           len(VALIDATION_SCENARIOS) == 13,
   str(len(VALIDATION_SCENARIOS)))
ok("A2 all IDs are unique",
   len(set(SCENARIO_IDS)) == len(SCENARIO_IDS))
ok("A3 SCENARIO_BY_ID has 13 entries",     len(SCENARIO_BY_ID) == 13)

# Required scenario IDs
_required_ids = {
    "direct_captain_score",
    "ranked_captain_candidates",
    "player_summary",
    "player_resolve",
    "direct_comparison",
    "unsupported_prompt",
    "ambiguous_player",
    "not_found_player",
    "no_session_follow_up",
    "comparison_followup_det",
    "comparison_followup_llm",
    "pronoun_det",
    "pronoun_llm",
}
ok("A4 all required scenario IDs present",
   _required_ids.issubset(set(SCENARIO_IDS)),
   str(_required_ids - set(SCENARIO_IDS)))

# All scenarios are ValidationScenario instances
ok("A5 all entries are ValidationScenario",
   all(isinstance(s, ValidationScenario) for s in VALIDATION_SCENARIOS))

# Surfaces coverage
_all_surfaces = {s for sc in VALIDATION_SCENARIOS for s in sc.surfaces}
ok("A6 cli surface present in corpus",        "cli" in _all_surfaces)
ok("A7 http surface present in corpus",       "http" in _all_surfaces)
ok("A8 session_cli surface present",          "session_cli" in _all_surfaces)
ok("A9 session_http surface present",         "session_http" in _all_surfaces)

# LLM stub scenarios are session_cli only
_comp_llm = SCENARIO_BY_ID["comparison_followup_llm"]
_pron_llm  = SCENARIO_BY_ID["pronoun_llm"]
ok("A10 comparison_followup_llm surfaces == session_cli only",
   set(_comp_llm.surfaces) == {"session_cli"})
ok("A11 pronoun_llm surfaces == session_cli only",
   set(_pron_llm.surfaces) == {"session_cli"})

# Deterministic session scenarios include session_http
_cmp_det = SCENARIO_BY_ID["comparison_followup_det"]
_pro_det  = SCENARIO_BY_ID["pronoun_det"]
ok("A12 comparison_followup_det includes session_http",
   "session_http" in _cmp_det.surfaces)
ok("A13 pronoun_det includes session_http",
   "session_http" in _pro_det.surfaces)


# ===========================================================================
# Section B — Stateless CLI surface
# ===========================================================================
print("\n--- B: Stateless CLI surface ---")

_b_cap  = run_cli_surface(SCENARIO_BY_ID["direct_captain_score"],   STANDARD_BOOTSTRAP)
_b_rank = run_cli_surface(SCENARIO_BY_ID["ranked_captain_candidates"], STANDARD_BOOTSTRAP)
_b_cmp  = run_cli_surface(SCENARIO_BY_ID["direct_comparison"],      STANDARD_BOOTSTRAP)
_b_uns  = run_cli_surface(SCENARIO_BY_ID["unsupported_prompt"],      STANDARD_BOOTSTRAP)
_b_nf   = run_cli_surface(SCENARIO_BY_ID["not_found_player"],        STANDARD_BOOTSTRAP)

ok("B1  captain_score CLI intent",   _b_cap.get("intent") == "captain_score")
ok("B2  captain_score CLI outcome",  _b_cap.get("outcome") == "ok")
ok("B3  captain_score CLI supported", _b_cap.get("supported") is True)

ok("B4  rank_candidates CLI intent",  _b_rank.get("intent") == "rank_candidates")
ok("B5  rank_candidates CLI outcome", _b_rank.get("outcome") == "ok")
ok("B6  rank_candidates CLI supported", _b_rank.get("supported") is True)

ok("B7  compare_players CLI intent",  _b_cmp.get("intent") == "compare_players")
ok("B8  compare_players CLI outcome", _b_cmp.get("outcome") == "ok")

ok("B9  unsupported CLI intent",      _b_uns.get("intent") == "unsupported")
ok("B10 unsupported CLI supported",   _b_uns.get("supported") is False)

ok("B11 not_found CLI outcome",       _b_nf.get("outcome") == "not_found")
ok("B12 not_found CLI supported",     _b_nf.get("supported") is True)


# ===========================================================================
# Section C — Stateless HTTP surface
# ===========================================================================
print("\n--- C: Stateless HTTP surface ---")

_c_cap  = run_http_surface(SCENARIO_BY_ID["direct_captain_score"],    STANDARD_BOOTSTRAP)
_c_rank = run_http_surface(SCENARIO_BY_ID["ranked_captain_candidates"], STANDARD_BOOTSTRAP)
_c_cmp  = run_http_surface(SCENARIO_BY_ID["direct_comparison"],       STANDARD_BOOTSTRAP)
_c_uns  = run_http_surface(SCENARIO_BY_ID["unsupported_prompt"],       STANDARD_BOOTSTRAP)
_c_amb  = run_http_surface(SCENARIO_BY_ID["ambiguous_player"],         AMBIGUOUS_BOOTSTRAP)
_c_nf   = run_http_surface(SCENARIO_BY_ID["not_found_player"],         STANDARD_BOOTSTRAP)
_c_nss  = run_http_surface(SCENARIO_BY_ID["no_session_follow_up"],     STANDARD_BOOTSTRAP)

ok("C1  captain_score HTTP status",   _c_cap.get("http_status") == 200)
ok("C2  captain_score HTTP intent",   _c_cap.get("intent") == "captain_score")
ok("C3  captain_score HTTP outcome",  _c_cap.get("outcome") == "ok")

ok("C4  rank_candidates HTTP intent", _c_rank.get("intent") == "rank_candidates")
ok("C5  rank_candidates HTTP outcome", _c_rank.get("outcome") == "ok")

ok("C6  compare_players HTTP intent", _c_cmp.get("intent") == "compare_players")
ok("C7  compare_players HTTP outcome", _c_cmp.get("outcome") == "ok")

ok("C8  unsupported HTTP supported",  _c_uns.get("supported") is False)
ok("C9  unsupported HTTP outcome",    _c_uns.get("outcome") == "unsupported_intent")

ok("C10 ambiguous HTTP outcome",      _c_amb.get("outcome") == "ambiguous")
ok("C11 ambiguous HTTP supported",    _c_amb.get("supported") is True)
ok("C12 ambiguous HTTP intent",       _c_amb.get("intent") == "player_resolve")

ok("C13 not_found HTTP outcome",      _c_nf.get("outcome") == "not_found")
ok("C14 not_found HTTP supported",    _c_nf.get("supported") is True)

ok("C15 no_session_follow_up HTTP outcome",  _c_nss.get("outcome") == "not_found")
ok("C16 no_session_follow_up HTTP supported", _c_nss.get("supported") is True)
ok("C17 no_session_follow_up HTTP intent",   _c_nss.get("intent") == "captain_score")


# ===========================================================================
# Section D — CLI/HTTP cross-surface parity for stateless scenarios
# ===========================================================================
print("\n--- D: CLI/HTTP cross-surface parity ---")

_stateless_ids = [
    "direct_captain_score", "ranked_captain_candidates",
    "player_summary", "player_resolve", "direct_comparison",
    "unsupported_prompt", "not_found_player", "no_session_follow_up",
]

for _sid in _stateless_ids:
    _sc  = SCENARIO_BY_ID[_sid]
    _bs  = AMBIGUOUS_BOOTSTRAP if _sc.bootstrap == "ambiguous" else STANDARD_BOOTSTRAP
    _cr  = run_cli_surface(_sc, _bs)
    _hr  = run_http_surface(_sc, _bs)
    ok(f"D  {_sid}: CLI==HTTP intent",
       _cr.get("intent") == _hr.get("intent"),
       f"CLI={_cr.get('intent')!r}, HTTP={_hr.get('intent')!r}")
    ok(f"D  {_sid}: CLI==HTTP outcome",
       _cr.get("outcome") == _hr.get("outcome"),
       f"CLI={_cr.get('outcome')!r}, HTTP={_hr.get('outcome')!r}")
    ok(f"D  {_sid}: CLI==HTTP supported",
       _cr.get("supported") == _hr.get("supported"),
       f"CLI={_cr.get('supported')}, HTTP={_hr.get('supported')}")


# ===========================================================================
# Section E — Session CLI deterministic paths
# ===========================================================================
print("\n--- E: Session CLI deterministic paths ---")

_e_cmp_det = run_session_cli_surface(
    SCENARIO_BY_ID["comparison_followup_det"], STANDARD_BOOTSTRAP
)
ok("E1 comparison_followup_det intent == compare_players",
   _e_cmp_det.get("intent") == "compare_players", str(_e_cmp_det.get("intent")))
ok("E2 comparison_followup_det outcome == ok",
   _e_cmp_det.get("outcome") == "ok")
ok("E3 comparison_followup_det supported",
   _e_cmp_det.get("supported") is True)
ok("E4 comparison_followup_det resolver_source == comparison_followup",
   _e_cmp_det.get("resolver_source") == "comparison_followup",
   str(_e_cmp_det.get("resolver_source")))
ok("E5 comparison_followup_det comparison present",
   _e_cmp_det.get("comparison") is not None)

_e_pro_det = run_session_cli_surface(
    SCENARIO_BY_ID["pronoun_det"], STANDARD_BOOTSTRAP
)
ok("E6 pronoun_det intent == captain_score",
   _e_pro_det.get("intent") == "captain_score")
ok("E7 pronoun_det outcome == ok",
   _e_pro_det.get("outcome") == "ok")
ok("E8 pronoun_det resolver_source == fallback_regex",
   _e_pro_det.get("resolver_source") == "fallback_regex",
   str(_e_pro_det.get("resolver_source")))
ok("E9 pronoun_det captain present",
   _e_pro_det.get("captain") is not None)


# ===========================================================================
# Section F — Session HTTP deterministic paths
# ===========================================================================
print("\n--- F: Session HTTP deterministic paths ---")

_f_cmp_det = run_session_http_surface(
    SCENARIO_BY_ID["comparison_followup_det"], STANDARD_BOOTSTRAP
)
ok("F1 comparison_followup_det HTTP intent == compare_players",
   _f_cmp_det.get("intent") == "compare_players")
ok("F2 comparison_followup_det HTTP outcome == ok",
   _f_cmp_det.get("outcome") == "ok")
ok("F3 comparison_followup_det HTTP supported",
   _f_cmp_det.get("supported") is True)
ok("F4 comparison_followup_det HTTP comparison present",
   _f_cmp_det.get("comparison") is not None)

_f_pro_det = run_session_http_surface(
    SCENARIO_BY_ID["pronoun_det"], STANDARD_BOOTSTRAP
)
ok("F5 pronoun_det HTTP intent == captain_score",
   _f_pro_det.get("intent") == "captain_score")
ok("F6 pronoun_det HTTP outcome == ok",
   _f_pro_det.get("outcome") == "ok")
ok("F7 pronoun_det HTTP captain present",
   _f_pro_det.get("captain") is not None)

# CLI/HTTP parity for deterministic session scenarios
ok("F8 comparison_followup_det CLI==HTTP intent",
   _e_cmp_det.get("intent") == _f_cmp_det.get("intent"))
ok("F9 comparison_followup_det CLI==HTTP outcome",
   _e_cmp_det.get("outcome") == _f_cmp_det.get("outcome"))
ok("F10 pronoun_det CLI==HTTP intent",
   _e_pro_det.get("intent") == _f_pro_det.get("intent"))
ok("F11 pronoun_det CLI==HTTP outcome",
   _e_pro_det.get("outcome") == _f_pro_det.get("outcome"))


# ===========================================================================
# Section G — LLM stub paths (session_cli only)
# ===========================================================================
print("\n--- G: LLM stub paths ---")

_g_cmp_llm = run_session_cli_surface(
    SCENARIO_BY_ID["comparison_followup_llm"], STANDARD_BOOTSTRAP
)
ok("G1 comparison_followup_llm intent == compare_players",
   _g_cmp_llm.get("intent") == "compare_players",
   str(_g_cmp_llm.get("intent")))
ok("G2 comparison_followup_llm outcome == ok",
   _g_cmp_llm.get("outcome") == "ok",
   str(_g_cmp_llm.get("outcome")))
ok("G3 comparison_followup_llm resolver_source == comparison_followup_llm",
   _g_cmp_llm.get("resolver_source") == "comparison_followup_llm",
   str(_g_cmp_llm.get("resolver_source")))
ok("G4 comparison_followup_llm comparison present",
   _g_cmp_llm.get("comparison") is not None)
ok("G5 comparison_followup_llm rewritten question contains Saka",
   "Saka" in (_g_cmp_llm.get("rewritten_question") or ""),
   str(_g_cmp_llm.get("rewritten_question")))

_g_pro_llm = run_session_cli_surface(
    SCENARIO_BY_ID["pronoun_llm"], STANDARD_BOOTSTRAP
)
ok("G6 pronoun_llm intent == captain_score",
   _g_pro_llm.get("intent") == "captain_score",
   str(_g_pro_llm.get("intent")))
ok("G7 pronoun_llm outcome == ok",
   _g_pro_llm.get("outcome") == "ok",
   str(_g_pro_llm.get("outcome")))
ok("G8 pronoun_llm resolver_source == llm",
   _g_pro_llm.get("resolver_source") == "llm",
   str(_g_pro_llm.get("resolver_source")))
ok("G9 pronoun_llm captain present",
   _g_pro_llm.get("captain") is not None)
ok("G10 pronoun_llm rewritten question contains Salah",
   "Salah" in (_g_pro_llm.get("rewritten_question") or ""),
   str(_g_pro_llm.get("rewritten_question")))

# Stubs are distinct objects with correct interface
ok("G11 COMP_LLM_STUB has .messages.create",
   callable(getattr(getattr(COMP_LLM_STUB, "messages", None), "create", None)))
ok("G12 REF_LLM_STUB has .messages.create",
   callable(getattr(getattr(REF_LLM_STUB, "messages", None), "create", None)))


# ===========================================================================
# Section H — Structured metadata presence/absence
# ===========================================================================
print("\n--- H: Structured metadata presence/absence ---")

# Captain metadata: present for captain_score OK, absent for others
ok("H1  captain present for captain_score OK (CLI)",
   _b_cap.get("captain") is not None)
ok("H2  captain.tier is valid string",
   isinstance((_b_cap.get("captain") or {}).get("tier"), str) and
   len((_b_cap.get("captain") or {}).get("tier", "")) > 0)
ok("H3  captain absent for comparison (CLI)",
   _b_cmp.get("captain") is None)
ok("H4  captain absent for ranking (CLI)",
   _b_rank.get("captain") is None)
ok("H5  captain absent for unsupported (CLI)",
   _b_uns.get("captain") is None)

# Captain_ranking: present for rank_candidates OK, absent for others
ok("H6  captain_ranking present for ranking OK (CLI)",
   _b_rank.get("captain_ranking") is not None)
ok("H7  captain_ranking is list of 3 (CLI)",
   isinstance(_b_rank.get("captain_ranking"), list) and
   len(_b_rank.get("captain_ranking", [])) == 3,
   str(len(_b_rank.get("captain_ranking") or [])))
ok("H8  captain_ranking #1 is Salah (CLI)",
   (_b_rank.get("captain_ranking") or [{}])[0].get("web_name") == "Salah")
ok("H9  captain_ranking absent for captain_score (CLI)",
   _b_cap.get("captain_ranking") is None)
ok("H10 captain_ranking absent for comparison (CLI)",
   _b_cmp.get("captain_ranking") is None)

# Comparison: present for compare_players OK, absent for others
ok("H11 comparison present for compare OK (CLI)",
   _b_cmp.get("comparison") is not None)
ok("H12 comparison has winner key",
   "winner" in (_b_cmp.get("comparison") or {}))
ok("H13 comparison has margin key",
   "margin" in (_b_cmp.get("comparison") or {}))
ok("H14 comparison absent for captain_score (CLI)",
   _b_cap.get("comparison") is None)

# HTTP side mirrors CLI for presence/absence
ok("H15 captain present for captain_score OK (HTTP)",
   _c_cap.get("captain") is not None)
ok("H16 captain_ranking present for ranking OK (HTTP)",
   _c_rank.get("captain_ranking") is not None)
ok("H17 comparison present for compare OK (HTTP)",
   _c_cmp.get("comparison") is not None)

# Null (not missing) for Pydantic non-matching HTTP fields
ok("H18 captain is None (not absent) for comparison HTTP",
   _c_cmp.get("captain") is None)
ok("H19 comparison is None (not absent) for captain HTTP",
   _c_cap.get("comparison") is None)


# ===========================================================================
# Section I — Artifact output
# ===========================================================================
print("\n--- I: Artifact output ---")

import tempfile, pathlib

_tmp = tempfile.mkdtemp()
_json_path = os.path.join(_tmp, "validation_results.json")
_md_path   = os.path.join(_tmp, "validation_report.md")

# Run scenarios and write to temp dir
_all_results = run_all_scenarios()
write_json_artifact(_all_results, _json_path)
write_markdown_artifact(_all_results, _md_path)

ok("I1 JSON artifact written",   os.path.isfile(_json_path))
ok("I2 Markdown artifact written", os.path.isfile(_md_path))

_json_data: dict = {}
try:
    with open(_json_path, encoding="utf-8") as _f:
        _json_data = json.load(_f)
    ok("I3 JSON artifact is valid JSON", True)
except Exception as e:
    ok("I3 JSON artifact is valid JSON", False, str(e))

ok("I4 JSON scenario_count == 13",
   _json_data.get("scenario_count") == 13, str(_json_data.get("scenario_count")))
ok("I5 JSON pass_count field present",   "pass_count" in _json_data)
ok("I6 JSON fail_count field present",   "fail_count" in _json_data)
ok("I7 JSON run_at field present",       "run_at" in _json_data)
ok("I8 JSON scenarios is list of 13",
   isinstance(_json_data.get("scenarios"), list) and
   len(_json_data.get("scenarios", [])) == 13)

_md_text = pathlib.Path(_md_path).read_text(encoding="utf-8")
ok("I9  Markdown non-empty",             len(_md_text) > 200)
ok("I10 Markdown has summary section",   "## Summary" in _md_text)
ok("I11 Markdown has overview table",    "## Scenario Overview" in _md_text)
ok("I12 Markdown has details section",   "## Scenario Details" in _md_text)
ok("I13 Markdown mentions all 13 IDs",
   all(sid in _md_text for sid in SCENARIO_IDS),
   str([sid for sid in SCENARIO_IDS if sid not in _md_text]))

# Each scenario in JSON has required keys
_required_scenario_keys = {
    "id", "family", "description", "question", "surfaces_tested",
    "surface_results", "expected", "failures", "pass",
}
ok("I14 each JSON scenario has required keys",
   all(_required_scenario_keys.issubset(set(r.keys()))
       for r in _json_data.get("scenarios", [])),
   str([r.get("id") for r in _json_data.get("scenarios", [])
        if not _required_scenario_keys.issubset(set(r.keys()))]))


# ===========================================================================
# Section J — Failure-mode scenarios
# ===========================================================================
print("\n--- J: Failure-mode scenarios ---")

_j_uns  = run_cli_surface(SCENARIO_BY_ID["unsupported_prompt"],   STANDARD_BOOTSTRAP)
_j_amb  = run_cli_surface(SCENARIO_BY_ID["ambiguous_player"],     AMBIGUOUS_BOOTSTRAP)
_j_nf   = run_cli_surface(SCENARIO_BY_ID["not_found_player"],     STANDARD_BOOTSTRAP)
_j_nss  = run_cli_surface(SCENARIO_BY_ID["no_session_follow_up"], STANDARD_BOOTSTRAP)

ok("J1 unsupported — supported=False",    _j_uns.get("supported") is False)
ok("J2 unsupported — outcome correct",    _j_uns.get("outcome") == "unsupported_intent")
ok("J3 unsupported — final_text non-empty", bool(_j_uns.get("final_text")))

ok("J4 ambiguous — supported=True",       _j_amb.get("supported") is True)
ok("J5 ambiguous — outcome correct",      _j_amb.get("outcome") == "ambiguous")
ok("J6 ambiguous — no captain metadata",  _j_amb.get("captain") is None)

ok("J7 not_found — supported=True",       _j_nf.get("supported") is True)
ok("J8 not_found — outcome correct",      _j_nf.get("outcome") == "not_found")
ok("J9 not_found — no captain metadata",  _j_nf.get("captain") is None)

ok("J10 no_session_follow_up — graceful not_found",
   _j_nss.get("outcome") == "not_found" and _j_nss.get("supported") is True)
ok("J11 no_session_follow_up — does not crash", True)  # reaching here is sufficient
ok("J12 no_session_follow_up — final_text non-empty", bool(_j_nss.get("final_text")))


# ===========================================================================
# Section K — Full validation runner
# ===========================================================================
print("\n--- K: Full validation runner ---")

_k_results = run_all_scenarios()

ok("K1 run_all_scenarios returns list",   isinstance(_k_results, list))
ok("K2 13 results",                        len(_k_results) == 13,
   str(len(_k_results)))
ok("K3 all results have 'pass' key",      all("pass" in r for r in _k_results))
ok("K4 all results have 'id' key",        all("id" in r for r in _k_results))
ok("K5 all 13 scenarios PASS",
   all(r["pass"] for r in _k_results),
   str([r["id"] for r in _k_results if not r["pass"]]))

# Spot-check direct_captain_score result
_k_cap = next(r for r in _k_results if r["id"] == "direct_captain_score")
ok("K6 direct_captain_score result correct",
   _k_cap["expected"]["intent"] == "captain_score" and _k_cap["pass"])
ok("K7 direct_captain_score has cli and http surface_results",
   "cli" in _k_cap["surface_results"] and "http" in _k_cap["surface_results"])

# Spot-check comparison_followup_llm result (session_cli only)
_k_comp_llm = next(r for r in _k_results if r["id"] == "comparison_followup_llm")
ok("K8 comparison_followup_llm passes",   _k_comp_llm["pass"],
   str(_k_comp_llm.get("failures")))
ok("K9 comparison_followup_llm has session_cli result",
   "session_cli" in _k_comp_llm["surface_results"])

# JSON artifact from the full run has pass_count == 13
_k_json_path = os.path.join(_tmp, "k_validation_results.json")
write_json_artifact(_k_results, _k_json_path)
with open(_k_json_path, encoding="utf-8") as _f:
    _k_json = json.load(_f)
ok("K10 JSON pass_count == 13",
   _k_json.get("pass_count") == 13, str(_k_json.get("pass_count")))
ok("K11 JSON fail_count == 0",
   _k_json.get("fail_count") == 0, str(_k_json.get("fail_count")))

# Write final artifacts to package dir
_final_json = os.path.join(_HERE, "validation_results.json")
_final_md   = os.path.join(_HERE, "validation_report.md")
write_json_artifact(_k_results, _final_json)
write_markdown_artifact(_k_results, _final_md)
ok("K12 final JSON artifact written",    os.path.isfile(_final_json))
ok("K13 final Markdown artifact written", os.path.isfile(_final_md))


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*60}")
print(f"Phase V1 results: {_passed}/{_passed+_failed} PASS")
print(f"{'='*60}")
if _failed:
    sys.exit(1)
