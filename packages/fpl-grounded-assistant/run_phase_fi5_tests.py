"""FI-5 deterministic provider-neutral feature engine gate."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; PKG=ROOT/"packages/football-intelligence"; passed=failed=0
def ok(v,label):
 global passed,failed
 if v: passed+=1; print(f"  PASS: {label}")
 else: failed+=1; print(f"  FAIL: {label}")
source="\n".join(p.read_text(encoding="utf-8") for p in (PKG/"football_intelligence/features").glob("*.py"))
ok("strictly_before_kickoff_v1" in source,"strict pre-match cutoff pinned")
ok("RuntimeBuildHandle" in source,"validated local runtime handle is required")
ok("import sportmonks" not in source.casefold() and "from sportmonks" not in source.casefold() and "import requests" not in source,"feature engine is provider-neutral and offline")
ok("os.replace" in source and "validate_feature_build(stage" in source,"validation precedes atomic pointer publication")
result=subprocess.run([sys.executable,"-m","pytest","-q"],cwd=PKG,check=False)
ok(result.returncode==0,"complete football-intelligence FI-5 pytest boundary")
print(f"\nFI-5 feature checks: {passed} passed, {failed} failed"); raise SystemExit(1 if failed else 0)
