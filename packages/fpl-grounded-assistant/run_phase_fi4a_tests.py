"""FI-4a offline normalizer, canonical store, replay, and transport-cap gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages" / "football-intelligence"
passed = failed = 0


def ok(value: bool, label: str) -> None:
    global passed, failed
    if value: passed += 1; print(f"  PASS: {label}")
    else: failed += 1; print(f"  FAIL: {label}")


contract = (PKG / "CONTRACT.md").read_text(encoding="utf-8")
source = "\n".join(path.read_text(encoding="utf-8") for path in (PKG / "football_intelligence" / "ingestion").glob("*.py"))
runtime_root = ROOT / "packages" / "fpl-grounded-assistant" / "fpl_grounded_assistant"
runtime_adapter = runtime_root / "football_intelligence_runtime.py"
other_runtime = "\n".join(
    path.read_text(encoding="utf-8", errors="ignore")
    for path in runtime_root.glob("*.py")
    if path != runtime_adapter
)
adapter_source = runtime_adapter.read_text(encoding="utf-8", errors="ignore")
ok("offline-only" in contract and "FI-4b" in contract, "offline-only boundary and FI-4b deferral documented")
ok("requests" not in source and "SPORTMONKS_API_TOKEN" not in source, "ingestion CLI exposes no network or token path")
allowed_runtime_imports = {
    "from football_intelligence.ingestion.builder_v2 import validate_context_build",
    "from football_intelligence.ingestion.context_v2 import select_schedule",
}
actual_runtime_imports = {
    line.strip()
    for line in adapter_source.splitlines()
    if "football_intelligence.ingestion" in line
}
ok(
    "football_intelligence.ingestion" not in other_runtime
    and actual_runtime_imports == allowed_runtime_imports,
    "assistant ingestion imports are confined to FI-7b2 read-only validation/selection",
)
ok("unverified_against_live" in (PKG / "football_intelligence" / "ingestion" / "team_registry_seed.json").read_text(), "mock provider team mappings remain unverified")
result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PKG, check=False)
ok(result.returncode == 0, "football-intelligence FI-4a pytest suite")
print(f"\nFI-4a ingestion checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
