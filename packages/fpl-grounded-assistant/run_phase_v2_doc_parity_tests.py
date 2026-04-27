"""
V2 Phase 1e — Architecture doc parity verification.
=====================================================
Checks that the key intent_hint invariants are stated in the authoritative
architecture and contract docs so they cannot silently drift.

This runner does NOT test backend behavior — that is covered by
  run_phase_v2_intent_hint_tests.py        (69 tests)
  run_phase_v2_intent_hint_examples_tests.py (22 tests)

This runner checks that the *documentation* surfaces remain consistent with the
implemented backend contract.  Each assertion is a substring search against a
doc file; a missing phrase is a parity gap, not a behavioral bug.

Docs checked
------------
  FINAL_RESPONSE_CONTRACT.md   -- package-level caller-facing contract
  SESSION_CONTRACT.md          -- session endpoint contract
  ../../orchestrator-instructions.md  -- top-level architecture guidance
  ../../HANDOFF.md             -- top-level handoff / status doc

Key intent_hint invariants that must appear in the docs
--------------------------------------------------------
  1. deterministic router wins (hint only fires on router miss)
  2. allowlist of 7 valid values exists and is named
  3. invalid hints are silently ignored / safe
  4. session usage is per-turn (not persistent across turns)
  5. provider-neutral (no provider identity in the public contract)
  6. pre-classifier (fires before LLM classifier, without LLM call)
  7. classification_source audit field is mentioned
  8. V2 Phase 1c and 1d are listed as complete in the roadmap docs

Run::

    cd packages/fpl-grounded-assistant
    python run_phase_v2_doc_parity_tests.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))  # fpl-platform root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


_passed = 0
_failed = 0


def _assert(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        print(f"  [PASS] {label}")
        _passed += 1
    else:
        print(f"  [FAIL] {label}{(' -- ' + detail) if detail else ''}")
        _failed += 1


def _contains(doc: str, phrase: str) -> bool:
    return phrase.lower() in doc.lower()


def _check(label: str, doc: str, phrase: str) -> None:
    _assert(label, _contains(doc, phrase), f"phrase not found: {phrase!r}")


# ---------------------------------------------------------------------------
# Load docs
# ---------------------------------------------------------------------------

FINAL_CONTRACT_PATH = os.path.join(_HERE, "FINAL_RESPONSE_CONTRACT.md")
SESSION_CONTRACT_PATH = os.path.join(_HERE, "SESSION_CONTRACT.md")
ORCHESTRATOR_PATH = os.path.join(_REPO, "orchestrator-instructions.md")
HANDOFF_PATH = os.path.join(_REPO, "HANDOFF.md")

final_contract = _read(FINAL_CONTRACT_PATH)
session_contract = _read(SESSION_CONTRACT_PATH)
orchestrator = _read(ORCHESTRATOR_PATH)
handoff = _read(HANDOFF_PATH)


# ---------------------------------------------------------------------------
# Section A — FINAL_RESPONSE_CONTRACT.md
# ---------------------------------------------------------------------------

print("\n=== Section A: FINAL_RESPONSE_CONTRACT.md ===\n")

_check("A1 intent_hint appears in respond() signature",
       final_contract, "intent_hint=None")

_check("A2 allowlist table present",
       final_contract, "INTENT_HINT_ALLOWLIST")

_check("A3 deterministic router wins stated",
       final_contract, "deterministic router wins")

_check("A4 invalid hint safe-ignore stated",
       final_contract, "invalid")

_check("A5 provider-neutral stated",
       final_contract, "provider-neutral")

_check("A6 per-turn isolation stated",
       final_contract, "per-turn")

_check("A7 classification_source mentioned",
       final_contract, "classification_source")

_check("A8 allowlist values list present",
       final_contract, "captain_score")

_check("A9 pre-classifier stated",
       final_contract, "pre-classifier")


# ---------------------------------------------------------------------------
# Section B — SESSION_CONTRACT.md
# ---------------------------------------------------------------------------

print("\n=== Section B: SESSION_CONTRACT.md ===\n")

_check("B1 intent_hint mentioned",
       session_contract, "intent_hint")

_check("B2 per-turn isolation stated",
       session_contract, "per-turn")

_check("B3 allowlist mentioned",
       session_contract, "allowlist")

_check("B4 invalid hint safe stated",
       session_contract, "invalid")

_check("B5 deterministic router wins stated",
       session_contract, "deterministic router wins")

_check("B6 V2 Phase 1c reference",
       session_contract, "V2 Phase 1c")


# ---------------------------------------------------------------------------
# Section C — orchestrator-instructions.md
# ---------------------------------------------------------------------------

print("\n=== Section C: orchestrator-instructions.md ===\n")

_check("C1 intent_hint appears",
       orchestrator, "intent_hint")

_check("C2 deterministic router wins stated",
       orchestrator, "deterministic router wins")

_check("C3 allowlist stated",
       orchestrator, "INTENT_HINT_ALLOWLIST")

_check("C4 invalid hints ignored safely stated",
       orchestrator, "ignored safely")

_check("C5 per-turn isolation stated",
       orchestrator, "per-turn")

_check("C6 provider-neutral stated",
       orchestrator, "provider-neutral")

_check("C7 pre-classifier stated",
       orchestrator, "pre-classifier")

_check("C8 classification_source mentioned",
       orchestrator, "classification_source")

_check("C9 V2 Phase 1a listed as complete",
       orchestrator, "V2 Phase 1a")

_check("C10 V2 Phase 1b listed as complete",
       orchestrator, "V2 Phase 1b")

_check("C11 V2 Phase 1c listed as complete",
       orchestrator, "V2 Phase 1c")

_check("C12 V2 Phase 1d listed as complete",
       orchestrator, "V2 Phase 1d")

_check("C13 UI slash-command described as downstream consumer",
       orchestrator, "UI slash-command")

_check("C14 backend contract described as stable/complete",
       orchestrator, "backend contract is stable")

_check("C15 V2 Phase 1e listed as complete",
       orchestrator, "V2 Phase 1e")

_check("C16 V2 Phase 1f listed as complete",
       orchestrator, "V2 Phase 1f")

_check("C17 http_contract_fixtures.json mentioned as canonical artifact",
       orchestrator, "http_contract_fixtures.json")


# ---------------------------------------------------------------------------
# Section D — HANDOFF.md
# ---------------------------------------------------------------------------

print("\n=== Section D: HANDOFF.md ===\n")

_check("D1 intent_hint appears",
       handoff, "intent_hint")

_check("D2 V2 Phase 1a listed",
       handoff, "V2 Phase 1a")

_check("D3 V2 Phase 1b listed",
       handoff, "V2 Phase 1b")

_check("D4 V2 Phase 1c listed as complete",
       handoff, "V2 Phase 1c")

_check("D5 V2 Phase 1d listed as complete",
       handoff, "V2 Phase 1d")

_check("D6 allowlist invariants present",
       handoff, "Allowlisted only")

_check("D7 deterministic router wins stated",
       handoff, "Deterministic router wins")

_check("D8 per-turn session isolation stated",
       handoff, "Per-turn in sessions")

_check("D9 safe ignore stated",
       handoff, "Safe ignore")

_check("D10 provider-neutral stated",
       handoff, "Provider-neutral")

_check("D11 pre-classifier stated",
       handoff, "Pre-classifier")

_check("D12 classification_source audit field mentioned",
       handoff, "classification_source")

_check("D13 LLM-based intent classification NOT marked as deferred",
       handoff, "LLM-based intent classification is **implemented**")

_check("D14 UI slash-command as next downstream consumer",
       handoff, "slash-command")

_check("D15 last-updated date reflects V2 Phase 1f",
       handoff, "V2 Phase 1f complete")

_check("D16 V2 Phase 1e listed",
       handoff, "V2 Phase 1e")

_check("D17 V2 Phase 1f listed",
       handoff, "V2 Phase 1f")

_check("D18 http_contract_fixtures.json mentioned as canonical artifact",
       handoff, "http_contract_fixtures.json")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*55}")
total = _passed + _failed
print(f"V2 doc parity: {_passed}/{total} passed")
if _failed:
    print("SOME CHECKS FAILED — docs are out of parity with backend contract")
    sys.exit(1)
else:
    print("All doc-parity checks passed.")
