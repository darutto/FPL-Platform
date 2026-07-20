"""FI-5b(b) module-enablement feature-contract-v2 gate."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_features_v2.py"], cwd=ROOT / "packages/football-intelligence", check=False)
raise SystemExit(result.returncode)
