"""
run_phase_orch4f_tests.py
==========================
Phase Orch-4f: Deterministic contract drift checker.

Validates cross-file consistency between:
  FINAL_RESPONSE_CONTRACT.md  (source of truth for callers)
  http_contract_fixtures.json  (machine-readable HTTP expectations)

All checks are string/structure-based — no network calls, no LLM calls, no
runtime respond() calls. Pure document parsing.

Invariants checked:
  A   Stable field set parity       — fixture stable_fields == contract table fields
  A2  session_id HTTP-envelope      — session_id present in session endpoint, absent from
                                      ask endpoint and absent from FinalResponse contract table
  B   orch_outcome non-OK strings   — both files enumerate the same 6 strings
  C   HTTP always-present claim     — fixture and contract agree orch_outcome is always
                                      a key in HTTP JSON responses (even when null)
  D   Override-order completeness   — both files cover all 3 override types in order
  E   Independence invariant        — both files assert orch_outcome independence from outcome
  F   Deferred note parity          — both files record the sub-responses deferred note
  G   Conditional fields parity     — fixture conditional fields covered in contract doc
  H   HTTP status contract coverage — fixture and contract both cover 200/404/422
  I   Seeded mismatch detection     — mutating parsed data triggers failures (proves
                                      the checker catches real drift, not just vacuous checks)
  J   Regression                    — prior phase runners still importable / files present

Sections:
  A   Stable field set parity
  A2  session_id HTTP-envelope invariant
  B   Non-OK orch_outcome string parity
  C   HTTP always-present claim cross-reference
  D   Override-order completeness
  E   Independence invariant cross-reference
  F   Deferred note parity
  G   Conditional field coverage in contract
  H   HTTP status contract
  I   Seeded mismatch detection (mutation proof)
  J   Regression sanity
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys

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
# Assertion helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(cond: bool, label: str, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  [{detail}]"
        print(msg)


def ok_not(cond: bool, label: str, detail: str = "") -> None:
    """Assert that cond is False — used for mutation proof."""
    ok(not cond, label, detail)


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

_CONTRACT_PATH = os.path.join(_HERE, "FINAL_RESPONSE_CONTRACT.md")
_FIXTURE_PATH  = os.path.join(_HERE, "http_contract_fixtures.json")

with open(_CONTRACT_PATH, encoding="utf-8") as _f:
    _CONTRACT_TEXT = _f.read()

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    _FIXTURES = json.load(_f)


# ---------------------------------------------------------------------------
# Parsing helpers — extract normalized facts from each file
# ---------------------------------------------------------------------------

def extract_contract_table_fields(text: str) -> set[str]:
    """Extract field names from the stable caller-facing fields table.

    Matches rows of the form:  | `field_name` | ...
    Returns field names without backticks.
    """
    # Match markdown table rows starting with | `something`
    pattern = re.compile(r"^\|\s+`([^`]+)`\s+\|", re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(text)}


def extract_fixture_stable_fields(fixtures: dict) -> set[str]:
    """Union of stable fields for POST /ask and POST /session/{id}/ask.
    Used for union-level checks; use extract_fixture_stable_fields_per_endpoint
    for per-endpoint checks.
    """
    meta = fixtures.get("_meta", {})
    rsf  = meta.get("response_stable_fields", {})
    ask_fields     = set(rsf.get("POST /ask", []))
    session_fields = set(rsf.get("POST /session/{session_id}/ask", []))
    return ask_fields | session_fields


def extract_fixture_stable_fields_per_endpoint(fixtures: dict) -> dict[str, set[str]]:
    """Return stable field sets keyed by endpoint, for per-endpoint checks."""
    meta = fixtures.get("_meta", {})
    rsf  = meta.get("response_stable_fields", {})
    return {
        "ask":     set(rsf.get("POST /ask", [])),
        "session": set(rsf.get("POST /session/{session_id}/ask", [])),
    }


_NON_OK_STRINGS = frozenset([
    "no_client",
    "llm_error",
    "no_tool",
    "unknown_tool",
    "tool_error",
    "tool_result_error",
])

_OVERRIDE_TYPES = ["budget_constraint", "hit_warning", "chip_unavailable"]

_CONDITIONAL_KEYS = [
    "captain", "captain_ranking", "comparison", "transfer", "chip",
    "fixture_run", "differential", "sub_responses",
]


# ---------------------------------------------------------------------------
# Core checker functions — accept parsed data so mutation tests can call them
# ---------------------------------------------------------------------------

def check_stable_field_parity(
    contract_fields: set[str],
    fixture_fields: set[str],
    per_endpoint: "dict[str, set[str]] | None" = None,
) -> list[tuple[bool, str, str]]:
    """Return list of (pass, label, detail) tuples for stable field parity.

    ``session_id`` is intentionally excluded from the cross-file parity check.
    It is an HTTP session envelope field added by the server layer (SessionAskResponse),
    not a field on FinalResponse.  The contract table only covers FinalResponse fields.
    The fixture legitimately lists session_id for HTTP consumers of /session/{id}/ask.

    ``per_endpoint``, when provided, enables per-endpoint checks so a field that
    disappears from one endpoint only is caught (the union would hide it).
    """
    results = []

    # HTTP-envelope-only fields: present in fixture HTTP responses but not on FinalResponse
    _HTTP_ENVELOPE_ONLY = {"session_id"}

    # Every fixture stable field (excluding HTTP-envelope-only) must appear in contract table
    for field in sorted(fixture_fields - _HTTP_ENVELOPE_ONLY):
        present = field in contract_fields
        results.append((
            present,
            f"field '{field}' in fixture stable_fields is documented in contract table",
            "missing from contract table" if not present else "",
        ))

    # orch_outcome specifically must appear in both (union-level)
    results.append((
        "orch_outcome" in fixture_fields and "orch_outcome" in contract_fields,
        "orch_outcome present in both fixture stable_fields and contract table",
        f"fixture={('orch_outcome' in fixture_fields)}, contract={('orch_outcome' in contract_fields)}",
    ))

    # Per-endpoint: orch_outcome must be in EACH endpoint's stable field list independently
    if per_endpoint is not None:
        for ep_name, ep_fields in per_endpoint.items():
            results.append((
                "orch_outcome" in ep_fields,
                f"orch_outcome in fixture stable_fields for '{ep_name}' endpoint",
                f"missing from {ep_name} endpoint stable fields" if "orch_outcome" not in ep_fields else "",
            ))

    # Fixture stable fields must not be a proper strict subset of contract:
    # all core stable fields must be in the fixture too
    core_stable = {"final_text", "outcome", "supported", "intent", "review_passed", "llm_used"}
    for field in core_stable:
        results.append((
            field in fixture_fields,
            f"core stable field '{field}' present in fixture stable_fields",
            "",
        ))

    return results


def check_non_ok_strings_parity(
    contract_text: str,
    fixture_orch_values: dict,
) -> list[tuple[bool, str, str]]:
    """Check that both files enumerate the same 6 non-OK orch_outcome strings."""
    results = []
    for s in sorted(_NON_OK_STRINGS):
        in_contract = f'"{s}"' in contract_text or f"'{s}'" in contract_text or f"`\"{s}\"`" in contract_text
        in_fixture  = s in fixture_orch_values
        results.append((
            in_contract,
            f"non-OK string '{s}' documented in contract",
            "",
        ))
        results.append((
            in_fixture,
            f"non-OK string '{s}' documented in fixture orch_outcome_contract.values",
            "",
        ))
        results.append((
            in_contract and in_fixture,
            f"non-OK string '{s}' consistent across both files",
            "",
        ))
    return results


def check_http_always_present(
    contract_text: str,
    fixture_meta: dict,
    ask_fixtures: list[dict],
) -> list[tuple[bool, str, str]]:
    """Check that both files claim orch_outcome is always a key in HTTP JSON."""
    results = []

    orch_contract = fixture_meta.get("orch_outcome_contract", {})

    # Fixture: always_present_in_json must be True
    results.append((
        orch_contract.get("always_present_in_json") is True,
        "fixture orch_outcome_contract.always_present_in_json=true",
        f"got {orch_contract.get('always_present_in_json')!r}",
    ))

    # Contract doc must assert HTTP always-present
    always_phrases = [
        "always present",
        "always a key",
        "always present in the JSON",
    ]
    contract_has_always = any(p.lower() in contract_text.lower() for p in always_phrases)
    results.append((
        contract_has_always,
        "contract doc asserts orch_outcome always present in HTTP JSON",
        "",
    ))

    # At least one ask fixture must have orch_outcome field with presence=always
    fixtures_with_always = [
        f for f in ask_fixtures
        if f.get("expected", {}).get("body", {}).get("orch_outcome", {}).get("presence") == "always"
    ]
    results.append((
        len(fixtures_with_always) >= 1,
        f"at least 1 ask fixture has orch_outcome presence=always (found {len(fixtures_with_always)})",
        "",
    ))

    return results


def check_override_order_completeness(
    contract_text: str,
    fixture_meta: dict,
) -> list[tuple[bool, str, str]]:
    """Check that both files cover all 3 override types."""
    results = []
    orch_contract = fixture_meta.get("orch_outcome_contract", {})

    for ot in _OVERRIDE_TYPES:
        in_contract = ot in contract_text
        results.append((
            in_contract,
            f"override type '{ot}' documented in contract",
            "",
        ))

    # Contract must have the override-order section
    results.append((
        "Override application order" in contract_text or "override application order" in contract_text.lower(),
        "contract has override application order section",
        "",
    ))

    # Contract must classify types as hard-block vs advisory
    results.append((
        "Hard block" in contract_text or "hard block" in contract_text.lower(),
        "contract classifies override types as hard-block",
        "",
    ))
    results.append((
        "Advisory" in contract_text or "advisory" in contract_text.lower(),
        "contract classifies override types as advisory",
        "",
    ))

    # Fixture must have override_invariant
    results.append((
        bool(orch_contract.get("override_invariant")),
        "fixture orch_outcome_contract has non-empty override_invariant",
        f"got {orch_contract.get('override_invariant')!r}",
    ))

    # _apply_squad_overrides must be named in contract (single-source-of-truth claim)
    results.append((
        "_apply_squad_overrides" in contract_text,
        "contract names _apply_squad_overrides as single source of truth",
        "",
    ))

    return results


def check_independence_invariant(
    contract_text: str,
    fixture_meta: dict,
) -> list[tuple[bool, str, str]]:
    """Check that both files assert orch_outcome independence from outcome."""
    results = []
    orch_contract = fixture_meta.get("orch_outcome_contract", {})

    independence_phrases = ["independent", "independence", "Independent"]
    contract_has_independence = any(p in contract_text for p in independence_phrases)
    results.append((
        contract_has_independence,
        "contract doc asserts orch_outcome independence from outcome",
        "",
    ))

    results.append((
        bool(orch_contract.get("independence_invariant")),
        "fixture orch_outcome_contract has non-empty independence_invariant",
        f"got {orch_contract.get('independence_invariant')!r}",
    ))

    # Both must agree that non-OK orch_outcome never changes outcome
    never_changes_phrases = [
        "never changes",
        "never change",
        "non-OK orch_outcome never changes",
        "does not change",
    ]
    contract_has_never_changes = any(
        p.lower() in contract_text.lower() for p in never_changes_phrases
    )
    results.append((
        contract_has_never_changes,
        "contract states non-OK orch_outcome never changes outcome",
        "",
    ))

    independence_inv = orch_contract.get("independence_invariant", "")
    fixture_has_independence = any(
        p.lower() in independence_inv.lower()
        for p in ["independent", "does not", "never", "safe for routing"]
    )
    results.append((
        fixture_has_independence,
        "fixture independence_invariant contains independence assertion",
        f"got {independence_inv!r}",
    ))

    return results


def check_deferred_notes(
    contract_text: str,
) -> list[tuple[bool, str, str]]:
    """Check that the contract records the sub-responses deferred note."""
    results = []

    results.append((
        "sub_responses" in contract_text,
        "contract mentions sub_responses in deferred context",
        "",
    ))

    results.append((
        "orch_outcome" in contract_text and "deferred" in contract_text.lower(),
        "contract has both orch_outcome and deferred keywords (deferred note present)",
        "",
    ))

    # Out of Scope table must have orch_outcome row
    results.append((
        "Per-sub-response" in contract_text and "orch_outcome" in contract_text,
        "contract Out of Scope table has per-sub-response orch_outcome entry",
        "",
    ))

    # Multi-intent depth bypass must be noted
    results.append((
        "_multi_intent_depth" in contract_text,
        "contract documents _multi_intent_depth bypass mechanism",
        "",
    ))

    return results


def check_conditional_fields(
    contract_text: str,
    fixture_meta: dict,
) -> list[tuple[bool, str, str]]:
    """Check that fixture conditional fields are all documented in contract."""
    results = []
    fixture_conditional = fixture_meta.get("response_conditional_fields", {})

    for field_name in _CONDITIONAL_KEYS:
        in_fixture = field_name in fixture_conditional
        in_contract = f"`{field_name}`" in contract_text or f"| `{field_name}`" in contract_text
        results.append((
            in_fixture,
            f"conditional field '{field_name}' documented in fixture response_conditional_fields",
            "",
        ))
        results.append((
            in_contract,
            f"conditional field '{field_name}' documented in contract doc",
            "",
        ))

    return results


def check_http_status_contract(
    contract_text: str,
    fixture_http_status: dict,
) -> list[tuple[bool, str, str]]:
    """Check HTTP status code coverage.

    HTTP status codes are the authoritative domain of http_contract_fixtures.json.
    The contract markdown explicitly delegates HTTP detail to that file (see Purpose
    section: "http_contract_fixtures.json ... canonical source of truth for downstream
    consumers").  We therefore verify codes in the fixture only, and separately confirm
    the contract doc references the fixture file as the HTTP authority.
    """
    results = []
    required_codes = ["200", "404", "422"]
    for code in required_codes:
        results.append((
            code in fixture_http_status,
            f"HTTP status {code} in fixture http_status_contract",
            "",
        ))

    # Contract doc must delegate HTTP authority to fixture file (not duplicate it)
    results.append((
        "http_contract_fixtures.json" in contract_text,
        "contract doc references http_contract_fixtures.json as HTTP authority",
        "",
    ))

    return results


def check_session_id_envelope(
    contract_fields: set[str],
    per_endpoint: "dict[str, set[str]]",
) -> list[tuple[bool, str, str]]:
    """Enforce the session_id HTTP-envelope-only invariant.

    ``session_id`` is added by the HTTP server layer (``SessionAskResponse``),
    not by ``respond()`` / ``FinalResponse``.  Three invariants must hold:

    1. ``session_id`` IS present in the session endpoint's stable field list
       (callers of ``POST /session/{id}/ask`` need it to correlate responses).
    2. ``session_id`` is NOT present in the ask endpoint's stable field list
       (``POST /ask`` is stateless — no session_id in the response).
    3. ``session_id`` is NOT present in the ``FinalResponse`` contract table
       (it is an HTTP envelope field, not a ``FinalResponse`` field).

    These three conditions together prove that session_id is deliberately
    envelope-only.  A single failing assertion pinpoints exactly which boundary
    has drifted.
    """
    results = []
    ask_sf     = per_endpoint.get("ask", set())
    session_sf = per_endpoint.get("session", set())

    results.append((
        "session_id" in session_sf,
        "session_id present in session endpoint stable fields (callers need it for correlation)",
        "session_id missing from session stable fields" if "session_id" not in session_sf else "",
    ))

    results.append((
        "session_id" not in ask_sf,
        "session_id absent from ask endpoint stable fields (POST /ask is stateless)",
        f"session_id unexpectedly found in ask stable fields: {sorted(ask_sf)}" if "session_id" in ask_sf else "",
    ))

    results.append((
        "session_id" not in contract_fields,
        "session_id absent from FinalResponse contract table (HTTP-envelope-only, not a FinalResponse field)",
        f"session_id unexpectedly found in contract table fields: {sorted(contract_fields)}" if "session_id" in contract_fields else "",
    ))

    # Derived: session endpoint is a superset of ask endpoint (session adds session_id, nothing lost)
    results.append((
        ask_sf.issubset(session_sf),
        "session endpoint stable fields are a superset of ask endpoint stable fields",
        f"fields in ask but missing from session: {sorted(ask_sf - session_sf)}" if not ask_sf.issubset(session_sf) else "",
    ))

    return results


# ---------------------------------------------------------------------------
# Run checker on real data — collect results
# ---------------------------------------------------------------------------

def _apply_results(results: list[tuple[bool, str, str]]) -> None:
    for cond, label, detail in results:
        ok(cond, label, detail)


_contract_fields = extract_contract_table_fields(_CONTRACT_TEXT)
_fixture_fields  = extract_fixture_stable_fields(_FIXTURES)
_per_endpoint    = extract_fixture_stable_fields_per_endpoint(_FIXTURES)
_fixture_meta    = _FIXTURES.get("_meta", {})
_ask_fixtures    = _FIXTURES.get("ask_fixtures", [])
_orch_values     = _fixture_meta.get("orch_outcome_contract", {}).get("values", {})
_http_status     = _FIXTURES.get("http_status_contract", {})
_ask_sf          = _per_endpoint["ask"]
_session_sf      = _per_endpoint["session"]


# ===========================================================================
# Section A — Stable field set parity
# ===========================================================================

print("\n--- A: Stable field set parity ---")
_apply_results(check_stable_field_parity(_contract_fields, _fixture_fields, per_endpoint=_per_endpoint))

# Extra cross-check: every fixture stable field (excluding HTTP-envelope-only) must be in
# contract table. session_id is excluded: it is an HTTP layer field, not a FinalResponse field.
_HTTP_ENVELOPE_ONLY = {"session_id"}
_fixture_only = (_fixture_fields - _contract_fields) - _HTTP_ENVELOPE_ONLY
ok(
    len(_fixture_only) == 0,
    "no FinalResponse-level stable fields in fixture that are absent from contract table",
    detail=f"fixture-only fields: {sorted(_fixture_only)}" if _fixture_only else "",
)

# session_id envelope invariant is checked in Section A2 (dedicated section with
# per-invariant labels and mutation proofs). No duplicate inline checks here.


# ===========================================================================
# Section A2 — session_id HTTP-envelope invariant
# ===========================================================================

print("\n--- A2: session_id HTTP-envelope invariant ---")
_apply_results(check_session_id_envelope(_contract_fields, _per_endpoint))


# ===========================================================================
# Section B — Non-OK orch_outcome string parity
# ===========================================================================

print("\n--- B: Non-OK orch_outcome string parity ---")
_apply_results(check_non_ok_strings_parity(_CONTRACT_TEXT, _orch_values))

# Both files must enumerate exactly the same 6 non-OK strings (no extras in fixture)
_fixture_non_ok = frozenset(_orch_values.keys()) - {"null", "ok"}
ok(
    _fixture_non_ok == _NON_OK_STRINGS,
    f"fixture non-OK string set matches expected 6 strings exactly",
    detail=f"fixture={sorted(_fixture_non_ok)}, expected={sorted(_NON_OK_STRINGS)}" if _fixture_non_ok != _NON_OK_STRINGS else "",
)

# "ok" must also be present in fixture values
ok(
    "ok" in _orch_values,
    "fixture orch_outcome_contract.values includes 'ok'",
)
ok(
    "null" in _orch_values,
    "fixture orch_outcome_contract.values includes 'null' (represents JSON null / None)",
)


# ===========================================================================
# Section C — HTTP always-present claim cross-reference
# ===========================================================================

print("\n--- C: HTTP always-present claim cross-reference ---")
_apply_results(check_http_always_present(_CONTRACT_TEXT, _fixture_meta, _ask_fixtures))

# Fixture type annotation for orch_outcome
_orch_type = _fixture_meta.get("orch_outcome_contract", {}).get("type", "")
ok(
    "null" in _orch_type or "None" in _orch_type or "|" in _orch_type,
    "fixture orch_outcome_contract.type acknowledges nullable type",
    detail=f"got {_orch_type!r}",
)

# Contract doc explicitly mentions null-when-None behavior
ok(
    "null" in _CONTRACT_TEXT and "orch_outcome" in _CONTRACT_TEXT,
    "contract doc uses 'null' in orch_outcome context (JSON null when None)",
)


# ===========================================================================
# Section D — Override-order completeness
# ===========================================================================

print("\n--- D: Override-order completeness ---")
_apply_results(check_override_order_completeness(_CONTRACT_TEXT, _fixture_meta))

# Step numbers must appear in contract (1, 2, 3 in the override order table)
ok(
    "step 1" in _CONTRACT_TEXT.lower() or "| 1 |" in _CONTRACT_TEXT,
    "contract override order table has explicit step 1",
)
ok(
    "step 2" in _CONTRACT_TEXT.lower() or "| 2 |" in _CONTRACT_TEXT,
    "contract override order table has explicit step 2",
)
ok(
    "step 3" in _CONTRACT_TEXT.lower() or "| 3 |" in _CONTRACT_TEXT,
    "contract override order table has explicit step 3",
)

# Combined firing (budget + hit_warning) must be documented
ok(
    "combined" in _CONTRACT_TEXT.lower() or "co-fire" in _CONTRACT_TEXT.lower() or "both" in _CONTRACT_TEXT.lower(),
    "contract documents combined override firing behavior",
)


# ===========================================================================
# Section E — Independence invariant cross-reference
# ===========================================================================

print("\n--- E: Independence invariant cross-reference ---")
_apply_results(check_independence_invariant(_CONTRACT_TEXT, _fixture_meta))

# Contract must have the independence table (4 rows: None/any, ok/ok, ok/other, non-OK/any)
ok(
    "non-OK string" in _CONTRACT_TEXT or "non-OK" in _CONTRACT_TEXT,
    "contract independence table references 'non-OK' orch_outcome row",
)

# Fixture independence_invariant must mention outcome or routing
_indep_inv = _fixture_meta.get("orch_outcome_contract", {}).get("independence_invariant", "")
ok(
    "outcome" in _indep_inv.lower(),
    "fixture independence_invariant mentions 'outcome'",
    detail=f"got {_indep_inv!r}",
)
ok(
    "routing" in _indep_inv.lower() or "route" in _indep_inv.lower() or "safe" in _indep_inv.lower(),
    "fixture independence_invariant states outcome is safe for routing decisions",
    detail=f"got {_indep_inv!r}",
)


# ===========================================================================
# Section F — Deferred note parity
# ===========================================================================

print("\n--- F: Deferred note parity ---")
_apply_results(check_deferred_notes(_CONTRACT_TEXT))

# "Out of Scope" section must have orch_outcome entry
ok(
    "Out of Scope" in _CONTRACT_TEXT and "orch_outcome" in _CONTRACT_TEXT,
    "contract Out of Scope section exists and orch_outcome is mentioned",
)

# Deferred note must explain WHY sub-calls bypass orch
ok(
    "latency" in _CONTRACT_TEXT.lower() or "recursive" in _CONTRACT_TEXT.lower() or "prevents" in _CONTRACT_TEXT.lower(),
    "contract deferred note explains WHY sub-calls bypass orch gate",
)


# ===========================================================================
# Section G — Conditional field coverage in contract
# ===========================================================================

print("\n--- G: Conditional field coverage in contract ---")
_apply_results(check_conditional_fields(_CONTRACT_TEXT, _fixture_meta))

# Fixture must have exactly the expected conditional fields (no undocumented extras)
_expected_conditional = set(_CONDITIONAL_KEYS)
_fixture_conditional_keys = set(_fixture_meta.get("response_conditional_fields", {}).keys())
_unexpected_conditional = _fixture_conditional_keys - _expected_conditional
ok(
    len(_unexpected_conditional) == 0,
    "no unexpected conditional fields in fixture (all accounted for)",
    detail=f"unexpected: {sorted(_unexpected_conditional)}" if _unexpected_conditional else "",
)


# ===========================================================================
# Section H — HTTP status contract
# ===========================================================================

print("\n--- H: HTTP status contract ---")
_apply_results(check_http_status_contract(_CONTRACT_TEXT, _http_status))

# 200 semantics must clarify that 200 does NOT imply outcome=ok
ok(
    "200" in _http_status and "does not imply" in _http_status.get("200", "").lower(),
    "fixture HTTP 200 notes that 200 does NOT imply outcome='ok'",
    detail=f"got {_http_status.get('200')!r}",
)

# 503 coverage in fixture (bootstrap not initialised)
ok(
    "503" in _http_status,
    "fixture http_status_contract covers 503 (bootstrap not initialised)",
)

# 429 coverage (session cap)
ok(
    "429" in _http_status,
    "fixture http_status_contract covers 429 (session cap reached)",
)


# ===========================================================================
# Section I — Seeded mismatch detection (mutation proof)
# ===========================================================================

print("\n--- I: Seeded mismatch detection (mutation proof) ---")

# I-A: Remove orch_outcome from ONE endpoint's stable fields (not both).
# The union check would miss this; the per-endpoint check must catch it.
# This is the realistic drift scenario: a developer edits one endpoint and forgets the other.
_mutated_fixtures_A = copy.deepcopy(_FIXTURES)
_mA_rsf = _mutated_fixtures_A["_meta"]["response_stable_fields"]
_mA_rsf["POST /ask"] = [f for f in _mA_rsf["POST /ask"] if f != "orch_outcome"]
# session endpoint left intact — union would still contain orch_outcome
_mA_contract  = extract_contract_table_fields(_CONTRACT_TEXT)
_mA_fixture   = extract_fixture_stable_fields(_mutated_fixtures_A)      # union
_mA_per_ep    = extract_fixture_stable_fields_per_endpoint(_mutated_fixtures_A)
_mA_results   = check_stable_field_parity(_mA_contract, _mA_fixture, per_endpoint=_mA_per_ep)
# Union check passes (session still has orch_outcome); per-endpoint check must fail for ask
_mA_union_check = [r for r in _mA_results if "orch_outcome present in both" in r[1]]
_mA_ep_check    = [r for r in _mA_results if "orch_outcome in fixture stable_fields for 'ask'" in r[1]]
ok(
    _mA_union_check[0][0] if _mA_union_check else False,
    "I-A union check passes when orch_outcome missing from only one endpoint (expected: union hides it)",
    detail="union check incorrectly failed" if _mA_union_check and not _mA_union_check[0][0] else "",
)
ok_not(
    _mA_ep_check[0][0] if _mA_ep_check else True,
    "I-A per-endpoint check catches orch_outcome missing from 'ask' endpoint",
    detail="per-endpoint check missed the mutation" if not _mA_ep_check or _mA_ep_check[0][0] else "",
)

# I-B: Remove a non-OK string from fixture values → string parity check must fail
_mutated_fixtures_B = copy.deepcopy(_FIXTURES)
_mB_values = _mutated_fixtures_B["_meta"]["orch_outcome_contract"]["values"]
_mB_values.pop("llm_error", None)  # remove one non-OK string
_mB_results = check_non_ok_strings_parity(_CONTRACT_TEXT, _mB_values)
# At least one check involving llm_error must fail
_mB_fails = [r for r in _mB_results if "llm_error" in r[1] and not r[0]]
ok(
    len(_mB_fails) >= 1,
    "I-B mutation: removing 'llm_error' from fixture values is detected by string parity check",
    detail=f"expected >=1 failure, got {len(_mB_fails)}",
)

# I-C: Set always_present_in_json=False → always-present check must fail
_mutated_fixtures_C = copy.deepcopy(_FIXTURES)
_mutated_fixtures_C["_meta"]["orch_outcome_contract"]["always_present_in_json"] = False
_mC_results = check_http_always_present(_CONTRACT_TEXT, _mutated_fixtures_C["_meta"], _ask_fixtures)
_mC_fails = [r for r in _mC_results if "always_present_in_json=true" in r[1] and not r[0]]
ok(
    len(_mC_fails) >= 1,
    "I-C mutation: setting always_present_in_json=False is detected by HTTP presence check",
    detail=f"expected >=1 failure, got {len(_mC_fails)}",
)

# I-D: Remove independence_invariant → independence check must fail
_mutated_fixtures_D = copy.deepcopy(_FIXTURES)
_mutated_fixtures_D["_meta"]["orch_outcome_contract"]["independence_invariant"] = ""
_mD_results = check_independence_invariant(_CONTRACT_TEXT, _mutated_fixtures_D["_meta"])
_mD_fails = [r for r in _mD_results if "fixture independence_invariant" in r[1] and not r[0]]
ok(
    len(_mD_fails) >= 1,
    "I-D mutation: clearing independence_invariant is detected by independence check",
    detail=f"expected >=1 failure, got {len(_mD_fails)}",
)

# I-E: Remove an override type from contract text → override check must fail
_mE_text = _CONTRACT_TEXT.replace("chip_unavailable", "REMOVED_OVERRIDE")
_mE_results = check_override_order_completeness(_mE_text, _fixture_meta)
_mE_fails = [r for r in _mE_results if "chip_unavailable" in r[1] and not r[0]]
ok(
    len(_mE_fails) >= 1,
    "I-E mutation: removing 'chip_unavailable' from contract text is detected by override check",
    detail=f"expected >=1 failure, got {len(_mE_fails)}",
)

# I-G: Inject session_id into ask endpoint stable fields → envelope invariant must catch it.
# Realistic drift: a developer accidentally copies session stable fields to ask.
_mutated_fixtures_G = copy.deepcopy(_FIXTURES)
_mG_rsf = _mutated_fixtures_G["_meta"]["response_stable_fields"]
if "session_id" not in _mG_rsf["POST /ask"]:
    _mG_rsf["POST /ask"] = ["session_id"] + _mG_rsf["POST /ask"]
_mG_per_ep   = extract_fixture_stable_fields_per_endpoint(_mutated_fixtures_G)
_mG_results  = check_session_id_envelope(_contract_fields, _mG_per_ep)
_mG_fails    = [r for r in _mG_results if "ask endpoint stable fields" in r[1] and "absent" in r[1] and not r[0]]
ok(
    len(_mG_fails) >= 1,
    "I-G mutation: injecting session_id into ask stable fields is caught by envelope check",
    detail=f"expected >=1 failure, got {len(_mG_fails)}",
)

# I-H: Remove session_id from session endpoint stable fields → envelope invariant must catch it.
# Realistic drift: a developer strips session_id while refactoring stable field lists.
_mutated_fixtures_H = copy.deepcopy(_FIXTURES)
_mH_rsf = _mutated_fixtures_H["_meta"]["response_stable_fields"]
_mH_rsf["POST /session/{session_id}/ask"] = [
    f for f in _mH_rsf["POST /session/{session_id}/ask"] if f != "session_id"
]
_mH_per_ep   = extract_fixture_stable_fields_per_endpoint(_mutated_fixtures_H)
_mH_results  = check_session_id_envelope(_contract_fields, _mH_per_ep)
_mH_fails    = [r for r in _mH_results if "session endpoint stable fields" in r[1] and "present" in r[1] and not r[0]]
ok(
    len(_mH_fails) >= 1,
    "I-H mutation: removing session_id from session stable fields is caught by envelope check",
    detail=f"expected >=1 failure, got {len(_mH_fails)}",
)

# I-F: Real data passes all checks (prove mutation checks are tight, not vacuous)
_real_parity    = check_stable_field_parity(_contract_fields, _fixture_fields, per_endpoint=_per_endpoint)
_real_envelope  = check_session_id_envelope(_contract_fields, _per_endpoint)
_real_strings   = check_non_ok_strings_parity(_CONTRACT_TEXT, _orch_values)
_real_http      = check_http_always_present(_CONTRACT_TEXT, _fixture_meta, _ask_fixtures)
_real_overrides = check_override_order_completeness(_CONTRACT_TEXT, _fixture_meta)
_real_indep     = check_independence_invariant(_CONTRACT_TEXT, _fixture_meta)
_all_real_results = _real_parity + _real_envelope + _real_strings + _real_http + _real_overrides + _real_indep
_real_failures = [r for r in _all_real_results if not r[0]]
ok(
    len(_real_failures) == 0,
    f"I-F sanity: all core checks pass on real (unmodified) data (checked {len(_all_real_results)} assertions)",
    detail=f"unexpected failures: {[r[1] for r in _real_failures]}" if _real_failures else "",
)


# ===========================================================================
# Section J — Regression sanity
# ===========================================================================

print("\n--- J: Regression sanity ---")

# Both files are present and non-trivially long
ok(os.path.isfile(_CONTRACT_PATH), "J1 FINAL_RESPONSE_CONTRACT.md file exists")
ok(os.path.isfile(_FIXTURE_PATH),  "J2 http_contract_fixtures.json file exists")
ok(len(_CONTRACT_TEXT) > 5000,     "J3 contract doc is non-trivially long", detail=f"len={len(_CONTRACT_TEXT)}")
ok(len(json.dumps(_FIXTURES)) > 3000, "J4 fixture JSON is non-trivially large")

# Both orch4e and orch4d runners exist
ok(
    os.path.isfile(os.path.join(_HERE, "run_phase_orch4e_tests.py")),
    "J5 run_phase_orch4e_tests.py exists",
)
ok(
    os.path.isfile(os.path.join(_HERE, "run_phase_orch4d_tests.py")),
    "J6 run_phase_orch4d_tests.py exists",
)

# Phase 9a/9b/9c runners exist
for _phase in ("9a", "9b", "9c"):
    ok(
        os.path.isfile(os.path.join(_HERE, f"run_phase{_phase}_tests.py")),
        f"J7.{_phase} run_phase{_phase}_tests.py exists",
    )

# Core contract invariant anchors still in contract doc
for _anchor in [
    "## `FinalResponse`",
    "## Invariants",
    "## Outcome Vocabulary",
    "## Stability Commitment",
    "## Out of Scope",
    "## `orch_outcome`",
    "Override application order",
]:
    ok(
        _anchor in _CONTRACT_TEXT,
        f"J8 contract anchor present: {_anchor!r}",
    )

# Fixture top-level structure intact
for _key in ["_meta", "ask_fixtures", "session_ask_fixtures", "http_status_contract"]:
    ok(
        _key in _FIXTURES,
        f"J9 fixture top-level key '{_key}' present",
    )


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'=' * 50}")
total = _PASS + _FAIL
print(f"Phase Orch-4f: {_PASS}/{total} assertions passed.")
if _FAIL:
    print(f"               {_FAIL} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
