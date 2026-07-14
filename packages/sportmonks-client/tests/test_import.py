import importlib


def test_package_imports() -> None:
    module = importlib.import_module("sportmonks_client")
    assert module.__name__ == "sportmonks_client"
