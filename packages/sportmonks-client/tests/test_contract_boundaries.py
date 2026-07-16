from pathlib import Path

from sportmonks_client.assumptions import assumption_registry
from sportmonks_client.cli import main


ROOT = Path(__file__).resolve().parents[2]


def test_assumptions_all_unverified_and_live_required():
    assumptions = assumption_registry()
    assert len(assumptions) >= 8
    assert all(item["status"] == "unverified_against_live" and item["live_validation_required"] for item in assumptions)


def test_fixture_provenance_labels_present():
    text = "\n".join(path.read_text(encoding="utf-8") for path in (Path(__file__).parent / "fixtures").glob("*.json"))
    assert "unverified_against_live" in text
    assert "documentation-derived" in text and "manually constructed" in text


def test_live_smoke_refuses_without_opt_in(capsys):
    assert main(["smoke"]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_live_smoke_opt_in_without_token_fails_without_network(monkeypatch, capsys):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    assert main(["smoke", "--i-understand-this-is-live"]) == 1
    assert "API_TOKEN" in capsys.readouterr().out


def test_no_sportmonks_import_contamination():
    forbidden_roots = ["football-data-contract", "football-identity-registry", "football-intelligence"]
    for package in forbidden_roots:
        production = ROOT / package
        text = "\n".join(path.read_text(encoding="utf-8") for path in production.rglob("*.py") if "tests" not in path.parts)
        assert "import sportmonks_client" not in text and "from sportmonks_client" not in text


def test_assistant_runtime_does_not_import_client():
    runtime = ROOT / "fpl-grounded-assistant" / "fpl_grounded_assistant"
    text = "\n".join(path.read_text(encoding="utf-8") for path in runtime.glob("*.py"))
    assert "sportmonks_client" not in text


def test_no_canonical_normalization_module():
    module = Path(__file__).parents[1] / "sportmonks_client"
    assert not (module / "normalize").exists() and not (module / "ingest.py").exists()
