import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "football_data_contract"
FORBIDDEN_IMPORT_PREFIXES = ("fpl_", "sportmonks_", "requests", "httpx")


def test_package_has_no_provider_or_platform_imports() -> None:
    for path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            assert not any(name.startswith(FORBIDDEN_IMPORT_PREFIXES) for name in names)


def test_no_prohibited_tactical_field_identifier_exists() -> None:
    prohibited_name = "average" + "_position"
    for path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        identifiers = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
        }
        assert prohibited_name not in identifiers


def test_provider_name_is_confined_to_the_closed_provider_enum() -> None:
    for path in PACKAGE_ROOT.glob("*.py"):
        if path.name == "enums.py":
            continue
        assert "sportmonks" not in path.read_text(encoding="utf-8").casefold()
