"""The orchestrator is the only place both sides meet; neither side may import it.

Mirror of sportmonks-client's test_no_sportmonks_import_contamination, which stays unchanged.
"""
from __future__ import annotations

from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]


def _production_text(package: str, module: str) -> str:
    root = PACKAGES / package / module
    return "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))


def test_neither_side_imports_the_orchestrator():
    for package, module in (("football-intelligence", "football_intelligence"),
                            ("sportmonks-client", "sportmonks_client"),
                            ("football-data-contract", "football_data_contract"),
                            ("football-identity-registry", "football_identity_registry")):
        text = _production_text(package, module)
        assert "licensed_ingestion" not in text, package


def test_the_orchestrator_imports_both_sides():
    text = _production_text("licensed-ingestion", "licensed_ingestion")
    assert "from sportmonks_client" in text and "from football_intelligence" in text


def test_football_intelligence_still_never_imports_the_client():
    assert "sportmonks_client" not in _production_text("football-intelligence", "football_intelligence")


def test_the_job_has_no_network_of_its_own():
    """Provider traffic goes through sportmonks_client's Transport and the free FPL feed through fpl_api_client;
    this package builds no URL and imports no HTTP library."""
    for path in (PACKAGES / "licensed-ingestion" / "licensed_ingestion").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "recording.py":    # its replay answers by path, and parses a URL it is handed
            continue
        for banned in ("import requests", "import httpx", "import urllib", "from requests", "from urllib", "http://",
                       "https://", "api_token", "RawResponseSnapshot", "raw_hook"):
            assert banned not in text, f"{path.name}: {banned}"
