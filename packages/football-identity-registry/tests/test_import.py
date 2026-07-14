import importlib


def test_package_imports() -> None:
    module = importlib.import_module("football_identity_registry")
    assert module.__name__ == "football_identity_registry"
