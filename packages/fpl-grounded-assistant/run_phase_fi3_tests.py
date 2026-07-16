"""FI-3 Sportmonks client contract gate; delegates semantic checks to pytest."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages" / "sportmonks-client"
passed = failed = 0


def ok(value: bool, label: str) -> None:
    global passed, failed
    if value:
        passed += 1; print(f"  PASS: {label}")
    else:
        failed += 1; print(f"  FAIL: {label}")


contract = (PKG / "CONTRACT.md").read_text(encoding="utf-8")
source = "\n".join(path.read_text(encoding="utf-8") for path in (PKG / "sportmonks_client").glob("*.py"))
ok("unverified_against_live" in contract, "live assumptions remain explicitly unverified")
ok("canonical normalization" in contract and "FI-4" in contract, "canonical work remains deferred")
ok("api_token" in source and "SPORTMONKS_API_TOKEN" in source, "authentication location and environment key governed")
ok("data/football" not in source and "football_data_contract" not in source, "persistence and canonical contamination absent")
result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PKG, check=False)
ok(result.returncode == 0, "sportmonks-client pytest suite")
print(f"\nFI-3 client checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
