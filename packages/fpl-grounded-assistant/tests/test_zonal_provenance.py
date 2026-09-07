"""
Tests for i74 — the zonal surface declares which season its data is from.

The zonal tools read an owned Understat shot store keyed by season. Before
i74 they answered ``status: "ok"`` with a full verdict computed on last
season's shots while a new season was already three gameweeks old, and
neither the payload nor the card mentioned a season anywhere. That is worse
than switching off, because switching off is visible.

Two things have to be true for the stamp to be worth anything, and each is
pinned here by a test that a one-line mutation kills:

  1. WHAT THE STAMP SAYS comes from the store's own ``_tactical_latest.json``
     pointer, never from ``CURRENT_SEASON``. ``CURRENT_SEASON`` is what
     *locates* the store, so a stamp sourced from it could never disagree
     with the path it chose — a tautology wearing provenance's clothes.
     Mutation: source the season from ``CURRENT_SEASON``.

  2. WHAT IT IS COMPARED AGAINST comes from ``derive_live_season(bootstrap)``,
     never from ``CURRENT_SEASON``. The store key *is* ``CURRENT_SEASON`` by
     construction, so comparing them reports "up to date" unconditionally —
     including on the exact day this defect was measured.
     Mutation: compare against ``CURRENT_SEASON``.

Policy is DECLARE, never reject: a mismatch downgrades the stamp, never the
``status``. Rejecting would take the whole zonal surface offline until the
season rotation lands.
"""
from __future__ import annotations

import json
import os as _os
import sys as _sys

import pandas as pd
import pytest

# sys.path bootstrap — mirrors test_zonal_weakness_tool.py.
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
    _os.path.join(_PKGS, "fpl-tactical"),
    _os.path.join(_PKGS, "fpl-historical"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401  (triggers tool self-registration)
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_grounded_assistant.renderer import render  # noqa: E402
from fpl_grounded_assistant.zonal_weakness import (  # noqa: E402
    CURRENT_SEASON,
    MIN_TRUSTWORTHY_MATCHES,
    build_data_provenance,
)
from fpl_grounded_assistant.final_response import (  # noqa: E402
    _extract_zonal_opportunity_meta,
)


# ---------------------------------------------------------------------------
# Season helpers — derived from CURRENT_SEASON so these tests survive the
# i73 rotation instead of pinning today's literal.
# ---------------------------------------------------------------------------

def _start_year(season: str) -> int:
    return int(season.split("-")[0])


def _season_from_start(year: int) -> str:
    return f"{year}-{year + 1}"


#: The season a live bootstrap would report while the store still holds
#: CURRENT_SEASON — i.e. exactly the situation this stamp exists to catch.
NEXT_SEASON = _season_from_start(_start_year(CURRENT_SEASON) + 1)


def _bootstrap_for(season: str, *, with_fixtures: bool = False) -> dict:
    """Bootstrap whose GW1 deadline makes derive_live_season return *season*."""
    boot: dict = {
        "teams": [
            {"id": 1, "name": "Crystal Palace", "short_name": "CRY"},
            {"id": 2, "name": "Aston Villa", "short_name": "AVL"},
            {"id": 3, "name": "Burnley", "short_name": "BUR"},
            {"id": 4, "name": "Sunderland", "short_name": "SUN"},
        ],
        "events": [
            {
                "id": 1,
                "is_current": True,
                "deadline_time": f"{_start_year(season)}-08-14T17:30:00Z",
            }
        ],
    }
    if with_fixtures:
        boot["team_fixtures"] = {
            3: [
                {"gameweek": 1, "opponent_team": 1, "is_home": True},
                {"gameweek": 2, "opponent_team": 2, "is_home": False},
            ]
        }
    return boot


# ---------------------------------------------------------------------------
# Store fixture
# ---------------------------------------------------------------------------

def _row(conceding, shooting, x, y, xg, *, match_id=1, player="Someone"):
    return {
        "season": CURRENT_SEASON, "match_id": match_id,
        "date": "2025-09-01T15:00:00",
        "shooting_team": shooting, "conceding_team": conceding,
        "player": player, "is_home_shot": True, "minute": 10,
        "x": x, "y": y, "xg": xg, "situation": "Open Play",
        "shot_type": "Right Foot", "result": "Saved Shot",
    }


def _store_df() -> pd.DataFrame:
    """Crystal Palace very weak in-box/right; 'Right Poacher' (Burnley) there."""
    rows = [
        _row("Crystal Palace", "Burnley", 0.90, 0.20, 0.10,
             match_id=1, player="Right Poacher")
        for _ in range(10)
    ]
    rows += [
        _row("Aston Villa", "Crystal Palace", 0.90, 0.20, 0.10, match_id=2),
        _row("Burnley", "Aston Villa", 0.90, 0.20, 0.10, match_id=3),
        _row("Sunderland", "Burnley", 0.90, 0.20, 0.10, match_id=4),
    ]
    return pd.DataFrame(rows)


def _make_store(tmp_path, monkeypatch, pointer):
    """Owned store at FPL_TACTICAL_ROOT, optionally with a provenance pointer.

    The parquet always lives under the CURRENT_SEASON key (that is how the
    real store is laid out); *pointer* is written verbatim, so its ``season``
    field can deliberately disagree with the directory it sits in.
    """
    season_dir = tmp_path / "seasons" / CURRENT_SEASON
    season_dir.mkdir(parents=True)
    _store_df().to_parquet(season_dir / "understat_shots.parquet", index=False)
    if pointer is not None:
        (season_dir / "_tactical_latest.json").write_text(
            json.dumps(pointer), encoding="utf-8"
        )
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path


def _pointer(season: str, *, n_matches: int = 380, n_shots: int = 9524) -> dict:
    return {
        "season": season,
        "ingested_at": "2026-07-07T11:52:14Z",
        "source": "understat via soccerdata",
        "n_matches": n_matches,
        "n_shots": n_shots,
    }


# ===========================================================================
# MUTATION TARGET 1 — the stamp is read from the pointer, not from the key
# ===========================================================================

def test_stamp_names_the_pointers_season_not_the_store_key(tmp_path, monkeypatch):
    """A pointer that disagrees with its own directory is believed.

    The parquet sits under the CURRENT_SEASON key but the pointer next to it
    declares an older season. A stamp wired to CURRENT_SEASON would report
    the key and never notice; a real one reports what the data says about
    itself. This is the case that catches a mis-stamped or half-copied store.
    """
    stored = _season_from_start(_start_year(CURRENT_SEASON) - 6)
    assert stored != CURRENT_SEASON  # guard: the mutation must have room to differ
    _make_store(tmp_path, monkeypatch, _pointer(stored))

    out = run_tool(
        "get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap_for(stored)
    )

    assert out["status"] == "ok"
    assert out["data_provenance"]["season"] == stored
    assert out["data_provenance"]["season"] != CURRENT_SEASON


def test_stamp_never_invents_a_season_when_the_pointer_is_absent(tmp_path, monkeypatch):
    """No pointer means "we do not know", never a fallback to the store key.

    Falling back to CURRENT_SEASON here is the tautology in its purest form:
    an unlabelled parquet would be confidently announced as live-season data.
    """
    _make_store(tmp_path, monkeypatch, None)

    out = run_tool(
        "get_zonal_weakness", {"team": "Crystal Palace"},
        _bootstrap_for(CURRENT_SEASON),
    )

    assert out["status"] == "ok"           # declare, never reject
    prov = out["data_provenance"]
    assert prov["season"] is None
    assert prov["status"] == "unknown"
    assert prov["is_current"] is False
    assert "no declara" in prov["label"]


# ===========================================================================
# MUTATION TARGET 2 — compared against the LIVE season, not the store key
# ===========================================================================

def test_stale_season_is_detected_against_the_live_bootstrap(tmp_path, monkeypatch):
    """Store on CURRENT_SEASON + a bootstrap on the next one reads as stale.

    This is the measured production defect (2026-09-07): the store key and
    CURRENT_SEASON agree by construction, so a stamp that compares those two
    reports "up to date" while serving last season's shots. Only the live
    season derived from the bootstrap can disagree with the store.
    """
    _make_store(tmp_path, monkeypatch, _pointer(CURRENT_SEASON))

    out = run_tool(
        "get_zonal_weakness", {"team": "Crystal Palace"},
        _bootstrap_for(NEXT_SEASON),
    )

    assert out["status"] == "ok"           # declare, never reject
    prov = out["data_provenance"]
    assert prov["season"] == CURRENT_SEASON
    assert prov["live_season"] == NEXT_SEASON
    assert prov["status"] == "stale_season"
    assert prov["is_current"] is False
    assert "no de la temporada en curso" in prov["label"]


def test_matching_live_season_reads_as_current(tmp_path, monkeypatch):
    """Positive control — the stamp is not simply always crying stale."""
    _make_store(tmp_path, monkeypatch, _pointer(CURRENT_SEASON))

    out = run_tool(
        "get_zonal_weakness", {"team": "Crystal Palace"},
        _bootstrap_for(CURRENT_SEASON),
    )

    prov = out["data_provenance"]
    assert prov["status"] == "current"
    assert prov["is_current"] is True
    assert prov["season_label"] in prov["label"]
    assert "⚠" not in prov["label"]


# ===========================================================================
# All three tools, and the declare-never-reject policy
# ===========================================================================

_ALL_ZONAL_TOOLS = [
    ("get_zonal_weakness", {"team": "Crystal Palace"}),
    ("get_zonal_opportunity", {"opponent": "Crystal Palace"}),
    ("get_player_zonal_outlook", {"player": "Right Poacher"}),
]


@pytest.mark.parametrize("tool,args", _ALL_ZONAL_TOOLS)
def test_every_zonal_tool_declares_a_stale_season(tmp_path, monkeypatch, tool, args):
    """All three surfaces say it — the two text-only ones included.

    A prose answer has no card chrome to hang a badge on, so it is the easier
    one to be misled by, not the lesser case.
    """
    _make_store(tmp_path, monkeypatch, _pointer(CURRENT_SEASON))

    out = run_tool(tool, args, _bootstrap_for(NEXT_SEASON, with_fixtures=True))

    assert out["status"] == "ok", out
    prov = out["data_provenance"]
    assert prov["status"] == "stale_season"
    assert prov["season"] == CURRENT_SEASON
    assert prov["live_season"] == NEXT_SEASON


@pytest.mark.parametrize("tool,args", _ALL_ZONAL_TOOLS)
def test_stale_data_still_answers_and_the_text_says_so(
    tmp_path, monkeypatch, tool, args
):
    """Rendered text carries the warning — the card is not the only surface."""
    _make_store(tmp_path, monkeypatch, _pointer(CURRENT_SEASON))
    out = run_tool(tool, args, _bootstrap_for(NEXT_SEASON, with_fixtures=True))

    text = render(tool, out)

    assert out["data_provenance"]["label"] in text
    assert "no de la temporada en curso" in text


def test_renderers_stay_silent_on_pre_i74_payloads():
    """A payload with no provenance renders exactly as it did before i74."""
    payload = {
        "status": "ok", "team": "Crystal Palace", "verdict": "V.",
        "weakest_zones": [], "penalty_context": {},
    }
    assert render("get_zonal_weakness", payload) == "V."


# ===========================================================================
# The free catch: right season, not enough of it
# ===========================================================================

def test_thin_current_season_store_is_flagged_not_silently_trusted(
    tmp_path, monkeypatch
):
    """A correctly-stamped store with three gameweeks in it is still thin.

    This is what the i73 rotation will produce on day one: an honest
    ``season`` label over a sample far too small for a league-relative
    signal. A stamp that only named the season would say something true and
    hide this.
    """
    _make_store(
        tmp_path, monkeypatch,
        _pointer(CURRENT_SEASON, n_matches=30, n_shots=700),
    )

    out = run_tool(
        "get_zonal_weakness", {"team": "Crystal Palace"},
        _bootstrap_for(CURRENT_SEASON),
    )

    prov = out["data_provenance"]
    assert prov["status"] == "thin"
    assert prov["n_matches"] == 30
    assert prov["n_matches"] < MIN_TRUSTWORTHY_MATCHES
    assert "30" in prov["label"]
    assert out["status"] == "ok"


def test_unverifiable_live_season_is_its_own_state():
    """No usable bootstrap: name the season, admit we could not check it.

    Guessing "current" here would quietly restore the tautology.
    """
    prov = build_data_provenance(_pointer(CURRENT_SEASON), None)
    assert prov["status"] == "unverified"
    assert prov["is_current"] is False
    assert prov["season"] == CURRENT_SEASON


# ===========================================================================
# The card's projection
# ===========================================================================

def test_card_meta_carries_the_stamp(tmp_path, monkeypatch):
    """DefensiveZonesMeta projects the stamp so the card can render it."""
    _make_store(tmp_path, monkeypatch, _pointer(CURRENT_SEASON))
    out = run_tool(
        "get_zonal_opportunity", {"opponent": "Crystal Palace"},
        _bootstrap_for(NEXT_SEASON),
    )

    meta = _extract_zonal_opportunity_meta(out)

    assert meta is not None
    assert meta.data_provenance is not None
    assert meta.data_provenance.status == "stale_season"
    assert meta.data_provenance.label == out["data_provenance"]["label"]


def test_card_meta_survives_a_pre_i74_payload():
    """Older payloads still project — the card just shows no stamp."""
    meta = _extract_zonal_opportunity_meta({
        "status": "ok", "opponent": "X", "weakness_label": "W", "verdict": "V",
        "zones": [{"lateral": "left", "pct_over_avg": 5.0,
                   "opportunity_level": "warm"}],
        "exploiters": [], "penalty_context": {"penalty_xga_per_game": 0.1},
    })
    assert meta is not None
    assert meta.data_provenance is None
