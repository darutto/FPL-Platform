"""i75 (follow-up to PR #272): the zonal card's projected rows carry the club
provenance the tool already emits.

PR #272 made ``get_zonal_opportunity`` stamp every exploiter row with
``club_source`` (``"bootstrap"`` / ``"store"``) and ``club_note`` ("antes en
BUR" when the live club differs from the store's). The React card reads
``exploiter.club_note`` (``DefensiveZonesCard.tsx``, ``exploiterSub``) -- but
the card is fed through ``final_response.Exploiter`` +
``_extract_zonal_opportunity_meta``, which project an explicit field list, so
the two keys were dropped before reaching the wire. This pins that they now
survive the projection, and that a pre-i75 row (no such keys) still projects
with ``None`` rather than breaking.

No network, no store: the payload is the tool's documented row shape.
"""
from __future__ import annotations

import dataclasses
import os as _os
import sys as _sys

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

from fpl_grounded_assistant.final_response import (  # noqa: E402
    Exploiter,
    _extract_zonal_opportunity_meta,
)


def _row(rank: int, **extra) -> dict:
    base = {
        "rank": rank, "web_name": f"P{rank}", "team_short": "BRE",
        "position": "MID", "zone": "left", "fit_score": 7.5,
    }
    base.update(extra)
    return base


def _payload(*rows: dict) -> dict:
    return {
        "status": "ok", "opponent": "Crystal Palace",
        "weakness_label": "left flank", "verdict": "attack the left",
        "zones": [{"lateral": "left", "pct_over_avg": 12.0, "opportunity_level": "hot"}],
        "exploiters": list(rows),
        "penalty_context": {"penalty_xga_per_game": 0.1},
    }


def test_club_note_and_source_reach_the_projected_row():
    """A #272-shaped row (transferred player) keeps both keys through the
    projection -- the exact values the tool wrote, not re-derived."""
    meta = _extract_zonal_opportunity_meta(_payload(
        _row(1, club_source="bootstrap", club_note="antes en BUR"),
    ))
    assert meta is not None
    top = meta.exploiters[0]
    assert top.club_source == "bootstrap"
    assert top.club_note == "antes en BUR"
    # And the wire shape (harness_adapter._to_dict walks dataclass fields) sees them.
    assert dataclasses.asdict(top)["club_note"] == "antes en BUR"
    assert dataclasses.asdict(top)["club_source"] == "bootstrap"


def test_store_sourced_row_projects_note_as_none():
    """The no-match case #272 emits: club_source='store', club_note=None."""
    meta = _extract_zonal_opportunity_meta(_payload(
        _row(1, club_source="store", club_note=None),
    ))
    assert meta is not None
    assert meta.exploiters[0].club_source == "store"
    assert meta.exploiters[0].club_note is None


def test_pre_i75_row_without_the_keys_still_projects():
    """A row with neither key (older payload, or a fixture built before
    #272) must not break the card: both fields default to None."""
    meta = _extract_zonal_opportunity_meta(_payload(_row(1), _row(2)))
    assert meta is not None
    assert len(meta.exploiters) == 2
    for e in meta.exploiters:
        assert e.club_source is None
        assert e.club_note is None


def test_exploiter_dataclass_declares_both_fields_with_none_defaults():
    names = {f.name: f for f in dataclasses.fields(Exploiter)}
    assert names["club_source"].default is None
    assert names["club_note"].default is None
