"""
Tests for Track D / FI4-3 — deterministic /calendario routing.

The fixture ticker is reached deterministically via a distinct 'ticker'
trigger, so it never competes with the existing team-calendar ranking routes.
axis defaults to attack and flips to defence on clean-sheet phrasing. The
/calendario slash command routes here via its intent-hint canonical template.
"""
from __future__ import annotations

import os as _os
import sys as _sys

# sys.path bootstrap (mirror fpl_server.py's _SIB pattern).
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant.router import route  # noqa: E402
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    _HINT_CANONICAL_TEMPLATES,
    INTENT_HINT_ALLOWLIST,
    INTENT_FIXTURE_OUTLOOK,
    _TOOL_TO_INTENT,
)


# ---------------------------------------------------------------------------
# Deterministic route + axis extraction
# ---------------------------------------------------------------------------

def test_route_fixture_ticker_defaults_to_attack():
    rr = route("fixture ticker")
    assert rr is not None
    assert rr.tool_name == "get_fixture_outlook"
    assert rr.tool_args == {"axis": "attack"}


def test_route_ticker_spanish_phrasing():
    rr = route("muéstrame el ticker de calendario")
    assert rr is not None and rr.tool_name == "get_fixture_outlook"
    assert rr.tool_args["axis"] == "attack"


def test_route_ticker_defence_axis():
    for q in ("fixture ticker portería a cero",
              "ticker defensivo",
              "clean sheet ticker"):
        rr = route(q)
        assert rr is not None and rr.tool_name == "get_fixture_outlook", q
        assert rr.tool_args["axis"] == "defence", q


# ---------------------------------------------------------------------------
# No regression on the existing team-calendar routes (overlap guard)
# ---------------------------------------------------------------------------

def test_best_fixtures_still_routes_to_team_calendar():
    rr = route("which teams have the best fixtures next 5 gameweeks")
    assert rr is not None and rr.tool_name == "get_team_fixture_calendar"


def test_plain_calendar_query_not_hijacked():
    # No 'ticker' → must NOT go to fixture_outlook.
    rr = route("qué equipos tienen el mejor calendario las próximas 5 jornadas")
    assert rr is not None and rr.tool_name == "get_team_fixture_calendar"


# ---------------------------------------------------------------------------
# Intent-hint canonical flow (the /calendario slash command)
# ---------------------------------------------------------------------------

def test_hint_registered_and_allowlisted():
    assert INTENT_FIXTURE_OUTLOOK in _HINT_CANONICAL_TEMPLATES
    assert INTENT_FIXTURE_OUTLOOK in INTENT_HINT_ALLOWLIST


def test_slash_calendario_canonical_routes_to_fixture_outlook():
    # /calendario sends an empty question → template collapses to "fixture ticker".
    template = _HINT_CANONICAL_TEMPLATES[INTENT_FIXTURE_OUTLOOK]
    canonical = template.replace("{question}", "").strip()
    rr = route(canonical)
    assert rr is not None and rr.tool_name == "get_fixture_outlook"
    # …and that tool maps back to the renderable fixture_outlook intent (the card).
    assert _TOOL_TO_INTENT["get_fixture_outlook"] == INTENT_FIXTURE_OUTLOOK


def test_slash_calendario_with_defence_text():
    template = _HINT_CANONICAL_TEMPLATES[INTENT_FIXTURE_OUTLOOK]
    canonical = template.replace("{question}", "portería").strip()
    rr = route(canonical)
    assert rr is not None and rr.tool_name == "get_fixture_outlook"
    assert rr.tool_args["axis"] == "defence"
