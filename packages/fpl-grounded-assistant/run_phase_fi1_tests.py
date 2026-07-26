"""FI-1 provider-neutral evidence contract gate (stdlib only; no network)."""
from __future__ import annotations

import ast
import re
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

from football_data_contract import (
    EVIDENCE_CODES,
    EvidenceDirection,
    EvidenceItem,
    SignalBasis,
    SubjectType,
)
from football_data_contract.evidence import EVIDENCE_FIELD_NAMES


REPO_ROOT = Path(__file__).resolve().parents[2]
PY_ROOT = REPO_ROOT / "packages" / "football-data-contract" / "football_data_contract"
TS_PATH = REPO_ROOT / "packages" / "fpl-ui" / "lib" / "evidence.ts"
FINAL_RESPONSE = REPO_ROOT / "packages" / "fpl-grounded-assistant" / "fpl_grounded_assistant" / "final_response.py"

passed = 0
failed = 0


def ok(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def make_item(**overrides: object) -> EvidenceItem:
    values: dict[str, object] = {
        "code": "ROLE_STABLE", "label": "Stable role",
        "subject_type": SubjectType.PLAYER, "subject_id": "cp_1",
        "fixture_id": None, "impact": 2.0,
        "direction": EvidenceDirection.POSITIVE, "confidence": 0.8,
        "basis": SignalBasis.OBSERVED, "summary": "Stable recent role.",
        "source_features": ("role_stability",),
        "model_version": "tactical-role-v1",
        "calculated_at": "2026-07-14T18:00:00Z",
    }
    values.update(overrides)
    return EvidenceItem(**values)  # type: ignore[arg-type]


def rejects(**overrides: object) -> bool:
    try:
        make_item(**overrides)
    except (TypeError, ValueError):
        return True
    return False


item = make_item()
ok(tuple(field.name for field in fields(EvidenceItem)) == EVIDENCE_FIELD_NAMES,
   "Python EvidenceItem field order is pinned")
ok(not {"provider", "provider_id", "recommendation"}.intersection(EVIDENCE_FIELD_NAMES),
   "EvidenceItem encodes no provider identity or recommendation field")
try:
    item.impact = 1.0  # type: ignore[misc]
except FrozenInstanceError:
    immutable = True
else:
    immutable = False
ok(immutable, "EvidenceItem is frozen")
ok(rejects(impact=10.01), "impact above upper bound rejected")
ok(rejects(impact=-10.01), "impact below lower bound rejected")
ok(rejects(confidence=1.01), "confidence above upper bound rejected")
ok(rejects(confidence=-0.01), "confidence below lower bound rejected")
ok(rejects(impact=-1.0, direction=EvidenceDirection.POSITIVE),
   "direction/impact mismatch rejected")
ok(rejects(source_features=["role_stability"]),
   "mutable source_features rejected")
ok(len(EVIDENCE_CODES) == 13, "approved evidence-code registry has exactly 13 values")
ok(EVIDENCE_CODES == {
    "MINUTES_CONFIDENCE_HIGH", "MINUTES_CONFIDENCE_LOW", "ROTATION_RISK",
    "CAMEO_RISK", "ROLE_STABLE", "ROLE_CHANGED", "OUT_OF_POSITION",
    "OPPONENT_FLANK_WEAKNESS", "OPPONENT_UNIT_DISRUPTION",
    "FIXTURE_CONGESTION", "REST_ADVANTAGE", "SET_PIECE_ROLE",
    "AVAILABILITY_DOUBT",
}, "evidence-code registry matches the approved literal set")
ok(rejects(basis="observed"), "basis outside the closed enum is rejected")
ok({member.value for member in SignalBasis} == {"observed", "inferred_proxy"},
   "SignalBasis vocabulary is closed")
ok({member.value for member in EvidenceDirection} == {"positive", "negative", "neutral"},
   "EvidenceDirection vocabulary is closed")
ok({member.value for member in SubjectType} == {"player", "team", "fixture"},
   "SubjectType vocabulary is closed")

forbidden_imports: list[str] = []
for source_path in PY_ROOT.glob("*.py"):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        forbidden_imports.extend(
            name for name in names
            if name.startswith(("fpl_", "sportmonks_", "requests", "httpx"))
        )
ok(not forbidden_imports, "package imports no platform or provider client")
prohibited_tactical_name = "average" + "_position"
ok(not any(
    prohibited_tactical_name in path.read_text(encoding="utf-8")
    for path in PY_ROOT.glob("*.py")
), "prohibited tactical field term absent from Python package")

ts_source = TS_PATH.read_text(encoding="utf-8")
interface_match = re.search(r"export interface EvidenceItem \{([\s\S]*?)\n\}", ts_source)
ts_fields = re.findall(r"^\s*readonly\s+(\w+)\??:", interface_match.group(1), re.MULTILINE) if interface_match else []
ok(tuple(ts_fields) == EVIDENCE_FIELD_NAMES, "TypeScript EvidenceItem fields match Python")
ok("readonly fixture_id: string | null;" in ts_source,
   "TypeScript fixture_id is explicitly nullable")
ok(not re.search(r"readonly\s+\w+\?:", ts_source),
   "TypeScript EvidenceItem has no independently optional fields")
ok(all(code in ts_source for code in EVIDENCE_CODES),
   "TypeScript contains every approved evidence code")
final_response_source = FINAL_RESPONSE.read_text(encoding="utf-8")
ok(bool(re.search(
       r"evidence:\s+[\"']?tuple\[EvidenceItem,\s*\.\.\.\]\s*\|\s*None[\"']?"
       r"\s*=\s*field\(default=None\)",
       final_response_source,
   )),
   "FinalResponse exposes additive optional immutable evidence in FI-7a")

print(f"\nFI-1 contract checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
