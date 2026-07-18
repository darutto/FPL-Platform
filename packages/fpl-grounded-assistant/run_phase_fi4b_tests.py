"""FI-4b portable distribution and fail-soft runtime gate."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]; PKG = ROOT / "packages/football-intelligence"
passed = failed = 0
def ok(value, label):
    global passed, failed
    if value: passed += 1; print(f"  PASS: {label}")
    else: failed += 1; print(f"  FAIL: {label}")

source = "\n".join(p.read_text(encoding="utf-8") for p in (PKG / "football_intelligence/distribution").glob("*.py"))
builder = (PKG / "football_intelligence/ingestion/builder.py").read_text(encoding="utf-8")
ok('"source_fixture"' not in builder, "portable manifest has no source_fixture field")
ok("SPORTMONKS" not in source and "sportmonks_client" not in source, "distribution is provider-neutral")
ok("put_pointer" in source and "put_immutable" in source, "immutable publication and pointer-last primitives are pinned")
ok("ArtifactSizeError" in source and "limits.total" in source, "per-object and total download caps are pinned")
result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PKG, check=False)
ok(result.returncode == 0, "football-intelligence FI-4b pytest suite")
print(f"\nFI-4b distribution checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
