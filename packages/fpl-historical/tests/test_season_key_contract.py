"""
tests/test_season_key_contract.py
==================================
CONTRACT §1 / §3 checks: CURRENT_SEASON constant and season_registry.yaml.
"""

from __future__ import annotations

from pathlib import Path


SEASON_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "fpl-data-core"
    / "season_registry.yaml"
)

EXPECTED_SEASON = "2025-2026"


class TestSeasonKeyContract:
    def test_current_season_constant(self):
        """paths.CURRENT_SEASON must equal the canonical season string."""
        from fpl_historical.paths import CURRENT_SEASON

        assert CURRENT_SEASON == EXPECTED_SEASON

    def test_season_in_registry_yaml(self):
        """The exact season string must appear in season_registry.yaml."""
        assert SEASON_REGISTRY_PATH.exists(), (
            f"season_registry.yaml not found at {SEASON_REGISTRY_PATH}"
        )
        content = SEASON_REGISTRY_PATH.read_text(encoding="utf-8")

        # Try yaml.safe_load first for structured check; fall back to string search
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(content)
            seasons = [entry.get("season") for entry in data.get("seasons", [])]
            assert EXPECTED_SEASON in seasons, (
                f"'{EXPECTED_SEASON}' not found in seasons list of season_registry.yaml"
            )
        except ImportError:
            # pyyaml not available — plain string search
            assert EXPECTED_SEASON in content, (
                f"'{EXPECTED_SEASON}' not found in season_registry.yaml"
            )
