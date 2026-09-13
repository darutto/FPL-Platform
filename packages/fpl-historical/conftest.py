"""Root conftest -- Windows-only ``basetemp`` pin (i71).

WHY THIS EXISTS
---------------
pytest's default ``basetemp`` is ``<tempfile.gettempdir()>/pytest-of-<user>``.
On this project's Windows machines that resolves under ``%LOCALAPPDATA%/Temp``,
where creating that directory is denied, so every test that requests
``tmp_path`` dies in fixture setup with ``PermissionError: [WinError 5]`` before
reaching its first assertion (measured on main 6f26c21, bare ``python -m pytest``:
fpl-historical 101 errors, football-intelligence 119, football-identity-registry
9 -- all ``tmp_path`` setup). The rule "always pass ``--basetemp`` outside
AppData" lived in people's heads; this file puts it in the repo. The same file
is dropped verbatim into every package that needs it.

WHAT IT DOES
------------
Only on Windows, and only when the caller did NOT pass ``--basetemp``, it pins
``basetemp`` to ``<package>/.pytest-tmp`` (gitignored at the repo root). On
Linux (CI) it is a no-op, so the CI baseline for this suite is untouched.

WHY ``pytest_configure`` AND NOT ``pytest_load_initial_conftests``
-----------------------------------------------------------------
The hookspec for ``pytest_load_initial_conftests`` says: "This hook is not
called for conftest files." The value has to be set before
``_pytest.tmpdir.pytest_configure`` builds its ``TempPathFactory`` (it reads
``config.option.basetemp`` exactly once, in ``TempPathFactory.from_config``).
Conftest hookimpls are registered after the builtin plugins and therefore run
first; ``tryfirst=True`` makes that ordering explicit instead of incidental.

Like an explicit ``--basetemp``, the pinned directory is wiped at the start of
every session (``TempPathFactory.getbasetemp`` does ``rm_rf`` on a given
basetemp). Nothing else changes: ``tmp_path`` names, retention and cleanup are
pytest's own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PACKAGE_DIR = Path(__file__).resolve().parent
_WINDOWS_BASETEMP = _PACKAGE_DIR / ".pytest-tmp"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    if not sys.platform.startswith("win"):
        return
    if getattr(config.option, "basetemp", None):
        # The caller chose a location; respect it.
        return
    config.option.basetemp = str(_WINDOWS_BASETEMP)
