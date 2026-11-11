"""The player card's ``strip_axis``: observed role -> fixture-strip axis, end to end over a synthetic licensed store.

No network, no provider, no LLM. Every lineup here is invented.
"""
from __future__ import annotations

import pandas as pd
import pytest

from fpl_grounded_assistant import player_strip_axis as mod
from fpl_grounded_assistant.final_response import _extract_player_snapshot_meta
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.player_strip_axis import strip_axis_for
from football_intelligence.ingestion.licensed.store import TABLES

HOLDER, WINGBACK, NEWBIE, NOBODY = 501, 502, 503, 504  # MID, DEF, MID, DEF

BOOTSTRAP = {
    "teams": [{"id": 1, "name": "Alpha", "short_name": "AAA"}, {"id": 2, "name": "Beta", "short_name": "BBB"}],
    "element_types": [{"id": 2, "singular_name_short": "DEF"}, {"id": 3, "singular_name_short": "MID"}],
    "elements": [
        {"id": HOLDER, "web_name": "Holder", "first_name": "Hal", "second_name": "Holder", "team": 1, "element_type": 3, "status": "a"},
        {"id": WINGBACK, "web_name": "Wingback", "first_name": "Wes", "second_name": "Wingback", "team": 1, "element_type": 2, "status": "a"},
        {"id": NEWBIE, "web_name": "Newbie", "first_name": "Ned", "second_name": "Newbie", "team": 1, "element_type": 3, "status": "a"},
        {"id": NOBODY, "web_name": "Nobody", "first_name": "Noa", "second_name": "Nobody", "team": 2, "element_type": 2, "status": "a"},
    ],
}
FPL_FIXTURES = [
    {"id": fid, "event": fid, "kickoff_time": f"2026-11-{fid:02d}T15:00:00Z", "team_h": 1, "team_a": 2}
    for fid in range(1, 6)
]


def _tables():
    snaps, slots = [], []
    for fid in range(1, 6):
        obs = f"2026-11-{fid:02d}T10:00:00Z"
        snaps.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "state": "finished", "confirmed": True,
                      "formation": "3-4-2-1", "n_starters": 3, "n_bench": 1})
        slots.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "element": HOLDER, "starter": True,
                      "detailed_position": "Defensive Midfield", "grid_slot": "3:2", "side": "centre"})
        slots.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "element": WINGBACK, "starter": True,
                      "detailed_position": "Left Midfield", "grid_slot": "3:4", "side": "left"})
        # Two starts only, then the bench: under the minimum, FPL decides.
        slots.append({"fixture_id": fid, "team": "AAA", "observed_at": obs, "element": NEWBIE, "starter": fid <= 2,
                      "detailed_position": "Defensive Midfield" if fid <= 2 else None,
                      "grid_slot": "3:3" if fid <= 2 else None, "side": "centre" if fid <= 2 else None})
    frames = {"lineup_snapshots": snaps, "lineup_slots": slots}
    return {name: pd.DataFrame(rows, columns=list(TABLES[name][0])).astype(object) for name, rows in frames.items()}


class FakeHandle:
    def __init__(self, build_id="b-1"):
        self._tables, self._build_id, self.reads = _tables(), build_id, 0

    def build_id(self):
        return self._build_id

    def table(self, name):
        self.reads += 1
        return self._tables[name]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "1")
    mod._reset_for_tests()
    yield
    mod._reset_for_tests()


def _axis(element, handle, **kw):
    return strip_axis_for(element, dict(BOOTSTRAP), handle=handle, fetch_fixtures=lambda: FPL_FIXTURES,
                          background=False, **kw)


def test_a_defensive_mid_reads_defence_and_an_attacking_wing_back_attack():
    handle = FakeHandle()
    assert _axis(HOLDER, handle) == "defence"
    assert _axis(WINGBACK, handle) == "attack"


def test_too_few_starts_and_no_data_leave_the_fpl_fallback():
    handle = FakeHandle()
    assert _axis(NEWBIE, handle) is None
    assert _axis(NOBODY, handle) is None


def test_the_store_is_read_once_per_build():
    handle = FakeHandle()
    for element in (HOLDER, WINGBACK, NEWBIE, HOLDER):
        _axis(element, handle)
    assert handle.reads == 2  # lineup_snapshots + lineup_slots, once
    handle._build_id = "b-2"
    _axis(HOLDER, handle)
    assert handle.reads == 4


def test_the_card_never_waits_for_the_first_read(monkeypatch):
    started = []
    monkeypatch.setattr(mod.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: started.append(kw)})())
    handle = FakeHandle()
    assert strip_axis_for(HOLDER, dict(BOOTSTRAP), handle=handle, fetch_fixtures=lambda: FPL_FIXTURES) is None
    assert strip_axis_for(HOLDER, dict(BOOTSTRAP), handle=handle, fetch_fixtures=lambda: FPL_FIXTURES) is None
    assert len(started) == 1 and handle.reads == 0  # one build in flight, nothing read on the card's path
    started[0]["target"](*started[0]["args"])
    assert strip_axis_for(HOLDER, dict(BOOTSTRAP), handle=handle, fetch_fixtures=lambda: FPL_FIXTURES) == "defence"


def test_flag_off_missing_store_or_fixture_list_give_none(monkeypatch):
    class Broken:
        def build_id(self):
            raise FileNotFoundError("no pointer")

    assert _axis(HOLDER, Broken()) is None

    def boom():
        raise OSError("FPL unreachable")

    from fpl_grounded_assistant import position_changes_tool as pct
    monkeypatch.setattr(pct, "_fixture_cache", {"at": 0.0, "rows": None})
    assert strip_axis_for(HOLDER, dict(BOOTSTRAP), handle=FakeHandle(), fetch_fixtures=boom, background=False) is None
    assert mod._index["build_id"] is None  # not remembered: the next card tries again

    monkeypatch.delenv("FOOTBALL_INTELLIGENCE_ENABLED")
    assert _axis(HOLDER, FakeHandle()) is None


def test_the_snapshot_payload_carries_the_axis_to_the_card_meta(monkeypatch):
    import sys
    snap = sys.modules["fpl_grounded_assistant.get_player_snapshot"]  # the package re-exports the function by name
    monkeypatch.setattr(snap, "strip_axis_for", lambda element, bs: "defence")
    monkeypatch.setattr(snap, "_attach_zonal", lambda *a, **k: None)
    out = get_player_snapshot("Holder", dict(BOOTSTRAP))
    assert out["status"] == "ok" and out["player"]["strip_axis"] == "defence"
    meta = _extract_player_snapshot_meta(out)
    assert meta is not None and meta.strip_axis == "defence"


def test_the_meta_drops_anything_but_the_two_axes():
    out = {"status": "ok", "player": {"id": 1, "web_name": "X", "strip_axis": "midfield", "fixtures": []}}
    assert _extract_player_snapshot_meta(out).strip_axis is None
    out["player"].pop("strip_axis")
    assert _extract_player_snapshot_meta(out).strip_axis is None
