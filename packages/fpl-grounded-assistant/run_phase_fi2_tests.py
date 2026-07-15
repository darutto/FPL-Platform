"""FI-2 identity contract gate (stdlib source checks plus package tests)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages" / "football-identity-registry"
passed = failed = 0


def ok(value: bool, label: str) -> None:
    global passed, failed
    if value:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


contract = (PKG / "CONTRACT.md").read_text(encoding="utf-8")
source = "\n".join(path.read_text(encoding="utf-8") for path in (PKG / "football_identity_registry").glob("*.py"))
ok("player_identity.parquet" in contract and "ambiguity_queue.json" in contract, "persistent schemas and queue governed")
ok("manual_override` 1.00" in contract and "surname_birth_date` 0.80" in contract, "tier endpoints governed")
ok("os.replace" in source, "atomic replace implementation present")
ok(all(token not in source for token in ("import requests", "import urllib", "import socket", "sportmonks_client", "fpl_grounded_assistant")), "network/runtime contamination absent")
result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PKG, check=False)
ok(result.returncode == 0, "football-identity-registry pytest suite")
print(f"\nFI-2 identity checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
