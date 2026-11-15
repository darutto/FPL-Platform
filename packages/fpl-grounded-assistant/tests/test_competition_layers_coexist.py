"""The European manual layer is ADDED to the licensed cups (FA, EFL); it never replaces them.

Prod report (2026-10-30): after the manual layer shipped, /fixtures showed Europe and no EFL. These tests pin the
contract at the endpoint: with or without the layer (file or Railway variable), every cup the licensed store holds
is still served, for one team and for all teams.
"""
from __future__ import annotations

import json

import pytest

import fpl_server  # noqa: F401  (puts the sibling packages on sys.path)
from fpl_grounded_assistant import competition_calendar as cc
from test_competition_calendar_licensed import _fa, _install, _snap

_EFL = lambda club, opp, code, when: ["EFL", *_fa(club, opp, code, when)[1:]]  # noqa: E731
_RECS = [
    _fa("ARS", "Luton", "LUT", "2098-12-20T19:45:00Z"),
    _EFL("ARS", "Brighton", "BHA", "2098-12-17T19:45:00Z"),
    _EFL("CHE", "Brighton", "BHA", "2098-12-17T19:45:00Z"),
]
_ROWS = [
    {"competition": "UCL", "club": "ARS", "opponent": "Equipo Uno", "opponent_code": "", "date": "2099-01-01",
     "venue": "A", "kickoff_known": True, "kickoff_utc": "2099-01-01T20:00:00Z"},
    {"competition": "UEL", "club": "CHE", "opponent": "Equipo Dos", "opponent_code": "", "date": "2099-01-02",
     "venue": "H", "kickoff_known": False},
]
_ENVELOPE = {"schema_version": 1, "provenance": "manual_curated", "list_date": "2026-10-28", "coverage": "partial",
             "frozen": True, "competitions": ["UCL", "UEL"], "matches": _ROWS}


def _comps(out, team):
    return sorted((m["competition"], m["kickoff_utc"][:10]) for m in out["teams"][team]["matches"])


@pytest.fixture
def served(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap("FA"), _snap("EFL")], _RECS)
    target = tmp_path / "sub" / "europe.json"
    monkeypatch.setenv(cc.ENV_MANUAL, str(target))
    monkeypatch.delenv(cc.ENV_MANUAL_JSON, raising=False)
    cc._manual_cache.clear()
    return target


def test_cups_alone_without_the_layer(served):
    out = cc.competitions_response("patreon_basic", None, None, None)
    assert _comps(out, "ARS") == [("EFL", "2098-12-17"), ("FA", "2098-12-20")]
    assert "manual" not in out["data"]


@pytest.mark.parametrize("team", [None, "ARS"])
def test_the_railway_variable_adds_europe_and_keeps_the_cups(served, monkeypatch, team):
    monkeypatch.setenv(cc.ENV_MANUAL_JSON, json.dumps(_ENVELOPE))
    assert cc.materialize_manual_layer()["state"] == "written"
    cc._manual_cache.clear()
    out = cc.competitions_response("patreon_basic", team, None, None)
    assert _comps(out, "ARS") == [("EFL", "2098-12-17"), ("FA", "2098-12-20"), ("UCL", "2099-01-01")]
    if team is None:
        assert _comps(out, "CHE") == [("EFL", "2098-12-17"), ("UEL", "2099-01-02")]
    assert out["data"]["provenance"] == "licensed_starter+manual_curated"
    assert out["data"]["coverage"] == {"FA": "partial", "EFL": "partial"}  # the cups' own coverage is untouched


def test_an_invalid_variable_leaves_exactly_the_cups(served, monkeypatch):
    monkeypatch.setenv(cc.ENV_MANUAL_JSON, "{not json")
    cc.materialize_manual_layer()
    cc._manual_cache.clear()
    out = cc.competitions_response("patreon_basic", None, None, None)
    assert _comps(out, "ARS") == [("EFL", "2098-12-17"), ("FA", "2098-12-20")]
    assert "manual" not in out["data"]


def test_the_window_filter_applies_to_every_layer_alike(served, monkeypatch):
    monkeypatch.setenv(cc.ENV_MANUAL_JSON, json.dumps(_ENVELOPE))
    cc.materialize_manual_layer()
    cc._manual_cache.clear()
    out = cc.competitions_response("patreon_basic", "ARS", "2098-12-01", "2098-12-31")
    assert _comps(out, "ARS") == [("EFL", "2098-12-17"), ("FA", "2098-12-20")]
