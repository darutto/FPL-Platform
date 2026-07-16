from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "football_identity_registry"


def test_no_network_or_runtime_imports():
    text = "\n".join(path.read_text(encoding="utf-8") for path in MODULE.glob("*.py"))
    for forbidden in ("requests", "urllib", "http.client", "socket", "sportmonks", "fpl_grounded_assistant", "fpl_player_registry"):
        assert forbidden not in text


def test_existing_matcher_is_not_modified_by_package():
    assert not (MODULE / "player_matching.py").exists()
