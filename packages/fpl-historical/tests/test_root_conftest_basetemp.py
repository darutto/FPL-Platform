"""
tests/test_root_conftest_basetemp.py
====================================
Pins the two guards of the root ``conftest.py`` ``basetemp`` hook (i71):

1. Windows-only -- on any other platform the hook leaves ``config.option``
   untouched, so the CI (Linux) baseline is unaffected.
2. An explicit ``--basetemp`` from the caller is respected, never overridden.

The hook is loaded by path rather than ``import conftest``: with a non-package
``tests/`` directory both the root and ``tests/conftest.py`` would resolve to
the bare module name ``conftest``, and pytest deliberately evicts the earlier
one from ``sys.modules`` when it imports the next.

The end-to-end evidence (a bare ``python -m pytest`` in this package on Windows
going from 101 errors to 0) is in the i71 PR; these tests only make each guard
individually mutable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT_CONFTEST = Path(__file__).resolve().parent.parent / "conftest.py"


def _load_root_conftest():
    spec = importlib.util.spec_from_file_location(
        "fpl_historical_root_conftest_under_test", _ROOT_CONFTEST
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_config(basetemp):
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))


def test_windows_without_flag_pins_basetemp_under_package(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mod = _load_root_conftest()
    config = _fake_config(None)

    mod.pytest_configure(config)

    pinned = Path(config.option.basetemp)
    assert pinned == _ROOT_CONFTEST.parent / ".pytest-tmp"
    assert pinned.name == ".pytest-tmp"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_non_windows_is_a_no_op(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    mod = _load_root_conftest()
    config = _fake_config(None)

    mod.pytest_configure(config)

    assert config.option.basetemp is None


def test_explicit_basetemp_is_respected_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mod = _load_root_conftest()
    explicit = "C:/somewhere/the/caller/chose"
    config = _fake_config(explicit)

    mod.pytest_configure(config)

    assert config.option.basetemp == explicit
