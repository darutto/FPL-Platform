import importlib


def test_package_imports() -> None:
    module = importlib.import_module("football_data_contract")
    assert module.__name__ == "football_data_contract"
