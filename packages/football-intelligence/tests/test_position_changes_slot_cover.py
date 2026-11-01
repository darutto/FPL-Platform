"""Who held a player's usual slot in the matches he did not start. Synthetic store only, no network."""
from __future__ import annotations

import pandas as pd

from football_intelligence.ingestion.licensed.store import TABLES
from football_intelligence.position_changes import OBSERVED, FixtureMeta, analyse

X, A, B, C, D = 10, 20, 30, 40, 50
NAMES = {el: {"web_name": n, "team_short": "CHE"} for el, n in {X: "Xavi", A: "Delap", B: "Nkunku", C: "Mate", D: "Dave"}.items()}
CF = ("Centre Forward", "centre")
LW = ("Left Midfield", "left")


def _frame(table, rows):
    return pd.DataFrame(rows, columns=list(TABLES[table][0])).astype(object)


class Store:
    def __init__(self):
        self.snapshots, self.slots, self.fixtures, self.n = [], [], {}, 0

    def match(self, starters, bench=(), formation="4-4-2"):
        """starters: [(element, (position, side), grid_slot)]. Absent elements are simply not listed."""
        self.n += 1
        fid, day = self.n, self.n
        self.fixtures[fid] = FixtureMeta(fid, f"2026-11-{day:02d}T15:00:00Z", "CHE" if fid % 2 else "EVE", "EVE" if fid % 2 else "CHE")
        obs = f"2026-11-{day:02d}T10:00:00Z"
        self.snapshots.append({"fixture_id": fid, "team": "CHE", "observed_at": obs, "state": "scheduled", "confirmed": True,
                               "formation": formation, "n_starters": len(starters), "n_bench": len(bench)})
        for el, role, slot in starters:
            self.slots.append({"fixture_id": fid, "team": "CHE", "observed_at": obs, "element": el, "starter": True,
                               "detailed_position": role[0], "grid_slot": slot, "side": role[1]})
        for el in bench:
            self.slots.append({"fixture_id": fid, "team": "CHE", "observed_at": obs, "element": el, "starter": False,
                               "detailed_position": None, "grid_slot": None, "side": None})

    def build(self, element=X, **kw):
        squad = [{"team": "CHE", "element": el, "jersey_number": 1, "observed_at": "2026-10-01T05:00:00Z"} for el in NAMES]
        return analyse(element=element, snapshots=_frame("lineup_snapshots", self.snapshots), slots=_frame("lineup_slots", self.slots),
                       sidelined=_frame("sidelined", []), squad_membership=_frame("squad_membership", squad),
                       fixtures=self.fixtures, names=NAMES, **kw)


def _occ(result):
    return {m["gameweek"]: [(o["player"]["web_name"], o["match"]) for o in m.get("slot_occupants", [])] for m in result["matches"]}


def test_the_usual_slot_is_filled_by_whoever_started_there_in_the_matches_without_him():
    s = Store()
    for _ in range(3):
        s.match([(X, CF, "4:1"), (C, LW, "3:1")])
    s.match([(A, CF, "4:1"), (C, LW, "3:1")], bench=[X])
    s.match([(A, CF, "4:1"), (C, LW, "3:1")])
    s.match([(B, CF, "4:1"), (C, LW, "3:1")])
    r = s.build()
    cover = r["slot_cover"]
    assert cover["status"] == "ok" and cover["usual_slot"] == {"detailed_position": "Centre Forward", "side": "centre"}
    assert cover["claim_status"] == OBSERVED and cover["matches_without"] == 3 and cover["small_sample"] is False
    assert [(o["player"]["web_name"], o["count"]) for o in cover["occupants"]] == [("Delap", 2), ("Nkunku", 1)]
    assert _occ(r)[4] == [("Delap", "exact")] and _occ(r)[1] == []


def test_a_partner_who_shared_the_role_with_him_does_not_count_as_taking_his_slot():
    s = Store()
    for _ in range(3):  # 4-4-2: two centre forwards, Delap always next to him
        s.match([(X, CF, "4:1"), (A, CF, "4:2")])
    s.match([(A, CF, "4:2"), (B, CF, "4:1")])  # without him: Delap stays, Nkunku comes in
    r = s.build()
    assert [n for n, _k in _occ(r)[4]] == ["Nkunku"]
    assert [o["player"]["web_name"] for o in r["slot_cover"]["occupants"]] == ["Nkunku"]
    assert r["slot_cover"]["small_sample"] is True and r["slot_cover"]["matches_without"] == 1


def test_when_only_the_old_partner_is_left_nobody_is_named_for_his_slot():
    s = Store()
    for _ in range(3):
        s.match([(X, CF, "4:1"), (A, CF, "4:2")])
    s.match([(A, CF, "4:2"), (C, LW, "3:1")])  # nobody else in his role; Delap is his old partner -> excluded
    r = s.build()
    assert _occ(r)[4] == []  # Mate's cell is half a pitch away (depth 0.5 vs 1.0), over LINE_STEP_MIN
    assert r["slot_cover"]["status"] == "ok" and r["slot_cover"]["occupants"] == []


def test_a_changed_formation_names_the_closest_cell_and_says_so():
    s = Store()
    for _ in range(3):
        s.match([(X, CF, "5:1"), (C, LW, "4:1")], formation="4-2-3-1")
    s.match([(D, ("Attacker", "centre"), "4:1"), (C, LW, "3:1")], bench=[X], formation="4-4-2")
    r = s.build()
    assert _occ(r)[4] == [("Dave", "closest")]
    assert r["slot_cover"]["closest_used"] is True


def test_nobody_is_named_when_nobody_is_close():
    s = Store()
    for _ in range(3):
        s.match([(X, CF, "4:1")], formation="4-4-2")
    s.match([(C, ("Centre Back", "centre"), "2:2")], bench=[X], formation="4-4-2")
    r = s.build()
    assert _occ(r)[4] == [] and r["slot_cover"]["occupants"] == [] and r["slot_cover"]["matches_covered"] == 0


def test_without_enough_starts_or_with_a_tie_no_usual_slot_is_claimed():
    s = Store()
    s.match([(X, CF, "4:1")])
    s.match([(A, CF, "4:1")], bench=[X])
    r = s.build()
    assert r["slot_cover"]["status"] == "no_usual_slot" and r["slot_cover"]["reason"] == "too_few_starts"
    assert all("slot_occupants" not in m for m in r["matches"])
    t = Store()
    t.match([(X, CF, "4:1")]); t.match([(X, LW, "3:1")]); t.match([(A, CF, "4:1")], bench=[X])
    assert t.build()["slot_cover"]["reason"] == "no_single_usual_role"


def test_no_slot_cover_when_he_started_every_match():
    s = Store()
    for _ in range(3):
        s.match([(X, CF, "4:1")])
    assert "slot_cover" not in s.build()


def test_not_listed_counts_like_bench():
    s = Store()
    for _ in range(3):
        s.match([(X, CF, "4:1")])
    s.match([(A, CF, "4:1")])
    assert s.build()["slot_cover"]["matches_without"] == 1
