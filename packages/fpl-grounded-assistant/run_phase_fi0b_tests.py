"""FI-0(b) package-scaffold contract checks (stdlib only; no network)."""
from __future__ import annotations

import importlib
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    ("football-data-contract", "football_data_contract"),
    ("sportmonks-client", "sportmonks_client"),
    ("football-identity-registry", "football_identity_registry"),
    ("football-intelligence", "football_intelligence"),
)
REQUIRED_FILES = ("README.md", "CONTRACT.md", "pytest.ini", "requirements.txt")
APPROVED_REQUIREMENTS = {
    "sportmonks-client": ["requests>=2.31"],
    "football-identity-registry": ["pandas>=2.0", "pyarrow>=14.0", "PyYAML==6.0.3"],
}
DOCKERFILE = REPO_ROOT / "packages" / "fpl-grounded-assistant" / "Dockerfile"

passed = 0
failed = 0


def ok(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


docker_text = DOCKERFILE.read_text(encoding="utf-8")
for package_dir, module_name in PACKAGES:
    package_root = REPO_ROOT / "packages" / package_dir
    try:
        imported = importlib.import_module(module_name)
    except Exception:
        imported = None
    ok(imported is not None, f"{module_name} imports")
    ok(all((package_root / name).is_file() for name in REQUIRED_FILES),
       f"{package_dir} has required scaffold files")
    active_requirements = [
        line for line in (package_root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    expected_requirements = APPROVED_REQUIREMENTS.get(package_dir, [])
    ok(active_requirements == expected_requirements,
       f"{package_dir} dependencies match the deliberate FI-2 allowlist")
    docker_copy = re.compile(
        rf"^COPY\s+packages/{re.escape(package_dir)}/\s+"
        rf"/app/packages/{re.escape(package_dir)}/\s*$",
        re.MULTILINE,
    )
    ok(bool(docker_copy.search(docker_text)),
       f"backend image copies {package_dir} source to exact destination")

print(f"\nFI-0(b) scaffold checks: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
