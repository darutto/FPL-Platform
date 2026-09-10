"""
tests/test_verify_healthz_season.py
====================================
i73 Entrega 2: scripts/verify_healthz_merged_at.py --expected-season is the
central invariant of the season rollover -- the manual "Verify /healthz"
workflow step used to confirm only a timestamp moved, never that production
actually serves the correct season for either store. These tests bite in
both directions: a matching payload must exit 0, and a season mismatch on
either store must NOT be accepted as a match even when merged_at agrees.

No network: requests.get is monkeypatched at the module's own import of it.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os
import sys as _sys
from types import SimpleNamespace

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_SCRIPT_PATH = _os.path.join(
    _os.path.dirname(_HERE), "scripts", "verify_healthz_merged_at.py"
)
_spec = _ilu.spec_from_file_location("verify_healthz_merged_at", _SCRIPT_PATH)
verify_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(verify_mod)


def _fake_response(body: dict, status: int = 200):
    return SimpleNamespace(status_code=status, json=lambda: body)


def _run(monkeypatch, body: dict, *, expected_season: str | None, expected_merged_at="M1"):
    monkeypatch.setattr(
        verify_mod.requests, "get", lambda *a, **k: _fake_response(body)
    )
    argv = [
        "verify_healthz_merged_at.py",
        "--url", "https://example.test/healthz",
        "--expected-merged-at", expected_merged_at,
        "--timeout", "1",
        "--interval", "1",
    ]
    if expected_season is not None:
        argv += ["--expected-season", expected_season]
    monkeypatch.setattr(_sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        verify_mod.main()
    return exc.value.code


def test_matching_season_and_merged_at_exits_zero(monkeypatch):
    body = {
        "owned_store_sync": {"merged_at": "M1", "season": "2026-2027"},
        "tactical_store_sync": {"season": "2026-2027"},
    }
    assert _run(monkeypatch, body, expected_season="2026-2027") == 0


def test_owned_season_mismatch_does_not_match(monkeypatch):
    """merged_at agrees but owned_store_sync.season is stale -- must NOT exit 0."""
    body = {
        "owned_store_sync": {"merged_at": "M1", "season": "2025-2026"},
        "tactical_store_sync": {"season": "2026-2027"},
    }
    assert _run(monkeypatch, body, expected_season="2026-2027") == 1


def test_tactical_season_mismatch_does_not_match(monkeypatch):
    """owned season is right but tactical_store_sync.season disagrees."""
    body = {
        "owned_store_sync": {"merged_at": "M1", "season": "2026-2027"},
        "tactical_store_sync": {"season": "2025-2026"},
    }
    assert _run(monkeypatch, body, expected_season="2026-2027") == 1


def test_tactical_block_absent_is_not_a_failure(monkeypatch):
    """No tactical_store_sync key at all (flag off) -- only owned season is checked."""
    body = {"owned_store_sync": {"merged_at": "M1", "season": "2026-2027"}}
    assert _run(monkeypatch, body, expected_season="2026-2027") == 0


def test_no_expected_season_preserves_merged_at_only_behavior(monkeypatch):
    """Backward compatibility: omitting --expected-season ignores season entirely."""
    body = {"owned_store_sync": {"merged_at": "M1", "season": "anything-else"}}
    assert _run(monkeypatch, body, expected_season=None) == 0
