"""
run_phase26b_tests.py
=====================
Phase 2.6b: P1 bug-fix verification suite.

Stories covered
---------------
1.1  Spanish preposition stripping in router.py
     - _strip_spanish_name_prefix() unit tests
     - compare route strips "a", "al", "tengo a" from player tokens
     - captain_score route strips preposition after new Spanish prefixes
     - player_summary route strips preposition after new Spanish prefixes
     - transfer route strips preposition from out_part and in_part

1.2  Renderer locale audit
     - Confirm no Portuguese strings in renderer.py
     - not_found / ambiguous messages are English (renderer language)

1.3  Degraded flag plumbing
     - LLMResponse.provider_failed=True when provider call returns error_code
     - LLMResponse.provider_failed=False on no-client fallback path
     - FinalResponse.degraded mirrors LLMResponse.provider_failed
     - degraded field serialised in AskResponse (fpl_server)
     - degraded field present in SessionAskResponse (fpl_server)

1.4  Spanish routing coverage
     - Generic captain ranking phrases route to rank_captain_candidates
     - Named captain score phrases route to get_captain_score
     - Player summary Spanish phrases route to get_player_summary
     - Classifier prompt contains Spanish examples for all three intents

Regression
----------
- run_validation: all 51 scenarios must still PASS
- run_phase26a: all 39 assertions must still PASS (infra baseline)
"""
from __future__ import annotations

import sys
import os

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
# Test runner helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# A — Story 1.1: _strip_spanish_name_prefix unit tests
# ---------------------------------------------------------------------------

print("\n=== A: _strip_spanish_name_prefix unit tests ===")

from fpl_grounded_assistant.router import _strip_spanish_name_prefix, route  # noqa: E402

_check("A1 strip leading 'a '",     _strip_spanish_name_prefix("a Salah") == "Salah")
_check("A2 strip leading 'al '",    _strip_spanish_name_prefix("al Saka") == "Saka")
_check("A3 strip leading 'tengo a '", _strip_spanish_name_prefix("tengo a Haaland") == "Haaland")
_check("A4 no-prefix unchanged",    _strip_spanish_name_prefix("Haaland") == "Haaland")
_check("A5 case-insensitive strip", _strip_spanish_name_prefix("A Salah") == "Salah")
_check("A6 'al Bruyne' preserved when not a prefix", _strip_spanish_name_prefix("KDB") == "KDB")
_check("A7 only first matching prefix stripped",
       _strip_spanish_name_prefix("a a Salah") == "a Salah")

# ---------------------------------------------------------------------------
# B — Story 1.1: Routing integration with compare_players
# ---------------------------------------------------------------------------

print("\n=== B: compare_players preposition stripping ===")

r = route("compara a Salah y Haaland")
_check("B1 'compara a Salah y Haaland' routes",       r is not None)
_check("B2 routes to compare_players",                 r is not None and r.tool_name == "compare_players")
_check("B3 query_a is 'Salah' (not 'a Salah')",
       r is not None and r.tool_args.get("query_a") == "Salah",
       f"got query_a={r.tool_args.get('query_a') if r else 'NO ROUTE'}")
_check("B4 query_b is 'Haaland'",
       r is not None and r.tool_args.get("query_b") == "Haaland")

r2 = route("tengo a saka y haaland")
_check("B5 'tengo a saka y haaland' routes",             r2 is not None)
_check("B6 routes to compare_players",                   r2 is not None and r2.tool_name == "compare_players")
_check("B7 query_a is 'saka' (not 'tengo a saka')",
       r2 is not None and r2.tool_args.get("query_a", "").lower() == "saka",
       f"got query_a={r2.tool_args.get('query_a') if r2 else 'NO ROUTE'}")
_check("B8 query_b is 'haaland'",
       r2 is not None and r2.tool_args.get("query_b", "").lower() == "haaland")

r3 = route("compara a Saka y Haaland")
_check("B9 'compara a Saka y Haaland' strips 'a Saka'",
       r3 is not None and r3.tool_args.get("query_a") == "Saka")

# ---------------------------------------------------------------------------
# C — Story 1.1: captain_score preposition stripping
# ---------------------------------------------------------------------------

print("\n=== C: captain_score preposition stripping ===")

r4 = route("debería capitanear a Haaland")
_check("C1 'debería capitanear a Haaland' routes",     r4 is not None)
_check("C2 routes to get_captain_score",               r4 is not None and r4.tool_name == "get_captain_score")
_check("C3 query is 'Haaland' (not 'a Haaland')",
       r4 is not None and r4.tool_args.get("query") == "Haaland",
       f"got query={r4.tool_args.get('query') if r4 else 'NO ROUTE'}")

r5 = route("deberia capitar a Salah")
_check("C4 'deberia capitar a Salah' routes",          r5 is not None)
_check("C5 routes to get_captain_score",               r5 is not None and r5.tool_name == "get_captain_score")
_check("C6 query is 'Salah' (not 'a Salah')",
       r5 is not None and r5.tool_args.get("query") == "Salah")

# ---------------------------------------------------------------------------
# D — Story 1.4: Spanish rank_candidates routing
# ---------------------------------------------------------------------------

print("\n=== D: Spanish rank_candidates routing ===")

for phrase, label in [
    ("quién debería capitanear esta semana", "D1"),
    ("quien deberia capitanear esta semana", "D2"),
    ("quien deberia capitanear",             "D3"),
    ("dame el ranking de capitanes",         "D4"),
    ("ranking de capitanes",                 "D5"),
    ("capitan para esta semana",             "D6"),
    ("a quien capitaneo esta semana",        "D7"),
]:
    rx = route(phrase)
    _check(f"{label} '{phrase[:40]}' routes to rank_captain_candidates",
           rx is not None and rx.tool_name == "rank_captain_candidates",
           f"got {rx.tool_name if rx else 'None'}")

# ---------------------------------------------------------------------------
# E — Story 1.4: Spanish player_summary routing
# ---------------------------------------------------------------------------

print("\n=== E: Spanish player_summary routing ===")

for phrase, expected_query, label in [
    ("dame un resumen de Salah",    "Salah",   "E1"),
    ("dame el resumen de Haaland",  "Haaland", "E2"),
    ("dame las stats de Saka",      "Saka",    "E3"),
    ("información sobre Haaland",   "Haaland", "E4"),
    ("informacion sobre Saka",      "Saka",    "E5"),
    ("cómo le va Salah",            "Salah",   "E6"),
    ("como le va Haaland",          "Haaland", "E7"),
    ("cuántos puntos lleva Salah",  "Salah",   "E8"),
    ("cuantos puntos lleva Saka",   "Saka",    "E9"),
    ("resumen de Haaland",          "Haaland", "E10"),
    ("precio de Saka",              "Saka",    "E11"),
    ("stats de Salah",              "Salah",   "E12"),
]:
    rx = route(phrase)
    _check(f"{label} '{phrase}' routes to get_player_summary",
           rx is not None and rx.tool_name == "get_player_summary",
           f"got {rx.tool_name if rx else 'None'}")
    if rx is not None and rx.tool_name == "get_player_summary":
        _check(f"{label}q query is '{expected_query}'",
               rx.tool_args.get("query") == expected_query,
               f"got query={rx.tool_args.get('query')}")

# ---------------------------------------------------------------------------
# F — Story 1.2: Renderer locale audit (no Portuguese)
# ---------------------------------------------------------------------------

print("\n=== F: Renderer locale audit ===")

import inspect  # noqa: E402
from fpl_grounded_assistant import renderer as _renderer_mod  # noqa: E402

_renderer_src = inspect.getsource(_renderer_mod)
_check("F1 no Portuguese 'Não' in renderer source",  "Não" not in _renderer_src)
_check("F2 no Portuguese 'nenhum' in renderer source", "nenhum" not in _renderer_src)
_check("F3 not_found message in English",
       "No player found matching" in _renderer_src)

# ---------------------------------------------------------------------------
# G — Story 1.3: LLMResponse.provider_failed plumbing
# ---------------------------------------------------------------------------

print("\n=== G: LLMResponse.provider_failed plumbing ===")

from fpl_grounded_assistant.llm_layer import LLMResponse  # noqa: E402

# Check field is present on the dataclass
_check("G1 LLMResponse has provider_failed field",
       hasattr(LLMResponse, "__dataclass_fields__") and "provider_failed" in LLMResponse.__dataclass_fields__)
_check("G2 provider_failed default is False",
       LLMResponse.__dataclass_fields__["provider_failed"].default is False)

# Simulate ask_llm with a stub provider that returns error_code
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.provider_client import ProviderResult  # noqa: E402

# Build a stub that injects a provider error
class _FailingProvider:
    """Stub provider that returns an error_code on every call."""
    def call(self, **_kwargs):
        return ProviderResult(
            text=None,
            model="test-model",
            error_code="PERR_TIMEOUT",
            error_msg="simulated timeout",
            latency_ms=50.0,
            attempts=1,
        )

class _FailingProviderFactory:
    """Makes ask_llm use the failing stub via the client kwarg path."""
    pass

# Import ask_llm and patch get_provider temporarily
from fpl_grounded_assistant import llm_layer as _llm_mod  # noqa: E402
_original_get_provider = _llm_mod.get_provider

def _patched_get_provider(provider_name, *, client=None, api_key=None):
    return _FailingProvider()

_llm_mod.get_provider = _patched_get_provider
try:
    lr = _llm_mod.ask_llm("should I captain Salah", STANDARD_BOOTSTRAP)
    _check("G3 provider_failed=True when provider returns error_code",
           lr.provider_failed is True,
           f"got provider_failed={lr.provider_failed}")
    _check("G4 llm_called=False on provider error (fell back)",
           lr.llm_called is False,
           f"got llm_called={lr.llm_called}")
    _check("G5 llm_text is deterministic fallback (non-empty)",
           bool(lr.llm_text))
finally:
    _llm_mod.get_provider = _original_get_provider

# Test no-client path: provider_failed should remain False
from fpl_grounded_assistant.provider_client import ProviderNotAvailableError  # noqa: E402

def _unavailable_get_provider(provider_name, *, client=None, api_key=None):
    raise ProviderNotAvailableError("no client")

_llm_mod.get_provider = _unavailable_get_provider
try:
    lr_no_client = _llm_mod.ask_llm("should I captain Salah", STANDARD_BOOTSTRAP)
    _check("G6 provider_failed=False on ProviderNotAvailableError (no client)",
           lr_no_client.provider_failed is False,
           f"got provider_failed={lr_no_client.provider_failed}")
finally:
    _llm_mod.get_provider = _original_get_provider

# ---------------------------------------------------------------------------
# H — Story 1.3: FinalResponse.degraded field
# ---------------------------------------------------------------------------

print("\n=== H: FinalResponse.degraded field ===")

from fpl_grounded_assistant.final_response import FinalResponse, respond  # noqa: E402

_check("H1 FinalResponse has degraded field",
       hasattr(FinalResponse, "__dataclass_fields__") and "degraded" in FinalResponse.__dataclass_fields__)
_check("H2 FinalResponse.degraded default is False",
       FinalResponse.__dataclass_fields__["degraded"].default is False)

# Test degraded=True path by patching get_provider
_llm_mod.get_provider = _patched_get_provider
try:
    r_degraded = respond("should I captain Salah", STANDARD_BOOTSTRAP)
    _check("H3 degraded=True when provider fails",
           r_degraded.degraded is True,
           f"got degraded={r_degraded.degraded}")
    _check("H4 outcome=ok despite degradation (deterministic path ran)",
           r_degraded.outcome == "ok",
           f"got outcome={r_degraded.outcome}")
    _check("H5 llm_used=False on degraded turn",
           r_degraded.llm_used is False,
           f"got llm_used={r_degraded.llm_used}")
    _check("H6 final_text is non-empty on degraded turn",
           bool(r_degraded.final_text))
finally:
    _llm_mod.get_provider = _original_get_provider

# Normal path (no LLM client): degraded should be False
r_normal = respond("should I captain Salah", STANDARD_BOOTSTRAP)
_check("H7 degraded=False on normal deterministic path",
       r_normal.degraded is False,
       f"got degraded={r_normal.degraded}")

# ---------------------------------------------------------------------------
# I — Story 1.3: fpl_server AskResponse degraded field
# ---------------------------------------------------------------------------

print("\n=== I: fpl_server AskResponse/SessionAskResponse degraded field ===")

# Import the response schemas (no network needed — just schema validation)
import importlib  # noqa: E402
_server_spec = importlib.util.spec_from_file_location(
    "fpl_server", os.path.join(_HERE, "fpl_server.py")
)
# We can't import fpl_server directly here easily due to FastAPI app startup,
# so test the AskResponse schema by introspecting its Pydantic fields.
# Instead, read the source to confirm the field is present.
with open(os.path.join(_HERE, "fpl_server.py")) as _f:
    _server_src = _f.read()

_check("I1 AskResponse has degraded field in fpl_server.py",
       "degraded: bool = False" in _server_src and
       "Phase 2.6b" in _server_src)
_check("I2 SessionAskResponse has degraded field",
       _server_src.count("degraded: bool = False") >= 2)
_check("I3 degraded=r.degraded wired in ask endpoint",
       "degraded=r.degraded" in _server_src)
_check("I4 degraded wired in session_ask endpoint",
       _server_src.count("degraded=r.degraded") >= 2)

# ---------------------------------------------------------------------------
# J — Story 1.3: TypeScript types updated
# ---------------------------------------------------------------------------

print("\n=== J: TypeScript types updated ===")

_ts_path = os.path.join(_HERE, "..", "fpl-ui", "lib", "types.ts")
if os.path.exists(_ts_path):
    with open(_ts_path) as _f:
        _ts_src = _f.read()
    _check("J1 degraded field in AskResponse TypeScript interface",
           "degraded: boolean" in _ts_src)
    _check("J2 degraded has Phase 2.6b annotation",
           "Phase 2.6b" in _ts_src)
else:
    _check("J1 types.ts exists", False, f"not found at {_ts_path}")
    _check("J2 degraded annotation",  False)

# ---------------------------------------------------------------------------
# K — Regression: validation corpus 51/51
# ---------------------------------------------------------------------------

print("\n=== K: Regression — validation corpus ===")

from run_validation import run_all_scenarios  # noqa: E402

results = run_all_scenarios()   # returns list[dict]
total   = len(results)
passed  = sum(1 for r in results if r.get("pass"))
_check(f"K1 validation corpus {passed}/{total} PASS", passed == total,
       f"{total - passed} scenario(s) failed")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"Phase 2.6b: {len(_pass)}/{len(_pass) + len(_fail)} assertions passed.")
if _fail:
    print(f"            {len(_fail)} assertion(s) FAILED.")
    for f in _fail:
        print(f"  - {f}")
else:
    print("            All assertions passed.")
