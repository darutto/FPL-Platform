"""
tests/test_season_single_source.py
====================================
Cross-package test: every "satellite" that used to hardcode its own copy of
the current-season literal must now read it from the single source of
truth, packages/fpl-data-core/season_registry.yaml's `current_season` key
(loaded as fpl_data_core.season_registry.CURRENT_SEASON).

Incident this guards against: six-plus copies of "2025-2026" drifted from
reality unchecked for six weeks (owned-store-refresh silently wrote
2026-2027 data under the 2025-2026 key). "Single source of truth" is only
true if breaking the source actually breaks every consumer — this file
proves that by mutating the source and asserting every reloadable
consumer picks up the new value (or the mutation is asserted directly
against modules that are unsafe to reload mid-session).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = _REPO_ROOT / "packages"

for _pkg_dir in ("fpl-data-core", "fpl-historical", "fpl-tactical"):
    _p = str(_PACKAGES / _pkg_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_module_standalone(module_name: str, file_path: Path):
    """Load a module fresh from disk (bypasses sys.modules caching), mirroring
    test_owned_store_fallback.py's pattern so mutating a global constant and
    reloading doesn't collide with anything already imported this session."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_GROUNDED = _PACKAGES / "fpl-grounded-assistant" / "fpl_grounded_assistant"


@pytest.fixture
def restore_current_season():
    """Snapshot + restore fpl_data_core.season_registry.CURRENT_SEASON.

    Also reloads fpl_historical.paths / fpl_tactical.paths back to the
    restored value afterwards: importlib.reload() mutates the cached
    sys.modules entry in place, so leaving it un-reloaded after a test would
    permanently poison every later test that does
    ``from fpl_historical.paths import CURRENT_SEASON`` (including fresh
    standalone-loaded satellite modules, which still resolve that import
    against the same cached fpl_historical.paths module object).
    """
    from fpl_data_core import season_registry
    original = season_registry.CURRENT_SEASON
    yield season_registry
    season_registry.CURRENT_SEASON = original
    if "fpl_historical.paths" in sys.modules:
        importlib.reload(sys.modules["fpl_historical.paths"])
    if "fpl_tactical.paths" in sys.modules:
        importlib.reload(sys.modules["fpl_tactical.paths"])


class TestOwnPathsModulesReadTheSingleSource:
    """fpl_historical.paths and fpl_tactical.paths hold their own
    CURRENT_SEASON but must import it, not repeat the literal."""

    def test_fpl_historical_paths_matches_source(self):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        import fpl_historical.paths as fh_paths
        assert fh_paths.CURRENT_SEASON == SOURCE

    def test_fpl_tactical_paths_matches_source(self):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        import fpl_tactical.paths as ft_paths
        assert ft_paths.CURRENT_SEASON == SOURCE

    def test_mutating_source_breaks_fpl_historical_paths(self, restore_current_season):
        """Break the source -> fpl_historical.paths goes red (mismatches) on reload."""
        import fpl_historical.paths as fh_paths
        restore_current_season.CURRENT_SEASON = "1999-2000"
        importlib.reload(fh_paths)
        assert fh_paths.CURRENT_SEASON == "1999-2000"

    def test_mutating_source_breaks_fpl_tactical_paths(self, restore_current_season):
        import fpl_tactical.paths as ft_paths
        restore_current_season.CURRENT_SEASON = "1999-2000"
        importlib.reload(ft_paths)
        assert ft_paths.CURRENT_SEASON == "1999-2000"


class TestGroundedAssistantSatellitesReadTheSingleSource:
    """Standalone-loadable satellites (mirrors test_owned_store_fallback.py's
    import pattern to avoid pulling in fpl_grounded_assistant/__init__.py)."""

    @pytest.mark.parametrize("module_name,file_name", [
        ("owned_store_fallback", "owned_store_fallback.py"),
        ("owned_store_sync", "owned_store_sync.py"),
        ("zonal_weakness", "zonal_weakness.py"),
    ])
    def test_satellite_matches_source(self, module_name, file_name):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        mod = _load_module_standalone(
            f"fpl_grounded_assistant.{module_name}_singlesource_check",
            _GROUNDED / file_name,
        )
        assert mod.CURRENT_SEASON == SOURCE

    def test_get_player_season_points_matches_source(self):
        # Imported normally elsewhere in the suite (unconditional
        # fpl_tool_runner registration makes standalone loading unsafe here);
        # equality against the live source is still a real assertion that it
        # is not carrying its own independent literal.
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        from fpl_grounded_assistant.get_player_season_points import CURRENT_SEASON as SATELLITE
        assert SATELLITE == SOURCE

    def test_historical_gameweek_top_scorer_matches_source(self):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        from fpl_grounded_assistant.historical_gameweek_top_scorer import CURRENT_SEASON as SATELLITE
        assert SATELLITE == SOURCE


# ---------------------------------------------------------------------------
# The GitHub Actions workflows — the sites the #222 consolidation could not
# reach, because YAML cannot import Python.
# ---------------------------------------------------------------------------

import re          # noqa: E402
import shutil      # noqa: E402
import subprocess  # noqa: E402

import yaml        # noqa: E402

_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_SEASON_LITERAL = re.compile(r"\b\d{4}-\d{4}\b")

#: Workflows that pick a season key and act on a store under it. Both must
#: derive that key from the registry; neither may carry its own copy.
_STORE_WORKFLOWS = ["owned-store-refresh.yml", "tactical-store-refresh.yml"]


def _workflow_values_only(name: str) -> str:
    """Return the workflow's *values* as text, with every comment dropped.

    Round-tripping through the YAML parser is what drops them — comments are
    not part of the parsed document. So a season key surviving into this
    string is a real pin, not prose about the incident.
    """
    doc = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    return yaml.safe_dump(doc, allow_unicode=True, default_flow_style=False)


def _resolve_command(name: str) -> str:
    """Extract the one `python -c "..."` payload out of a workflow's shell."""
    text = (_WORKFLOWS / name).read_text(encoding="utf-8")
    found = re.findall(r'python -c "([^"]+)"', text)
    assert len(found) == 1, (
        f"{name}: expected exactly one `python -c` invocation (the season "
        f"resolution); found {len(found)}"
    )
    return found[0]


class TestWorkflowsResolveSeasonFromTheRegistry:
    """A workflow cannot import Python, so it shells out to it. These cover
    both halves of that: that no workflow still pins a season literal, and
    that the command it shells out to actually tracks the registry."""

    @pytest.mark.parametrize("workflow", _STORE_WORKFLOWS)
    def test_workflow_pins_no_season_literal(self, workflow):
        """No season key appears in any workflow *value* (comments excluded).

        tactical-store-refresh.yml carried `DEFAULT_SEASON: "2025-2026"` in
        its env block until 2026-09-07 — the twelfth copy of the key, and the
        one still running on a live weekly cron while the rest of the
        pipeline sat paused. Swapping that literal for a newer literal would
        leave the identical defect, so this asserts on the *shape*, never on
        the value.
        """
        found = _SEASON_LITERAL.findall(_workflow_values_only(workflow))
        assert not found, (
            f"{workflow} pins season literal(s) {found} in a value. The "
            f"season key must be resolved at run time from "
            f"packages/fpl-data-core/season_registry.yaml."
        )

    @pytest.mark.parametrize("workflow", _STORE_WORKFLOWS)
    def test_resolve_step_follows_the_registry(self, workflow, tmp_path):
        """Mutate the registry, run the workflow's own resolve command
        against the mutant, and assert the answer moved with it.

        The command is extracted from the workflow file rather than re-typed
        here, so the thing under test is the thing that runs. A resolve step
        that reads a stale or wrong copy of the registry passes every static
        check and fails this one.

        No network: the command only imports and prints a constant.
        """
        scratch_pkg = tmp_path / "packages" / "fpl-data-core"
        scratch_pkg.mkdir(parents=True)
        shutil.copytree(
            _PACKAGES / "fpl-data-core" / "fpl_data_core",
            scratch_pkg / "fpl_data_core",
        )
        registry = (
            _PACKAGES / "fpl-data-core" / "season_registry.yaml"
        ).read_text(encoding="utf-8")
        from fpl_data_core.season_registry import CURRENT_SEASON as REAL
        mutated = registry.replace(
            f'current_season: "{REAL}"', 'current_season: "1999-2000"'
        )
        assert 'current_season: "1999-2000"' in mutated, (
            "could not rewrite current_season in season_registry.yaml; the "
            "key's formatting changed — update this mutation to match."
        )
        # current_season must name a season the same load registers.
        mutated += (
            '\n  - season: "1999-2000"\n'
            '    data_root: "data/1999-2000"\n'
            '    has_consolidated_files: false\n'
            '    files:\n'
            '      players: "players.csv"\n'
        )
        (scratch_pkg / "season_registry.yaml").write_text(mutated, encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-c", _resolve_command(workflow)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, (
            f"{workflow}'s season-resolution command failed: {proc.stderr}"
        )
        assert proc.stdout.strip() == "1999-2000", (
            f"{workflow}'s season-resolution command printed "
            f"{proc.stdout.strip()!r} against a registry whose current_season "
            f"is '1999-2000'. It is not reading the registry."
        )
