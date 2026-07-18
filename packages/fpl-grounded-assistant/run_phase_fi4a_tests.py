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
runtime = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "packages" / "fpl-grounded-assistant" / "fpl_grounded_assistant").glob("*.py"))
ok("offline-only" in contract and "FI-4b" in contract, "offline-only boundary and FI-4b deferral documented")
ok("requests" not in source and "SPORTMONKS_API_TOKEN" not in source, "ingestion CLI exposes no network or token path")
ok("football_intelligence.ingestion" not in runtime, "assistant runtime does not import FI-4a ingestion")
ok("unverified_against_live" in (PKG / "football_intelligence" / "ingestion" / "team_registry_seed.json").read_text(), "mock provider team mappings remain unverified")
result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PKG, check=False)
ok(result.returncode == 0, "football-intelligence FI-4a pytest suite")
print(f"\nFI-4a ingestion checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
