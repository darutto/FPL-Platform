import importlib


def test_package_imports() -> None:
    module = importlib.import_module("football_intelligence")
    assert module.__name__ == "football_intelligence"
