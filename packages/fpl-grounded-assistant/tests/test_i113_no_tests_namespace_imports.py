"""i113 -- no test in this package may import from the ``tests`` namespace.

``packages/fpl-grounded-assistant/tests`` has no ``__init__.py``: pytest
(rootdir importmode, the default) puts this directory on sys.path and test
modules import each other and the conftest by bare name --
``from conftest import BOOTSTRAP``, ``from test_name_resolution import ...``.

The name ``tests`` is therefore NOT this directory. pytest.ini's
``pythonpath`` lists sibling packages whose ``tests/`` ARE regular packages
(fpl-data-core first, then fpl-api-client, fpl-player-registry,
fpl-query-tools, fpl-tool-contract, fpl-tool-runner), so ``import tests``
binds to whichever of those is first on sys.path -- measured 2026-10-03:
``fpl-data-core/tests``. In CI the winner moved with import order and
``from tests.conftest import BOOTSTRAP`` failed intermittently (#315, the
stats bot; fixed in that one test by #316).

Adding an ``__init__.py`` here was tried and rejected: 9 modules stop
collecting (bare-name sibling imports), and making them collect would mean
``from tests.x import`` -- the very pattern this guard forbids. Sibling
packages keep their own ``from tests.conftest import``; each runs in its own
directory, where ``tests`` is theirs.

The guard is a static scan (AST), not a runtime probe, so it does not depend
on which ``tests`` happens to win on a given machine.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def _is_tests_name(name: str | None) -> bool:
    return bool(name) and (name == "tests" or name.startswith("tests."))


def scan_tests_namespace_imports(source: str) -> list[str]:
    """Every way *source* reaches the ``tests`` namespace, as ``line:what``."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits += [f"{node.lineno}:import {a.name}" for a in node.names if _is_tests_name(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _is_tests_name(node.module):
                hits.append(f"{node.lineno}:from {node.module} import")
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if fname in ("import_module", "__import__") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_tests_name(arg.value):
                    hits.append(f"{node.lineno}:{fname}({arg.value!r})")
    return hits


def _test_sources() -> list[Path]:
    return sorted(p for p in TESTS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_test_imports_from_the_tests_namespace():
    offenders = {
        str(p.relative_to(TESTS_DIR)): hits
        for p in _test_sources()
        if (hits := scan_tests_namespace_imports(p.read_text(encoding="utf-8")))
    }
    assert offenders == {}, (
        "`tests` is not this directory here (no __init__.py; it resolves to a sibling "
        "package's tests/). Import by bare name instead -- `from conftest import X`, "
        f"or use the fixture. Offenders: {offenders}"
    )


def test_the_scan_covers_the_whole_suite():
    sources = _test_sources()
    assert len(sources) > 100
    assert TESTS_DIR / "conftest.py" in sources


def test_this_directory_stays_a_rootdir_import_directory():
    """The guard's premise. Adding __init__.py changes how every module here
    is named; that is a decision with its own card, not a drive-by."""
    assert not (TESTS_DIR / "__init__.py").exists()


# ---------------------------------------------------------------------------
# the scanner itself catches every form (so the guard is not vacuous)
# ---------------------------------------------------------------------------

def test_scanner_catches_every_form():
    src = "\n".join([
        "from tests.conftest import BOOTSTRAP",
        "from tests import conftest",
        "import tests",
        "import tests.conftest as c",
        "import os, tests.helpers",
        "importlib.import_module('tests.conftest')",
        "__import__('tests')",
    ])
    assert len(scan_tests_namespace_imports(src)) == 7


def test_scanner_ignores_what_is_legal_here():
    src = "\n".join([
        "from conftest import BOOTSTRAP",
        "from test_name_resolution import CURRENT_PL_TEAMS",
        "from .helpers import x",                  # relative: not the global name
        "import testsuite",
        "from tests_support import y",
        "x = 'from tests.conftest import BOOTSTRAP'",  # a string, not an import
    ])
    assert scan_tests_namespace_imports(src) == []
